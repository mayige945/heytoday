"""文本归一化（plan §10.2 / §10.4）。

- ``normalize_text``：正文清洗后归一（NFKC 全半角、压缩空白）；
- ``normalize_title``：标题去媒体后缀、去重复标点、NFKC、统一大小写，供标题去重与聚类；
- ``count_chinese_chars`` / ``sha256_hex``：内容去重的前置工具。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from ..config import defaults


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def collapse_whitespace(text: str) -> str:
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n[ ]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_text(text: str | None) -> str:
    """正文归一：NFKC + 压缩空白。"""
    if not text:
        return ""
    return collapse_whitespace(nfkc(text))


def _strip_media_suffix(title: str, media_suffixes: tuple[str, ...]) -> str:
    cleaned = title
    # 去掉常见分隔符 + 媒体名后缀，如 "...- 少数派"、"...｜果壳"、"... _澎湃新闻"
    separators = "｜|_-—－·：: "
    for suffix in media_suffixes:
        suffix_norm = nfkc(suffix).strip()
        if not suffix_norm:
            continue
        if cleaned.endswith(suffix_norm):
            cleaned = cleaned[: -len(suffix_norm)].rstrip(separators).rstrip()
        # 形如 "标题 - 少数派" 已被上面命中；也处理 "少数派：标题" 前缀
        if cleaned.startswith(suffix_norm) and len(cleaned) > len(suffix_norm):
            cleaned = cleaned[len(suffix_norm):].lstrip(separators).lstrip()
    return cleaned


def _collapse_repeated_punctuation(title: str, punctuation: str) -> str:
    if not punctuation:
        return title
    pattern = f"([{re.escape(punctuation)}])\\1+"
    return re.sub(pattern, r"\1", title)


def normalize_title(
    title: str | None,
    *,
    media_suffixes: tuple[str, ...] = defaults.MEDIA_SUFFIXES,
    punctuation: str = defaults.TITLE_PUNCTUATION,
) -> str:
    """标题归一：NFKC → 去媒体后缀 → 去重复标点 → 压缩空白 → 小写。"""
    if not title:
        return ""
    cleaned = nfkc(title).strip()
    cleaned = _strip_media_suffix(cleaned, media_suffixes)
    cleaned = _collapse_repeated_punctuation(cleaned, punctuation)
    cleaned = collapse_whitespace(cleaned)
    return cleaned.lower()


def title_fingerprint(
    title: str | None,
    *,
    media_suffixes: tuple[str, ...] = defaults.MEDIA_SUFFIXES,
    punctuation: str = defaults.TITLE_PUNCTUATION,
) -> str:
    normalized = normalize_title(title, media_suffixes=media_suffixes, punctuation=punctuation)
    return sha256_hex(normalized)


_CJK_RANGES = (
    (0x4E00, 0x9FFF),     # CJK Unified Ideographs
    (0x3400, 0x4DBF),     # CJK Extension A
    (0x20000, 0x2A6DF),   # CJK Extension B
    (0xF900, 0xFAFF),     # CJK Compatibility Ideographs
)


def is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    for low, high in _CJK_RANGES:
        if low <= code <= high:
            return True
    return False


def count_chinese_chars(text: str | None) -> int:
    if not text:
        return 0
    return sum(1 for ch in text if is_cjk_char(ch))


def sha256_hex(text: str | None) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
