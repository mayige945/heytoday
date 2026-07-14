"""SQLAlchemy 2.x 声明基类与公共类型。

``UTCDateTime``：SQLite 不保留时区，故统一以 ISO8601 UTC 字符串落库，
Python 层拿到 tz-aware UTC ``datetime``，边界处再转 Asia/Shanghai。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import orm, types

class UTCDateTime(types.TypeDecorator):
    """Postgres 使用 timestamptz；SQLite 测试使用 ISO8601 字符串。"""

    impl = types.VARCHAR(40)
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(types.DateTime(timezone=True))
        return dialect.type_descriptor(types.VARCHAR(40))

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        normalized = value.astimezone(timezone.utc)
        return normalized if dialect.name == "postgresql" else normalized.isoformat()

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


class Base(orm.DeclarativeBase):
    """所有 ORM 模型的基类。"""
