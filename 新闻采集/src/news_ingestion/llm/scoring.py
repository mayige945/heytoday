"""二级完整识别与结构化评分（plan §8.3 / §8.6 / §8.7）。"""

from __future__ import annotations

import json
from typing import Any

from ..cleaners.text import sha256_hex
from ..models import NewsArticle, NewsEvent, NewsSource
from ..repositories.llm_run import LlmRunRepository
from .client import LlmCallError, LlmClient
from .parsing import call_and_parse
from .prompts import load_prompt


def full_input(
    event: NewsEvent,
    articles: list[NewsArticle],
    sources_by_id: dict[str, NewsSource],
) -> dict[str, Any]:
    def source_name(article: NewsArticle) -> str:
        source = sources_by_id.get(article.source_id)
        return source.name if source is not None else article.source_id

    representative = articles[0] if articles else None
    related = [
        {
            "title": article.title,
            "source": source_name(article),
            "summary": (article.summary or "")[:200],
        }
        for article in articles[1:4]
    ]
    return {
        "event_title": event.event_title,
        "representative_article": {
            "title": representative.title if representative else event.event_title,
            "summary": (representative.summary or "")[:500] if representative else "",
            "content_excerpt": (representative.content_clean or "")[:1200] if representative else "",
            "source": source_name(representative) if representative else "",
            "published_at": representative.published_at.isoformat() if representative and representative.published_at else None,
        },
        "related_articles": related,
        "trend_signals": [],
    }


def score_full(
    client: LlmClient,
    *,
    event: NewsEvent,
    articles: list[NewsArticle],
    sources_by_id: dict[str, NewsSource],
    max_tokens: int,
    run_repo: LlmRunRepository,
) -> tuple[dict | None, Any]:
    """返回 (parsed|None, llm_run)。失败时返回 (None, run)，事件不进入自动导出。"""
    spec = load_prompt("news_scoring")
    user = json.dumps(full_input(event, articles, sources_by_id), ensure_ascii=False)
    input_hash = sha256_hex(user)
    run = run_repo.create(
        mode="full",
        prompt_name=spec.name,
        prompt_version=spec.version,
        schema_version=spec.schema_version,
        input_hash=input_hash,
        event_id=event.id,
        model_name=client.model,
    )

    try:
        parsed, raw, usage, _attempts = call_and_parse(
            client, system=spec.text, user=user, schema_version=spec.schema_version, max_tokens=max_tokens
        )
    except LlmCallError as exc:
        run_repo.mark_failed(run, error=str(exc))
        return None, run

    if parsed is None:
        run_repo.mark_failed(run, error="full: JSON 解析或 Schema 校验失败", raw_response=raw)
        return None, run

    # estimated_cost 暂记 None：Kimi Coding 无公开计价，token_usage（input/output）已完整记录；
    # 取得正式 API 定价后在此按 token_usage × 费率计算即可（schema 允许 null）。
    run_repo.mark_success(run, parsed_result=parsed, raw_response=raw, token_usage=usage, estimated_cost=None)
    return parsed, run
