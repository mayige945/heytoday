"""采集器解析测试：RSS 2.0 / Atom / 网页列表（标准库解析）。"""

from __future__ import annotations

from news_ingestion.collectors.rss import parse_feed
from news_ingestion.config import SourceConfig
from news_ingestion.parsers import generic_list

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>T</title><link>https://example.com/</link>
<item><title>第一篇</title><link>https://example.com/a/1</link><guid isPermaLink="false">g1</guid><pubDate>Wed, 09 Jul 2026 10:00:00 +0800</pubDate><dc:creator>张三</dc:creator><category>太空</category></item>
<item><title><![CDATA[第二篇]]></title><link>/rel/2</link><pubDate>2026-07-08T12:00:00Z</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>NASA</title>
<entry><title>Webb Image</title><link rel="alternate" href="https://nasa.gov/x"/><id>urn:1</id><published>2026-07-07T00:00:00Z</published><category term="science"/></entry>
</feed>"""


def test_rss_parses_namespaces_relative_cdata():
    items = parse_feed(RSS)
    assert len(items) == 2
    assert items[0]["guid"] == "g1"
    assert items[0]["author"] == "张三"
    assert items[0]["tags"] == ["太空"]
    assert items[0]["published_at"] is not None
    assert items[1]["url"] == "https://example.com/rel/2"  # 相对链接解析
    assert items[1]["title"] == "第二篇"  # CDATA


def test_atom_parses_link_and_category():
    items = parse_feed(ATOM)
    assert len(items) == 1
    assert items[0]["url"] == "https://nasa.gov/x"
    assert items[0]["tags"] == ["science"]
    assert items[0]["published_at"] is not None


def test_empty_and_malformed():
    assert parse_feed("<rss><channel></channel></rss>") == []
    import pytest
    from news_ingestion.errors import FetchError
    with pytest.raises(FetchError):
        parse_feed("<rss><broken")


def _webpage_source(**kw):
    base = dict(
        unit_code="S06", code="thepaper", name="澎湃", homepage_url="https://thepaper.cn",
        language="zh-CN", source_category="society", source_role=["topic_source"],
        acquisition_method="webpage", list_page_urls=["https://thepaper.cn/news/"],
        allowed_sections=["newsDetail"], excluded_keywords=["广告", "登录"], enabled=False,
    )
    base.update(kw)
    return SourceConfig(**base)


def test_webpage_list_filters_sections_and_keywords():
    html = """<html><body><nav><a href="/">首页</a></nav>
    <div class="news">
      <a href="/newsDetail_2612345">火星发现水痕迹 研究人员称意义重大</a>
      <a href="/newsDetail_2612346">量子计算机取得新突破</a>
      <a href="/login">登录</a>
      <a href="https://other.com/x">外站</a>
      <a href="/ad/1">广告位</a>
    </div></body></html>"""
    items = generic_list.parse_list(html, "https://thepaper.cn/news/", _webpage_source())
    titles = [i.title for i in items]
    assert len(items) == 2
    assert all("广告" not in t and "登录" not in t for t in titles)
