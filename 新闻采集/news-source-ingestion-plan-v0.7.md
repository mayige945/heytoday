# 喂今天：新闻采集模块实施方案

- **文档版本**：V0.7
- **日期**：2026-07-13
- **状态**：服务器定时任务实施版
- **面向对象**：Codex / 开发人员 / 产品负责人
- **所属项目**：喂今天
- **适用节目**：喂今天

### V0.7 更新记录

- 生产持久化从本地 SQLite 改为 Supabase Postgres；采集文章、事件、来源健康、LLM 留痕、
  事实核验、策展和禁止重聚关系全部写入远端。
- 允许 cron 等外部调度器定时触发一次性 `run --json` 任务；任务完成即退出，不建设常驻服务。
- 重复采集以规范 URL 和同来源 GUID 数据库唯一约束兜底，并把新文章与完整历史非重复池比较；
  URL、标题、正文 SHA-256、SimHash 与事件聚类逻辑保留。
- Postgres advisory lock 防止多服务器任务重叠；stdout 输出含运行 ID、起止时间、退出码和各阶段统计。
- 增加 Dockerfile；生产必须配置 `SUPABASE_DB_URL`，SQLite 只允许显式测试夹具。

### V0.6 更新记录

- 新增 Supabase 新闻素材快照库：本地 SQLite 继续承担采集事务与运行状态，成功导出的
  `news-material/v1` 可由显式命令幂等同步到远端。
- 远端以 `content_sha256` 派生稳定 `sync_id`，保留不可变快照历史；只有完整写入且状态为
  `success` 的最新快照进入 `latest_news_material_events` 视图。
- Supabase 表启用 RLS，撤销 `public` / `anon` / `authenticated` 权限；写入只接受后端
  `SUPABASE_SECRET_KEY`（兼容旧 `SUPABASE_SERVICE_ROLE_KEY`），密钥不入仓库。
- 同步保持人工显式触发，不把远端可用性耦合进 `run` / `export`，不引入调度器。

### V0.5 更新记录

> 本版重定位采集模块的职责边界：**采集 = 「儿童新闻选题引擎的新闻采集底座」**，只产出
> 一个宽口径的「新闻素材库」，不做下游选题/写稿阶段才会做的把关。

- **采集阶段只保留一道硬过滤：红线**（图像化暴力、未成年人性化、自残方法、仇恨煽动、
  危险操作指引、极端主义等不可换角度的内容）。红线永不入素材库。
- **事实核验降级为提示标签**：`needs_fact_check` / `fact_check_targets` 不再是入池 gate，
  留给写稿阶段在真正对孩子说出来前核验。采集只标注「这则素材含哪些可核验点」。
- **取消小学高年级/初中的分档 gate 与家长档×年龄档六组合 eligibility 矩阵**：采集做成
  单一素材库，LLM 的两档年龄兴趣评估保留为**参考信息**，帮下游选题快速挑，但不 gate、
  不拆分导出。家长档×年龄档判定是**选题/写稿当天**（知道目标年龄与家长设置时）才做的决定。
- **敏感层降级为标签**：敏感话题（死亡/战争/灾难/犯罪/疾病/争议）可换角度再讲，进素材库
  并标注 `sensitive` + 可讲角度/注意事项；放不放进当期稿是下游选题决定。
- **导出契约由「按年龄档×家长档双格式六组合」改为「单一新闻素材库」**（schema
  `news-material/v1`）：一份 JSON + 一份 Markdown，含全部非红线、非重复、未被人工拒绝的
  事件，及其结构化参考标签（话题分类、评分、两档年龄兴趣、安全分级与理由、待核验点、儿童入口）。
- **人工复核由「六组合矩阵 + 事实核验闸门」简化为可选策展**：`reject` 把事件剔出素材库，
  `approve`/留空则保留；不再强制矩阵与核验 gate。

### V0.4 更新记录

- 明确双格式原子导出、家长档参数、空结果、时间戳命名和完整退出码。
- 明确 14 个采集单元对应 15 条来源记录，至少 3 条真实启用并覆盖 RSS、网页与 RSSHub；取消人工录入。
- 统一使用 uv、TOML 与标准库采集解析；SQLite 迁移、事务、崩溃恢复和留存策略闭环。
- 固定 Kimi Coding Anthropic 兼容接口、一级/二级 LLM Schema、降级与人工补录路径。
- 补齐事实核验硬闸门、人工 eligibility 矩阵、保守确定性聚类及唯一 `run` 状态机。

### V0.3 更新记录

- 将新闻采集确认为当前唯一工程化的独立模块；推荐、家长选择、写稿和音频仍按现有手工流程运行。
- 保留 14 个采集单元、网页/RSSHub、去重聚类与两级 LLM；取消定时调度，只允许人工触发 CLI。
- 锁定本地 Python + SQLite 运行路径和模块输出边界，新闻采集同时覆盖小学高年级和初中两档。
- 对齐内容安全三层、LLM 数据契约、状态枚举和章节编号。

---

## 1. 项目背景

喂今天是一档面向 9–15 岁孩子的每日新闻播客。新闻采集模块同时评估小学高年级和初中两档；当前下游日常写稿仍先跑小学高年级，初中稿在另行启动前继续保持手工流程待命。

节目每天选择一条真实新闻，通过“爸爸 + 孩子”的自然对话展开。节目不是新闻速报，也不是知识灌输，而是借助正在发生的社会与科技新闻，引发孩子对现实世界的兴趣、判断和思考。

本模块的目标不是建设一个传统新闻爬虫，而是建设：

> **儿童新闻选题引擎的新闻采集底座。**

系统需要持续发现：

- 孩子可能感兴趣的新闻；
- 具有故事性、冲突性或新奇性的事件；
- 能够引发亲子讨论的社会与科技话题；
- 具有多元视角，而非只有单一结论的新闻；
- 适合转化为音频对话的内容。

---

## 2. MVP目标

MVP阶段完成以下能力：

1. 维护一套可配置的新闻源库；
2. 支持 RSS、网页栏目抓取和 RSSHub；
3. 通过服务器外部调度器定时触发一次性 CLI，增量采集新增文章；
4. 统一文章基础字段；
5. 对文章进行去重；
6. 将相似文章聚合为新闻事件；
7. 记录来源、题材、采集状态和错误信息；
8. 使用LLM完成六类选题识别、儿童兴趣判断、故事性判断、讨论价值判断和音频适配判断；
9. 将LLM判断结果以结构化字段写入新闻事件；
10. 支持人工查看、修正，并确认事件是否进入合格新闻池；
11. 以 JSON 和 Markdown 导出**新闻素材库**（v0.5：单一素材库，不分年龄/家长档；仅排除红线），为后续手工选题提供宽口径素材输入。下游选题/写稿阶段再做家长档 × 年龄档判定与事实核验。

MVP阶段暂不要求：

- 自动生成完整播客稿；
- 自动决定当天最终选题；
- 完成复杂版权管理；
- 购买商业新闻API；
- 接入微博、公众号、Reuters、AP等第二批来源；
- 建设复杂的推荐算法。
- 自动生成 3 个候选或标记推荐；
- 代替家长确认当天最终选题；
- 后台常驻或实时抓取服务；调度由 cron 等外部设施负责；
- 自动写稿、自动生成音频或自动发布。

### 2.1 独立运行定义

本模块是根目录 `新闻采集/` 下可独立部署的 Python 项目：

- Python 3.12，统一使用 uv 管理 Python、虚拟环境与依赖；`pyproject.toml`、`uv.lock`、`.python-version` 必须提交；
- Supabase Postgres 为唯一生产事务数据库，SQLAlchemy 2.x + psycopg 3 + Alembic 管理模型和迁移；
- Typer 提供 `news-ingestion` CLI；
- 运行依赖固定为 Typer、SQLAlchemy、psycopg、Alembic、Anthropic Python SDK、jsonschema；测试依赖固定为 pytest；所有版本由 `uv.lock` 锁定；
- 每次运行由外部调度器发起，命令完成后退出；模块不内置调度器或常驻服务；
- 数据库存储在 Supabase；日志写 stdout/stderr，导出文件可写容器临时目录或挂载卷；
- LLM 固定使用 Kimi Coding 的 Anthropic 兼容接口与 `kimi-for-coding` 模型；程序读取 `ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY`，不把密钥写入仓库；
- 单次命令以本地进程锁 + Postgres advisory lock 防止同机及跨服务器重复运行，失败返回非零退出码并保留已成功提交的来源结果；
- `run` 按来源划分事务：每个来源的文章变更与对应 `fetch_log` 在同一事务中提交；单来源失败只回滚该来源，其它来源继续；
- 采集完成后的推荐、家长选择、写稿、TTS 和发布仍由项目现有手工流程完成。

