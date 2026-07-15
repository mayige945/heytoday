from __future__ import annotations

import pytest

from news_ingestion.audit.news_ingestion import NEWS_INGESTION_WORKFLOW
from news_ingestion.config import FiltersConfig, RuntimeConfig, SourceConfig
from news_ingestion.models import BusinessTask, BusinessTaskStage, FetchLog, LlmRun
from news_ingestion.services.audit_service import AuditLifecycleService
from news_ingestion.services.run_service import run_pipeline

from conftest import make_discovered
from test_pipeline_e2e import _fake_collector, _fake_content


def _source(code: str = "audit_source") -> SourceConfig:
    return SourceConfig(
        unit_code="S08",
        code=code,
        name=code,
        homepage_url="https://example.com/",
        language="zh-CN",
        source_category="science",
        source_role=["topic_source", "fact_source"],
        acquisition_method="rss",
        enabled=True,
        priority=80,
        access_review_status="verified",
        access_reviewed_at="2026-07-10",
        access_evidence_url="https://example.com/robots.txt",
        feed_url="https://example.com/feed",
    )


def _items():
    return {
        "audit_source": [
            make_discovered(
                source_id="audit_source",
                url="https://example.com/audit/1",
                title="韦伯望远镜发现遥远星系的新线索",
                guid="audit-1",
            )
        ]
    }


def _start_task(service: AuditLifecycleService) -> str:
    return service.start_task(
        module="news_ingestion",
        operation="run",
        workflow=NEWS_INGESTION_WORKFLOW,
        lock_domain="news_ingestion.run",
    )


def _run(session_factory, fake_llm, service, task_id):
    return run_pipeline(
        session_factory,
        enabled_sources=[_source()],
        runtime=RuntimeConfig(),
        filters=FiltersConfig(),
        user_agent="test-ua",
        client=fake_llm(),
        collector_for=_fake_collector(_items()),
        content_fetcher=_fake_content(),
        audit_lifecycle=service,
        task_id=task_id,
    )


def test_audited_pipeline_records_eight_ordered_stages_and_detail_links(
    session_factory, fake_llm
):
    service = AuditLifecycleService(session_factory)
    task_id = _start_task(service)

    result = _run(session_factory, fake_llm, service, task_id)

    assert result.run_id == task_id
    assert (result.execution_status, result.design_status, result.exit_code) == (
        "succeeded",
        "compliant",
        0,
    )
    expected_keys = [stage.key for stage in NEWS_INGESTION_WORKFLOW.stages]
    assert expected_keys == [
        "fetch",
        "metadata_dedup",
        "classify",
        "content",
        "content_dedup",
        "cluster",
        "score",
        "safety",
    ]

    with session_factory() as session:
        task = session.get(BusinessTask, task_id)
        stages = list(
            session.query(BusinessTaskStage)
            .filter_by(task_id=task_id)
            .order_by(BusinessTaskStage.actual_sequence)
        )
        assert task.execution_status == "succeeded"
        assert [stage.stage_key for stage in stages] == expected_keys
        assert [stage.status for stage in stages] == ["succeeded"] * 8
        assert all(stage.validation_snapshot["status"] == "compliant" for stage in stages)
        assert session.query(FetchLog).filter_by(audit_task_id=task_id).count() == 1
        assert session.query(LlmRun).filter_by(audit_task_id=task_id).count() >= 2
        assert {
            row.audit_stage_id
            for row in session.query(LlmRun).filter_by(audit_task_id=task_id)
        } == {
            next(stage.id for stage in stages if stage.stage_key == "classify"),
            next(stage.id for stage in stages if stage.stage_key == "score"),
        }


def test_repeated_audited_pipeline_uses_a_new_explicit_task(session_factory, fake_llm):
    service = AuditLifecycleService(session_factory)
    first_task_id = _start_task(service)
    first = _run(session_factory, fake_llm, service, first_task_id)
    second_task_id = _start_task(service)
    second = _run(session_factory, fake_llm, service, second_task_id)

    assert first.run_id != second.run_id
    assert {first.run_id, second.run_id} == {first_task_id, second_task_id}
    with session_factory() as session:
        assert session.query(BusinessTaskStage).filter_by(task_id=first_task_id).count() == 8
        assert session.query(BusinessTaskStage).filter_by(task_id=second_task_id).count() == 8
        assert session.query(FetchLog).filter_by(audit_task_id=first_task_id).count() == 1
        assert session.query(FetchLog).filter_by(audit_task_id=second_task_id).count() == 1


