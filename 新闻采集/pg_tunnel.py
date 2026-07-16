"""Supabase PG 隧道：本地端口 -> HTTP 代理 CONNECT -> Supabase:5432。

仅用于「HTTP 代理出网、PG 直连不稳」的部署环境（如联想内网）。
psycopg（PG 协议）不读 *_proxy，故经 HTTP 代理的 CONNECT 方法建 TCP 隧道转发。
验证依据：直连 5432 成功率 ~50%，经此隧道 5/5 稳定。

这是部署适配脚本（与「测试Kimi连接.py」同类），**不是采集业务逻辑**；
不导入 news_ingestion 包，只依赖标准库 + .env / 系统环境。

配置（环境变量）：
  SUPABASE_DB_URL  真实 Supabase 连接串（取 host:port 作隧道目标），从本目录 .env 加载
  https_proxy      HTTP 代理地址（含认证），由系统环境提供（如 /root/.bashrc）
  PG_TUNNEL_PORT   本地监听端口（默认 6543）
"""
from __future__ import annotations

import base64
import os
import select
import signal
import socket
import sys
import threading
import time
from urllib.parse import urlparse, unquote

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("PG_TUNNEL_PORT", "6543"))
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s and "=" in s and not s.startswith("#"):
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _log(msg: str) -> None:
    print(f"[pg-tunnel] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


_load_dotenv(ENV_PATH)

db_url = os.environ.get("SUPABASE_DB_URL")
proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if not db_url:
    _log("缺少 SUPABASE_DB_URL（.env）"); sys.exit(2)
if not proxy_url:
    _log("缺少 https_proxy（系统环境）"); sys.exit(2)

_t = urlparse(db_url)
TARGET = (_t.hostname, _t.port or 5432)
_p = urlparse(proxy_url)
PROXY = (_p.hostname, _p.port or 8080)
_user = unquote(_p.username or "")
_pwd = unquote(_p.password or "")
AUTH = base64.b64encode(f"{_user}:{_pwd}".encode()).decode() if (_user or _pwd) else None


def connect_via_proxy() -> socket.socket:
    s = socket.create_connection(PROXY, timeout=15)
    req = f"CONNECT {TARGET[0]}:{TARGET[1]} HTTP/1.1\r\nHost: {TARGET[0]}:{TARGET[1]}\r\n"
    if AUTH:
        req += f"Proxy-Authorization: Basic {AUTH}\r\n"
    req += "\r\n"
    s.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = s.recv(4096)
        if not d:
            raise RuntimeError("代理在 CONNECT 阶段关闭连接")
        buf += d
    first = buf.split(b"\r\n")[0]
    if b" 200 " not in first:
        raise RuntimeError(f"代理 CONNECT 失败: {first.decode(errors='replace')}")
    return s


def relay(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            r, _, _ = select.select([a, b], [], [])
            for s in r:
                d = s.recv(65536)
                if not d:
                    return
                (b if s is a else a).sendall(d)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass


def handle(client: socket.socket) -> None:
    try:
        remote = connect_via_proxy()
        relay(client, remote)
    except Exception as e:
        _log(f"转发失败: {type(e).__name__}: {str(e)[:90]}")
        try:
            client.close()
        except Exception:
            pass


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((LISTEN_HOST, LISTEN_PORT))
srv.listen(100)
_log(f"监听 {LISTEN_HOST}:{LISTEN_PORT} -> 代理 {PROXY[0]}:{PROXY[1]} -> {TARGET[0]}:{TARGET[1]}")


def _shutdown(signum, _frame):
    _log(f"收到信号 {signum}，退出")
    try:
        srv.close()
    except Exception:
        pass
    sys.exit(0)


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)

while True:
    try:
        client, _ = srv.accept()
    except OSError:
        break
    threading.Thread(target=handle, args=(client,), daemon=True).start()
