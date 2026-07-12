"""时间工具：统一 UTC 存储、Asia/Shanghai 展示。

SQLite 不擅长保留时区信息，因此本模块一律以 tz-aware UTC ``datetime`` 在
Python 层流转，并由 ``UTCDateTime`` TypeDecorator 以 ISO8601 UTC 字符串落库。
导出文件名、留存计算等需要本地时间时，统一经 ``to_shanghai`` 转换。
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc

# 日期格式化字符：保留连字符形式用于 CLI 选项与 DB/JSON 字段
AGE_BAND_CLI = {"upper-primary", "junior-high"}
AGE_BAND_FIELD = {"upper_primary", "junior_high"}
PARENT_MODES = {"conservative", "standard", "open"}


def utcnow() -> datetime:
    """当前 tz-aware UTC 时间。"""
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    """把任意 datetime 归一为 tz-aware UTC；naive 视作 UTC。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_shanghai(value: datetime | None) -> datetime | None:
    """转 Asia/Shanghai；``None`` 原样返回。"""
    if value is None:
        return None
    return to_utc(value).astimezone(SHANGHAI)


def shanghai_stamp(value: datetime | None = None) -> str:
    """``YYYYMMDD_HHmmss``（Asia/Shanghai），用于导出文件名。"""
    moment = to_shanghai(value) if value is not None else to_shanghai(utcnow())
    assert moment is not None
    return moment.strftime("%Y%m%d_%H%M%S")


def cli_age_to_field(age: str) -> str:
    """CLI 连字符档位 → DB/JSON 下划线档位。"""
    if age not in AGE_BAND_CLI:
        raise ValueError(f"非法年龄档 CLI 取值：{age}")
    return age.replace("-", "_")


def field_age_to_cli(age: str) -> str:
    return age.replace("_", "-")
