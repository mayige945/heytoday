from __future__ import annotations

from datetime import timedelta

import pytest

from news_ingestion.audit import StageDefinition, WorkflowDefinition
from news_ingestion.errors import AuditPersistenceError
from news_ingestion.models import BusinessTask, BusinessTaskStage
from news_ingestion.services.audit_service import AuditLifecycleService, TaskOutcome
from news_ingestion.timeutil import utcnow


WORKFLOW = WorkflowDefinition(
    name="demo.publish",
    version="1",
    stages=(
        StageDefinition("prepare", 1, unit="item"),
        StageDefinition("publish", 2, unit="item", prerequisites=("prepare",)),
    ),
)


def _service(session_factory):
    return AuditLifecycleService(session_factory)


def test_lifecycle_uses_committed_short_transactions_and_actual_sequence(session_factory):
    service = _service(session_factory)
    task_id = service.start_task(module="demo", operation="publish", workflow=WORKFLOW, lock_domain="demo")
    service.mark_running(task_id)
    first = service.start_stage(task_id, WORKFLOW.stages[0])
    service.finish_stage(task_id, first, status="succeeded", input_count=2, output_count=2)
    second = service.start_stage(task_id, WORKFLOW.stages[1])
    service.finish_stage(task_id, second, status="succeeded", input_count=2, output_count=2)
    service.finish_task(task_id, TaskOutcome(execution_status="succeeded", design_status="compliant", exit_code=0))

    with session_factory() as session:
        task = session.get(BusinessTask, task_id)
        stages = list(session.query(BusinessTaskStage).filter_by(task_id=task_id).order_by(BusinessTaskStage.actual_sequence))
        assert task.execution_status == "succeeded"
        assert [stage.actual_sequence for stage in stages] == [1, 2]


def test_blocked_is_compliant_and_deviation_forces_exit_nine(session_factory):
    service = _service(session_factory)
    blocked = service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    service.finish_task(blocked, TaskOutcome.blocked(exit_code=5, summary={"reason": "lock"}))
    deviated = service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    service.mark_running(deviated)
    service.finish_task(deviated, TaskOutcome(execution_status="succeeded", design_status="deviation", exit_code=0))
    with session_factory() as session:
        assert session.get(BusinessTask, blocked).design_status == "compliant"
        assert session.get(BusinessTask, deviated).exit_code == 9


def test_prerequisite_is_checked_before_stage_is_created(session_factory):
    service = _service(session_factory)
    task_id = service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    service.mark_running(task_id)
    with pytest.raises(ValueError, match="prerequisite"):
        service.start_stage(task_id, WORKFLOW.stages[1])
    with session_factory() as session:
        assert session.query(BusinessTaskStage).filter_by(task_id=task_id).count() == 0


def test_cas_rejects_late_finalizer(session_factory):
    service = _service(session_factory)
    task_id = service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    service.mark_running(task_id)
    service.finish_task(task_id, TaskOutcome(execution_status="failed", design_status="incomplete", exit_code=9))
    with pytest.raises(AuditPersistenceError, match="state conflict"):
        service.finish_task(task_id, TaskOutcome(execution_status="succeeded", design_status="compliant", exit_code=0))


def test_same_stage_cannot_be_started_twice_while_first_is_active(session_factory):
    service = _service(session_factory)
    task_id = service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    service.mark_running(task_id)
    service.start_stage(task_id, WORKFLOW.stages[0])
    with pytest.raises(AuditPersistenceError, match="already started"):
        service.start_stage(task_id, WORKFLOW.stages[0])


