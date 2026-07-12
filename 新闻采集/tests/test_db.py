"""数据库迁移与闸门测试（plan §15：落后 head → 退出码 6）。"""

from __future__ import annotations

from news_ingestion.db import current_revision, head_revision, is_at_head, make_engine, needs_init_or_upgrade, run_upgrade


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
