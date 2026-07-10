# 新闻采集

**状态**：独立工程化 MVP，尚未开始实现  
**当前方案**：`news-source-ingestion-plan-v0.4.md`

## 这是什么

这是喂今天当前唯一工程化的新闻采集模块。它以本地手动 CLI 独立运行，覆盖小学高年级和初中两档，把 RSS、网页栏目和 RSSHub 材料处理成可供后续手工选题使用的合格新闻池。人工临时发现的材料不进入本模块数据库，继续直接走下游手工选题流程。

## 模块边界

本模块负责：

- 维护并接入 14 个首批采集单元；
- 采集、正文清洗、URL/标题/内容去重和新闻事件聚类；
- 两级 LLM 分类与结构化评分；
- 按 `../Content_Safety_Policy_v0.1.md` 执行“红线 / 敏感 / 默认 × 家长档 × 年龄档”；
- 分别输出小学高年级与初中的年龄适配结果；
- 人工复核后导出 JSON / Markdown 合格新闻池。

本模块不负责：

- 后台常驻、定时调度或自动抓取；
- 生成 3 个候选、标记 1 个推荐；
- 替家长确认最终选题；
- 写稿、TTS、音频评估或发布。

采集之后仍进入现有手工流程：合格新闻池 → 手工生成 3 个候选并标 1 个推荐 → 家长拍板 → 写稿 → 音频。

## 运行方式（实施完成后）

技术路径锁定为 Python 3.12、SQLite、SQLAlchemy/Alembic 和 Typer CLI。每次运行由人手动发起，命令结束后进程退出。计划中的基础入口为：

LLM 固定使用 Kimi Coding Anthropic 兼容接口和 `kimi-for-coding` 模型；运行前由用户设置 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_API_KEY`，仓库不保存密钥。该接口仅用于当前本地个人 MVP；扩展到外部家庭或商业运行前必须迁移到正式产品 API。

```powershell
uv sync --locked
uv run news-ingestion db upgrade
uv run news-ingestion run
uv run news-ingestion source list
uv run news-ingestion fetch --all
uv run news-ingestion dedup --since 24h
uv run news-ingestion cluster --since 72h
uv run news-ingestion classify --since 24h --mode light
uv run news-ingestion export --age upper-primary --parent-mode standard
uv run news-ingestion export --age junior-high --parent-mode open
```

每次导出同时生成同名 JSON 与 Markdown，不提供单格式导出选项。
`--parent-mode` 支持 `conservative / standard / open`，不传时默认 `standard`。
文件按 `YYYYMMDD_HHmmss_年龄档_家长档` 命名，使用 Asia/Shanghai 时间，保留历史且不覆盖旧文件。

当前目录尚未实现代码，以上命令不能运行。具体数据契约、失败处理、验收标准和实施顺序以方案文档为准。

日常默认先执行 `uv run news-ingestion run`，它完成采集、去重、聚类和两级 LLM 识别后停在人工复核队列；事实核验、人工批准和导出继续分步手工执行。

## Kimi 连接测试

1. 在本目录 `.env` 中填写 `ANTHROPIC_API_KEY`；`ANTHROPIC_BASE_URL` 已预填官方 Anthropic 兼容地址。
2. 在本目录运行：

```powershell
uv run python .\测试Kimi连接.py
```

成功时会打印实际模型和短回复。脚本不会打印 API Key；`.env` 已由根目录 `.gitignore` 忽略。

## 文档职责

- `news-source-ingestion-plan-v0.4.md`：当前实施方案；下一次实质修订时同步升版文件名、文档版本和本指针。
- 本 README：维护模块入口、边界、当前运行方法和当前方案指针。

新闻采集的产品边界由 `../PRD_v0.8.md` 定义；内容安全判定由 `../Content_Safety_Policy_v0.1.md` 定义。若三者冲突，先修订上游真理源，再更新本目录。
