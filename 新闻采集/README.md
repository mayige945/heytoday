# 新闻采集

**状态**：MVP 已实现（plan v0.8：服务器一次性任务 + Supabase 唯一运行库 + 通用业务任务审计；来源默认禁用，待 live smoke 核验后启用）
**当前方案**：`news-source-ingestion-plan-v0.8.md`

## 这是什么

这是喂今天当前唯一工程化的新闻采集模块。它以服务器一次性 CLI 任务独立运行，把 RSS、网页栏目和 RSSHub 材料处理成**新闻素材库**：一个宽口径、带结构化参考标签（话题分类、评分、两档年龄兴趣、安全分级、待核验点、儿童入口）的素材池，只对**红线**做硬过滤；家长档 × 年龄档判定与事实核验下移到下游选题/写稿阶段。人工临时发现的材料不进入本模块数据库，继续直接走下游手工选题流程。

## 模块边界

本模块负责：

- 维护并接入 14 个首批采集单元；
- 采集、正文清洗、URL/标题/内容去重和新闻事件聚类；
- 两级 LLM 分类与结构化评分；
- 按 `../Content_Safety_Policy_v0.1.md` 执行“红线 / 敏感 / 默认 × 家长档 × 年龄档”；
- 分别输出小学高年级与初中的年龄适配结果；
- 人工复核后导出 JSON / Markdown **新闻素材库**（单一素材池，仅排除红线；v0.5）。

本模块不负责：

- 后台常驻或实时抓取服务（允许外部 cron 定时触发一次性任务）；
- 生成 3 个候选、标记 1 个推荐；
- 替家长确认最终选题；
- 写稿、TTS、音频评估或发布。

采集之后仍进入现有手工流程：新闻素材库 → 手工生成 3 个候选并标 1 个推荐（这时做家长档 × 年龄档判定与事实核验）→ 家长拍板 → 写稿 → 音频。

## 运行方式

技术路径锁定为 Python 3.12、Supabase Postgres、SQLAlchemy/Alembic 和 Typer CLI（CLI 名 `news-ingestion`），统一用 uv 管理。生产不创建或读取 SQLite；每次由服务器调度器启动一次性任务，命令结束后进程退出。

