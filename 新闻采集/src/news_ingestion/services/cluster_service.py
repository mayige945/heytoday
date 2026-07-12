"""事件聚类阶段服务（plan §7 / §10.4）。

对非重复、relevant/uncertain 的文章做保守确定性聚类，形成事件并绑定。增量安全：
若组内已有绑定事件则复用，否则新建。人工拆分写入 ``data/no_remerge.json`` 禁止重聚。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from ..clustering import cluster_articles
from ..config import FiltersConfig, defaults
from ..logging_setup import get_logger
from ..models import NewsArticle, NewsSource
from ..paths import DATA_DIR
from ..repositories import ArticleRepository, EventRepository, SourceRepository
from ..timeutil import to_utc
from ..types import ClusterArticle

_LOG = get_logger(__name__)
_SCIENCE_CATEGORIES = {"science", "academic_explainer"}
_SCIENCE_TOPIC = "discovery"
_NO_REMERGE_FILE = DATA_DIR / "no_remerge.json"


def _load_forbid_pairs() -> frozenset[frozenset[str]]:
    if not _NO_REMERGE_FILE.exists():
        return frozenset()
    try:
        data = json.loads(_NO_REMERGE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return frozenset()
    pairs: set[frozenset[str]] = set()
    for pair in data.get("forbid", []):
        if isinstance(pair, list) and len(pair) == 2:
            pairs.add(frozenset(pair))
    return frozenset(pairs)


def add_forbid_pair(a_id: str, b_id: str) -> None:
    pairs = set(_load_forbid_pairs())
    pairs.add(frozenset({a_id, b_id}))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _NO_REMERGE_FILE.write_text(
        json.dumps({"forbid": [sorted(p) for p in pairs]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
            since_hours, relevance_in=["relevant", "uncertain"], not_duplicate=True
        )
        sources = {s.code: s for s in SourceRepository(session).list_all()}

    cluster_inputs = [
        _to_cluster_article(a, sources.get(a.source_id)) for a in articles if not a.event_id or True
    ]
    forbid = _load_forbid_pairs()
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
