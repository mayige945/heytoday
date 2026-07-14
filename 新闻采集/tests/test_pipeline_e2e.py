"""离线端到端测试（plan §19.14）：fake 采集器 + fake 正文 + fake LLM client。

不依赖真实网站或真实 Kimi；覆盖：源配置 → 采集 → 保存文章 → 正文抓取 → URL 去重
→ 采集日志 → 事件聚类 → LLM 分类与评分 → 结构化结果落库 → 双格式导出。
"""

from __future__ import annotations

from news_ingestion.config import FiltersConfig, RuntimeConfig, SourceConfig
from news_ingestion.models import LlmRun, NewsEvent
from news_ingestion.repositories import ArticleRepository
from news_ingestion.services import (
    approve_event,
    export_material,
    run_pipeline,
)
from news_ingestion.types import FetchedContent

from conftest import make_discovered


def _source(code, method="rss", **kw):
    base = dict(
        unit_code="S08", code=code, name=code, homepage_url="https://example.com/",
        language="zh-CN", source_category="science", source_role=["topic_source", "fact_source"],
        acquisition_method=method, enabled=True, priority=80,
        access_review_status="verified", access_reviewed_at="2026-07-10",
        access_evidence_url="https://example.com/robots.txt",
        feed_url="https://example.com/feed" if method == "rss" else None,
        list_page_urls=["https://example.com/list"] if method == "webpage" else None,
    )
    base.update(kw)
    return SourceConfig(**base)


def _fake_collector(items_by_code):
    def make(source, **_kwargs):
        return list(items_by_code.get(source.code, []))

    class _Wrapper:
        def __init__(self, code):
            self.code = code

        def collect(self, source, **kwargs):
            return make(source, **kwargs)

    def factory(code):
        return _Wrapper(code)

    return factory


def _fake_content(text_by_url=None):
    default_a = "据一项新研究发现，科学家用韦伯望远镜拍到了遥远星系的清晰图像，这有助于理解宇宙早期星系的形成。" * 6
    default_b = "研究人员在南极冰层下展开考察，发现了一种此前未知的微生物群落，它们依靠化学反应获得能量。" * 6
    text_by_url = text_by_url or {}

    def fetcher(url, *, source, user_agent, max_retries):
        if url in text_by_url:
            text = text_by_url[url]
        elif "a/1" in url or "b/1" in url:
            text = default_a
        else:
            text = default_b
        return FetchedContent(content_raw="<p>" + text + "</p>", content_clean=text, content_hash="h" * 64)

    return fetcher


def _runtime():
    return RuntimeConfig()


def _filters():
    return FiltersConfig()


def test_offline_end_to_end_happy_path(session_factory, fake_llm, tmp_path):
    src_a = _source("src_a")
    src_b = _source("src_b")
    items = {
        "src_a": [
            make_discovered(source_id="src_a", url="https://example.com/a/1", title="NASA韦伯望远镜拍到遥远星系新照片", guid="a1", published_hours_ago=2),
            make_discovered(source_id="src_a", url="https://example.com/a/2", title="深海发现新物种填补演化空白", guid="a2", published_hours_ago=3),
        ],
        # src_b b1 用不同 URL、与 a1 同标题同正文（测内容 sha256 / 标题去重）
        "src_b": [
            make_discovered(source_id="src_b", url="https://example.com/b/1", title="NASA韦伯望远镜拍到遥远星系新照片", guid="b1", published_hours_ago=1),
        ],
    }

    result = run_pipeline(
        session_factory,
        enabled_sources=[src_a, src_b],
        runtime=_runtime(),
        filters=_filters(),
        user_agent="test-ua",
        client=fake_llm(),
        collector_for=_fake_collector(items),
        content_fetcher=_fake_content(),
    )

    # 采集：两源各成功；三条被发现；至少一条被判重复
    assert result.exit_code == 0
    assert result.summary["sources_success"] == 2
    assert result.summary["articles_created"] == 3
    assert result.summary["duplicates"] >= 1

    with session_factory() as session:
        articles = ArticleRepository(session).list_since(None)
        non_dup = [a for a in articles if not a.duplicate_of]
        assert len(non_dup) == 2  # a1 + a2（b1 被去重）

        from news_ingestion.repositories import FetchLogRepository
        logs = FetchLogRepository(session).list(limit=10)
        assert all(log.status == "success" for log in logs)

        # 一级识别：非重复文章均已分类
        assert all(a.relevance_status != "pending" for a in non_dup)

        events = session.query(NewsEvent).all()
        assert len(events) >= 1

        scored = [e for e in events if e.llm_status == "success"]
        assert scored, "至少一个事件应被二级评分"
        evt = scored[0]
        assert evt.primary_category == "technology_in_life"
        assert evt.safety_tier in {"default", "sensitive"}
        assert evt.child_hook
        assert evt.age_assessments and evt.safety_assessments

        runs = session.query(LlmRun).all()
        assert runs
        for run in runs:
            assert run.model_name and run.prompt_version and run.schema_version
            assert run.input_hash and run.token_usage
            assert "ANTHROPIC_API_KEY" not in (run.raw_response or "")
            assert "sk-" not in (run.error_message or "")

        scored_event_id = evt.id

    repeated = run_pipeline(
        session_factory,
        enabled_sources=[src_a, src_b],
        runtime=_runtime(),
        filters=_filters(),
        user_agent="test-ua",
        client=fake_llm(),
        collector_for=_fake_collector(items),
        content_fetcher=_fake_content(),
    )
    assert repeated.summary["articles_created"] == 0
    assert repeated.summary["duplicates"] == 0

    # v0.5：事件默认进素材库；approve 可选；导出单一新闻素材库
    approve_event(session_factory, scored_event_id, reviewer="tester")

    json_path, md_path, info = export_material(session_factory, output_dir=tmp_path)
    assert info["result"] == "populated"
    assert json_path.exists() and md_path.exists()
    assert json_path.read_text(encoding="utf-8").startswith("{")
    assert "新闻素材库" in md_path.read_text(encoding="utf-8")


def test_run_without_llm_credentials_degrades_and_exits_7(session_factory, monkeypatch, tmp_path):
    """无 Kimi 凭据：非 LLM 阶段完成、一级降级 uncertain、二级 pending、退出码 7（plan §16.4）。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    from news_ingestion.llm import credentials_present
    assert credentials_present() is False

    src = _source("src_only")
    items = {"src_only": [make_discovered(source_id="src_only", url="https://example.com/x/1", title="测试新闻一", guid="x1")]}
    result = run_pipeline(
        session_factory,
        enabled_sources=[src],
        runtime=_runtime(),
        filters=_filters(),
        user_agent="test-ua",
        client=None,
        collector_for=_fake_collector(items),
        content_fetcher=_fake_content(),
    )
    assert result.exit_code == 7
    assert result.llm_configured is False
    # 非 LLM 数据保留
    with session_factory() as session:
        articles = ArticleRepository(session).list_since(None)
        assert len(articles) == 1
        assert articles[0].relevance_status == "uncertain"  # 降级
        events = session.query(NewsEvent).all()
        for event in events:
            assert event.llm_status in {"pending", "failed"}  # 二级未跑
