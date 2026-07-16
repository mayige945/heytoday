"""跨平台进程锁，防止同一工作区重复运行（plan §15）。

锁由操作系统随进程退出 / 崩溃自动释放，因此锁文件即使保留也不会成为失效锁；无需
手动清理。冲突时抛 ``LockBusyError``（CLI → 退出码 5）。
"""

from __future__ import annotations

import errno
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from ..errors import LockBusyError
from ..paths import lock_path
from ..timeutil import utcnow

from ..logging_setup import get_logger

_LOG = get_logger(__name__)


class ProcessLock:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or lock_path()
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 注意：不能用 'with open' 关闭，持有期间需保持句柄
        self._handle = open(self.path, "a+")  # noqa: SIM115
        try:
            if os.name == "nt":
                # msvcrt 锁定从当前位置开始的字节区间，文件必须至少有 1 字节。
                self._handle.seek(0, os.SEEK_END)
                if self._handle.tell() == 0:
                    self._handle.write(" ")
                    self._handle.flush()
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._handle.close()
            self._handle = None
            is_busy = isinstance(exc, BlockingIOError) or (
                os.name == "nt" and exc.errno in {errno.EACCES, errno.EDEADLK}
            )
            if not is_busy:
                raise
            raise LockBusyError(
                f"已有 news-ingestion 实例在运行（锁文件：{self.path}）"
            ) from None
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(str(os.getpid()))
        self._handle.flush()

    def release(self) -> None:
        if self._handle is not None:
            try:
                if os.name == "nt":
                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # 锁随进程退出 / PG 连接关闭自动释放；release 本身的异常（如隧道抖动）
        # 不影响正确性，降级为 warning，避免污染已成功的业务退出码。
        try:
            self.release()
        except Exception as exc:
            _LOG.warning("%s 释放失败（已忽略：锁随进程/连接退出自动释放）：%s", type(self).__name__, exc)


class DatabaseLock:
    """Postgres 会话级 advisory lock，防止多服务器任务重叠。"""

    _LOCK_ID = 744_202_607_13

    def __init__(
        self,
        engine: Engine,
        *,
        lock_domain: str = "news-ingestion",
        on_acquired: Callable[["DatabaseLock"], None] | None = None,
    ) -> None:
        self.engine = engine
        self.lock_domain = lock_domain
        self.on_acquired = on_acquired
        self.acquired_at: datetime | None = None
        self._connection: Connection | None = None

    @property
    def lock_id(self) -> int:
        if self.lock_domain == "news-ingestion":
            return self._LOCK_ID
        digest = hashlib.blake2b(self.lock_domain.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, byteorder="big", signed=True)

    def acquire(self) -> None:
        if self.engine.dialect.name == "postgresql":
            self._connection = self.engine.connect()
            acquired = bool(
                self._connection.scalar(
                    text("select pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": self.lock_id},
                )
            )
            if not acquired:
                self._connection.close()
                self._connection = None
                raise LockBusyError("已有 news-ingestion 服务器任务正在运行（Postgres advisory lock）")
        self.acquired_at = utcnow()
        if self.on_acquired is not None:
            try:
                self.on_acquired(self)
            except BaseException:
                self.release()
                raise

    def release(self) -> None:
        if self._connection is None:
            self.acquired_at = None
            return
        try:
            self._connection.execute(
                text("select pg_advisory_unlock(:lock_id)"),
                {"lock_id": self.lock_id},
            )
        finally:
            self._connection.close()
            self._connection = None
            self.acquired_at = None

    def __enter__(self) -> "DatabaseLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # 锁随进程退出 / PG 连接关闭自动释放；release 本身的异常（如隧道抖动）
        # 不影响正确性，降级为 warning，避免污染已成功的业务退出码。
        try:
            self.release()
        except Exception as exc:
            _LOG.warning("%s 释放失败（已忽略：锁随进程/连接退出自动释放）：%s", type(self).__name__, exc)
