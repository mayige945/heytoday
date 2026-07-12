"""SQLite 引擎与会话工厂。

连接一律启用 ``foreign_keys``；文件库额外启用 ``WAL`` 与可配置 ``busy_timeout``。
测试可用 ``make_engine(tmp_path)`` 或内存库。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import load_runtime
from ..paths import db_path, ensure_runtime_dirs


def _is_memory(db_path: Path | str) -> bool:
    text = str(db_path)
    return text == ":memory:" or text.endswith("/:memory:") or text == "sqlite://"


def make_engine(
    db_path: Path | str,
    *,
    busy_timeout_ms: int | None = None,
    echo: bool = False,
) -> Engine:
    """构造 SQLite 引擎；文件库启用 WAL，内存库跳过 WAL。"""
    if busy_timeout_ms is None:
        try:
            busy_timeout_ms = load_runtime().busy_timeout_ms
        except Exception:  # 配置缺失时回退默认
            busy_timeout_ms = 5000

    text = str(db_path)
    memory = _is_memory(text)
    if text in ("sqlite://",):
        url = "sqlite://"
    elif text.startswith("sqlite:"):
        url = text
    else:
        if not memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
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
    """基于 ``paths.db_path()`` + 运行期配置构造默认引擎（确保 data 目录存在）。"""
    ensure_runtime_dirs()
    return make_engine(db_path())
