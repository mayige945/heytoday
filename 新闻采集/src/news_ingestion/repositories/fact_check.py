"""事实核验仓储。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ids import new_id
from ..models import FactCheckRecord
from ..timeutil import utcnow


class FactCheckRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_for_event(self, event_id: str) -> FactCheckRecord | None:
        stmt = (
            select(FactCheckRecord)
            .where(FactCheckRecord.event_id == event_id)
            .order_by(FactCheckRecord.created_at.desc())
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def record(
        self,
        *,
        event_id: str,
        status: str,
        conclusion: str | None,
        evidence_sources: list[dict],
        checker: str,
    ) -> FactCheckRecord:
        record = FactCheckRecord(
            id=new_id("fcr"),
            event_id=event_id,
            status=status,
            conclusion=conclusion,
            evidence_sources=list(evidence_sources or []),
            checker=checker,
        )
        self.session.add(record)
        self.session.flush()
        return record