---

## 3. 选题范围

系统需要覆盖六类选题。

### 3.1 奇异新发现

包括但不限于：

- 新物种；
- 深海探索；
- 太空任务；
- 恐龙与古生物；
- 考古发现；
- 动物异常行为；
- 自然界的新现象。

特点：

- 新奇；
- 有画面感；
- 容易形成故事；
- 儿童天然感兴趣。

### 3.2 科技进入生活

包括但不限于：

- AI；
- 机器人；
- 无人驾驶；
- 游戏与互联网；
- 新型设备；
- 航天技术；
- 科技改变学校、家庭或社会生活。

筛选重点不是产品参数，而是：

- 技术影响了谁；
- 带来了什么变化；
- 出现了什么新问题；
- 是否存在效率、公平、隐私或责任冲突。

### 3.3 青少年直接相关

包括但不限于：

- 学校与课堂；
- 手机使用；
- 社交平台；
- 游戏；
- 体育；
- 考试与作业；
- 校园规则；
- 青少年发明、行动与社会参与。

### 3.4 有冲突的社会小事件

包括但不限于：

- 居民与管理方的冲突；
- 消费者与平台的冲突；
- 便利与隐私的冲突；
- 动物保护与人类活动的冲突；
- 学校管理与学生自由的冲突；
- 科技效率与社会公平的冲突。

这类新闻需要保留多个合理立场，避免直接给出标准答案。

### 3.5 普通人的不普通经历

包括但不限于：

- 普通人解决现实问题；
- 孩子、家庭、社区的行动；
- 科研人员、消防员、快递员等职业故事；
- 小人物面对社会或科技变化作出的选择。

不要求人物必须成功，也不要求故事必须励志。

### 3.6 网络文化和流行现象

包括但不限于：

- 游戏；
- 网络梗；
- 热门视频；
- AI生成内容；
- 流行玩具；
- 社交平台现象；
- 突然爆火的文化事件。

此类来源主要用于发现热点，不能作为唯一事实来源。

---

## 4. 首批新闻源范围

MVP 采用 **14 个采集单元、15 条来源记录**。S01–S13 各对应一条来源记录；S14“热点雷达”由知乎热榜和 B 站热门两条来源记录组成，通过共同的 `unit_code: S14` 聚合统计和验收。

| 编号 | 采集单元 | 类型 | 主要覆盖选题 | 优先采集方式 | 角色 |
|---|---|---|---|---|---|
| S01 | 少年報導者 | 儿少/社会 | 青少年、普通人故事、社会议题 | 网页栏目抓取 | 精品选题源 |
| S02 | 果壳 | 中文科学 | 新发现、动物、科学解释 | RSS优先，网页正文补充 | 选题源/解释源 |
| S03 | 少数派 | 中文科技生活 | 科技进入生活、AI、数字文化 | 官方RSS + 正文抓取 | 选题源 |
| S04 | Solidot | 中文科技资讯 | 科技、互联网、科学动态 | 官方RSS | 线索源 |
| S05 | 极客公园 | 中文科技媒体 | AI、机器人、消费科技 | 网页栏目抓取 | 选题源 |
| S06 | 澎湃新闻 | 中文社会 | 社会、教育、城市、人物 | 指定栏目抓取 | 选题源/事实源 |
| S07 | 界面新闻 | 中文社会/商业生活 | 社会生活、消费、科技影响 | 指定栏目抓取 | 选题源 |
| S08 | NASA | 国际科学 | 太空、任务、天文发现 | 官方RSS | 原始事实源 |
| S09 | MIT News | 国际科技科学 | 发明、科研、工程、AI | 官方分类RSS | 原始事实源/解释源 |
| S10 | Smithsonian Magazine | 国际科学人文 | 动物、历史、考古、奇异发现 | 官方分类RSS | 选题源 |
| S11 | The Guardian | 国际综合 | 环境、动物、社会、科技 | 官方栏目RSS + 正文抓取 | 多元视角源 |
| S12 | BBC News | 国际综合 | 科技、科学、社会、教育 | 官方RSS | 事实源 |
| S13 | The Conversation | 学术解释 | 科学、教育、社会争议 | RSS优先，栏目抓取兜底 | 解释源/观点源 |
| S14 | 热点雷达 | 热点平台 | 社会热度、网络文化、青少年兴趣 | RSSHub或页面抓取 | 线索源 |

### 4.1 热点雷达子来源

| 子来源 | 用途 | 采集方式 | 是否可作为事实源 |
|---|---|---|---|
| 知乎热榜 | 发现社会讨论和问题型话题 | RSSHub或公开页面抓取 | 否 |
| B站热门 | 发现青少年关注内容和网络文化 | RSSHub或公开页面抓取 | 否 |

知乎热榜与 B 站热门分别使用独立的 `news_source.code`、抓取状态和错误记录，但共享 `unit_code: S14`。`fetch --all` 按 15 条启用来源执行；健康统计既输出来源记录维度，也按 `unit_code` 汇总为 14 个采集单元。

---

## 5. 第二批来源备注

以下来源暂不进入MVP，仅记录在后续批次：

- 微博热搜；
- 百度热搜；
- 新京报人物、社会栏目；
- 36氪；
- 中国国家地理相关内容；
- JPL；
- Smithsonian Insider；
- Reuters；
- AP News；
- 微信公众号人工精选源；
- 其他地方媒体、独立媒体和垂直社区。

第二批来源是否接入，依据第一阶段运行数据决定。

主要评估指标：

- 抓取稳定性；
- 有效文章率；
- 候选入选率；
- 最终成稿率；
- 事实可靠性；
- 重复率；
- 维护成本。

---

## 6. 采集方式设计

### 6.1 RSS

适用于：

- 少数派；
- Solidot；
- NASA；
- MIT News；
- Smithsonian Magazine；
- The Guardian；
- BBC News；
- The Conversation；
- 果壳，如能确认稳定Feed。

RSS的职责：

- 发现新增文章；
- 获取标题；
- 获取发布时间；
- 获取摘要；
- 获取原文链接；
- 获取作者和栏目等可选字段。

RSS不应默认承担完整正文存储。

MVP 使用 Python 标准库 `urllib.request` 拉取 Feed，使用 `xml.etree.ElementTree` 解析 RSS 2.0 与 Atom；不引入 `httpx`、`requests` 或 `feedparser`。命名空间、CDATA、缺失 guid、相对链接、无发布时间和空 Feed 必须用离线 fixture 覆盖。

固定流程：

```text
拉取RSS
→ 比较guid或canonical_url
→ 发现新增文章
→ 建立 article 元数据记录
→ 进入 URL/标题去重、规则预筛和一级 LLM
```

RSS `fetch` 阶段只发现并保存元数据，不抓取正文。正文抓取只对一级结果为 `relevant` 或 `uncertain` 的非重复文章执行；一级调用失败或缺少凭据时按 `uncertain` 处理并继续抓正文。

### 6.2 网页栏目抓取

适用于：

- 少年報導者；
- 极客公园；
- 澎湃新闻；
- 界面新闻；
- RSS不稳定的果壳和The Conversation。

要求：

- 不抓整个网站；
- 只抓指定栏目；
- 栏目列表页与正文页解析器分离；
- 页面规则通过配置维护；
- 页面改版不能影响其他来源。

MVP 使用 `urllib.request` 发起请求，使用 `html.parser.HTMLParser` 构建来源特定的列表页与正文页解析器；不引入 `selectolax`、BeautifulSoup、readability 或 trafilatura。通用正文清洗只负责移除脚本、样式、导航、广告和重复空白；来源特定选择规则放在独立 parser/config 中。若标准库无法在不绕过访问控制的前提下稳定解析某来源，则按来源禁用规则处理，不为单个来源引入浏览器自动化。

