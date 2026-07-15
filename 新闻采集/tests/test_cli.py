"""CLI 退出码与命令测试（plan §15）。"""

from __future__ import annotations

import pytest
import json
from types import SimpleNamespace
from typer.testing import CliRunner

from news_ingestion.cli import app
from news_ingestion.services.run_service import RunResult

runner = CliRunner()


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'db.sqlite3'}")
    monkeypatch.setenv("NEWS_ALLOW_SQLITE_TESTS", "1")
    monkeypatch.setenv("NEWS_LOCK_PATH", str(tmp_path / "lock"))
    monkeypatch.setenv("NEWS_LOG_FILE", str(tmp_path / "logs" / "test.log"))
    monkeypatch.setenv("NEWS_OUTPUT_DIR", str(tmp_path / "output"))
    return tmp_path


def test_uninitialized_db_gate_returns_6(isolated_env):
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 6


def test_db_upgrade_then_status(isolated_env):
    up = runner.invoke(app, ["db", "upgrade"])
    assert up.exit_code == 0
    status = runner.invoke(app, ["db", "status"])
    assert status.exit_code == 0
    assert "needs_init_or_upgrade=False" in status.stdout


def test_run_without_enabled_sources_returns_2(isolated_env, monkeypatch):
    runner.invoke(app, ["db", "upgrade"])
    # 与真实 config 启停状态解耦：强制无启用来源
    monkeypatch.setattr("news_ingestion.cli.load_sources", lambda: [])
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 2


def test_db_status_hides_connection_traceback(monkeypatch):
    from sqlalchemy.exc import OperationalError

    monkeypatch.setattr(
        "news_ingestion.cli.default_engine",
        lambda: (_ for _ in ()).throw(OperationalError("connect", {}, OSError("offline"))),
    )

    result = runner.invoke(app, ["db", "status"])

    assert result.exit_code == 6
    assert "数据库错误：OperationalError" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_run_json_outputs_machine_readable_task_result(isolated_env, monkeypatch):
    runner.invoke(app, ["db", "upgrade"])
    monkeypatch.setattr(
        "news_ingestion.cli.load_sources",
        lambda: [SimpleNamespace(enabled=True)],
    )
    monkeypatch.setattr(
        "news_ingestion.cli.run_pipeline",
        lambda *_args, **_kwargs: RunResult(
            exit_code=0,
            summary={"articles_created": 2, "duplicates": 1, "events_new": 1},
        ),
    )

    result = runner.invoke(app, ["run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["exit_code"] == 0
    assert payload["summary"]["articles_created"] == 2
    assert payload["summary"]["duplicates"] == 1
    assert payload["sources"] == []


def test_source_list_reads_config():
    result = runner.invoke(app, ["source", "list"])
    assert result.exit_code == 0
    assert "15 条来源记录" in result.stdout


def test_export_empty_returns_0(isolated_env):
    runner.invoke(app, ["db", "upgrade"])
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 0
    assert "result=empty" in result.stdout


def test_supabase_sync_reports_result(isolated_env, monkeypatch, tmp_path):
    runner.invoke(app, ["db", "upgrade"])
    material = tmp_path / "material.json"
    material.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "news_ingestion.cli.sync_material",
        lambda path: {"sync_id": "sync_123", "events": 2},
    )

    result = runner.invoke(app, ["supabase", "sync", "--input", str(material)])

    assert result.exit_code == 0
    assert "sync_123" in result.stdout
    assert "events=2" in result.stdout


def test_classify_without_llm_creds_returns_7(isolated_env, monkeypatch):
    runner.invoke(app, ["db", "upgrade"])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("NEWS_AUDIT_REASON", "验证未配置 LLM 的退出码")
    monkeypatch.setattr("news_ingestion.cli._require_ready", lambda *_args, **_kwargs: None)
    result = runner.invoke(app, ["classify", "--since", "24h"])
    assert result.exit_code == 7


def test_fact_check_without_reviewer_returns_9(isolated_env, monkeypatch):
    """缺 reviewer（业务前置）必须在 app_context 内捕获 → 退出码 9（非 1）。"""
    runner.invoke(app, ["db", "upgrade"])
    monkeypatch.delenv("NEWS_REVIEWER", raising=False)
    result = runner.invoke(app, ["event", "fact-check", "evt_bogus", "--status", "verified"])
    assert result.exit_code == 9


def test_review_nonexistent_event_returns_9(isolated_env, monkeypatch):
    """approve 不存在的事件 → 业务前置未满足 → 退出码 9。"""
    runner.invoke(app, ["db", "upgrade"])
    monkeypatch.setenv("NEWS_REVIEWER", "tester")
    result = runner.invoke(app, ["event", "review", "evt_bogus", "--approve"])
    assert result.exit_code == 9
