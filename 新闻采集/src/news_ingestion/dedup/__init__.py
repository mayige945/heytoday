"""去重层入口：按 URL → 标题 → 内容（SHA-256 / SimHash）优先序判定。"""

from __future__ import annotations

from ..config import FiltersConfig
from ..types import DedupCandidate, DedupDecision
from .content_dedup import (
    build_candidate_from_content,
    find_content_duplicate,
    hamming_distance,
    simhash,
)
from .url_dedup import find_title_duplicate, find_url_duplicate, fingerprint_title

__all__ = [
    "build_candidate_from_content",
    "find_content_duplicate",
    "find_duplicate",
    "find_title_duplicate",
    "find_url_duplicate",
    "fingerprint_title",
    "hamming_distance",
    "simhash",
]


def find_duplicate(
    target: DedupCandidate,
    candidates: list[DedupCandidate],
    *,
    filters: FiltersConfig | None = None,
) -> DedupDecision:
    """按 plan §10 优先序判定 target 是否为某 candidate 的重复。"""
    hamming = filters.content_dedup.simhash_hamming_threshold if filters else 3
    min_chars = filters.content_dedup.min_chinese_chars_for_simhash if filters else 200

    decision = find_url_duplicate(target, candidates)
    if decision.is_duplicate:
        return decision
    decision = find_title_duplicate(target, candidates)
    if decision.is_duplicate:
        return decision
    return find_content_duplicate(
        target,
        candidates,
        hamming_threshold=hamming,
        min_chinese_chars=min_chars,
    )
