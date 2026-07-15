"""业务任务账本 ORM 与仓储约束。"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from news_ingestion.models import BusinessTask, BusinessTaskStage, FetchLog, LlmRun, NewsSource
from news_ingestion.repositories import AuditRepository
from news_ingestion.timeutil import utcnow


def _task(repo: AuditRepository, *, operation: str = "publish") -> BusinessTask:
    return repo.create_task(
        module="documents",
        operation=operation,
        trigger_type="scheduler",
        path_type="standard",
        workflow_name="document-publishing",
        workflow_version="v1",
        expected_stages={"schema_version": "audit-expected-stages/v1", "stages": ["receive", "publish"]},
    )


def _stage(repo: AuditRepository, task: BusinessTask, *, key: str, sequence: int, attempt: int = 1) -> BusinessTaskStage:
    return repo.create_stage(
        task_id=task.id,
        stage_key=key,
        attempt_no=attempt,
        expected_sequence=sequence,
        actual_sequence=sequence,
        unit="document",
        input_count=0,
        output_count=0,
    )


def test_repository_flushes_task_and_stage_without_committing(session_factory) -> None:
    with session_factory() as session:
        repo = AuditRepository(session)
        task = _task(repo)
        stage = _stage(repo, task, key="receive", sequence=1)
        assert session.get(BusinessTask, task.id) is task
        assert repo.list_stages(task.id) == [stage]
        session.rollback()

    with session_factory() as session:
        assert session.get(BusinessTask, task.id) is None


@pytest.mark.parametrize(
    "first,second",
    [
        ({"key": "receive", "sequence": 1, "attempt": 1}, {"key": "publish", "sequence": 1, "attempt": 1}),
        ({"key": "receive", "sequence": 1, "attempt": 1}, {"key": "receive", "sequence": 2, "attempt": 1}),
    ],
)
def test_stage_sequence_and_attempt_are_unique_per_task(session_factory, first, second) -> None:
    with session_factory() as session:
        repo = AuditRepository(session)
        task = _task(repo)
        _stage(repo, task, **first)
        with pytest.raises(IntegrityError):
            _stage(repo, task, **second)


def test_database_rejects_invalid_task_state_and_late_finish(session_factory) -> None:
    with session_factory() as session:
        task = BusinessTask(
            module="documents",
            operation="publish",
            trigger_type="manual",
            path_type="standard",
            workflow_name="document-publishing",
            workflow_version="v1",
            execution_status="succeeded",
            design_status="pending",
            started_at=utcnow(),
            finished_at=utcnow(),
            exit_code=0,
        )
        session.add(task)
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize("execution_status", ["succeeded", "partial_success"])
def test_design_deviation_is_orthogonal_to_business_execution_status(session_factory, execution_status) -> None:
    with session_factory() as session:
        task = BusinessTask(
            module="documents",
            operation="publish",
            trigger_type="manual",
            path_type="standard",
            workflow_name="document-publishing",
            workflow_version="v1",
            execution_status=execution_status,
            design_status="deviation",
            started_at=utcnow(),
            finished_at=utcnow(),
            exit_code=9,
        )
        session.add(task)
        session.flush()
        assert task.execution_status == execution_status


def test_successful_compliant_task_requires_zero_exit_code(session_factory) -> None:
    with session_factory() as session:
        task = BusinessTask(
            module="documents",
            operation="publish",
            trigger_type="manual",
            path_type="standard",
            workflow_name="document-publishing",
            workflow_version="v1",
            execution_status="succeeded",
            design_status="compliant",
            started_at=utcnow(),
            finished_at=utcnow(),
            exit_code=9,
        )
        session.add(task)
        with pytest.raises(IntegrityError):
            session.flush()

    with session_factory() as session:
        task = BusinessTask(
            module="documents",
            operation="publish",
            trigger_type="manual",
            path_type="standard",
            workflow_name="document-publishing",
            workflow_version="v1",
            execution_status="failed",
            design_status="incomplete",
            started_at=utcnow(),
            finished_at="2000-01-01T00:00:00+00:00",
            exit_code=6,
        )
        session.add(task)
        with pytest.raises(IntegrityError):
            session.flush()


def test_detail_links_allow_double_null_and_matching_pair_but_reject_half_or_cross_task(session_factory) -> None:
    with session_factory() as session:
        source = NewsSource(
            id="source-test",
            code="source-test",
            name="source-test",
            unit_code="U1",
            homepage_url="https://example.test/",
            language="en",
            source_category="science",
            source_role=["fact_source"],
            acquisition_method="rss",
        )
        session.add(source)
        repo = AuditRepository(session)
        task_a = _task(repo, operation="a")
        task_b = _task(repo, operation="b")
        stage_a = _stage(repo, task_a, key="receive", sequence=1)
        stage_b = _stage(repo, task_b, key="receive", sequence=1)
        session.add(FetchLog(source_id=source.id))
        session.flush()

        linked = LlmRun(mode="light", prompt_name="x", prompt_version="v1", schema_version="v1", input_hash="0" * 64, audit_task_id=task_a.id, audit_stage_id=stage_a.id)
        session.add(linked)
        session.flush()
        session.delete(linked)
        session.flush()

        session.add(LlmRun(mode="light", prompt_name="x", prompt_version="v1", schema_version="v1", input_hash="1" * 64, audit_task_id=task_a.id))
        with pytest.raises(IntegrityError):
            session.flush()

    with session_factory() as session:
        repo = AuditRepository(session)
        task_a = _task(repo, operation="a")
        task_b = _task(repo, operation="b")
        _stage(repo, task_a, key="receive", sequence=1)
        stage_b = _stage(repo, task_b, key="receive", sequence=1)
        session.add(LlmRun(mode="light", prompt_name="x", prompt_version="v1", schema_version="v1", input_hash="2" * 64, audit_task_id=task_a.id, audit_stage_id=stage_b.id))
        with pytest.raises(IntegrityError):
            session.flush()


def test_task_delete_is_restricted_but_detail_delete_is_allowed(session_factory) -> None:
    with session_factory() as session:
        repo = AuditRepository(session)
        task = _task(repo)
        stage = _stage(repo, task, key="receive", sequence=1)
        detail = LlmRun(mode="light", prompt_name="x", prompt_version="v1", schema_version="v1", input_hash="3" * 64, audit_task_id=task.id, audit_stage_id=stage.id)
        session.add(detail)
        session.commit()
        detail_id = detail.id
        task_id = task.id

    with session_factory() as session:
        session.delete(session.get(BusinessTask, task_id))
        with pytest.raises(IntegrityError):
            session.commit()

    with session_factory() as session:
        detail = session.get(LlmRun, detail_id)
        session.delete(detail)
        session.commit()
        assert session.get(BusinessTask, task_id) is not None
