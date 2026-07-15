"""通过 ``ContextVar`` 传播审计日志关联键。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_task_id: ContextVar[str | None] = ContextVar("audit_task_id", default=None)
_stage_id: ContextVar[str | None] = ContextVar("audit_stage_id", default=None)
_module: ContextVar[str | None] = ContextVar("audit_module", default=None)
_operation: ContextVar[str | None] = ContextVar("audit_operation", default=None)


def current_audit_context() -> dict[str, str]:
    return {
        "task_id": _task_id.get() or "-",
        "stage_id": _stage_id.get() or "-",
        "audit_module": _module.get() or "-",
        "audit_operation": _operation.get() or "-",
    }


def current_audit_link() -> tuple[str | None, str | None]:
    """返回详情记录关联；上下文必须同时具备任务与阶段。"""
    task_id = _task_id.get()
    stage_id = _stage_id.get()
    task_present = task_id is not None
    stage_present = stage_id is not None
    if task_present != stage_present:
        raise RuntimeError("audit task/stage context must be both present or both absent")
    if not task_present:
        return None, None
    return task_id, stage_id


@contextmanager
def audit_log_context(
    *,
    task_id: str | None = None,
    stage_id: str | None = None,
    audit_module: str | None = None,
    audit_operation: str | None = None,
) -> Iterator[None]:
    values = (
        (_task_id, task_id),
        (_stage_id, stage_id),
        (_module, audit_module),
        (_operation, audit_operation),
    )
    tokens = [(variable, variable.set(value)) for variable, value in values if value is not None]
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


class AuditLogFilter(logging.Filter):
    """为所有记录补齐关联字段，无上下文时使用 ``-``。"""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in current_audit_context().items():
            setattr(record, key, value)
        return True
