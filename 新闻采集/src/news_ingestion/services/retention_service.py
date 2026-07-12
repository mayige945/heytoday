"""留存清理（plan §9.2 / §15）。

幂等，按 Asia/Shanghai 计算到期日，默认实清，提供 ``--dry-run`` 预览：
- ``content_raw`` 自 ``fetched_at`` 起 7 天清空；
- ``content_clean`` 自 ``fetched_at`` 起 30 天清空；
- 超过 30 天的 LLM ``raw_response`` / 脱敏错误清空；
- 超过 30 天的文件运行日志删除；
- **不删**文章 / 事件 / 来源 / hash / 事件关联 / 结构化 LLM 结果 / 事实核验 / 复核记录。
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..logging_setup import get_logger
from ..models import LlmRun, NewsArticle
from ..paths import LOGS_DIR
from ..timeutil import utcnow

_LOG = get_logger(__name__)
_RAW_DAYS = 7
_CLEAN_DAYS = 30
_LOG_DAYS = 30


def prune(session_factory: sessionmaker, *, dry_run: bool = False, logs_dir: Path | None = None) -> dict:
    now = utcnow()
    raw_cutoff = now - timedelta(days=_RAW_DAYS)
    clean_cutoff = now - timedelta(days=_CLEAN_DAYS)
    log_cutoff_ts = (now - timedelta(days=_LOG_DAYS)).timestamp()
    stats = {
        "content_raw_cleared": 0,
        "content_clean_cleared": 0,
        "llm_raw_cleared": 0,
        "log_files_deleted": 0,
        "dry_run": dry_run,
    }

    with session_factory() as session:
        for article in session.scalars(select(NewsArticle)):
            fetched = article.fetched_at
            if fetched and fetched < raw_cutoff and article.content_raw:
                stats["content_raw_cleared"] += 1
                if not dry_run:
                    article.content_raw = None
            if fetched and fetched < clean_cutoff and article.content_clean:
                stats["content_clean_cleared"] += 1
                if not dry_run:
                    article.content_clean = None

        for run in session.scalars(select(LlmRun)):
            if run.requested_at and run.requested_at < clean_cutoff and (run.raw_response or run.error_message):
                stats["llm_raw_cleared"] += 1
                if not dry_run:
                    run.raw_response = None
                    run.error_message = None
        if not dry_run:
            session.commit()

    directory = logs_dir or LOGS_DIR
    if directory.exists():
        for entry in directory.iterdir():
            if entry.is_file() and entry.stat().st_mtime < log_cutoff_ts:
                stats["log_files_deleted"] += 1
                if not dry_run:
                    try:
                        entry.unlink()
                    except OSError:
                        pass

    _LOG.info("留存清理完成（dry_run=%s）：%s", dry_run, stats)
    return stats
