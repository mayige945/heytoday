from __future__ import annotations

import errno
import os

import pytest

from news_ingestion.errors import LockBusyError
from news_ingestion.services import lock as lock_module
from news_ingestion.services.lock import ProcessLock


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
