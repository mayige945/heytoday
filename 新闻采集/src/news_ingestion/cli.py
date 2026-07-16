"""``news-ingestion`` CLI（plan §15）。

Typer 提供命令树；退出码字面值固定（见 ``errors.ExitCode``）。所有写命令经进程锁防
重复运行；除 ``db upgrade/status``、``source list/validate``、``event list``、
``fetch-log`` 外，启动时检查 Alembic revision，未初始化 / 落后 head 返回退出码 6。
"""

from __future__ import annotations

import json
import os
import re
import getpass
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import typer
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from .config import load_filters, load_runtime, load_sources, load_source_by_code
from .db import current_revision, default_engine, head_revision, make_session_factory, needs_init_or_upgrade, run_upgrade
from .env import load_dotenv
from .errors import (
    BusinessPreconditionError,
    AuditPersistenceError,
    ConfigError,
    DbInfraError,
    LlmNotConfiguredError,
    LockBusyError,
    SchemaValidationError,
)
from .logging_setup import get_logger, setup_logging
from .timeutil import utcnow
from .audit.news_ingestion import NEWS_INGESTION_WORKFLOW, resolve_news_ingestion_details
from .models import NewsArticle, NewsEvent
from .services import (
    AuditedCommandResult,
    AuditedCommandSpec,
    AuditViewService,
    TriggerContext,
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
    run_audited_command,
)

_LOG = get_logger(__name__)

app = typer.Typer(help="喂今天 · 新闻采集 CLI（单次执行，进程结束即退出）", no_args_is_help=True)
db_app = typer.Typer(help="数据库迁移")
source_app = typer.Typer(help="来源管理")
article_app = typer.Typer(help="文章操作")
event_app = typer.Typer(help="事件与复核")
llm_app = typer.Typer(help="LLM 识别")
supabase_app = typer.Typer(help="Supabase 新闻素材库同步")
task_app = typer.Typer(help="业务任务主线与详情")
app.add_typer(db_app, name="db")
app.add_typer(source_app, name="source")
app.add_typer(article_app, name="article")
app.add_typer(event_app, name="event")
app.add_typer(llm_app, name="llm")
app.add_typer(supabase_app, name="supabase")
app.add_typer(task_app, name="task")

AUDITED_COMMANDS: dict[str, AuditedCommandSpec] = {
    "run": AuditedCommandSpec(
        "news_ingestion",
        "run",
        lock_domain="news-ingestion",
        workflow=NEWS_INGESTION_WORKFLOW,
        stages_managed_by_callback=True,
    ),
    "fetch": AuditedCommandSpec("news_ingestion", "fetch", lock_domain="news-ingestion"),
    "event.review": AuditedCommandSpec("news_ingestion", "event.review", lock_domain="news-ingestion"),
    "event.fact-check": AuditedCommandSpec("news_ingestion", "event.fact-check", lock_domain="news-ingestion"),
    "export": AuditedCommandSpec("news_ingestion", "export", lock_domain="news-ingestion"),
    "supabase.sync": AuditedCommandSpec("news_ingestion", "supabase.sync", lock_domain="news-ingestion"),
    "dedup": AuditedCommandSpec("news_ingestion", "dedup", lock_domain="news-ingestion", path_type="non_standard", reason_required=True),
    "cluster": AuditedCommandSpec("news_ingestion", "cluster", lock_domain="news-ingestion", path_type="non_standard", reason_required=True),
    "classify": AuditedCommandSpec("news_ingestion", "classify", lock_domain="news-ingestion", path_type="non_standard", reason_required=True),
    "score": AuditedCommandSpec("news_ingestion", "score", lock_domain="news-ingestion", path_type="non_standard", reason_required=True),
    "llm.retry": AuditedCommandSpec("news_ingestion", "llm.retry", lock_domain="news-ingestion", path_type="non_standard", reason_required=True),
    "article.refetch": AuditedCommandSpec("news_ingestion", "article.refetch", lock_domain="news-ingestion", path_type="non_standard", reason_required=True),
    "retention.prune": AuditedCommandSpec("operations", "retention.prune", lock_domain="operations", path_type="operations"),
    "pool-index": AuditedCommandSpec("operations", "pool-index", lock_domain="operations", path_type="operations"),
}
EXCLUDED_COMMANDS = frozenset({
    "db.upgrade", "db.status", "source.list", "source.validate", "event.list",
    "fetch-log", "health", "retention.dry-run", "task.list", "task.show",
})
_TRIGGER_CONTEXT = TriggerContext("manual", getpass.getuser(), None)


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
    except AuditPersistenceError as exc:
        task_id = exc.task_id or "-"
        typer.echo(
            f"审计数据库错误：task_id={task_id} failure_phase={exc.failure_phase} "
            f"business_commit_state={exc.business_commit_state} error={exc}",
            err=True,
        )
        if exc.__cause__ is not None:
            typer.echo(f"  原始异常：{type(exc.__cause__).__name__}: {exc.__cause__}", err=True)
        raise typer.Exit(6)
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


