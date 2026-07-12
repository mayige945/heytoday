# CLAUDE.md（新闻采集）

本文件是 `新闻采集/` 目录内 AI agent 的唯一项目级约束入口，与父级 `/home/heytoday/CLAUDE.md` 配套。父级的 uv 铁律、产品宪法七条、全文中文与术语约定在此全部继承并生效；二者冲突以父级为准。本文件只补充本模块特有的形状与硬约束。

这是「喂今天」当前**唯一获准独立工程化**的子模块（PRD 引擎 *Content Intelligence* 层）。它把 RSS、网页栏目、RSSHub 材料处理成**「新闻素材库」**（v0.5：宽口径素材池，带结构化参考标签，**采集阶段只硬过滤红线**），停在可选人工策展队列；家长档 × 年龄档判定、事实核验、候选推荐、家长选题、写稿、TTS、音频评估、发布仍走主线手工流程（在选题/写稿时做）。

## 唯一真理源指针

- `news-source-ingestion-plan-v0.5.md` 是本模块当前唯一实施方案（v0.5：采集=「新闻素材库底座」，只硬过滤红线；事实核验/家长档×年龄档/敏感放行全部下移到选题与写稿阶段）。数据契约、采集约束、退出码、验收标准、实施顺序**一律以它为准，不得凭记忆改写**。`v0.4.md` 已归档。
- 做实质性修订时，同步升版文件名（v0.5…）、文档版本号与日期，并更新本目录 `README.md` 的指针——参照父 CLAUDE.md 的编辑约定。
- 本文件不定义产品边界或安全判定逻辑：产品边界看 `../PRD_v0.8.md`，安全判定看 `../Content_Safety_Policy_v0.1.md`。

## 当前状态（先看这条）

**MVP 代码已实现（plan §14 七阶段全部落地），`uv run pytest` 全绿。** 目录已含 `pyproject.toml`、`uv.lock`、`.python-version`（3.12）、`src/news_ingestion/`、`migrations/`、`tests/`、`config/`、`prompts/`。

- 下文 `uv run news-ingestion …` CLI 命令均已可运行；先 `uv sync --locked`，再 `uv run news-ingestion db upgrade` 初始化到 head。
- 15 条来源记录默认全部 `enabled=false`、`access_review_status=uncertain`；启用前必须按 plan §16.1 完成 robots/条款核验 + live smoke（至少 3 条，RSS/网页/RSSHub 各 ≥1）——这部分依赖运行时网络与当时站点政策，需操作者现场核验并在运行记录中写明核验日期。
- **无条件验收**是离线端到端（`tests/test_pipeline_e2e.py`，fake 采集器 + fake Anthropic client）与 `run` 无凭据降级路径，均已通过；真实 Kimi live smoke 需用户提供 `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` 后单独运行，未验证时运行记录须标明「live Kimi 未验证」。
- 仍可运行 Kimi 连接冒烟测试（见「如何运行与测试」）。

## 模块边界：负责 / 不负责

**本模块负责**：维护并接入首批 14 个采集单元 / 15 条来源记录；RSS、网页栏目、RSSHub 三类采集；正文清洗；URL/标题/内容去重与新闻事件聚类；两级 LLM 分类与结构化评分（话题/评分/两档年龄兴趣/安全分级/待核验点/儿童入口，均作**参考标签**）；采集阶段对齐 `../Content_Safety_Policy_v0.1.md` 但**只硬过滤红线**（敏感/uncertain 作标签入库）；导出 JSON + Markdown **新闻素材库**。

**本模块不负责**：后台常驻、定时调度或自动抓取；生成 3 候选、标 1 推荐；替家长确认最终选题；**家长档 × 年龄档判定与事实核验**（这些在下游选题/写稿时做）；写稿、TTS、音频评估或发布。人工或家长临时发现的材料**不录入本模块数据库**，直接走下游手工选题。CLI 不调用下游写稿或音频流程，不写 `稿子/` 目录。采集之后仍进入现有手工流程：新闻素材库 → 手工出 3 候选标 1 推荐（此时做家长档×年龄档判定与事实核验）→ 家长拍板 → 写稿 → 音频。

