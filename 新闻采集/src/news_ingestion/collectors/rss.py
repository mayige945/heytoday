"""RSS 采集器 + RSS 2.0 / Atom 解析（标准库 ``xml.etree.ElementTree``）。

覆盖：命名空间（atom/content/dc）、CDATA、缺失 guid、相对链接、无发布时间、空 Feed。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from ..cleaners.url import clean_url
from ..config import SourceConfig
from ..errors import FetchError
from ..logging_setup import get_logger
from ..timeutil import to_utc
from ..types import DiscoveredArticle
from .base import Collector
from .http import safe_fetch

_LOG = get_logger(__name__)

_ATOM_NS = "http://www.w3.org/2005/Atom"
_CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
_DC_NS = "http://purl.org/dc/elements/1.1/"

_TAG_RE = re.compile(r"\s+")


def _strip(text: str | None) -> str | None:
    if text is None:
        return None
    return _TAG_RE.sub(" ", text).strip() or None


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    return _strip(element.text)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    # RFC822（RSS pubDate）
    try:
        parsed = parsedate_to_datetime(value)
        if parsed is not None:
            return to_utc(parsed)
    except (TypeError, ValueError):
        pass
    # ISO8601（Atom / 部分中文 RSS）
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return to_utc(parsed)
    except ValueError:
        return None


def parse_feed(xml_text: str) -> list[dict]:
    """解析 RSS 2.0 / Atom Feed，返回 [{title,url,guid,canonical_url,summary,published_at,author,tags}]。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FetchError(f"RSS 解析失败：{exc}") from exc

    items: list[dict] = []
    tag = root.tag.lower()

    if tag.endswith("feed") or root.tag == f"{{{_ATOM_NS}}}feed":
        base = _text(root.find(f"{{{_ATOM_NS}}}link")) or ""  # noqa: F841
        for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
            items.append(_parse_atom_entry(entry, root))
    else:
        channel = root.find("channel")
        container = channel if channel is not None else root
        for item in container.findall("item"):
            items.append(_parse_rss_item(item, container))
    return items


def _parse_rss_item(item: ET.Element, container: ET.Element) -> dict:
    title = _text(item.find("title"))
    link = _text(item.find("link"))
    # guid
    guid_el = item.find("guid")
    guid = _text(guid_el)
    is_permalink = False
    if guid_el is not None and guid_el.get("isPermaLink", "true").lower() != "false":
        is_permalink = bool(guid)
    # content:encoded / description
    description = _text(item.find("description"))
    content_encoded = _text(item.find(f"{{{_CONTENT_NS}}}encoded"))
    summary = content_encoded or description
    pub = _text(item.find("pubDate")) or _text(item.find(f"{{{_DC_NS}}}date"))
    author = _text(item.find("author")) or _text(item.find(f"{{{_DC_NS}}}creator"))
    tags = [_text(c) for c in item.findall("category") if _text(c)]

    # 相对链接处理：用 channel link 作 base
    base = _text(container.find("link")) or ""
    if link:
        link = urljoin(base, link)
    if is_permalink and guid and not link:
        link = guid

    return {
        "title": title,
        "url": link,
        "guid": guid,
        "canonical_url": clean_url(link) if link else None,
        "summary": summary,
        "published_at": _parse_date(pub),
        "author": author,
        "tags": tags,
    }


def _parse_atom_entry(entry: ET.Element, root: ET.Element) -> dict:
    title = _text(entry.find(f"{{{_ATOM_NS}}}title"))
    link = ""
    for link_el in entry.findall(f"{{{_ATOM_NS}}}link"):
        rel = (link_el.get("rel") or "alternate").lower()
        if rel == "alternate":
            href = link_el.get("href")
            if href:
                link = href
                break
    if not link:
        first = entry.find(f"{{{_ATOM_NS}}}link")
        if first is not None and first.get("href"):
            link = first.get("href") or ""
    guid = _text(entry.find(f"{{{_ATOM_NS}}}id")) or link
    summary_el = entry.find(f"{{{_ATOM_NS}}}summary") or entry.find(f"{{{_ATOM_NS}}}content")
    summary = None
    if summary_el is not None:
        raw = "".join(summary_el.itertext())
        summary = _strip(raw)
    pub = _text(entry.find(f"{{{_ATOM_NS}}}published")) or _text(entry.find(f"{{{_ATOM_NS}}}updated"))
    author_el = entry.find(f"{{{_ATOM_NS}}}author")
    author = None
    if author_el is not None:
        author = _text(author_el.find(f"{{{_ATOM_NS}}}name"))
    tags = []
    for cat in entry.findall(f"{{{_ATOM_NS}}}category"):
        label = cat.get("label") or cat.get("term")
        if label:
            tags.append(label.strip())

    base = ""
    root_link = root.find(f"{{{_ATOM_NS}}}link")
    # xml:base 未处理；相对链接用 entry 自身无法解析时保留原值
    if link:
        link = urljoin(base, link) if base else link

    return {
        "title": title,
        "url": link,
        "guid": guid,
        "canonical_url": clean_url(link) if link else None,
        "summary": summary,
        "published_at": _parse_date(pub),
        "author": author,
        "tags": tags,
    }


class RssCollector(Collector):
    acquisition_method = "rss"

    def collect(self, source: SourceConfig, *, user_agent: str, max_retries: int = 2) -> list[DiscoveredArticle]:
        if not source.feed_url:
            raise FetchError(f"来源 {source.code} 缺少 feed_url")
        response = safe_fetch(
            source.feed_url,
            timeout_seconds=source.timeout_seconds,
            max_redirects=source.max_redirects,
            max_bytes=source.max_response_bytes,
            allowed_content_types=tuple(source.allowed_content_types) or None,
            allow_private_hosts=frozenset(),
            max_retries=max_retries,
            user_agent=user_agent,
            min_interval_seconds=source.request_interval_seconds,
        )
        parsed_items = parse_feed(response.text())
        discovered: list[DiscoveredArticle] = []
        for item in parsed_items:
            if not item.get("url") or not item.get("title"):
                continue
            discovered.append(
                DiscoveredArticle(
                    source_id=source.code,
                    url=item["url"],
                    title=item["title"],
                    guid=item.get("guid"),
                    canonical_url=item.get("canonical_url"),
                    summary=item.get("summary"),
                    author=item.get("author"),
                    published_at=item.get("published_at"),
                    language=source.language,
                    tags=list(item.get("tags") or []),
                )
            )
        _LOG.info("rss collect %s: %d items", source.code, len(discovered))
        return discovered