### 6.3 RSSHub

适用于：

- 知乎热榜；
- B站热门；
- 其他无官方RSS但存在RSSHub路由的平台。

要求：

- RSSHub只作为适配层；
- 需要记录具体route；
- 通过 `RSSHUB_BASE_URL` 支持自建 RSSHub 地址；未配置时使用配置文件中明确登记并核验的公网 RSSHub；
- RSSHub失败不能阻塞其他来源；
- 热点内容只进入线索库；
- 线索必须通过正式媒体或原始材料核验。

人工或家长临时发现的材料不录入本模块数据库，继续直接进入下游手工选题流程。

### 6.4 外部来源访问约束

每条来源在启用前必须核验并记录 robots.txt、公开服务条款或官方使用说明。采集器必须：

- 使用可配置的明确 User-Agent，并提供项目标识；
- 遵守来源配置的单主机并发数、请求间隔、超时和 `Retry-After`；
- 只访问公开 HTTP/HTTPS 内容，不登录、不绕过验证码、付费墙、反爬或访问控制；
- 除 `RSSHUB_BASE_URL` 显式指向 `localhost`、`127.0.0.1` 或 `::1` 外，禁止请求或重定向到私网、环回、链路本地、组播和云元数据地址；每次重定向后必须重新解析并校验目标 IP；
- 禁止 `file:`、`data:`、`ftp:` 等非 HTTP(S) 协议，以及 URL 中携带用户名或密码；
- 限制重定向次数、响应体大小和允许的内容类型；
- 来源明确禁止、需要登录、长期不稳定或无法确认许可时，将其设为 `disabled`，记录原因、核验日期和证据 URL；
- 禁用来源保留在 14 个采集单元/15 条来源记录清单中，不阻塞 MVP 验收，但不得产生采集成功记录。

---

## 7. 总体架构

```text
新闻源库
   ↓
人工触发 CLI
   ├── RSS采集器
   ├── 网页栏目采集器
   └── RSSHub采集器
   ↓
原始文章库
   ↓
URL/标题规则去重
   ↓
传统规则预筛
   ↓
一级 LLM 轻量识别（失败时保留并继续抓正文）
   ↓
正文抓取、清洗与内容去重
   ↓
新闻事件聚类（单篇文章也形成事件）
   ↓
二级 LLM 完整识别与结构化评分
   ↓
JSON Schema 校验 + 内容安全规则兜底
   ↓
人工复核、修正并确认合格新闻池
   ↓
导出 JSON / Markdown
   ↓
现有手工流程：3 个候选 + 1 个推荐 → 家长拍板 → 写稿 → 音频
```

上图是唯一权威执行顺序。`fetch` 只完成来源发现和文章元数据写入；`run` 必须严格按图推进，不得先聚类再做一级识别。首次接入 Feed 发现的历史条目仍写入文章表并参与后续去重；一级识别同时检查发现时间与新闻发布时间，发布时间早于 `--since` 窗口的条目直接标记为规则无关，不调用 LLM。缺失发布时间的条目继续进入正常识别，避免误丢新闻。

---


## 8. LLM新闻识别与评分

### 8.1 定位

LLM不参与底层抓取，也不替代URL清洗、正文解析、去重和基础安全规则。

LLM负责传统规则难以稳定完成的语义判断：

- 新闻属于六类选题中的哪一类；
- 小学高年级和初中学生是否可能感兴趣；两档分别输出适配结论，不共用一个模糊总分；
- 是否有明确人物、行动、变化或冲突；
- 是否存在两个以上合理立场；
- 是否具有知识增量；
- 是否与学校、家庭、网络生活相关；
- 是否过度说教或只有单一标准结论；
- 是否严重依赖图片或视频；
- 是否适合转化为双人播客；
- 是否需要额外事实核验；
- 是否存在未成年人、暴力、性、自杀等高风险内容。

唯一处理顺序以上一节总体架构为准。一级识别位于正文抓取前，二级识别位于事件聚类后；本节不再定义另一条流程。

### 8.2 LLM输入

LLM应以“新闻事件”为主要识别对象，不应对所有重复转载文章分别调用。

MVP 输入结构固定为：

```yaml
event_title:
representative_article:
  title:
  summary:
  content_excerpt:
  source:
  published_at:
related_articles:
  - title:
    source:
    summary:
trend_signals:
  platform:
  rank:
  heat:
```

正文输入原则：

- 优先使用清洗后的正文；
- 正文过长时截取前部、关键段落和结尾；
- 多来源事件可提供2—4个来源的摘要；
- 热点平台内容必须标记为“线索源”；
- 单次输入需要控制token成本。

### 8.3 LLM结构化输出

LLM必须输出可校验JSON，不接受只有自然语言结论。

MVP 输出结构固定为：

```json
{
  "topic_categories": [
    "technology_in_life",
    "youth"
  ],
  "primary_category": "technology_in_life",
  "age_assessments": {
    "upper_primary": {
      "child_interest_score": 82,
      "age_fit": "fit",
      "reason": "与学校生活直接相关"
    },
    "junior_high": {
      "child_interest_score": 88,
      "age_fit": "fit",
      "reason": "可讨论效率、公平与责任"
    }
  },
  "story_score": 68,
  "discussion_score": 91,
  "knowledge_gain_score": 76,
  "life_relevance_score": 88,
  "value_pluralism_score": 85,
  "audio_fit_score": 75,
  "safety_tier": "default",
  "safety_tags": [],
  "safety_reason": "未命中红线或敏感层",
  "safety_uncertain": false,
  "safety_assessments": {
    "upper_primary": {
      "conservative": "eligible",
      "standard": "eligible",
      "open": "eligible"
    },
    "junior_high": {
      "conservative": "eligible",
      "standard": "eligible",
      "open": "eligible"
    }
  },
  "needs_fact_check": true,
  "fact_check_targets": [
    "确认事件发生时间",
    "确认平台官方规则"
  ],
  "key_people": [
    "学生",
    "学校管理者"
  ],
  "key_conflicts": [
    "效率与公平",
    "学校管理与学生自由"
  ],
  "child_hook": "如果AI能帮你完成作业，它到底是在帮助你，还是替你学习？",
  "reason": "事件与学生生活直接相关，存在明确冲突，并适合通过父子对话展开。"
}
```

### 8.4 分数字段

每个评分字段必须为 0—100 的整数。

| 字段 | 含义 |
|---|---|
| age_assessments.*.child_interest_score | 对应年龄档是否愿意继续听 |
| story_score | 是否有人物、行动、变化和过程 |
| discussion_score | 是否适合形成讨论 |
| knowledge_gain_score | 是否能自然带来新知识 |
| life_relevance_score | 是否和学生生活接近 |
| value_pluralism_score | 是否存在多个合理立场 |
| audio_fit_score | 是否脱离图片后仍能讲清楚 |

### 8.5 传统规则与LLM边界

以下任务优先使用传统规则：

- URL规范化；
- HTML清洗；
- guid去重；
- 标题hash；
- 正文SimHash；
- 发布时间提取；
- 来源分类；
- 明确红线词与敏感信号初筛（关键词只负责召回，不能单独把敏感话题判成红线）；
- 采集失败重试；
- 数据格式校验。

以下任务优先使用LLM：

- 六类选题分类；
- 故事性判断；
- 儿童兴趣判断；
- 讨论价值判断；
- 多元视角判断；
- 音频适配判断；
- 说教化判断；
- 事实核验点提取；
- 统一事件摘要生成。

### 8.6 调用策略

MVP阶段不应对每篇原始文章都调用LLM。

MVP 固定分两级调用：

#### 一级轻量识别

输入标题、摘要、来源和栏目。

用途：

- 排除明显无关内容；
- 初步分类；
- 判断是否值得抓取完整正文；
- 控制调用成本。

一级输出必须通过 `news_relevance.schema.json` 校验：

```json
{
  "schema_version": "news-relevance/v1",
  "relevance": "relevant",
  "topic_categories": ["technology_in_life"],
  "reason": "与学生日常使用 AI 的情境直接相关"
}
```

