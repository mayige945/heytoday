from __future__ import annotations

import logging

from news_ingestion.audit.context import AuditLogFilter, audit_log_context, current_audit_context


def test_filter_supplies_defaults_and_context_is_reset():
    filter_ = AuditLogFilter()
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    filter_.filter(record)
    assert (record.task_id, record.stage_id, record.audit_module, record.audit_operation) == ("-", "-", "-", "-")

    with audit_log_context(task_id="task-1", audit_module="demo", audit_operation="publish"):
        with audit_log_context(stage_id="stage-1"):
            nested = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
            filter_.filter(nested)
            assert (nested.task_id, nested.stage_id, nested.audit_module, nested.audit_operation) == (
                "task-1",
                "stage-1",
                "demo",
                "publish",
            )
        assert current_audit_context()["stage_id"] == "-"

    assert current_audit_context() == {
        "task_id": "-",
        "stage_id": "-",
        "audit_module": "-",
        "audit_operation": "-",
    }


def test_context_resets_after_exception():
    try:
        with audit_log_context(task_id="task-error"):
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        pass
    assert current_audit_context()["task_id"] == "-"
