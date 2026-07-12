"""进程锁：用 ``fcntl`` 排斥锁防止同一工作区重复运行（plan §15）。

``flock`` 在进程退出 / 崩溃时由内核自动释放，因此天然不存在失效锁文件；无需手动
清理。冲突时抛 ``LockBusyError``（CLI → 退出码 5）。
"""

from __future__ import annotations

import fcntl
from pathlib import Path

from ..errors import LockBusyError
from ..paths import lock_path


class ProcessLock:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or lock_path()
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 注意：不能用 'with open' 关闭，持有期间需保持句柄
        self._handle = open(self.path, "w")  # noqa: SIM115
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._handle.close()
            self._handle = None
            raise LockBusyError(f"已有 news-ingestion 实例在运行（锁文件：{self.path}）")
        self._handle.write(str(__import__("os").getpid()))
        self._handle.flush()

    def release(self) -> None:
        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
