"""安全 HTTP 抓取（plan §6.4）。

采集与正文抓取共享本模块。硬约束：
- 只访问公开 HTTP/HTTPS，禁 ``file:``/``data:``/``ftp:`` 与携带用户名密码的 URL；
- 除 ``allow_private_hosts``（仅 RSSHub 的 localhost/127.0.0.1/::1）外，禁止请求
  或重定向到私网 / 环回 / 链路本地 / 组播 / 云元数据地址，**每次重定向后重新解析
  并校验目标 IP**；
- 限制重定向次数、响应体大小与允许的 content-type；
- 遵守单主机并发、请求间隔、超时与 ``Retry-After``；429/503 与超时可重试，
  401/403 等确定性 4xx 不重试。
"""

from __future__ import annotations

import gzip
import ipaddress
import socket
import threading
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from ..config import defaults
from ..errors import (
    BlockedTargetError,
    ContentTypeRejectedError,
    FetchError,
    HttpStatusError,
    ResponseTooBigError,
)

# 私网 / 环回 / 链路本地 / 组播 / 云元数据 / 保留
_BLOCKED_V4 = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
)]
_BLOCKED_V6 = [ipaddress.ip_network(n) for n in (
    "::1/128", "fc00::/7", "fe80::/10", "ff00::/8", "::/128",
)]

_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class _Redirect(Exception):
    def __init__(self, newurl: str, code: int):
        self.newurl = newurl
        self.code = code


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise _Redirect(newurl, code)


@dataclass
class FetchResponse:
    status: int
    final_url: str
    body: bytes
    encoding: str | None = None
    content_type: str | None = None
    elapsed_ms: int = 0
    metadata: dict = field(default_factory=dict)

    def text(self) -> str:
        for encoding in (self.encoding, "utf-8", "gb18030", "latin-1"):
            if not encoding:
                continue
            try:
                return self.body.decode(encoding, errors="strict")
            except (UnicodeDecodeError, LookupError):
                continue
        return self.body.decode("utf-8", errors="replace")


def _resolve_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedTargetError(f"无法解析主机 {host}: {exc}")
    seen: list[str] = []
    for family, _ctype, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in seen:
            seen.append(ip)
    return seen


def _is_blocked_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    if ip.version == 4:
        return any(ip in net for net in _BLOCKED_V4)
    # IPv6：查 v6 黑名单，再查 IPv4-mapped 内嵌地址（防 ::ffff:127.0.0.1 / ::ffff:169.254.169.254 绕过）
    if any(ip in net for net in _BLOCKED_V6):
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return any(mapped in net for net in _BLOCKED_V4)
    return False


# 单主机最小请求间隔（来源级礼貌限速，plan §6.4）
_HOST_LAST_REQUEST: dict[str, float] = {}
_HOST_PACER_LOCK = threading.Lock()


def _pace_host(host: str, min_interval_seconds: float) -> None:
    if min_interval_seconds <= 0 or not host:
        return
    key = host.lower()
    with _HOST_PACER_LOCK:
        last = _HOST_LAST_REQUEST.get(key)
        now = time.monotonic()
        wait = max(0.0, min_interval_seconds - (now - last)) if last is not None else 0.0
        _HOST_LAST_REQUEST[key] = now + wait
    if wait > 0:
        time.sleep(wait)


def validate_target(url: str, *, allow_private_hosts: frozenset[str] = frozenset()) -> str:
    """校验目标 URL 的协议与 IP；返回规范化 URL。非法即抛 ``BlockedTargetError``。"""
    if not url or not isinstance(url, str):
        raise BlockedTargetError("空 URL")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise BlockedTargetError(f"非法协议 {scheme!r}（仅允许 http/https）：{url}")
    if not parts.netloc:
        raise BlockedTargetError(f"缺少主机：{url}")
    if "@" in parts.netloc:
        raise BlockedTargetError(f"URL 含用户名/密码：{url}")
    host = parts.hostname or ""
    # 仅 RSSHub 调用方在 base_url 为 localhost/127.0.0.1/::1 时显式放行；其余一律拒绝私网/环回。
    host_allowed = host in allow_private_hosts
    if not host_allowed:
        for ip_text in _resolve_ips(host):
            if _is_blocked_ip(ip_text):
                raise BlockedTargetError(f"目标 {host}({ip_text}) 属私网/环回/链路本地/组播/云元数据，已拒绝")
    return url


