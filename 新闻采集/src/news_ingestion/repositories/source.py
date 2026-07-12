"""来源仓储。

来源表的种子幂等：以 ``code`` 为稳定主键；re-seed 时只更新配置派生字段，保留
运行期健康字段（last_fetch_at / last_success_at / consecutive_failures / last_error）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import SourceConfig
from ..models import NewsSource
from ..timeutil import utcnow

_CONFIG_FIELDS: tuple[str, ...] = (
    "unit_code", "name", "homepage_url", "language", "country_or_region",
    "source_category", "source_role", "acquisition_method", "feed_url",
    "list_page_urls", "rsshub_route", "enabled", "priority",
    "access_review_status", "access_reviewed_at", "access_evidence_url",
    "disabled_reason", "request_interval_seconds", "max_concurrency_per_host",
    "timeout_seconds", "max_redirects", "max_response_bytes",
    "allowed_content_types", "topic_tags", "allowed_sections",
    "excluded_sections", "excluded_keywords", "requires_fulltext_fetch",
    "requires_fact_check", "commercial_use_note",
)


def _apply_config(source: NewsSource, cfg: SourceConfig) -> NewsSource:
    source.id = cfg.code
    source.code = cfg.code
    for field_name in _CONFIG_FIELDS:
        setattr(source, field_name, getattr(cfg, field_name))
    return source


class SourceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def seed_from_configs(self, configs: list[SourceConfig]) -> tuple[int, int]:
        """幂等种子：返回 (created, updated)。保留运行期健康字段。"""
        created = 0
        updated = 0
        for cfg in configs:
            existing = self.session.get(NewsSource, cfg.code)
            if existing is None:
                self.session.add(_apply_config(NewsSource(), cfg))
                created += 1
            else:
                _apply_config(existing, cfg)
                updated += 1
        self.session.flush()
        return created, updated

    def get(self, code: str) -> NewsSource | None:
        return self.session.get(NewsSource, code)

    def list_all(self) -> list[NewsSource]:
        return list(self.session.scalars(select(NewsSource).order_by(NewsSource.priority.desc(), NewsSource.code)))

    def list_enabled(self, category: str | None = None) -> list[NewsSource]:
        stmt = select(NewsSource).where(NewsSource.enabled.is_(True))
        if category:
            stmt = stmt.where(NewsSource.source_category == category)
        stmt = stmt.order_by(NewsSource.priority.desc(), NewsSource.code)
        return list(self.session.scalars(stmt))

    def count_enabled(self) -> int:
        return int(self.session.scalar(select(NewsSource).where(NewsSource.enabled.is_(True)).with_only_columns(NewsSource.id).order_by(None)) or 0)  # noqa: E712

    def record_fetch_start(self, source_id: str) -> None:
        source = self.session.get(NewsSource, source_id)
        if source is not None:
            source.last_fetch_at = utcnow()

    def record_fetch_outcome(self, source_id: str, *, success: bool, error: str | None) -> None:
        source = self.session.get(NewsSource, source_id)
        if source is None:
            return
        source.last_error = None if success else (error[:1024] if error else "未知错误")
        if success:
            source.last_success_at = utcnow()
            source.consecutive_failures = 0
        else:
            source.consecutive_failures = (source.consecutive_failures or 0) + 1
