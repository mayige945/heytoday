"""RSSHub 采集器（plan §6.3）：只作适配层，热点只进线索库。

通过 ``RSSHUB_BASE_URL``（或 ``filters.toml [rsshub] base_url``）支持自建 RSSHub；
仅当 base 显式指向 localhost/127.0.0.1/::1 时才放行私网目标。失败不阻塞其它来源。
"""

from __future__ import annotations

import os
import tomllib
from urllib.parse import urljoin, urlsplit

from ..config import SourceConfig
from ..errors import FetchError
from ..logging_setup import get_logger
from ..paths import CONFIG_DIR
from ..types import DiscoveredArticle
from .base import Collector
from .http import safe_fetch
from .rss import parse_feed

_LOG = get_logger(__name__)
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def resolve_rsshub_base() -> str | None:
    env_value = os.environ.get("RSSHUB_BASE_URL", "").strip()
    if env_value:
        return env_value.rstrip("/")
    config_path = CONFIG_DIR / "filters.toml"
    if config_path.exists():
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
        value = str(data.get("rsshub", {}).get("base_url", "") or "").strip()
        if value:
            return value.rstrip("/")
    return None


class RssHubCollector(Collector):
    acquisition_method = "rsshub"

    def collect(self, source: SourceConfig, *, user_agent: str, max_retries: int = 2) -> list[DiscoveredArticle]:
        if not source.rsshub_route:
            raise FetchError(f"来源 {source.code} 缺少 rsshub_route")
        base = resolve_rsshub_base()
        if not base:
            raise FetchError("RSSHUB_BASE_URL 未配置，且 filters.toml 未登记公网 RSSHub")

        host = urlsplit(base).hostname or ""
        allow_private = frozenset({host}) if host in _LOCALHOST_HOSTS else frozenset()
        url = urljoin(base.rstrip("/") + "/", source.rsshub_route.lstrip("/"))

        response = safe_fetch(
            url,
            timeout_seconds=source.timeout_seconds,
            max_redirects=source.max_redirects,
            max_bytes=source.max_response_bytes,
            allowed_content_types=tuple(source.allowed_content_types) or None,
            allow_private_hosts=allow_private,
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
        _LOG.info("rsshub collect %s: %d items", source.code, len(discovered))
        return discovered
