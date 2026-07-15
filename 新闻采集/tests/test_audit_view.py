from __future__ import annotations

import inspect
from datetime import timedelta

import pytest
from sqlalchemy import select

from news_ingestion.audit import FunnelSnapshot, StageDefinition, WorkflowDefinition, validate_funnel
from news_ingestion.audit.news_ingestion import resolve_news_ingestion_details
from news_ingestion.errors import BusinessPreconditionError
from news_ingestion.models import BusinessTask, BusinessTaskStage, FetchLog, LlmRun, NewsSource
from news_ingestion.services.audit_service import AuditLifecycleService, TaskOutcome
from news_ingestion.services.audit_view import AuditViewService
from news_ingestion.timeutil import utcnow


WORKFLOW = WorkflowDefinition(
    "demo.publish",
    "1",
    (
        StageDefinition("prepare", 1, unit="item"),
        StageDefinition("publish", 2, unit="item", prerequisites=("prepare",)),
    ),
)


def _completed_task(session_factory, *, module="demo", operator="alice", design_status="compliant"):
    lifecycle = AuditLifecycleService(session_factory)
    task_id = lifecycle.start_task(
        module=module,
        operation="publish",
        workflow=WORKFLOW,
        operator=operator,
        scope={"schema_version": "audit-scope/v1", "document_id": "doc-1"},
    )
    lifecycle.mark_running(task_id)
    stage_id = lifecycle.start_stage(task_id, WORKFLOW.stages[0])
    funnel = FunnelSnapshot("item", 3, 2, (("rejected", 1),))
    validation = validate_funnel(funnel)
    lifecycle.finish_stage(
        task_id,
        stage_id,
        status="succeeded",
        input_count=3,
        output_count=2,
        routes={"schema_version": "audit-routes/v1", "routes": [{"key": "rejected", "count": 1}]},
        validation=validation.snapshot(),
    )
    lifecycle.finish_task(
        task_id,
        TaskOutcome("succeeded", design_status, 0 if design_status == "compliant" else 9, {"published": 2}),
    )
    return task_id, stage_id


def test_list_filters_and_show_share_one_read_model(session_factory):
    first, _ = _completed_task(session_factory, module="demo")
    _completed_task(session_factory, module="other", operator="bob")
    service = AuditViewService(session_factory)

    listed = service.list_tasks(status="succeeded", module="demo", since=utcnow() - timedelta(hours=1))
    assert [task["task_id"] for task in listed["tasks"]] == [first]
    assert listed["tasks"][0]["execution_status"] == "succeeded"
    assert listed["tasks"][0]["design_status"] == "compliant"
    assert listed["tasks"][0]["key_funnel"]["input_count"] == 3

    shown = service.show_task(first)
    assert shown["story"] == {
        "who": {"operator": "alice", "trigger_type": "manual"},
        "when": shown["story"]["when"],
        "object": {"schema_version": "audit-scope/v1", "document_id": "doc-1"},
        "action": {"module": "demo", "operation": "publish", "path_type": "standard", "reason": None},
        "result": shown["story"]["result"],
    }
    assert shown["workflow"]["expected"][0]["key"] == "prepare"
    assert shown["workflow"]["actual"][0]["actual_sequence"] == 1
    assert shown["funnel"][0]["routes"] == [{"key": "rejected", "count": 1}]


def test_deviation_is_visible_without_file_logs(session_factory):
    task_id, stage_id = _completed_task(session_factory)
    with session_factory() as session:
        stage = session.get(BusinessTaskStage, stage_id)
        stage.validation_snapshot = {
            "schema_version": "audit-validation/v1",
            "status": "deviation",
            "results": [{"rule_id": "audit.funnel.conservation", "status": "deviation", "expected": 3, "actual": 2, "delta": -1, "message": ""}],
        }
        task = session.get(BusinessTask, task_id)
        task.execution_status = "partial_success"
        task.design_status = "deviation"
        task.exit_code = 9
        session.commit()
    shown = AuditViewService(session_factory).show_task(task_id)
    assert shown["design"]["deviations"][0]["rule_id"] == "audit.funnel.conservation"
    assert shown["design"]["deviations"][0]["stage_key"] == "prepare"


