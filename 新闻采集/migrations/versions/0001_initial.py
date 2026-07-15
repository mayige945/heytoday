"""initial: 创建全部七张表（与 Base.metadata 同源）。

Revision ID: 0001
Revises:
Create Date: 2026-07-10

首版迁移直接以 ``Base.metadata.create_all`` 建表，保证表结构与 ORM 模型完全
一致；后续结构变更需新增 revision 并使用 batch 模式（SQLite）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from news_ingestion.models import Base

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


# 0001 历史上使用当前 ORM metadata，0002/0003 因而按幂等方式兼容。
# 在 0005 引入新账本前冻结 pre-audit（0004）表面，阻止后续模型继续倒灌到旧 revision。
_PRE_AUDIT_COLUMNS = {
    "news_source": (
        "id", "unit_code", "code", "name", "homepage_url", "language",
        "country_or_region", "source_category", "source_role", "acquisition_method",
        "feed_url", "list_page_urls", "rsshub_route", "enabled", "priority",
        "access_review_status", "access_reviewed_at", "access_evidence_url",
        "disabled_reason", "request_interval_seconds", "max_concurrency_per_host",
        "timeout_seconds", "max_redirects", "max_response_bytes", "allowed_content_types",
        "topic_tags", "allowed_sections", "excluded_sections", "excluded_keywords",
        "requires_fulltext_fetch", "requires_fact_check", "commercial_use_note",
        "last_fetch_at", "last_success_at", "consecutive_failures", "last_error",
        "created_at", "updated_at",
    ),
    "news_article": (
        "id", "source_id", "external_id", "guid", "url", "canonical_url",
        "identity_url", "title", "subtitle", "summary", "content_raw", "content_clean",
        "author", "section", "published_at", "discovered_at", "fetched_at", "language",
        "image_urls", "tags", "content_hash", "title_hash", "fetch_status",
        "relevance_status", "relevance_reason", "relevance_prompt_version",
        "relevance_processed_at", "duplicate_of", "duplicate_basis", "event_id",
        "created_at", "updated_at",
    ),
    "news_event": (
        "id", "event_title", "event_summary", "topic_categories", "primary_category",
        "article_ids", "source_count", "language_count", "first_published_at",
        "latest_published_at", "heat_score", "age_assessments", "story_score",
        "discussion_score", "knowledge_gain_score", "life_relevance_score",
        "value_pluralism_score", "audio_fit_score", "safety_tier", "safety_tags",
        "safety_reason", "safety_uncertain", "safety_assessments", "needs_fact_check",
        "fact_check_targets", "key_people", "key_conflicts", "child_hook", "llm_reason",
        "llm_status", "llm_model", "prompt_version", "llm_processed_at", "status",
        "created_at", "updated_at",
    ),
    "llm_run": (
        "id", "article_id", "event_id", "mode", "model_provider", "model_name",
        "prompt_name", "prompt_version", "schema_version", "input_hash", "raw_response",
        "parsed_result", "status", "requested_at", "completed_at", "token_usage",
        "estimated_cost", "error_message",
    ),
    "fetch_log": (
        "id", "source_id", "started_at", "finished_at", "status", "items_found",
        "items_created", "items_updated", "items_skipped", "errors_count",
        "error_message", "metadata",
    ),
    "fact_check_record": (
        "id", "event_id", "status", "conclusion", "evidence_sources", "checker",
        "created_at", "updated_at",
    ),
    "event_review": (
        "id", "event_id", "review_status", "reviewer", "eligibility",
        "category_override", "score_overrides", "safety_override",
        "age_assessments_override", "content_overrides", "rejection_reason", "note",
        "reviewed_at", "created_at", "updated_at",
    ),
}


def _revision_metadata() -> sa.MetaData:
    metadata = sa.MetaData()
    for table_name in _PRE_AUDIT_COLUMNS:
        Base.metadata.tables[table_name].to_metadata(metadata)
    for table_name, allowed_names in _PRE_AUDIT_COLUMNS.items():
        table = metadata.tables[table_name]
        allowed = set(allowed_names)
        for constraint in list(table.constraints):
            constrained = {column.name for column in constraint.columns}
            if constrained - allowed or "audit_" in (constraint.name or ""):
                table.constraints.remove(constraint)
        for index in list(table.indexes):
            indexed = {getattr(expression, "name", None) for expression in index.expressions}
            if indexed - allowed:
                table.indexes.remove(index)
        for column in list(table.columns):
            if column.name in allowed:
                continue
            for foreign_key in list(column.foreign_keys):
                column.foreign_keys.remove(foreign_key)
                table.foreign_keys.remove(foreign_key)
            table._columns.remove(column)
    return metadata


def upgrade() -> None:
    bind = op.get_bind()
    _revision_metadata().create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    _revision_metadata().drop_all(bind)
