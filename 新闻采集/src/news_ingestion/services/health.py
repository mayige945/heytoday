"""来源健康与采集统计（plan §15 / §17）。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ..models import FetchLog, NewsArticle, NewsSource
from ..timeutil import to_shanghai, utcnow


def source_health(session_factory: sessionmaker) -> dict:
    with session_factory() as session:
        sources = list(session.scalars(select(NewsSource).order_by(NewsSource.unit_code, NewsSource.code)))
        per_source = []
        per_unit: dict[str, dict] = {}
        for source in sources:
            row = {
                "unit_code": source.unit_code,
                "code": source.code,
                "name": source.name,
                "enabled": source.enabled,
                "acquisition_method": source.acquisition_method,
                "access_review_status": source.access_review_status,
                "last_fetch_at": to_shanghai(source.last_fetch_at),
                "last_success_at": to_shanghai(source.last_success_at),
                "consecutive_failures": source.consecutive_failures,
                "last_error": source.last_error,
            }
            per_source.append(row)
            unit = per_unit.setdefault(
                source.unit_code,
                {"unit_code": source.unit_code, "sources": [], "any_enabled": False, "max_failures": 0},
            )
            unit["sources"].append(source.code)
            unit["any_enabled"] = unit["any_enabled"] or source.enabled
            unit["max_failures"] = max(unit["max_failures"], source.consecutive_failures or 0)
        return {"count": len(per_source), "sources": per_source, "units": list(per_unit.values())}


def fetch_logs(session_factory: sessionmaker, *, status: str | None = None, limit: int = 20) -> list[dict]:
    with session_factory() as session:
        stmt = select(FetchLog).order_by(FetchLog.started_at.desc())
        if status:
            stmt = stmt.where(FetchLog.status == status)
        logs = list(session.scalars(stmt.limit(limit)))
        return [
            {
                "id": log.id,
                "source_id": log.source_id,
                "status": log.status,
                "items_found": log.items_found,
                "items_created": log.items_created,
                "errors_count": log.errors_count,
                "error_message": log.error_message,
                "started_at": to_shanghai(log.started_at),
                "finished_at": to_shanghai(log.finished_at),
            }
            for log in logs
        ]


def daily_stats(session_factory: sessionmaker, *, since_hours: float = 24) -> dict:
    cutoff = utcnow() - timedelta(hours=since_hours)
    with session_factory() as session:
        articles = int(session.scalar(select(func.count(NewsArticle.id)).where(NewsArticle.discovered_at >= cutoff)) or 0)
        duplicates = int(session.scalar(select(func.count(NewsArticle.id)).where(NewsArticle.duplicate_of.isnot(None))) or 0)
        logs = list(session.scalars(select(FetchLog).where(FetchLog.started_at >= cutoff)))
        return {
            "since_hours": since_hours,
            "articles": articles,
            "duplicates": duplicates,
            "fetch_runs": len(logs),
            "fetch_success": sum(1 for log in logs if log.status == "success"),
            "fetch_failed": sum(1 for log in logs if log.status == "failed"),
        }
