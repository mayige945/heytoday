"""TOML → 类型化配置 + 严格校验（plan §14 阶段一）。

校验失败一律抛 ``ConfigError``，由 CLI 统一映射为退出码 2。
"""

from __future__ import annotations

import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import ConfigError
from ..models import enums
from .. import paths
from . import defaults
from .schema import (
    SOURCE_KNOWN_KEYS,
    SOURCE_REQUIRED_KEYS,
    ClusteringThresholds,
    ContentDedupConfig,
    FiltersConfig,
    RuntimeConfig,
    SourceConfig,
)

__all__ = [
    "ClusteringThresholds",
    "ContentDedupConfig",
    "FiltersConfig",
    "RuntimeConfig",
    "SourceConfig",
    "load_sources",
    "load_source_by_code",
    "load_filters",
    "load_runtime",
]


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"配置文件不存在：{path}")
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件 {path} 解析失败：{exc}") from exc


def _require_nonempty_str(value: Any, key: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"来源 {code!r} 字段 {key!r} 缺失或为空")
    return value.strip()


def _parse_date(value: Any, key: str, code: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        try:
            if len(text) == 10 and text[4] == "-" and text[7] == "-":
                return datetime.fromisoformat(text + "T00:00:00+00:00")
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ConfigError(f"来源 {code!r} 字段 {key!r} 不是合法日期：{value!r}") from exc
    raise ConfigError(f"来源 {code!r} 字段 {key!r} 不是合法日期：{value!r}")


def _build_source(raw: dict[str, Any]) -> SourceConfig:
    code_hint = str(raw.get("code", "<未知>"))

    unknown = set(raw) - SOURCE_KNOWN_KEYS
    if unknown:
        raise ConfigError(f"来源 {code_hint!r} 含未知字段：{sorted(unknown)}")

    for key in SOURCE_REQUIRED_KEYS:
        if key not in raw or raw[key] in (None, ""):
            raise ConfigError(f"来源 {code_hint!r} 缺少必填字段 {key!r}")

    code = _require_nonempty_str(raw["code"], "code", code_hint)
    unit_code = _require_nonempty_str(raw["unit_code"], "unit_code", code)

    source_category = raw["source_category"]
    if not enums.is_valid(source_category, enums.SourceCategory):
        raise ConfigError(
            f"来源 {code!r} source_category 非法：{source_category!r}（允许 {sorted(enums.values(enums.SourceCategory))}）"
        )

    acquisition_method = raw["acquisition_method"]
    if not enums.is_valid(acquisition_method, enums.AcquisitionMethod):
        raise ConfigError(
            f"来源 {code!r} acquisition_method 非法：{acquisition_method!r}"
        )

    access_review_status = raw.get("access_review_status", "uncertain")
    if not enums.is_valid(access_review_status, enums.AccessReviewStatus):
        raise ConfigError(f"来源 {code!r} access_review_status 非法：{access_review_status!r}")

    roles = raw.get("source_role", [])
    if not isinstance(roles, list) or not roles:
        raise ConfigError(f"来源 {code!r} source_role 必须是非空列表")
    for role in roles:
        if not enums.is_valid(role, enums.SourceRole):
            raise ConfigError(f"来源 {code!r} source_role 含非法值 {role!r}")

    enabled = bool(raw.get("enabled", False))
    if enabled and access_review_status != enums.AccessReviewStatus.VERIFIED.value:
        raise ConfigError(
            f"来源 {code!r} enabled=true 但 access_review_status={access_review_status!r}（必须为 verified 才能启用）"
        )

    # 采集方式专属必填
    if acquisition_method == enums.AcquisitionMethod.RSS.value:
        if not raw.get("feed_url"):
            raise ConfigError(f"来源 {code!r} 采集方式 rss 需要 feed_url")
    elif acquisition_method == enums.AcquisitionMethod.WEBPAGE.value:
        if not raw.get("list_page_urls"):
            raise ConfigError(f"来源 {code!r} 采集方式 webpage 需要 list_page_urls")
    elif acquisition_method == enums.AcquisitionMethod.RSSHUB.value:
        if not raw.get("rsshub_route"):
            raise ConfigError(f"来源 {code!r} 采集方式 rsshub 需要 rsshub_route")

    return SourceConfig(
        unit_code=unit_code,
        code=code,
        name=_require_nonempty_str(raw["name"], "name", code),
        homepage_url=_require_nonempty_str(raw["homepage_url"], "homepage_url", code),
        language=_require_nonempty_str(raw["language"], "language", code),
        source_category=source_category,
        acquisition_method=acquisition_method,
        source_role=list(roles),
        country_or_region=str(raw.get("country_or_region", "") or ""),
        feed_url=(raw.get("feed_url") or None),
        list_page_urls=list(raw.get("list_page_urls", []) or []),
        rsshub_route=(raw.get("rsshub_route") or None),
        enabled=enabled,
        priority=int(raw.get("priority", 50)),
        access_review_status=access_review_status,
        access_reviewed_at=_parse_date(raw.get("access_reviewed_at"), "access_reviewed_at", code),
        access_evidence_url=(raw.get("access_evidence_url") or None),
        disabled_reason=(raw.get("disabled_reason") or None),
        request_interval_seconds=float(raw.get("request_interval_seconds", defaults.HTTP_DEFAULTS["request_interval_seconds"])),
        max_concurrency_per_host=int(raw.get("max_concurrency_per_host", defaults.HTTP_DEFAULTS["max_concurrency_per_host"])),
        timeout_seconds=float(raw.get("timeout_seconds", defaults.HTTP_DEFAULTS["timeout_seconds"])),
        max_redirects=int(raw.get("max_redirects", defaults.HTTP_DEFAULTS["max_redirects"])),
        max_response_bytes=int(raw.get("max_response_bytes", defaults.HTTP_DEFAULTS["max_response_bytes"])),
        allowed_content_types=list(raw.get("allowed_content_types", []) or list(defaults.ALLOWED_CONTENT_TYPES_DEFAULT)),
        topic_tags=list(raw.get("topic_tags", []) or []),
        allowed_sections=list(raw.get("allowed_sections", []) or []),
        excluded_sections=list(raw.get("excluded_sections", []) or []),
        excluded_keywords=list(raw.get("excluded_keywords", []) or []),
        requires_fulltext_fetch=bool(raw.get("requires_fulltext_fetch", True)),
        requires_fact_check=bool(raw.get("requires_fact_check", False)),
        commercial_use_note=(raw.get("commercial_use_note") or None),
    )


def load_sources(config_dir: Path | None = None) -> list[SourceConfig]:
    """加载并校验全部来源记录（plan §14：未知字段/重复 code/非法枚举/缺失必填/enabled 未核验 → ConfigError）。"""
    config_dir = config_dir or paths.CONFIG_DIR
    data = _read_toml(config_dir / "sources.toml")
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ConfigError("sources.toml 缺少 [[sources]] 列表")

    sources: list[SourceConfig] = []
    seen_codes: set[str] = set()
    for index, raw in enumerate(raw_sources):
        if not isinstance(raw, dict):
            raise ConfigError(f"sources.toml 第 {index} 条不是表")
        source = _build_source(raw)
        if source.code in seen_codes:
            raise ConfigError(f"来源 code 重复：{source.code!r}")
        seen_codes.add(source.code)
        sources.append(source)
    return sources


def load_source_by_code(code: str, config_dir: Path | None = None) -> SourceConfig:
    for source in load_sources(config_dir):
        if source.code == code:
            return source
    raise ConfigError(f"未找到来源 code={code!r}")


def load_filters(config_dir: Path | None = None) -> FiltersConfig:
    config_dir = config_dir or paths.CONFIG_DIR
    path = config_dir / "filters.toml"
    data = _read_toml(path) if path.exists() else {}

    clustering_raw = data.get("clustering", {})
    clustering = ClusteringThresholds(
        title_keyword_jaccard=float(clustering_raw.get("title_keyword_jaccard", defaults.CLUSTERING_DEFAULTS["title_keyword_jaccard"])),
        entity_overlap_coefficient=float(clustering_raw.get("entity_overlap_coefficient", defaults.CLUSTERING_DEFAULTS["entity_overlap_coefficient"])),
        time_window_hours_general=int(clustering_raw.get("time_window_hours_general", defaults.CLUSTERING_DEFAULTS["time_window_hours_general"])),
        time_window_hours_ongoing=int(clustering_raw.get("time_window_hours_ongoing", defaults.CLUSTERING_DEFAULTS["time_window_hours_ongoing"])),
        time_window_hours_science=int(clustering_raw.get("time_window_hours_science", defaults.CLUSTERING_DEFAULTS["time_window_hours_science"])),
    )

    dedup_raw = data.get("content_dedup", {})
    content_dedup = ContentDedupConfig(
        simhash_hamming_threshold=int(dedup_raw.get("simhash_hamming_threshold", defaults.CONTENT_DEDUP_DEFAULTS["simhash_hamming_threshold"])),
        min_chinese_chars_for_simhash=int(dedup_raw.get("min_chinese_chars_for_simhash", defaults.CONTENT_DEDUP_DEFAULTS["min_chinese_chars_for_simhash"])),
        simhash_hash_bits=int(dedup_raw.get("simhash_hash_bits", defaults.CONTENT_DEDUP_DEFAULTS["simhash_hash_bits"])),
    )

    alias_raw = data.get("alias_dict", {})
    alias_dict = {str(k): str(v) for k, v in alias_raw.items()} if isinstance(alias_raw, dict) else dict(defaults.ALIAS_DICT)
    if not alias_dict:
        alias_dict = dict(defaults.ALIAS_DICT)

    safety_raw = data.get("safety", {})
    redline_recall = frozenset(safety_raw.get("redline_recall_keywords", []))
    sensitive_recall = frozenset(safety_raw.get("sensitive_recall_keywords", []))

    return FiltersConfig(
        clustering=clustering,
        content_dedup=content_dedup,
        alias_dict=alias_dict,
        chinese_stop_chars=frozenset(defaults.CHINESE_STOP_CHARS),
        latin_stopwords=frozenset(defaults.LATIN_STOPWORDS),
        url_tracking_exact=frozenset(defaults.URL_TRACKING_EXACT),
        url_tracking_prefixes=tuple(defaults.URL_TRACKING_PREFIXES),
        url_meaningless_fragments=frozenset(defaults.URL_MEANINGLESS_FRAGMENTS),
        media_suffixes=tuple(defaults.MEDIA_SUFFIXES),
        title_punctuation=defaults.TITLE_PUNCTUATION,
        redline_recall_keywords=redline_recall,
        sensitive_recall_keywords=sensitive_recall,
    )


def load_runtime(config_dir: Path | None = None) -> RuntimeConfig:
    config_dir = config_dir or paths.CONFIG_DIR
    path = config_dir / "filters.toml"
    data = _read_toml(path) if path.exists() else {}
    runtime_raw = data.get("runtime", {})
    return RuntimeConfig(
        busy_timeout_ms=int(runtime_raw.get("busy_timeout_ms", defaults.RUNTIME_DEFAULTS["busy_timeout_ms"])),
        stale_run_recovery_minutes=int(runtime_raw.get("stale_run_recovery_minutes", defaults.RUNTIME_DEFAULTS["stale_run_recovery_minutes"])),
        llm_max_retries=int(runtime_raw.get("llm_max_retries", defaults.RUNTIME_DEFAULTS["llm_max_retries"])),
        llmlight_max_tokens=int(runtime_raw.get("llmlight_max_tokens", defaults.RUNTIME_DEFAULTS["llmlight_max_tokens"])),
        llmfull_max_tokens=int(runtime_raw.get("llmfull_max_tokens", defaults.RUNTIME_DEFAULTS["llmfull_max_tokens"])),
        user_agent=str(runtime_raw.get("user_agent", defaults.HTTP_DEFAULTS["user_agent"])),
    )
