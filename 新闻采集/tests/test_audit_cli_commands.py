"""U4：CLI 命令审计覆盖与排除契约。"""

from __future__ import annotations

import getpass
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from news_ingestion.cli import AUDITED_COMMANDS, EXCLUDED_COMMANDS, _require_ready, app
from news_ingestion.db import default_engine, make_session_factory
from news_ingestion.models import BusinessTask, BusinessTaskStage, NewsArticle, NewsEvent
from news_ingestion.errors import (
    AuditPersistenceError,
    BusinessPreconditionError,
    LlmNotConfiguredError,
    LockBusyError,
)
from news_ingestion.audit import StageDefinition, WorkflowDefinition
from news_ingestion.errors import ConfigError
from news_ingestion.services import AuditedCommandResult, AuditedCommandSpec, AuditLifecycleService
from news_ingestion.services.run_service import RunResult
from news_ingestion.timeutil import utcnow

runner = CliRunner()

AUDITED = {
    "run", "fetch", "event.review", "event.fact-check", "export", "supabase.sync",
    "dedup", "cluster", "classify", "score", "llm.retry", "article.refetch",
    "retention.prune", "pool-index",
}
EXCLUDED = {
    "db.upgrade", "db.status", "source.list", "source.validate", "event.list",
    "fetch-log", "health", "retention.dry-run", "task.list", "task.show",
}


