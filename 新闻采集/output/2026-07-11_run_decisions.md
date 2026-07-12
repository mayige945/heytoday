# 运行与决策日志 · 2026-07-11

> **v0.5 重组（同日）**：操作者厘清「采集 = 新闻素材库底座」——采集不追求事实、角度会重选、
> 稿件二次选择。据此 plan 升 v0.5：**采集阶段只硬过滤红线**；事实核验/家长档×年龄档/敏感放行
> 全部下移到选题/写稿。下方 v0.4 时代的「事实核验 gate / 六组合矩阵 / 63 待决」记录保留作历史；
> v0.5 下这 63 个事件**已作为带标签的素材自然进入单一新闻素材库**（`latest_news_material.json`，
> 76 事件：57 default + 19 sensitive，红线已排除），不再卡在采集阶段。

操作者授权 Claude 代决「简单决策」、跳过并记录「影响业务的复杂决策」。reviewer 记为 `家长(演示)`（正式运行请替换为真实姓名或设 `NEWS_REVIEWER`）。

## 一、真跑暴露并修复的 bug（离线测试全绿、真跑才现形）

1. **默认 User-Agent 含中文「喂今天」** → HTTP 头 latin-1 编码失败，所有真实采集崩。改 ASCII（`WeiJinTian-...`）。
2. **CLI 不读 `.env`** → 填了凭据但 `run`/`classify`/`score` 看不到（退出 7）。加 `env.load_dotenv()`，console_script 走 `cli.main()`（CliRunner 直调 app，测试不受影响）。
3. **`anthropic.Anthropic(anthropic_version=...)` 非法参数** → 真实 SDK 客户端构造即崩。删该 kwarg（版本头 SDK 默认发）。
4. **kimi-for-coding 把六类选题写成中文**（schema 只认英文键）→ 校验失败。加 `normalize_llm_output()` 中文→枚举归一 + prompt 强化。
5. **正文抓取 0 成功**：RSS 源 `allowed_content_types` 是 feed 的 xml 类型，被复用去抓文章页（HTML）→ content-type 拒。正文页固定用 HTML 类型。
6. **思考截断**：kimi-for-coding 先吐 thinking 块，`max_tokens` 不够时正文 JSON 被吞 → 32/123 light 失败。调大（light 2048 / full 4096）+ 空正文时修复重试用 3× token。

## 二、来源启用/禁用决策（robots + 实测）

| 来源 | 决策 | 依据 |
|---|---|---|
| nasa / smithsonian / sspai / solidot / bbc / the_guardian / the_conversation | **启用 verified** | robots 允许 + feed 实测返回（the_conversation 修正为 `/us/technology/articles.atom`）|
| smithsonian | 启用（注） | robots 人读允许 `/rss/latest_articles/`；Python robotparser 因 `/*?ms=` 通配误判全 False（已记 quirk）|
| mit_news | 禁用 | `/rss` 返回 text/html，正确 feed URL 待核验 |
| guokr | 禁用 | Feed 404，长期不稳定 |
| geepark | 禁用 | 域名解析失败 |
| thepaper | 禁用 | 列表页 403（访问控制），按 plan 不绕过 |
| twreporter / jiemian | **暂缓** | 通用解析可用（64/152 条）但 `allowed_sections` 空→噪声大，批量前需收窄/写专属解析 |
| zhihu / bilibili (S14) | 跳过 | 需自建 `RSSHUB_BASE_URL`，未配置 |

## 三、事件复核决策（Phase 1 + 2d）

规则：
- **代决 approve**：`safety=default` 且 `needs_fact_check=false` 且 `story≥25` → 六组合 eligible-all（安全策略：default 任意档进）。
- **代决 reject**：`redline`（永不入池）或 `story<25`（低价值）。
- **跳过记录**：`needs_fact_check=true`（事实核验是人工闸，不橡皮章）或 `safety=sensitive`（六组合矩阵属家长业务）。

结果（共 81 事件）：
- **approve 13**（Phase 1：Curiosity 等 7 NASA；Phase 2d：guardian 小行星、conversation×3、bbc 刺客信条、sspai Vibe Coding）
- **reject 5**：Moon、Tech Life、观星、Cinnamon/Wayland（低价值）；"Parents warned not to publicly…"（redline：儿童隐私）
- **跳过 63**：需事实核验 52 + 敏感 18（委内瑞拉地震、最高法院手机搜索、世界杯监控、空气污染 DNA、Waymo 玩具枪报警、Ivermectin 抗癌传言、中国洪灾无人机救援、Meta AI 图像、EU 罚 Meta 等——安全分级正确，留家长/人工）

## 四、产出

- `output/20260711_112624_upper_primary_standard.json/.md`（13 事件）
- `output/20260711_112624_upper_primary_standard.json/.md`（同事件，初中档）
- 7 源 123 篇采集、79 篇正文、81 事件评分、6 内容去重、0 评分失败。

## 五、留给操作者的人工项（跳过的复杂决策）

1. 52 个 `needs_fact_check=true` 事件：逐个人工事实核验（记证据 URL + 结论）后再 approve。
2. 18 个 `sensitive` 事件：按「家长档 × 年龄档」矩阵决定放行（保守/标准/开放 × 小学/初中）。
3. twreporter/jiemian：收窄栏目或写专属 list 解析后再批量启用。
4. zhihu/bilibili：配置自建 RSSHub 后启用（线索源，需经正式媒体核验）。
5. reviewer 改为真实姓名。