def test_funnel_deviation_stops_later_stages_and_finishes_with_exit_nine(
    session_factory, fake_llm, monkeypatch
):
    from news_ingestion.services import run_service

    service = AuditLifecycleService(session_factory)
    task_id = _start_task(service)
    content_called = False

    def inconsistent_classify(*_args, **_kwargs):
        return {
            "processed": 4,
            "relevant": 1,
            "irrelevant": 0,
            "uncertain": 0,
            "rule_excluded": 0,
            "published_before_window": 0,
        }

    def content_must_not_run(*_args, **_kwargs):
        nonlocal content_called
        content_called = True
        raise AssertionError("偏差后不应继续执行")

    monkeypatch.setattr(run_service, "run_classify_light", inconsistent_classify)
    monkeypatch.setattr(run_service, "fetch_contents", content_must_not_run)

    result = _run(session_factory, fake_llm, service, task_id)

    assert content_called is False
    assert (result.execution_status, result.design_status, result.exit_code) == (
        "partial_success",
        "deviation",
        9,
    )
    with session_factory() as session:
        task = session.get(BusinessTask, task_id)
        stages = list(
            session.query(BusinessTaskStage)
            .filter_by(task_id=task_id)
            .order_by(BusinessTaskStage.actual_sequence)
        )
        assert (task.execution_status, task.design_status, task.exit_code) == (
            "partial_success",
            "deviation",
            9,
        )
        assert [stage.stage_key for stage in stages] == [
            "fetch",
            "metadata_dedup",
            "classify",
        ]
        assert stages[-1].validation_snapshot["status"] == "deviation"


def test_legacy_pipeline_call_remains_unaudited_and_compatible(session_factory, fake_llm):
    result = run_pipeline(
        session_factory,
        enabled_sources=[_source()],
        runtime=RuntimeConfig(),
        filters=FiltersConfig(),
        user_agent="test-ua",
        client=fake_llm(),
        collector_for=_fake_collector(_items()),
        content_fetcher=_fake_content(),
    )

    assert result.run_id.startswith("run_")
    assert result.exit_code == 0
    with session_factory() as session:
        assert session.query(BusinessTask).count() == 0
        assert session.query(FetchLog).filter(FetchLog.audit_task_id.is_not(None)).count() == 0
        assert session.query(LlmRun).filter(LlmRun.audit_task_id.is_not(None)).count() == 0


def test_invalid_workflow_mapping_fails_before_business_execution(
    session_factory, fake_llm, monkeypatch
):
    from news_ingestion.audit import StageDefinition, WorkflowDefinition
    from news_ingestion.services import run_service

    collector_called = False

    def collector_for(_code):
        nonlocal collector_called
        collector_called = True
        raise AssertionError("工作流校验失败时不应开始采集")

    monkeypatch.setattr(
        run_service,
        "NEWS_INGESTION_WORKFLOW",
        WorkflowDefinition(
            "news_ingestion.run",
            "broken",
            (StageDefinition("fetch", 1, unit="article"),),
        ),
    )

    with pytest.raises(ValueError, match="workflow definition and handlers"):
        run_pipeline(
            session_factory,
            enabled_sources=[_source()],
            runtime=RuntimeConfig(),
            filters=FiltersConfig(),
            user_agent="test-ua",
            client=fake_llm(),
            collector_for=collector_for,
            content_fetcher=_fake_content(),
        )
    assert collector_called is False


def test_partial_source_failure_is_compliant_exit_four(session_factory, fake_llm):
    service = AuditLifecycleService(session_factory)
    task_id = _start_task(service)
    item = make_discovered(
        source_id="source_ok",
        url="https://example.com/partial/1",
        title="一条仍可继续处理的新闻",
        guid="partial-1",
    )
    successful = _fake_collector({"source_ok": [item]})

    class FailingCollector:
        def collect(self, *_args, **_kwargs):
            raise RuntimeError("source unavailable")

    def collector_for(code):
        return FailingCollector() if code == "source_failed" else successful(code)

    result = run_pipeline(
        session_factory,
        enabled_sources=[_source("source_ok"), _source("source_failed")],
        runtime=RuntimeConfig(),
        filters=FiltersConfig(),
        user_agent="test-ua",
        client=fake_llm(),
        collector_for=collector_for,
        content_fetcher=_fake_content(),
        audit_lifecycle=service,
        task_id=task_id,
    )

    assert (result.execution_status, result.design_status, result.exit_code) == (
        "partial_success",
        "compliant",
        4,
    )
    failed = next(outcome for outcome in result.fetch_outcomes if outcome.status == "failed")
    assert failed.error_message == "source unavailable"
    assert failed.errors == []
    with session_factory() as session:
        task = session.get(BusinessTask, task_id)
        assert (task.execution_status, task.design_status, task.exit_code) == (
            "partial_success",
            "compliant",
            4,
        )
