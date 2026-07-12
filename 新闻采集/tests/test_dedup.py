"""去重测试：URL / 标题 / SHA-256 / SimHash（plan §10）。"""

from __future__ import annotations

from news_ingestion.dedup import build_candidate_from_content, find_duplicate
from news_ingestion.types import DedupCandidate

_BODY_A = ("据一项新研究发现，科学家用韦伯望远镜拍到了遥远星系的清晰图像，"
           "这有助于理解宇宙早期星系的形成。研究团队来自全球十余家机构。") * 6


def _candidate(id_, *, urls=None, title="t", content=None, fp=None):
    return DedupCandidate(
        id=id_,
        urls=urls or [f"https://x/{id_}"],
        title=title,
        title_fingerprint=fp or f"fp-{title}",
        content_hash=None,
        simhash=None,
        chinese_chars=0,
    )


def test_url_duplicate():
    target = _candidate("t", urls=["https://a.com/p?utm_source=x"])
    pool = [_candidate("a", urls=["https://a.com/p"])]
    decision = find_duplicate(target, pool)
    assert decision.is_duplicate and decision.basis == "url"


def test_title_duplicate():
    target = _candidate("t", title="hi", fp="fp-hi")
    pool = [_candidate("a", title="hi", fp="fp-hi")]
    decision = find_duplicate(target, pool)
    assert decision.is_duplicate and decision.basis == "title"


def test_sha256_exact_duplicate():
    a = build_candidate_from_content("a", url="https://a/1", canonical_url=None, title="A", content_clean=_BODY_A)
    b = build_candidate_from_content("b", url="https://b/1", canonical_url=None, title="B", content_clean=_BODY_A)
    decision = find_duplicate(b, [a])
    assert decision.is_duplicate and decision.basis == "sha256"


def test_simhash_near_repost_within_threshold():
    a = build_candidate_from_content("a", url="https://a/1", canonical_url=None, title="A", content_clean=_BODY_A)
    repost = "新华社北京7月10日电 " + _BODY_A + "（完）"
    b = build_candidate_from_content("b", url="https://b/1", canonical_url=None, title="B", content_clean=repost)
    decision = find_duplicate(b, [a])
    assert decision.is_duplicate and decision.basis == "simhash"


def test_short_content_skips_simhash():
    a = build_candidate_from_content("a", url="https://a/1", canonical_url=None, title="A", content_clean="短文本")
    b = build_candidate_from_content("b", url="https://b/1", canonical_url=None, title="B", content_clean="短文本别的")
    decision = find_duplicate(b, [a])
    # 都 < 200 中文字 → 不做 SimHash 自动合并
    assert not decision.is_duplicate


def test_not_duplicate():
    a = build_candidate_from_content("a", url="https://a/1", canonical_url=None, title="A", content_clean=_BODY_A)
    other = ("今天的股市行情出现了较大波动，多家上市公司发布了季度财报，投资者密切关注后续走势。") * 6
    b = build_candidate_from_content("b", url="https://b/1", canonical_url=None, title="B", content_clean=other)
    assert not find_duplicate(b, [a]).is_duplicate