## 技术栈与依赖管理（uv 铁律）

锁定栈：**Python 3.12 + uv + SQLite（唯一 DB）+ SQLAlchemy 2.x + Alembic + Typer CLI**（CLI 名 `news-ingestion`）。运行依赖固定 Typer / SQLAlchemy / Alembic / Anthropic Python SDK / jsonschema；测试依赖固定 pytest，用 `uv run pytest`。

重申父 CLAUDE.md 的 uv 铁律：以 `pyproject.toml` + `uv.lock` 为依赖事实源，二者必须提交；`uv python pin 3.12` 固定版本（`.python-version` 必须为 3.12）；用 `uv add / uv remove` 改依赖、`uv sync` 同步、`uv run` 执行；**禁** `pip install`、`python -m venv`、Poetry、Pipenv、Conda 建第二套环境，不直接编辑锁文件，不直接调 `.venv` 的 Python。

LLM 固定 **Kimi Coding 的 Anthropic 兼容接口**，模型 **`kimi-for-coding`**（`expected_base_url = https://api.kimi.com/coding/`，`anthropic-version: 2023-06-01`，端点 `v1/messages`）。客户端必须保留 Anthropic SDK 的真实身份，**不伪装 User-Agent、不绕过额度/用途限制/服务拒绝**；遇到限制按 LLM 失败降级。此约束针对生产 LLM 客户端（Anthropic Python SDK）；`测试Kimi连接.py` 是仅用标准库 `urllib` 的手工连通性冒烟探测，自带 User-Agent，不在此约束内。该接口仅限作者本地个人 MVP；扩展到外部家庭、团队共享或商业运行前必须迁移正式产品 API，并更新方案与 README。

采集与解析层**只用标准库**：`urllib.request` + `xml.etree.ElementTree`（RSS 2.0/Atom）+ `html.parser.HTMLParser` + `tomllib`（TOML）。**禁引入** requests / httpx / feedparser / BeautifulSoup / selectolax / readability / trafilatura，**禁**浏览器自动化；标准库无法在不绕过访问控制前提下稳定解析某来源时，按来源禁用规则处理，不为单来源引浏览器。

## 如何运行与测试

### Kimi 连接冒烟测试（当前唯一可跑）

1. 在本目录 `.env` 录入 `ANTHROPIC_API_KEY` 与 `ANTHROPIC_BASE_URL`（`.env` 已由根 `.gitignore` 忽略）。`ANTHROPIC_BASE_URL` 的规范值为 `https://api.kimi.com/coding/`（plan §19 要求生产客户端只发 HTTPS 到此地址）；`.env` 实际值以本地为准，当前可能指向作者内网代理（明文 HTTP），冒烟脚本会对明文 HTTP 打印警告——这种 HTTP 代理仅供本地冒烟，**不要**把它「修正」回 `api.kimi.com` 而破坏本地连通。
2. 运行 `uv run python ./测试Kimi连接.py`。成功打印实际模型与短回复；**无 key 或 `ANTHROPIC_BASE_URL` 非合法 HTTP(S) 返回 2，连接失败（HTTP/URL/超时/JSON）返回 1，成功返回 0**；脚本不打印 API Key。

### CLI 契约命令（已实现）

```bash
uv python pin 3.12
uv sync --locked
uv run news-ingestion db upgrade          # 显式迁移；落后 head 返回退出码 6，不自动迁移
uv run news-ingestion db status
uv run news-ingestion run                 # 日常默认入口；跑完停在人工复核队列；未配置 LLM 凭据返回退出码 7，非 LLM 阶段数据保留、一级降级 uncertain、二级保持 pending
uv run news-ingestion source list
uv run news-ingestion source validate <code>
uv run news-ingestion fetch --all         # 按 15 条启用来源采集；0 条启用返回退出码 2；fetch 只写元数据，不抓正文
uv run news-ingestion fetch <code>
uv run news-ingestion fetch --category trend_radar   # 仅抓热点雷达（知乎热榜 + B 站热门）
uv run news-ingestion article refetch <article-id>   # 重新抓取单篇文章正文
uv run news-ingestion fetch-log --status failed
uv run news-ingestion dedup --since 24h
uv run news-ingestion cluster --since 72h
uv run news-ingestion classify --since 24h --mode light      # 一级轻量识别
uv run news-ingestion classify --mode light --stale          # Prompt 升版后重评旧 irrelevant
uv run news-ingestion score --event <id> --mode full         # 二级完整评分
uv run news-ingestion llm retry --status failed
uv run news-ingestion event list --review-status pending
uv run news-ingestion review event <id> [--reviewer <name>]
uv run news-ingestion fact-check event <id> [--reviewer <name>]
uv run news-ingestion export               # v0.5：导出单一新闻素材库（不分年龄/家长档）
uv run news-ingestion retention prune     # 幂等，Asia/Shanghai，默认实清，提供 --dry-run
uv run pytest                             # 默认禁真实网络；live smoke 需显式标记并单独跑
```

