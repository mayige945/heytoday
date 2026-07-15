"""审计持久化与技术日志共用的递归秘密净化边界。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_REDACTED = "[REDACTED]"
_NEXT_SECRET_FIELD = (
    r"(?=\s+(?:authorization|proxy-authorization|cookie|set-cookie|"
    r"x-api-key|api(?:[\s_-]+)?key)\s*[:=]|\s*\]|$)"
)
_INLINE_SECRET_PATTERNS = (
    re.compile(
        rf"(?i)(\b(?:proxy-)?authorization\s*[:=]\s*)digest\b.*?{_NEXT_SECRET_FIELD}"
    ),
    re.compile(
        r"(?i)(\b(?:proxy-)?authorization\s*[:=]\s*)(?:basic|bearer)\s+[^\s,\]]+"
    ),
    re.compile(
        r"(?i)(\b(?:proxy-)?authorization\s*[:=]\s*)(?!\[REDACTED\])[^\s,\]]+"
    ),
    re.compile(
        rf"(?i)(\b(?:set-cookie|cookie)\s*[:=]\s*).*?{_NEXT_SECRET_FIELD}"
    ),
    re.compile(r"(?i)(\bx-api-key\s*[:=]\s*)[^\s,\]]+"),
    re.compile(r"(?i)((?<![\w-])api(?:[\s_-]+)?key\s*[:=]\s*)[^\s,\]]+"),
)
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "xapikey",
        "apikey",
        "accesskey",
        "secretkey",
        "clientsecret",
        "password",
        "token",
        "accesstoken",
        "refreshtoken",
        "privatekey",
    }
)


def redact_secrets(text: str | None) -> str | None:
    """净化自由文本中的常见认证头、Cookie 与 API Key。"""
    if text is None:
        return None
    redacted = text
    for pattern in _INLINE_SECRET_PATTERNS:
        redacted = pattern.sub(rf"\1{_REDACTED}", redacted)
    return redacted


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return normalized in _SENSITIVE_KEYS


def sanitize_audit_value(value: Any) -> Any:
    """递归净化将进入长期审计账本的 JSON 兼容值。"""
    if isinstance(value, Mapping):
        return {
            key: _REDACTED if _is_sensitive_key(key) else sanitize_audit_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_audit_value(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value