@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DATABASE_URL", f"sqlite:///{tmp_path / 'db.sqlite3'}")
    monkeypatch.setenv("NEWS_ALLOW_SQLITE_TESTS", "1")
    monkeypatch.setenv("NEWS_LOCK_PATH", str(tmp_path / "lock"))
    monkeypatch.setenv("NEWS_LOG_FILE", str(tmp_path / "logs" / "test.log"))
    monkeypatch.setenv("NEWS_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.delenv("NEWS_AUDIT_REASON", raising=False)
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == 0
    return tmp_path


def _tasks() -> list[BusinessTask]:
    with make_session_factory(default_engine())() as session:
        return list(session.scalars(select(BusinessTask).order_by(BusinessTask.created_at)))


def test_command_registry_covers_every_write_and_explicit_exclusion() -> None:
    assert set(AUDITED_COMMANDS) == AUDITED
    assert set(EXCLUDED_COMMANDS) == EXCLUDED
    assert AUDITED.isdisjoint(EXCLUDED)


def test_command_specs_require_and_separate_explicit_lock_domains() -> None:
    with pytest.raises(TypeError):
        AuditedCommandSpec("demo", "write")

    news_domains = {
        spec.lock_domain for spec in AUDITED_COMMANDS.values() if spec.module == "news_ingestion"
    }
    operations_domains = {
        spec.lock_domain for spec in AUDITED_COMMANDS.values() if spec.module == "operations"
    }
    assert news_domains == {"news-ingestion"}
    assert operations_domains == {"operations"}


def test_readiness_rejects_articles_outside_operation_window(session_factory, seeded_sources) -> None:
    source_id = next(iter(seeded_sources)).strip()
    with session_factory() as session:
        session.add(
            NewsArticle(
                source_id=source_id,
                url="https://example.com/old",
                title="窗口外旧文章",
                discovered_at=utcnow() - timedelta(hours=25),
                relevance_status="pending",
            )
        )
        session.commit()

    with pytest.raises(BusinessPreconditionError):
        _require_ready(session_factory, "dedup", since_hours=24)
    with pytest.raises(BusinessPreconditionError):
        _require_ready(session_factory, "classify", since_hours=24)


def test_cluster_readiness_rejects_old_published_article(session_factory, seeded_sources) -> None:
    source_id = next(iter(seeded_sources)).strip()
    with session_factory() as session:
        session.add(
            NewsArticle(
                source_id=source_id,
                url="https://example.com/old-published",
                title="发布时间超窗文章",
                discovered_at=utcnow(),
                published_at=utcnow() - timedelta(hours=73),
                relevance_status="relevant",
            )
        )
        session.commit()

    with pytest.raises(BusinessPreconditionError):
        _require_ready(session_factory, "cluster", since_hours=72)


def test_score_readiness_respects_retry_failed_and_target_status(session_factory) -> None:
    with session_factory() as session:
        event = NewsEvent(event_title="失败待重试事件", llm_status="failed")
        session.add(event)
        session.commit()
        event_id = event.id

    with pytest.raises(BusinessPreconditionError):
        _require_ready(session_factory, "score", target_id=event_id, retry_failed=False)
    _require_ready(session_factory, "score", target_id=event_id, retry_failed=True)


@pytest.mark.parametrize(
    ("operation", "args"),
    [
        ("run", ["run"]),
        ("fetch", ["fetch", "source-x"]),
        ("event.review", ["event", "review", "evt-x", "--approve"]),
        ("event.fact-check", ["event", "fact-check", "evt-x", "--status", "pending"]),
        ("export", ["export"]),
        ("supabase.sync", ["supabase", "sync"]),
        ("dedup", ["dedup", "--reason", "x"]),
        ("cluster", ["cluster", "--reason", "x"]),
        ("classify", ["classify", "--reason", "x"]),
        ("score", ["score", "--reason", "x"]),
        ("llm.retry", ["llm", "retry", "--reason", "x"]),
        ("article.refetch", ["article", "refetch", "art-x", "--reason", "x"]),
        ("retention.prune", ["retention", "prune"]),
        ("pool-index", ["pool-index"]),
    ],
)
def test_every_registered_command_is_wired_through_runner(cli_env, monkeypatch, operation, args) -> None:
    values = {
        "run": RunResult(exit_code=0, summary={}),
        "fetch": [SimpleNamespace(source_id="s", status="success", items_found=0, items_created=0, items_updated=0, errors=[])],
        "event.review": "reviewed",
        "event.fact-check": "checked",
        "export": (Path("a.json"), Path("a.md"), {"result": "empty", "events": 0}),
        "supabase.sync": {"sync_id": "sync-x", "events": 0},
        "dedup": {"checked": 0, "duplicates": 0, "by_basis": {}},
        "cluster": {}, "classify": {}, "score": {}, "llm.retry": {},
        "article.refetch": (True, 0),
        "retention.prune": {},
        "pool-index": Path("INDEX.md"),
    }
    seen: list[str] = []

    def fake_runner(_engine, _factory, actual_operation, _callback, **_kwargs):
        seen.append(actual_operation)
        return AuditedCommandResult(values[actual_operation])

    monkeypatch.setattr("news_ingestion.cli._run_audited", fake_runner)
    monkeypatch.setattr("news_ingestion.cli.load_source_by_code", lambda code: SimpleNamespace(code=code, enabled=True))
    monkeypatch.setattr("news_ingestion.cli.load_sources", lambda: [SimpleNamespace(code="s", enabled=True)])

    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert seen == [operation]


def test_nonstandard_missing_reason_is_noninteractive_blocked_task(cli_env, monkeypatch) -> None:
    called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("news_ingestion.cli.run_dedup", should_not_run)
    result = runner.invoke(app, ["dedup", "--since", "24h"])

    assert result.exit_code == 9
    assert called is False
    assert "prompt" not in (result.stdout + result.stderr).lower()
    task = _tasks()[-1]
    assert (task.operation, task.path_type, task.execution_status, task.design_status) == (
        "dedup", "non_standard", "blocked", "compliant"
    )


@pytest.mark.parametrize(
    ("args", "operation"),
    [
        (["cluster"], "cluster"),
        (["classify"], "classify"),
        (["score"], "score"),
        (["llm", "retry"], "llm.retry"),
        (["article", "refetch", "art_missing"], "article.refetch"),
    ],
)
def test_every_nonstandard_entry_requires_reason_before_business(cli_env, args, operation) -> None:
    before = len(_tasks())
    result = runner.invoke(app, args)
    assert result.exit_code == 9
    tasks = _tasks()
    assert len(tasks) == before + 1
    assert (tasks[-1].operation, tasks[-1].path_type, tasks[-1].execution_status) == (
        operation, "non_standard", "blocked"
    )


def test_score_missing_event_is_blocked_before_business(cli_env, monkeypatch) -> None:
    monkeypatch.setenv("NEWS_AUDIT_REASON", "人工排查评分失败")
    called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("news_ingestion.cli.run_score_full", should_not_run)
    result = runner.invoke(app, ["score", "--event", "evt_missing"])

    assert result.exit_code == 9
    assert called is False
    task = _tasks()[-1]
    assert task.operation == "score"
    assert task.reason == "人工排查评分失败"
    assert task.execution_status == "blocked"


def test_retention_write_and_pool_index_are_operations_but_dry_run_is_read_only(cli_env, monkeypatch) -> None:
    monkeypatch.setattr("news_ingestion.cli.prune", lambda *_args, **kwargs: {"dry_run": kwargs["dry_run"]})
    monkeypatch.setattr("news_ingestion.cli.regenerate_index", lambda *_args: cli_env / "output" / "INDEX.md")

    before = len(_tasks())
    dry = runner.invoke(app, ["retention", "prune", "--dry-run"])
    assert dry.exit_code == 0
    assert len(_tasks()) == before

    live = runner.invoke(app, ["retention", "prune"])
    pool = runner.invoke(app, ["pool-index"])
    assert (live.exit_code, pool.exit_code) == (0, 0)
    assert [task.operation for task in _tasks()[-2:]] == ["retention.prune", "pool-index"]


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["fetch", "--unknown-option"],
        ["db", "status"],
        ["source", "list"],
        ["source", "validate", "nasa"],
        ["event", "list"],
        ["fetch-log"],
        ["health"],
    ],
)
def test_excluded_help_and_parse_errors_do_not_create_tasks(cli_env, args) -> None:
    before = len(_tasks())
    runner.invoke(app, args)
    assert len(_tasks()) == before


