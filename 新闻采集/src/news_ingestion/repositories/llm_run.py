"""LLM 调用留痕仓储。

持久化前必须移除 API Key / Authorization / x-api-key / Cookie；错误文本设长度上限。
原始 raw_response 与脱敏错误保留 30 天，由 retention 清理。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ids import new_id
from ..models import LlmRun
from ..timeutil import utcnow

ERROR_TEXT_LIMIT = 1024
RAW_RESPONSE_LIMIT = 64_000


def sanitize_error(text: str | None) -> str | None:
    if text is None:
        return None
    return text[:ERROR_TEXT_LIMIT]


class LlmRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        mode: str,
        prompt_name: str,
        prompt_version: str,
        schema_version: str,
        input_hash: str,
        article_id: str | None = None,
        event_id: str | None = None,
        model_provider: str = "kimi_coding_anthropic",
        model_name: str = "kimi-for-coding",
    ) -> LlmRun:
        run = LlmRun(
            id=new_id("llm"),
            article_id=article_id,
            event_id=event_id,
            mode=mode,
            model_provider=model_provider,
            model_name=model_name,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            schema_version=schema_version,
            input_hash=input_hash,
            status="pending",
            requested_at=utcnow(),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def mark_success(
        self,
        run: LlmRun,
        *,
        parsed_result: dict,
        raw_response: str | None,
        token_usage: dict,
        estimated_cost: float | None,
    ) -> None:
        run.status = "success"
        run.parsed_result = parsed_result
        run.raw_response = (raw_response or "")[:RAW_RESPONSE_LIMIT] or None
        run.token_usage = token_usage or {}
        run.estimated_cost = estimated_cost
        run.completed_at = utcnow()
        run.error_message = None

    def mark_failed(self, run: LlmRun, *, error: str, raw_response: str | None = None) -> None:
        run.status = "failed"
        run.error_message = sanitize_error(error)
        run.raw_response = (raw_response or "")[:RAW_RESPONSE_LIMIT] or None
        run.completed_at = utcnow()

    def list(
        self,
        *,
        mode: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[LlmRun]:
        stmt = select(LlmRun).order_by(LlmRun.requested_at.desc())
        if mode:
            stmt = stmt.where(LlmRun.mode == mode)
        if status:
            stmt = stmt.where(LlmRun.status == status)
        return list(self.session.scalars(stmt.limit(limit)))

    def latest_success(self, *, article_id: str | None = None, event_id: str | None = None, mode: str | None = None) -> LlmRun | None:
        stmt = select(LlmRun).where(LlmRun.status == "success")
        if article_id:
            stmt = stmt.where(LlmRun.article_id == article_id)
        if event_id:
            stmt = stmt.where(LlmRun.event_id == event_id)
        if mode:
            stmt = stmt.where(LlmRun.mode == mode)
        stmt = stmt.order_by(LlmRun.requested_at.desc()).limit(1)
        return self.session.scalars(stmt).first()
