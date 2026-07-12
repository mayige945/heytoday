# 新闻采集

**状态**：MVP 已实现（plan v0.5：采集=新闻素材库底座，只挡红线；`uv run pytest` 全绿；来源默认禁用，待 live smoke 核验后启用）  
**当前方案**：`news-source-ingestion-plan-v0.5.md`

## 这是什么

这是喂今天当前唯一工程化的新闻采集模块。它以本地手动 CLI 独立运行，把 RSS、网页栏目和 RSSHub 材料处理成**新闻素材库**：一个宽口径、带结构化参考标签（话题分类、评分、两档年龄兴趣、安全分级、待核验点、儿童入口）的素材池，只对**红线**做硬过滤；家长档 × 年龄档判定与事实核验下移到下游选题/写稿阶段。人工临时发现的材料不进入本模块数据库，继续直接走下游手工选题流程。

## 模块边界

本模块负责：

- 维护并接入 14 个首批采集单元；
- 采集、正文清洗、URL/标题/内容去重和新闻事件聚类；
- 两级 LLM 分类与结构化评分；
- 按 `../Content_Safety_Policy_v0.1.md` 执行“红线 / 敏感 / 默认 × 家长档 × 年龄档”；
- 分别输出小学高年级与初中的年龄适配结果；
- 人工复核后导出 JSON / Markdown **新闻素材库**（单一素材池，仅排除红线；v0.5）。

本模块不负责：

- 后台常驻、定时调度或自动抓取；
- 生成 3 个候选、标记 1 个推荐；
- 替家长确认最终选题；
- 写稿、TTS、音频评估或发布。

采集之后仍进入现有手工流程：新闻素材库 → 手工生成 3 个候选并标 1 个推荐（这时做家长档 × 年龄档判定与事实核验）→ 家长拍板 → 写稿 → 音频。

## 运行方式

技术路径锁定为 Python 3.12、SQLite、SQLAlchemy/Alembic 和 Typer CLI（CLI 名 `news-ingestion`），统一用 uv 管理。每次运行由人手动发起，命令结束后进程退出。基础入口：

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
uv run news-ingestion export                 # 导出单一新闻素材库（v0.5：不分年龄/家长档）
```

每次导出同时生成同名 JSON 与 Markdown（`YYYYMMDD_HHmmss_news_material.json/.md`），不提供单格式选项；
Asia/Shanghai 时间，保留历史且不覆盖旧文件。`output/INDEX.md` 与 `latest_news_material.*` 提供人读索引。
素材库含全部非红线、非重复、未被人工拒绝的事件及其参考标签；家长档 × 年龄档判定与事实核验在下游选题/写稿时做。

当前目录已实现完整代码：采集 / 清洗 / 去重聚类 / 两级 LLM / 安全分级 / 人工复核 / 双格式导出 / 留存，全部命令可运行。15 条来源默认全部 `enabled=false`、`access_review_status=uncertain`；启用前必须完成 robots/条款核验 + live smoke（至少 3 条，RSS/网页/RSSHub 各 ≥1）。具体数据契约、失败处理、验收标准和实施顺序以方案文档为准。

## 测试

```powershell
uv run pytest
```

默认禁真实网络与真实 LLM；离线端到端（`tests/test_pipeline_e2e.py`）用 fake 采集器与 fake Anthropic client 覆盖采集 → 去重 → 聚类 → 两级识别 → 结构化落库 → 双格式导出的完整链路，以及 `run` 无凭据降级（退出码 7、非 LLM 数据保留）。需要 live smoke 的来源 URL / robots / Kimi 真实响应核验另行单独运行并在运行记录写明核验日期。

日常默认先执行 `uv run news-ingestion run`，它完成采集、去重、聚类和两级 LLM 识别后停在人工复核队列；事实核验、人工批准和导出继续分步手工执行。

## Kimi 连接测试

1. 在本目录 `.env` 中填写 `ANTHROPIC_API_KEY`；`ANTHROPIC_BASE_URL` 已预填官方 Anthropic 兼容地址。
2. 在本目录运行：

```powershell
uv run python .\测试Kimi连接.py
```

成功时会打印实际模型和短回复。脚本不会打印 API Key；`.env` 已由根目录 `.gitignore` 忽略。

## 文档职责

- `news-source-ingestion-plan-v0.5.md`：当前实施方案（v0.5：采集=新闻素材库底座，只挡红线）；下一次实质修订时同步升版文件名、文档版本和本指针。`v0.4.md` 已归档。
- `CLAUDE.md`：本目录的 AI agent 项目级约束入口——uv 铁律、CLI 契约、模块边界、数据契约与硬约束；代码尚未实现，当前唯一可跑的是 Kimi 冒烟测试。
- 本 README：维护模块入口、边界、当前运行方法和当前方案指针。

新闻采集的产品边界由 `../PRD_v0.8.md` 定义；内容安全判定由 `../Content_Safety_Policy_v0.1.md` 定义。若三者冲突，先修订上游真理源，再更新本目录。
