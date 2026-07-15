"""新闻采集完整运行的唯一工作流定义。"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BusinessTask, BusinessTaskStage, FetchLog, LlmRun
from ..paths import log_files
from ..timeutil import to_shanghai, utcnow
from .contracts import StageDefinition, WorkflowDefinition
from .sanitization import redact_secrets


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
def _redact_log_line(line: str) -> str:
    return (redact_secrets(line) or "").rstrip("\r\n")


def _task_log_dates(task: BusinessTask) -> set[date]:
    started = to_shanghai(task.created_at)
    finished = to_shanghai(task.finished_at or utcnow())
    current = started.date()
    end = max(current, finished.date())
    dates: set[date] = set()
    while current <= end:
        dates.add(current)
        current += timedelta(days=1)
    return dates


def _technical_logs(task: BusinessTask, task_id: str) -> dict:
    matches: list[dict] = []
    task_marker = re.compile(rf"(?:^|[\s\[])task={re.escape(task_id)}(?=[\s\]])")
    expired = task.created_at < utcnow() - timedelta(days=_LOG_RETENTION_DAYS)
    for path in log_files(
        rotated_dates=_task_log_dates(task),
        include_current=not expired,
    ):
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
    fetch_logs = session.execute(
        select(
            FetchLog.id,
            FetchLog.audit_stage_id,
            FetchLog.source_id,
            FetchLog.status,
            FetchLog.items_found,
            FetchLog.items_created,
            FetchLog.errors_count,
        )
        .where(FetchLog.audit_task_id == task_id)
        .order_by(FetchLog.started_at)
    ).all()
    llm_runs = session.execute(
        select(
            LlmRun.id,
            LlmRun.audit_stage_id,
            LlmRun.mode,
            LlmRun.status,
            LlmRun.model_name,
            LlmRun.prompt_name,
            LlmRun.prompt_version,
        )
        .where(LlmRun.audit_task_id == task_id)
        .order_by(LlmRun.requested_at)
    ).all()
    fetch_details = [
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
    ]
    llm_details = [
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
    ]
    technical_logs = _technical_logs(task, task_id)
    lines = []
    if technical_logs.get("message"):
        lines.append(f"log_detail={technical_logs['message']}")
    lines.extend(
        f"fetch_log id={row['id']} stage={row['stage_id'] or '-'} "
        f"source={row['source_id']} status={row['status']}"
        for row in fetch_details
    )
    lines.extend(
        f"llm_run id={row['id']} stage={row['stage_id'] or '-'} "
        f"mode={row['mode']} status={row['status']} "
        f"prompt={row['prompt_name']}@{row['prompt_version']}"
        for row in llm_details
    )
    for file_detail in technical_logs.get("files", []):
        lines.extend(
            f"log {file_detail['path']}:{match['line']} "
            f"stage={match['stage_id'] or '-'} {match['text']}"
            for match in file_detail["matches"]
        )
    return {
        "kind": "news_ingestion",
        "fetch_logs": fetch_details,
        "llm_runs": llm_details,
        "technical_logs": technical_logs,
        "display": {
            "section": "news_ingestion",
            "summary": (
                f"fetch_log={len(fetch_details)} llm_run={len(llm_details)} "
                f"logs={technical_logs.get('status', '-')}"
            ),
            "lines": lines,
        },
    }