- 本块为常用子集，完整 CLI 见 plan §15。
- v0.5 起 `export` 不再带 `--age` / `--parent-mode`：素材库单一导出，家长档 × 年龄档判定下移到选题/写稿。
- `review` / `fact-check` 为可选策展与标注（不再是入池/导出 gate）。
- `--since` 默认：dedup=24h、cluster=72h、classify=24h。
- 单阶段命令（fetch/dedup/cluster/classify/score）保留用于诊断和重跑；`run` 不得自动批准、自动导出或调用下游流程。

### 凭据规则

`ANTHROPIC_BASE_URL` 与 `ANTHROPIC_API_KEY` 由用户在本目录 `.env` 录入（另有 `RSSHUB_BASE_URL` 支持自建 RSSHub）；`ANTHROPIC_BASE_URL` 规范值为 `https://api.kimi.com/coding/`，明文 HTTP 代理仅供本地冒烟，生产客户端只发 HTTPS。**密钥不许写入** `.env` 之外的配置、日志、异常、数据库或仓库；持久化 `llm_run` 前必须移除 API Key、Authorization/x-api-key 头、Cookie，错误文本设长度上限。两个 LLM 环境变量任一缺失或空白时，`classify`/`score` 返回「未配置」、事件保持 `pending`，采集/清洗/去重/聚类仍成功。

## 架构与数据流

**唯一权威执行顺序**（plan §7）：源库 → 人工触发 CLI → 采集 → 原始文章库 → URL/标题去重与规则预筛 → 一级 LLM → 正文抓取与内容去重 → 事件聚类 → 二级 LLM → JSON Schema 校验 + 安全兜底 → 人工复核 → 导出。`fetch` 只发现并写元数据；`run` 严格按图推进，**不许先聚类再做一级识别**。

**采集（14 单元 / 15 条来源记录）。** 首批固定 14 个采集单元（unit_code S01–S14）、15 条来源记录：S01–S13 各一条；S14「热点雷达」由知乎热榜 + B 站热门两条记录组成、共享 `unit_code=S14`，只作线索源、不作事实源（始终 `needs_fact_check=true`）。健康统计同时输出记录维度（15）与单元维度（14）。三类采集方式：

- **RSS**（`urllib.request` 拉 Feed + `xml.etree.ElementTree` 解析 RSS 2.0/Atom）：拉 Feed → 比 guid/canonical_url → 建元数据。
- **网页栏目**（`html.parser.HTMLParser` 写来源特定解析器）：列表页与正文页解析器分离、规则走配置、只抓指定栏目不抓全站；页面改版不影响其它来源。
- **RSSHub**（仅作适配层）：记具体 route，经 `RSSHUB_BASE_URL` 支持自建地址，失败不阻塞其它来源，热点只进线索库且必须经正式媒体核验。

**外部访问硬约束。** 启用每条来源前必须核验并记录 robots.txt / 服务条款 / 官方使用说明，存核验日期与证据 URL；用可配置的明确 User-Agent 并带项目标识；守单主机并发、请求间隔、超时、`Retry-After`；限制重定向次数、响应体大小、允许的 content-type。**SSRF**：除 `RSSHUB_BASE_URL` 显式指向 `localhost`/`127.0.0.1`/`::1` 外，禁止请求或重定向到私网/环回/链路本地/组播/云元数据地址，每次重定向后必须重新解析并校验目标 IP。**协议**：只访问公开 HTTP/HTTPS，不登录、不绕验证码/付费墙/反爬/访问控制；禁 `file:`/`data:`/`ftp:` 及 URL 携带用户名密码。禁用来源（明确禁止/需登录/长期不稳定/无法确认许可）保留在 14 单元清单中、不阻塞验收、记录原因/核验日期/证据，但**不得产生采集成功记录**。

