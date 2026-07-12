"""事件聚类：保守的确定性聚类（plan §10.4）。

不使用 embedding / 外部向量 / 中文分词库。四条件全满足才合并：
① 落在题材时间窗口内（普通热点 72h / 持续事件 7 天 / 科学发现 30 天）
② 归一化标题关键词 Jaccard ≥ 0.60
③ 命名实体 overlap coefficient ≥ 0.80
④ 至少共享一个非通用的关键实体。

任一不满足 → 独立事件；单篇文章也建独立事件；人工拆分写入禁止重聚关系。
阈值写 ``filters.toml``，调整属配置变更，必须同步测试夹具。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from ..cleaners.text import is_cjk_char, nfkc, normalize_title
from ..config import FiltersConfig
from ..types import ClusterArticle

# 引号 / 书名号片段（含全角与弯引号；NFKC 会把弯引号归一到直引号附近，这里两者都认）
_QUOTED_PATTERNS = [
    re.compile(r"《([^》]+)》"),
    re.compile(r"「([^」]+)」"),
    re.compile(r"『([^』]+)』"),
    re.compile(r"“([^”]+)”"),  # “…”
    re.compile(r"‘([^’]+)’"),  # ‘…’
    re.compile(r'"([^"]+)"'),
    re.compile(r"'([^']+)'"),
]
# 拉丁 token（保留原大小写，用于专名提取）
_LATIN_TOKEN_RAW = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_LATIN_PROPER_STOP = frozenset(
    {"the", "new", "an", "a", "is", "are", "was", "were", "will", "can",
     "says", "said", "of", "to", "in", "on", "for", "and", "or", "but", "with", "at", "by"}
)
# 带编号的任务 / 型号（含中文数字，如 神舟十八号 / 嫦娥六号 / 神舟18号）
_MISSION_CJK = re.compile(r"[一-鿿]{1,4}(?:[0-9]+|[一二三四五六七八九十百千万零两]+)号?")
_MISSION_LATIN = re.compile(r"[A-Za-z]{1,12}[\-\s]?[0-9]+[A-Za-z]{0,4}")
_LATIN_TOKEN = re.compile(r"[a-z0-9]+")

# 过度通用、不作为 condition④ 的「非通用实体」
_GENERIC_ENTITIES = frozenset(
    {"中国", "美国", "日本", "世界", "全球", "今天", "新闻", "报道", "网友", "官方"}
)


def extract_chinese_bigrams(text: str, stop_chars: frozenset[str]) -> set[str]:
    """去停用字后的连续二元字组（中文关键词）。"""
    chars = [ch for ch in text if is_cjk_char(ch) and ch not in stop_chars]
    if len(chars) < 2:
        return set()
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def extract_latin_tokens(text: str, stopwords: frozenset[str]) -> set[str]:
    tokens = {m.group(0) for m in _LATIN_TOKEN.finditer(text.lower())}
    return {t for t in tokens if t not in stopwords and len(t) > 1}


def extract_keywords(
    title: str,
    *,
    stop_chars: frozenset[str],
    latin_stopwords: frozenset[str],
) -> set[str]:
    """标题关键词 = 中文二元字组 ∪ 拉丁 token（归一化后）。"""
    normalized = normalize_title(title)
    return extract_chinese_bigrams(normalized, stop_chars) | extract_latin_tokens(normalized, latin_stopwords)


def _normalize_entity(entity: str, alias_dict: dict[str, str]) -> str:
    entity = entity.strip()
    return alias_dict.get(entity, entity)


def extract_entities(
    title: str,
    *,
    alias_dict: dict[str, str],
    source_tags: tuple[str, ...] = (),
) -> set[str]:
    """提取命名实体：书名号/引号片段、拉丁专名、带编号任务/型号、来源结构化标签；经别名词典归一。"""
    raw_title = nfkc(title or "")
    entities: set[str] = set()
    for pattern in _QUOTED_PATTERNS:
        for match in pattern.findall(raw_title):
            text = match.strip()
            if 2 <= len(text) <= 40:
                entities.add(text)
    for token in _LATIN_TOKEN_RAW.findall(raw_title):
        if len(token) >= 2 and any(ch.isupper() for ch in token) and token.lower() not in _LATIN_PROPER_STOP:
            entities.add(token)
    for match in _MISSION_CJK.finditer(raw_title):
        entities.add(match.group(0))
    for match in _MISSION_LATIN.finditer(raw_title):
        token = match.group(0).strip()
        if any(c.isdigit() for c in token) and len(token) >= 2:
            entities.add(token)
    for tag in source_tags:
        if tag:
            entities.add(str(tag))
    return {_normalize_entity(e, alias_dict) for e in entities if e}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def overlap_coefficient(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _window_hours(a: ClusterArticle, b: ClusterArticle, filters: FiltersConfig) -> int:
    # 三档时间窗口（plan §10.4）：科学发现/深度解释 30d、持续事件 7d、普通热点 72h
    if a.is_science or b.is_science:
        return filters.clustering.time_window_hours_science
    if a.is_ongoing or b.is_ongoing:
        return filters.clustering.time_window_hours_ongoing
    return filters.clustering.time_window_hours_general


def should_merge(
    a: ClusterArticle,
    b: ClusterArticle,
    *,
    filters: FiltersConfig,
    forbid_pairs: frozenset[frozenset[str]] = frozenset(),
) -> tuple[bool, str]:
    """四条件全满足才合并。返回 (是否合并, 原因)。"""
    pair = frozenset({a.id, b.id})
    if pair in forbid_pairs:
        return False, "forbid_remerge"

    window_hours = _window_hours(a, b, filters)
    if abs(a.time - b.time) > timedelta(hours=window_hours):
        return False, "time_window"

    keywords_a = extract_keywords(
        a.title, stop_chars=filters.chinese_stop_chars, latin_stopwords=filters.latin_stopwords
    )
    keywords_b = extract_keywords(
        b.title, stop_chars=filters.chinese_stop_chars, latin_stopwords=filters.latin_stopwords
    )
    if not keywords_a or not keywords_b:
        return False, "no_keywords"
    if jaccard(keywords_a, keywords_b) < filters.clustering.title_keyword_jaccard:
        return False, "keywords_jaccard"

    entities_a = extract_entities(a.title, alias_dict=filters.alias_dict, source_tags=tuple(a.source_tags))
    entities_b = extract_entities(b.title, alias_dict=filters.alias_dict, source_tags=tuple(b.source_tags))
    if not entities_a or not entities_b:
        return False, "no_entities"
    if overlap_coefficient(entities_a, entities_b) < filters.clustering.entity_overlap_coefficient:
        return False, "entity_overlap"

    shared_non_generic = (entities_a & entities_b) - _GENERIC_ENTITIES
    if not shared_non_generic:
        return False, "no_shared_entity"

    return True, "merged"


def cluster_articles(
    articles: list[ClusterArticle],
    *,
    filters: FiltersConfig,
    forbid_pairs: frozenset[frozenset[str]] = frozenset(),
) -> list[list[str]]:
    """单链接聚类：四条件满足则并入同一连通分量；返回分组（每组为 article id 列表）。

    单篇文章也形成独立事件。顺序按 time 升序，保证确定性。
    """
    if not articles:
        return []
    ordered = sorted(articles, key=lambda x: (x.time, x.id))
    n = len(ordered)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(n):
        for j in range(i + 1, n):
            merged, _ = should_merge(ordered[i], ordered[j], filters=filters, forbid_pairs=forbid_pairs)
            if merged:
                union(i, j)

    groups: dict[int, list[str]] = {}
    for index, article in enumerate(ordered):
        groups.setdefault(find(index), []).append(article.id)
    return list(groups.values())
