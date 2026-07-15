"""通用业务任务审计生命周期；每个操作使用独立短事务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..audit.contracts import StageDefinition, WorkflowDefinition
from ..errors import AuditPersistenceError
from ..models import BusinessTask, BusinessTaskStage
from ..repositories import AuditRepository
from ..timeutil import utcnow


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    execution_status: str
    design_status: str
    exit_code: int
    summary: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def blocked(cls, *, exit_code: int, summary: dict[str, Any] | None = None) -> "TaskOutcome":
        return cls("blocked", "compliant", exit_code, summary or {})

    def normalized(self) -> "TaskOutcome":
        if self.execution_status == "blocked":
            return TaskOutcome("blocked", "compliant", self.exit_code, self.summary, self.validation)
        if self.execution_status == "abandoned":
            return TaskOutcome("abandoned", "incomplete", self.exit_code, self.summary, self.validation)
        if self.design_status == "deviation":
            return TaskOutcome(self.execution_status, "deviation", 9, self.summary, self.validation)
        if self.execution_status == "failed":
            return TaskOutcome("failed", "incomplete", self.exit_code, self.summary, self.validation)
        return self


class AuditLifecycleService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _commit(session: Session) -> None:
        session.commit()

    @staticmethod
    def _error(
        exc: BaseException,
        *,
        phase: str,
        task_id: str | None,
        business_commit_state: str,
    ) -> AuditPersistenceError:
        if isinstance(exc, AuditPersistenceError):
            return exc
        controlled_prefixes = ("task state conflict:", "stage state conflict:")
        message = str(exc)
        detail = f": {message[:160]}" if message.startswith(controlled_prefixes) else ""
        return AuditPersistenceError(
            f"audit persistence failed during {phase}: {exc.__class__.__name__}{detail}",
            failure_phase=phase,
            task_id=task_id,
            business_commit_state=business_commit_state,
        )

    def start_task(
        self,
        *,
        module: str,
        operation: str,
        workflow: WorkflowDefinition,
        trigger_type: str = "manual",
        path_type: str = "standard",
        operator: str | None = None,
        lock_domain: str | None = None,
        executor_instance: str | None = None,
        scope: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> str:
        try:
            with self.session_factory() as session:
                task = AuditRepository(session).create_task(
                    module=module,
                    operation=operation,
                    trigger_type=trigger_type,
                    path_type=path_type,
                    workflow_name=workflow.name,
                    workflow_version=workflow.version,
                    expected_stages=workflow.snapshot(),
                    operator=operator,
                    lock_domain=lock_domain,
                    executor_instance=executor_instance,
                    scope=scope,
                    reason=reason,
                )
                task_id = task.id
                self._commit(session)
                return task_id
        except BaseException as exc:
            raise self._error(exc, phase="task_start", task_id=None, business_commit_state="not_started") from exc

    def mark_running(self, task_id: str) -> None:
        try:
            with self.session_factory() as session:
                task = self._locked_task(session, task_id)
                if task.execution_status != "requested":
                    raise RuntimeError("task state conflict: expected requested")
                task.execution_status = "running"
                task.started_at = utcnow()
                self._commit(session)
        except BaseException as exc:
            raise self._error(exc, phase="task_running", task_id=task_id, business_commit_state="not_started") from exc

    def start_stage(
        self,
        task_id: str,
        definition: StageDefinition,
        *,
        prerequisite_evidence: dict[str, Any] | None = None,
    ) -> str:
        try:
            with self.session_factory() as session:
                task = self._locked_task(session, task_id)
                if task.execution_status != "running":
                    raise RuntimeError("task state conflict: expected running")
                stages = AuditRepository(session).list_stages(task_id)
                succeeded = {stage.stage_key for stage in stages if stage.status == "succeeded"}
                missing = set(definition.prerequisites) - succeeded
                if missing:
                    raise ValueError(f"prerequisite not satisfied: {sorted(missing)}")
                active_same_stage = [
                    stage
                    for stage in stages
                    if stage.stage_key == definition.key
                    and stage.status not in {"failed", "blocked", "abandoned"}
                ]
                if active_same_stage:
                    raise RuntimeError(f"stage state conflict: {definition.key} already started")
                actual_sequence = max((stage.actual_sequence for stage in stages), default=0) + 1
                attempt_no = 1 + max(
                    (stage.attempt_no for stage in stages if stage.stage_key == definition.key),
                    default=0,
                )
                stage = AuditRepository(session).create_stage(
                    task_id=task_id,
                    stage_key=definition.key,
                    attempt_no=attempt_no,
                    expected_sequence=definition.sequence,
                    actual_sequence=actual_sequence,
                    unit=definition.unit,
                    prerequisite_evidence=prerequisite_evidence,
                )
                stage_id = stage.id
                self._commit(session)
                return stage_id
        except ValueError:
            raise
        except BaseException as exc:
            raise self._error(exc, phase="stage_start", task_id=task_id, business_commit_state="not_started") from exc

    def finish_stage(
        self,
        task_id: str,
        stage_id: str,
        *,
        status: str,
        input_count: int | None = None,
        output_count: int | None = None,
        routes: dict[str, Any] | None = None,
        reasons: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        business_commit_state: str = "committed",
    ) -> None:
        if status not in {"succeeded", "failed", "blocked", "abandoned"}:
            raise ValueError(f"invalid terminal stage status: {status}")
        try:
            with self.session_factory() as session:
                self._locked_task(session, task_id)
                stage = session.scalars(
                    select(BusinessTaskStage)
                    .where(BusinessTaskStage.id == stage_id, BusinessTaskStage.task_id == task_id)
                    .with_for_update()
                ).one_or_none()
                if stage is None or stage.status != "running":
                    raise RuntimeError("stage state conflict: expected running")
                stage.status = status
                stage.input_count = input_count
                stage.output_count = output_count
                stage.routes_snapshot = dict(routes or {"schema_version": "audit-routes/v1", "routes": []})
                stage.reason_breakdown = dict(reasons or {"schema_version": "audit-reasons/v1", "reasons": {}})
                stage.metrics_snapshot = dict(metrics or {"schema_version": "audit-metrics/v1", "metrics": {}})
                stage.validation_snapshot = dict(validation or {"schema_version": "audit-validation/v1", "status": "incomplete", "results": []})
                stage.finished_at = utcnow()
                self._commit(session)
        except BaseException as exc:
            raise self._error(
                exc,
                phase="stage_finish",
                task_id=task_id,
                business_commit_state=business_commit_state,
            ) from exc

    def finish_task(
        self,
        task_id: str,
        outcome: TaskOutcome,
        *,
        business_commit_state: str = "committed",
    ) -> None:
        outcome = outcome.normalized()
        if outcome.execution_status not in {"succeeded", "partial_success", "failed", "blocked", "abandoned"}:
            raise ValueError(f"invalid terminal task status: {outcome.execution_status}")
        try:
            with self.session_factory() as session:
                task = self._locked_task(session, task_id)
                if task.execution_status not in {"requested", "running"}:
                    raise RuntimeError("task state conflict: expected requested or running")
                now = utcnow()
                task.execution_status = outcome.execution_status
                task.design_status = outcome.design_status
                task.exit_code = outcome.exit_code
                task.started_at = task.started_at or now
                task.finished_at = now
                task.summary_snapshot = {
                    "schema_version": "audit-summary/v1",
                    **outcome.summary,
                }
                task.design_validation_snapshot = {
                    "schema_version": "audit-validation/v1",
                    "status": outcome.design_status,
                    "results": [],
                    **outcome.validation,
                }
                self._commit(session)
        except BaseException as exc:
            raise self._error(
                exc,
                phase="task_finish",
                task_id=task_id,
                business_commit_state=business_commit_state,
            ) from exc

    def recover_stale(
        self,
        *,
        lock_domain: str,
        cutoff: datetime,
        current_task_id: str,
        recovered_by: str,
    ) -> list[str]:
        """在调用方已取得同一 ``lock_domain`` 锁后收敛旧非终态。"""
        recovered: list[str] = []
        try:
            with self.session_factory() as session:
                candidates = list(
                    session.scalars(
                        select(BusinessTask.id).where(
                            BusinessTask.lock_domain == lock_domain,
                            BusinessTask.id != current_task_id,
                            BusinessTask.created_at < cutoff,
                            BusinessTask.execution_status.in_(("requested", "running")),
                        )
                    )
                )
            for task_id in candidates:
                with self.session_factory() as session:
                    task = self._locked_task(session, task_id)
                    if (
                        task.execution_status not in {"requested", "running"}
                        or task.lock_domain != lock_domain
                        or task.id == current_task_id
                        or task.created_at >= cutoff
                    ):
                        continue
                    original = task.execution_status
                    now = utcnow()
                    for stage in AuditRepository(session).list_stages(task.id):
                        if stage.status in {"requested", "running"}:
                            stage.status = "abandoned"
                            stage.started_at = stage.started_at or task.started_at or task.created_at
                            stage.finished_at = now
                    task.execution_status = "abandoned"
                    task.design_status = "incomplete"
                    task.exit_code = 6
                    task.started_at = task.started_at or task.created_at
                    task.finished_at = now
                    task.summary_snapshot = {
                        "schema_version": "audit-summary/v1",
                        "recovery": {
                            "recovered_by": recovered_by,
                            "recovered_at": now.isoformat(),
                            "original_status": original,
                            "reason": "stale_non_terminal_after_lock_acquisition",
                        },
                    }
                    task.design_validation_snapshot = {
                        "schema_version": "audit-validation/v1",
                        "status": "incomplete",
                        "results": [],
                    }
                    self._commit(session)
                    recovered.append(task_id)
            return recovered
        except BaseException as exc:
            raise self._error(exc, phase="stale_recovery", task_id=current_task_id, business_commit_state="not_started") from exc

    @staticmethod
    def _locked_task(session: Session, task_id: str) -> BusinessTask:
        task = AuditRepository(session).get_task(task_id, for_update=True)
        if task is None:
            raise RuntimeError("task state conflict: task not found")
        return task
