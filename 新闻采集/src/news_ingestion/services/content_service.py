"""正文抓取阶段服务（plan §7：一级识别后抓正文）。"""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from ..logging_setup import get_logger
from ..models import NewsArticle, NewsSource
from ..repositories import ArticleRepository, SourceRepository
from ..types import FetchedContent
from .fulltext import fetch_article_content

_LOG = get_logger(__name__)


def fetch_contents(
    session_factory: sessionmaker,
    *,
    since_hours: float | None,
    user_agent: str,
    max_retries: int = 2,
    limit: int | None = None,
    fetcher=None,
) -> dict:
    stats = {"fetched": 0, "failed": 0, "empty": 0}
    fetcher = fetcher or fetch_article_content
    with session_factory() as session:
        articles = ArticleRepository(session).list_for_fulltext(since_hours)
        if limit:
            articles = articles[:limit]

    for article in articles:
        with session_factory() as session:
            current = session.get(NewsArticle, article.id)
            if current is None or current.content_clean:
                continue
            source = session.get(NewsSource, current.source_id)
            if source is None:
                continue
            fetched = fetcher(current.url, source=source, user_agent=user_agent, max_retries=max_retries)
            if fetched.error:
                stats["failed"] += 1
                ArticleRepository(session).set_content(
                    current.id, content_raw=None, content_clean=None, content_hash=None, fetch_status="failed"
                )
                current.last_error = None  # 文章级错误不入来源；fetch_log 体现
                session.commit()
                _LOG.info("正文抓取失败 %s：%s", current.id, fetched.error)
            elif not fetched.content_clean:
                stats["empty"] += 1
                ArticleRepository(session).set_content(
                    current.id, content_raw=fetched.content_raw, content_clean="", content_hash=None, fetch_status="parsed"
                )
                session.commit()
            else:
                stats["fetched"] += 1
                ArticleRepository(session).set_content(
                    current.id,
                    content_raw=fetched.content_raw,
                    content_clean=fetched.content_clean,
                    content_hash=fetched.content_hash,
                    fetch_status="parsed",
                )
                session.commit()
    _LOG.info("正文抓取完成：%s", stats)
    return stats
