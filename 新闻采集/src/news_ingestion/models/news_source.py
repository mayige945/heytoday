"""新闻源表 ``news_source``（plan §9.1）。"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import new_id
from ..timeutil import utcnow
from .base import Base, UTCDateTime


class NewsSource(Base):
    __tablename__ = "news_source"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    unit_code: Mapped[str] = mapped_column(String(16), index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    homepage_url: Mapped[str] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(16))
    country_or_region: Mapped[str] = mapped_column(String(64), default="")
    source_category: Mapped[str] = mapped_column(String(32), index=True)
    source_role: Mapped[list] = mapped_column(JSON, default=list)
    acquisition_method: Mapped[str] = mapped_column(String(16), index=True)
    feed_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    list_page_urls: Mapped[list] = mapped_column(JSON, default=list)
    rsshub_route: Mapped[str | None] = mapped_column(String(512), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    access_review_status: Mapped[str] = mapped_column(String(16), default="uncertain", index=True)
    access_reviewed_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)
    access_evidence_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    request_interval_seconds: Mapped[float] = mapped_column(Float, default=5.0)
    max_concurrency_per_host: Mapped[int] = mapped_column(Integer, default=1)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=20.0)
    max_redirects: Mapped[int] = mapped_column(Integer, default=5)
    max_response_bytes: Mapped[int] = mapped_column(Integer, default=5_000_000)
    allowed_content_types: Mapped[list] = mapped_column(JSON, default=list)

    topic_tags: Mapped[list] = mapped_column(JSON, default=list)
    allowed_sections: Mapped[list] = mapped_column(JSON, default=list)
    excluded_sections: Mapped[list] = mapped_column(JSON, default=list)
    excluded_keywords: Mapped[list] = mapped_column(JSON, default=list)

    requires_fulltext_fetch: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_fact_check: Mapped[bool] = mapped_column(Boolean, default=False)
    commercial_use_note: Mapped[str | None] = mapped_column(String(512), nullable=True)

    last_fetch_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)
    last_success_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NewsSource {self.unit_code}/{self.code} enabled={self.enabled}>"
