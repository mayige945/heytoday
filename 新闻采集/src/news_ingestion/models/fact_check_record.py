"""事实核验表 ``fact_check_record``（plan §9.6）。

``needs_fact_check=true`` 的事件默认 ``pending``；只有人工填写明确结论，并
记录至少一个正式媒体事实源 / 原始来源 URL 后才能转 ``verified``。``pending`` /
``failed`` 不得批准、不得导出。热点雷达来源始终 ``needs_fact_check=true``。
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import new_id
from ..timeutil import utcnow
from .base import Base, UTCDateTime


class FactCheckRecord(Base):
    __tablename__ = "fact_check_record"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("fcr"))
    event_id: Mapped[str] = mapped_column(ForeignKey("news_event.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{url, source_name, source_role, checked_at}]
    evidence_sources: Mapped[list] = mapped_column(JSON, default=list)
    checker: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FactCheckRecord {self.id} {self.event_id} {self.status}>"