**去重与聚类。** URL 去重优先序：canonical URL → RSS guid → 清洗后 URL（去 utm/渠道/分享/追踪参数与无意义锚点）→ 原始 URL。标题去重：去媒体后缀与重复标点、统一全半角与大小写、算标题指纹。内容去重：精确正文 SHA-256 + 近似正文 SimHash（汉明距离默认 ≤3，阈值可配置）；正文为空或清洗后 <200 中文字符不做 SimHash 自动合并，只保留 URL/标题结果并标人工复核；任何自动合并保留 `duplicate_of` 与判定依据，可人工撤销。事件聚类保守确定性，标题关键词 + 发布时间窗口 + 关键实体重合度，**不用 embedding/外部向量服务/中文分词库**。自动合并需四条件全满足：① 落在题材时间窗口内（普通热点 72h / 持续事件 7 天 / 科学发现与深度解释 30 天）② 归一化标题关键词 Jaccard ≥0.60 ③ 命名实体 overlap coefficient ≥0.80 ④ 共享至少一个非通用关键实体。任一不满足 → 独立事件，**不做"可能相似"合并**；单篇文章也必须建独立事件；人工拆分后写入禁止重聚关系。阈值写 `config/filters.toml`，调整属配置变更，必须同步增/更新"应合并/不应合并"测试夹具（≥10 组）。

**两级 LLM 识别与评分。** 一级（`mode=light`）：输入标题+摘要+来源+栏目，输出 `relevance` ∈ relevant/irrelevant/uncertain（schema `news-relevance/v1`）。`irrelevant` 停止抓正文与聚类；`relevant`/`uncertain` 继续。一级**不用分数阈值决定 eligible**。二级（`mode=full`）：输入清洗正文+同事件多来源摘要，输出完整结构化评分（7 个分数字段均为 0–100 整数）+ 六类选题分类 + 两档年龄适配 + 安全分级 + 事实核验点 + 候选卡片；**必须输出可校验 JSON，不接受只有自然语言结论**。LLM 只做语义判断；URL 清洗、正文解析、去重、基础安全规则、发布时间提取、来源分类、格式校验走传统规则；关键词只负责召回，**不能单独把敏感话题判成红线、不能单独完成最终安全分类**。Prompt 独立版本化、不硬编码进业务代码：`prompts/news_relevance_v1.md`、`news_scoring_v1.md`、`risk_review_v1.md` + `prompts/schemas/news_relevance.schema.json`、`news_scoring.schema.json`；每次调用记 model_provider/model_name/prompt_name/prompt_version/schema_version/input_hash/token_usage/estimated_cost。失败只做一次 JSON 修复重试；失败/缺凭据/Schema 修复失败**物化 uncertain 并保留真实 `llm_run.status`，不许伪记成功**。

**数据模型**（plan §9，七张表）：`news_source`、`news_article`、`news_event`、`llm_run`、`fetch_log`、`fact_check_record`、`event_review`。数组与结构化结果**统一以 JSON 字段保存**，不用 PostgreSQL 专属数组类型。SQLite 文件默认 `data/news_ingestion.sqlite3`，连接启用 foreign keys + WAL + 配置化 busy timeout。`db upgrade` 只能显式执行，落后 head 返回退出码 6、不自动迁移。每来源用独立事务，单来源失败只回滚该来源；非零退出不得删除此前已成功提交的数据。关键枚举：`safety_tier` = redline/sensitive/default/uncertain；`primary_category` = discovery/technology_in_life/youth/social_conflict/ordinary_people/internet_culture；`acquisition_method` = rss/webpage/rsshub；`access_review_status` = verified/prohibited/uncertain。

