"""采集阶段服务：每来源独立事务，单来源失败隔离（plan §15）。

- 单来源事务：文章变更 + fetch_log 同事务提交；失败回滚该来源，单独写脱敏 failed 日志；
- 非零退出不删除此前已成功提交的数据；
- ``collector`` 可注入（离线 e2e 用 fake collector）。
"""

from __future__ import annotations

from typing import Callable, Union

from sqlalchemy.orm import sessionmaker

from ..collectors.base import Collector, get_collector
from ..config import SourceConfig
from ..logging_setup import get_logger
from ..repositories import ArticleRepository, FetchLogRepository, SourceRepository
from ..types import FetchOutcome

_LOG = get_logger(__name__)

CollectorLike = Union[Collector, Callable[[SourceConfig], list]]


def _run_collector(collector: CollectorLike, source: SourceConfig, *, user_agent: str, max_retries: int):
    if hasattr(collector, "collect"):
        return collector.collect(source, user_agent=user_agent, max_retries=max_retries)
    return collector(source)


def fetch_source(
    session_factory: sessionmaker,
    source: SourceConfig,
    *,
    user_agent: str,
    max_retries: int = 2,
    collector: CollectorLike | None = None,
) -> FetchOutcome:
    collector = collector or get_collector(source.acquisition_method)
    outcome = FetchOutcome(source_id=source.code)
    try:
        with session_factory() as session:
            fl_repo = FetchLogRepository(session)
            src_repo = SourceRepository(session)
            art_repo = ArticleRepository(session)
            log = fl_repo.start(source.code)
            src_repo.record_fetch_start(source.code)
            try:
                items = _run_collector(collector, source, user_agent=user_agent, max_retries=max_retries)
            except Exception as exc:
                outcome.status = "failed"
                outcome.error_message = str(exc)[:500]
                outcome.errors.append(str(exc)[:300])
                fl_repo.finish(log.id, outcome)
                src_repo.record_fetch_outcome(source.code, success=False, error=str(exc)[:500])
                session.commit()
                _LOG.warning("来源 %s 采集失败：%s", source.code, outcome.error_message)
                return outcome

            for item in items:
                outcome.items_found += 1
                try:
                    # 用 savepoint 隔离单条失败，避免毒化会话导致剩余条目全部 PendingRollback
                    created = False
                    with session.begin_nested():
                        _article, created = art_repo.upsert_discovered(item)
                except Exception as exc:  # 单条失败不中断整源
                    outcome.errors.append(str(item.url)[:120] + " -> " + str(exc)[:160])
                    continue
                outcome.items_created += int(created)
                outcome.items_updated += int(not created)
            outcome.status = "partial_success" if outcome.errors else "success"
            fl_repo.finish(log.id, outcome)
            src_repo.record_fetch_outcome(source.code, success=True, error=None)
            session.commit()
        return outcome
    except Exception as exc:
        # 事务级失败：回滚该来源文章，单独写 failed 日志
        outcome.status = "failed"
        outcome.error_message = str(exc)[:500]
        outcome.errors.append(str(exc)[:300])
        _LOG.exception("来源 %s 事务失败", source.code)
        try:
            with session_factory() as session2:
                fl_repo = FetchLogRepository(session2)
                src_repo = SourceRepository(session2)
                log = fl_repo.start(source.code)
                fl_repo.finish(log.id, outcome)
                src_repo.record_fetch_outcome(source.code, success=False, error=str(exc)[:500])
                session2.commit()
        except Exception:
            _LOG.exception("写入来源 %s 失败日志时再次失败", source.code)
        return outcome


def fetch_all(
    session_factory: sessionmaker,
    sources: list[SourceConfig],
    *,
    user_agent: str,
    max_retries: int = 2,
    collector_for: Callable[[str], CollectorLike] | None = None,
    interval_seconds: float = 0.0,
) -> list[FetchOutcome]:
    import time

    # 先把所给来源 upsert 进 news_source（幂等），保证文章 / fetch_log 外键存在
    with session_factory() as session:
        SourceRepository(session).seed_from_configs(list(sources))
        session.commit()

    outcomes: list[FetchOutcome] = []
    for source in sources:
        collector = collector_for(source.code) if collector_for else None
        outcomes.append(
            fetch_source(session_factory, source, user_agent=user_agent, max_retries=max_retries, collector=collector)
        )
        if interval_seconds > 0:
            time.sleep(interval_seconds)
    return outcomes
