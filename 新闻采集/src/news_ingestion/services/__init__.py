"""服务编排层入口。"""

from __future__ import annotations

from .audited_command import AuditedCommandResult, AuditedCommandSpec, TriggerContext, run_audited_command

from .audit_service import AuditLifecycleService, TaskOutcome
from .classify_service import run_classify_light
from .cluster_service import run_cluster
from .content_service import fetch_contents
from .dedup_service import run_dedup
from .event_view import build_effective, build_material_event
from .export_service import export_material, regenerate_index
from .fetch_service import fetch_all, fetch_source
from .health import daily_stats, fetch_logs, source_health
from .lock import DatabaseLock, ProcessLock
from .retention_service import prune
from .review_service import (
    approve_event,
    list_events_for_review,
    record_fact_check,
    reject_event,
    require_reviewer,
)
from .run_service import run_pipeline
from .score_service import run_score_full
from .supabase_sync import sync_material

__all__ = [
    "AuditedCommandResult",
    "AuditedCommandSpec",
    "TriggerContext",
    "run_audited_command",
    "AuditLifecycleService",
    "TaskOutcome",
    "ProcessLock",
    "DatabaseLock",
    "approve_event",
    "build_effective",
    "build_material_event",
    "daily_stats",
    "export_material",
    "fetch_all",
    "fetch_contents",
    "fetch_logs",
    "fetch_source",
    "list_events_for_review",
    "prune",
    "regenerate_index",
    "record_fact_check",
    "reject_event",
    "require_reviewer",
    "run_classify_light",
    "run_cluster",
    "run_dedup",
    "run_pipeline",
    "run_score_full",
    "source_health",
    "sync_material",
]
