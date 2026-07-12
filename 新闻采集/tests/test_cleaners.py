"""清洗层测试：URL / HTML / 文本。"""

from __future__ import annotations

from news_ingestion.cleaners import (
    clean_url,
    count_chinese_chars,
    html_to_text,
    normalize_title,
    sha256_hex,
    title_fingerprint,
)


def test_clean_url_drops_tracking():
    out = clean_url("https://a.com/p?utm_source=x&from=share&id=9&ref=tw#main")
    assert "utm_source" not in out and "from=share" not in out and "#main" not in out
    assert "id=9" in out


def test_clean_url_normalizes_default_port():
    assert clean_url("http://a.com:80/p") == "http://a.com/p"
    assert clean_url("https://a.com:443/p") == "https://a.com/p"


def test_html_to_text_strips_noise():
    html = "<html><head><script>x()</script><style>a{}</style></head><body><nav>导航</nav><article><p>第一段。</p><div class='ad'>广告</div><p>第二段。</p></article></body></html>"
    text = html_to_text(html)
    assert "x()" not in text and "导航" not in text and "广告" not in text
    assert "第一段" in text and "第二段" in text


def test_normalize_title_strips_media_and_punct():
    out = normalize_title("快讯：火星发现水！！ - 少数派")
    assert "少数派" not in out and "！！" not in out and out.endswith("水!")


def test_title_fingerprint_stable_across_surface_forms():
    a = title_fingerprint("火星发现水 - 少数派")
    b = title_fingerprint("  火星发现水 ｜少数派 ")
    assert a == b


def test_count_chinese_and_sha256():
    assert count_chinese_chars("hello 世界 abc 你好") == 4
    assert len(sha256_hex("abc")) == 64
