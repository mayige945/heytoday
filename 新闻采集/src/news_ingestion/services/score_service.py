"""二级完整评分阶段服务（plan §8.3 / §8.7）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..config import RuntimeConfig
from ..errors import LlmNotConfiguredError
from ..llm import LlmClient, credentials_present, score_full
from ..logging_setup import get_logger
from ..models import NewsEvent, NewsSource
from ..repositories import ArticleRepository, EventRepository, LlmRunRepository, SourceRepository

_LOG = get_logger(__name__)


def _resolve_client(provided) -> LlmClient | None:
    if provided is not None:
        return provided
    if credentials_present():
        return LlmClient.from_env()
    return None


def _events_to_score(session, event_id: str | None, statuses: list[str]) -> list[NewsEvent]:
    if event_id:
        event = session.get(NewsEvent, event_id)
        return [event] if event else []
    return list(session.scalars(select(NewsEvent).where(NewsEvent.llm_status.in_(statuses))))


def run_score_full(
    session_factory: sessionmaker,
    *,
    runtime: RuntimeConfig,
    client=None,
    strict: bool = False,
    event_id: str | None = None,
    retry_failed: bool = False,
) -> dict:
    stats = {"scored": 0, "failed": 0, "skipped": 0}
    resolved = _resolve_client(client)
    if resolved is None and strict:
        raise LlmNotConfiguredError("未配置 LLM 凭据，无法执行二级评分")

    statuses = ["pending", "failed"] if retry_failed else ["pending"]
    with session_factory() as session:
        events = _events_to_score(session, event_id, statuses)

    for event in events:
        if resolved is None:
            stats["skipped"] += 1
            continue
        with session_factory() as session:
            current = session.get(NewsEvent, event.id)
            if current is None:
                continue
            articles = ArticleRepository(session).list_by_event(current.id)
            if not articles:
                stats["skipped"] += 1
                continue
            sources_by_id = {s.code: s for s in SourceRepository(session).list_all()}
            parsed, run = score_full(
                resolved,
                event=current,
                articles=articles,
                sources_by_id=sources_by_id,
                max_tokens=runtime.llmfull_max_tokens,
                run_repo=LlmRunRepository(session),
            )
            evt_repo = EventRepository(session)
            if parsed is not None:
                evt_repo.apply_full_scoring(current, parsed, model=resolved.model, prompt_version=run.prompt_version)
                current.status = "needs_review"
                stats["scored"] += 1
            else:
                evt_repo.mark_llm_failed(current, model=resolved.model, prompt_version=run.prompt_version)
                stats["failed"] += 1
            session.commit()
    _LOG.info("二级评分完成：%s", stats)
    return stats