**新闻素材库导出契约**（plan §9.8，schema `news-material/v1`，v0.5）：每次导出**同时、原子化生成同名 JSON 与 Markdown**（`YYYYMMDD_HHmmss_news_material.json/.md`），不提供单格式选项（Markdown 是 JSON 的人读视图）。先写临时文件，双格式都过 Schema 校验后一起改名；任一失败删临时文件、**不覆盖上一份成功文件**。Asia/Shanghai 时间，UTF-8，保留历史不覆盖；导出文件**不得写入 `稿子/`**，下游选题/写稿自行读取并在那时做家长档×年龄档判定与事实核验。**入选**：全部非红线、非重复、未被人工 `rejected` 的事件，及其参考标签（话题/评分/两档年龄兴趣/安全分级/待核验点/儿童入口）；**红线是唯一被排除的安全分级**（sensitive/uncertain 作标签入库）。`output/INDEX.md` + `latest_news_material.*` 提供人读索引。无事件时生成 `result: empty`、`events: []` 的合法双格式，退出码 0，**不补凑新闻**。

## 必守硬约束（违反即让模块失效）

1. **采集阶段只硬过滤红线；家长档 × 年龄档判定下移到选题/写稿**（v0.5）。对齐 `../Content_Safety_Policy_v0.1.md` 的 redline/sensitive/default + uncertain：**红线是采集阶段唯一被排除的安全分级**（不可换角度的伤害内容，永不入素材库、永不导出）；`sensitive`/`uncertain` 进素材库并作为**标签**提示下游，不 gate。LLM 的两档年龄兴趣评估是**参考信息**，不拆分导出、不作 gate。关键词只召回风险，**不许单独判红、不许单独完成最终安全分类**；`safety_override` 只许更严或补证据解除 uncertain，**红线永不可放宽**。
2. **入素材库不需矩阵与事实核验 gate**（v0.5）：事件默认进素材库（非红线、非重复即可）。**取消 upper_primary/junior_high × conservative/standard/open 六组合 eligibility 矩阵**（那是选题当天、知道目标年龄与家长设置时才做的判定）；**`needs_fact_check` / `fact_check_targets` 降级为写稿阶段的提示标签**，不再是入池/导出 gate。人工复核是**可选策展**：`reject` 把事件剔出素材库，`approve`/留空则保留。`reviewer`/`checker` 仍必须取自 `--reviewer` 或 `NEWS_REVIEWER`，缺失/空白拒绝写入。每次复核/`llm_run` 保留新记录不覆盖历史。
3. **AI 不替家长拍板**：本模块只产新闻素材库（宽口径素材），不生成当天 3 候选、不标推荐、不确认最终选题、不做家长档×年龄档判定。
4. **Prompt 版本化**：Prompt 独立成文件、带版本，不硬编码进业务代码；每次调用记 model/prompt/schema 版本、input_hash、token 与成本。Prompt 升版后用 `classify --mode light --stale` 重评旧 `irrelevant`，历史 `llm_run` 不覆盖。
5. **密钥不入库**：`ANTHROPIC_API_KEY` 不写配置、日志、异常或数据库；持久化 `llm_run` 前移除 API Key/Authorization/x-api-key/Cookie，错误文本设长度上限；`.env` 已由根 `.gitignore` 忽略。
6. **导出必双格式 · 单一素材库**（v0.5）：JSON + Markdown 原子同出（`YYYYMMDD_HHmmss_news_material.json/.md`），无单格式选项，不覆盖旧文件，不写 `稿子/`。导出**一个**新闻素材库（不再按年龄档×家长档拆六组合），含全部非红线、非重复、未被人工 `rejected` 的事件及其参考标签；红线是唯一被排除的安全分级。
7. **退出码字面固定**（plan §15）：0 成功（含合法空导出）/ 2 参数或配置校验失败 / 3 所有启用外部来源均失败 / 4 部分成功 / 5 进程锁冲突 / 6 DB 连接/迁移/事务基础设施失败 / 7 显式 LLM 命令或 `run` 需要 LLM 但凭据未配置（非 LLM 阶段数据保留）/ 8 批准或导出 Schema 校验失败 / 9 访问策略拒绝/事实核验闸门/其它业务前置未满足。非零退出**不得删除此前已成功提交的数据**。
8. **每次运行由人手动发起，进程结束即退出**：不引入后台常驻、定时调度或自动抓取。
9. **留存**：`content_raw` 7 天、`content_clean` 30 天、文件运行日志与 LLM `raw_response`/脱敏错误 30 天；到期由人工执行 `retention prune`（幂等、Asia/Shanghai、提供 `--dry-run`）清空，**不删文章/事件/来源/hash/事件关联/结构化 LLM 结果/事实核验/复核记录**，不引入调度器。

