"""JSON Schema 加载与校验（plan §8.6）。"""

from __future__ import annotations

import json
from functools import lru_cache

import jsonschema

from ..paths import PROMPTS_DIR

_SCHEMA_FILES = {
    "news-relevance/v1": "news_relevance.schema.json",
    "news-scoring/v1": "news_scoring.schema.json",
}


@lru_cache(maxsize=8)
def _load(schema_version: str) -> dict:
    filename = _SCHEMA_FILES[schema_version]
    path = PROMPTS_DIR / "schemas" / filename
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validator(schema_version: str) -> jsonschema.Draft7Validator:
    return jsonschema.Draft7Validator(_load(schema_version))


def validate_instance(schema_version: str, instance: object) -> list[str]:
    """返回错误信息列表；空列表表示通过。"""
    validator_ = validator(schema_version)
    errors = sorted(validator_.iter_errors(instance), key=lambda e: list(e.path))
    messages: list[str] = []
    for err in errors:
        path = "/".join(str(p) for p in err.path) or "<root>"
        messages.append(f"{path}: {err.message}")
    return messages