`relevance` 只允许 `relevant`、`irrelevant`、`uncertain`。`irrelevant` 停止正文抓取和后续聚类；`relevant`、`uncertain` 继续。调用失败、缺少凭据或 Schema 修复失败均物化为 `uncertain`，同时保留真实 `llm_run.status`，不得伪记为成功。

#### 二级完整识别

输入清洗后的正文和同事件多来源摘要。

用途：

- 完整评分；
- 提取冲突和人物；
- 判断音频适配性；
- 形成候选新闻卡片。

完整识别触发条件：

- 通过传统规则初筛；
- 非重复文章；
- 已形成新闻事件，包括只有一篇文章的独立事件；
- 一级识别未明确判为无关。一级识别不使用分数阈值决定 `eligible`，只允许标记 `relevant`、`irrelevant` 或 `uncertain`；`uncertain` 继续进入完整识别和人工复核。

### 8.7 LLM失败处理

LLM不是采集链路的强依赖。

要求：

- LLM调用失败时保留文章或事件记录；
- 状态统一标记为 `pending` 或 `failed`；
- 支持后续重试；
- 不阻塞其他新闻事件；
- 保存模型名、Prompt版本和调用时间；
- 保存原始返回，便于问题追踪；
- JSON不合法时执行一次修复重试；
- 多次失败后进入人工处理队列。

一级识别失败时默认继续抓取正文，并将记录保留为 `pending`；二级识别失败时事件不得进入自动导出的合格新闻池，人工可复核后放行。

### 8.8 Prompt版本管理

Prompt需要独立版本化，不应硬编码在业务代码中。

固定目录：

```text
prompts/
├── news_relevance_v1.md
├── news_scoring_v1.md
├── risk_review_v1.md
└── schemas/
    ├── news_relevance.schema.json
    └── news_scoring.schema.json
```

每次LLM识别结果应记录：

```yaml
model_provider:
model_name:
prompt_name:
prompt_version:
schema_version:
input_hash:
requested_at:
completed_at:
token_usage:
estimated_cost:
```

### 8.9 人工复核

人工复核通过 CLI 完成，必须支持：

- 修改选题分类；
- 调整各项评分；
- 标记不适合儿童；
- 标记事实有疑问；
- 合并或拆分新闻事件；
- 确认进入合格新闻池；
- 记录拒绝原因；

这里的“候选池”统一称为“合格新闻池”。本模块不得生成当天 3 个候选、标记推荐或确认最终选题；这些动作属于下游 Cognitive 与家长人工闸，当前继续手工完成。

### 8.10 MVP实现优先级

LLM能力按以下顺序实现：

1. 六类选题分类；
2. 儿童兴趣判断；
3. 风险等级判断；
4. 故事性和讨论性评分；
5. 音频适配评分；
6. 事实核验点提取；
7. 多来源统一摘要；
8. 后续再增加个性化和历史反馈学习。


## 9. 数据模型

### 9.1 新闻源表 `news_source`

MVP 字段固定为：

```yaml
id: string
unit_code: string
code: string
name: string
homepage_url: string
language: string
country_or_region: string

source_category:
  - child_news
  - science
  - technology
  - society
  - international
  - academic_explainer
  - trend_radar

source_role:
  - topic_source
  - fact_source
  - explainer_source
  - viewpoint_source
  - lead_source

acquisition_method:
  - rss
  - webpage
  - rsshub

feed_url: string | null
list_page_urls: array
rsshub_route: string | null

enabled: boolean
priority: integer
access_review_status: verified | prohibited | uncertain
access_reviewed_at: datetime | null
access_evidence_url: string | null
disabled_reason: string | null
request_interval_seconds: number
max_concurrency_per_host: integer
timeout_seconds: integer
max_redirects: integer
max_response_bytes: integer
allowed_content_types: array

topic_tags: array
allowed_sections: array
excluded_sections: array
excluded_keywords: array

requires_fulltext_fetch: boolean
requires_fact_check: boolean
commercial_use_note: string | null

last_fetch_at: datetime | null
last_success_at: datetime | null
consecutive_failures: integer
last_error: string | null

created_at: datetime
updated_at: datetime
```

### 9.2 原始文章表 `news_article`

```yaml
id: string
source_id: string

external_id: string | null
guid: string | null
url: string
canonical_url: string | null

title: string
subtitle: string | null
summary: string | null
content_raw: text | null
content_clean: text | null

author: string | null
section: string | null
published_at: datetime | null
discovered_at: datetime
fetched_at: datetime | null

language: string
image_urls: array
tags: array

content_hash: string | null
title_hash: string | null

fetch_status:
  - discovered
  - fetched
  - parsed
  - failed
  - skipped

relevance_status: pending | relevant | irrelevant | uncertain
relevance_reason: string | null
relevance_prompt_version: string | null
relevance_processed_at: datetime | null

duplicate_of: string | null
event_id: string | null

created_at: datetime
updated_at: datetime
```

一级识别每次调用仍完整记录在 `llm_run`；`news_article.relevance_*` 只物化最新一次 Schema 校验成功的结果，失败降级时物化 `uncertain`。Prompt 升版后，`classify --mode light --stale` 重跑旧版本结果；新的成功结果可以把此前 `irrelevant` 的文章改为 `relevant/uncertain` 并重新进入正文抓取，历史 `llm_run` 不覆盖。

正文留存规则：`content_raw` 自 `fetched_at` 起保留 7 天，`content_clean` 保留 30 天；到期后清空正文列，但长期保留标题、摘要、URL、来源、hash、事件关联和其它元数据。留存清理由人工执行 CLI；采集进程不内置调度器，服务器可另行配置外部 cron。

### 9.3 新闻事件表 `news_event`

相似文章应聚合为同一新闻事件。

```yaml
id: string
event_title: string
event_summary: string | null

topic_categories: array
primary_category:
  - discovery
  - technology_in_life
  - youth
  - social_conflict
  - ordinary_people
  - internet_culture

article_ids: array
source_count: integer
language_count: integer

first_published_at: datetime | null
latest_published_at: datetime | null

heat_score: number | null
age_assessments: json
story_score: number | null
discussion_score: number | null
knowledge_gain_score: number | null
life_relevance_score: number | null
value_pluralism_score: number | null
audio_fit_score: number | null
safety_tier:
  - redline
  - sensitive
  - default
  - uncertain
safety_tags: array
safety_reason: string | null
safety_uncertain: boolean
safety_assessments: json
needs_fact_check: boolean
fact_check_targets: array
key_people: array
key_conflicts: array
child_hook: string | null
llm_reason: string | null

llm_status:
  - pending
  - success
  - failed
  - skipped

llm_model: string | null
prompt_version: string | null
llm_processed_at: datetime | null

status:
  - new
  - rejected
  - needs_review
  - archived

created_at: datetime
updated_at: datetime
```

### 9.4 LLM 调用表 `llm_run`

每次一级或二级调用单独留痕，`news_event` 只保存当前已校验通过的结果：

```yaml
id: string
article_id: string | null
event_id: string | null
mode: light | full
model_provider: string
model_name: string
prompt_name: string
prompt_version: string
schema_version: string
input_hash: string
raw_response: text | null
parsed_result: json | null
status: pending | success | failed
requested_at: datetime
completed_at: datetime | null
token_usage: json | null
estimated_cost: number | null
error_message: string | null
```

`raw_response`、LLM 脱敏错误和文件运行日志保留 30 天；到期后由 `retention prune` 清理。`parsed_result`、provider、model、Prompt/Schema 版本、input hash、token/cost 与调用状态长期保留。持久化前必须移除 API Key、Authorization/x-api-key 请求头、Cookie 和其它凭据；错误文本设置长度上限。

### 9.5 采集日志表 `fetch_log`

```yaml
id: string
source_id: string
started_at: datetime
finished_at: datetime | null

status:
  - running
  - success
  - partial_success
  - failed

items_found: integer
items_created: integer
items_updated: integer
items_skipped: integer
errors_count: integer

error_message: string | null
metadata: json
```

### 9.6 事实核验表 `fact_check_record`

