""".env 加载（仅 CLI 运行时调用）。

plan / CLAUDE.md：``ANTHROPIC_BASE_URL`` 与 ``ANTHROPIC_API_KEY`` 由用户在本目录 ``.env``
录入（已 gitignore）。``测试Kimi连接.py`` 自带加载；CLI 也必须加载才能看到凭据。
用 ``setdefault``，已存在的环境变量优先（测试 monkeypatch 不被覆盖）。
"""

from __future__ import annotations

import os
from pathlib import Path

from .paths import MODULE_ROOT


def load_dotenv(path: Path | None = None) -> None:
    target = path or (MODULE_ROOT / ".env")
    if not target.exists():
        return
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
