"""新闻采集完整运行的唯一工作流定义。"""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BusinessTask, BusinessTaskStage, FetchLog, LlmRun
from ..paths import log_files
from ..timeutil import utcnow
from .contracts import StageDefinition, WorkflowDefinition


NEWS_INGESTION_WORKFLOW = WorkflowDefinition(
    name="news_ingestion.run",
    version="1",
    stages=(
        StageDefinition("fetch", 1, unit="article"),
        StageDefinition("metadata_dedup", 2, unit="article", prerequisites=("fetch",)),
        StageDefinition("classify", 3, unit="article", prerequisites=("metadata_dedup",)),
        StageDefinition("content", 4, unit="article", prerequisites=("classify",)),
        StageDefinition("content_dedup", 5, unit="article", prerequisites=("content",)),
        StageDefinition("cluster", 6, unit="article", prerequisites=("content_dedup",)),
        StageDefinition("score", 7, unit="event", prerequisites=("cluster",)),
        StageDefinition("safety", 8, unit="event", prerequisites=("score",)),
    ),
)

_LOG_RETENTION_DAYS = 30
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,\]]+"),
    re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s,\]]+"),
    re.compile(r"(?i)(cookie\s*[:=]\s*)[^\s,\]]+"),
    re.compile(r"(?i)((?:api[\s_-]?key)\s*[:=]\s*)[^\s,\]]+"),
)


def _redact_log_line(line: str) -> str:
    for pattern in _SECRET_PATTERNS:
        line = pattern.sub(r"\1[REDACTED]", line)
    return line.rstrip("\r\n")


def _technical_logs(task: BusinessTask, task_id: str) -> dict:
    matches: list[dict] = []
    task_marker = re.compile(rf"(?:^|[\s\[])task={re.escape(task_id)}(?=[\s\]])")
    for path in log_files():
        excerpts: list[dict] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if task_marker.search(line):
                        stage_match = re.search(r"(?:^|[\s\[])stage=([^\s\]]+)", line)
                        excerpts.append(
                            {
                                "line": line_number,
                                "stage_id": None if stage_match is None or stage_match.group(1) == "-" else stage_match.group(1),
                                "text": _redact_log_line(line),
                            }
                        )
                        if len(excerpts) >= 200:
                            break
        except OSError:
            continue
        if excerpts:
            matches.append({"path": str(path), "matches": excerpts})
    if matches:
        return {"status": "available", "retention_days": _LOG_RETENTION_DAYS, "files": matches}
    expired = task.created_at < utcnow() - timedelta(days=_LOG_RETENTION_DAYS)
    return {
        "status": "expired" if expired else "unavailable",
        "retention_days": _LOG_RETENTION_DAYS,
        "message": "详情已过期" if expired else "未找到关联技术日志",
        "files": [],
    }


def resolve_news_ingestion_details(
    session: Session,
    task_id: str,
    _stages: list[BusinessTaskStage],
) -> dict | None:
    """新闻采集详情适配器；通用读模型只调用注册接口。"""
    task = session.get(BusinessTask, task_id)
    if task is None or task.module != "news_ingestion":
        return None
    fetch_logs = list(
        session.scalars(select(FetchLog).where(FetchLog.audit_task_id == task_id).order_by(FetchLog.started_at))
    )
    llm_runs = list(
        session.scalars(select(LlmRun).where(LlmRun.audit_task_id == task_id).order_by(LlmRun.requested_at))
    )
    return {
        "kind": "news_ingestion",
        "fetch_logs": [
            {
                "id": row.id,
                "stage_id": row.audit_stage_id,
                "source_id": row.source_id,
                "status": row.status,
                "items_found": row.items_found,
                "items_created": row.items_created,
                "errors_count": row.errors_count,
            }
            for row in fetch_logs
        ],
        "llm_runs": [
            {
                "id": row.id,
                "stage_id": row.audit_stage_id,
                "mode": row.mode,
                "status": row.status,
                "model_name": row.model_name,
                "prompt_name": row.prompt_name,
                "prompt_version": row.prompt_version,
            }
            for row in llm_runs
        ],
        "technical_logs": _technical_logs(task, task_id),
    }
