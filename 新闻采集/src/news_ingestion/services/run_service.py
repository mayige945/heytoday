"""``run`` 流水线：唯一权威执行顺序（plan §7）。

元数据采集 → URL/标题去重 → 一级识别 → 正文抓取与内容去重 → 事件聚类 → 二级完整评分
→ 安全兜底 → 停在人工复核队列。**不**自动批准 / 导出 / 调用下游。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from ..config import FiltersConfig, RuntimeConfig, SourceConfig
from ..llm import credentials_present
from ..logging_setup import get_logger
from ..models import NewsArticle, NewsEvent
from ..repositories import FetchLogRepository
from .classify_service import run_classify_light
from .cluster_service import run_cluster
from .content_service import fetch_contents
from .dedup_service import run_dedup
from .fetch_service import fetch_all
from .safety import apply_rule_fallback
from .score_service import run_score_full

_LOG = get_logger(__name__)


@dataclass
class RunResult:
    fetch_outcomes: list = field(default_factory=list)
    dedup: dict = field(default_factory=dict)
    classify: dict = field(default_factory=dict)
    content: dict = field(default_factory=dict)
    cluster: dict = field(default_factory=dict)
    score: dict = field(default_factory=dict)
    llm_configured: bool = True
    exit_code: int = 0
    summary: dict[str, Any] = field(default_factory=dict)


def _recover_stale(session_factory: sessionmaker, runtime: RuntimeConfig) -> None:
    with session_factory() as session:
        recovered = FetchLogRepository(session).recover_stale(runtime.stale_run_recovery_minutes)
        if recovered:
            _LOG.warning("恢复 %d 条 stale running 日志为 failed", recovered)
        session.commit()


def _apply_safety_fallback(session_factory: sessionmaker, filters: FiltersConfig) -> int:
    changed = 0
    with session_factory() as session:
        events = list(session.scalars(select(NewsEvent).where(NewsEvent.llm_status == "success")))
    for event in events:
        with session_factory() as session:
            current = session.get(NewsEvent, event.id)
            if current and apply_rule_fallback(current, filters):
                changed += 1
                session.commit()
    return changed


def run_pipeline(
    session_factory: sessionmaker,
    *,
    enabled_sources: list[SourceConfig],
    runtime: RuntimeConfig,
    filters: FiltersConfig,
    user_agent: str,
    client=None,
    since_hours: float = 24.0,
    cluster_hours: float = 72.0,
    fetch_interval_seconds: float = 0.0,
    fulltext_limit: int | None = None,
    collector_for=None,
    content_fetcher=None,
) -> RunResult:
    result = RunResult()
    result.llm_configured = client is not None or credentials_present()

    _recover_stale(session_factory, runtime)

    # 1. 采集
    result.fetch_outcomes = fetch_all(
        session_factory,
        enabled_sources,
        user_agent=user_agent,
        max_retries=runtime.llm_max_retries,
        collector_for=collector_for,
        interval_seconds=fetch_interval_seconds,
    )

    # 2. URL/标题去重
    result.dedup = run_dedup(session_factory, since_hours=since_hours, filters=filters)

    # 3. 一级识别（无凭据降级 uncertain）
    result.classify = run_classify_light(
        session_factory, since_hours=since_hours, runtime=runtime, client=client, strict=False
    )

    # 4. 正文抓取
    result.content = fetch_contents(
        session_factory, since_hours=since_hours, user_agent=user_agent, limit=fulltext_limit, fetcher=content_fetcher
    )

    # 5. 内容去重（正文就绪后重跑，含 SimHash）
    result.dedup = run_dedup(session_factory, since_hours=since_hours, filters=filters)

    # 6. 事件聚类
    result.cluster = run_cluster(session_factory, since_hours=cluster_hours, filters=filters)

    # 7. 二级评分（无凭据跳过，事件保持 pending）
    result.score = run_score_full(
        session_factory, runtime=runtime, client=client, strict=False
    )

    # 8. 规则安全兜底（只可更严）
    _apply_safety_fallback(session_factory, filters)

    # 汇总：实际被标重复的文章数（跨两次去重）
    with session_factory() as session:
        duplicate_count = int(
            session.scalar(select(func.count(NewsArticle.id)).where(NewsArticle.duplicate_of.isnot(None))) or 0
        )

    # 退出码：无 LLM 凭据 → 7（非 LLM 数据已保留）；否则按采集成败 0/3/4
    if not result.llm_configured:
        result.exit_code = 7
    else:
        enabled = [o for o in result.fetch_outcomes]
        if enabled and all(o.status == "failed" for o in enabled):
            result.exit_code = 3
        elif any(o.status == "failed" for o in enabled):
            result.exit_code = 4
        else:
            result.exit_code = 0

    result.summary = {
        "sources_success": sum(1 for o in result.fetch_outcomes if o.status == "success"),
        "sources_partial": sum(1 for o in result.fetch_outcomes if o.status == "partial_success"),
        "sources_failed": sum(1 for o in result.fetch_outcomes if o.status == "failed"),
        "articles_created": sum(o.items_created for o in result.fetch_outcomes),
        "duplicates": duplicate_count,
        "events_new": result.cluster.get("events_new", 0),
        "events_scored": result.score.get("scored", 0),
        "llm_configured": result.llm_configured,
    }
    _LOG.info("run 完成：%s", result.summary)
    return result
