from __future__ import annotations

import json
import math

import pytest

from news_ingestion.errors import ConfigError, DbInfraError
from news_ingestion.services.supabase_sync import SupabaseRestClient, prepare_snapshot, sync_material


def _material_doc() -> dict:
    return {
        "schema_version": "news-material/v1",
        "generated_at": "2026-07-13T18:19:11+08:00",
        "result": "populated",
        "events": [
            {
                "event_id": "evt_1",
                "title": "第一条新闻",
                "summary": "摘要",
                "primary_category": "discovery",
                "topic_categories": ["science"],
                "child_hook": "你怎么看？",
                "age_assessments": {"upper_primary": {"child_interest_score": 80}},
                "safety_tier": "default",
                "safety_tags": [],
                "safety_reason": "默认可聊",
                "needs_fact_check": True,
                "fact_check_targets": ["核对数字"],
                "source_count": 1,
                "sources": [{"name": "NASA", "url": "https://example.com/1"}],
                "scores": {"discussion_score": 88},
                "human_review": None,
            },
            {
                "event_id": "evt_2",
                "title": "第二条新闻",
                "primary_category": "technology_in_life",
                "safety_tier": "sensitive",
                "needs_fact_check": False,
                "source_count": 1,
                "sources": [{"name": "MIT News", "url": "https://example.com/2"}],
            },
        ],
    }


class FakeClient:
    def __init__(self, *, fail_events: bool = False) -> None:
        self.fail_events = fail_events
        self.upserts: list[tuple[str, list[dict], str]] = []
        self.updates: list[tuple[str, dict, dict]] = []

    def upsert(self, table: str, rows: list[dict], *, on_conflict: str) -> None:
        if self.fail_events and table == "news_material_events":
            raise DbInfraError("remote write failed")
        self.upserts.append((table, rows, on_conflict))

    def update(self, table: str, values: dict, *, filters: dict) -> None:
        self.updates.append((table, values, filters))


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, _limit: int) -> bytes:
        return b""


@pytest.mark.parametrize(
    ("key", "expects_authorization"),
    [("sb_secret_example", False), ("legacy.jwt.service-role", True)],
)
def test_rest_client_uses_correct_headers_for_new_and_legacy_keys(
    monkeypatch, key, expects_authorization
):
    captured = []

    def fake_urlopen(request, *, timeout):
        captured.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr("news_ingestion.services.supabase_sync.urlopen", fake_urlopen)
    client = SupabaseRestClient("https://example.supabase.co", key)

    client.upsert("news_material_sync_runs", [{"sync_id": "sync_1"}], on_conflict="sync_id")

    headers = dict(captured[0][0].header_items())
    assert headers["Apikey"] == key
    assert ("Authorization" in headers) is expects_authorization


def test_prepare_snapshot_is_deterministic_and_keeps_full_payload():
    doc = _material_doc()

    first_run, first_events = prepare_snapshot(doc)
    second_run, second_events = prepare_snapshot(json.loads(json.dumps(doc)))

    assert first_run["sync_id"] == second_run["sync_id"]
    assert first_run["content_sha256"] == second_run["content_sha256"]
    assert first_run["event_count"] == 2
    assert first_events[0]["sync_id"] == first_run["sync_id"]
    assert first_events[0]["payload"] == doc["events"][0]
    assert second_events == first_events


def test_prepare_snapshot_normalizes_non_finite_numbers_to_valid_json():
    doc = _material_doc()
    doc["events"][0]["scores"]["story_score"] = math.nan

    run, events = prepare_snapshot(doc)

    assert events[0]["scores"]["story_score"] is None
    json.dumps(events, allow_nan=False)
    assert run["sync_id"].startswith("sync_")


def test_sync_material_upserts_snapshot_in_chunks_and_marks_success(tmp_path):
    path = tmp_path / "material.json"
    path.write_text(json.dumps(_material_doc(), ensure_ascii=False), encoding="utf-8")
    client = FakeClient()

    result = sync_material(path, client=client, chunk_size=1)

    assert result["events"] == 2
    assert [call[0] for call in client.upserts] == [
        "news_material_sync_runs",
        "news_material_events",
        "news_material_events",
    ]
    assert client.upserts[0][2] == "sync_id"
    assert client.upserts[1][2] == "sync_id,event_id"
    assert client.updates[-1][1]["status"] == "success"
    assert client.updates[-1][2] == {"sync_id": result["sync_id"]}


def test_sync_material_marks_snapshot_failed_when_event_write_fails(tmp_path):
    path = tmp_path / "material.json"
    path.write_text(json.dumps(_material_doc(), ensure_ascii=False), encoding="utf-8")
    client = FakeClient(fail_events=True)

    with pytest.raises(DbInfraError, match="remote write failed"):
        sync_material(path, client=client)

    assert client.updates[-1][1]["status"] == "failed"
    assert "remote write failed" in client.updates[-1][1]["error_message"]


def test_sync_material_requires_server_credentials(tmp_path, monkeypatch):
    path = tmp_path / "material.json"
    path.write_text(json.dumps(_material_doc(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(ConfigError, match="SUPABASE_URL"):
        sync_material(path)
