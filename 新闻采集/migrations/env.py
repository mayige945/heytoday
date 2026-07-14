"""Alembic 运行环境。

target_metadata 指向 ``news_ingestion.models.Base.metadata``，迁移因此与模型同源。
生产 URL 取 ``SUPABASE_DB_URL``，测试可显式注入 ``NEWS_DATABASE_URL``。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context

from news_ingestion.db.session import make_engine
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
    url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("NEWS_DATABASE_URL")
    if not url:
        raise RuntimeError("缺少 SUPABASE_DB_URL")
    return str(url)


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_resolve_url().startswith("sqlite:"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = make_engine(_resolve_url())
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
