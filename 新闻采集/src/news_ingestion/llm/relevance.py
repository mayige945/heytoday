"""一级轻量识别（plan §8.6 / §8.7）。"""

from __future__ import annotations

import json
from typing import Any

from ..cleaners.text import sha256_hex
from ..models import NewsArticle, NewsSource
from ..repositories.llm_run import LlmRunRepository
from .client import LlmCallError, LlmClient
from .parsing import call_and_parse
from .prompts import load_prompt


def light_input(article: NewsArticle, source: NewsSource) -> dict[str, Any]:
    return {
        "title": article.title,
        "summary": (article.summary or "")[:500],
        "source": {
            "name": source.name,
            "category": source.source_category,
            "roles": list(source.source_role or []),
        },
        "section": article.section,
        "language": article.language or source.language,
    }


def classify_light(
    client: LlmClient,
    *,
    article: NewsArticle,
    source: NewsSource,
    max_tokens: int,
    run_repo: LlmRunRepository,
) -> tuple[str, dict | None, Any]:
    """返回 (relevance, parsed|None, llm_run)。失败一律物化 ``uncertain``。"""
    spec = load_prompt("news_relevance")
    user = json.dumps(light_input(article, source), ensure_ascii=False)
    input_hash = sha256_hex(user)
    run = run_repo.create(
        mode="light",
        prompt_name=spec.name,
        prompt_version=spec.version,
        schema_version=spec.schema_version,
        input_hash=input_hash,
        article_id=article.id,
        model_name=client.model,
    )

    try:
        parsed, raw, usage, _attempts = call_and_parse(
            client, system=spec.text, user=user, schema_version=spec.schema_version, max_tokens=max_tokens
        )
    except LlmCallError as exc:
        run_repo.mark_failed(run, error=str(exc))
        return "uncertain", None, run

    if parsed is None:
        run_repo.mark_failed(run, error="light: JSON 解析或 Schema 校验失败", raw_response=raw)
        return "uncertain", None, run

    run_repo.mark_success(run, parsed_result=parsed, raw_response=raw, token_usage=usage, estimated_cost=None)
    relevance = parsed.get("relevance", "uncertain")
    if relevance not in {"relevant", "irrelevant", "uncertain"}:
        relevance = "uncertain"
    return relevance, parsed, run
