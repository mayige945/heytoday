"""采集日志表 ``fetch_log``（plan §9.5）。

每个来源每次采集一条；进程异常退出后，下次运行把超过时限仍为 ``running`` 的
日志标为 ``failed``（原因 ``stale_run_recovered``）。
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import new_id
from ..timeutil import utcnow
from .base import Base, UTCDateTime


class FetchLog(Base):
    __tablename__ = "fetch_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("flg"))
    source_id: Mapped[str] = mapped_column(ForeignKey("news_source.id", ondelete="RESTRICT"), index=True)
    started_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="running", index=True)

    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_skipped: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FetchLog {self.id} {self.source_id} {self.status}>"
