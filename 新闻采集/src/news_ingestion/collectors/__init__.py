"""采集器层：RSS / 网页 / RSSHub + 安全 HTTP。"""

from __future__ import annotations

from .base import Collector, get_collector
from .http import (
    BlockedTargetError,
    ContentTypeRejectedError,
    FetchError,
    FetchResponse,
    HttpStatusError,
    ResponseTooBigError,
    safe_fetch,
    validate_target,
)

__all__ = [
    "BlockedTargetError",
    "Collector",
    "ContentTypeRejectedError",
    "FetchError",
    "FetchResponse",
    "HttpStatusError",
    "ResponseTooBigError",
    "get_collector",
    "safe_fetch",
    "validate_target",
]
