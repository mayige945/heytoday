"""业务枚举词汇表。

DB 列一律以字符串存储；这里用 ``StrEnum`` 提供类型安全的常量与合法取值集合，
供配置校验、Repository 写入与导出校验复用。本文件只依赖标准库，避免 config
层为校验枚举而引入 SQLAlchemy。
"""

from __future__ import annotations

import enum
from typing import Iterable


class _Vocab(str, enum.Enum):
    """基类：值即字符串，便于直接落库与 JSON 序列化。"""

    def __str__(self) -> str:  # pragma: no cover - 仅日志友好
        return str(self.value)


class AcquisitionMethod(_Vocab):
    RSS = "rss"
    WEBPAGE = "webpage"
    RSSHUB = "rsshub"


class AccessReviewStatus(_Vocab):
    VERIFIED = "verified"
    PROHIBITED = "prohibited"
    UNCERTAIN = "uncertain"


class SourceCategory(_Vocab):
    CHILD_NEWS = "child_news"
    SCIENCE = "science"
    TECHNOLOGY = "technology"
    SOCIETY = "society"
    INTERNATIONAL = "international"
    ACADEMIC_EXPLAINER = "academic_explainer"
    TREND_RADAR = "trend_radar"


class SourceRole(_Vocab):
    TOPIC_SOURCE = "topic_source"
    FACT_SOURCE = "fact_source"
    EXPLAINER_SOURCE = "explainer_source"
    VIEWPOINT_SOURCE = "viewpoint_source"
    LEAD_SOURCE = "lead_source"


class FetchStatus(_Vocab):
    DISCOVERED = "discovered"
    FETCHED = "fetched"
    PARSED = "parsed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RelevanceStatus(_Vocab):
    PENDING = "pending"
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    UNCERTAIN = "uncertain"


class LlmMode(_Vocab):
    LIGHT = "light"
    FULL = "full"


class LlmRunStatus(_Vocab):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class EventLlmStatus(_Vocab):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class EventStatus(_Vocab):
    NEW = "new"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"
    ARCHIVED = "archived"


class SafetyTier(_Vocab):
    REDLINE = "redline"
    SENSITIVE = "sensitive"
    DEFAULT = "default"
    UNCERTAIN = "uncertain"


class PrimaryCategory(_Vocab):
    DISCOVERY = "discovery"
    TECHNOLOGY_IN_LIFE = "technology_in_life"
    YOUTH = "youth"
    SOCIAL_CONFLICT = "social_conflict"
    ORDINARY_PEOPLE = "ordinary_people"
    INTERNET_CULTURE = "internet_culture"


class FetchLogStatus(_Vocab):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class ReviewStatus(_Vocab):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Eligibility(_Vocab):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class AgeBand(_Vocab):
    UPPER_PRIMARY = "upper_primary"
    JUNIOR_HIGH = "junior_high"


class ParentMode(_Vocab):
    CONSERVATIVE = "conservative"
    STANDARD = "standard"
    OPEN = "open"


class FactCheckStatus(_Vocab):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


def values(vocab: type[_Vocab]) -> frozenset[str]:
    return frozenset(member.value for member in vocab)


def is_valid(value: str, vocab: type[_Vocab]) -> bool:
    return value in values(vocab)


def ensure_in(value: str, vocab: type[_Vocab], field_name: str) -> str:
    if not is_valid(value, vocab):
        allowed = ", ".join(sorted(values(vocab)))
        raise ValueError(f"{field_name} 取值非法：{value!r}（允许：{allowed}）")
    return value


def coalesce_values(vocabs: Iterable[type[_Vocab]]) -> frozenset[str]:
    result: set[str] = set()
    for vocab in vocabs:
        result |= values(vocab)
    return frozenset(result)