def test_root_trigger_context_uses_explicit_values_and_safe_operator_default(cli_env, monkeypatch) -> None:
    monkeypatch.setattr("news_ingestion.cli.prune", lambda *_args, **_kwargs: {})
    result = runner.invoke(app, ["--trigger-type", "scheduler", "--operator", "cron-a", "retention", "prune"])
    assert result.exit_code == 0
    task = _tasks()[-1]
    assert (task.trigger_type, task.operator) == ("scheduler", "cron-a")

    result = runner.invoke(app, ["retention", "prune"])
    assert result.exit_code == 0
    assert _tasks()[-1].operator == getpass.getuser()


def test_lock_conflict_is_recorded_as_blocked_with_exit_5(cli_env, monkeypatch) -> None:
    class BusyLock:
        def __enter__(self):
            raise LockBusyError("busy")

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr("news_ingestion.services.audited_command.ProcessLock", BusyLock)
    result = runner.invoke(app, ["retention", "prune"])
    assert result.exit_code == 5
    task = _tasks()[-1]
    assert (task.operation, task.execution_status, task.design_status, task.exit_code) == (
        "retention.prune", "blocked", "compliant", 5
    )


def test_fetch_partial_success_keeps_exit_4_and_audit_status(cli_env, monkeypatch) -> None:
    source = SimpleNamespace(code="s", enabled=True)
    monkeypatch.setattr("news_ingestion.cli.load_source_by_code", lambda _code: source)
    outcomes = [
        SimpleNamespace(source_id="ok", status="success", items_found=1, items_created=1, items_updated=0, errors=[]),
        SimpleNamespace(source_id="bad", status="failed", items_found=0, items_created=0, items_updated=0, errors=["x"]),
    ]
    monkeypatch.setattr("news_ingestion.cli.fetch_all", lambda *_args, **_kwargs: outcomes)
    result = runner.invoke(app, ["fetch", "s"])
    assert result.exit_code == 4
    task = _tasks()[-1]
    assert (task.execution_status, task.design_status, task.exit_code) == ("partial_success", "compliant", 4)


def test_fetch_all_sources_failed_marks_task_and_stage_failed(cli_env, monkeypatch) -> None:
    source = SimpleNamespace(code="s", enabled=True)
    monkeypatch.setattr("news_ingestion.cli.load_source_by_code", lambda _code: source)
    monkeypatch.setattr(
        "news_ingestion.cli.fetch_all",
        lambda *_args, **_kwargs: [
            SimpleNamespace(source_id="bad", status="failed", items_found=0, items_created=0, items_updated=0, errors=["x"])
        ],
    )
    result = runner.invoke(app, ["fetch", "s"])
    assert result.exit_code == 3
    task = _tasks()[-1]
    with make_session_factory(default_engine())() as session:
        stage = session.scalar(select(BusinessTaskStage).where(BusinessTaskStage.task_id == task.id))
    assert (task.execution_status, task.design_status, task.exit_code) == ("failed", "incomplete", 3)
    assert (stage.status, stage.input_count, stage.output_count) == ("failed", 1, 0)


