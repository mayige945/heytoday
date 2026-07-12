"""URL / 标题去重（plan §10.1 / §10.2）。"""

from __future__ import annotations

from ..cleaners.url import clean_url
from ..cleaners.text import title_fingerprint
from ..types import DedupCandidate, DedupDecision


def _clean_url_set(urls: list[str]) -> set[str]:
    return {clean_url(u) for u in urls if u}


def find_url_duplicate(target: DedupCandidate, candidates: list[DedupCandidate]) -> DedupDecision:
    target_urls = _clean_url_set(target.urls)
    if not target_urls:
        return DedupDecision(is_duplicate=False, basis="no_url")
    for cand in candidates:
        if cand.id == target.id:
            continue
        if target_urls & _clean_url_set(cand.urls):
            return DedupDecision(is_duplicate=True, duplicate_of=cand.id, basis="url")
    return DedupDecision(is_duplicate=False, basis="none")


def find_title_duplicate(target: DedupCandidate, candidates: list[DedupCandidate]) -> DedupDecision:
    if not target.title_fingerprint:
        return DedupDecision(is_duplicate=False, basis="no_title")
    for cand in candidates:
        if cand.id == target.id:
            continue
        if cand.title_fingerprint and cand.title_fingerprint == target.title_fingerprint:
            return DedupDecision(is_duplicate=True, duplicate_of=cand.id, basis="title")
    return DedupDecision(is_duplicate=False, basis="none")


def fingerprint_title(title: str) -> str:
    return title_fingerprint(title)
