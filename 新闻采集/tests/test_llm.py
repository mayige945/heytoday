"""LLM 识别服务契约测试（fake client；plan §8 / §16.4）。"""

from __future__ import annotations

from datetime import timedelta

from news_ingestion.config import RuntimeConfig
from news_ingestion.llm import extract_json, load_prompt, validate_instance
from news_ingestion.llm.relevance import classify_light
from news_ingestion.llm.scoring import score_full
from news_ingestion.models import NewsArticle, NewsEvent, NewsSource
from news_ingestion.repositories import LlmRunRepository
from news_ingestion.services.classify_service import run_classify_light
from news_ingestion.services.score_service import run_score_full
from news_ingestion.timeutil import utcnow

from conftest import SCORING_DEFAULT


def test_schemas_reject_invalid():
    bad = dict(SCORING_DEFAULT, story_score=150)
    assert validate_instance("news-scoring/v1", bad)
    bad2 = dict(SCORING_DEFAULT, safety_tier="bogus")
    assert validate_instance("news-scoring/v1", bad2)
    assert not validate_instance("news-scoring/v1", SCORING_DEFAULT)


def test_extract_json_handles_fences():
    text = '```json\n{"a": 1}\n```'
    assert extract_json(text) == {"a": 1}
    assert extract_json("no json here") is None


def test_prompt_versions():
    assert load_prompt("news_relevance").version == "v1"
    assert load_prompt("news_scoring").schema_version == "news-scoring/v1"


def _seed_article(session_factory):
    with session_factory() as session:
        session.add(NewsSource(id="nasa", unit_code="S08", code="nasa", name="NASA",
                               homepage_url="https://nasa.gov", language="en",
                               source_category="science", acquisition_method="rss", source_role=["fact_source"]))
        session.flush()
        article = NewsArticle(source_id="nasa", url="https://nasa.gov/x", title="NASA新发现",
                              summary="摘要", language="en", published_at=utcnow())
        session.add(article)
        session.flush()
        article_id = article.id
        event = NewsEvent(event_title="NASA新发现", needs_fact_check=False)
        session.add(event)
        session.flush()
        event_id = event.id
        article.event_id = event_id
        session.commit()
        return article_id, event_id


def test_classify_light_success(session_factory, fake_llm):
    article_id, _ = _seed_article(session_factory)
    client = fake_llm()
    with session_factory() as session:
        article = session.get(NewsArticle, article_id)
        source = session.get(NewsSource, "nasa")
        relevance, parsed, run = classify_light(
            client, article=article, source=source, max_tokens=512, run_repo=LlmRunRepository(session)
        )
        session.commit()
    assert relevance == "relevant"
    assert run.status == "success"
    assert run.model_name == "kimi-fake"
    assert "sk-" not in (run.raw_response or "")


def test_classify_light_malformed_degrades_to_uncertain(session_factory, fake_llm):
    article_id, _ = _seed_article(session_factory)
    client = fake_llm(malformed=True)
    with session_factory() as session:
        article = session.get(NewsArticle, article_id)
        source = session.get(NewsSource, "nasa")
        relevance, parsed, run = classify_light(
            client, article=article, source=source, max_tokens=512, run_repo=LlmRunRepository(session)
        )
        session.commit()
    assert relevance == "uncertain"
    assert run.status == "failed"


def test_classify_service_skips_articles_published_before_window(session_factory, fake_llm):
    old_id, _ = _seed_article(session_factory)
    with session_factory() as session:
        old = session.get(NewsArticle, old_id)
        old.published_at = utcnow() - timedelta(hours=48)
        session.add(
            NewsArticle(
                source_id="nasa",
                url="https://nasa.gov/new",
                title="NASA今日新发现",
                summary="摘要",
                language="en",
                published_at=utcnow() - timedelta(hours=1),
            )
        )
        session.commit()

    client = fake_llm()
    stats = run_classify_light(
        session_factory,
        since_hours=24,
        runtime=RuntimeConfig(),
        client=client,
    )

    assert stats["processed"] == 2
    assert stats["published_before_window"] == 1
    assert len(client.calls) == 1
    with session_factory() as session:
        old = session.get(NewsArticle, old_id)
        assert old.relevance_status == "irrelevant"
        assert old.relevance_reason == "rule:published_before_window"


def test_score_full_success(session_factory, fake_llm):
    article_id, event_id = _seed_article(session_factory)
    client = fake_llm()
    with session_factory() as session:
        event = session.get(NewsEvent, event_id)
        article = session.get(NewsArticle, article_id)
        parsed, run = score_full(
            client, event=event, articles=[article], sources_by_id={"nasa": session.get(NewsSource, "nasa")},
            max_tokens=2048, run_repo=LlmRunRepository(session),
        )
        session.commit()
    assert parsed is not None
    assert parsed["primary_category"] == "technology_in_life"
    assert run.status == "success"


def test_score_service_excludes_events_published_before_window(session_factory, fake_llm):
    _, event_id = _seed_article(session_factory)
    with session_factory() as session:
        event = session.get(NewsEvent, event_id)
        event.latest_published_at = utcnow() - timedelta(hours=48)
        session.commit()

    client = fake_llm()
    stats = run_score_full(
        session_factory,
        runtime=RuntimeConfig(),
        client=client,
        since_hours=24,
    )

    assert stats == {"scored": 0, "failed": 0, "skipped": 0}
    assert client.calls == []
