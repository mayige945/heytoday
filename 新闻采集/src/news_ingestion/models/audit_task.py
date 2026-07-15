"""长期保留的统一业务任务主账本。"""

from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import new_id
from ..timeutil import utcnow
from .base import Base, UTCDateTime

_EXECUTION = "'requested','running','succeeded','partial_success','failed','blocked','abandoned'"
_DESIGN = "'pending','compliant','deviation','incomplete'"


class BusinessTask(Base):
    __tablename__ = "business_task"
    __table_args__ = (
        CheckConstraint(f"execution_status in ({_EXECUTION})", name="ck_business_task_execution_status"),
        CheckConstraint(f"design_status in ({_DESIGN})", name="ck_business_task_design_status"),
        CheckConstraint(
            "(execution_status = 'requested' and started_at is null and finished_at is null and exit_code is null and design_status = 'pending') or "
            "(execution_status = 'running' and started_at is not null and finished_at is null and exit_code is null and design_status = 'pending') or "
            "(execution_status in ('succeeded','partial_success','failed','blocked','abandoned') and started_at is not null and finished_at is not null and exit_code is not null and design_status <> 'pending')",
            name="ck_business_task_lifecycle",
        ),
        CheckConstraint("finished_at is null or finished_at >= started_at", name="ck_business_task_time_order"),
        CheckConstraint("design_status <> 'deviation' or exit_code = 9", name="ck_business_task_deviation_exit"),
        CheckConstraint("execution_status <> 'succeeded' or design_status <> 'compliant' or exit_code = 0", name="ck_business_task_success_result"),
        Index(
            "ix_business_task_recovery",
            "lock_domain",
            "execution_status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("task"))
    module: Mapped[str] = mapped_column(String(128), index=True)
    operation: Mapped[str] = mapped_column(String(128), index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), index=True)
    operator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    path_type: Mapped[str] = mapped_column(String(32), index=True)
    execution_status: Mapped[str] = mapped_column(String(32), default="requested", index=True)
    design_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    workflow_name: Mapped[str] = mapped_column(String(128))
    workflow_version: Mapped[str] = mapped_column(String(64))
    lock_domain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    executor_instance: Mapped[str | None] = mapped_column(String(256), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope_snapshot: Mapped[dict] = mapped_column(JSON, default=lambda: {"schema_version": "audit-scope/v1"})
    expected_stages_snapshot: Mapped[dict] = mapped_column(JSON, default=lambda: {"schema_version": "audit-expected-stages/v1", "stages": []})
    summary_snapshot: Mapped[dict] = mapped_column(JSON, default=lambda: {"schema_version": "audit-summary/v1"})
    design_validation_snapshot: Mapped[dict] = mapped_column(JSON, default=lambda: {"schema_version": "audit-validation/v1", "status": "pending", "results": []})
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, index=True)
    started_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)
