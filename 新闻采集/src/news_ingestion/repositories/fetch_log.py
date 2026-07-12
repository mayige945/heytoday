"""采集日志仓储 + stale 恢复。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ids import new_id
from ..models import FetchLog
from ..timeutil import utcnow
from ..types import FetchOutcome


class FetchLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start(self, source_id: str) -> FetchLog:
        log = FetchLog(id=new_id("flg"), source_id=source_id, status="running", started_at=utcnow())
        self.session.add(log)
        self.session.flush()
        return log

    def finish(self, log_id: str, outcome: FetchOutcome) -> None:
        log = self.session.get(FetchLog, log_id)
        if log is None:
            return
        log.status = outcome.status
        log.finished_at = utcnow()
        log.items_found = outcome.items_found
        log.items_created = outcome.items_created
        log.items_updated = outcome.items_updated
        log.items_skipped = outcome.items_skipped
        log.errors_count = len(outcome.errors)
        msg = outcome.error_message or ("\n".join(outcome.errors[:5]) if outcome.errors else None)
        log.error_message = msg[:1024] if msg else None
        log.metadata_ = dict(outcome.metadata)

    def list(self, *, status: str | None = None, limit: int = 100) -> list[FetchLog]:
        stmt = select(FetchLog).order_by(FetchLog.started_at.desc())
        if status:
            stmt = stmt.where(FetchLog.status == status)
        return list(self.session.scalars(stmt.limit(limit)))

    def recover_stale(self, stale_minutes: int) -> int:
        """把超时仍 running 的日志标 failed(stale_run_recovered)，返回处理条数。"""
        threshold = utcnow() - timedelta(minutes=stale_minutes)
        stmt = select(FetchLog).where(FetchLog.status == "running", FetchLog.started_at < threshold)
        count = 0
        for log in self.session.scalars(stmt):
            log.status = "failed"
            log.finished_at = utcnow()
            log.error_message = "stale_run_recovered"
            count += 1
        return count
