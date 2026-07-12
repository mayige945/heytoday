"""新闻事件表 ``news_event``（plan §9.3）。

事件是 LLM 二级识别的对象；结构化评分、安全分级、两档年龄适配与事实核验点
均落在此表。``eligible`` 不在此表，只存在于最新人工复核记录的六组合矩阵。
"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import new_id
from ..timeutil import utcnow
from .base import Base, UTCDateTime


class NewsEvent(Base):
    __tablename__ = "news_event"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("evt"))
    event_title: Mapped[str] = mapped_column(String(512))
    event_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    topic_categories: Mapped[list] = mapped_column(JSON, default=list)
    primary_category: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    article_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    language_count: Mapped[int] = mapped_column(Integer, default=1)

    first_published_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True, index=True)
    latest_published_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)

    heat_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    age_assessments: Mapped[dict] = mapped_column(JSON, default=dict)
    story_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    discussion_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    knowledge_gain_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    life_relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_pluralism_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    safety_tier: Mapped[str] = mapped_column(String(16), default="uncertain", index=True)
    safety_tags: Mapped[list] = mapped_column(JSON, default=list)
    safety_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    safety_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    safety_assessments: Mapped[dict] = mapped_column(JSON, default=dict)
    needs_fact_check: Mapped[bool] = mapped_column(Boolean, default=False)
    fact_check_targets: Mapped[list] = mapped_column(JSON, default=list)
    key_people: Mapped[list] = mapped_column(JSON, default=list)
    key_conflicts: Mapped[list] = mapped_column(JSON, default=list)
    child_hook: Mapped[str | None] = mapped_column(String(512), nullable=True)
    llm_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    llm_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_processed_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="new", index=True)

    created_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NewsEvent {self.id} {self.event_title!r:.40}>"
