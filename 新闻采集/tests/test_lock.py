from __future__ import annotations

import errno
import os
from datetime import datetime

import pytest

from news_ingestion.errors import LockBusyError
from news_ingestion.services import lock as lock_module
from news_ingestion.services.lock import DatabaseLock, ProcessLock


def test_process_lock_rejects_second_holder_and_releases(tmp_path):
    path = tmp_path / "news-ingestion.lock"
    first = ProcessLock(path)
    second = ProcessLock(path)

    first.acquire()
    try:
        with pytest.raises(LockBusyError):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_process_lock_preserves_unexpected_os_errors(tmp_path, monkeypatch):
    def fail_lock(*_args):
        raise OSError(errno.EIO, "simulated I/O failure")

    backend = lock_module.msvcrt if os.name == "nt" else lock_module.fcntl
    monkeypatch.setattr(backend, "locking" if os.name == "nt" else "flock", fail_lock)

    lock = ProcessLock(tmp_path / "news-ingestion.lock")
    with pytest.raises(OSError, match="simulated I/O failure"):
        lock.acquire()

    assert lock._handle is None


class _FakeConnection:
    def __init__(self, acquired):
        self.acquired = acquired
        self.closed = False
        self.calls = []

    def scalar(self, statement, _params=None):
        self.calls.append(str(statement))
        return self.acquired if len(self.calls) == 1 else True

    def execute(self, statement, _params=None):
        self.calls.append(str(statement))

    def close(self):
        self.closed = True


class _FakeEngine:
    class dialect:
        name = "postgresql"

    def __init__(self, acquired):
        self.connection = _FakeConnection(acquired)

    def connect(self):
        return self.connection


class _FakeSqliteEngine:
    class dialect:
        name = "sqlite"


def test_database_lock_rejects_overlapping_server_run():
    engine = _FakeEngine(acquired=False)
    lock = DatabaseLock(engine)

    with pytest.raises(LockBusyError):
        lock.acquire()

    assert engine.connection.closed is True


def test_database_lock_releases_postgres_advisory_lock():
    engine = _FakeEngine(acquired=True)

    with DatabaseLock(engine):
        assert engine.connection.closed is False

    assert any("pg_advisory_unlock" in call for call in engine.connection.calls)
    assert engine.connection.closed is True


def test_database_lock_exposes_stable_domain_and_acquisition_time():
    engine = _FakeEngine(acquired=True)
    called = []
    lock = DatabaseLock(engine, lock_domain="news-run", on_acquired=lambda held: called.append(held))
    lock.acquire()
    try:
        assert lock.lock_domain == "news-run"
        assert isinstance(lock.acquired_at, datetime)
        assert called == [lock]
    finally:
        lock.release()
    assert lock.acquired_at is None


def test_database_lock_releases_when_acquisition_callback_fails():
    engine = _FakeEngine(acquired=True)

    def fail(_lock):
        raise RuntimeError("recovery failed")

    lock = DatabaseLock(engine, on_acquired=fail)
    with pytest.raises(RuntimeError, match="recovery failed"):
        lock.acquire()
    assert any("pg_advisory_unlock" in call for call in engine.connection.calls)
    assert engine.connection.closed is True
    assert lock.acquired_at is None


def test_database_lock_clears_acquisition_time_for_non_postgres():
    lock = DatabaseLock(_FakeSqliteEngine())
    lock.acquire()
    assert isinstance(lock.acquired_at, datetime)
    lock.release()
    assert lock.acquired_at is None
