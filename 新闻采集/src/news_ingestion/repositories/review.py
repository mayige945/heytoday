"""人工复核仓储。

每次复核保留新记录、不覆盖历史。``eligible`` 只存在于最新复核记录的六组合矩阵。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ids import new_id
from ..models import EventReview
from ..timeutil import utcnow


class ReviewRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_for_event(self, event_id: str) -> EventReview | None:
        stmt = (
            select(EventReview)
            .where(EventReview.event_id == event_id)
            .order_by(EventReview.created_at.desc())
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def create(
        self,
        *,
        event_id: str,
        review_status: str,
        reviewer: str,
        eligibility: dict | None = None,
        category_override: dict | None = None,
        score_overrides: dict | None = None,
        safety_override: dict | None = None,
        age_assessments_override: dict | None = None,
        content_overrides: dict | None = None,
        rejection_reason: str | None = None,
        note: str | None = None,
    ) -> EventReview:
        review = EventReview(
            id=new_id("rvw"),
            event_id=event_id,
            review_status=review_status,
            reviewer=reviewer,
            eligibility=eligibility or {},
            category_override=category_override or {},
            score_overrides=score_overrides or {},
            safety_override=safety_override or {},
            age_assessments_override=age_assessments_override or {},
            content_overrides=content_overrides or {},
            rejection_reason=rejection_reason,
            note=note,
            reviewed_at=utcnow() if review_status != "pending" else None,
        )
        self.session.add(review)
        self.session.flush()
        return review
