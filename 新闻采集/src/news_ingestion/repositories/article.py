"""文章仓储。

fetch 阶段按身份键（canonical_url → guid → 清洗 URL → 原始 URL）做增量幂等；
content/title hash、duplicate_of、event_id、relevance 等由各阶段服务单独更新。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import NewsArticle
from ..timeutil import utcnow
from ..types import DiscoveredArticle


class ArticleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, article_id: str) -> NewsArticle | None:
        return self.session.get(NewsArticle, article_id)

    def find_by_identity(
        self,
        *,
        guid: str | None = None,
        canonical_url: str | None = None,
        cleaned_url: str | None = None,
        raw_url: str | None = None,
    ) -> NewsArticle | None:
        conds = []
        if guid:
            conds.append(NewsArticle.guid == guid)
        if canonical_url:
            conds.append(NewsArticle.canonical_url == canonical_url)
        if raw_url:
            conds.append(NewsArticle.url == raw_url)
        if cleaned_url and cleaned_url != raw_url:
            conds.append(NewsArticle.url == cleaned_url)
            conds.append(NewsArticle.canonical_url == cleaned_url)
        if not conds:
            return None
        stmt = select(NewsArticle).where(or_(*conds)).limit(1)
        return self.session.scalars(stmt).first()

    def upsert_discovered(self, item: DiscoveredArticle) -> tuple[NewsArticle, bool]:
        """身份命中则返回既有（不覆盖首次记录），否则新建。返回 (article, created)。"""
        existing = self.find_by_identity(
            guid=item.guid,
            canonical_url=item.canonical_url,
            raw_url=item.url,
        )
        if existing is not None:
            return existing, False

        article = NewsArticle(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            guid=item.guid,
            external_id=item.external_id,
            title=item.title,
            subtitle=item.subtitle,
            summary=item.summary,
            author=item.author,
            section=item.section,
            published_at=item.published_at,
            language=item.language or "",
            image_urls=list(item.image_urls),
            tags=list(item.tags),
            fetch_status="discovered",
            relevance_status="pending",
        )
        self.session.add(article)
        self.session.flush()
        return article, True

    def set_relevance(
        self,
        article_id: str,
        *,
        status: str,
        reason: str | None,
        prompt_version: str | None,
    ) -> None:
        article = self.session.get(NewsArticle, article_id)
        if article is None:
            return
        article.relevance_status = status
        article.relevance_reason = reason
        article.relevance_prompt_version = prompt_version
        article.relevance_processed_at = utcnow()

    def set_content(
        self,
        article_id: str,
        *,
        content_raw: str | None,
        content_clean: str | None,
        content_hash: str | None,
        fetch_status: str = "parsed",
    ) -> None:
        article = self.session.get(NewsArticle, article_id)
        if article is None:
            return
        article.content_raw = content_raw
        article.content_clean = content_clean
        article.content_hash = content_hash
        article.fetch_status = fetch_status
        article.fetched_at = utcnow()

    def set_hashes(self, article_id: str, *, content_hash: str | None, title_hash: str | None) -> None:
        article = self.session.get(NewsArticle, article_id)
        if article is None:
            return
        if content_hash is not None:
            article.content_hash = content_hash
        if title_hash is not None:
            article.title_hash = title_hash

    def mark_duplicate(self, article_id: str, *, duplicate_of: str, basis: str = "") -> None:
        article = self.session.get(NewsArticle, article_id)
        if article is None:
            return
        article.duplicate_of = duplicate_of
        article.duplicate_basis = (basis or "")[:32] or None
        article.fetch_status = "skipped"

    def bind_event(self, article_id: str, event_id: str) -> None:
        article = self.session.get(NewsArticle, article_id)
        if article is not None:
            article.event_id = event_id

    def list_since(
        self,
        since_hours: float | None,
        *,
        relevance_in: list[str] | None = None,
        not_duplicate: bool = True,
    ) -> list[NewsArticle]:
        stmt = select(NewsArticle)
        if since_hours is not None:
            cutoff = utcnow() - timedelta(hours=since_hours)
            stmt = stmt.where(NewsArticle.discovered_at >= cutoff)
        if relevance_in:
            stmt = stmt.where(NewsArticle.relevance_status.in_(relevance_in))
        if not_duplicate:
            stmt = stmt.where(NewsArticle.duplicate_of.is_(None))
        stmt = stmt.order_by(NewsArticle.discovered_at.desc())
        return list(self.session.scalars(stmt))

    def list_for_fulltext(self, since_hours: float | None) -> list[NewsArticle]:
        """需要抓正文的文章：一级 relevant/uncertain、未抓正文、非重复。"""
        stmt = select(NewsArticle).where(
            NewsArticle.relevance_status.in_(["relevant", "uncertain"]),
            NewsArticle.duplicate_of.is_(None),
            NewsArticle.content_clean.is_(None),
        )
        if since_hours is not None:
            cutoff = utcnow() - timedelta(hours=since_hours)
            stmt = stmt.where(NewsArticle.discovered_at >= cutoff)
        return list(self.session.scalars(stmt.order_by(NewsArticle.discovered_at.desc())))

    def list_by_event(self, event_id: str) -> list[NewsArticle]:
        stmt = select(NewsArticle).where(NewsArticle.event_id == event_id)
        return list(self.session.scalars(stmt.order_by(NewsArticle.published_at.asc().nullslast())))
