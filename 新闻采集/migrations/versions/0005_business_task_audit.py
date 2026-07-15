"""新增通用业务任务审计账本与详情关联。

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_DETAIL_TABLES = ("fetch_log", "llm_run")
_COMMENTS = {
    "business_task": "跨模块业务任务主账本；长期保留执行与设计结论",
    "business_task_stage": "业务任务内按实际序号记录的阶段账本",
}


def _utc_type() -> sa.types.TypeEngine:
    """冻结本 revision 的跨方言时间类型，不依赖会继续演进的应用 ORM。"""
    return sa.DateTime(timezone=True).with_variant(sa.String(40), "sqlite")


def _create_business_task() -> None:
    op.create_table("business_task",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("module", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("operator", sa.String(256), nullable=True),
        sa.Column("path_type", sa.String(32), nullable=False),
        sa.Column("execution_status", sa.String(32), nullable=False),
        sa.Column("design_status", sa.String(32), nullable=False),
        sa.Column("workflow_name", sa.String(128), nullable=False),
        sa.Column("workflow_version", sa.String(64), nullable=False),
        sa.Column("lock_domain", sa.String(128), nullable=True),
        sa.Column("executor_instance", sa.String(256), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False),
        sa.Column("expected_stages_snapshot", sa.JSON(), nullable=False),
        sa.Column("summary_snapshot", sa.JSON(), nullable=False),
        sa.Column("design_validation_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", _utc_type(), nullable=False),
        sa.Column("started_at", _utc_type(), nullable=True),
        sa.Column("finished_at", _utc_type(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("execution_status in ('requested','running','succeeded','partial_success','failed','blocked','abandoned')", name="ck_business_task_execution_status"),
        sa.CheckConstraint("design_status in ('pending','compliant','deviation','incomplete')", name="ck_business_task_design_status"),
        sa.CheckConstraint(
            "(execution_status = 'requested' and started_at is null and finished_at is null and exit_code is null and design_status = 'pending') or "
            "(execution_status = 'running' and started_at is not null and finished_at is null and exit_code is null and design_status = 'pending') or "
            "(execution_status in ('succeeded','partial_success','failed','blocked','abandoned') and started_at is not null and finished_at is not null and exit_code is not null and design_status <> 'pending')",
            name="ck_business_task_lifecycle",
        ),
        sa.CheckConstraint("finished_at is null or finished_at >= started_at", name="ck_business_task_time_order"),
        sa.CheckConstraint("design_status <> 'deviation' or exit_code = 9", name="ck_business_task_deviation_exit"),
        sa.CheckConstraint("execution_status <> 'succeeded' or design_status <> 'compliant' or exit_code = 0", name="ck_business_task_success_result"),
    )
    for column in ("module", "operation", "trigger_type", "path_type", "execution_status", "design_status", "created_at"):
        op.create_index(f"ix_business_task_{column}", "business_task", [column])


def _create_business_task_stage() -> None:
    op.create_table("business_task_stage",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("stage_key", sa.String(128), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("expected_sequence", sa.Integer(), nullable=False),
        sa.Column("actual_sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column("input_count", sa.Integer(), nullable=True),
        sa.Column("output_count", sa.Integer(), nullable=True),
        sa.Column("prerequisite_evidence", sa.JSON(), nullable=False),
        sa.Column("routes_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason_breakdown", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("validation_snapshot", sa.JSON(), nullable=False),
        sa.Column("started_at", _utc_type(), nullable=True),
        sa.Column("finished_at", _utc_type(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["business_task.id"], name="fk_business_task_stage_task_id_business_task", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "task_id", name="uq_business_task_stage_id_task"),
        sa.UniqueConstraint("task_id", "actual_sequence", name="uq_business_task_stage_actual_sequence"),
        sa.UniqueConstraint("task_id", "stage_key", "attempt_no", name="uq_business_task_stage_attempt"),
        sa.CheckConstraint("attempt_no > 0", name="ck_business_task_stage_attempt_positive"),
        sa.CheckConstraint("expected_sequence > 0 and actual_sequence > 0", name="ck_business_task_stage_sequence_positive"),
        sa.CheckConstraint("input_count is null or input_count >= 0", name="ck_business_task_stage_input_non_negative"),
        sa.CheckConstraint("output_count is null or output_count >= 0", name="ck_business_task_stage_output_non_negative"),
        sa.CheckConstraint("status in ('requested','running','succeeded','failed','blocked','abandoned')", name="ck_business_task_stage_status"),
        sa.CheckConstraint(
            "(status = 'requested' and started_at is null and finished_at is null) or "
            "(status = 'running' and started_at is not null and finished_at is null) or "
            "(status in ('succeeded','failed','blocked','abandoned') and started_at is not null and finished_at is not null)",
            name="ck_business_task_stage_lifecycle",
        ),
        sa.CheckConstraint("finished_at is null or finished_at >= started_at", name="ck_business_task_stage_time_order"),
    )
    op.create_index("ix_business_task_stage_task_id", "business_task_stage", ["task_id"])
    op.create_index("ix_business_task_stage_status", "business_task_stage", ["status"])
    op.create_index("ix_business_task_stage_task_status", "business_task_stage", ["task_id", "status"])


def _add_detail_links(table: str) -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
    # 0001 历史上从当前 metadata 建表；空库可能已含新列，迁移需保持幂等。
    if {"audit_task_id", "audit_stage_id"} <= columns:
        return
    if bind.dialect.name == "postgresql":
        op.add_column(table, sa.Column("audit_task_id", sa.String(64), nullable=True))
        op.add_column(table, sa.Column("audit_stage_id", sa.String(64), nullable=True))
        op.create_check_constraint(f"ck_{table}_audit_link_pair", table, "(audit_task_id is null) = (audit_stage_id is null)")
        op.create_foreign_key(
            f"fk_{table}_audit_stage_task", table, "business_task_stage",
            ["audit_stage_id", "audit_task_id"], ["id", "task_id"],
            ondelete="RESTRICT", match="FULL",
        )
    else:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("audit_task_id", sa.String(64), nullable=True))
            batch.add_column(sa.Column("audit_stage_id", sa.String(64), nullable=True))
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.create_check_constraint(f"ck_{table}_audit_link_pair", "(audit_task_id is null) = (audit_stage_id is null)")
            batch.create_foreign_key(
                f"fk_{table}_audit_stage_task", "business_task_stage",
                ["audit_stage_id", "audit_task_id"], ["id", "task_id"],
                ondelete="RESTRICT", match="FULL",
            )
    op.create_index(f"ix_{table}_audit_task_id", table, ["audit_task_id"])
    op.create_index(f"ix_{table}_audit_stage_task", table, ["audit_stage_id", "audit_task_id"])


def _drop_detail_links(table: str) -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
    if not {"audit_task_id", "audit_stage_id"} <= columns:
        return
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
    for index in (f"ix_{table}_audit_stage_task", f"ix_{table}_audit_task_id"):
        if index in indexes:
            op.drop_index(index, table_name=table)
    if bind.dialect.name == "postgresql":
        op.drop_constraint(f"fk_{table}_audit_stage_task", table, type_="foreignkey")
        op.drop_constraint(f"ck_{table}_audit_link_pair", table, type_="check")
        op.drop_column(table, "audit_stage_id")
        op.drop_column(table, "audit_task_id")
    else:
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(f"fk_{table}_audit_stage_task", type_="foreignkey")
            batch.drop_constraint(f"ck_{table}_audit_link_pair", type_="check")
            batch.drop_column("audit_stage_id")
            batch.drop_column("audit_task_id")


def _secure_postgres_tables() -> None:
    bind = op.get_bind()
    existing_roles = set(
        bind.execute(
            sa.text("select rolname from pg_roles where rolname in ('anon','authenticated','service_role')")
        ).scalars()
    )
    clients = [role for role in ("anon", "authenticated") if role in existing_roles]
    for table, comment in _COMMENTS.items():
        op.execute(sa.text(f'alter table public."{table}" enable row level security'))
        op.execute(sa.text(f'revoke all on table public."{table}" from public'))
        for role in clients:
            op.execute(sa.text(f'revoke all on table public."{table}" from "{role}"'))
        if "service_role" in existing_roles:
            op.execute(sa.text(f'grant select, insert, update on table public."{table}" to service_role'))
        policy = f"deny_client_{table}"
        op.execute(sa.text(f'drop policy if exists "{policy}" on public."{table}"'))
        if clients:
            role_list = ", ".join(f'"{role}"' for role in clients)
            op.execute(
                sa.text(
                    f'create policy "{policy}" on public."{table}" '
                    f"as restrictive for all to {role_list} using (false) with check (false)"
                )
            )
        escaped = comment.replace("'", "''")
        op.execute(sa.text(f"comment on table public.\"{table}\" is '{escaped}'"))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("business_task"):
        _create_business_task()
    inspector = sa.inspect(bind)
    if not inspector.has_table("business_task_stage"):
        _create_business_task_stage()
    for table in _DETAIL_TABLES:
        _add_detail_links(table)
    if bind.dialect.name == "postgresql":
        _secure_postgres_tables()


def downgrade() -> None:
    bind = op.get_bind()
    for table in _DETAIL_TABLES:
        _drop_detail_links(table)
    inspector = sa.inspect(bind)
    if inspector.has_table("business_task_stage"):
        op.drop_table("business_task_stage")
    inspector = sa.inspect(bind)
    if inspector.has_table("business_task"):
        op.drop_table("business_task")