LLM 固定使用 Kimi Coding Anthropic 兼容接口和 `kimi-for-coding` 模型；运行前由用户设置 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_API_KEY`，仓库不保存密钥。该接口仅用于当前本地个人 MVP；扩展到外部家庭或商业运行前必须迁移到正式产品 API。

```powershell
uv sync --locked
uv run news-ingestion db upgrade
uv run news-ingestion --trigger-type cron --operator scheduler:daily run --json
uv run news-ingestion source list
uv run news-ingestion fetch --all
uv run news-ingestion dedup --since 24h --reason "人工确认的补跑原因"
uv run news-ingestion cluster --since 72h --reason "人工确认的补跑原因"
uv run news-ingestion classify --since 24h --reason "人工确认的补跑原因"
uv run news-ingestion export                 # 导出单一新闻素材库（v0.5：不分年龄/家长档）
uv run news-ingestion supabase sync          # 幂等同步 latest_news_material.json
uv run news-ingestion task list
uv run news-ingestion task show <task-id> --json
```

## 业务任务主线

业务审计核心按模块复用，不是新闻采集定制日志。受控写命令每次恰好创建一个任务，记录操作者、触发方式、
范围、动作、结果、实际阶段、漏斗及设计结论；`task list` 看主流水，`task show` 再下钻 `fetch_log`、
`llm_run` 和仍在留存期内的文件日志。

- 标准写任务：`run/fetch/event review/event fact-check/export/supabase sync`。
- 非标准补跑：`dedup/cluster/classify/score/llm retry/article refetch`，必须通过 `--reason` 或
  `NEWS_AUDIT_REASON` 提供原因。
- 运维写任务：`retention prune/pool-index`；`retention prune --dry-run` 不建任务。
- 只读/基础设施：`db upgrade/status`、`source list/validate`、`event list`、`fetch-log`、`health`、
  `task list/show`，不建任务。

执行状态与设计状态分开：正常为 `succeeded/compliant/0`，无 LLM 为 `partial_success/compliant/7`，
部分来源失败为 `partial_success/compliant/4`；已发生阶段或守恒偏差为 `partial_success/deviation/9`。
退出 9 或审计/数据库退出 6 时，调度器必须停止盲目重试，先查 `task show`；补偿用带原因的新任务。

每次导出同时生成同名 JSON 与 Markdown（`YYYYMMDD_HHmmss_news_material.json/.md`），不提供单格式选项；
Asia/Shanghai 时间，保留历史且不覆盖旧文件。`output/INDEX.md` 与 `latest_news_material.*` 提供人读索引。
素材库含全部非红线、非重复、未被人工拒绝的事件及其参考标签；家长档 × 年龄档判定与事实核验在下游选题/写稿时做。

生产运行必须从 Supabase Dashboard 的 **Connect** 对话框复制 Direct connection 或 Session pooler
连接串，并在服务器密钥环境中设置：

```dotenv
SUPABASE_DB_URL=postgresql://postgres...:<数据库密码>@...:5432/postgres?sslmode=require
```

这里使用的是**数据库连接串与数据库密码**，不是 `sb_secret_...` 或 `sb_publishable_...`。
`SUPABASE_SECRET_KEY` 只供可选的素材快照 Data API 同步使用。所有凭据不得提交。

## 服务器部署与定时执行

```bash
docker build -t heytoday-news .
docker run --rm --env-file .env heytoday-news db upgrade
docker run --rm --env-file .env heytoday-news run --json
```

cron 只需定时执行最后一条命令并收集 stdout、stderr 与退出码。数据库 advisory lock 会拒绝重叠任务；
同一来源 GUID、规范 URL、标题、正文 SHA-256/SimHash 与事件聚类共同处理重复新闻。JSON 结果包含
`run_id`、起止时间、退出码、各阶段统计、新文章数、重复数和新事件数。

部署 0005 前固定顺序：暂停 cron 并确认无活跃执行 → 备份和记录 revision/旧业务基线 →
`db upgrade` → 验证新表、约束、RLS/权限和基线 → 受控假数据任务 → 验证 `task list/show --json` →
签署后恢复 cron。stale 任务只有在取得同锁域后才会把超过 30 分钟的旧非终态收敛为
`abandoned/incomplete/6`，不会推断成功或自动重跑。生产回滚优先旧代码配合保留 0005 schema；详细
Go/No-Go 与回滚条件见 plan v0.8 §20–22。

当前目录已实现完整代码：采集 / 清洗 / 去重聚类 / 两级 LLM / 安全分级 / 人工复核 / 双格式导出 / 留存，全部命令可运行。15 条来源默认全部 `enabled=false`、`access_review_status=uncertain`；启用前必须完成 robots/条款核验 + live smoke（至少 3 条，RSS/网页/RSSHub 各 ≥1）。具体数据契约、失败处理、验收标准和实施顺序以方案文档为准。

## 测试

```powershell
uv run pytest
uv run alembic check
$env:NEWS_TEST_POSTGRES_URL='<temporary-postgres-url>'
$env:NEWS_TEST_POSTGRES_ISOLATED='1'  # 仅在确认该库可丢弃且与生产隔离后设置
uv run pytest -m live tests/test_audit_postgres.py
```

默认禁真实网络与真实 LLM。PostgreSQL gate 必须使用 Supabase-shaped 临时/隔离库，且不得等于生产
`SUPABASE_DB_URL`；测试会规范化比较两者的用户、主机、端口与数据库名，并在未显式确认隔离时失败。它验证真实行锁、终态竞争、复合外键，以及客户端拒绝和 `service_role` 最小读写权限。来源/Kimi live smoke 仍另行执行并记录日期。

日常默认先执行 `uv run news-ingestion run`，它完成采集、去重、聚类和两级 LLM 识别后停在人工复核队列；事实核验、人工批准和导出继续分步手工执行。首次接入 Feed 时，超出 `--since` 时间窗的历史条目仍会保存并参与去重，但不会调用 LLM。

## Kimi 连接测试

1. 在本目录 `.env` 中填写 `ANTHROPIC_API_KEY`；`ANTHROPIC_BASE_URL` 已预填官方 Anthropic 兼容地址。
2. 在本目录运行：

```powershell
uv run python .\测试Kimi连接.py
```

成功时会打印实际模型和短回复。脚本不会打印 API Key；`.env` 已由根目录 `.gitignore` 忽略。

## 文档职责

- `news-source-ingestion-plan-v0.8.md`：当前实施方案（v0.8：服务器定时一次性任务 + Supabase 唯一运行库 + 通用业务任务审计）。`v0.7.md` 及更早版本已归档。
- `CLAUDE.md`：本目录的 AI agent 项目级约束入口——uv 铁律、CLI 契约、模块边界、数据契约与硬约束。
- 本 README：维护模块入口、边界、当前运行方法和当前方案指针。

新闻采集的产品边界由 `../PRD_v0.9.md` 定义；内容安全判定由 `../Content_Safety_Policy_v0.1.md` 定义。若三者冲突，先修订上游真理源，再更新本目录。
