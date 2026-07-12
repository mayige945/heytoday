"""来源配置校验测试（plan §14 阶段一：未知字段 / 重复 code / 非法枚举 / 缺失必填 / enabled 未核验 → ConfigError）。"""

from __future__ import annotations

import pytest

from news_ingestion.config import load_sources
from news_ingestion.errors import ConfigError


def test_real_config_has_15_records_14_units():
    sources = load_sources()
    assert len(sources) == 15
    units = {s.unit_code for s in sources}
    assert len(units) == 14
    s14 = [s for s in sources if s.unit_code == "S14"]
    assert {s.code for s in s14} == {"trend_radar_zhihu", "trend_radar_bilibili"}
    assert all(s.requires_fact_check for s in s14)  # 热点雷达始终需事实核验
    # 注：来源 enabled 状态随操作者核验启用而变化（如 nasa 已 verified+enabled），不作为结构不变量断言


def _write_sources(tmp_path, body):
    path = tmp_path / "sources.toml"
    path.write_text(body, encoding="utf-8")
    return path.parent


def _valid_block(code="nasa", **overrides):
    base = f'''
[[sources]]
unit_code = "S08"
code = "{code}"
name = "NASA"
homepage_url = "https://nasa.gov/"
language = "en"
source_category = "science"
source_role = ["fact_source"]
acquisition_method = "rss"
feed_url = "https://nasa.gov/feed"
enabled = false
access_review_status = "uncertain"
'''
    return base


def test_duplicate_code_rejected(tmp_path):
    d = _write_sources(tmp_path, _valid_block("nasa") + _valid_block("nasa"))
    with pytest.raises(ConfigError, match="重复"):
        load_sources(d)


def test_unknown_field_rejected(tmp_path):
    d = _write_sources(tmp_path, _valid_block("nasa").replace('enabled = false', 'enabled = false\nbogus_field = 1'))
    with pytest.raises(ConfigError, match="未知字段"):
        load_sources(d)


def test_invalid_enum_rejected(tmp_path):
    d = _write_sources(tmp_path, _valid_block("nasa").replace('acquisition_method = "rss"', 'acquisition_method = "ftp"'))
    with pytest.raises(ConfigError, match="acquisition_method"):
        load_sources(d)


def test_missing_required_rejected(tmp_path):
    body = _valid_block("nasa").replace('language = "en"\n', '')
    d = _write_sources(tmp_path, body)
    with pytest.raises(ConfigError, match="language"):
        load_sources(d)


def test_enabled_without_verified_rejected(tmp_path):
    body = _valid_block("nasa").replace('enabled = false\naccess_review_status = "uncertain"',
                                        'enabled = true\naccess_review_status = "uncertain"')
    d = _write_sources(tmp_path, body)
    with pytest.raises(ConfigError, match="enabled=true"):
        load_sources(d)


def test_enabled_with_verified_accepted(tmp_path):
    body = _valid_block("nasa").replace('enabled = false\naccess_review_status = "uncertain"',
                                        'enabled = true\naccess_review_status = "verified"')
    d = _write_sources(tmp_path, body)
    sources = load_sources(d)
    assert sources[0].enabled is True


def test_method_specific_required(tmp_path):
    # webpage 缺 list_page_urls
    body = _valid_block("nasa").replace('acquisition_method = "rss"\nfeed_url = "https://nasa.gov/feed"',
                                        'acquisition_method = "webpage"')
    d = _write_sources(tmp_path, body)
    with pytest.raises(ConfigError, match="list_page_urls"):
        load_sources(d)
