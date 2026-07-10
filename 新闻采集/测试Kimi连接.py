"""用 Anthropic 兼容协议测试 Kimi Coding 连接。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib import error, request
from urllib.parse import urljoin, urlparse


MODEL = "kimi-for-coding"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.kimi.com/coding/"


def load_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_env(Path(__file__).with_name(".env"))

    base_url = os.getenv("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL).strip()
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("错误：请先在 新闻采集/.env 中填写 ANTHROPIC_API_KEY。", file=sys.stderr)
        return 2

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print("错误：ANTHROPIC_BASE_URL 必须是有效的 HTTP(S) 地址。", file=sys.stderr)
        return 2
    if parsed.scheme == "http":
        print("警告：当前 Base URL 使用明文 HTTP，请确认它只在可信内网中使用。", file=sys.stderr)

    endpoint = urljoin(base_url.rstrip("/") + "/", "v1/messages")
    payload = {
        "model": MODEL,
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "请只回复：Kimi 连接成功"}],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    http_request = request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            "x-api-key": api_key,
            "User-Agent": "heytoday-news-ingestion-kimi-smoke/0.1",
        },
    )

    try:
        with request.urlopen(http_request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        print(f"连接失败：HTTP {exc.code}\n{detail}", file=sys.stderr)
        return 1
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"连接失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    texts = [
        block.get("text", "")
        for block in result.get("content", [])
        if block.get("type") == "text"
    ]
    print(f"连接成功，模型：{result.get('model', MODEL)}")
    print("回复：" + "".join(texts).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