def _decode_body(body: bytes, encoding_header: str | None, max_bytes: int) -> tuple[bytes, str | None]:
    """解压并限制解压后大小，防解压炸弹 DoS。"""
    if encoding_header and "gzip" in encoding_header.lower():
        try:
            decompressed = gzip.decompress(body)
        except OSError:
            return body, None
        if len(decompressed) > max_bytes:
            raise ResponseTooBigError(f"gzip 解压后超过 {max_bytes} 字节")
        return decompressed, None
    if encoding_header and "deflate" in encoding_header.lower():
        try:
            decompressed = zlib.decompress(body)
        except zlib.error:
            try:
                decompressed = zlib.decompress(body, -zlib.MAX_WBITS)
            except zlib.error:
                return body, None
        if len(decompressed) > max_bytes:
            raise ResponseTooBigError(f"deflate 解压后超过 {max_bytes} 字节")
        return decompressed, None
    return body, encoding_header


def _parse_retry_after(header_value: str | None) -> float:
    if not header_value:
        return 1.0
    header_value = header_value.strip()
    if header_value.isdigit():
        return min(float(header_value), 60.0)
    try:
        when = parsedate_to_datetime(header_value)
        if when is not None:
            delta = when.timestamp() - time.time()
            return max(0.0, min(delta, 60.0))
    except (TypeError, ValueError):
        pass
    return 1.0


def safe_fetch(
    url: str,
    *,
    timeout_seconds: float = 20.0,
    max_redirects: int = 5,
    max_bytes: int = 5_000_000,
    allowed_content_types: tuple[str, ...] = defaults.ALLOWED_CONTENT_TYPES_DEFAULT,
    allow_private_hosts: frozenset[str] = frozenset(),
    max_retries: int = 2,
    extra_headers: dict[str, str] | None = None,
    user_agent: str = defaults.HTTP_DEFAULTS["user_agent"],
    method: str = "GET",
    min_interval_seconds: float = 0.0,
) -> FetchResponse:
    """安全抓取一个 URL，遵循 SSRF / 大小 / content-type / Retry-After / 单主机间隔约束。"""
    opener = urllib.request.build_opener(_NoRedirectHandler)
    headers = {
        "User-Agent": user_agent,
        "Accept": ", ".join(allowed_content_types) if allowed_content_types else "*/*",
        "Accept-Encoding": "gzip, deflate",
    }
    if extra_headers:
        headers.update(extra_headers)

    current_url = url
    redirects = 0
    started = time.monotonic()
    last_error: str | None = None

    for attempt in range(max_retries + 1):
        validate_target(current_url, allow_private_hosts=allow_private_hosts)
        _pace_host(urlsplit(current_url).hostname or "", min_interval_seconds)
        request = urllib.request.Request(current_url, method=method, headers=headers)
        try:
            response = opener.open(request, timeout=timeout_seconds)
            status = response.status
            body = _read_capped(response, max_bytes)
            content_type = response.headers.get_content_type()
            encoding = response.headers.get_content_charset()
            body, _ = _decode_body(body, response.headers.get("Content-Encoding"), max_bytes)
            if allowed_content_types and not _content_type_allowed(content_type, allowed_content_types):
                raise ContentTypeRejectedError(f"{current_url} content-type={content_type!r} 不在允许列表")
            return FetchResponse(
                status=status,
                final_url=response.url or current_url,
                body=body,
                encoding=encoding,
                content_type=content_type,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                metadata={"redirects": redirects},
            )
        except _Redirect as redirect:
            redirects += 1
            if redirects > max_redirects:
                raise FetchError(f"超过最大重定向次数 {max_redirects}：{url}")
            current_url = redirect.newurl
            last_error = None
            continue  # 重定向不算一次 retry 消耗，重新走 loop
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status in (301, 302, 303, 307, 308):
                # 某些环境下 handler 未拦截到重定向，兜底
                location = exc.headers.get("Location")
                if not location:
                    raise HttpStatusError(status, "重定向缺 Location")
                redirects += 1
                if redirects > max_redirects:
                    raise FetchError(f"超过最大重定向次数 {max_redirects}：{url}")
                from urllib.parse import urljoin

                current_url = urljoin(current_url, location)
                continue
            if status in (429, 503) and attempt < max_retries:
                last_error = f"HTTP {status}"
                time.sleep(_parse_retry_after(exc.headers.get("Retry-After")))
                continue
            detail = _safe_read_error(exc)
            raise HttpStatusError(status, detail)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < max_retries:
                time.sleep(min(2.0 ** attempt, 4.0))
                continue
            raise FetchError(f"请求失败 {current_url}: {last_error}") from exc

    raise FetchError(f"抓取失败 {url}: {last_error}")


def _read_capped(response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooBigError(f"响应体超过 {max_bytes} 字节")
        chunks.append(chunk)
    return b"".join(chunks)


def _content_type_allowed(content_type: str | None, allowed: tuple[str, ...]) -> bool:
    if not content_type:
        return False
    normalized = content_type.split(";")[0].strip().lower()
    return any(normalized == allowed_ct or normalized.startswith(allowed_ct + "+xml") for allowed_ct in allowed)


def _safe_read_error(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read(4096).decode("utf-8", errors="replace")
    except Exception:
        return ""
