"""initial: 创建全部七张表（与 Base.metadata 同源）。

Revision ID: 0001
Revises:
Create Date: 2026-07-10

首版迁移直接以 ``Base.metadata.create_all`` 建表，保证表结构与 ORM 模型完全
一致；后续结构变更需新增 revision 并使用 batch 模式（SQLite）。
"""

from __future__ import annotations

from alembic import op

from news_ingestion.models import Base

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
