"""URL 清洗与规范化（plan §10.1）。

用途：去重前把追踪 / 渠道 / 分享参数和无意义锚点去掉，得到稳定的 canonical
身份。优先序：canonical URL → RSS guid → 清洗后 URL → 原始 URL。
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..config import defaults


def _drop_tracking_params(
    query: str,
    *,
    tracking_exact: frozenset[str],
    tracking_prefixes: tuple[str, ...],
) -> str:
    kept = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key in tracking_exact:
            continue
        if any(key.startswith(prefix) for prefix in tracking_prefixes):
            continue
        kept.append((key, value))
    kept.sort()
    return urlencode(kept)


def clean_url(
    url: str,
    *,
    tracking_exact: frozenset[str] = defaults.URL_TRACKING_EXACT,
    tracking_prefixes: tuple[str, ...] = defaults.URL_TRACKING_PREFIXES,
    meaningless_fragments: frozenset[str] = defaults.URL_MEANINGLESS_FRAGMENTS,
) -> str:
    """移除追踪参数与无意义锚点，返回清洗后 URL。非法 URL 原样返回。"""
    if not url or not isinstance(url, str):
        return url
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # 去掉默认端口
    if netloc and ":" in netloc:
        host, _, port = netloc.partition(":")
        if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
            netloc = host

    query = _drop_tracking_params(
        parts.query, tracking_exact=tracking_exact, tracking_prefixes=tracking_prefixes
    )
    fragment = parts.fragment
    if fragment in meaningless_fragments:
        fragment = ""

    return urlunsplit((scheme, netloc, parts.path or "/", query, fragment))


def normalize_url(url: str, **kwargs) -> str:
    """清洗 URL 的别名（语义同 clean_url）。"""
    return clean_url(url, **kwargs)


def is_same_url(a: str, b: str) -> bool:
    return clean_url(a) == clean_url(b)
