"""Prompt 加载与版本管理（plan §8.8）。

Prompt 独立成文件、带版本，不硬编码进业务代码。每个 prompt 文件顶部以 ``key: value``
形式登记 version / schema / prompt_name，其余为系统提示正文。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..paths import PROMPTS_DIR

_META_LINE = re.compile(r"^([a-z_]+)\s*:\s*(.+?)\s*$")

# name → (文件名, schema_version)
_PROMPT_FILES: dict[str, tuple[str, str]] = {
    "news_relevance": ("news_relevance_v1.md", "news-relevance/v1"),
    "news_scoring": ("news_scoring_v1.md", "news-scoring/v1"),
    "risk_review": ("risk_review_v1.md", "news-scoring/v1"),
}


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: str
    schema_version: str
    text: str


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    lines = raw.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        match = _META_LINE.match(line)
        if match and match.group(1) in {"version", "schema", "prompt_name"}:
            meta[match.group(1)] = match.group(2).strip()
            index += 1
        else:
            break
    body = "\n".join(lines[index:]).strip()
    return meta, body


def prompt_path(name: str) -> Path:
    try:
        filename, _schema = _PROMPT_FILES[name]
    except KeyError as exc:
        raise KeyError(f"未知 prompt：{name}") from exc
    return PROMPTS_DIR / filename


def load_prompt(name: str) -> PromptSpec:
    path = prompt_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在：{path}")
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_front_matter(raw)
    _schema_file, schema_version = _PROMPT_FILES[name]
    return PromptSpec(
        name=meta.get("prompt_name", name),
        version=meta.get("version", "v1"),
        schema_version=schema_version,
        text=body,
    )