```yaml
id: string
event_id: string
status: pending | verified | failed
conclusion: string | null
evidence_sources:
  - url: string
    source_name: string
    source_role: fact_source | original_source
    checked_at: datetime
checker: string | null
created_at: datetime
updated_at: datetime
```

当 `needs_fact_check=true` 时，表示这则素材含可核验的具体声明（数字、时间、规则、专家断言等），
**仅作为写稿阶段的提示标签**，不再是入素材库的 gate（v0.5）。「核验」是写稿/播出前在真正对孩子
说出来时做的事；采集只标注「这则素材有哪些可核验点」。`fact_check_record` 仍可由人工随时记录
核验结论与证据（`status` ∈ pending/verified/failed），供下游参考，**但不影响事件是否进入素材库**。
热点雷达来源仍始终设置 `needs_fact_check=true`，提醒其只作线索、须经正式媒体核验后再用于稿。
`checker` 取自 CLI `--reviewer`，未传时读取 `NEWS_REVIEWER`；两者都缺失或空白时拒绝写入核验记录。

### 9.7 人工复核表 `event_review`

```yaml
id: string
event_id: string
review_status: pending | approved | rejected
reviewer: string
eligibility:
  upper_primary:
    conservative: eligible | ineligible
    standard: eligible | ineligible
    open: eligible | ineligible
  junior_high:
    conservative: eligible | ineligible
    standard: eligible | ineligible
    open: eligible | ineligible
category_override: json | null
score_overrides: json | null
safety_override: json | null
age_assessments_override: json | null
content_overrides:
  title: string | null
  summary: string | null
  child_hook: string | null
  safety_reason: string | null
rejection_reason: string | null
note: string | null
reviewed_at: datetime | null
created_at: datetime
updated_at: datetime
```

`reviewer` 必须取自 CLI `--reviewer`，未传时读取 `NEWS_REVIEWER`；两者都缺失或空白时拒绝写入。
v0.5 起，**人工复核是可选策展，不是入素材库的 gate**：

- 事件**默认进入素材库**（只要非红线、非重复）。`review_status` 留空 / `approved` 都表示保留在库；
  `rejected` 表示人工把该事件剔出素材库（不再被导出）。
- **取消六组合 eligibility 矩阵与 `needs_fact_check` 核验闸门**：家长档 × 年龄档判定下移到选题/
  写稿阶段；事实核验是写稿阶段的事（见 §9.6）。采集阶段不再要求复核人填矩阵或先核验。
- `score_overrides` / `category_override` / `age_assessments_override` / `content_overrides` 仍可由
  复核人修正 LLM 结果，作为**参考标签的订正**（非 gate）。
- `safety_override` 只允许把事件判得更严（如把 default 升为 sensitive、或把 uncertain 解除为明确
  分级），**红线永不可放宽**。
- 每次复核保留新记录，不覆盖历史复核。

### 9.8 新闻素材库导出契约（v0.5）

采集模块导出**一个**「新闻素材库」（不再是按年龄档×家长档的六组合合格新闻池）。每次导出
原子化生成同名 JSON 与 Markdown，文件名 `YYYYMMDD_HHmmss_news_material.json/.md`，Asia/Shanghai
时间，UTF-8，不覆盖历史文件；先写临时文件，双格式都过 Schema 校验后一起改名，任一失败删临时
文件。JSON 顶层结构（schema `news-material/v1`）：

```yaml
schema_version: news-material/v1
generated_at: datetime
result: populated | empty
events:
  - event_id: string
    title: string
    summary: string
    primary_category: string
    topic_categories: array
    child_hook: string
    age_assessments:            # 两档年龄兴趣，参考信息（非 gate）
      upper_primary: {child_interest_score, age_fit, reason}
      junior_high:   {child_interest_score, age_fit, reason}
    scores:                     # story/discussion/knowledge_gain/life_relevance/value_pluralism/audio_fit
    safety_tier: sensitive | default | uncertain   # 红线不在此列（永不导出）
    safety_tags: array
    safety_reason: string
    needs_fact_check: boolean   # 提示标签：写稿前需核验
    fact_check_targets: array
    source_count: integer
    sources:
      - name: string
        role: string
        url: string
        published_at: datetime | null
    human_review:               # 可选；留空表示未人工策展
      status: approved | rejected | null
      reviewed_at: datetime
      reviewer: string
      note: string | null
```

**入选规则**：导出**全部**「非红线、非重复、未被人工 `rejected`」的事件，**不再按年龄档/家长档
筛选、不要求 fact-check verified、不要求 approved**。`sensitive` / `uncertain` / `needs_fact_check=true`
的事件都进素材库，仅作为**标签**提示下游注意。**红线是唯一被排除的安全分级**（永不导出）。
Markdown 是同一 JSON 的人读视图；`output/INDEX.md` 与 `latest_*.json/.md` 提供人读索引。

导出前对整个文件做 `news-material/v1` Schema 校验；任何事件不合规则整次导出失败（退出码 8），
不覆盖上一份成功文件。导出文件**不写入 `稿子/`**，下游选题/写稿流程自行读取并在那时做家长档×
年龄档判定与事实核验。无任何事件时生成 `result: empty`、`events: []` 的合法双格式，退出码 0。

### 9.9 Supabase 新闻素材快照

`uv run news-ingestion supabase sync` 默认读取 `output/latest_news_material.json`，也可用
`--input` 指定历史导出。同步前必须通过 `news-material/v1` Schema 校验；历史导出中的
非有限浮点值统一转为合法 JSON `null`。完整文档的规范 JSON SHA-256 决定稳定 `sync_id`，
同一内容重复同步只执行幂等 upsert。

远端表为 `news_material_sync_runs` 与 `news_material_events`；前者记录快照状态与摘要，
后者保存便于查询的展开字段和完整事件 `payload`。事件分批写入，全部成功后快照才标记
`success`；失败标记 `failed`，最新视图只读取最新成功快照。Supabase 运行表是采集事实源；
本地双格式导出只是可移交产物，不承担运行状态持久化。

---

## 10. 去重与聚类要求

### 10.1 URL去重

优先顺序：

1. canonical URL；
2. RSS guid；
3. 清洗后的URL；
4. 原始URL。

URL清洗应去除：

- utm参数；
- 渠道参数；
- 分享参数；
- 无意义锚点；
- 可识别的追踪参数。

### 10.2 标题去重

处理：

- 去除媒体后缀；
- 去除重复标点；
- 统一全角半角；
- 统一大小写；
- 计算标题指纹。

### 10.3 内容去重

MVP固定采用：

```text
URL规范化
+ 标题归一化
+ 完整正文SHA-256（精确重复）
+ 正文SimHash（近似重复，汉明距离默认 ≤ 3，阈值可配置）
```

正文为空或清洗后少于 200 个中文字符时不做 SimHash 自动合并，只保留 URL/标题结果并标记人工复核。任何自动合并都保留 `duplicate_of` 和判定依据，可由人工撤销。

### 10.4 事件聚类

同一事件的不同媒体文章需要聚合。

MVP 固定采用标题关键词、发布时间窗口和关键实体重合度进行保守的确定性聚类，不使用 embedding、外部向量服务或中文分词库。关键词和实体提取规则固定如下：

- 标题先做 Unicode NFKC、大小写归一、标点/媒体后缀清理；
- 中文关键词使用去停用字后的连续二元字组，拉丁文本使用 `re` 提取小写字母数字 token；
- 关键实体只来自来源结构化标签、`filters.toml` 的别名词典、书名号/引号片段、连续拉丁专名和带编号的任务/型号；
- 实体全部经过 `filters.toml` 别名归一；无法可靠提取实体时不自动合并。

只有以下条件全部满足才自动合并：

- 落在对应题材的时间窗口内；
- 归一化标题关键词 Jaccard 相似度 `>= 0.60`；
- 命名实体 overlap coefficient `>= 0.80`；
- 至少共享一个非通用的关键实体（具体人物、机构、地点、作品、任务或事件名）。

任一条件不满足就保持为独立事件，并进入人工可合并列表，不进行“可能相似”的自动合并。阈值写入 `filters.toml`，默认值由测试锁定；调整阈值属于配置变更，必须同步增加或更新“应合并/不应合并”夹具。

```text
标题关键词
+ 发布时间窗口
+ 实体重合度
```

