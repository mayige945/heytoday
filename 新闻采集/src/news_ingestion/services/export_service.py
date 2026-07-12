"""新闻素材库导出（plan §9.8 v0.5，schema ``news-material/v1``）。

- 采集模块导出**一个**「新闻素材库」：宽口径素材池，**采集阶段只排除红线**；
- 含全部非红线、非重复、未被人工 ``rejected`` 且已评分（有 primary_category）的事件，及参考标签；
- 不分年龄档/家长档、不要求 fact-check verified、不要求 approved（这些判定下移选题/写稿）；
- JSON + Markdown 原子同出（先临时文件，双格式过 Schema 再一起改名，不覆盖历史）；不写 ``稿子/``；
- ``output/INDEX.md`` 与 ``latest_news_material.*`` 提供人读索引。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import jsonschema
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..errors import SchemaValidationError
from ..logging_setup import get_logger
from ..models import NewsEvent
from ..paths import PROMPTS_DIR
from ..paths import output_dir as default_output_dir
from ..repositories import ArticleRepository, ReviewRepository, SourceRepository
from ..timeutil import shanghai_stamp, to_shanghai, utcnow
from .event_view import build_material_event

_LOG = get_logger(__name__)
_SCHEMA_PATH = PROMPTS_DIR / "schemas" / "news_material.schema.json"


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _render_markdown(doc: dict) -> str:
    lines: list[str] = []
    lines.append("# 新闻素材库")
    lines.append("")
    lines.append(f"- 生成时间：{doc['generated_at']}（Asia/Shanghai）")
    lines.append(f"- schema：{doc['schema_version']}")
    lines.append(f"- 结果：{doc['result']}（采集阶段只排除红线；家长档×年龄档与事实核验在下游选题/写稿时做）")
    lines.append("")
    if doc["result"] == "empty":
        lines.append("**本次无素材事件。**")
        return "\n".join(lines) + "\n"

    for idx, event in enumerate(doc["events"], 1):
        review = event.get("human_review")
        review_tag = f" · 复核={review['status']}" if review else ""
        lines.append(f"## {idx}. {event['title']}  `_safety={event['safety_tier']}{review_tag}_`")
        lines.append("")
        lines.append(f"- 主分类：{event['primary_category']}；话题：{', '.join(event.get('topic_categories') or []) or '—'}")
        tags = event.get("safety_tags") or []
        lines.append(f"- 安全：{event['safety_tier']}{(' [' + ', '.join(tags) + ']') if tags else ''} —— {event.get('safety_reason') or '—'}")
        if event.get("summary"):
            lines.append(f"- 概述：{event['summary']}")
        if event.get("child_hook"):
            lines.append(f"- 儿童入口：{event['child_hook']}")
        aa = event.get("age_assessments") or {}
        up = (aa.get("upper_primary") or {}).get("child_interest_score")
        jh = (aa.get("junior_high") or {}).get("child_interest_score")
        if up is not None or jh is not None:
            lines.append(f"- 年龄兴趣参考：小学{up}·初中{jh}")
        scores = event.get("scores") or {}
        score_text = ", ".join(f"{k}={v}" for k, v in scores.items() if v is not None)
        if score_text:
            lines.append(f"- 评分：{score_text}")
        if event.get("needs_fact_check"):
            targets = event.get("fact_check_targets") or []
            lines.append(f"- ⚠️ 待核验（写稿前）：{'；'.join(targets) if targets else '是'}")
        lines.append(f"- 来源（{event['source_count']}）：")
        for source in event["sources"]:
            published = source.get("published_at")
            lines.append(f"  - {source['name']}（{source.get('role', '—')}）{source['url']}" + (f"  @{published}" if published else ""))
        lines.append("")
    return "\n".join(lines) + "\n"


def _unique_path(directory: Path, base: str, suffix: str) -> Path:
    candidate = directory / f"{base}{suffix}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{base}_{index}{suffix}"
        index += 1
    return candidate


def export_material(
    session_factory: sessionmaker,
    *,
    output_dir: Path | None = None,
) -> tuple[Path, Path, dict]:
    """导出单一新闻素材库（v0.5）。"""
    output_dir = output_dir or default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    material_events: list[dict] = []
    with session_factory() as session:
        events = list(session.scalars(select(NewsEvent).where(NewsEvent.status != "rejected")))
        sources_by_id = {s.code: s for s in SourceRepository(session).list_all()}
        review_repo = ReviewRepository(session)
        article_repo = ArticleRepository(session)
        for event in events:
            review = review_repo.latest_for_event(event.id)
            articles = article_repo.list_by_event(event.id)
            view = build_material_event(event, review, articles, sources_by_id)
            if view is not None:
                material_events.append(view)

    # 按讨论价值降序，便于下游选题人从最值得聊的看起
    material_events.sort(key=lambda e: (e.get("scores", {}).get("discussion_score") or 0), reverse=True)

    generated_at_shanghai = to_shanghai(utcnow())
    doc = {
        "schema_version": "news-material/v1",
        "generated_at": generated_at_shanghai.isoformat() if generated_at_shanghai else "",
        "result": "populated" if material_events else "empty",
        "events": material_events,
    }

    validator_ = jsonschema.Draft7Validator(_load_schema())
    errors = sorted(validator_.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        messages = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:8])
        raise SchemaValidationError(f"导出未通过 news-material/v1 Schema：{messages}")

    base = f"{shanghai_stamp(generated_at_shanghai)}_news_material"
    json_path = _unique_path(output_dir, base, ".json")
    md_path = json_path.with_suffix(".md")
    json_tmp = json_path.with_suffix(".json.tmp")
    md_tmp = md_path.with_suffix(".md.tmp")

    try:
        json_tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        md_tmp.write_text(_render_markdown(doc), encoding="utf-8")
    except OSError as exc:
        for tmp in (json_tmp, md_tmp):
            if tmp.exists():
                tmp.unlink()
        raise SchemaValidationError(f"写临时导出文件失败：{exc}") from exc

    try:
        os.replace(json_tmp, json_path)
        os.replace(md_tmp, md_path)
    except OSError as exc:
        for path in (json_path, md_path, json_tmp, md_tmp):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        raise SchemaValidationError(f"导出改名失败：{exc}") from exc

    _LOG.info("导出新闻素材库：%s（%d 事件）", json_path.name, len(material_events))
    try:
        shutil.copy2(json_path, output_dir / "latest_news_material.json")
        shutil.copy2(md_path, output_dir / "latest_news_material.md")
        regenerate_index(output_dir)
    except OSError as exc:
        _LOG.warning("生成 latest/INDEX 失败（不影响导出）：%s", exc)

    return json_path, md_path, {"result": doc["result"], "events": len(material_events), "json": str(json_path), "markdown": str(md_path)}


def regenerate_index(output_dir: Path | None = None) -> Path:
    """扫描 output/ 全部新闻素材库，生成中文人读 INDEX.md（最新在前）。"""
    output_dir = output_dir or default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for path in output_dir.glob("*.json"):
        if path.name.startswith("latest_") or path.name.startswith("INDEX"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if doc.get("schema_version") not in ("news-material/v1", "news-pool/v1"):
            continue
        events = doc.get("events") or []
        rows.append(
            {
                "generated_at": doc.get("generated_at", ""),
                "schema": doc.get("schema_version", ""),
                "result": doc.get("result", ""),
                "count": len(events),
                "first": (events[0].get("title", "—") if events else "（空池）"),
                "stem": path.stem,
            }
        )
    rows.sort(key=lambda r: r["generated_at"], reverse=True)

    lines: list[str] = []
    lines.append("# 新闻素材库索引（人读）\n")
    lines.append("> 每次导出生成 `YYYYMMDD_HHmmss_news_material.json/.md`（v0.5）；`latest_news_material.*` 覆盖式指向最新。\n")
    lines.append("| 时间（Asia/Shanghai） | schema | 结果 | 事件数 | 首条标题 | 文件 |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['generated_at'][:19]} | {r['schema']} | {r['result']} | {r['count']} | {r['first'][:30]} | `{r['stem']}` |"
        )
    index_path = output_dir / "INDEX.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path
