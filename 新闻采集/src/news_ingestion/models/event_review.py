"""人工复核表 ``event_review``（plan §9.7）。

``eligible`` 只存在于最新人工复核记录的六组合矩阵（upper_primary/junior_high ×
conservative/standard/open），不由分数或规则自动产生。每次修改保留新记录，
不覆盖历史复核。
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import new_id
from ..timeutil import utcnow
from .base import Base, UTCDateTime


class EventReview(Base):
    __tablename__ = "event_review"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rvw"))
    event_id: Mapped[str] = mapped_column(ForeignKey("news_event.id", ondelete="CASCADE"), index=True)
    review_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reviewer: Mapped[str] = mapped_column(String(128))

    # 六组合 eligibility 矩阵：{upper_primary:{conservative,standard,open}, junior_high:{...}}
    eligibility: Mapped[dict] = mapped_column(JSON, default=dict)
    category_override: Mapped[dict] = mapped_column(JSON, default=dict)
    score_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    safety_override: Mapped[dict] = mapped_column(JSON, default=dict)
    age_assessments_override: Mapped[dict] = mapped_column(JSON, default=dict)
    content_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    reviewed_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EventReview {self.id} {self.event_id} {self.review_status}>"