聚类时间窗口固定为：

- 普通热点：72小时；
- 持续事件：7天；
- 科学发现与深度解释：30天。

单篇文章也必须创建独立事件。人工拆分后的事件写入禁止重聚关系，后续重复运行不得再次自动合并。测试夹具至少包含 10 组“应合并/不应合并”样本，覆盖空正文、短标题、跨语言和持续事件。

---

## 11. 内容安全与初步过滤规则

### 11.1 安全判定（v0.5：采集只挡红线）

本模块对齐 `../Content_Safety_Policy_v0.1.md` 的三层 + uncertain，但 **v0.5 起采集阶段只对红线
做硬过滤**；家长档 × 年龄档的「能不能讲、怎么讲」判定下移到选题/写稿阶段（那时才知道目标年龄
与家长设置）。采集阶段的处理：

- `redline`：**唯一被硬过滤的安全分级**，永不进入素材库、永不导出（不可换角度的伤害内容）。
- `sensitive`：进素材库并标注 `sensitive` + 可讲角度/注意事项；放不放进当期稿、按哪档家长×年龄讲，
  是下游选题决定。
- `default`：进素材库，常规素材。
- `uncertain`：进素材库并标注 `uncertain`（LLM 对安全分级拿不准），提示下游人工留意；不自动判红。

LLM 给出的两档 `age_assessments`（小学高年级/初中兴趣分）保留为**参考信息**，帮下游快速挑，
不作为 gate、也不拆分导出。关键词只用于召回风险信号，不能单独完成最终安全分类；规则红线召回
（`safety.py`）命中只把事件标 `uncertain` 交下游，**永不自动判红、永不放宽**。

### 11.2 红线（直接过滤）

包括：

- 图像化或细节化的暴力、血腥、酷刑、虐待；
- 任何性内容、性暗示或未成年人性化；
- 自杀、自残的方法、过程或美化；
- 针对受保护群体的仇恨与歧视煽动；
- 危险行为的可操作指引；
- 极端主义或恐怖主义的宣传、美化；
- 无法核验的谣言；
- 纯营销软文；
- 只有标题、无有效事实的信息。

其中“无法核验、营销、无有效事实”属于数据质量淘汰，不属于产品红线；实现中必须分别记录原因。

### 11.3 敏感层与降权

死亡、战争、灾难、犯罪、疾病和政治/社会争议默认进入敏感判定，不因出现主题词直接过滤；必须记录可讲角度、风险提示和两个年龄档的放行结果。

包括：

- 纯政策通稿；
- 纯公司融资；
- 单纯新品参数；
- 明星八卦；
- 饭圈内容；
- 重复转载；
- 标题党；
- 严重依赖图片或视频才能理解；
- 只有结论、没有人物和过程；
- 明显说教式报道。

### 11.4 提升权重

包括：

- 有明确人物；
- 有行动过程；
- 有意外或变化；
- 有两个以上合理立场；
- 与学校、家庭、网络生活相关；
- 有动物、太空、AI、机器人、考古等兴趣元素；
- 能够自然解释一个新概念；
- 不依赖视觉也能讲清楚。

---

## 12. 来源配置示例

```toml
[[sources]]
unit_code = "S08"
code = "nasa"
name = "NASA"
homepage_url = "https://www.nasa.gov/"
language = "en"
source_category = "science"
source_role = ["topic_source", "fact_source"]
acquisition_method = "rss"
feed_url = "<实施时从官方页面核验并写入；未核验不得启用>"
enabled = false
priority = 90
topic_tags = ["space", "astronomy", "exploration"]
requires_fulltext_fetch = true
requires_fact_check = false

[[sources]]
unit_code = "S03"
code = "sspai"
name = "少数派"
homepage_url = "https://sspai.com/"
language = "zh-CN"
source_category = "technology"
source_role = ["topic_source"]
acquisition_method = "rss"
feed_url = "<实施时从官方页面核验并写入；未核验不得启用>"
enabled = false
priority = 80
topic_tags = ["ai", "digital_life", "technology"]
requires_fulltext_fetch = true
requires_fact_check = true

[[sources]]
unit_code = "S14"
code = "trend_radar_zhihu"
name = "知乎热榜"
homepage_url = "https://www.zhihu.com/"
language = "zh-CN"
source_category = "trend_radar"
source_role = ["lead_source"]
acquisition_method = "rsshub"
rsshub_route = "<实施时核验可用路由并写入；未核验不得启用>"
enabled = false
priority = 70
requires_fulltext_fetch = false
requires_fact_check = true

[[sources]]
unit_code = "S14"
code = "trend_radar_bilibili"
name = "B站热门"
homepage_url = "https://www.bilibili.com/"
language = "zh-CN"
source_category = "trend_radar"
source_role = ["lead_source"]
acquisition_method = "rsshub"
rsshub_route = "<实施时核验可用路由并写入；未核验不得启用>"
enabled = false
priority = 70
requires_fulltext_fetch = false
requires_fact_check = true
```

所有实际 Feed 地址和栏目 URL 应放在配置文件中，不应硬编码进采集器。示例默认 `enabled: false`；只有 URL/route 与访问约束全部核验完成后才可启用。

---

## 13. 目录结构

```text
新闻采集/
├── README.md
├── pyproject.toml
├── uv.lock
├── .python-version
├── config/
│   ├── sources.toml
│   ├── filters.toml
│   └── logging.toml
├── src/
│   └── news_ingestion/
│       ├── collectors/
│       │   ├── base.py
│       │   ├── rss.py
│       │   ├── webpage.py
│       │   └── rsshub.py
│       ├── parsers/
│       │   ├── generic_article.py
│       │   └── sources/
│       ├── cleaners/
│       │   ├── url.py
│       │   ├── html.py
│       │   └── text.py
│       ├── dedup/
│       │   ├── url_dedup.py
│       │   ├── title_dedup.py
│       │   └── content_dedup.py
│       ├── clustering/
│       │   └── event_cluster.py
│       ├── models/
│       ├── repositories/
│       ├── services/
│       └── cli.py
├── tests/
│   ├── fixtures/
│   ├── test_rss_collector.py
│   ├── test_webpage_collector.py
│   ├── test_dedup.py
│   └── test_source_configs.py
├── migrations/
├── data/              # 数据库与进程锁，忽略提交
├── logs/              # 运行日志，忽略提交
└── output/            # 合格新闻池 JSON/Markdown，按需留档
```

---

## 14. Codex 实施任务拆分

### 阶段一：采集框架

- [ ] 创建项目骨架；
- [ ] 执行 `uv python pin 3.12`，创建 `pyproject.toml`，通过 `uv add` 添加依赖并提交最新 `uv.lock`；
- [ ] 定义统一Collector接口；
- [ ] 实现RSS Collector；
- [ ] 实现网页栏目Collector基础接口；
- [ ] 实现RSSHub Collector；
- [ ] 使用 Python 3.12 标准库 `tomllib` 加载并校验 TOML 配置；
- [ ] 实现采集日志。
- [ ] 采集与解析层使用 `urllib.request`、`xml.etree.ElementTree`、`html.parser`；不得引入 requests/httpx/feedparser/BeautifulSoup/selectolax/readability/trafilatura 或浏览器自动化；
- [ ] 使用 dataclass + 显式校验函数把 TOML 转为类型化配置；未知字段、重复 `code`、非法枚举、缺失必填字段和 `enabled=true` 但访问核验未通过时返回退出码 `2`；

### 阶段二：数据存储

- [ ] 建立 `news_source`；
- [ ] 建立 `news_article`；
- [ ] 建立 `news_event`；
- [ ] 建立 `fetch_log`；
- [ ] 建立数据库迁移；
- [ ] 实现Repository层。

采集运行数据库锁定 Supabase Postgres。八张运行表启用 RLS，撤销 PUBLIC / anon / authenticated
权限；`service_role` 仅用于后端管理访问。数组与结构化结果以 JSON 字段保存；时间字段使用
`timestamptz`。生产入口没有 `SUPABASE_DB_URL` 或收到 SQLite URL 时必须拒绝运行。

### 阶段三：正文和清洗

