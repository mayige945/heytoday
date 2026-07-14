"""事件聚类阶段服务（plan §7 / §10.4）。

对非重复、relevant/uncertain 的文章做保守确定性聚类，形成事件并绑定。增量安全：
若组内已有绑定事件则复用，否则新建。人工拆分关系持久化到 Supabase，禁止重聚。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from ..clustering import cluster_articles
from ..config import FiltersConfig, defaults
from ..logging_setup import get_logger
from ..models import NewsArticle, NewsSource
from ..repositories import ArticleRepository, ClusterForbidRepository, EventRepository, SourceRepository
from ..timeutil import to_utc
from ..types import ClusterArticle

_LOG = get_logger(__name__)
_SCIENCE_CATEGORIES = {"science", "academic_explainer"}
_SCIENCE_TOPIC = "discovery"
def add_forbid_pair(session_factory: sessionmaker, a_id: str, b_id: str, *, reason: str | None = None) -> None:
    with session_factory() as session:
        ClusterForbidRepository(session).add(a_id, b_id, reason=reason)
        session.commit()


def _to_cluster_article(article: NewsArticle, source: NewsSource | None) -> ClusterArticle:
    moment = article.published_at or article.discovered_at or datetime.now(timezone.utc)
    is_science = bool(source and source.source_category in _SCIENCE_CATEGORIES)
    # 社会类来源多对应持续发展的社会事件 → 用 7 天「持续事件」窗口
    is_ongoing = bool(source and source.source_category == "society")
    return ClusterArticle(
        id=article.id,
        title=article.title,
        time=to_utc(moment),
        is_science=is_science,
        is_ongoing=is_ongoing,
        source_tags=list(source.topic_tags or []) if source else [],
        language=article.language or (source.language if source else ""),
    )


def run_cluster(session_factory: sessionmaker, *, since_hours: float | None, filters: FiltersConfig) -> dict:
    stats = {"events_new": 0, "events_reused": 0, "articles_grouped": 0, "groups": 0}
    with session_factory() as session:
        articles = ArticleRepository(session).list_since(
            since_hours,
            relevance_in=["relevant", "uncertain"],
            not_duplicate=True,
            published_within=True,
        )
        sources = {s.code: s for s in SourceRepository(session).list_all()}

    cluster_inputs = [
        _to_cluster_article(a, sources.get(a.source_id)) for a in articles if not a.event_id or True
    ]
    with session_factory() as session:
        forbid = ClusterForbidRepository(session).list_pairs()
    groups = cluster_articles(cluster_inputs, filters=filters, forbid_pairs=forbid)
    stats["groups"] = len(groups)

    for group_ids in groups:
        if not group_ids:
            continue
        with session_factory() as session:
            art_repo = ArticleRepository(session)
            evt_repo = EventRepository(session)
            existing_event_id = None
            for aid in group_ids:
                linked = session.get(NewsArticle, aid)
                if linked and linked.event_id:
                    existing_event_id = linked.event_id
                    break

            representative = session.get(NewsArticle, group_ids[0])
            if existing_event_id:
                event = evt_repo.get(existing_event_id)
                stats["events_reused"] += 1
            else:
                group_sources = [sources.get(session.get(NewsArticle, aid).source_id) for aid in group_ids if session.get(NewsArticle, aid)]
                needs_fact_check = any(
                    (s and (s.requires_fact_check or s.unit_code == defaults.TREND_RADAR_UNIT_CODE))
                    for s in group_sources
                )
                event = evt_repo.create(
                    event_title=(representative.title if representative else "未命名事件"),
                    needs_fact_check=needs_fact_check,
                )
                stats["events_new"] += 1
            if event is None:
                continue
            for aid in group_ids:
                art_repo.bind_event(aid, event.id)
                stats["articles_grouped"] += 1
            evt_repo.recompute_aggregates(event.id)
            session.commit()
    _LOG.info("聚类完成：%s", stats)
    return stats
