"""所有 CLI 写命令共用的审计、锁、前置和终态边界。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..audit import StageDefinition, WorkflowDefinition
from ..audit.context import audit_log_context
from ..errors import (
    AuditPersistenceError,
    BusinessPreconditionError,
    ConfigError,
    DbInfraError,
    LlmNotConfiguredError,
    LockBusyError,
    SchemaValidationError,
)
from ..timeutil import utcnow
from .audit_service import AuditLifecycleService, TaskOutcome
from .lock import DatabaseLock, ProcessLock


@dataclass(frozen=True, slots=True)
class TriggerContext:
    trigger_type: str
    operator: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AuditedCommandSpec:
    module: str
    operation: str
    lock_domain: str
    path_type: str = "standard"
    reason_required: bool = False
    stages_managed_by_callback: bool = False
    workflow: WorkflowDefinition | None = None

    def resolved_workflow(self) -> WorkflowDefinition:
        return self.workflow or WorkflowDefinition(
            name=f"{self.module}.{self.operation}",
            version="1",
            stages=(StageDefinition(self.operation, 1, unit="operation"),),
        )


@dataclass(frozen=True, slots=True)
class AuditedCommandResult:
    value: Any = None
    exit_code: int = 0
    execution_status: str | None = None
    design_status: str = "compliant"
    summary: dict[str, Any] = field(default_factory=dict)

    def outcome(self) -> TaskOutcome:
        execution = self.execution_status
        if execution is None:
            execution = "succeeded" if self.exit_code == 0 else "partial_success" if self.exit_code in {4, 7} else "failed"
        design = self.design_status if execution not in {"failed", "abandoned"} else "incomplete"
        return TaskOutcome(execution, design, self.exit_code, summary=self.summary)


def run_audited_command(
    engine: Engine,
    session_factory: sessionmaker[Session],
    *,
    spec: AuditedCommandSpec,
    trigger: TriggerContext,
    callback: Callable[[AuditLifecycleService, str], AuditedCommandResult],
    precondition: Callable[[], None] | None = None,
    scope: dict[str, Any] | None = None,
    stale_after_minutes: int = 30,
) -> AuditedCommandResult:
    """任务先落库，随后取锁、校验前置、执行业务并提交审计终态。"""
    audit = AuditLifecycleService(session_factory)
    workflow = spec.resolved_workflow()
    reason = (trigger.reason or "").strip() or None
    task_id = audit.start_task(
        module=spec.module,
        operation=spec.operation,
        workflow=workflow,
        trigger_type=trigger.trigger_type,
        path_type=spec.path_type,
        operator=trigger.operator,
        lock_domain=spec.lock_domain,
        scope=scope,
        reason=reason,
    )
    stage_id: str | None = None
    try:
        with ProcessLock(), DatabaseLock(engine, lock_domain=spec.lock_domain):
            audit.recover_stale(
                lock_domain=spec.lock_domain,
                cutoff=utcnow() - timedelta(minutes=stale_after_minutes),
                current_task_id=task_id,
                recovered_by=f"{trigger.trigger_type}:{trigger.operator}",
            )
            if spec.reason_required and not reason:
                raise BusinessPreconditionError("非标准补跑必须通过 --reason 或 NEWS_AUDIT_REASON 提供原因")
            if precondition is not None:
                precondition()
            if spec.stages_managed_by_callback:
                result = callback(audit, task_id)
            else:
                audit.mark_running(task_id)
                definition = workflow.stages[0]
                stage_id = audit.start_stage(task_id, definition)
                with audit_log_context(
                    task_id=task_id,
                    stage_id=stage_id,
                    audit_module=spec.module,
                    audit_operation=spec.operation,
                ):
                    result = callback(audit, task_id)
            outcome = result.outcome()
            if stage_id is not None:
                audit.finish_stage(
                    task_id,
                    stage_id,
                    status="failed" if outcome.execution_status == "failed" else "succeeded",
                    input_count=1,
                    output_count=0 if outcome.execution_status == "failed" else 1,
                    business_commit_state="committed",
                )
            audit.finish_task(task_id, outcome, business_commit_state="committed")
            return result
    except AuditPersistenceError:
        raise
    except (BusinessPreconditionError, ConfigError, LockBusyError) as exc:
        if stage_id is not None:
            audit.finish_stage(
                task_id,
                stage_id,
                status="blocked",
                input_count=1,
                output_count=0,
                business_commit_state="not_committed",
            )
        audit.finish_task(
            task_id,
            TaskOutcome.blocked(
                exit_code=5 if isinstance(exc, LockBusyError) else 2 if isinstance(exc, ConfigError) else 9,
                summary={"reason": str(exc)},
            ),
            business_commit_state="not_committed",
        )
        raise
    except LlmNotConfiguredError:
        _finish_failed(audit, task_id, stage_id, exit_code=7, business_commit_state="not_committed")
        raise
    except SchemaValidationError:
        _finish_failed(audit, task_id, stage_id, exit_code=8, business_commit_state="unknown")
        raise
    except DbInfraError:
        _finish_failed(audit, task_id, stage_id, exit_code=6, business_commit_state="unknown")
        raise
    except BaseException:
        _finish_failed(audit, task_id, stage_id, exit_code=6, business_commit_state="unknown")
        raise


def _finish_failed(
    audit: AuditLifecycleService,
    task_id: str,
    stage_id: str | None,
    *,
    exit_code: int,
    business_commit_state: str,
) -> None:
    if stage_id is not None:
        audit.finish_stage(
            task_id,
            stage_id,
            status="failed",
            business_commit_state=business_commit_state,
        )
    audit.finish_task(
        task_id,
        TaskOutcome("failed", "incomplete", exit_code),
        business_commit_state=business_commit_state,
    )