- [ ] 实现正文抓取；
- [ ] HTML转纯文本；
- [ ] 删除导航、广告、推荐阅读等噪声；
- [ ] 处理编码；
- [ ] 规范化URL；
- [ ] 生成内容hash。

### 阶段四：去重与聚类

- [ ] URL去重；
- [ ] 标题归一化；
- [ ] 正文SimHash；
- [ ] 初步事件聚类；
- [ ] 将文章绑定至新闻事件。

### 阶段五：来源接入

来源接入顺序固定为：

1. NASA；
2. MIT News；
3. Smithsonian Magazine；
4. 少数派；
5. Solidot；
6. BBC；
7. The Guardian；
8. The Conversation；
9. 果壳；
10. 少年報導者；
11. 极客公园；
12. 澎湃；
13. 界面；
14. 知乎热榜和B站热门。

先接结构稳定的官方RSS，再接网页抓取源。

### 阶段六：LLM识别服务

- [ ] 定义LLM结构化输出Schema；
- [ ] 实现一级轻量识别；
- [ ] 实现二级完整识别；
- [ ] 实现Prompt文件化和版本管理；
- [ ] 实现JSON Schema校验；
- [ ] 实现调用失败重试；
- [ ] 实现调用日志与成本记录；
- [ ] 将识别结果写入 `news_event`；
- [ ] 提供人工修正接口或CLI；
- [ ] 为典型六类选题准备测试样本。

### 阶段七：CLI 运行和观测

- [ ] 完整手动 CLI 入口与退出码；
- [ ] 进程锁，禁止同一工作区重复运行；
- [ ] 单来源失败隔离；
- [ ] 重试机制；
- [ ] 超时机制；
- [ ] 失败汇总输出；
- [ ] 来源健康状态；
- [ ] 每日采集统计；
- [ ] 支持手动触发单个来源。

---

## 15. CLI 契约

```bash
# 批量执行：元数据采集 → URL/标题去重与规则预筛 → 一级识别 → 正文抓取/内容去重 → 聚类 → 二级评分；停在人工复核队列
uv run news-ingestion run --json

# 查看所有来源
uv run news-ingestion source list

# 初始化或升级数据库
uv run news-ingestion db upgrade

# 查看数据库迁移状态
uv run news-ingestion db status

# 测试来源配置
uv run news-ingestion source validate nasa

# 抓取单一来源
uv run news-ingestion fetch nasa

# 抓取全部启用来源
uv run news-ingestion fetch --all

# 仅抓取热点雷达
uv run news-ingestion fetch --category trend_radar

# 查看最近失败
uv run news-ingestion fetch-log --status failed

# 按留存策略清理到期正文
uv run news-ingestion retention prune

# 重新抓取某篇文章
uv run news-ingestion article refetch <article-id>

# 执行去重
uv run news-ingestion dedup --since 24h

# 执行事件聚类
uv run news-ingestion cluster --since 72h

# 执行LLM轻量识别
uv run news-ingestion classify --since 24h --mode light

# 执行LLM完整评分
uv run news-ingestion score --event <event-id> --mode full

# 重试LLM失败任务
uv run news-ingestion llm retry --status failed

# 人工修正或确认事件进入合格新闻池
uv run news-ingestion review event <event-id> [--reviewer <name>]

# 查看待复核事件
uv run news-ingestion event list --review-status pending

# 记录事件的事实核验结论与证据
uv run news-ingestion fact-check event <event-id> [--reviewer <name>]

# 导出单一新闻素材库；每次同时生成 JSON 与 Markdown
uv run news-ingestion export

# 将最新（或指定）JSON 素材库幂等同步到 Supabase
uv run news-ingestion supabase sync
uv run news-ingestion supabase sync --input output/<历史文件>.json
```

采集运行要求 `SUPABASE_DB_URL`；可选素材快照同步另要求 `SUPABASE_URL` 与 `SUPABASE_SECRET_KEY`；旧项目可临时使用
`SUPABASE_SERVICE_ROLE_KEY`。新式 `sb_secret_...` 只放 `apikey` 请求头，不作为 Bearer JWT。

`run` 是日常默认入口，严格按“元数据采集 → URL/标题去重与规则预筛 → 一级识别 → 正文抓取与内容去重 → 事件聚类 → 二级完整评分”执行，完成后停在人工复核队列。单阶段命令保留用于诊断和重跑。`run` 不得自动批准、自动导出或调用下游流程；没有配置 LLM 凭据时，一级按 `uncertain` 降级并继续正文抓取，二级保持 `pending`。

数据库初始化和升级只能通过 `uv run news-ingestion db upgrade` 显式执行。其它命令启动时检查 Alembic revision；数据库未初始化或落后于 `head` 时返回退出码 `6`，不得自动迁移。生产连接必须启用 TLS。

每个来源使用独立数据库事务。来源成功时文章变更和 `fetch_log=success|partial_success` 一起提交；来源失败时回滚该来源的文章变更，并单独写入脱敏后的 `fetch_log=failed`。进程异常退出后，下次运行把超过配置时限仍为 `running` 的日志标为 `failed`（原因 `stale_run_recovered`），清理失效进程锁后再继续。最终 CLI 摘要列出成功、部分成功、失败、禁用和跳过来源。

服务器定时任务与后续人工流程的顺序为：

```text
uv run news-ingestion run --json
→ uv run news-ingestion event list --review-status pending
→ 必要时完成 fact-check
→ 逐事件 review
→ 按年龄档与家长档 export
```

`retention prune` 使用 Asia/Shanghai 计算到期日，默认执行实际清理，并提供 `--dry-run` 预览数量；重复执行必须幂等。它清空到期正文、删除超过 30 天的文件运行日志，并清空超过 30 天的 LLM 原始响应与脱敏错误；不删除文章、事件、来源、结构化 LLM 结果、事实核验或人工复核记录。

CLI 退出码固定如下：

| 退出码 | 含义 |
|---:|---|
| `0` | 成功；包括合法的空导出 |
| `2` | 参数或配置校验失败 |
| `3` | 本次所有启用外部来源均失败 |
| `4` | 部分成功；成功来源已提交，至少一个启用来源失败 |
| `5` | 进程锁冲突，已有实例运行 |
| `6` | 数据库连接、迁移或事务基础设施失败 |
| `7` | 显式 LLM 命令或 `run` 需要 LLM，但凭据未配置；非 LLM 阶段已完成的数据保留 |
| `8` | 人工批准或导出 Schema 校验失败 |
| `9` | 访问策略拒绝、事实核验闸门或其它业务前置条件未满足 |

部分成功必须提交成功来源的数据并在摘要中列出失败来源。任何非零退出都不得删除此前已成功提交的数据。CLI 不调用下游写稿或音频流程。

---

## 16. 验收标准

### 16.1 新闻源管理

- [ ] 干净检出后执行 `uv sync --locked` 成功，`uv.lock` 与 `pyproject.toml` 一致，`.python-version` 固定为 3.12；
- [ ] 空数据目录执行 `uv run news-ingestion db upgrade` 可初始化到 `head`；重复执行幂等；旧 revision 可升级且数据保留；其它命令面对落后 revision 时返回 `6`；
- [ ] 14 个采集单元、15 条来源记录均存在配置；S14 恰好包含知乎热榜和 B 站热门两条记录；
- [ ] 可以单独启用和停用；
- [ ] 每个来源包含 URL/route、允许栏目、采集方式、robots/条款核验状态、限速说明、核验日期和证据；可访问来源必须完成 live smoke，禁止或不确定来源必须禁用并记录原因；
- [ ] 至少 3 条来源记录真实启用并完成端到端 live smoke，且 RSS、网页栏目、RSSHub 各至少 1 条；其余来源可按证据禁用；
- [ ] 若 0 条来源启用，`fetch --all` 和 `run` 返回退出码 `2`，提示配置不满足最低运行条件；
- [ ] 可以查看最后成功时间；
- [ ] 可以查看连续失败次数。

### 16.2 采集

- [ ] RSS源能增量抓取；
- [ ] 网页源只抓配置栏目；
- [ ] 重复执行不会重复创建文章；
- [ ] RSSHub失败不会影响其他源；
- [ ] 只有 `RSSHUB_BASE_URL` 可显式使用 localhost；其它来源和重定向访问私网、链路本地或云元数据地址时必须拒绝并记录；
- [ ] 文章保留原始URL和来源信息。

