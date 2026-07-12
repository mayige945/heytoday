"""事件有效视图：DB 原值 + 人工 override 合并（plan §9.7 / §9.8 v0.5）。

review 与 export 共用，保证「合并后的有效事件」一致。``safety_override`` 只允许更严
（红线永不可放宽），或补证据后解除 uncertain。
"""

from __future__ import annotations

from typing import Any

from ..errors import BusinessPreconditionError
from ..models import EventReview, NewsArticle, NewsEvent, NewsSource

_SAFETY_RANK = {"default": 1, "sensitive": 2, "redline": 3}
_PLACEHOLDER = {"", "无", "无内容", "todo", "tbd", "n/a", "待补充", "占位", "placeholder"}


def _can_override_safety(current: str, new: str) -> bool:
    if current == "redline":
        return new == "redline"
    if current == "uncertain":
        return new in {"default", "sensitive", "redline", "uncertain"}
    return _SAFETY_RANK.get(new, 0) >= _SAFETY_RANK.get(current, 0)


def _is_placeholder(value: str | None) -> bool:
    return value is None or str(value).strip().lower() in _PLACEHOLDER


def build_effective(event: NewsEvent, review: EventReview | None) -> dict[str, Any]:
    """合并数据库原值与最新人工 override，返回有效事件字段。"""
    review = review or EventReview(event_id=event.id, reviewer="")
    content = review.content_overrides or {}
    category = review.category_override or {}
    scores_override = review.score_overrides or {}
    age_override = review.age_assessments_override or {}
    safety_override = review.safety_override or {}

    title = content.get("title") or event.event_title
    summary = content.get("summary") or event.event_summary
    child_hook = content.get("child_hook") or event.child_hook
    safety_reason = content.get("safety_reason") or event.safety_reason

    primary_category = category.get("primary_category") or event.primary_category
    topic_categories = category.get("topic_categories") or event.topic_categories or []

    scores = {
        "story_score": event.story_score,
        "discussion_score": event.discussion_score,
        "knowledge_gain_score": event.knowledge_gain_score,
        "life_relevance_score": event.life_relevance_score,
        "value_pluralism_score": event.value_pluralism_score,
        "audio_fit_score": event.audio_fit_score,
    }
    scores.update({k: v for k, v in scores_override.items() if v is not None})

    age_assessments = age_override or event.age_assessments or {}

    safety_tier = event.safety_tier
    safety_tags = list(event.safety_tags or [])
    safety_uncertain = bool(event.safety_uncertain)
    safety_assessments = dict(event.safety_assessments or {})
    if safety_override:
        new_tier = safety_override.get("safety_tier")
        if new_tier:
            if not _can_override_safety(safety_tier, new_tier):
                raise BusinessPreconditionError(
                    f"safety_override 试图把 {safety_tier!r} 放宽为 {new_tier!r}（只允许更严或解除 uncertain）"
                )
            safety_tier = new_tier
        if "safety_tags" in safety_override:
            safety_tags = list(safety_override.get("safety_tags") or [])
        if "safety_reason" in safety_override and safety_override.get("safety_reason"):
            safety_reason = safety_override["safety_reason"]
        if "safety_uncertain" in safety_override:
            safety_uncertain = bool(safety_override.get("safety_uncertain"))
        if "safety_assessments" in safety_override:
            safety_assessments = dict(safety_override.get("safety_assessments") or {})

    return {
        "title": title,
        "summary": summary,
        "child_hook": child_hook,
        "safety_reason": safety_reason,
        "primary_category": primary_category,
        "topic_categories": list(topic_categories),
        "scores": scores,
        "age_assessments": age_assessments,
        "safety_tier": safety_tier,
        "safety_tags": safety_tags,
        "safety_uncertain": safety_uncertain,
        "safety_assessments": safety_assessments,
    }


def _source_view(article: NewsArticle, source: NewsSource | None) -> dict[str, Any]:
    role = ", ".join(source.source_role) if source and source.source_role else (source.source_category if source else "unknown")
    return {
        "name": source.name if source else article.source_id,
        "role": role,
        "url": article.url,
        "published_at": article.published_at.isoformat() if article.published_at else None,
    }


def build_material_event(
    event: NewsEvent,
    review: EventReview | None,
    articles: list[NewsArticle],
    sources_by_id: dict[str, NewsSource],
) -> dict[str, Any] | None:
    """v0.5 新闻素材库单事件视图。

    入选：非红线、非重复、**未被人工 rejected**；不要求 fact-check verified、不要求 approved、
    不做家长档×年龄档筛选。所有结构化字段作为参考标签保留。
    """
    if review is not None and review.review_status == "rejected":
        return None
    if not articles:
        return None
    effective = build_effective(event, review)
    if effective["safety_tier"] == "redline":
        return None  # 采集阶段唯一硬过滤
    if not effective.get("primary_category"):
        return None  # 未评分事件不作为「已评估素材」入库

    sources = [_source_view(a, sources_by_id.get(a.source_id)) for a in articles if not a.duplicate_of]
    if not sources:
        sources = [_source_view(articles[0], sources_by_id.get(articles[0].source_id))]

    review_view = None
    if review is not None and review.review_status in ("approved", "rejected"):
        review_view = {
            "status": review.review_status,
            "reviewer": review.reviewer,
            "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
            "note": review.note,
        }

    return {
        "event_id": event.id,
        "title": effective["title"] or event.event_title,
        "summary": effective["summary"] or "",
        "primary_category": effective["primary_category"],
        "topic_categories": effective["topic_categories"],
        "child_hook": effective["child_hook"] or "",
        "age_assessments": effective["age_assessments"],
        "safety_tier": effective["safety_tier"],
        "safety_tags": effective["safety_tags"],
        "safety_reason": effective["safety_reason"] or "",
        "needs_fact_check": bool(event.needs_fact_check),
        "fact_check_targets": list(event.fact_check_targets or []),
        "source_count": len({a.source_id for a in articles}),
        "sources": sources,
        "scores": effective["scores"],
        "human_review": review_view,
    }