def test_recovery_is_scoped_old_and_never_infers_success(session_factory):
    service = _service(session_factory)
    old_running = service.start_task(module="demo", operation="publish", workflow=WORKFLOW, lock_domain="same")
    service.mark_running(old_running)
    old_requested = service.start_task(module="demo", operation="publish", workflow=WORKFLOW, lock_domain="same")
    other_domain = service.start_task(module="demo", operation="publish", workflow=WORKFLOW, lock_domain="other")
    current = service.start_task(module="demo", operation="publish", workflow=WORKFLOW, lock_domain="same")
    cutoff = utcnow() - timedelta(minutes=30)
    with session_factory() as session:
        for task_id in (old_running, old_requested, other_domain):
            task = session.get(BusinessTask, task_id)
            task.created_at = cutoff - timedelta(seconds=1)
            if task.started_at is not None:
                task.started_at = cutoff - timedelta(seconds=1)
        session.commit()

    recovered = service.recover_stale(lock_domain="same", cutoff=cutoff, current_task_id=current, recovered_by="test")
    assert set(recovered) == {old_running, old_requested}
    with session_factory() as session:
        for task_id in recovered:
            task = session.get(BusinessTask, task_id)
            assert (task.execution_status, task.design_status) == ("abandoned", "incomplete")
        assert session.get(BusinessTask, other_domain).execution_status == "requested"
        assert session.get(BusinessTask, current).execution_status == "requested"


def test_keyboard_interrupt_can_be_recorded_as_failure(session_factory):
    service = _service(session_factory)
    task_id = service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    service.mark_running(task_id)
    stage_id = service.start_stage(task_id, WORKFLOW.stages[0])
    service.finish_stage(task_id, stage_id, status="failed", metrics={"exception": "KeyboardInterrupt"})
    service.finish_task(task_id, TaskOutcome(execution_status="failed", design_status="incomplete", exit_code=9))
    with session_factory() as session:
        assert session.get(BusinessTask, task_id).execution_status == "failed"


def test_task_start_failure_has_no_fabricated_task_id(session_factory, monkeypatch):
    service = _service(session_factory)
    monkeypatch.setattr(service, "_commit", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(AuditPersistenceError) as caught:
        service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    assert caught.value.task_id is None
    assert caught.value.failure_phase == "task_start"


def test_uncontrolled_exception_text_is_not_copied_into_audit_error(session_factory, monkeypatch):
    service = _service(session_factory)
    secret = "Authorization: Bearer api-key-secret; Cookie=session-secret"
    monkeypatch.setattr(service, "_commit", lambda *_args: (_ for _ in ()).throw(RuntimeError(secret)))
    with pytest.raises(AuditPersistenceError) as caught:
        service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    assert "Authorization" not in str(caught.value)
    assert "Cookie" not in str(caught.value)
    assert "api-key-secret" not in str(caught.value)
    assert "RuntimeError" in str(caught.value)


def test_terminal_persistence_failure_reports_committed_business_and_leaves_running(session_factory, monkeypatch):
    service = _service(session_factory)
    task_id = service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    service.mark_running(task_id)
    original_commit = service._commit

    def fail_commit(_session):
        raise RuntimeError("simulated final audit failure")

    monkeypatch.setattr(service, "_commit", fail_commit)
    with pytest.raises(AuditPersistenceError) as caught:
        service.finish_task(
            task_id,
            TaskOutcome(execution_status="succeeded", design_status="compliant", exit_code=0),
            business_commit_state="committed",
        )
    assert caught.value.task_id == task_id
    assert caught.value.failure_phase == "task_finish"
    assert caught.value.business_commit_state == "committed"
    monkeypatch.setattr(service, "_commit", original_commit)
    with session_factory() as session:
        assert session.get(BusinessTask, task_id).execution_status == "running"


def test_explicit_business_failure_cannot_claim_completed_design_validation(session_factory):
    service = _service(session_factory)
    task_id = service.start_task(module="demo", operation="publish", workflow=WORKFLOW)
    service.mark_running(task_id)
    service.finish_task(task_id, TaskOutcome(execution_status="failed", design_status="compliant", exit_code=9))
    with session_factory() as session:
        assert session.get(BusinessTask, task_id).design_status == "incomplete"
