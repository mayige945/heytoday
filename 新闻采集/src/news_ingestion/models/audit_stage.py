"""任务内按实际序号排列的业务阶段账本。"""

from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import new_id
from ..timeutil import utcnow
from .base import Base, UTCDateTime


class BusinessTaskStage(Base):
    __tablename__ = "business_task_stage"
    __table_args__ = (
        UniqueConstraint("id", "task_id", name="uq_business_task_stage_id_task"),
        UniqueConstraint("task_id", "actual_sequence", name="uq_business_task_stage_actual_sequence"),
        UniqueConstraint("task_id", "stage_key", "attempt_no", name="uq_business_task_stage_attempt"),
        CheckConstraint("attempt_no > 0", name="ck_business_task_stage_attempt_positive"),
        CheckConstraint("expected_sequence > 0 and actual_sequence > 0", name="ck_business_task_stage_sequence_positive"),
        CheckConstraint("input_count is null or input_count >= 0", name="ck_business_task_stage_input_non_negative"),
        CheckConstraint("output_count is null or output_count >= 0", name="ck_business_task_stage_output_non_negative"),
        CheckConstraint("status in ('requested','running','succeeded','failed','blocked','abandoned')", name="ck_business_task_stage_status"),
        CheckConstraint(
            "(status = 'requested' and started_at is null and finished_at is null) or "
            "(status = 'running' and started_at is not null and finished_at is null) or "
            "(status in ('succeeded','failed','blocked','abandoned') and started_at is not null and finished_at is not null)",
            name="ck_business_task_stage_lifecycle",
        ),
        CheckConstraint("finished_at is null or finished_at >= started_at", name="ck_business_task_stage_time_order"),
        Index("ix_business_task_stage_task_status", "task_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("stage"))
    task_id: Mapped[str] = mapped_column(ForeignKey("business_task.id", ondelete="RESTRICT"), index=True)
    stage_key: Mapped[str] = mapped_column(String(128))
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    expected_sequence: Mapped[int] = mapped_column(Integer)
    actual_sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prerequisite_evidence: Mapped[dict] = mapped_column(JSON, default=lambda: {"schema_version": "audit-prerequisites/v1", "items": []})
    routes_snapshot: Mapped[dict] = mapped_column(JSON, default=lambda: {"schema_version": "audit-routes/v1", "routes": []})
    reason_breakdown: Mapped[dict] = mapped_column(JSON, default=lambda: {"schema_version": "audit-reasons/v1", "reasons": {}})
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, default=lambda: {"schema_version": "audit-metrics/v1", "metrics": {}})
    validation_snapshot: Mapped[dict] = mapped_column(JSON, default=lambda: {"schema_version": "audit-validation/v1", "status": "pending", "results": []})
    started_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True, default=utcnow)
    finished_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)

