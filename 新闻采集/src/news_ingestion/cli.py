"""``news-ingestion`` CLI（plan §15）。

Typer 提供命令树；退出码字面值固定（见 ``errors.ExitCode``）。所有写命令经进程锁防
重复运行；除 ``db upgrade/status``、``source list/validate``、``event list``、
``fetch-log`` 外，启动时检查 Alembic revision，未初始化 / 落后 head 返回退出码 6。
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

import typer
from sqlalchemy.exc import SQLAlchemyError

from .config import load_filters, load_runtime, load_sources, load_source_by_code
from .db import current_revision, default_engine, head_revision, make_session_factory, needs_init_or_upgrade, run_upgrade
from .env import load_dotenv
from .errors import (
    BusinessPreconditionError,
    ConfigError,
    DbInfraError,
    LlmNotConfiguredError,
    LockBusyError,
    SchemaValidationError,
)
from .logging_setup import get_logger, setup_logging
from .services import (
    ProcessLock,
    DatabaseLock,
    approve_event,
    daily_stats,
    export_material,
    fetch_all,
    fetch_logs,
    list_events_for_review,
    prune,
    record_fact_check,
    regenerate_index,
    reject_event,
    run_classify_light,
    run_cluster,
    run_dedup,
    run_pipeline,
    run_score_full,
    source_health,
    sync_material,
)

_LOG = get_logger(__name__)

app = typer.Typer(help="喂今天 · 新闻采集 CLI（单次执行，进程结束即退出）", no_args_is_help=True)
db_app = typer.Typer(help="数据库迁移")
source_app = typer.Typer(help="来源管理")
article_app = typer.Typer(help="文章操作")
event_app = typer.Typer(help="事件与复核")
llm_app = typer.Typer(help="LLM 识别")
supabase_app = typer.Typer(help="Supabase 新闻素材库同步")
app.add_typer(db_app, name="db")
app.add_typer(source_app, name="source")
app.add_typer(article_app, name="article")
app.add_typer(event_app, name="event")
app.add_typer(llm_app, name="llm")
app.add_typer(supabase_app, name="supabase")


@contextmanager
def app_context(*, lock: bool = False, gate: bool = True):
    """统一引导：日志 / DB 闸门 / 进程锁 / 异常 → 退出码映射。"""
    setup_logging()
    try:
        engine = default_engine()
        if gate and needs_init_or_upgrade(engine):
            typer.echo("数据库未初始化或落后 head，请先执行：uv run news-ingestion db upgrade", err=True)
            raise typer.Exit(6)
        session_factory = make_session_factory(engine)
        try:
            if lock:
                with ProcessLock(), DatabaseLock(engine):
                    yield engine, session_factory
            else:
                yield engine, session_factory
        except LockBusyError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(5)
    except typer.Exit:
        raise
    except ConfigError as exc:
        typer.echo(f"配置错误：{exc}", err=True)
        raise typer.Exit(2)
    except DbInfraError as exc:
        typer.echo(f"数据库错误：{exc}", err=True)
        raise typer.Exit(6)
    except SchemaValidationError as exc:
        typer.echo(f"Schema 校验失败：{exc}", err=True)
        raise typer.Exit(8)
    except BusinessPreconditionError as exc:
        typer.echo(f"业务前置未满足：{exc}", err=True)
        raise typer.Exit(9)
    except LlmNotConfiguredError as exc:
        typer.echo(f"LLM 未配置：{exc}", err=True)
        raise typer.Exit(7)
    except SQLAlchemyError as exc:
        _LOG.error("Supabase 数据库操作失败：%s", exc.__class__.__name__)
        typer.echo(f"数据库错误：{exc.__class__.__name__}", err=True)
        raise typer.Exit(6)


def _parse_since(value: str | None, default: float) -> float | None:
    if value is None:
        return default
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*h", text)
    if match:
        return float(match.group(1))
    if text.isdigit():
        return float(int(text))
    try:
        return float(text)
    except ValueError as exc:
        raise typer.BadParameter(f"无法解析 --since：{value!r}（例：24h）") from exc


def _resolve_reviewer(explicit: str | None) -> str:
    reviewer = (explicit or os.environ.get("NEWS_REVIEWER") or "").strip()
    if not reviewer:
        raise BusinessPreconditionError("缺少 reviewer：请用 --reviewer 或设置 NEWS_REVIEWER")
    return reviewer


@app.callback()
def _main() -> None:
    """喂今天 · 新闻采集 CLI。"""
    setup_logging()


# ----------------------------- db -----------------------------


@db_app.command("upgrade")
def db_upgrade() -> None:
    """显式初始化 / 升级到 head（幂等）。"""
    with app_context(gate=False) as (engine, _session_factory):
        run_upgrade(engine)
        typer.echo(f"数据库已升级到 head（{head_revision()}）")


@db_app.command("status")
def db_status() -> None:
    """查看当前 / head revision。"""
    with app_context(gate=False) as (engine, _session_factory):
        current = current_revision(engine)
        head = head_revision()
        needs = needs_init_or_upgrade(engine)
        typer.echo(f"current={current} head={head} needs_init_or_upgrade={needs}")


# ----------------------------- source -----------------------------


@source_app.command("list")
def source_list() -> None:
    """列出配置的全部来源（读 config，不依赖 DB）。"""
    setup_logging()
    sources = load_sources()
    by_unit: dict[str, list] = {}
    for source in sources:
        by_unit.setdefault(source.unit_code, []).append(source)
    typer.echo(f"共 {len(sources)} 条来源记录 / {len(by_unit)} 个采集单元")
    for unit_code in sorted(by_unit):
        items = by_unit[unit_code]
        for source in items:
            flag = "✓" if source.enabled else "·"
            typer.echo(
                f"{flag} {source.unit_code} {source.code:24} {source.acquisition_method:7} "
                f"{source.source_category:18} {source.access_review_status:10} {source.name}"
            )


@source_app.command("validate")
def source_validate(code: str = typer.Argument(..., help="来源 code")) -> None:
    """校验单条来源配置。"""
    setup_logging()
    source = load_source_by_code(code)
    typer.echo(f"OK {source.unit_code}/{source.code} method={source.acquisition_method} enabled={source.enabled}")


# ----------------------------- fetch -----------------------------


@app.command("fetch")
def fetch_cmd(
    code: str | None = typer.Argument(None, help="来源 code；省略则需 --all 或 --category"),
    all_sources: bool = typer.Option(False, "--all", help="抓取全部启用来源"),
    category: str | None = typer.Option(None, "--category", help="仅抓某 source_category（如 trend_radar）"),
) -> None:
    """抓取来源元数据（只写元数据，不抓正文）。"""
    with app_context(lock=True) as (_engine, session_factory):
        runtime = load_runtime()
        all_cfg = load_sources()
        if code:
            selected = [load_source_by_code(code)]
            selected[0].enabled = True  # 单源显式抓取允许越过 enabled
        elif all_sources:
            selected = [s for s in all_cfg if s.enabled]
        elif category:
            selected = [s for s in all_cfg if s.enabled and s.source_category == category]
        else:
            typer.echo("请指定来源 code、--all 或 --category", err=True)
            raise typer.Exit(2)
        if not selected:
            typer.echo("没有符合条件的启用来源", err=True)
            raise typer.Exit(2)

        outcomes = fetch_all(
            session_factory,
            selected,
            user_agent=runtime.user_agent,
            max_retries=runtime.llm_max_retries,
        )
        for outcome in outcomes:
            typer.echo(
                f"{outcome.source_id}: {outcome.status} found={outcome.items_found} "
                f"created={outcome.items_created} updated={outcome.items_updated} errors={len(outcome.errors)}"
            )
        if all(o.status == "failed" for o in outcomes):
            raise typer.Exit(3)
        if any(o.status == "failed" for o in outcomes):
            raise typer.Exit(4)


@app.command("run")
def run_cmd(
    output_json: bool = typer.Option(False, "--json", help="向 stdout 输出机器可读任务结果"),
) -> None:
    """日常默认入口：采集 → 去重 → 一级 → 正文 → 聚类 → 二级 → 停在人工复核队列。"""
    with app_context(lock=True) as (_engine, session_factory):
        runtime = load_runtime()
        filters = load_filters()
        enabled = [s for s in load_sources() if s.enabled]
        if not enabled:
            typer.echo("无启用来源；请先在 config/sources.toml 启用并完成访问核验", err=True)
            raise typer.Exit(2)
        result = run_pipeline(
            session_factory,
            enabled_sources=enabled,
            runtime=runtime,
            filters=filters,
            user_agent=runtime.user_agent,
        )
        if output_json:
            typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")))
        else:
            typer.echo(
                f"run 完成：来源 success/partial/failed="
                f"{result.summary.get('sources_success')}/{result.summary.get('sources_partial')}/{result.summary.get('sources_failed')} "
                f"新文章={result.summary.get('articles_created')} 去重={result.summary.get('duplicates')} "
                f"新事件={result.summary.get('events_new')} 已评分={result.summary.get('events_scored')} "
                f"llm_configured={result.summary.get('llm_configured')}"
            )
        raise typer.Exit(result.exit_code)


# ----------------------------- 单阶段命令 -----------------------------


@app.command("dedup")
def dedup_cmd(since: str = typer.Option("24h", "--since")) -> None:
    with app_context(lock=True) as (_engine, session_factory):
        stats = run_dedup(session_factory, since_hours=_parse_since(since, 24), filters=load_filters())
        typer.echo(f"去重：checked={stats['checked']} duplicates={stats['duplicates']} by_basis={stats['by_basis']}")


@app.command("cluster")
def cluster_cmd(since: str = typer.Option("72h", "--since")) -> None:
    with app_context(lock=True) as (_engine, session_factory):
        stats = run_cluster(session_factory, since_hours=_parse_since(since, 72), filters=load_filters())
        typer.echo(f"聚类：{stats}")


@app.command("classify")
def classify_cmd(
    since: str = typer.Option("24h", "--since"),
    stale: bool = typer.Option(False, "--stale", help="重评旧 irrelevant（prompt 升版后）"),
) -> None:
    with app_context(lock=True) as (_engine, session_factory):
        stats = run_classify_light(
            session_factory,
            since_hours=_parse_since(since, 24),
            runtime=load_runtime(),
            strict=True,
            stale=stale,
        )
        typer.echo(f"一级识别：{stats}")


@app.command("score")
def score_cmd(
    event_id: str | None = typer.Option(None, "--event", help="仅评分指定事件"),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="重试 failed 事件"),
) -> None:
    with app_context(lock=True) as (_engine, session_factory):
        stats = run_score_full(
            session_factory,
            runtime=load_runtime(),
            strict=True,
            event_id=event_id,
            retry_failed=retry_failed,
        )
        typer.echo(f"二级评分：{stats}")


@llm_app.command("retry")
def llm_retry(status: str = typer.Option("failed", "--status")) -> None:
    """重试失败的 LLM 评分。"""
    with app_context(lock=True) as (_engine, session_factory):
        retry = status == "failed"
        stats = run_score_full(session_factory, runtime=load_runtime(), strict=True, retry_failed=retry)
        typer.echo(f"LLM 重试：{stats}")


@app.command("retention")
def retention_cmd(
    action: str = typer.Argument("prune"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    if action != "prune":
        typer.echo(f"未知 retention 动作：{action}", err=True)
        raise typer.Exit(2)
    with app_context(lock=True) as (_engine, session_factory):
        stats = prune(session_factory, dry_run=dry_run)
        typer.echo(f"留存清理：{stats}")


# ----------------------------- 文章 -----------------------------


@article_app.command("refetch")
def article_refetch(article_id: str = typer.Argument(...)) -> None:
    """重新抓取单篇文章正文。"""
    from .repositories import ArticleRepository, SourceRepository
    from .services.fulltext import fetch_article_content

    with app_context(lock=True) as (_engine, session_factory):
        runtime = load_runtime()
        with session_factory() as session:
            article = ArticleRepository(session).get(article_id)
            if article is None:
                typer.echo(f"文章不存在：{article_id}", err=True)
                raise typer.Exit(9)
            source = SourceRepository(session).get(article.source_id)
        fetched = fetch_article_content(article.url, source=source, user_agent=runtime.user_agent)
        with session_factory() as session:
            repo = ArticleRepository(session)
            if fetched.error:
                repo.set_content(article_id, content_raw=None, content_clean=None, content_hash=None, fetch_status="failed")
                session.commit()
                typer.echo(f"正文抓取失败：{fetched.error}", err=True)
                raise typer.Exit(4)
            repo.set_content(article_id, content_raw=fetched.content_raw, content_clean=fetched.content_clean, content_hash=fetched.content_hash)
            session.commit()
            typer.echo(f"已重新抓取正文：{article_id}（{len(fetched.content_clean or '')} 字）")


# ----------------------------- 复核 / 事实核验 / 导出 -----------------------------


@event_app.command("list")
def event_list(review_status: str = typer.Option("pending", "--review-status")) -> None:
    """查看待复核 / 指定状态的事件。"""
    with app_context(gate=True) as (_engine, session_factory):
        rows = list_events_for_review(session_factory, review_status=review_status)
        typer.echo(f"事件（review_status={review_status}）：{len(rows)} 条")
        for row in rows:
            typer.echo(
                f"{row['event_id'][:14]} {row['status']:12} llm={row['llm_status']:8} "
                f"safety={row['safety_tier']:10} cat={row['primary_category']} "
                f"fc={row['needs_fact_check']} arts={row['article_count']} {row['title'][:30]}"
            )


@event_app.command("review")
def event_review(
    event_id: str = typer.Argument(...),
    reviewer: str | None = typer.Option(None, "--reviewer"),
    approve: bool = typer.Option(False, "--approve", help="可选策展：标记 approved（事件默认已在素材库）"),
    reject: bool = typer.Option(False, "--reject", help="把事件剔出素材库"),
    note: str | None = typer.Option(None, "--note"),
    rejection_reason: str | None = typer.Option(None, "--rejection-reason"),
) -> None:
    """人工策展事件（v0.5：可选）。--approve 标记认可；--reject 剔出素材库。无需矩阵/事实核验。"""
    if approve == reject:
        typer.echo("请明确 --approve 或 --reject（二选一）", err=True)
        raise typer.Exit(2)
    with app_context(lock=True) as (_engine, session_factory):
        reviewer_value = _resolve_reviewer(reviewer)  # 缺失 → BusinessPreconditionError → 退出码 9
        if approve:
            approve_event(session_factory, event_id, reviewer=reviewer_value, note=note)
            typer.echo(f"事件 {event_id} 已 approved（reviewer={reviewer_value}）")
        else:
            reject_event(session_factory, event_id, reviewer=reviewer_value, rejection_reason=rejection_reason, note=note)
            typer.echo(f"事件 {event_id} 已 rejected（剔出素材库，reviewer={reviewer_value}）")


@event_app.command("fact-check")
def event_fact_check(
    event_id: str = typer.Argument(...),
    reviewer: str | None = typer.Option(None, "--reviewer"),
    status: str = typer.Option(..., "--status", help="pending | verified | failed"),
    conclusion: str | None = typer.Option(None, "--conclusion"),
    evidence_url: list[str] = typer.Option([], "--evidence-url", help="正式媒体事实源 / 原始来源 URL（可多次）"),
    evidence_source_name: str = typer.Option("正式媒体", "--evidence-source-name"),
) -> None:
    """记录事件事实核验结论与证据。"""
    with app_context(lock=True) as (_engine, session_factory):
        reviewer_value = _resolve_reviewer(reviewer)  # 缺失 → 退出码 9
        from .timeutil import utcnow

        evidence = [
            {"url": url, "source_name": evidence_source_name, "source_role": "fact_source", "checked_at": utcnow().isoformat()}
            for url in evidence_url
        ]
        record_fact_check(
            session_factory,
            event_id,
            reviewer=reviewer_value,
            status=status,
            conclusion=conclusion,
            evidence_sources=evidence,
        )
        typer.echo(f"事件 {event_id} 事实核验已记录：status={status}")


@app.command("export")
def export_cmd() -> None:
    """导出新闻素材库（v0.5：单一素材池，不分年龄/家长档；JSON + Markdown 原子同出）。"""
    with app_context(lock=True) as (_engine, session_factory):
        _json, md, info = export_material(session_factory)
        typer.echo(f"导出完成：result={info['result']} events={info['events']}")
        typer.echo(f"  JSON: {_json}")
        typer.echo(f"  MD:   {md}")


@supabase_app.command("sync")
def supabase_sync_cmd(
    input_path: Path | None = typer.Option(None, "--input", help="素材库 JSON；默认 output/latest_news_material.json"),
) -> None:
    """把一份 news-material/v1 素材库幂等同步到 Supabase。"""
    with app_context(lock=True, gate=False):
        result = sync_material(input_path)
        typer.echo(f"Supabase 同步完成：sync_id={result['sync_id']} events={result['events']}")


@app.command("pool-index")
def pool_index_cmd() -> None:
    """重新生成 output/ 的中文 INDEX.md（人读索引；导出时也会自动维护）。"""
    setup_logging()
    from .paths import output_dir as _output_dir

    idx = regenerate_index(_output_dir())
    typer.echo(f"已生成索引：{idx}")


# ----------------------------- 观测 -----------------------------


@app.command("fetch-log")
def fetch_log_cmd(
    status: str | None = typer.Option(None, "--status", help="running|success|partial_success|failed"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    with app_context(gate=True) as (_engine, session_factory):
        logs = fetch_logs(session_factory, status=status, limit=limit)
        typer.echo(f"采集日志（{len(logs)} 条）")
        for log in logs:
            typer.echo(
                f"{log['source_id']:24} {log['status']:14} found={log['items_found']} "
                f"created={log['items_created']} errors={log['errors_count']} {log['started_at']}"
            )


@app.command("health")
def health_cmd() -> None:
    """来源健康与每日采集统计。"""
    with app_context(gate=True) as (_engine, session_factory):
        typer.echo("=== 来源健康 ===")
        health = source_health(session_factory)
        for source in health["sources"]:
            typer.echo(
                f"{source['unit_code']} {source['code']:24} enabled={source['enabled']} "
                f"access={source['access_review_status']:10} fails={source['consecutive_failures']} "
                f"last_success={source['last_success_at']}"
            )
        typer.echo("=== 每日统计（24h）===")
        typer.echo(json.dumps(daily_stats(session_factory, since_hours=24), ensure_ascii=False, indent=2))


def main() -> None:
    """console_script 入口：先加载本目录 .env（凭据），再启动 CLI。

    CliRunner 在测试里直接调 ``app``，不会触发本函数，故 monkeypatch 的环境变量不受影响。
    """
    load_dotenv()
    app()
