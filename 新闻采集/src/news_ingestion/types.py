"""跨层共享的数据结构（避免 collectors / services / repositories 互相依赖内部类型）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DiscoveredArticle:
    """采集器发现的单篇文章元数据（fetch 阶段产物，不含正文）。"""

    source_id: str
    url: str
    title: str
    guid: str | None = None
    canonical_url: str | None = None
    subtitle: str | None = None
    summary: str | None = None
    author: str | None = None
    section: str | None = None
    published_at: datetime | None = None
    language: str = ""
    image_urls: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    external_id: str | None = None


@dataclass
class FetchOutcome:
    """单来源一次采集的结果摘要，供 fetch_log 写入与健康统计。"""

    source_id: str
    items_found: int = 0
    items_created: int = 0
    items_updated: int = 0
    items_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    # status: success | partial_success | failed
    status: str = "success"
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DedupDecision:
    """内容去重判定（plan §10.3）。"""

    is_duplicate: bool
    duplicate_of: str | None = None
    basis: str = ""  # url | title | sha256 | simhash | none


@dataclass
class ClusterDecision:
    """聚类判定：归入某事件 or 新建。"""

    event_id: str
    merged_into_existing: bool
    basis: str = ""  # new | merged(<conditions>) | singleton


@dataclass
class FetchedContent:
    """正文抓取产物。"""

    content_raw: str | None
    content_clean: str | None
    content_hash: str | None
    final_url: str | None = None
    encoding: str | None = None
    error: str | None = None


@dataclass
class DedupCandidate:
    """去重比较用的文章视图（由服务从 NewsArticle 构造）。"""

    id: str
    urls: list[str] = field(default_factory=list)  # [canonical_url?, url]
    title: str = ""
    title_fingerprint: str = ""
    content_hash: str | None = None
    simhash: int | None = None
    chinese_chars: int = 0


@dataclass
class ClusterArticle:
    """聚类用的文章视图（由服务从 NewsArticle + 来源构造）。"""

    id: str
    title: str
    time: datetime  # 发布时间；缺失时由服务回填 discovered_at
    is_science: bool = False
    is_ongoing: bool = False
    source_tags: list[str] = field(default_factory=list)
    language: str = ""
