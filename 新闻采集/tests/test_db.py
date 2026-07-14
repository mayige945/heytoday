"""数据库迁移与闸门测试（plan §15：落后 head → 退出码 6）。"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

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
