"""把 ``news-material/v1`` 导出同步为 Supabase 不可变快照。"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jsonschema

from ..errors import ConfigError, DbInfraError, SchemaValidationError
from ..paths import PROMPTS_DIR
from ..paths import output_dir as default_output_dir

_SCHEMA_PATH = PROMPTS_DIR / "schemas" / "news_material.schema.json"


class SyncClient(Protocol):
    def upsert(self, table: str, rows: list[dict], *, on_conflict: str) -> None: ...

    def update(self, table: str, values: dict, *, filters: dict) -> None: ...


class SupabaseRestClient:
    """使用服务端密钥调用 Supabase Data API。"""

    def __init__(self, url: str, secret_key: str, *, timeout: float = 30.0) -> None:
        base = url.strip().rstrip("/")
        if not base.startswith("https://"):
            raise ConfigError("SUPABASE_URL 必须是 HTTPS 地址")
        if not secret_key.strip():
            raise ConfigError("SUPABASE_SECRET_KEY 不能为空")
        self.base_url = f"{base}/rest/v1"
        self.secret_key = secret_key.strip()
        self.timeout = timeout

    def _request(self, method: str, table: str, payload: object, query: dict[str, str]) -> None:
        url = f"{self.base_url}/{table}"
        if query:
            url = f"{url}?{urlencode(query)}"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "apikey": self.secret_key,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        if not self.secret_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.secret_key}"
        request = Request(
            url,
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - URL 经 HTTPS 校验
                response.read(1024)
        except HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise DbInfraError(f"Supabase Data API HTTP {exc.code}: {detail[:1000]}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise DbInfraError(f"Supabase Data API 连接失败：{exc}") from exc

    def upsert(self, table: str, rows: list[dict], *, on_conflict: str) -> None:
        self._request("POST", table, rows, {"on_conflict": on_conflict})

    def update(self, table: str, values: dict, *, filters: dict) -> None:
        query = {key: f"eq.{value}" for key, value in filters.items()}
        self._request("PATCH", table, values, query)


def _validate_material(doc: dict) -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft7Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        messages = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:8])
        raise SchemaValidationError(f"Supabase 同步输入未通过 news-material/v1 Schema：{messages}")


def _json_safe(value):
    """把历史导出中的非有限浮点数归一为合法 JSON null。"""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def prepare_snapshot(doc: dict) -> tuple[dict, list[dict]]:
    """生成稳定快照 ID、同步记录与事件行。"""
    doc = _json_safe(doc)
    _validate_material(doc)
    canonical = json.dumps(
        doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    sync_id = f"sync_{digest[:32]}"
    started_at = datetime.now(timezone.utc).isoformat()
    run = {
        "sync_id": sync_id,
        "schema_version": doc["schema_version"],
        "material_generated_at": doc["generated_at"],
        "result": doc["result"],
        "event_count": len(doc["events"]),
        "content_sha256": digest,
        "status": "syncing",
        "started_at": started_at,
        "finished_at": None,
        "error_message": None,
    }
    events = []
    for event in doc["events"]:
        events.append(
            {
                "sync_id": sync_id,
                "event_id": event["event_id"],
                "title": event["title"],
                "summary": event.get("summary"),
                "primary_category": event["primary_category"],
                "topic_categories": event.get("topic_categories") or [],
                "child_hook": event.get("child_hook"),
                "age_assessments": event.get("age_assessments") or {},
                "safety_tier": event["safety_tier"],
                "safety_tags": event.get("safety_tags") or [],
                "safety_reason": event.get("safety_reason"),
                "needs_fact_check": event["needs_fact_check"],
                "fact_check_targets": event.get("fact_check_targets") or [],
                "source_count": event["source_count"],
                "sources": event["sources"],
                "scores": event.get("scores") or {},
                "human_review": event.get("human_review"),
                "payload": event,
            }
        )
    return run, events


def _client_from_env() -> SupabaseRestClient:
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    ).strip()
    if not url or not key:
        raise ConfigError(
            "Supabase 同步缺少 SUPABASE_URL 与 SUPABASE_SECRET_KEY（或旧版 SUPABASE_SERVICE_ROLE_KEY）"
        )
    return SupabaseRestClient(url, key)


def sync_material(
    path: Path | None = None,
    *,
    client: SyncClient | None = None,
    chunk_size: int = 100,
) -> dict:
    """幂等同步一份新闻素材库；只在完整写入后标记 ``success``。"""
    material_path = Path(path) if path else default_output_dir() / "latest_news_material.json"
    if not material_path.is_file():
        raise ConfigError(f"新闻素材库不存在：{material_path}")
    if chunk_size <= 0:
        raise ConfigError("chunk_size 必须大于 0")
    try:
        doc = json.loads(material_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"读取新闻素材库失败：{exc}") from exc

    run, events = prepare_snapshot(doc)
    sync_client = client or _client_from_env()
    sync_client.upsert("news_material_sync_runs", [run], on_conflict="sync_id")
    try:
        for start in range(0, len(events), chunk_size):
            sync_client.upsert(
                "news_material_events",
                events[start : start + chunk_size],
                on_conflict="sync_id,event_id",
            )
    except Exception as exc:
        try:
            sync_client.update(
                "news_material_sync_runs",
                {
                    "status": "failed",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "error_message": str(exc)[:1000],
                },
                filters={"sync_id": run["sync_id"]},
            )
        except Exception:
            pass
        raise

    sync_client.update(
        "news_material_sync_runs",
        {
            "status": "success",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error_message": None,
        },
        filters={"sync_id": run["sync_id"]},
    )
    return {"sync_id": run["sync_id"], "events": len(events), "path": str(material_path)}
