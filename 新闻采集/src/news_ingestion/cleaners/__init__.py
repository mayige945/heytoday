"""清洗层：URL / HTML / 文本。"""

from __future__ import annotations

from .html import extract_title, html_to_text
from .text import (
    collapse_whitespace,
    count_chinese_chars,
    nfkc,
    normalize_text,
    normalize_title,
    sha256_hex,
    title_fingerprint,
)
from .url import clean_url, is_same_url, normalize_url

__all__ = [
    "clean_url",
    "collapse_whitespace",
    "count_chinese_chars",
    "extract_title",
    "html_to_text",
    "is_same_url",
    "nfkc",
    "normalize_text",
    "normalize_title",
    "normalize_url",
    "sha256_hex",
    "title_fingerprint",
]
