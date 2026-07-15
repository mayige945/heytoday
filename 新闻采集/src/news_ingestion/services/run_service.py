"""``run`` 流水线：由单一工作流定义驱动八个业务阶段。"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..audit import FunnelSnapshot, UnitConversion, validate_funnel, validate_workflow
from ..audit.context import audit_log_context
from ..audit.news_ingestion import NEWS_INGESTION_WORKFLOW
from ..config import FiltersConfig, RuntimeConfig, SourceConfig
from ..ids import new_id
from ..llm import credentials_present
from ..logging_setup import get_logger
from ..models import NewsEvent
from ..repositories import FetchLogRepository
from ..timeutil import utcnow
from ..types import FetchOutcome
from .audit_service import AuditLifecycleService, TaskOutcome
from .classify_service import run_classify_light
from .cluster_service import run_cluster
from .content_service import fetch_contents
from .dedup_service import run_dedup
from .fetch_service import fetch_all
from .safety import apply_rule_fallback
from .score_service import run_score_full

_LOG = get_logger(__name__)


@dataclass
class RunResult:
    run_id: str = field(default_factory=lambda: new_id("run"))
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    fetch_outcomes: list[FetchOutcome] = field(default_factory=list)
    dedup: dict = field(default_factory=dict)
    classify: dict = field(default_factory=dict)
    content: dict = field(default_factory=dict)
    cluster: dict = field(default_factory=dict)
    score: dict = field(default_factory=dict)
    safety: dict = field(default_factory=dict)
    llm_configured: bool = True
    execution_status: str = "succeeded"
    design_status: str = "compliant"
    exit_code: int = 0
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "execution_status": self.execution_status,
            "design_status": self.design_status,
            "exit_code": self.exit_code,
            "summary": self.summary,
            "sources": [asdict(outcome) for outcome in self.fetch_outcomes],
            "phases": {
                "dedup": self.dedup,
                "classify": self.classify,
                "content": self.content,
                "cluster": self.cluster,
                "score": self.score,
                "safety": self.safety,
            },
        }


@dataclass(frozen=True, slots=True)
class _StageReport:
    funnel: FunnelSnapshot
    reasons: dict[str, int] = field(default_factory=dict)
    metrics: dict[str, int] = field(default_factory=dict)


def _recover_stale(session_factory: sessionmaker, runtime: RuntimeConfig) -> None:
    with session_factory() as session:
        recovered = FetchLogRepository(session).recover_stale(runtime.stale_run_recovery_minutes)
        if recovered:
            _LOG.warning("恢复 %d 条 stale running 日志为 failed", recovered)
        session.commit()


def _apply_safety_fallback(session_factory: sessionmaker, filters: FiltersConfig) -> dict[str, int]:
    with session_factory() as session:
        event_ids = list(
            session.scalars(select(NewsEvent.id).where(NewsEvent.llm_status == "success"))
        )
    changed = 0
    for event_id in event_ids:
        with session_factory() as session:
            current = session.get(NewsEvent, event_id)
            if current and apply_rule_fallback(current, filters):
                changed += 1
                session.commit()
    return {
        "evaluated": len(event_ids),
        "changed": changed,
        "unchanged": len(event_ids) - changed,
    }


def _summary(result: RunResult) -> dict[str, Any]:
    return {
        "sources_success": sum(1 for outcome in result.fetch_outcomes if outcome.status == "success"),
        "sources_partial": sum(1 for outcome in result.fetch_outcomes if outcome.status == "partial_success"),
        "sources_failed": sum(1 for outcome in result.fetch_outcomes if outcome.status == "failed"),
        "articles_created": sum(outcome.items_created for outcome in result.fetch_outcomes),
        "duplicates": result.dedup.get("duplicates", 0),
        "events_new": result.cluster.get("events_new", 0),
        "events_scored": result.score.get("scored", 0),
        "llm_configured": result.llm_configured,
    }


def _finish_task(audit: AuditLifecycleService | None, task_id: str | None, result: RunResult) -> None:
    if audit is None or task_id is None:
        return
    audit.finish_task(
        task_id,
        TaskOutcome(
            execution_status=result.execution_status,
            design_status=result.design_status,
            exit_code=result.exit_code,
            summary=result.summary,
        ),
    )


def run_pipeline(
    session_factory: sessionmaker,
    *,
    enabled_sources: list[SourceConfig],
    runtime: RuntimeConfig,
    filters: FiltersConfig,
    user_agent: str,
    client=None,
    since_hours: float = 24.0,
    cluster_hours: float = 72.0,
    fetch_interval_seconds: float = 0.0,
    fulltext_limit: int | None = None,
    collector_for=None,
    content_fetcher=None,
    audit_lifecycle: AuditLifecycleService | None = None,
    task_id: str | None = None,
) -> RunResult:
    if (audit_lifecycle is None) != (task_id is None):
        raise ValueError("audit_lifecycle and task_id must be provided together")

    result = RunResult(run_id=task_id) if task_id is not None else RunResult()
    result.llm_configured = client is not None or credentials_present()
    metadata_dedup: dict[str, Any] = {}
    content_dedup: dict[str, Any] = {}

    def fetch_stage() -> _StageReport:
        result.fetch_outcomes = fetch_all(
            session_factory,
            enabled_sources,
            user_agent=user_agent,
            max_retries=runtime.llm_max_retries,
            collector_for=collector_for,
            interval_seconds=fetch_interval_seconds,
        )
        found = sum(outcome.items_found for outcome in result.fetch_outcomes)
        created = sum(outcome.items_created for outcome in result.fetch_outcomes)
        updated = sum(outcome.items_updated for outcome in result.fetch_outcomes)
        skipped = sum(outcome.items_skipped for outcome in result.fetch_outcomes)
        item_failures = sum(len(outcome.errors) for outcome in result.fetch_outcomes)
        return _StageReport(
            FunnelSnapshot(
                unit="article",
                input_count=found,
                output_count=created + updated + skipped,
                routes=(("item_failures", item_failures),),
            ),
            metrics={
                "sources_success": sum(outcome.status == "success" for outcome in result.fetch_outcomes),
                "sources_partial": sum(outcome.status == "partial_success" for outcome in result.fetch_outcomes),
                "sources_failed": sum(outcome.status == "failed" for outcome in result.fetch_outcomes),
                "items_created": created,
                "items_updated": updated,
                "items_skipped": skipped,
            },
        )

    def metadata_dedup_stage() -> _StageReport:
        nonlocal metadata_dedup
        metadata_dedup = run_dedup(session_factory, since_hours=since_hours, filters=filters)
        return _StageReport(
            FunnelSnapshot(
                unit="article",
                input_count=metadata_dedup["checked"],
                output_count=metadata_dedup["retained"],
                routes=(("duplicates", metadata_dedup["duplicates"]),),
            ),
            reasons=dict(metadata_dedup["by_basis"]),
        )

    def classify_stage() -> _StageReport:
        result.classify = run_classify_light(
            session_factory,
            since_hours=since_hours,
            runtime=runtime,
            client=client,
            strict=False,
        )
        return _StageReport(
            FunnelSnapshot(
                unit="article",
                input_count=result.classify["processed"],
                output_count=result.classify["relevant"],
                routes=(
                    ("irrelevant", result.classify["irrelevant"]),
                    ("uncertain", result.classify["uncertain"]),
                ),
            ),
            reasons={
                "rule_excluded": result.classify["rule_excluded"],
                "published_before_window": result.classify["published_before_window"],
            },
        )

    def content_stage() -> _StageReport:
        result.content = fetch_contents(
            session_factory,
            since_hours=since_hours,
            user_agent=user_agent,
            limit=fulltext_limit,
            fetcher=content_fetcher,
        )
        return _StageReport(
            FunnelSnapshot(
                unit="article",
                input_count=result.content["input"],
                output_count=result.content["fetched"],
                routes=(("failed", result.content["failed"]), ("empty", result.content["empty"])),
            )
        )

    def content_dedup_stage() -> _StageReport:
        nonlocal content_dedup
        content_dedup = run_dedup(session_factory, since_hours=since_hours, filters=filters)
        result.dedup = {
            "metadata": metadata_dedup,
            "content": content_dedup,
            "checked": metadata_dedup["checked"] + content_dedup["checked"],
            "duplicates": metadata_dedup["duplicates"] + content_dedup["duplicates"],
            "by_basis": dict(
                Counter(metadata_dedup["by_basis"]) + Counter(content_dedup["by_basis"])
            ),
        }
        return _StageReport(
            FunnelSnapshot(
                unit="article",
                input_count=content_dedup["checked"],
                output_count=content_dedup["retained"],
                routes=(("duplicates", content_dedup["duplicates"]),),
            ),
            reasons=dict(content_dedup["by_basis"]),
        )

    def cluster_stage() -> _StageReport:
        result.cluster = run_cluster(session_factory, since_hours=cluster_hours, filters=filters)
        return _StageReport(
            FunnelSnapshot(
                unit="article",
                input_count=result.cluster["candidate_articles"],
                output_count=result.cluster["articles_grouped"],
                routes=(("unhandled", result.cluster["unhandled"]),),
                conversion=UnitConversion(
                    input_unit="article",
                    output_unit="event",
                    input_count=result.cluster["articles_grouped"],
                    output_count=result.cluster["events_new"] + result.cluster["events_reused"],
                ),
            ),
            metrics={
                "groups": result.cluster["groups"],
                "events_new": result.cluster["events_new"],
                "events_reused": result.cluster["events_reused"],
            },
        )

    def score_stage() -> _StageReport:
        result.score = run_score_full(
            session_factory,
            runtime=runtime,
            client=client,
            strict=False,
            since_hours=since_hours,
        )
        return _StageReport(
            FunnelSnapshot(
                unit="event",
                input_count=result.score["input"],
                output_count=result.score["scored"],
                routes=(("failed", result.score["failed"]), ("skipped", result.score["skipped"])),
            )
        )

    def safety_stage() -> _StageReport:
        result.safety = _apply_safety_fallback(session_factory, filters)
        return _StageReport(
            FunnelSnapshot(
                unit="event",
                input_count=result.safety["evaluated"],
                output_count=result.safety["changed"],
                routes=(("unchanged", result.safety["unchanged"]),),
            )
        )

    handlers: dict[str, Callable[[], _StageReport]] = {
        "fetch": fetch_stage,
        "metadata_dedup": metadata_dedup_stage,
        "classify": classify_stage,
        "content": content_stage,
        "content_dedup": content_dedup_stage,
        "cluster": cluster_stage,
        "score": score_stage,
        "safety": safety_stage,
    }
    workflow_validation = validate_workflow(NEWS_INGESTION_WORKFLOW)
    workflow_keys = [stage.key for stage in NEWS_INGESTION_WORKFLOW.stages]
    if workflow_validation.status != "compliant" or len(workflow_keys) != len(handlers) or set(workflow_keys) != set(handlers):
        raise ValueError("news ingestion workflow definition and handlers do not match")

    if audit_lifecycle is not None and task_id is not None:
        audit_lifecycle.mark_running(task_id)
    _recover_stale(session_factory, runtime)

    for definition in NEWS_INGESTION_WORKFLOW.stages:
        stage_id = (
            audit_lifecycle.start_stage(task_id, definition)
            if audit_lifecycle is not None and task_id is not None
            else None
        )
        try:
            with audit_log_context(
                task_id=task_id,
                stage_id=stage_id,
                audit_module="news_ingestion",
                audit_operation="run",
            ):
                report = handlers[definition.key]()
        except BaseException as exc:
            if audit_lifecycle is not None and task_id is not None and stage_id is not None:
                audit_lifecycle.finish_stage(
                    task_id,
                    stage_id,
                    status="failed",
                    metrics={"exception_type": exc.__class__.__name__},
                    validation={
                        "schema_version": "audit-validation/v1",
                        "status": "incomplete",
                        "results": [],
                    },
                )
                audit_lifecycle.finish_task(
                    task_id,
                    TaskOutcome("failed", "incomplete", 9, summary=_summary(result)),
                )
            raise

        validation = validate_funnel(report.funnel)
        if audit_lifecycle is not None and task_id is not None and stage_id is not None:
            audit_lifecycle.finish_stage(
                task_id,
                stage_id,
                status="succeeded",
                input_count=report.funnel.input_count,
                output_count=report.funnel.output_count,
                routes={
                    "schema_version": "audit-routes/v1",
                    "routes": report.funnel.snapshot()["routes"],
                },
                reasons={
                    "schema_version": "audit-reasons/v1",
                    "reasons": report.reasons,
                },
                metrics={
                    "schema_version": "audit-metrics/v1",
                    "metrics": report.metrics,
                },
                validation=validation.snapshot(),
            )
        if validation.status == "deviation":
            result.execution_status = "partial_success"
            result.design_status = "deviation"
            result.exit_code = 9
            result.summary = _summary(result)
            result.finished_at = utcnow()
            _finish_task(audit_lifecycle, task_id, result)
            _LOG.error("run 在阶段 %s 检出设计偏差，停止后续阶段", definition.key)
            return result

    if not result.llm_configured:
        result.execution_status = "partial_success"
        result.exit_code = 7
    elif result.fetch_outcomes and all(outcome.status == "failed" for outcome in result.fetch_outcomes):
        result.execution_status = "failed"
        result.exit_code = 3
    elif any(outcome.status != "success" for outcome in result.fetch_outcomes):
        result.execution_status = "partial_success"
        result.exit_code = 4
    else:
        result.execution_status = "succeeded"
        result.exit_code = 0

    result.summary = _summary(result)
    result.finished_at = utcnow()
    _finish_task(audit_lifecycle, task_id, result)
    _LOG.info("run 完成：%s", result.summary)
    return result
