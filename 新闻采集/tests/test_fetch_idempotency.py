"""重复采集幂等与跨运行去重的数据库行为。"""

from __future__ import annotations

from datetime import timedelta

from news_ingestion.config import FiltersConfig
from news_ingestion.models import NewsArticle
from news_ingestion.repositories import ArticleRepository, ClusterForbidRepository
from news_ingestion.services import run_dedup
from news_ingestion.timeutil import utcnow

from conftest import make_discovered


def test_same_source_guid_is_idempotent_when_url_changes(session_factory, seeded_sources):
    source_id = next(iter(seeded_sources))
    first = make_discovered(
        source_id=source_id,
        guid="stable-guid",
        url="https://example.com/first",
        title="同一条新闻",
    )
    changed_url = make_discovered(
        source_id=source_id,
        guid="stable-guid",
        url="https://example.com/second",
        title="同一条新闻更新链接",
    )

    with session_factory() as session:
        repo = ArticleRepository(session)
        original, first_created = repo.upsert_discovered(first)
        repeated, second_created = repo.upsert_discovered(changed_url)
        session.commit()

        assert first_created is True
        assert second_created is False
        assert repeated.id == original.id
        assert len(repo.list_since(None)) == 1


def test_tracking_variants_share_one_identity_url(session_factory, seeded_sources):
    source_id = next(iter(seeded_sources))
    tracked = make_discovered(
        source_id=source_id,
        url="https://example.com/story?id=7&utm_source=feed",
        title="带追踪参数",
    )
    clean = make_discovered(
        source_id=source_id,
        url="https://example.com/story?id=7",
        title="不带追踪参数",
    )

    with session_factory() as session:
        repo = ArticleRepository(session)
        original, first_created = repo.upsert_discovered(tracked)
        repeated, second_created = repo.upsert_discovered(clean)
        session.commit()

        assert first_created is True
        assert second_created is False
        assert repeated.id == original.id
        assert original.identity_url == "https://example.com/story?id=7"


def test_downstream_queries_exclude_old_published_articles(session_factory, seeded_sources):
    source_id = next(iter(seeded_sources))
    with session_factory() as session:
        repo = ArticleRepository(session)
        old, _ = repo.upsert_discovered(
            make_discovered(
                source_id=source_id,
                url="https://example.com/historical",
                title="历史新闻",
                published_hours_ago=48,
            )
        )
        old.relevance_status = "relevant"
        fresh, _ = repo.upsert_discovered(
            make_discovered(
                source_id=source_id,
                url="https://example.com/fresh",
                title="最新新闻",
                published_hours_ago=1,
            )
        )
        fresh.relevance_status = "relevant"
        session.commit()

        assert [article.id for article in repo.list_for_fulltext(24)] == [fresh.id]
        assert [
            article.id
            for article in repo.list_since(
                24,
                relevance_in=["relevant"],
                published_within=True,
            )
        ] == [fresh.id]


def test_new_repost_is_compared_with_canonical_article_outside_since_window(
    session_factory, seeded_sources
):
    source_ids = list(seeded_sources)[:2]
    with session_factory() as session:
        repo = ArticleRepository(session)
        old, _ = repo.upsert_discovered(
            make_discovered(
                source_id=source_ids[0],
                url="https://old.example.com/story",
                title="韦伯望远镜拍到遥远星系",
            )
        )
        old.discovered_at = utcnow() - timedelta(days=10)
        old.content_clean = "这是较早发布的完整正文。" * 100
        session.commit()
        old_id = old.id

    with session_factory() as session:
        repo = ArticleRepository(session)
        repost, _ = repo.upsert_discovered(
            make_discovered(
                source_id=source_ids[1],
                url="https://new.example.com/repost",
                title="韦伯望远镜拍到遥远星系",
            )
        )
        repost.content_clean = "这是较早发布的完整正文。" * 100
        session.commit()
        repost_id = repost.id

    stats = run_dedup(session_factory, since_hours=24, filters=FiltersConfig())

    with session_factory() as session:
        repost = session.get(NewsArticle, repost_id)
        assert stats["duplicates"] == 1
        assert repost.duplicate_of == old_id
        assert repost.duplicate_basis in {"title", "sha256", "simhash"}


def test_cluster_forbid_pairs_are_persisted_in_database(session_factory, seeded_sources):
    source_id = next(iter(seeded_sources))
    with session_factory() as session:
        article_repo = ArticleRepository(session)
        first, _ = article_repo.upsert_discovered(
            make_discovered(source_id=source_id, url="https://example.com/a", title="A")
        )
        second, _ = article_repo.upsert_discovered(
            make_discovered(source_id=source_id, url="https://example.com/b", title="B")
        )
        session.flush()
        ClusterForbidRepository(session).add(second.id, first.id, reason="人工拆分")
        session.commit()

    with session_factory() as session:
        pairs = ClusterForbidRepository(session).list_pairs()
        assert frozenset((first.id, second.id)) in pairs
