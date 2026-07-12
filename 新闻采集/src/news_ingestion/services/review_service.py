"""人工复核 + 事实核验（v0.5：可选策展，非 gate）。

- ``reviewer``/``checker`` 必须取自 ``--reviewer`` 或 ``NEWS_REVIEWER``，缺失拒绝；
- ``approve`` = 可选策展（事件默认已进素材库）；``reject`` = 把事件剔出素材库；
  **不再要求六组合矩阵、不再要求 fact-check verified、不再做 news-pool Schema 闸门**；
- ``safety_override`` 只许更严（红线永不可放宽，build_effective 内部校验）；
- ``fact-check`` 为可选标注（写稿阶段用），不影响入素材库；
- 每次复核/核验保留新记录，不覆盖历史。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..errors import BusinessPreconditionError
from ..logging_setup import get_logger
from ..models import EventReview, FactCheckRecord, NewsEvent
from ..repositories import FactCheckRepository, ReviewRepository
from ..timeutil import utcnow
from .event_view import build_effective

_LOG = get_logger(__name__)


def require_reviewer(value: str | None) -> str:
    reviewer = (value or "").strip()
    if not reviewer:
        raise BusinessPreconditionError("缺少 reviewer：请用 --reviewer 或设置 NEWS_REVIEWER")
    return reviewer


def approve_event(
    session_factory: sessionmaker,
    event_id: str,
    *,
    reviewer: str,
    eligibility: dict | None = None,  # v0.5：兼容旧调用，已不再是 gate（矩阵下移选题）
    category_override: dict | None = None,
    score_overrides: dict | None = None,
    safety_override: dict | None = None,
    age_assessments_override: dict | None = None,
    content_overrides: dict | None = None,
    note: str | None = None,
) -> EventReview:
    """v0.5：approve 是可选策展（事件默认已进素材库）。只保留 safety_override「只许更严」校验；
    不再要求六组合矩阵、不再要求 fact-check verified、不再做 news-pool Schema 闸门。"""
    reviewer = require_reviewer(reviewer)
    with session_factory() as session:
        event = session.get(NewsEvent, event_id)
        if event is None:
            raise BusinessPreconditionError(f"事件不存在：{event_id}")

        # safety_override 只许更严（build_effective 内部会拒绝放宽红线/降严）
        draft_review = EventReview(
            event_id=event_id,
            review_status="approved",
            reviewer=reviewer,
            safety_override=safety_override or {},
            category_override=category_override or {},
            score_overrides=score_overrides or {},
            age_assessments_override=age_assessments_override or {},
            content_overrides=content_overrides or {},
            note=note,
            reviewed_at=utcnow(),
        )
        build_effective(event, draft_review)  # 触发 safety_override 校验（放宽则抛 BusinessPreconditionError）

        review = ReviewRepository(session).create(
            event_id=event_id,
            review_status="approved",
            reviewer=reviewer,
            category_override=category_override or {},
            score_overrides=score_overrides or {},
            safety_override=safety_override or {},
            age_assessments_override=age_assessments_override or {},
            content_overrides=content_overrides or {},
            note=note,
        )
        session.commit()
        _LOG.info("事件 %s 已 approved（可选策展，reviewer=%s）", event_id, reviewer)
        return review


def reject_event(
    session_factory: sessionmaker,
    event_id: str,
    *,
    reviewer: str,
    rejection_reason: str | None = None,
    note: str | None = None,
) -> EventReview:
    reviewer = require_reviewer(reviewer)
    with session_factory() as session:
        event = session.get(NewsEvent, event_id)
        if event is None:
            raise BusinessPreconditionError(f"事件不存在：{event_id}")
        review = ReviewRepository(session).create(
            event_id=event_id,
            review_status="rejected",
            reviewer=reviewer,
            rejection_reason=rejection_reason,
            note=note,
        )
        event.status = "rejected"  # export 按 status != rejected 过滤
        session.commit()
        return review


def record_fact_check(
    session_factory: sessionmaker,
    event_id: str,
    *,
    reviewer: str,
    status: str,
    conclusion: str | None = None,
    evidence_sources: list[dict] | None = None,
) -> FactCheckRecord:
    checker = require_reviewer(reviewer)
    if status not in ("pending", "verified", "failed"):
        raise BusinessPreconditionError(f"非法事实核验状态：{status}")
    evidence_sources = evidence_sources or []
    if status == "verified":
        valid = [e for e in evidence_sources if isinstance(e, dict) and str(e.get("url", "")).strip()]
        if not valid:
            raise BusinessPreconditionError("verified 需至少一个带 URL 的正式媒体事实源 / 原始来源证据")
    with session_factory() as session:
        event = session.get(NewsEvent, event_id)
        if event is None:
            raise BusinessPreconditionError(f"事件不存在：{event_id}")
        record = FactCheckRepository(session).record(
            event_id=event_id,
            status=status,
            conclusion=conclusion,
            evidence_sources=evidence_sources,
            checker=checker,
        )
        session.commit()
        return record


def list_events_for_review(session_factory: sessionmaker, *, review_status: str = "pending") -> list[dict]:
    with session_factory() as session:
        if review_status == "pending":
            events = list(
                session.scalars(
                    select(NewsEvent).where(NewsEvent.status.in_(["new", "needs_review"])).order_by(NewsEvent.created_at.desc())
                )
            )
        else:
            events = list(session.scalars(select(NewsEvent).where(NewsEvent.status == review_status)))
        result = []
        for event in events:
            latest = ReviewRepository(session).latest_for_event(event.id)
            result.append(
                {
                    "event_id": event.id,
                    "title": event.event_title,
                    "status": event.status,
                    "llm_status": event.llm_status,
                    "safety_tier": event.safety_tier,
                    "primary_category": event.primary_category,
                    "needs_fact_check": event.needs_fact_check,
                    "review_status": latest.review_status if latest else "pending",
                    "article_count": len(event.article_ids or []),
                }
            )
        return result