## 实施顺序（plan §14，七阶段，按序推进）

1. **采集框架**：项目骨架、`uv python pin 3.12`、Collector 接口、RSS/网页/RSSHub Collector、标准库解析、TOML 校验、采集日志。
2. **数据存储**：四张核心表（`news_source`/`news_article`/`news_event`/`fetch_log`）+ 迁移 + Repository 层；WAL/foreign keys/busy timeout。
3. **正文和清洗**：正文抓取、HTML 转纯文本、去噪、编码、URL 规范化、内容 hash。
4. **去重与聚类**：URL/标题/SimHash、四条件事件聚类、`filters.toml` 阈值、文章绑事件、测试夹具（≥10 组）。
5. **来源接入**（顺序固定）：NASA → MIT News → Smithsonian Magazine → 少数派 → Solidot → BBC → The Guardian → The Conversation → 果壳 → 少年報導者 → 极客公园 → 澎湃 → 界面 → 知乎热榜 + B 站热门；先接稳定官方 RSS，再接网页抓取。
6. **LLM 识别服务**：Schema、一级/二级识别、Prompt 文件化与版本、JSON Schema 校验、失败重试、日志成本、写入 `news_event`、人工修正 CLI、六类选题测试样本；补建 `llm_run`。
7. **CLI 运行和观测**：完整入口与退出码、进程锁、单来源失败隔离、重试/超时、失败汇总、来源健康、每日统计、单来源触发、双格式原子导出（单一素材库，v0.5）；补建 `fact_check_record`/`event_review`（支撑可选 review/fact-check 策展与 export；v0.5 起不再作 gate）。

首批范围固定：**14 个采集单元（S01–S14）、15 条来源记录**。MVP 至少 3 条真实启用并完成 live smoke，RSS/网页/RSSHub 各 ≥1。第二批来源（微博/公众号/Reuters/AP 等）暂不接入。

## 上下游关系

- `../PRD_v0.8.md`：产品边界与引擎五层的真理源；本模块的「做什么」由它定义（新闻采集 = Content Intelligence，唯一工程化）。
- `../Content_Safety_Policy_v0.1.md`：内容安全判定逻辑的执行细则；判定恒为「家长档 × 年龄档」，红线只增不减。
- 根 `CLAUDE.md`：uv 与 Python 铁律、模块边界、产品宪法、全文中文与术语一致等全局约束。
- 三者冲突时**先改上游真理源，再回流本目录**，不在本目录私自改写产品决策或安全规则。本目录的 plan 只负责把上游边界落成可执行的采集/数据/CLI 契约。

## 编辑约定

- 全文中文；正式名「喂今天」。术语与父级一致：核心机制、产品宪法、北极星、红线/敏感/默认三层 + uncertain、家长档 × 年龄档、引擎五层（Content Intelligence / Cognitive / Narrative / Family Personalization / Voice Performance）。
- 文档带版本号 + 日期 + 更新记录（参照 PRD 写法）。区分「已定设定」与「开放问题」。
- 测试默认禁真实网络，live smoke 必须显式标记并单独运行；断网/429/超时/畸形 RSS/空 Feed/HTML 异常/LLM 非法 JSON 均用离线 fixture 覆盖。
- 提交 `新闻采集/CLAUDE.md` 后，须在 `正式文档索引.md` 登记：区分 `README.md`（人读入口：边界/方案/运行）与 `CLAUDE.md`（AI agent 项目级约束入口）。
- 每次会话结束前，若改了方案、Prompt、CLI 行为或配置规则，按 `正式文档索引.md` 的「会话结束文档检查」扫一遍，确认是否同步指针、归档旧版或更新索引。