def test_detail_resolver_registration_and_generic_import_boundary(session_factory):
    task_id, _ = _completed_task(session_factory)

    def fake_resolver(_session, resolved_task_id, _stages):
        return {"kind": "fake", "task_id": resolved_task_id}

    service = AuditViewService(session_factory, detail_resolvers=(fake_resolver,))
    assert service.show_task(task_id)["details"] == [{"kind": "fake", "task_id": task_id}]
    import news_ingestion.services.audit_view as module
    source = inspect.getsource(module)
    assert "FetchLog" not in source
    assert "LlmRun" not in source


def test_news_resolver_links_details_and_sanitizes_rotated_logs(session_factory, seeded_sources, monkeypatch, tmp_path):
    task_id, stage_id = _completed_task(session_factory, module="news_ingestion")
    with session_factory() as session:
        source_id = session.scalars(select(NewsSource.id).limit(1)).one()
        session.add(
            FetchLog(
                id="fetch-view-1", source_id=source_id, status="success",
                audit_task_id=task_id, audit_stage_id=stage_id,
            )
        )
        session.add(
            LlmRun(
                id="llm-view-1", mode="light", prompt_name="p", prompt_version="1",
                schema_version="v1", input_hash="0" * 64, status="success",
                audit_task_id=task_id, audit_stage_id=stage_id,
            )
        )
        session.commit()
    log = tmp_path / "news-ingestion.log"
    rotated = tmp_path / "news-ingestion.log.2026-07-14"
    monkeypatch.setenv("NEWS_LOG_FILE", str(log))
    log.write_text(
        f"INFO task={task_id} stage={stage_id} current-log\n",
        encoding="utf-8",
    )
    rotated.write_text(
        f"INFO task={task_id}2 stage={stage_id} prefix-must-not-match\n"
        f"INFO task={task_id} stage={stage_id} Authorization: Bearer secret-token Cookie=session-secret x-api-key=key-secret API key=space-secret\n",
        encoding="utf-8",
    )
    shown = AuditViewService(session_factory, detail_resolvers=(resolve_news_ingestion_details,)).show_task(task_id)
    news = shown["details"][0]
    assert news["fetch_logs"][0]["id"] == "fetch-view-1"
    assert news["llm_runs"][0]["id"] == "llm-view-1"
    assert news["technical_logs"]["status"] == "available"
    assert len(news["technical_logs"]["files"]) == 2
    assert sum(len(item["matches"]) for item in news["technical_logs"]["files"]) == 2
    assert "prefix-must-not-match" not in str(news["technical_logs"])
    assert news["technical_logs"]["files"][0]["matches"][0]["stage_id"] == stage_id
    text = str(news["technical_logs"])
    assert all(secret not in text for secret in ("secret-token", "session-secret", "key-secret", "space-secret"))


def test_old_task_without_logs_is_explicitly_expired_but_ledger_remains_valid(session_factory, monkeypatch, tmp_path):
    task_id, _ = _completed_task(session_factory, module="news_ingestion")
    with session_factory() as session:
        task = session.get(BusinessTask, task_id)
        task.created_at = utcnow() - timedelta(days=31)
        session.commit()
    monkeypatch.setenv("NEWS_LOG_FILE", str(tmp_path / "missing.log"))
    shown = AuditViewService(session_factory, detail_resolvers=(resolve_news_ingestion_details,)).show_task(task_id)
    assert shown["details"][0]["technical_logs"]["status"] == "expired"
    assert shown["ledger_complete"] is True


def test_missing_task_is_business_precondition_and_read_queries_never_create_tasks(session_factory):
    service = AuditViewService(session_factory)
    before = service.list_tasks()["count"]
    with pytest.raises(BusinessPreconditionError):
        service.show_task("task-missing")
    assert service.list_tasks()["count"] == before
