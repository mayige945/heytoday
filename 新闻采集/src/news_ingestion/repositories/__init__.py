"""Repository 层：每张表一个仓储，服务层通过它们读写。"""

from __future__ import annotations

from .article import ArticleRepository
from .audit import AuditRepository
from .cluster_forbid import ClusterForbidRepository
from .event import EventRepository
from .fact_check import FactCheckRepository
from .fetch_log import FetchLogRepository
from .llm_run import LlmRunRepository
from .review import ReviewRepository
from .source import SourceRepository

__all__ = [
    "ArticleRepository",
    "AuditRepository",
    "ClusterForbidRepository",
    "EventRepository",
    "FactCheckRepository",
    "FetchLogRepository",
    "LlmRunRepository",
    "ReviewRepository",
    "SourceRepository",
]
