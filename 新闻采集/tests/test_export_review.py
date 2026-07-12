"""导出与人工复核测试（v0.5：新闻素材库，采集只挡红线，无矩阵/无 fact-check gate）。"""

from __future__ import annotations

import pytest

from news_ingestion.errors import BusinessPreconditionError
from news_ingestion.models import NewsArticle, NewsEvent, NewsSource
from news_ingestion.services import approve_event, export_material, record_fact_check, reject_event
from news_ingestion.services.review_service import require_reviewer
from news_ingestion.timeutil import utcnow


def _seed_scored_event(session_factory, *, needs_fact_check=False, safety_tier="default", status="needs_review"):
    with session_factory() as session:
        if session.get(NewsSource, "nasa") is None:
            session.add(NewsSource(id="nasa", unit_code="S08", code="nasa", name="NASA",
                                   homepage_url="https://nasa.gov", language="en",
                                   source_category="science", acquisition_method="rss", source_role=["fact_source"]))
            session.flush()
        article = NewsArticle(source_id="nasa", url="https://nasa.gov/x", title="NASA韦伯望远镜拍到遥远星系照片",
                              summary="摘要", content_clean="正文", language="en", published_at=utcnow(),
                              relevance_status="relevant")
        session.add(article)
        session.flush()
        event = NewsEvent(
            event_title="NASA韦伯望远镜拍到遥远星系照片",
            event_summary="概述",
            primary_category="technology_in_life",
            topic_categories=["technology_in_life"],
            article_ids=[article.id],
            source_count=1,
            age_assessments={"upper_primary": {"child_interest_score": 80, "age_fit": "fit", "reason": "r"},
                             "junior_high": {"child_interest_score": 85, "age_fit": "fit", "reason": "r"}},
            story_score=70, discussion_score=80, knowledge_gain_score=75, life_relevance_score=70,
            value_pluralism_score=72, audio_fit_score=78,
            safety_tier=safety_tier, safety_reason="ok", safety_assessments={},
            needs_fact_check=needs_fact_check, fact_check_targets=[], key_people=["研究团队"], key_conflicts=[],
            child_hook="如果望远镜能看那么远，它看到的是现在还是过去？",
            llm_reason="理由", llm_status="success", llm_model="kimi", prompt_version="v1", status=status,
        )
        session.add(event)
        session.flush()
        article.event_id = event.id
        session.commit()
        return event.id


def test_reviewer_required():
    with pytest.raises(BusinessPreconditionError):
        require_reviewer("")
    with pytest.raises(BusinessPreconditionError):
        require_reviewer(None)


def test_export_empty_when_no_events(session_factory, tmp_path):
    _json, _md, info = export_material(session_factory, output_dir=tmp_path)
    assert info["result"] == "empty"
    assert _json.exists() and _md.exists()
    assert "无素材事件" in _md.read_text(encoding="utf-8")


def test_event_in_pool_by_default_no_approve_needed(session_factory, tmp_path):
    """v0.5：事件默认进素材库，不需 approve / 不需 fact-check verified。"""
    _seed_scored_event(session_factory, needs_fact_check=True)  # 需核验但仍应入池
    _json, _md, info = export_material(session_factory, output_dir=tmp_path)
    assert info["result"] == "populated"
    import json
    doc = json.loads(_json.read_text(encoding="utf-8"))
    assert doc["schema_version"] == "news-material/v1"
    assert doc["events"][0]["needs_fact_check"] is True  # 作为标签保留


def test_redline_excluded_sensitive_included(session_factory, tmp_path):
    red_id = _seed_scored_event(session_factory, safety_tier="redline")
    sens_id = _seed_scored_event(session_factory, safety_tier="sensitive")
    _json, _md, info = export_material(session_factory, output_dir=tmp_path)
    assert info["result"] == "populated"
    import json
    doc = json.loads(_json.read_text(encoding="utf-8"))
    ids = {e["event_id"] for e in doc["events"]}
    assert red_id not in ids  # 红线被排除（唯一硬过滤）
    assert sens_id in ids  # 敏感作为标签入库
    assert doc["events"][0]["safety_tier"] == "sensitive"


def test_rejected_excluded(session_factory, tmp_path):
    eid = _seed_scored_event(session_factory)
    reject_event(session_factory, eid, reviewer="tester", rejection_reason="不合适")
    _json, _md, info = export_material(session_factory, output_dir=tmp_path)
    assert info["result"] == "empty"  # 被 reject 剔出


def test_approve_optional_and_export_populated(session_factory, tmp_path):
    eid = _seed_scored_event(session_factory)
    approve_event(session_factory, eid, reviewer="tester")  # 无矩阵、无 fact-check
    _json, _md, info = export_material(session_factory, output_dir=tmp_path)
    assert info["result"] == "populated"


def test_fact_check_is_advisory_not_gate(session_factory, tmp_path):
    """needs_fact_check=true 且未核验：仍入素材库（核验是写稿阶段的事）。"""
    eid = _seed_scored_event(session_factory, needs_fact_check=True)
    # 不做 fact-check，直接导出
    _json, _md, info = export_material(session_factory, output_dir=tmp_path)
    assert info["result"] == "populated"


def test_fact_check_record_still_works(session_factory, tmp_path):
    eid = _seed_scored_event(session_factory, needs_fact_check=True)
    record_fact_check(
        session_factory, eid, reviewer="checker", status="verified", conclusion="已核",
        evidence_sources=[{"url": "https://nasa.gov/official", "source_name": "NASA", "source_role": "fact_source", "checked_at": "2026-07-11T00:00:00Z"}],
    )
    _json, _md, info = export_material(session_factory, output_dir=tmp_path)
    assert info["result"] == "populated"


def test_fact_check_verified_requires_evidence_url(session_factory):
    eid = _seed_scored_event(session_factory, needs_fact_check=True)
    with pytest.raises(BusinessPreconditionError, match="URL"):
        record_fact_check(session_factory, eid, reviewer="checker", status="verified", evidence_sources=[])


def test_safety_override_cannot_loosen(session_factory):
    eid = _seed_scored_event(session_factory, safety_tier="redline")
    with pytest.raises(BusinessPreconditionError, match="放宽"):
        approve_event(session_factory, eid, reviewer="tester", safety_override={"safety_tier": "default"})


def test_export_creates_index_and_latest_pointers(session_factory, tmp_path):
    from news_ingestion.services import regenerate_index

    eid = _seed_scored_event(session_factory)
    export_material(session_factory, output_dir=tmp_path)
    assert (tmp_path / "latest_news_material.json").exists()
    assert (tmp_path / "latest_news_material.md").exists()
    index = regenerate_index(tmp_path)
    text = index.read_text(encoding="utf-8")
    assert "新闻素材库索引" in text
    assert "news_material" in text
    data_rows = [line for line in text.splitlines() if line.startswith("| 20")]
    assert data_rows and all("latest_" not in line for line in data_rows)