def test_runner_recovers_old_same_domain_task_after_lock_but_not_other_domain(cli_env, monkeypatch) -> None:
    factory = make_session_factory(default_engine())
    workflow = WorkflowDefinition("old.operation", "1", (StageDefinition("work", 1),))
    lifecycle = AuditLifecycleService(factory)
    old_same = lifecycle.start_task(module="old", operation="same", workflow=workflow, lock_domain="operations")
    lifecycle.mark_running(old_same)
    old_other = lifecycle.start_task(module="old", operation="other", workflow=workflow, lock_domain="other-domain")
    lifecycle.mark_running(old_other)
    with factory() as session:
        for task_id in (old_same, old_other):
            task = session.get(BusinessTask, task_id)
            task.created_at = utcnow() - timedelta(minutes=6)
        session.commit()
    monkeypatch.setattr(
        "news_ingestion.cli.load_runtime",
        lambda: SimpleNamespace(stale_run_recovery_minutes=5),
    )
    monkeypatch.setattr("news_ingestion.cli.prune", lambda *_args, **_kwargs: {})

    result = runner.invoke(app, ["retention", "prune"])
    assert result.exit_code == 0
    with factory() as session:
        same = session.get(BusinessTask, old_same)
        other = session.get(BusinessTask, old_other)
        current = session.scalar(select(BusinessTask).where(BusinessTask.operation == "retention.prune"))
    assert (same.execution_status, same.design_status) == ("abandoned", "incomplete")
    assert other.execution_status == "running"
    assert current.execution_status == "succeeded"


@pytest.mark.parametrize("args", [["run"], ["fetch", "source-x"]])
def test_pre_audit_config_error_keeps_exit_2_and_creates_no_task(cli_env, monkeypatch, args) -> None:
    before = len(_tasks())
    monkeypatch.setattr(
        "news_ingestion.cli.load_runtime",
        lambda: (_ for _ in ()).throw(ConfigError("bad config")),
    )
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert len(_tasks()) == before


def test_llm_not_configured_keeps_exit_7_and_terminal_task(cli_env, monkeypatch) -> None:
    monkeypatch.setattr("news_ingestion.cli._require_ready", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "news_ingestion.cli.run_classify_light",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(LlmNotConfiguredError("missing")),
    )
    result = runner.invoke(app, ["classify", "--reason", "diagnose"])
    assert result.exit_code == 7
    task = _tasks()[-1]
    assert (task.execution_status, task.design_status, task.exit_code) == ("failed", "incomplete", 7)


def test_business_precondition_is_finalized_inside_runner(cli_env, monkeypatch) -> None:
    monkeypatch.delenv("NEWS_REVIEWER", raising=False)
    result = runner.invoke(app, ["event", "review", "evt-x", "--approve"])
    assert result.exit_code == 9
    task = _tasks()[-1]
    assert (task.operation, task.execution_status, task.design_status) == (
        "event.review", "blocked", "compliant"
    )


def test_audit_persistence_error_prints_structured_retry_diagnostics(cli_env, monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AuditPersistenceError(
            "finalization failed",
            task_id="task-visible",
            failure_phase="task_finish",
            business_commit_state="committed",
        )

    monkeypatch.setattr("news_ingestion.cli.run_audited_command", fail)
    result = runner.invoke(app, ["retention", "prune"])
    assert result.exit_code == 6
    assert "task_id=task-visible" in result.stderr
    assert "failure_phase=task_finish" in result.stderr
    assert "business_commit_state=committed" in result.stderr


def test_run_json_stdout_is_exactly_one_json_document(cli_env, monkeypatch) -> None:
    monkeypatch.setattr("news_ingestion.cli.load_sources", lambda: [SimpleNamespace(enabled=True)])
    monkeypatch.setattr(
        "news_ingestion.cli.run_pipeline",
        lambda *_args, **_kwargs: RunResult(exit_code=0, summary={"articles_created": 1}),
    )
    result = runner.invoke(app, ["run", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["articles_created"] == 1
    assert result.stdout.count("\n") == 1
