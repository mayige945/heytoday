"""通用网页列表页解析器（标准库 ``html.parser``）。

抽取页面中的文章锚点，按来源的 allowed_sections / excluded_sections / excluded_keywords
过滤。来源特定解析规则在 ``parsers/sources/<code>.py`` 覆盖；页面改版不影响其它来源。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ..cleaners.text import normalize_text
from ..cleaners.url import clean_url
from ..config import SourceConfig
from ..types import DiscoveredArticle

# 锚点文本长度区间：太短多半是导航，太长多半不是标题
_MIN_TITLE_LEN = 4
_MAX_TITLE_LEN = 200


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_pieces: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):  # type: ignore[override]
        if tag.lower() == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "")
            self._href = href or None
            self._text_pieces = []
            self._depth += 1

    def handle_data(self, data):  # type: ignore[override]
        if self._depth > 0:
            self._text_pieces.append(data)

    def handle_endtag(self, tag):  # type: ignore[override]
        if tag.lower() == "a" and self._depth > 0:
            text = normalize_text("".join(self._text_pieces))
            if self._href and text:
                self.anchors.append((self._href, text))
            self._href = None
            self._text_pieces = []
            self._depth -= 1


def _section_of(url: str) -> str:
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    return segments[0] if segments else ""


def _is_article_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return False
    if not parts.netloc:
        return False
    return True


def parse_list(html: str, base_url: str, source: SourceConfig) -> list[DiscoveredArticle]:
    """通用列表页解析：返回过滤后的文章元数据列表。"""
    parser = _AnchorCollector()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass

    allowed_sections = {s.strip().lower() for s in source.allowed_sections if s.strip()}
    excluded_sections = {s.strip().lower() for s in source.excluded_sections if s.strip()}
    excluded_keywords = [k.lower() for k in source.excluded_keywords if k.strip()]
    seen: set[str] = set()
    results: list[DiscoveredArticle] = []

    for href, text in parser.anchors:
        title = text.strip()
        if not (_MIN_TITLE_LEN <= len(title) <= _MAX_TITLE_LEN):
            continue
        if any(kw in title.lower() for kw in excluded_keywords):
            continue
        full_url = urljoin(base_url, href)
        if not _is_article_url(full_url):
            continue
        section = _section_of(full_url).lower()
        path_lower = urlsplit(full_url).path.lower()
        # allowed_sections 用路径包含匹配（兼容 /newsDetail_123 这类「前缀+id」栏目）
        if allowed_sections and not any(tok in path_lower for tok in allowed_sections):
            continue
        if excluded_sections and any(tok in path_lower for tok in excluded_sections):
            continue
        cleaned = clean_url(full_url)
        if cleaned in seen:
            continue
        seen.add(cleaned)
        results.append(
            DiscoveredArticle(
                source_id=source.code,
                url=full_url,
                canonical_url=cleaned,
                title=title,
                language=source.language,
                section=section or None,
            )
        )
    return results
