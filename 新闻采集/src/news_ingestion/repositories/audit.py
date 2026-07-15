"""业务任务审计仓储；只 flush，不替调用者 commit。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ids import new_id
from ..models import BusinessTask, BusinessTaskStage


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_task(
        self,
        *,
        module: str,
        operation: str,
        trigger_type: str,
        path_type: str,
        workflow_name: str,
        workflow_version: str,
        expected_stages: dict,
        operator: str | None = None,
        lock_domain: str | None = None,
        executor_instance: str | None = None,
        scope: dict | None = None,
        reason: str | None = None,
    ) -> BusinessTask:
        task = BusinessTask(
            id=new_id("task"),
            module=module,
            operation=operation,
            trigger_type=trigger_type,
            operator=operator,
            path_type=path_type,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            lock_domain=lock_domain,
            executor_instance=executor_instance,
            expected_stages_snapshot=dict(expected_stages),
            scope_snapshot=dict(scope or {"schema_version": "audit-scope/v1"}),
            reason=reason,
        )
        self.session.add(task)
        self.session.flush()
        return task

    def get_task(self, task_id: str, *, for_update: bool = False) -> BusinessTask | None:
        stmt = select(BusinessTask).where(BusinessTask.id == task_id)
        if for_update:
            stmt = stmt.with_for_update()
        return self.session.scalars(stmt).one_or_none()

    def create_stage(
        self,
        *,
        task_id: str,
        stage_key: str,
        attempt_no: int,
        expected_sequence: int,
        actual_sequence: int,
        unit: str | None = None,
        input_count: int | None = None,
        output_count: int | None = None,
        prerequisite_evidence: dict | None = None,
    ) -> BusinessTaskStage:
        stage = BusinessTaskStage(
            id=new_id("stage"),
            task_id=task_id,
            stage_key=stage_key,
            attempt_no=attempt_no,
            expected_sequence=expected_sequence,
            actual_sequence=actual_sequence,
            unit=unit,
            input_count=input_count,
            output_count=output_count,
            prerequisite_evidence=dict(prerequisite_evidence or {"schema_version": "audit-prerequisites/v1", "items": []}),
        )
        self.session.add(stage)
        self.session.flush()
        return stage

    def list_stages(self, task_id: str) -> list[BusinessTaskStage]:
        stmt = select(BusinessTaskStage).where(BusinessTaskStage.task_id == task_id).order_by(BusinessTaskStage.actual_sequence)
        return list(self.session.scalars(stmt))

