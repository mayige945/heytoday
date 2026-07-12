"""SQLAlchemy 2.x 声明基类与公共类型。

``UTCDateTime``：SQLite 不保留时区，故统一以 ISO8601 UTC 字符串落库，
Python 层拿到 tz-aware UTC ``datetime``，边界处再转 Asia/Shanghai。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import orm, types

from ..timeutil import utcnow


class UTCDateTime(types.TypeDecorator):
    """以 ISO8601 UTC 字符串存储 datetime，读回 tz-aware UTC。"""

    impl = types.VARCHAR(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        return datetime.fromisoformat(value)


class Base(orm.DeclarativeBase):
    """所有 ORM 模型的基类。"""