### 16.3 数据质量

- [ ] 标题、URL、来源、发现时间不能为空；
- [ ] 正文抓取失败时文章仍可保留；
- [ ] `retention prune --dry-run` 可预览到期正文；实际执行后原始 HTML 超过 7 天、清洗正文超过 30 天被清空，其它元数据保持不变；
- [ ] 超过 30 天的文件运行日志被删除，LLM 原始响应和脱敏错误被清空，结构化结果与版本元数据保留；
- [ ] URL追踪参数能够清理；
- [ ] 完全重复文章能够识别；
- [ ] 同一事件的多篇文章可初步聚合。
- [ ] 缺少任一导出必填字段的事件不能批准；失败提示列出具体字段；
- [ ] 导出 Schema 校验失败时不产生半成品，也不覆盖上一份成功文件；
- [ ] 无合格事件时生成 `result: empty` 的合法双格式文件并返回 `0`；

### 16.4 LLM识别

- [ ] 能对新闻事件输出六类选题分类；
- [ ] `news_relevance.schema.json` 覆盖一级 `relevant|irrelevant|uncertain`，最新成功结果正确物化到文章并驱动正文抓取状态；
- [ ] 输出符合JSON Schema；
- [ ] 各评分字段范围为0—100；
- [ ] 能分别输出小学高年级与初中适配结果、三层安全判定和事实核验点；
- [ ] `needs_fact_check=true` 的事件未记录 `verified` 结论与至少一个证据 URL 前不能批准或导出；
- [ ] LLM失败不影响采集链路；
- [ ] 支持保存模型和Prompt版本；
- [ ] 支持人工修正LLM结果；
- [ ] 相同输入在同一Prompt版本下可追踪结果。
- [ ] 无 Kimi 凭据时，fake client 的一级/二级契约测试和 `run` 降级路径必须通过，`run` 返回 `7` 且非 LLM 数据保留；这部分是无条件验收；
- [ ] 用户提供 `ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY` 时运行一次 opt-in Kimi live smoke，验证 `kimi-for-coding` 的 Anthropic 兼容响应；没有凭据不阻塞代码层 MVP 完成，但运行交付记录必须标明“live Kimi 未验证”。

### 16.5 稳定性

- [ ] 单一来源异常不会导致整个任务失败；
- [ ] 网络超时可重试；
- [ ] HTML结构异常有日志；
- [ ] 每次采集有完整统计；
- [ ] 单来源失败只回滚该来源，其它来源结果正常提交；崩溃后的 stale `running` 日志和失效进程锁可在下次运行恢复；
- [ ] 支持服务器外部调度器定时运行，且项目中不存在内置调度器或常驻服务；
- [ ] `uv run news-ingestion run` 按唯一权威顺序批量推进至人工复核队列，且不会自动批准或导出；
- [ ] 断网、429、超时、畸形 RSS、空 Feed、HTML 结构异常和 LLM 非法 JSON 均有离线 fixture 覆盖；
- [ ] 端到端离线测试不依赖真实网站或真实 LLM，live smoke test 单独运行；来源 URL、robots/条款和 live smoke 验收依赖实施时可用网络与当时站点政策，并在运行记录中写明核验日期；
- [ ] 测试统一通过 `uv run pytest` 执行；默认测试禁止真实网络，live smoke 必须显式标记并单独运行；

---

## 17. MVP 运行评估

模块完成后由服务器定时运行，至少连续观察两周，再决定是否扩大或替换来源。

每个来源记录以下指标：

```yaml
articles_collected_14d:
valid_articles_14d:
duplicate_rate:
fetch_success_rate:
candidate_count:
candidate_rate:
eligible_upper_primary_count:
eligible_junior_high_count:
downstream_candidate_count:
downstream_selected_count:
downstream_final_script_count:
maintenance_incidents:
```

重点关注：

1. 哪些来源提供的新闻最多；
2. 哪些来源有效新闻比例最高；
3. 哪些来源最容易进入候选前10；
4. 哪些来源最终能形成播客稿；
5. 哪些来源重复率高但价值低；
6. 哪些来源维护成本过高；
7. 六类选题是否出现明显缺口。

---

## 18. 关键产品原则

1. **热点源只发现话题，不确认事实。**
2. **同一事件尽量保留多个来源。**
3. **不以媒体是否官方作为唯一筛选标准。**
4. **优先选择有故事、有人物、有变化的新闻。**
5. **保留多种合理立场，不强制制造标准答案。**
6. **新闻必须适合音频表达，不能严重依赖图片。**
7. **首批范围锁定 14 个采集单元；接入顺序追求逐个稳定和可评估，不在此范围之外继续堆来源数量。**
8. **所有来源配置化，禁止在代码中硬编码。**
9. **新闻源库是长期资产，需要持续记录来源表现。**
10. **后续扩展由数据决定，而非凭感觉增加媒体。**

---

## 19. Codex 执行指令

请根据本文档实施儿童新闻选题引擎的新闻采集MVP。

执行要求：

1. 按本文已锁定的技术设计和任务顺序直接实施，不再重复产出设计稿；
2. 所有新闻源通过配置文件维护；
3. 采用统一Collector接口；
4. 优先完成RSS采集闭环；
5. 再逐步接入网页抓取和RSSHub；
6. 每接入一个来源，必须增加测试样本；
7. 不将具体页面规则散落在业务代码中；
8. 对失败、超时、解析异常和重复采集进行处理；
9. 提供本地运行说明；
10. 提供数据库初始化和迁移说明；
11. 实现LLM新闻识别服务，包含轻量分类和完整评分；
12. 所有LLM输出必须经过JSON Schema校验；
13. LLM调用失败不得阻塞新闻采集；
14. 提供至少一个可重复的离线端到端演示，外部来源和 Kimi 均使用 fixture/fake client：
    - 从新闻源配置；
    - 拉取RSS；
    - 保存文章；
    - 抓取正文；
    - URL去重；
    - 写入采集日志；
    - 形成新闻事件；
    - 调用LLM完成分类与评分；
    - 保存结构化识别结果。

本文已锁定 MVP 技术选型、系统边界、数据模型、来源顺序和降级原则。Codex 应按阶段顺序直接实施，不再停下来重复提交技术设计。只有以下情况才暂停找用户确认：需要新增付费服务、必须改动新闻采集目录之外的运行代码，或目标站的访问政策需要产品负责人决定是否替换来源。目标站明确禁止采集时按既定规则禁用，不必暂停；LLM 凭据缺失时按既定降级继续，也不必暂停。

LLM 固定使用 Kimi Coding 的 Anthropic 兼容协议：

```yaml
provider: kimi_coding_anthropic
base_url_env: ANTHROPIC_BASE_URL
api_key_env: ANTHROPIC_API_KEY
expected_base_url: https://api.kimi.com/coding/
model: kimi-for-coding
```

该接口只用于当前作者本人、本地运行的个人 MVP，不作为对外产品或商业运行的长期接口。客户端必须保留 Anthropic SDK 的真实身份标识，不修改或伪装 User-Agent。遇到会员额度、用途限制、服务拒绝或策略变化时按 LLM 失败降级，不尝试绕过。开始服务外部家庭、团队共享或商业运行前，必须把 LLM 接口迁移到适用于产品集成的正式 API，并更新本方案与 README。

环境变量值由用户在运行环境中录入，不写入 `.env`、配置文件、日志、异常文本或数据库。`ANTHROPIC_BASE_URL` 与 `ANTHROPIC_API_KEY` 任一缺失或空白时，`classify` / `score` 返回明确的“未配置”状态，事件保持 `pending`；采集、清洗、去重和聚类仍成功运行。测试使用本地 fake Anthropic client，不调用真实服务。

请求只向 HTTPS 的 `https://api.kimi.com/coding/` 发送；不得记录 API Key、Authorization/x-api-key 请求头或完整请求头。超时、429 和 5xx 可重试，429 必须遵守 `Retry-After`；401、403 和其它确定性 4xx 不重试。所有重试次数、超时和最终状态写入配置与 `llm_run`，但错误信息必须脱敏。
