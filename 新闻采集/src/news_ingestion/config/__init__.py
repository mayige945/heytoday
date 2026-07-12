"""配置层：把 ``config/*.toml`` 转为类型化 dataclass 并严格校验。

校验失败（未知字段、重复 code、非法枚举、缺失必填、enabled 但未核验访问）
一律抛 ``ConfigError``，CLI 转为退出码 2。
"""

from __future__ import annotations

from .loader import (
    FiltersConfig,
    RuntimeConfig,
    SourceConfig,
    load_filters,
    load_runtime,
    load_sources,
    load_source_by_code,
)
from . import defaults

__all__ = [
    "FiltersConfig",
    "RuntimeConfig",
    "SourceConfig",
    "defaults",
    "load_filters",
    "load_runtime",
    "load_sources",
    "load_source_by_code",
]
