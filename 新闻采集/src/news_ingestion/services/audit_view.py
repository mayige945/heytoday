"""通用的任务主线读模型；不依赖任何业务详情类型。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from ..errors import BusinessPreconditionError
from ..models import BusinessTask, BusinessTaskStage
from ..timeutil import to_shanghai, to_utc

DetailResolver = Callable[[Session, str, list[BusinessTaskStage]], dict[str, Any] | None]


def _iso(value: object | None) -> str | None:
    converted = to_shanghai(value) if isinstance(value, datetime) else None
    return converted.isoformat() if converted is not None else None


def _funnel(stage: BusinessTaskStage) -> dict[str, Any] | None:
    routes = dict(stage.routes_snapshot or {}).get("routes", [])
    if stage.input_count is None and stage.output_count is None and not routes:
        return None
    return {
        "stage_id": stage.id,
        "stage_key": stage.stage_key,
        "unit": stage.unit,
        "input_count": stage.input_count,
        "output_count": stage.output_count,
        "routes": routes,
        "reasons": dict(stage.reason_breakdown or {}).get("reasons", {}),
        "metrics": dict(stage.metrics_snapshot or {}).get("metrics", {}),
        "validation": dict(stage.validation_snapshot or {}),
    }


def _list_row(task: BusinessTask, stages: list[BusinessTaskStage]) -> dict[str, Any]:
    funnels = [item for stage in stages if (item := _funnel(stage)) is not None]
    return {
        "task_id": task.id,
        "created_at": _iso(task.created_at),
        "module": task.module,
        "operation": task.operation,
        "trigger_type": task.trigger_type,
        "operator": task.operator,
        "execution_status": task.execution_status,
        "design_status": task.design_status,
        "exit_code": task.exit_code,
        "key_funnel": funnels[-1] if funnels else None,
    }


class AuditViewService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        detail_resolvers: Iterable[DetailResolver] = (),
    ) -> None:
        self.session_factory = session_factory
        self.detail_resolvers = tuple(detail_resolvers)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        module: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            stmt = select(BusinessTask).order_by(BusinessTask.created_at.desc()).limit(limit)
            if status:
                stmt = stmt.where(
                    or_(BusinessTask.execution_status == status, BusinessTask.design_status == status)
                )
            if module:
                stmt = stmt.where(BusinessTask.module == module)
            if since:
                stmt = stmt.where(BusinessTask.created_at >= to_utc(since))
            if until:
                stmt = stmt.where(BusinessTask.created_at <= to_utc(until))
            tasks = list(session.scalars(stmt))
            task_ids = [task.id for task in tasks]
            stages = list(
                session.scalars(
                    select(BusinessTaskStage)
                    .where(BusinessTaskStage.task_id.in_(task_ids))
                    .order_by(BusinessTaskStage.task_id, BusinessTaskStage.actual_sequence)
                )
            ) if task_ids else []
            by_task: dict[str, list[BusinessTaskStage]] = {task_id: [] for task_id in task_ids}
            for stage in stages:
                by_task[stage.task_id].append(stage)
            rows = [_list_row(task, by_task[task.id]) for task in tasks]
        return {
            "schema_version": "audit-task-list/v1",
            "filters": {
                "status": status,
                "module": module,
                "since": _iso(since),
                "until": _iso(until),
                "limit": limit,
            },
            "count": len(rows),
            "tasks": rows,
        }

    def show_task(self, task_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            task = session.get(BusinessTask, task_id)
            if task is None:
                raise BusinessPreconditionError(f"任务不存在：{task_id}")
            stages = list(
                session.scalars(
                    select(BusinessTaskStage)
                    .where(BusinessTaskStage.task_id == task_id)
                    .order_by(BusinessTaskStage.actual_sequence)
                )
            )
            details = [
                detail
                for resolver in self.detail_resolvers
                if (detail := resolver(session, task_id, stages)) is not None
            ]
            expected_snapshot = dict(task.expected_stages_snapshot or {})
            expected = list(expected_snapshot.get("stages", []))
            actual = [
                {
                    "stage_id": stage.id,
                    "stage_key": stage.stage_key,
                    "attempt_no": stage.attempt_no,
                    "expected_sequence": stage.expected_sequence,
                    "actual_sequence": stage.actual_sequence,
                    "status": stage.status,
                    "started_at": _iso(stage.started_at),
                    "finished_at": _iso(stage.finished_at),
                    "prerequisite_evidence": dict(stage.prerequisite_evidence or {}),
                }
                for stage in stages
            ]
            funnels = [item for stage in stages if (item := _funnel(stage)) is not None]
            deviations: list[dict[str, Any]] = []
            for stage in stages:
                for result in dict(stage.validation_snapshot or {}).get("results", []):
                    if result.get("status") == "deviation":
                        deviations.append({"stage_key": stage.stage_key, **result})
            for result in dict(task.design_validation_snapshot or {}).get("results", []):
                if result.get("status") == "deviation":
                    deviations.append({"stage_key": None, **result})
            story = {
                "who": {"operator": task.operator, "trigger_type": task.trigger_type},
                "when": {
                    "created_at": _iso(task.created_at),
                    "started_at": _iso(task.started_at),
                    "finished_at": _iso(task.finished_at),
                },
                "object": dict(task.scope_snapshot or {}),
                "action": {
                    "module": task.module,
                    "operation": task.operation,
                    "path_type": task.path_type,
                    "reason": task.reason,
                },
                "result": {
                    "execution_status": task.execution_status,
                    "design_status": task.design_status,
                    "exit_code": task.exit_code,
                    "summary": dict(task.summary_snapshot or {}),
                },
            }
            return {
                "schema_version": "audit-task-show/v1",
                "task_id": task.id,
                "story": story,
                "workflow": {
                    "name": task.workflow_name,
                    "version": task.workflow_version,
                    "expected": expected,
                    "actual": actual,
                },
                "funnel": funnels,
                "design": {
                    "status": task.design_status,
                    "validation": dict(task.design_validation_snapshot or {}),
                    "deviations": deviations,
                },
                "details": details,
                "ledger_complete": True,
            }
