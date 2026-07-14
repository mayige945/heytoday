"""跨平台进程锁，防止同一工作区重复运行（plan §15）。

锁由操作系统随进程退出 / 崩溃自动释放，因此锁文件即使保留也不会成为失效锁；无需
手动清理。冲突时抛 ``LockBusyError``（CLI → 退出码 5）。
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from ..errors import LockBusyError
from ..paths import lock_path


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
        self.release()


class DatabaseLock:
    """Postgres 会话级 advisory lock，防止多服务器任务重叠。"""

    _LOCK_ID = 744_202_607_13

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._connection: Connection | None = None

    def acquire(self) -> None:
        if self.engine.dialect.name != "postgresql":
            return
        self._connection = self.engine.connect()
        acquired = bool(
            self._connection.scalar(
                text("select pg_try_advisory_lock(:lock_id)"),
                {"lock_id": self._LOCK_ID},
            )
        )
        if not acquired:
            self._connection.close()
            self._connection = None
            raise LockBusyError("已有 news-ingestion 服务器任务正在运行（Postgres advisory lock）")

    def release(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.execute(
                text("select pg_advisory_unlock(:lock_id)"),
                {"lock_id": self._LOCK_ID},
            )
        finally:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "DatabaseLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
