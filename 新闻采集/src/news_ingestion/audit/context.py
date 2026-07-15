"""通过 ``ContextVar`` 传播审计日志关联键。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_task_id: ContextVar[str] = ContextVar("audit_task_id", default="-")
_stage_id: ContextVar[str] = ContextVar("audit_stage_id", default="-")
_module: ContextVar[str] = ContextVar("audit_module", default="-")
_operation: ContextVar[str] = ContextVar("audit_operation", default="-")


def current_audit_context() -> dict[str, str]:
    return {
        "task_id": _task_id.get(),
        "stage_id": _stage_id.get(),
        "audit_module": _module.get(),
        "audit_operation": _operation.get(),
    }


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
