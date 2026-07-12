"""内容去重：SHA-256 精确 + SimHash 近似（plan §10.3）。

正文为空或清洗后 < 200 中文字符时不做 SimHash 自动合并，只保留 URL/标题结果
并标人工复核。任何自动合并保留 ``duplicate_of`` 与判定依据，可人工撤销。
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from ..cleaners.text import count_chinese_chars, normalize_text
from ..types import DedupCandidate, DedupDecision

_SHINGLE_RE = re.compile(r"\s+")
# 去除转载常见样板，使 repost 在 SimHash 上对齐：电头 / 尾注 / 版权行
_LEADING_DATELINE = re.compile(
    r"^[\s]*[（(]?\s*[一-鿿]{0,10}?\s*(?:\d{1,4}\s*[年\-/.]\s*)?"
    r"\d{1,2}\s*[月\-/.]\s*\d{1,2}\s*日?\s*[）)]?\s*"
    r"(?:电|讯|报道|消息|编译|记者)?\s*[—\-:：·．.]*\s*"
)
_TRAILING_BOILERPLATE = re.compile(
    r"[（(]\s*(完|结束|完稿|责任编辑[：:].*|来源[：:].*)\s*[)）].*$"
)
_COPYRIGHT_LINE = re.compile(r"(版权所有|未经授权|禁止转载|责任编辑|原标题|监制).*$")


def _strip_boilerplate(text: str) -> str:
    text = _LEADING_DATELINE.sub("", text, count=1)
    text = _TRAILING_BOILERPLATE.sub("", text).strip()
    return text


def _shingles(text: str, k: int = 3) -> list[str]:
    compact = _SHINGLE_RE.sub("", text)
    if len(compact) < k:
        return [compact] if compact else []
    return [compact[i : i + k] for i in range(len(compact) - k + 1)]


def simhash(text: str | None, *, bits: int = 64) -> int:
    """对清洗后正文计算 ``bits`` 位 TF 加权 SimHash 指纹。

    先去转载样板（电头 / 尾注 / 版权行），再以 3 字 shingle 的词频为权重投票，
    使近 repost 在汉明距离上接近 0。
    """
    if not text:
        return 0
    normalized = _strip_boilerplate(normalize_text(text))
    counts = Counter(_shingles(normalized, k=3))
    votes = [0] * bits
    for shingle, weight in counts.items():
        digest = hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "big")
        for i in range(bits):
            votes[i] += weight if (h & (1 << i)) else -weight
    fingerprint = 0
    for i in range(bits):
        if votes[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def find_content_duplicate(
    target: DedupCandidate,
    candidates: list[DedupCandidate],
    *,
    hamming_threshold: int = 3,
    min_chinese_chars: int = 200,
) -> DedupDecision:
    """精确 SHA-256 优先；其次 SimHash（仅当两端均 ≥ min_chinese_chars）。"""
    if target.content_hash:
        for cand in candidates:
            if cand.content_hash and cand.content_hash == target.content_hash:
                return DedupDecision(is_duplicate=True, duplicate_of=cand.id, basis="sha256")

    if target.simhash is None or target.chinese_chars < min_chinese_chars:
        return DedupDecision(is_duplicate=False, basis="short_or_empty_content")

    for cand in candidates:
        if cand.simhash is None or cand.chinese_chars < min_chinese_chars:
            continue
        if cand.id == target.id:
            continue
        if hamming_distance(target.simhash, cand.simhash) <= hamming_threshold:
            return DedupDecision(is_duplicate=True, duplicate_of=cand.id, basis="simhash")
    return DedupDecision(is_duplicate=False, basis="none")


def build_candidate_from_content(article_id: str, *, url: str, canonical_url: str | None, title: str, content_clean: str | None, bits: int = 64) -> DedupCandidate:
    """从正文构造 DedupCandidate（含 simhash / chinese_chars / content_hash）。"""
    clean = content_clean or ""
    return DedupCandidate(
        id=article_id,
        urls=[u for u in ([canonical_url, url] if canonical_url else [url]) if u],
        title=title or "",
        content_hash=(hashlib.sha256(clean.encode("utf-8")).hexdigest() if clean else None),
        simhash=simhash(clean, bits=bits) if clean else None,
        chinese_chars=count_chinese_chars(clean),
    )
