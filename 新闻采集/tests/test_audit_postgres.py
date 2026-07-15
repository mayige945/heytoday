"""审计账本的 PostgreSQL-only 完整性门槛。

必须显式提供 Supabase-shaped 隔离库；不得指向生产。
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from news_ingestion.audit import StageDefinition, WorkflowDefinition
from news_ingestion.db import make_engine, make_session_factory, run_upgrade
from news_ingestion.errors import AuditPersistenceError
from news_ingestion.services.audit_service import AuditLifecycleService, TaskOutcome


pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_engine():
    url = os.environ.get("NEWS_TEST_POSTGRES_URL", "")
    if not url:
        pytest.skip("requires isolated NEWS_TEST_POSTGRES_URL")
    assert url.startswith(("postgres://", "postgresql://"))
    production_url = os.environ.get("SUPABASE_DB_URL", "")
    assert not production_url or url != production_url, "NEWS_TEST_POSTGRES_URL must not equal SUPABASE_DB_URL"
    engine = make_engine(url)
    run_upgrade(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def lifecycle(live_engine):
    return AuditLifecycleService(make_session_factory(live_engine))


def _workflow(name: str = "live.concurrent") -> WorkflowDefinition:
    return WorkflowDefinition(name, "1", (StageDefinition("only", 1),))


def _running_task(service: AuditLifecycleService, *, name: str = "live.concurrent") -> str:
    task_id = service.start_task(module="live-test", operation=name, workflow=_workflow(name))
    service.mark_running(task_id)
    return task_id


def test_task_row_lock_serializes_same_stage_start(lifecycle):
    task_id = _running_task(lifecycle)

    def start():
        try:
            return lifecycle.start_stage(task_id, _workflow().stages[0])
        except AuditPersistenceError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: start(), range(2)))
    assert sum(result is not None for result in results) == 1


def test_terminal_task_cas_allows_only_one_finalizer(lifecycle):
    task_id = _running_task(lifecycle, name="live.finalize")

    def finish():
        try:
            lifecycle.finish_task(
                task_id,
                TaskOutcome(execution_status="succeeded", design_status="compliant", exit_code=0),
            )
            return True
        except AuditPersistenceError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: finish(), range(2)))
    assert results.count(True) == 1
    assert results.count(False) == 1


def test_detail_link_rejects_half_empty_and_cross_task_pairs(live_engine, lifecycle):
    first = _running_task(lifecycle, name="live.link.first")
    first_stage = lifecycle.start_stage(first, _workflow("live.link.first").stages[0])
    second = _running_task(lifecycle, name="live.link.second")

    llm_values = {
        "id": "llm_live_half",
        "mode": "light",
        "prompt_name": "live",
        "prompt_version": "1",
        "schema_version": "live/v1",
        "input_hash": "0" * 64,
        "status": "pending",
    }
    insert = text(
        "insert into llm_run "
        "(id, mode, model_provider, model_name, prompt_name, prompt_version, schema_version, input_hash, "
        "status, requested_at, token_usage, audit_task_id, audit_stage_id) "
        "values (:id, :mode, 'test', 'test', :prompt_name, :prompt_version, :schema_version, :input_hash, "
        ":status, now(), '{}'::json, :task_id, :stage_id)"
    )
    with pytest.raises(IntegrityError):
        with live_engine.begin() as connection:
            connection.execute(insert, {**llm_values, "task_id": first, "stage_id": None})
    with pytest.raises(IntegrityError):
        with live_engine.begin() as connection:
            connection.execute(
                insert,
                {**llm_values, "id": "llm_live_cross", "task_id": second, "stage_id": first_stage},
            )


def test_rls_is_enabled_and_client_roles_cannot_read_or_write(live_engine):
    with live_engine.connect() as connection:
        enabled = dict(
            connection.execute(
                text(
                    "select relname, relrowsecurity from pg_class "
                    "where relnamespace = 'public'::regnamespace "
                    "and relname in ('business_task','business_task_stage')"
                )
            )
        )
        roles = set(
            connection.execute(
                text("select rolname from pg_roles where rolname in ('anon','authenticated','service_role')")
            ).scalars()
        )
    assert enabled == {"business_task": True, "business_task_stage": True}
    missing = {"anon", "authenticated", "service_role"} - roles
    assert not missing, (
        "live audit gate requires a Supabase-shaped temporary database with roles; "
        f"missing: {sorted(missing)}"
    )

    for role in ("anon", "authenticated"):
        with live_engine.connect() as connection:
            connection.execute(text(f'SET ROLE "{role}"'))
            with pytest.raises(DBAPIError):
                connection.execute(text("select * from public.business_task limit 1"))
            connection.rollback()
        with live_engine.connect() as connection:
            connection.execute(text(f'SET ROLE "{role}"'))
            with pytest.raises(DBAPIError):
                connection.execute(text("insert into public.business_task (id) values ('client-write')"))
            connection.rollback()
