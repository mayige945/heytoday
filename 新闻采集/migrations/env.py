"""Alembic 运行环境。

target_metadata 指向 ``news_ingestion.models.Base.metadata``，迁移因此与模型同源。
SQLite 使用 batch 模式，便于未来 ALTER TABLE。URL 优先取 alembic 配置中的
``sqlalchemy.url``（由代码注入），缺失时回退到 ``NEWS_DB_PATH`` / 默认库路径。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from news_ingestion import paths
from news_ingestion.models import Base

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # alembic.ini 里的日志段可选；解析失败不影响迁移本身
        pass

target_metadata = Base.metadata


def _resolve_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    db_path = os.environ.get("NEWS_DB_PATH") or str(paths.db_path())
    return f"sqlite:///{db_path}"


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_resolve_url(), future=True, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
