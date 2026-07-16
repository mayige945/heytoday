"""LLM 客户端：Anthropic SDK 指向 Kimi Coding 兼容接口（plan §8 / §19）。

- 客户端保留 Anthropic SDK 真实身份，不伪装 / 修改 User-Agent；
- 不记录 API Key、Authorization / x-api-key 头或 Cookie，错误文本脱敏并设长度上限；
- 429 / 5xx / 超时可重试（429 遵守 Retry-After），401 / 403 / 400 等确定性错误不重试；
- 遇到额度 / 用途限制 / 服务拒绝按 LLM 失败降级，不尝试绕过。
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import anthropic

from ..config import load_runtime
from ..errors import LlmNotConfiguredError, NewsIngestionError
from ..logging_setup import get_logger

PROVIDER = "kimi_coding_anthropic"
DEFAULT_MODEL = "kimi-for-coding"
EXPECTED_BASE_URL = "https://api.kimi.com/coding/"
ANTHROPIC_VERSION = "2023-06-01"

_LOG = get_logger(__name__)
_ERROR_LIMIT = 800
_REDACT_TOKEN = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+[A-Za-z0-9_\-]{6,})", re.IGNORECASE)


@dataclass
class LlmResponse:
    text: str
    model: str
    usage: dict[str, int]
    finish_reason: str | None = None


class LlmCallError(NewsIngestionError):
    """LLM 调用失败（已脱敏）。"""


def credentials_present() -> bool:
    # 优先 ANTHROPIC_API_KEY；部分部署环境（如内部 Anthropic 中转）只提供
    # ANTHROPIC_AUTH_TOKEN，作为 fallback 同样视为已配置（探测确认 x-api-key 用同值可用）。
    key = (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or "").strip()
    return bool(key) and bool(os.getenv("ANTHROPIC_BASE_URL", "").strip())


def sanitize_text(text: str | None) -> str | None:
    if text is None:
        return None
    redacted = _REDACT_TOKEN.sub("[REDACTED]", text)
    return redacted[:_ERROR_LIMIT]


class LlmClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_retries: int | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries if max_retries is not None else load_runtime().llm_max_retries
        if base_url.startswith("http://"):
            _LOG.warning("ANTHROPIC_BASE_URL 使用明文 HTTP：%s（仅供本地可信内网冒烟）", base_url)
        # max_retries=0：重试与 Retry-After 由本模块统一控制。
        # anthropic-version 头由 SDK 默认发送（2023-06-01），无需也不可作构造参数传入。
        self._client = anthropic.Anthropic(base_url=base_url, api_key=api_key, max_retries=0)

    @classmethod
    def from_env(cls, *, model: str | None = None, max_retries: int | None = None) -> "LlmClient":
        if not credentials_present():
            raise LlmNotConfiguredError("未配置 ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL")
        key = (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or "").strip()
        # model 可由调用方传入；否则读 LLM_MODEL（部署可覆盖，如内部中转用 claude-sonnet-5），
        # 再退回默认 DEFAULT_MODEL（kimi-for-coding）。
        return cls(
            base_url=os.environ["ANTHROPIC_BASE_URL"].strip(),
            api_key=key,
            model=model or os.getenv("LLM_MODEL") or DEFAULT_MODEL,
            max_retries=max_retries,
        )

    def complete(self, *, system: str, user: str, max_tokens: int) -> LlmResponse:
        last_error: str | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text = "".join(getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text")
                usage = {
                    "input_tokens": int(getattr(response.usage, "input_tokens", 0) or 0),
                    "output_tokens": int(getattr(response.usage, "output_tokens", 0) or 0),
                }
                return LlmResponse(text=text, model=getattr(response, "model", self.model), usage=usage)
            except anthropic.APIStatusError as exc:
                status = int(getattr(exc, "status_code", 0) or 0)
                if status == 429 or status >= 500:
                    last_error = f"HTTP {status}"
                    time.sleep(_retry_after(exc))
                    continue
                raise LlmCallError(sanitize_text(_describe_status_error(exc)) or f"HTTP {status}") from exc
            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
                last_error = type(exc).__name__
                if attempt < self.max_retries:
                    time.sleep(min(2.0 ** attempt, 4.0))
                    continue
                raise LlmCallError(sanitize_text(str(exc))) from exc
            except anthropic.APIError as exc:
                raise LlmCallError(sanitize_text(str(exc))) from exc
        raise LlmCallError(f"LLM 调用失败（已重试 {self.max_retries} 次）：{last_error}")


def _retry_after(exc: anthropic.APIStatusError) -> float:
    headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
    value = headers.get("retry-after") or headers.get("Retry-After")
    if not value:
        return min(2.0, 1.0)
    text = str(value).strip()
    if text.isdigit():
        return min(float(text), 60.0)
    try:
        when = parsedate_to_datetime(text)
        if when is not None:
            return max(0.0, min(when.timestamp() - time.time(), 60.0))
    except (TypeError, ValueError):
        pass
    return min(2.0, 1.0)


def _describe_status_error(exc: anthropic.APIStatusError) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return json_safe(body)
    message = getattr(exc, "message", "") or str(exc)
    return message


def json_safe(obj: Any) -> str:
    import json

    try:
        return json.dumps(obj, ensure_ascii=False)[:_ERROR_LIMIT]
    except (TypeError, ValueError):
        return str(obj)[:_ERROR_LIMIT]
