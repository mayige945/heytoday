"""事件仓储 + LLM 评分物化。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ids import new_id
from ..models import NewsArticle, NewsEvent
from ..timeutil import utcnow

_SCORE_FIELDS = (
    "story_score",
    "discussion_score",
    "knowledge_gain_score",
    "life_relevance_score",
    "value_pluralism_score",
    "audio_fit_score",
)


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, event_id: str) -> NewsEvent | None:
        return self.session.get(NewsEvent, event_id)

    def create(
        self,
        *,
        event_title: str,
        event_summary: str | None = None,
        topic_categories: list[str] | None = None,
        primary_category: str | None = None,
        needs_fact_check: bool = False,
    ) -> NewsEvent:
        event = NewsEvent(
            event_title=event_title,
            event_summary=event_summary,
            topic_categories=list(topic_categories or []),
            primary_category=primary_category,
            needs_fact_check=needs_fact_check,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def set_status(self, event_id: str, status: str) -> None:
        event = self.session.get(NewsEvent, event_id)
        if event is not None:
            event.status = status

    def list_by_llm_status(self, statuses: list[str], limit: int = 500) -> list[NewsEvent]:
        stmt = select(NewsEvent).where(NewsEvent.llm_status.in_(statuses)).limit(limit)
        return list(self.session.scalars(stmt))

    def list_by_review_status(self, statuses: list[str], limit: int = 500) -> list[NewsEvent]:
        stmt = select(NewsEvent).where(NewsEvent.status.in_(statuses)).limit(limit)
        return list(self.session.scalars(stmt.order_by(NewsEvent.created_at.desc())))

    def get_by_id(self, event_id: str) -> NewsEvent | None:
        return self.session.get(NewsEvent, event_id)

    def apply_light_relevance_to_event(self, event: NewsEvent, parsed: dict) -> None:
        """一级结果也可顺手写入 topic_categories / primary_category（如有）。"""
        if parsed.get("topic_categories"):
            event.topic_categories = list(parsed["topic_categories"])
        if parsed.get("primary_category"):
            event.primary_category = parsed["primary_category"]

    def apply_full_scoring(self, event: NewsEvent, parsed: dict, *, model: str, prompt_version: str) -> None:
        """把二级结构化评分物化到事件（plan §8.3）。"""
        event.topic_categories = list(parsed.get("topic_categories") or [])
        event.primary_category = parsed.get("primary_category")
        event.age_assessments = parsed.get("age_assessments") or {}
        for field_name in _SCORE_FIELDS:
            value = parsed.get(field_name)
            if value is not None:
                setattr(event, field_name, float(value))
        event.safety_tier = parsed.get("safety_tier", event.safety_tier)
        event.safety_tags = list(parsed.get("safety_tags") or [])
        event.safety_reason = parsed.get("safety_reason")
        event.safety_uncertain = bool(parsed.get("safety_uncertain", False))
        event.safety_assessments = parsed.get("safety_assessments") or {}
        event.needs_fact_check = bool(parsed.get("needs_fact_check", event.needs_fact_check))
        event.fact_check_targets = list(parsed.get("fact_check_targets") or [])
        event.key_people = list(parsed.get("key_people") or [])
        event.key_conflicts = list(parsed.get("key_conflicts") or [])
        event.child_hook = parsed.get("child_hook")
        event.llm_reason = parsed.get("reason")
        event.event_summary = parsed.get("summary") or event.event_summary
        event.llm_status = "success"
        event.llm_model = model
        event.prompt_version = prompt_version
        event.llm_processed_at = utcnow()

    def mark_llm_failed(self, event: NewsEvent, *, model: str | None, prompt_version: str | None) -> None:
        event.llm_status = "failed"
        if model:
            event.llm_model = model
        if prompt_version:
            event.prompt_version = prompt_version

    def recompute_aggregates(self, event_id: str) -> None:
        """重算 article_ids / source_count / language_count / 发布时间范围。"""
        articles = list(
            self.session.scalars(select(NewsArticle).where(NewsArticle.event_id == event_id))
        )
        if not articles:
            return
        event = self.session.get(NewsEvent, event_id)
        if event is None:
            return
        event.article_ids = [a.id for a in articles]
        event.source_count = len({a.source_id for a in articles})
        langs = {a.language for a in articles if a.language}
        event.language_count = len(langs) if langs else 1
        published = [a.published_at for a in articles if a.published_at]
        if published:
            event.first_published_at = min(published)
            event.latest_published_at = max(published)
