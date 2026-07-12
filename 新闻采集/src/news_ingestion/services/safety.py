"""安全兜底（plan §8.5 / §11）。

传统规则只负责**召回**风险信号，不能单独把敏感话题判成红线，也不能完成最终安全
分类。命中红线召回词时只能把事件判得更严（标 ``safety_uncertain``，交人工），永不放宽。
"""

from __future__ import annotations

from ..config import FiltersConfig
from ..models import NewsEvent


def _event_text(event: NewsEvent) -> str:
    parts = [event.event_title or "", event.event_summary or ""]
    parts.extend(event.key_conflicts or [])
    parts.extend(event.key_people or [])
    parts.extend(event.fact_check_targets or [])
    return " ".join(parts).lower()


def apply_rule_fallback(event: NewsEvent, filters: FiltersConfig) -> bool:
    """命中红线召回词 → 标 uncertain + tag（不自动判红）。返回是否改动。"""
    if not filters.redline_recall_keywords:
        return False
    text = _event_text(event)
    if not text:
        return False
    hits = [kw for kw in filters.redline_recall_keywords if kw and kw.lower() in text]
    if not hits:
        return False
    changed = False
    tags = list(event.safety_tags or [])
    for hit in hits:
        tag = f"rule:redline_recall:{hit}"
        if tag not in tags:
            tags.append(tag)
            changed = True
    if event.safety_tier == "default":
        event.safety_tier = "uncertain"
        event.safety_uncertain = True
        changed = True
    elif not event.safety_uncertain:
        event.safety_uncertain = True
        changed = True
    event.safety_tags = tags
    if event.safety_reason and "rule:redline_recall" not in event.safety_reason:
        event.safety_reason = (event.safety_reason + " | 规则红线召回待人工确认").strip(" |")
    elif not event.safety_reason:
        event.safety_reason = "规则红线召回待人工确认"
    return changed
