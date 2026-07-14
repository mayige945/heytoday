"""Supabase Postgres 生产引擎与测试数据库会话工厂。"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import load_runtime
from ..errors import ConfigError, DbInfraError


def _is_memory(db_path: Path | str) -> bool:
    text = str(db_path)
    return text == ":memory:" or text.endswith("/:memory:") or text == "sqlite://"


def make_engine(
    database: Path | str,
    *,
    busy_timeout_ms: int | None = None,
    echo: bool = False,
) -> Engine:
    """构造数据库引擎；SQLite 仅供显式注入的离线测试使用。"""
    if busy_timeout_ms is None:
        try:
            busy_timeout_ms = load_runtime().busy_timeout_ms
        except Exception:  # 配置缺失时回退默认
            busy_timeout_ms = 5000

    text = str(database)
    if text.startswith("postgres://"):
        text = "postgresql+psycopg://" + text.removeprefix("postgres://")
    elif text.startswith("postgresql://"):
        text = "postgresql+psycopg://" + text.removeprefix("postgresql://")

    if text.startswith("postgresql+psycopg://"):
        if "sslmode=" not in text:
            text += ("&" if "?" in text else "?") + "sslmode=require"
        return create_engine(
            text,
            echo=echo,
            future=True,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            pool_recycle=300,
            connect_args={
                "application_name": "heytoday-news-ingestion",
                "connect_timeout": 10,
            },
        )

    memory = _is_memory(text)
    if text in ("sqlite://",):
        url = "sqlite://"
    elif text.startswith("sqlite:"):
        url = text
    else:
        if not memory:
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{text}"

    engine = create_engine(url, echo=echo, future=True)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            if not memory:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def default_engine() -> Engine:
    """生产只接受 Supabase Postgres；SQLite 仅可由测试显式放行。"""
    database_url = (
        os.environ.get("SUPABASE_DB_URL")
        or os.environ.get("NEWS_DATABASE_URL")
        or ""
    ).strip()
    if not database_url:
        raise ConfigError(
            "缺少 SUPABASE_DB_URL；请使用 Supabase Connect 中的 Direct 或 Session pooler 连接串"
        )
    is_sqlite = database_url.startswith("sqlite:")
    if is_sqlite:
        if os.environ.get("NEWS_ALLOW_SQLITE_TESTS") != "1":
            raise ConfigError("生产运行禁止 SQLite；请配置 SUPABASE_DB_URL")
    elif not database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise ConfigError("SUPABASE_DB_URL 必须是 Postgres 连接串")
    try:
        return make_engine(database_url)
    except ConfigError:
        raise
    except Exception as exc:
        raise DbInfraError(f"无法创建 Supabase 数据库引擎：{exc.__class__.__name__}") from exc
