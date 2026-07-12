"""配置 dataclass 与 TOML 字段定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# 一个 source TOML 表允许出现的全部字段；超出即「未知字段」→ ConfigError。
SOURCE_KNOWN_KEYS: frozenset[str] = frozenset(
    {
        "unit_code", "code", "name", "homepage_url", "language",
        "country_or_region", "source_category", "source_role",
        "acquisition_method", "feed_url", "list_page_urls", "rsshub_route",
        "enabled", "priority", "access_review_status", "access_reviewed_at",
        "access_evidence_url", "disabled_reason",
        "request_interval_seconds", "max_concurrency_per_host",
        "timeout_seconds", "max_redirects", "max_response_bytes",
        "allowed_content_types",
        "topic_tags", "allowed_sections", "excluded_sections",
        "excluded_keywords",
        "requires_fulltext_fetch", "requires_fact_check",
        "commercial_use_note",
    }
)

SOURCE_REQUIRED_KEYS: tuple[str, ...] = (
    "unit_code", "code", "name", "homepage_url", "language",
    "source_category", "acquisition_method",
)


@dataclass
class SourceConfig:
    """一条来源记录（plan §9.1）。"""

    unit_code: str
    code: str
    name: str
    homepage_url: str
    language: str
    source_category: str
    acquisition_method: str
    source_role: list[str] = field(default_factory=list)
    country_or_region: str = ""
    feed_url: str | None = None
    list_page_urls: list[str] = field(default_factory=list)
    rsshub_route: str | None = None
    enabled: bool = False
    priority: int = 50
    access_review_status: str = "uncertain"
    access_reviewed_at: datetime | None = None
    access_evidence_url: str | None = None
    disabled_reason: str | None = None
    request_interval_seconds: float = 5.0
    max_concurrency_per_host: int = 1
    timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_response_bytes: int = 5_000_000
    allowed_content_types: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    allowed_sections: list[str] = field(default_factory=list)
    excluded_sections: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    requires_fulltext_fetch: bool = True
    requires_fact_check: bool = False
    commercial_use_note: str | None = None

    @property
    def is_trend_radar(self) -> bool:
        return self.unit_code == "S14"

    @property
    def can_be_fact_source(self) -> bool:
        return "fact_source" in self.source_role


@dataclass
class ClusteringThresholds:
    title_keyword_jaccard: float = 0.60
    entity_overlap_coefficient: float = 0.80
    time_window_hours_general: int = 72
    time_window_hours_ongoing: int = 7 * 24
    time_window_hours_science: int = 30 * 24


@dataclass
class ContentDedupConfig:
    simhash_hamming_threshold: int = 3
    min_chinese_chars_for_simhash: int = 200
    simhash_hash_bits: int = 64


@dataclass
class FiltersConfig:
    clustering: ClusteringThresholds = field(default_factory=ClusteringThresholds)
    content_dedup: ContentDedupConfig = field(default_factory=ContentDedupConfig)
    alias_dict: dict[str, str] = field(default_factory=dict)
    chinese_stop_chars: frozenset[str] = field(default_factory=frozenset)
    latin_stopwords: frozenset[str] = field(default_factory=frozenset)
    url_tracking_exact: frozenset[str] = field(default_factory=frozenset)
    url_tracking_prefixes: tuple[str, ...] = field(default_factory=tuple)
    url_meaningless_fragments: frozenset[str] = field(default_factory=frozenset)
    media_suffixes: tuple[str, ...] = field(default_factory=tuple)
    title_punctuation: str = ""
    # 红线关键词召回（plan §11.2 / §8.5：只召回，不单独判红）
    redline_recall_keywords: frozenset[str] = field(default_factory=frozenset)
    sensitive_recall_keywords: frozenset[str] = field(default_factory=frozenset)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clustering": self.clustering.__dict__,
            "content_dedup": self.content_dedup.__dict__,
        }


@dataclass
class RuntimeConfig:
    busy_timeout_ms: int = 5000
    stale_run_recovery_minutes: int = 30
    llm_max_retries: int = 2
    llmlight_max_tokens: int = 512
    llmfull_max_tokens: int = 2048
    user_agent: str = ""
