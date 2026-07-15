"""审计账本的 PostgreSQL-only 完整性门槛。

必须显式提供 Supabase-shaped 隔离库；不得指向生产。
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, IntegrityError

from news_ingestion.audit import StageDefinition, WorkflowDefinition
from news_ingestion.db import make_engine, make_session_factory, run_upgrade
from news_ingestion.errors import AuditPersistenceError
from news_ingestion.services.audit_service import AuditLifecycleService, TaskOutcome


pytestmark = pytest.mark.live


def _database_identity(raw_url: str, *, variable: str) -> tuple[str, str, int, str]:
    try:
        url = make_url(raw_url)
    except ArgumentError as exc:
        pytest.fail(f"{variable} is not a valid database URL: {exc}")
    if url.get_backend_name() != "postgresql":
        pytest.fail(f"{variable} must use PostgreSQL")
    if not url.host or not url.database:
        pytest.fail(f"{variable} must include host and database")
    return (
        (url.username or "").lower(),
        url.host.rstrip(".").lower(),
        url.port or 5432,
        url.database,
    )


def test_database_identity_normalizes_driver_host_port_and_query():
    first = _database_identity(
        "postgresql://Audit@DB.EXAMPLE.test/app?sslmode=require",
        variable="first",
    )
    second = _database_identity(
        "postgresql+psycopg://audit:other@db.example.test:5432/app?connect_timeout=5",
        variable="second",
    )
    assert first == second == ("audit", "db.example.test", 5432, "app")


@pytest.fixture(scope="module")
def live_engine():
    url = os.environ.get("NEWS_TEST_POSTGRES_URL", "")
    if not url:
        pytest.skip("requires isolated NEWS_TEST_POSTGRES_URL")
    if os.environ.get("NEWS_TEST_POSTGRES_ISOLATED") != "1":
        pytest.fail(
            "set NEWS_TEST_POSTGRES_ISOLATED=1 only after confirming "
            "NEWS_TEST_POSTGRES_URL is disposable and isolated"
        )
    test_identity = _database_identity(url, variable="NEWS_TEST_POSTGRES_URL")
    production_url = os.environ.get("SUPABASE_DB_URL", "")
    if production_url:
        production_identity = _database_identity(production_url, variable="SUPABASE_DB_URL")
        if test_identity == production_identity:
            pytest.fail("NEWS_TEST_POSTGRES_URL resolves to the same database as SUPABASE_DB_URL")
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


def test_service_role_has_exact_runtime_permissions_and_can_read_write(live_engine):
    tables = ("business_task", "business_task_stage")
    with live_engine.connect() as connection:
        for table in tables:
            privileges = {
                privilege: bool(
                    connection.scalar(
                        text("select has_table_privilege('service_role', :table, :privilege)"),
                        {"table": f"public.{table}", "privilege": privilege},
                    )
                )
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
            }
            assert privileges == {
                "SELECT": True,
                "INSERT": True,
                "UPDATE": True,
                "DELETE": False,
            }

    task_id = "task_live_service_role"
    stage_id = "stage_live_service_role"
    with live_engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text('SET LOCAL ROLE "service_role"'))
        connection.execute(
            text(
                "insert into public.business_task "
                "(id, module, operation, trigger_type, path_type, execution_status, design_status, "
                "workflow_name, workflow_version, scope_snapshot, expected_stages_snapshot, "
                "summary_snapshot, design_validation_snapshot, created_at) values "
                "(:id, 'live-test', 'permission-check', 'manual', 'standard', 'requested', 'pending', "
                "'live.permission', '1', '{}'::json, '{}'::json, '{}'::json, '{}'::json, now())"
            ),
            {"id": task_id},
        )
        connection.execute(
            text(
                "insert into public.business_task_stage "
                "(id, task_id, stage_key, attempt_no, expected_sequence, actual_sequence, status, "
                "prerequisite_evidence, routes_snapshot, reason_breakdown, metrics_snapshot, "
                "validation_snapshot) values "
                "(:id, :task_id, 'permission-check', 1, 1, 1, 'requested', "
                "'{}'::json, '{}'::json, '{}'::json, '{}'::json, '{}'::json)"
            ),
            {"id": stage_id, "task_id": task_id},
        )
        connection.execute(
            text("update public.business_task set operator='service-role-check' where id=:id"),
            {"id": task_id},
        )
        connection.execute(
            text("update public.business_task_stage set unit='operation' where id=:id"),
            {"id": stage_id},
        )
        assert connection.scalar(
            text("select count(*) from public.business_task where id=:id"),
            {"id": task_id},
        ) == 1
        assert connection.scalar(
            text("select count(*) from public.business_task_stage where id=:id"),
            {"id": stage_id},
        ) == 1
        transaction.rollback()

    for table in tables:
        with live_engine.connect() as connection:
            connection.execute(text('SET ROLE "service_role"'))
            with pytest.raises(DBAPIError):
                connection.execute(text(f'delete from public."{table}" where false'))
            connection.rollback()
