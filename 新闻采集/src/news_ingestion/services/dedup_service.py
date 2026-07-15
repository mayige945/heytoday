"""去重阶段服务（plan §10）：URL → 标题 → 内容（SHA-256 / SimHash）。

幂等：已标 ``duplicate_of`` 的文章跳过；未标记的与「已确认非重复」池比较。
"""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from ..cleaners.text import title_fingerprint
from ..config import FiltersConfig
from ..dedup import build_candidate_from_content, find_duplicate
from ..logging_setup import get_logger
from ..models import NewsArticle
from ..repositories import ArticleRepository
from ..types import DedupCandidate

_LOG = get_logger(__name__)


def _to_candidate(article: NewsArticle, filters: FiltersConfig) -> DedupCandidate:
    bits = filters.content_dedup.simhash_hash_bits
    candidate = build_candidate_from_content(
        article.id,
        url=article.url,
        canonical_url=article.canonical_url,
        title=article.title,
        content_clean=article.content_clean,
        bits=bits,
    )
    candidate.title_fingerprint = title_fingerprint(article.title)
    candidate.urls = [u for u in ([article.canonical_url, article.url] if article.canonical_url else [article.url]) if u]
    return candidate


def run_dedup(session_factory: sessionmaker, *, since_hours: float | None, filters: FiltersConfig) -> dict:
    """执行去重；返回统计 {checked, duplicates, by_basis}。"""
    stats = {"checked": 0, "duplicates": 0, "retained": 0, "by_basis": {}}
    with session_factory() as session:
        repo = ArticleRepository(session)
        targets = repo.list_since(since_hours, not_duplicate=True)
        target_ids = {article.id for article in targets}
        articles = repo.list_since(None, not_duplicate=True)
        articles.sort(key=lambda a: (a.discovered_at is None, a.discovered_at, a.id))
        canonical = [
            _to_candidate(article, filters)
            for article in articles
            if article.id not in target_ids
        ]
        for current in (article for article in articles if article.id in target_ids):
            candidate = _to_candidate(current, filters)
            decision = find_duplicate(candidate, canonical, filters=filters)
            stats["checked"] += 1
            if decision.is_duplicate and decision.duplicate_of:
                repo.mark_duplicate(
                    current.id, duplicate_of=decision.duplicate_of, basis=decision.basis
                )
                current.title_hash = candidate.title_fingerprint
                stats["duplicates"] += 1
                stats["by_basis"][decision.basis] = stats["by_basis"].get(decision.basis, 0) + 1
                _LOG.info("去重命中 %s → %s（%s）", current.id, decision.duplicate_of, decision.basis)
                continue
            current.title_hash = candidate.title_fingerprint
            if current.content_hash is None and candidate.content_hash:
                current.content_hash = candidate.content_hash
            canonical.append(candidate)
        session.commit()
    stats["retained"] = stats["checked"] - stats["duplicates"]
    _LOG.info("去重完成：%s", stats)
    return stats
