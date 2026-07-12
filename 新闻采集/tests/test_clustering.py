"""事件聚类四条件测试（plan §10.4）：≥10 组应合并 / 不应合并夹具。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from news_ingestion.clustering import cluster_articles, should_merge
from news_ingestion.config import load_filters
from news_ingestion.timeutil import utcnow
from news_ingestion.types import ClusterArticle

FILTERS = load_filters()
T0 = utcnow()


def ca(title, *, science=False, dt=0.0, tags=(), key="x"):
    return ClusterArticle(
        id=key, title=title, time=T0 + timedelta(hours=dt), is_science=science, source_tags=list(tags)
    )


# (a_title, b_title, a_science, b_science, dt_hours, expected_merge)
SHOULD_MERGE = [
    ("NASA韦伯望远镜拍到遥远星系照片", "NASA韦伯望远镜拍到遥远星系照片公布", True, True, 5),
    ("SpaceX星舰完成第三次试飞", "SpaceX星舰完成第三次试飞成功", True, True, 8),
    ("OpenAI发布GPT-5模型", "OpenAI发布GPT-5模型亮相", False, False, 3),
    ("《三体》动画发布预告片", "《三体》动画发布预告片定档", False, False, 10),
    ("神舟十八号成功对接空间站", "神舟十八号成功对接", False, False, 6),
    ("苹果发布新款iPhone", "苹果发布新款iPhone亮相", False, False, 4),
]

SHOULD_NOT_MERGE = [
    ("NASA韦伯望远镜拍到遥远星系", "教育部发布课后服务新规", True, False, 5),
    ("SpaceX星舰试飞成功", "蓝色起源新格伦号完成首飞", True, True, 5),
    ("新研究发现黑洞旋转速率", "新研究发现中子星合并", False, False, 5),  # 无可提取实体
    ("OpenAI发布GPT-5模型", "谷歌发布Gemini新模型", False, False, 3),
    ("NASA韦伯望远镜拍到星系新照片", "NASA韦伯望远镜拍到星系新照片", False, False, 100),  # 超过普通 72h 窗口
    ("NASA Webb sees distant galaxy", "NASA韦伯望远镜拍到星系", True, True, 5),  # 跨语言
    ("", "短", False, False, 1),  # 空标题
]


@pytest.mark.parametrize("a,b,sa,sb,dt", SHOULD_MERGE)
def test_should_merge(a, b, sa, sb, dt):
    article_a = ca(a, science=sa, key="a")
    article_b = ca(b, science=sb, dt=dt, key="b")
    merged, reason = should_merge(article_a, article_b, filters=FILTERS)
    assert merged, f"期望合并但未合并（{reason}）：{a!r} / {b!r}"


@pytest.mark.parametrize("a,b,sa,sb,dt", SHOULD_NOT_MERGE)
def test_should_not_merge(a, b, sa, sb, dt):
    article_a = ca(a, science=sa, key="a")
    article_b = ca(b, science=sb, dt=dt, key="b")
    merged, reason = should_merge(article_a, article_b, filters=FILTERS)
    assert not merged, f"期望不合并却合并了：{a!r} / {b!r}"


def test_single_article_forms_own_event():
    groups = cluster_articles([ca("独一条新闻标题", key="solo")], filters=FILTERS)
    assert groups == [["solo"]]


def test_forbid_pair_prevents_remerge():
    a = ca("NASA韦伯望远镜拍到遥远星系新照片", science=True, key="a")
    b = ca("NASA韦伯望远镜拍到遥远星系图像", science=True, key="b")
    assert cluster_articles([a, b], filters=FILTERS) == [["a", "b"]]
    forbid = frozenset({frozenset({"a", "b"})})
    assert cluster_articles([a, b], filters=FILTERS, forbid_pairs=forbid) == [["a"], ["b"]]


def test_at_least_ten_fixtures():
    assert len(SHOULD_MERGE) + len(SHOULD_NOT_MERGE) >= 10
