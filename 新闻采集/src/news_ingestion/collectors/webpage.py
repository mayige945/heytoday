"""网页栏目采集器：用通用 / 来源特定解析器抓列表页元数据（plan §6.2）。

只抓指定栏目（allowed_sections），不抓全站；列表页与正文页解析分离；页面改版不
影响其它来源。通用 ``html.parser`` 解析；来源特定规则在 ``parsers/sources/`` 覆盖。
"""

from __future__ import annotations

from ..config import SourceConfig
from ..errors import FetchError
from ..logging_setup import get_logger
from ..parsers import get_list_parser
from ..parsers import generic_list
from ..types import DiscoveredArticle
from .base import Collector
from .http import safe_fetch

_LOG = get_logger(__name__)


class WebpageCollector(Collector):
    acquisition_method = "webpage"

    def collect(self, source: SourceConfig, *, user_agent: str, max_retries: int = 2) -> list[DiscoveredArticle]:
        if not source.list_page_urls:
            raise FetchError(f"来源 {source.code} 缺少 list_page_urls")

        parser = get_list_parser(source.code) or generic_list.parse_list
        discovered: list[DiscoveredArticle] = []
        seen_urls: set[str] = set()

        for list_url in source.list_page_urls:
            response = safe_fetch(
                list_url,
                timeout_seconds=source.timeout_seconds,
                max_redirects=source.max_redirects,
                max_bytes=source.max_response_bytes,
                allowed_content_types=tuple(source.allowed_content_types) or None,
                allow_private_hosts=frozenset(),
                max_retries=max_retries,
                user_agent=user_agent,
                min_interval_seconds=source.request_interval_seconds,
            )
            items = parser(response.text(), response.final_url, source)
            for item in items:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                discovered.append(item)

        _LOG.info("webpage collect %s: %d items", source.code, len(discovered))
        return discovered
