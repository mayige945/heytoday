"""原始文章表 ``news_article``（plan §9.2）。"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import new_id
from ..timeutil import utcnow
from .base import Base, UTCDateTime


class NewsArticle(Base):
    __tablename__ = "news_article"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("art"))
    source_id: Mapped[str] = mapped_column(ForeignKey("news_source.id", ondelete="RESTRICT"), index=True)

    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    guid: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(2048), index=True)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(512))
    subtitle: Mapped[str | None] = mapped_column(String(512), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_clean: Mapped[str | None] = mapped_column(Text, nullable=True)

    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    section: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True, index=True)
    discovered_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, index=True)
    fetched_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)

    language: Mapped[str] = mapped_column(String(16), default="")
    image_urls: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)

    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    fetch_status: Mapped[str] = mapped_column(String(16), default="discovered", index=True)
    relevance_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    relevance_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    relevance_prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    relevance_processed_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)

    duplicate_of: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    duplicate_basis: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("news_event.id", ondelete="SET NULL"), nullable=True, index=True)

    created_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NewsArticle {self.id} {self.title!r:.40}>"
