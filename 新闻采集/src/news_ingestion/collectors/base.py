"""Collector 统一接口与工厂。

采集器只负责发现文章元数据（fetch 阶段），不抓正文；正文抓取由正文服务在一级
识别后进行。所有外部请求经 ``collectors.http.safe_fetch`` 统一遵守 SSRF / 大小 /
content-type / Retry-After 等约束。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import SourceConfig
from ..types import DiscoveredArticle


class Collector(ABC):
    acquisition_method: str = ""

    @abstractmethod
    def collect(
        self,
        source: SourceConfig,
        *,
        user_agent: str,
        max_retries: int = 2,
    ) -> list[DiscoveredArticle]:
        """采集一个来源，返回发现的元数据文章列表。失败抛 ``FetchError``。"""


def get_collector(method: str) -> Collector:
    """按 acquisition_method 返回对应采集器。"""
    # 局部导入避免循环依赖
    if method == "rss":
        from .rss import RssCollector

        return RssCollector()
    if method == "webpage":
        from .webpage import WebpageCollector

        return WebpageCollector()
    if method == "rsshub":
        from .rsshub import RssHubCollector

        return RssHubCollector()
    raise ValueError(f"未知采集方式：{method!r}")
