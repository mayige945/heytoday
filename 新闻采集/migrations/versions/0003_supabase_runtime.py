"""Supabase Postgres 作为唯一运行库，并强化文章身份幂等。

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from news_ingestion.cleaners.url import clean_url
from news_ingestion.models import ClusterForbidPair

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_TABLE_COMMENTS = {
    "news_source": "新闻来源配置与运行健康状态",
    "news_article": "采集到的原始新闻文章；重复项通过 duplicate_of 指向保留项",
    "news_event": "由一篇或多篇非重复文章聚合形成的新闻事件",
    "llm_run": "新闻相关性与完整评分的 LLM 调用留痕",
    "fetch_log": "每个来源每次采集的结构化任务结果",
    "fact_check_record": "新闻事件的人工事实核验记录",
    "event_review": "新闻事件的人工策展记录",
    "cluster_forbid_pair": "人工拆分后禁止重新聚类的文章对",
}


def _index_names(bind, table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(bind).get_indexes(table)}


def _backfill_identity_urls(bind) -> None:
    rows = bind.execute(
        sa.text(
            "select id, source_id, guid, canonical_url, url, duplicate_of "
            "from news_article order by discovered_at, id"
        )
    ).mappings()
    seen_urls: dict[str, str] = {}
    seen_guids: dict[tuple[str, str], str] = {}
    for row in rows:
        identity = clean_url(row["canonical_url"] or row["url"])
        duplicate_of = row["duplicate_of"]
        basis = None
        if identity in seen_urls:
            duplicate_of = duplicate_of or seen_urls[identity]
            basis = "url"
            identity_value = None
        else:
            seen_urls[identity] = row["id"]
            identity_value = identity

        guid = row["guid"]
        if guid:
            guid_key = (row["source_id"], guid)
            if guid_key in seen_guids:
                duplicate_of = duplicate_of or seen_guids[guid_key]
                basis = basis or "guid"
                guid = None
                identity_value = None
            else:
                seen_guids[guid_key] = row["id"]

        bind.execute(
            sa.text(
                "update news_article set identity_url=:identity_url, guid=:guid, "
                "duplicate_of=:duplicate_of, duplicate_basis=coalesce(duplicate_basis, :basis) "
                "where id=:id"
            ),
            {
                "id": row["id"],
                "identity_url": identity_value,
                "guid": guid,
                "duplicate_of": duplicate_of,
                "basis": basis,
            },
        )


def upgrade() -> None:
    bind = op.get_bind()
    ClusterForbidPair.__table__.create(bind, checkfirst=True)
    columns = {column["name"] for column in sa.inspect(bind).get_columns("news_article")}
    if "identity_url" not in columns:
        op.add_column("news_article", sa.Column("identity_url", sa.String(2048), nullable=True))
    _backfill_identity_urls(bind)

    indexes = _index_names(bind, "news_article")
    if "uq_news_article_identity_url" not in indexes:
        op.create_index(
            "uq_news_article_identity_url",
            "news_article",
            ["identity_url"],
            unique=True,
            postgresql_where=sa.text("identity_url is not null"),
            sqlite_where=sa.text("identity_url is not null"),
        )
    if "uq_news_article_source_guid" not in indexes:
        op.create_index(
            "uq_news_article_source_guid",
            "news_article",
            ["source_id", "guid"],
            unique=True,
            postgresql_where=sa.text("guid is not null"),
            sqlite_where=sa.text("guid is not null"),
        )

    if bind.dialect.name != "postgresql":
        return

    for table, comment in _TABLE_COMMENTS.items():
        op.execute(sa.text(f'alter table public."{table}" enable row level security'))
        op.execute(sa.text(f'revoke all on table public."{table}" from public, anon, authenticated'))
        op.execute(sa.text(f'grant select, insert, update, delete on table public."{table}" to service_role'))
        escaped = comment.replace("'", "''")
        op.execute(sa.text(f"comment on table public.\"{table}\" is '{escaped}'"))


def downgrade() -> None:
    bind = op.get_bind()
    indexes = _index_names(bind, "news_article")
    if "uq_news_article_source_guid" in indexes:
        op.drop_index("uq_news_article_source_guid", table_name="news_article")
    if "uq_news_article_identity_url" in indexes:
        op.drop_index("uq_news_article_identity_url", table_name="news_article")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("news_article")}
    if "identity_url" in columns:
        op.drop_column("news_article", "identity_url")
    if sa.inspect(bind).has_table("cluster_forbid_pair"):
        op.drop_table("cluster_forbid_pair")
