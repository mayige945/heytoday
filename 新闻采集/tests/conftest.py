"""pytest 公共夹具：临时 SQLite、会话工厂、fake LLM client、fake 采集器。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Callable

import pytest
from sqlalchemy.orm import sessionmaker

from news_ingestion.config import SourceConfig, load_sources
from news_ingestion.db import make_engine, make_session_factory, run_upgrade
from news_ingestion.llm.client import LlmResponse
from news_ingestion.repositories import SourceRepository
from news_ingestion.timeutil import utcnow
from news_ingestion.types import DiscoveredArticle


@pytest.fixture()
def engine(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    eng = make_engine(db_path)
    run_upgrade(eng)
    return eng


@pytest.fixture()
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture()
def seeded_sources(session_factory):
    """把 config/sources.toml 的来源种子进临时库，返回 {code: SourceConfig}。"""
    configs = load_sources()
    with session_factory() as session:
        SourceRepository(session).seed_from_configs(configs)
        session.commit()
    return {c.code: c for c in configs}


# ---- 固定可用的 LLM 结构化输出（符合 schema）----

RELEVANCE_RELEVANT = {
    "schema_version": "news-relevance/v1",
    "relevance": "relevant",
    "topic_categories": ["technology_in_life"],
    "reason": "与学生 AI 使用情境直接相关",
}
RELEVANCE_IRRELEVANT = {
    "schema_version": "news-relevance/v1",
    "relevance": "irrelevant",
    "reason": "纯营销软文",
}
SCORING_DEFAULT = {
    "schema_version": "news-scoring/v1",
    "topic_categories": ["technology_in_life"],
    "primary_category": "technology_in_life",
    "summary": "一项关于 AI 进入校园的新政策引发讨论。",
    "age_assessments": {
        "upper_primary": {"child_interest_score": 82, "age_fit": "fit", "reason": "与学校生活相关"},
        "junior_high": {"child_interest_score": 88, "age_fit": "fit", "reason": "可讨论效率与公平"},
    },
    "story_score": 68,
    "discussion_score": 91,
    "knowledge_gain_score": 76,
    "life_relevance_score": 88,
    "value_pluralism_score": 85,
    "audio_fit_score": 75,
    "safety_tier": "default",
    "safety_tags": [],
    "safety_reason": "未命中红线或敏感层",
    "safety_uncertain": False,
    "safety_assessments": {
        "upper_primary": {"conservative": "eligible", "standard": "eligible", "open": "eligible"},
        "junior_high": {"conservative": "eligible", "standard": "eligible", "open": "eligible"},
    },
    "needs_fact_check": False,
    "fact_check_targets": [],
    "key_people": ["学生"],
    "key_conflicts": ["效率与公平"],
    "child_hook": "如果 AI 能帮你写作业，它是在帮你，还是在替你学习？",
    "reason": "事件与学生生活直接相关，存在明确冲突，适合父子对话。",
}


@dataclass
class FakeLlmClient:
    """按 system prompt 内容返回固定的合法 JSON；可注入失败 / 自定义结果。"""
    model: str = "kimi-fake"
    light_result: dict = field(default_factory=lambda: dict(RELEVANCE_RELEVANT))
    full_result: dict = field(default_factory=lambda: dict(SCORING_DEFAULT))
    fail_light: bool = False
    fail_full: bool = False
    malformed: bool = False
    calls: list = field(default_factory=list)

    def complete(self, *, system: str, user: str, max_tokens: int) -> LlmResponse:
        self.calls.append(system[:40])
        is_full = "news-scoring/v1" in system or "二级完整识别" in system
        if is_full:
            payload = self.full_result
            if self.fail_full:
                raise RuntimeError("fake full failure")
        else:
            payload = self.light_result
            if self.fail_light:
                raise RuntimeError("fake light failure")
        text = "oops not json" if self.malformed else json.dumps(payload, ensure_ascii=False)
        return LlmResponse(text=text, model=self.model, usage={"input_tokens": 100, "output_tokens": 200})


def make_discovered(
    *,
    source_id: str,
    url: str,
    title: str,
    guid: str | None = None,
    summary: str = "摘要",
    published_hours_ago: float = 1.0,
) -> DiscoveredArticle:
    return DiscoveredArticle(
        source_id=source_id,
        url=url,
        title=title,
        guid=guid,
        summary=summary,
        published_at=utcnow() - timedelta(hours=published_hours_ago),
        language="zh-CN",
    )


@pytest.fixture()
def fake_llm() -> Callable[..., FakeLlmClient]:
    def _make(**kwargs) -> FakeLlmClient:
        return FakeLlmClient(**kwargs)
    return _make


FIXTURES_DIR = Path(__file__).parent / "fixtures"
