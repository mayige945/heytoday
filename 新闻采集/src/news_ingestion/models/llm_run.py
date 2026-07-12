"""LLM 调用留痕表 ``llm_run``（plan §9.4）。

每次一级 / 二级调用单独留痕；``news_article`` / ``news_event`` 只物化最新一次
Schema 校验成功的结果。``raw_response``、脱敏错误与文件日志保留 30 天，由
``retention prune`` 清理；结构化结果与版本元数据长期保留。
"""

from __future__ import annotations

from sqlalchemy import JSON, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import new_id
from ..timeutil import utcnow
from .base import Base, UTCDateTime


class LlmRun(Base):
    __tablename__ = "llm_run"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("llm"))
    article_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)  # light | full

    model_provider: Mapped[str] = mapped_column(String(64), default="kimi_coding_anthropic")
    model_name: Mapped[str] = mapped_column(String(128), default="kimi-for-coding")
    prompt_name: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))

    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_result: Mapped[object] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)

    requested_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow, index=True)
    completed_at: Mapped[object] = mapped_column(UTCDateTime, nullable=True)

    token_usage: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LlmRun {self.id} {self.mode} {self.status}>"
