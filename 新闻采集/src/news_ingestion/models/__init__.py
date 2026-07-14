"""ORM 模型聚合：导入全部表类以注册到 ``Base.metadata``。"""

from __future__ import annotations

from .base import Base, UTCDateTime
from .enums import (
    AccessReviewStatus,
    AcquisitionMethod,
    AgeBand,
    Eligibility,
    EventLlmStatus,
    EventStatus,
    FactCheckStatus,
    FetchLogStatus,
    FetchStatus,
    LlmMode,
    LlmRunStatus,
    ParentMode,
    PrimaryCategory,
    RelevanceStatus,
    ReviewStatus,
    SafetyTier,
    SourceCategory,
    SourceRole,
)
from .event_review import EventReview
from .cluster_forbid_pair import ClusterForbidPair
from .fact_check_record import FactCheckRecord
from .fetch_log import FetchLog
from .llm_run import LlmRun
from .news_article import NewsArticle
from .news_event import NewsEvent
from .news_source import NewsSource

__all__ = [
    "Base",
    "UTCDateTime",
    "NewsSource",
    "NewsArticle",
    "NewsEvent",
    "LlmRun",
    "FetchLog",
    "FactCheckRecord",
    "EventReview",
    "ClusterForbidPair",
    # enums
    "AccessReviewStatus",
    "AcquisitionMethod",
    "AgeBand",
    "Eligibility",
    "EventLlmStatus",
    "EventStatus",
    "FactCheckStatus",
    "FetchLogStatus",
    "FetchStatus",
    "LlmMode",
    "LlmRunStatus",
    "ParentMode",
    "PrimaryCategory",
    "RelevanceStatus",
    "ReviewStatus",
    "SafetyTier",
    "SourceCategory",
    "SourceRole",
]
