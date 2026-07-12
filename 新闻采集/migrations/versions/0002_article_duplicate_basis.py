"""news_article.duplicate_basis：保留去重判定依据（plan §10.3）。

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-11

新列记录文章被判重复的依据（url / title / sha256 / simhash）。幂等：仅当列不存在时新增，
兼容「初始迁移用 metadata.create_all 已带该列」与「旧库需补列」两种情况。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("news_article")}
    if "duplicate_basis" not in columns:
        with op.batch_alter_table("news_article", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("duplicate_basis", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("news_article") as batch_op:
        batch_op.drop_column("duplicate_basis")
