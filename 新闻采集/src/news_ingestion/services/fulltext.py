"""正文抓取与清洗服务（plan §6.2 / §9.2）。

仅对一级 ``relevant`` / ``uncertain`` 且非重复的文章执行；抓取失败文章仍保留，只标
``failed``。返回 ``FetchedContent``，由调用方写入 ``content_raw`` / ``content_clean`` /
``content_hash``。
"""

from __future__ import annotations

from ..cleaners.html import html_to_text
from ..cleaners.text import normalize_text, sha256_hex
from ..collectors.http import FetchError, safe_fetch
from ..config import SourceConfig
from ..types import FetchedContent

_HTML_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/xml",
)


def fetch_article_content(
    url: str,
    *,
    source: SourceConfig,
    user_agent: str,
    max_retries: int = 2,
) -> FetchedContent:
    try:
        response = safe_fetch(
            url,
            timeout_seconds=source.timeout_seconds,
            max_redirects=source.max_redirects,
            max_bytes=source.max_response_bytes,
            # 正文页是 HTML：用 HTML 类型，不复用来源 feed 的 xml/rss allowed_content_types
            allowed_content_types=_HTML_CONTENT_TYPES,
            allow_private_hosts=frozenset(),
            max_retries=max_retries,
            user_agent=user_agent,
            min_interval_seconds=source.request_interval_seconds,
        )
    except FetchError as exc:
        return FetchedContent(content_raw=None, content_clean=None, content_hash=None, error=str(exc)[:500])

    html = response.text()
    cleaned = normalize_text(html_to_text(html))
    content_hash = sha256_hex(cleaned) if cleaned else None
    return FetchedContent(
        content_raw=html,
        content_clean=cleaned,
        content_hash=content_hash,
        final_url=response.final_url,
        encoding=response.encoding,
    )
