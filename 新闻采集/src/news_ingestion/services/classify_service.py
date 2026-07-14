"""一级轻量识别服务（plan §8.6）。

含传统规则预筛（excluded_keywords → irrelevant，不调 LLM）。
凭据缺失时：``strict=True``（显式 classify）抛 ``LlmNotConfiguredError``；
``strict=False``（run）降级为 ``uncertain`` 并继续。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import sessionmaker

from ..config import RuntimeConfig
from ..errors import LlmNotConfiguredError
from ..llm import LlmClient, classify_light, credentials_present, load_prompt
from ..logging_setup import get_logger
from ..models import NewsArticle, NewsSource
from ..repositories import ArticleRepository, LlmRunRepository
from ..timeutil import utcnow

_LOG = get_logger(__name__)
_LIGHT_VERSION = None


def _light_version() -> str:
    global _LIGHT_VERSION
    if _LIGHT_VERSION is None:
        _LIGHT_VERSION = load_prompt("news_relevance").version
    return _LIGHT_VERSION


def _rule_excluded(article: NewsArticle, source: NewsSource) -> str | None:
    text = f"{article.title or ''} {article.summary or ''}".lower()
    for keyword in source.excluded_keywords or []:
        keyword = keyword.strip().lower()
        if keyword and keyword in text:
            return keyword
    return None


def _resolve_client(provided) -> LlmClient | None:
    if provided is not None:
        return provided
    if credentials_present():
        return LlmClient.from_env()
    return None


def run_classify_light(
    session_factory: sessionmaker,
    *,
    since_hours: float | None,
    runtime: RuntimeConfig,
    client=None,
    strict: bool = False,
    stale: bool = False,
) -> dict:
    """对未判定（或 ``--stale`` 重评旧 irrelevant）的文章跑一级识别。"""
    stats = {
        "processed": 0,
        "relevant": 0,
        "irrelevant": 0,
        "uncertain": 0,
        "rule_excluded": 0,
        "published_before_window": 0,
    }
    published_cutoff = utcnow() - timedelta(hours=since_hours) if since_hours is not None else None
    statuses = ["irrelevant"] if stale else ["pending"]
    with session_factory() as session:
        repo = ArticleRepository(session)
        articles = repo.list_since(since_hours, relevance_in=statuses, not_duplicate=True)

    resolved = _resolve_client(client)
    if resolved is None and strict:
        raise LlmNotConfiguredError("未配置 LLM 凭据，无法执行一级识别")

    for article in articles:
        with session_factory() as session:
            current = session.get(NewsArticle, article.id)
            if current is None or current.duplicate_of:
                continue
            source = session.get(NewsSource, current.source_id)
            if source is None:
                continue
            art_repo = ArticleRepository(session)

            # 首次接入 Feed 时会发现大量历史条目。保留这些元数据用于去重，
            # 但不要把发布时间已超出任务窗口的旧闻送入 LLM，避免无效成本。
            if published_cutoff is not None and current.published_at and current.published_at < published_cutoff:
                art_repo.set_relevance(
                    current.id,
                    status="irrelevant",
                    reason="rule:published_before_window",
                    prompt_version=None,
                )
                session.commit()
                stats["published_before_window"] += 1
                stats["irrelevant"] += 1
                stats["processed"] += 1
                continue

            keyword = _rule_excluded(current, source)
            if keyword:
                art_repo.set_relevance(
                    current.id, status="irrelevant", reason=f"rule:excluded_keyword:{keyword}", prompt_version=None
                )
                session.commit()
                stats["rule_excluded"] += 1
                stats["irrelevant"] += 1
                stats["processed"] += 1
                continue

            if resolved is None:
                art_repo.set_relevance(current.id, status="uncertain", reason="llm_not_configured", prompt_version=None)
                session.commit()
                stats["uncertain"] += 1
                stats["processed"] += 1
                continue

            relevance, parsed, _run = classify_light(
                resolved,
                article=current,
                source=source,
                max_tokens=runtime.llmlight_max_tokens,
                run_repo=LlmRunRepository(session),
            )
            art_repo.set_relevance(
                current.id,
                status=relevance,
                reason=(parsed or {}).get("reason") if parsed else "parse_failed",
                prompt_version=_light_version(),
            )
            session.commit()
            stats[relevance] = stats.get(relevance, 0) + 1
            stats["processed"] += 1
    _LOG.info("一级识别完成：%s", stats)
    return stats