def _parse_task_time(value: str | None, option: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter(
            f"无法解析 {option}：{value!r}（例：2026-07-15T08:00:00+08:00）"
        ) from exc


def _resolve_reviewer(explicit: str | None) -> str:
    reviewer = (explicit or os.environ.get("NEWS_REVIEWER") or "").strip()
    if not reviewer:
        raise BusinessPreconditionError("缺少 reviewer：请用 --reviewer 或设置 NEWS_REVIEWER")
    return reviewer


def _trigger(reason: str | None = None) -> TriggerContext:
    return TriggerContext(
        _TRIGGER_CONTEXT.trigger_type,
        _TRIGGER_CONTEXT.operator,
        (reason or _TRIGGER_CONTEXT.reason or "").strip() or None,
    )


def _run_audited(
    engine,
    session_factory,
    operation: str,
    callback,
    *,
    reason: str | None = None,
    precondition=None,
    scope: dict | None = None,
) -> AuditedCommandResult:
    stale_after_minutes = load_runtime().stale_run_recovery_minutes
    return run_audited_command(
        engine,
        session_factory,
        spec=AUDITED_COMMANDS[operation],
        trigger=_trigger(reason),
        callback=callback,
        precondition=precondition,
        scope=scope,
        stale_after_minutes=stale_after_minutes,
    )


def _require_ready(
    session_factory,
    operation: str,
    *,
    target_id: str | None = None,
    stale: bool = False,
    since_hours: float | None = None,
    retry_failed: bool = False,
) -> None:
    cutoff = utcnow() - timedelta(hours=since_hours) if since_hours is not None else None
    with session_factory() as session:
        if operation in {"score", "llm.retry"}:
            statuses = ("pending", "failed") if retry_failed else ("pending",)
            statement = select(NewsEvent.id).where(NewsEvent.llm_status.in_(statuses))
            if target_id is not None:
                statement = statement.where(NewsEvent.id == target_id)
            exists = session.scalar(statement.limit(1))
        elif operation == "cluster":
            statement = select(NewsArticle.id).where(
                NewsArticle.relevance_status.in_(("relevant", "uncertain")),
                NewsArticle.duplicate_of.is_(None),
            )
            if cutoff is not None:
                statement = statement.where(
                    NewsArticle.discovered_at >= cutoff,
                    or_(NewsArticle.published_at.is_(None), NewsArticle.published_at >= cutoff),
                )
            exists = session.scalar(statement.limit(1))
        elif operation == "classify":
            desired = "irrelevant" if stale else "pending"
            statement = select(NewsArticle.id).where(
                NewsArticle.relevance_status == desired,
                NewsArticle.duplicate_of.is_(None),
            )
            if cutoff is not None:
                statement = statement.where(NewsArticle.discovered_at >= cutoff)
            exists = session.scalar(statement.limit(1))
        else:
            statement = select(NewsArticle.id).where(NewsArticle.duplicate_of.is_(None))
            if cutoff is not None:
                statement = statement.where(NewsArticle.discovered_at >= cutoff)
            exists = session.scalar(statement.limit(1))
        if exists is None:
            raise BusinessPreconditionError(f"{operation} 当前数据前置未满足，没有可处理对象")


@app.callback()
def _main(
    trigger_type: str = typer.Option("manual", "--trigger-type", envvar="NEWS_TRIGGER_TYPE"),
    operator: str | None = typer.Option(None, "--operator", envvar="NEWS_OPERATOR"),
    reason: str | None = typer.Option(None, "--reason", envvar="NEWS_AUDIT_REASON"),
) -> None:
    """喂今天 · 新闻采集 CLI。"""
    global _TRIGGER_CONTEXT
    _TRIGGER_CONTEXT = TriggerContext(trigger_type.strip() or "manual", (operator or getpass.getuser()).strip(), (reason or "").strip() or None)
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
    with app_context() as (engine, session_factory):
        runtime = load_runtime()
        all_cfg = load_sources()
        if code:
            selected = [load_source_by_code(code)]
            selected[0].enabled = True
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
        def execute(_audit, _task_id):
            outcomes = fetch_all(session_factory, selected, user_agent=runtime.user_agent, max_retries=runtime.llm_max_retries)
            exit_code = 3 if all(o.status == "failed" for o in outcomes) else 4 if any(o.status == "failed" for o in outcomes) else 0
            return AuditedCommandResult(outcomes, exit_code=exit_code)
        audited = _run_audited(engine, session_factory, "fetch", execute, scope={"schema_version": "audit-scope/v1", "sources": [s.code for s in selected]})
    for outcome in audited.value:
        typer.echo(f"{outcome.source_id}: {outcome.status} found={outcome.items_found} created={outcome.items_created} updated={outcome.items_updated} errors={len(outcome.errors)}")
    if audited.exit_code:
        raise typer.Exit(audited.exit_code)


@app.command("run")
def run_cmd(
    output_json: bool = typer.Option(False, "--json", help="向 stdout 输出机器可读任务结果"),
) -> None:
    """日常默认入口：采集 → 去重 → 一级 → 正文 → 聚类 → 二级 → 停在人工复核队列。"""
    with app_context() as (engine, session_factory):
        runtime = load_runtime()
        filters = load_filters()
        enabled = [s for s in load_sources() if s.enabled]
        if not enabled:
            typer.echo("无启用来源；请先在 config/sources.toml 启用并完成访问核验", err=True)
            raise typer.Exit(2)
        def execute(audit, task_id):
            result = run_pipeline(session_factory, enabled_sources=enabled, runtime=runtime, filters=filters, user_agent=runtime.user_agent, audit_lifecycle=audit, task_id=task_id)
            return AuditedCommandResult(result, exit_code=result.exit_code, execution_status=result.execution_status, design_status=result.design_status, summary=result.summary)
        audited = _run_audited(engine, session_factory, "run", execute)
    result = audited.value
    if output_json:
        typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")))
    else:
        typer.echo(f"run 完成：来源 success/partial/failed={result.summary.get('sources_success')}/{result.summary.get('sources_partial')}/{result.summary.get('sources_failed')} 新文章={result.summary.get('articles_created')} 去重={result.summary.get('duplicates')} 新事件={result.summary.get('events_new')} 已评分={result.summary.get('events_scored')} llm_configured={result.summary.get('llm_configured')}")
    if result.exit_code:
        raise typer.Exit(result.exit_code)


# ----------------------------- 单阶段命令 -----------------------------


@app.command("dedup")
def dedup_cmd(since: str = typer.Option("24h", "--since"), reason: str | None = typer.Option(None, "--reason")) -> None:
    since_hours = _parse_since(since, 24)
    with app_context() as (engine, session_factory):
        audited = _run_audited(engine, session_factory, "dedup", lambda *_: AuditedCommandResult(run_dedup(session_factory, since_hours=since_hours, filters=load_filters())), reason=reason, precondition=lambda: _require_ready(session_factory, "dedup", since_hours=since_hours))
    stats = audited.value
    typer.echo(f"去重：checked={stats['checked']} duplicates={stats['duplicates']} by_basis={stats['by_basis']}")


@app.command("cluster")
def cluster_cmd(since: str = typer.Option("72h", "--since"), reason: str | None = typer.Option(None, "--reason")) -> None:
    since_hours = _parse_since(since, 72)
    with app_context() as (engine, session_factory):
        audited = _run_audited(engine, session_factory, "cluster", lambda *_: AuditedCommandResult(run_cluster(session_factory, since_hours=since_hours, filters=load_filters())), reason=reason, precondition=lambda: _require_ready(session_factory, "cluster", since_hours=since_hours))
    typer.echo(f"聚类：{audited.value}")


@app.command("classify")
def classify_cmd(
    since: str = typer.Option("24h", "--since"),
    stale: bool = typer.Option(False, "--stale", help="重评旧 irrelevant（prompt 升版后）"),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    since_hours = _parse_since(since, 24)
    with app_context() as (engine, session_factory):
        audited = _run_audited(engine, session_factory, "classify", lambda *_: AuditedCommandResult(run_classify_light(session_factory, since_hours=since_hours, runtime=load_runtime(), strict=True, stale=stale)), reason=reason, precondition=lambda: _require_ready(session_factory, "classify", stale=stale, since_hours=since_hours))
    typer.echo(f"一级识别：{audited.value}")


@app.command("score")
def score_cmd(
    event_id: str | None = typer.Option(None, "--event", help="仅评分指定事件"),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="重试 failed 事件"),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    with app_context() as (engine, session_factory):
        audited = _run_audited(engine, session_factory, "score", lambda *_: AuditedCommandResult(run_score_full(session_factory, runtime=load_runtime(), strict=True, event_id=event_id, retry_failed=retry_failed)), reason=reason, precondition=lambda: _require_ready(session_factory, "score", target_id=event_id, retry_failed=retry_failed), scope={"schema_version": "audit-scope/v1", "event_id": event_id})
    typer.echo(f"二级评分：{audited.value}")


@llm_app.command("retry")
def llm_retry(status: str = typer.Option("failed", "--status"), reason: str | None = typer.Option(None, "--reason")) -> None:
    """重试失败的 LLM 评分。"""
    with app_context() as (engine, session_factory):
        retry = status == "failed"
        audited = _run_audited(engine, session_factory, "llm.retry", lambda *_: AuditedCommandResult(run_score_full(session_factory, runtime=load_runtime(), strict=True, retry_failed=retry)), reason=reason, precondition=lambda: _require_ready(session_factory, "llm.retry", retry_failed=retry))
    typer.echo(f"LLM 重试：{audited.value}")


@app.command("retention")
def retention_cmd(
    action: str = typer.Argument("prune"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    if action != "prune":
        typer.echo(f"未知 retention 动作：{action}", err=True)
        raise typer.Exit(2)
    with app_context() as (engine, session_factory):
        if dry_run:
            stats = prune(session_factory, dry_run=True)
        else:
            stats = _run_audited(engine, session_factory, "retention.prune", lambda *_: AuditedCommandResult(prune(session_factory, dry_run=False))).value
    typer.echo(f"留存清理：{stats}")


# ----------------------------- 文章 -----------------------------


@article_app.command("refetch")
def article_refetch(article_id: str = typer.Argument(...), reason: str | None = typer.Option(None, "--reason")) -> None:
    """重新抓取单篇文章正文。"""
    from .repositories import ArticleRepository, SourceRepository
    from .services.fulltext import fetch_article_content

    with app_context() as (engine, session_factory):
        runtime = load_runtime()
        def ready():
            with session_factory() as session:
                if ArticleRepository(session).get(article_id) is None:
                    raise BusinessPreconditionError(f"文章不存在：{article_id}")
        def execute(_audit, _task_id):
            with session_factory() as session:
                article = ArticleRepository(session).get(article_id)
                source = SourceRepository(session).get(article.source_id)
            fetched = fetch_article_content(article.url, source=source, user_agent=runtime.user_agent)
            with session_factory() as session:
                repo = ArticleRepository(session)
                if fetched.error:
                    repo.set_content(article_id, content_raw=None, content_clean=None, content_hash=None, fetch_status="failed")
                    session.commit()
                    return AuditedCommandResult((False, fetched.error), exit_code=4)
                repo.set_content(article_id, content_raw=fetched.content_raw, content_clean=fetched.content_clean, content_hash=fetched.content_hash)
                session.commit()
                return AuditedCommandResult((True, len(fetched.content_clean or "")))
        audited = _run_audited(engine, session_factory, "article.refetch", execute, reason=reason, precondition=ready, scope={"schema_version": "audit-scope/v1", "article_id": article_id})
    ok, detail = audited.value
    if not ok:
        typer.echo(f"正文抓取失败：{detail}", err=True)
        raise typer.Exit(4)
    typer.echo(f"已重新抓取正文：{article_id}（{detail} 字）")


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
    with app_context() as (engine, session_factory):
        def execute(_audit, _task_id):
            reviewer_value = _resolve_reviewer(reviewer)
            if approve:
                approve_event(session_factory, event_id, reviewer=reviewer_value, note=note)
                return AuditedCommandResult(f"事件 {event_id} 已 approved（reviewer={reviewer_value}）")
            reject_event(session_factory, event_id, reviewer=reviewer_value, rejection_reason=rejection_reason, note=note)
            return AuditedCommandResult(f"事件 {event_id} 已 rejected（剔出素材库，reviewer={reviewer_value}）")
        message = _run_audited(engine, session_factory, "event.review", execute, scope={"schema_version": "audit-scope/v1", "event_id": event_id}).value
    typer.echo(message)


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
    with app_context() as (engine, session_factory):
        from .timeutil import utcnow

        evidence = [
            {"url": url, "source_name": evidence_source_name, "source_role": "fact_source", "checked_at": utcnow().isoformat()}
            for url in evidence_url
        ]
        def execute(_audit, _task_id):
            reviewer_value = _resolve_reviewer(reviewer)
            record_fact_check(session_factory, event_id, reviewer=reviewer_value, status=status, conclusion=conclusion, evidence_sources=evidence)
            return AuditedCommandResult(f"事件 {event_id} 事实核验已记录：status={status}")
        message = _run_audited(engine, session_factory, "event.fact-check", execute, scope={"schema_version": "audit-scope/v1", "event_id": event_id}).value
    typer.echo(message)


@app.command("export")
def export_cmd() -> None:
    """导出新闻素材库（v0.5：单一素材池，不分年龄/家长档；JSON + Markdown 原子同出）。"""
    with app_context() as (engine, session_factory):
        audited = _run_audited(engine, session_factory, "export", lambda *_: AuditedCommandResult(export_material(session_factory)))
    _json, md, info = audited.value
    typer.echo(f"导出完成：result={info['result']} events={info['events']}")
    typer.echo(f"  JSON: {_json}")
    typer.echo(f"  MD:   {md}")


@supabase_app.command("sync")
def supabase_sync_cmd(
    input_path: Path | None = typer.Option(None, "--input", help="素材库 JSON；默认 output/latest_news_material.json"),
) -> None:
    """把一份 news-material/v1 素材库幂等同步到 Supabase。"""
    with app_context() as (engine, session_factory):
        result = _run_audited(engine, session_factory, "supabase.sync", lambda *_: AuditedCommandResult(sync_material(input_path))).value
    typer.echo(f"Supabase 同步完成：sync_id={result['sync_id']} events={result['events']}")


@app.command("pool-index")
def pool_index_cmd() -> None:
    """重新生成 output/ 的中文 INDEX.md（人读索引；导出时也会自动维护）。"""
    from .paths import output_dir as _output_dir
    with app_context() as (engine, session_factory):
        idx = _run_audited(engine, session_factory, "pool-index", lambda *_: AuditedCommandResult(regenerate_index(_output_dir()))).value
    typer.echo(f"已生成索引：{idx}")


# ----------------------------- 观测 -----------------------------


def _audit_view(session_factory) -> AuditViewService:
    return AuditViewService(
        session_factory,
        detail_resolvers=(resolve_news_ingestion_details,),
    )


@task_app.command("list")
def task_list_cmd(
    output_json: bool = typer.Option(False, "--json", help="输出机器可读 JSON"),
    status: str | None = typer.Option(None, "--status", help="执行或设计状态"),
    module: str | None = typer.Option(None, "--module"),
    since: str | None = typer.Option(None, "--since", help="ISO8601 开始时间"),
    until: str | None = typer.Option(None, "--until", help="ISO8601 结束时间"),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
) -> None:
    """按时间倒序查看业务任务主线。"""
    since_value = _parse_task_time(since, "--since")
    until_value = _parse_task_time(until, "--until")
    with app_context(gate=True) as (_engine, session_factory):
        model = _audit_view(session_factory).list_tasks(
            status=status,
            module=module,
            since=since_value,
            until=until_value,
            limit=limit,
        )
    if output_json:
        typer.echo(json.dumps(model, ensure_ascii=False, separators=(",", ":")))
        return
    typer.echo(f"业务任务（{model['count']} 条）")
    for row in model["tasks"]:
        funnel = row["key_funnel"]
        funnel_text = "-" if funnel is None else (
            f"{funnel['stage_key']}:{funnel['input_count']}→{funnel['output_count']} {funnel['unit'] or '-'}"
        )
        typer.echo(
            f"{row['task_id']} {row['created_at']} {row['module']}/{row['operation']} "
            f"operator={row['operator'] or '-'} execution={row['execution_status']} "
            f"design={row['design_status']} funnel={funnel_text}"
        )


@task_app.command("show")
def task_show_cmd(
    task_id: str = typer.Argument(...),
    output_json: bool = typer.Option(False, "--json", help="输出机器可读 JSON"),
) -> None:
    """围绕一个任务展示五要素、阶段、漏斗、设计结论和技术详情。"""
    with app_context(gate=True) as (_engine, session_factory):
        model = _audit_view(session_factory).show_task(task_id)
    if output_json:
        typer.echo(json.dumps(model, ensure_ascii=False, separators=(",", ":")))
        return
    story = model["story"]
    typer.echo(f"任务 {model['task_id']}")
    typer.echo(f"  谁：operator={story['who']['operator'] or '-'} trigger={story['who']['trigger_type']}")
    typer.echo(
        f"  何时：created={story['when']['created_at']} started={story['when']['started_at']} "
        f"finished={story['when']['finished_at']}"
    )
    typer.echo(f"  对象：{json.dumps(story['object'], ensure_ascii=False, separators=(',', ':'))}")
    typer.echo(
        f"  动作：{story['action']['module']}/{story['action']['operation']} "
        f"path={story['action']['path_type']} reason={story['action']['reason'] or '-'}"
    )
    typer.echo(
        f"  结果：execution={story['result']['execution_status']} "
        f"design={story['result']['design_status']} exit={story['result']['exit_code']} "
        f"summary={json.dumps(story['result']['summary'], ensure_ascii=False, separators=(',', ':'))}"
    )
    expected = ", ".join(f"{row['sequence']}:{row['key']}" for row in model["workflow"]["expected"])
    actual = ", ".join(
        f"{row['actual_sequence']}:{row['stage_key']}({row['status']})"
        for row in model["workflow"]["actual"]
    )
    typer.echo(f"  预期阶段：{expected or '-'}")
    typer.echo(f"  实际阶段：{actual or '-'}")
    for funnel in model["funnel"]:
        typer.echo(
            f"  漏斗 {funnel['stage_key']}：{funnel['input_count']}→{funnel['output_count']} "
            f"unit={funnel['unit'] or '-'} routes={json.dumps(funnel['routes'], ensure_ascii=False, separators=(',', ':'))}"
        )
    if model["design"]["deviations"]:
        for deviation in model["design"]["deviations"]:
            typer.echo(
                f"  设计偏差 stage={deviation['stage_key'] or '-'} rule={deviation.get('rule_id')} "
                f"delta={deviation.get('delta')} message={deviation.get('message') or '-'}"
            )
    for detail in model["details"]:
        display = detail["display"]
        typer.echo(f"  详情 {display['section']}：{display['summary']}")
        for line in display["lines"]:
            typer.echo(f"    {line}")


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
