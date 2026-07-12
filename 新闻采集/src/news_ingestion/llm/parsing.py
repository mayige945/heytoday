"""LLM 输出 JSON 提取与一次修复重试（plan §8.7）。"""

from __future__ import annotations

import json
import re

from .schemas import validate_instance

_FENCE_OPEN = re.compile(r"^\s*```[a-zA-Z0-9]*\s*\n", re.MULTILINE)
_FENCE_CLOSE = re.compile(r"\n?```\s*$", re.MULTILINE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")

# 中文模型常把枚举键写成中文名；这里把常见中文/同义归一到 schema 枚举值。
_TOPIC_ALIASES = {
    "discovery": "discovery", "奇异新发现": "discovery", "新发现": "discovery",
    "科技新发现": "discovery", "太空": "discovery", "考古": "discovery",
    "technology_in_life": "technology_in_life", "科技进入生活": "technology_in_life",
    "科技": "technology_in_life", "技术": "technology_in_life",
    "youth": "youth", "青少年直接相关": "youth", "青少年": "youth", "少年": "youth",
    "social_conflict": "social_conflict", "有冲突的社会小事件": "social_conflict",
    "社会冲突": "social_conflict", "冲突": "social_conflict",
    "ordinary_people": "ordinary_people", "普通人的不普通经历": "ordinary_people",
    "普通人": "ordinary_people",
    "internet_culture": "internet_culture", "网络文化与流行现象": "internet_culture",
    "网络文化": "internet_culture", "流行现象": "internet_culture",
}
_SAFETY_ALIASES = {
    "redline": "redline", "红线": "redline",
    "sensitive": "sensitive", "敏感": "sensitive", "敏感但重要": "sensitive",
    "default": "default", "默认": "default", "默认可聊": "default",
    "uncertain": "uncertain", "不确定": "uncertain",
}
_RELEVANCE_ALIASES = {
    "relevant": "relevant", "相关": "relevant",
    "irrelevant": "irrelevant", "无关": "irrelevant",
    "uncertain": "uncertain", "不确定": "uncertain",
}


def normalize_llm_output(parsed: dict) -> dict:
    """把中文枚举名归一到 schema 枚举键；已是合法英文值则不变。"""
    if not isinstance(parsed, dict):
        return parsed
    topics = parsed.get("topic_categories")
    if isinstance(topics, list):
        parsed["topic_categories"] = [_TOPIC_ALIASES.get(str(t).strip(), str(t).strip()) for t in topics]
    if "primary_category" in parsed:
        parsed["primary_category"] = _TOPIC_ALIASES.get(str(parsed["primary_category"]).strip(), str(parsed["primary_category"]).strip())
    if "relevance" in parsed:
        parsed["relevance"] = _RELEVANCE_ALIASES.get(str(parsed["relevance"]).strip(), str(parsed["relevance"]).strip())
    if "safety_tier" in parsed:
        parsed["safety_tier"] = _SAFETY_ALIASES.get(str(parsed["safety_tier"]).strip(), str(parsed["safety_tier"]).strip())
    return parsed


def extract_json(text: str | None) -> dict | None:
    """从可能含代码围栏或前后赘述的 LLM 文本中提取首个 JSON 对象。"""
    if not text:
        return None
    cleaned = _FENCE_OPEN.sub("", text.strip())
    cleaned = _FENCE_CLOSE.sub("", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < 0 or end < start:
        return None
    candidate = cleaned[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = _TRAILING_COMMA.sub(r"\1", candidate)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None


def call_and_parse(
    client,
    *,
    system: str,
    user: str,
    schema_version: str,
    max_tokens: int,
) -> tuple[dict | None, str, dict, int]:
    """调用一次；解析/校验失败则做一次修复重试。返回 (parsed|None, raw, usage, attempts)。"""
    response = client.complete(system=system, user=user, max_tokens=max_tokens)
    raw = response.text
    usage = response.usage
    parsed = normalize_llm_output(extract_json(raw))
    if parsed is not None and not validate_instance(schema_version, parsed):
        return parsed, raw, usage, 1

    # 修复重试。若首次正文为空（思考用尽 token），加码 token 并要求精简思考。
    first_raw_empty = not raw.strip()
    repair_tokens = max_tokens * 3 if first_raw_empty else max_tokens
    empty_hint = "上一次回复没有产出正文（思考用尽 token）。请大幅精简思考，直接输出 JSON。" if first_raw_empty else ""
    repair_system = (
        system
        + "\n\n—— 修复提示：你上一次的输出无法解析为合法 JSON，或不符合 JSON Schema。"
        "请只输出完全符合 schema 的合法 JSON 对象，枚举字段只用 schema 规定的英文键，"
        "不要任何额外文字、解释或代码围栏。"
        + empty_hint
    )
    response = client.complete(system=repair_system, user=user, max_tokens=repair_tokens)
    raw = response.text
    usage = response.usage
    parsed = normalize_llm_output(extract_json(raw))
    if parsed is not None and not validate_instance(schema_version, parsed):
        return parsed, raw, usage, 2
    return None, raw, usage, 2
