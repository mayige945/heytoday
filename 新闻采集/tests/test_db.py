"""数据库迁移与闸门测试（plan §15：落后 head → 退出码 6）。"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import Session

from news_ingestion.db import current_revision, head_revision, is_at_head, make_engine, needs_init_or_upgrade, run_upgrade
from news_ingestion.db.alembic import _make_config
from news_ingestion.db import session as db_session
from news_ingestion.db.session import default_engine
from news_ingestion.errors import ConfigError


def test_fresh_db_needs_init(tmp_path):
    eng = make_engine(tmp_path / "f.sqlite3")
    assert needs_init_or_upgrade(eng) is True
    assert is_at_head(eng) is False
    assert current_revision(eng) is None


def test_upgrade_then_at_head(tmp_path):
    db = tmp_path / "f.sqlite3"
    eng = make_engine(db)
    run_upgrade(eng)
    assert is_at_head(eng) is True
    assert current_revision(eng) == head_revision()
    # 幂等
    run_upgrade(eng)
    assert is_at_head(eng) is True


def test_duplicate_basis_column_present(tmp_path):
    """迁移后 news_article.duplicate_basis 列存在（plan §10.3 保留判定依据）。"""
    import sqlalchemy as sa

    eng = make_engine(tmp_path / "f.sqlite3")
    run_upgrade(eng)
    with eng.connect() as conn:
        cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(news_article)"))}
    assert "duplicate_basis" in cols


def test_production_default_engine_requires_supabase_database_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("NEWS_DATABASE_URL", raising=False)
    monkeypatch.delenv("NEWS_ALLOW_SQLITE_TESTS", raising=False)

    with pytest.raises(ConfigError, match="SUPABASE_DB_URL"):
        default_engine()


def test_default_engine_rejects_sqlite_without_explicit_test_flag(monkeypatch, tmp_path):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'runtime.sqlite3'}")
    monkeypatch.delenv("NEWS_ALLOW_SQLITE_TESTS", raising=False)

    with pytest.raises(ConfigError, match="SQLite"):
        default_engine()


def test_default_engine_rejects_non_postgres_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "mysql://example.invalid/news")
    monkeypatch.delenv("NEWS_DATABASE_URL", raising=False)

    with pytest.raises(ConfigError, match="Postgres"):
        default_engine()


def test_postgres_schema_uses_timezone_aware_timestamps():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from news_ingestion.models import NewsArticle

    ddl = str(CreateTable(NewsArticle.__table__).compile(dialect=postgresql.dialect()))
    assert "TIMESTAMP WITH TIME ZONE" in ddl


def test_postgres_engine_has_bounded_connect_timeout(monkeypatch):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(db_session, "create_engine", fake_create_engine)

    db_session.make_engine("postgresql://example.invalid/news")

    assert captured["kwargs"]["connect_args"]["connect_timeout"] == 10
    assert "sslmode=require" in captured["url"]


def test_downgrade_0003_removes_runtime_schema_additions(tmp_path):
    eng = make_engine(tmp_path / "downgrade.sqlite3")
    run_upgrade(eng)

    command.downgrade(_make_config(str(eng.url)), "0002")

    inspector = sa.inspect(eng)
    assert "cluster_forbid_pair" not in inspector.get_table_names()
    assert "identity_url" not in {
        column["name"] for column in inspector.get_columns("news_article")
    }


def test_business_audit_schema_and_nullable_detail_links_present(tmp_path):
    eng = make_engine(tmp_path / "audit.sqlite3")
    run_upgrade(eng)
    inspector = sa.inspect(eng)

    assert {"business_task", "business_task_stage"} <= set(inspector.get_table_names())
    task_columns = {column["name"] for column in inspector.get_columns("business_task")}
    assert {"execution_status", "design_status", "expected_stages_snapshot"} <= task_columns
    stage_indexes = {index["name"] for index in inspector.get_indexes("business_task_stage")}
    assert {"ix_business_task_stage_task_id", "ix_business_task_stage_task_status"} <= stage_indexes
    stage_uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("business_task_stage")}
    assert {
        "uq_business_task_stage_id_task",
        "uq_business_task_stage_actual_sequence",
        "uq_business_task_stage_attempt",
    } <= stage_uniques
    for table in ("fetch_log", "llm_run"):
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert columns["audit_task_id"]["nullable"] is True
        assert columns["audit_stage_id"]["nullable"] is True
        foreign_keys = {foreign_key["name"]: foreign_key for foreign_key in inspector.get_foreign_keys(table)}
        assert foreign_keys[f"fk_{table}_audit_stage_task"]["constrained_columns"] == [
            "audit_stage_id",
            "audit_task_id",
        ]


def test_postgres_audit_ddl_uses_match_full_and_supabase_security() -> None:
    from pathlib import Path

    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from news_ingestion.models import LlmRun

    ddl = str(CreateTable(LlmRun.__table__).compile(dialect=postgresql.dialect()))
    assert "MATCH FULL ON DELETE RESTRICT" in ddl
    migration = (Path(__file__).parents[1] / "migrations" / "versions" / "0005_business_task_audit.py").read_text(encoding="utf-8")
    assert "from news_ingestion.models" not in migration
    assert 'op.create_table("business_task"' in migration
    assert 'op.create_table("business_task_stage"' in migration
    assert "enable row level security" in migration
    assert "revoke all on table" in migration
    assert "grant select, insert, update on table" in migration
    assert "to service_role" in migration


def test_upgrade_and_round_trip_preserve_existing_business_rows(tmp_path):
    eng = make_engine(tmp_path / "audit-roundtrip.sqlite3")
    config = _make_config(str(eng.url))
    command.upgrade(config, "0004")
    from news_ingestion.models import NewsSource

    with Session(eng) as session:
        session.add(
            NewsSource(
                id="s1",
                code="s1",
                unit_code="U1",
                name="source",
                homepage_url="https://example.test/",
                language="en",
                source_category="science",
                source_role=["fact_source"],
                acquisition_method="rss",
            )
        )
        session.commit()
    baseline = _business_baseline(eng)

    command.upgrade(config, "0005")
    assert _business_baseline(eng) == baseline
    command.downgrade(config, "0004")
    assert _business_baseline(eng) == baseline
    command.upgrade(config, "0005")
    assert _business_baseline(eng) == baseline


def _business_baseline(engine):
    with engine.connect() as conn:
        return conn.execute(sa.text("select id, code, unit_code, name, homepage_url from news_source order by id")).all()
