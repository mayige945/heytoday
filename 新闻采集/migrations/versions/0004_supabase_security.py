"""补齐 Supabase 审计策略与禁止重聚外键索引。

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_RUNTIME_TABLES = (
    "news_source",
    "news_article",
    "news_event",
    "llm_run",
    "fetch_log",
    "fact_check_record",
    "event_review",
    "cluster_forbid_pair",
)


def upgrade() -> None:
    bind = op.get_bind()
    indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("cluster_forbid_pair")
    }
    if "ix_cluster_forbid_pair_article_b_id" not in indexes:
        op.create_index(
            "ix_cluster_forbid_pair_article_b_id",
            "cluster_forbid_pair",
            ["article_b_id"],
        )

    if bind.dialect.name != "postgresql":
        return

    for table in _RUNTIME_TABLES:
        policy = f"deny_client_{table}"
        op.execute(sa.text(f'drop policy if exists "{policy}" on public."{table}"'))
        op.execute(
            sa.text(
                f'create policy "{policy}" on public."{table}" '
                "as restrictive for all to anon, authenticated "
                "using (false) with check (false)"
            )
        )

    op.execute(sa.text("alter table public.alembic_version enable row level security"))
    op.execute(
        sa.text(
            "revoke all on table public.alembic_version from public, anon, authenticated"
        )
    )
    op.execute(
        sa.text(
            "create policy deny_client_alembic_version on public.alembic_version "
            "as restrictive for all to anon, authenticated "
            "using (false) with check (false)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in _RUNTIME_TABLES:
            op.execute(
                sa.text(
                    f'drop policy if exists "deny_client_{table}" on public."{table}"'
                )
            )
        op.execute(
            sa.text(
                "drop policy if exists deny_client_alembic_version "
                "on public.alembic_version"
            )
        )
    indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("cluster_forbid_pair")
    }
    if "ix_cluster_forbid_pair_article_b_id" in indexes:
        op.drop_index(
            "ix_cluster_forbid_pair_article_b_id",
            table_name="cluster_forbid_pair",
        )
