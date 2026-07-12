"""安全 HTTP 抓取：SSRF / 协议 / userinfo（plan §6.4）。"""

from __future__ import annotations

import pytest

from news_ingestion.collectors.http import BlockedTargetError, validate_target


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/x",
        "http://localhost/x",
        "http://[::1]/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://172.16.0.1/x",
        "ftp://example.com/x",
        "file:///etc/passwd",
        "https://user:pass@example.com/x",
    ],
)
def test_blocked_targets(url):
    with pytest.raises(BlockedTargetError):
        validate_target(url)


@pytest.mark.parametrize(
    "mapped_url",
    [
        "http://[::ffff:127.0.0.1]/x",
        "http://[::ffff:169.254.169.254]/x",
        "http://[::ffff:10.0.0.1]/x",
    ],
)
def test_ipv4_mapped_ipv6_blocked(mapped_url):
    """IPv4-mapped IPv6 不得绕过 SSRF 黑名单。"""
    with pytest.raises(BlockedTargetError):
        validate_target(mapped_url)


def test_rsshub_localhost_allowed_only_when_explicit():
    with pytest.raises(BlockedTargetError):
        validate_target("http://localhost:1200/feed")
    assert validate_target("http://localhost:1200/feed", allow_private_hosts=frozenset({"localhost"}))


def test_public_https_accepted():
    assert validate_target("https://www.nasa.gov/feed") == "https://www.nasa.gov/feed"
