#!/bin/bash
# 经本地 PG 隧道运行 news-ingestion 的 wrapper（cron 与手工调试共用）。
#
# 背景：本机在联想内网，强制 HTTP 代理出网。psycopg（PG 协议）不走 *_proxy，
# 直连 Supabase:5432 不稳（~50%）；已验证经 HTTP 代理 CONNECT 隧道 100% 稳定
# （见 pg_tunnel.py + heytoday-pg-tunnel.service）。
# LLM：中转 sub.netdevops.lenovo.com 按 key 分账户组——.env 的 ANTHROPIC_API_KEY
# （Kimi key）属 Kimi 组，模型必须用 kimi-for-coding；该组不提供 claude-*。
# client.from_env 优先 ANTHROPIC_API_KEY（.env 经 setdefault 加载，因 bashrc 未设），
# 故此处锁定 LLM_MODEL=kimi-for-coding（须与 key 同组，否则 model_not_found）。
#
# 本 wrapper 做两件事：
#   1. 把真实 SUPABASE_DB_URL 的 host:port 重写为本地隧道 127.0.0.1:6543
#      （setdefault 下系统 env 覆盖 .env，news-ingestion 即经隧道连库）
#   2. 锁定 LLM_MODEL=kimi-for-coding（client.from_env 读，须与 .env 的 Kimi key 同组）
# 用法：./run-via-tunnel.sh <news-ingestion 子命令...>
set -euo pipefail
# cron 环境不读 ~/.bashrc（缺 https_proxy / ANTHROPIC_* 中转配置 / uv 的 PATH），显式 source。
# 已确认 .bashrc 开头无交互 return 检查，source 会执行全部 export。
set +eu
source /root/.bashrc 2>/dev/null
set -eu
cd /home/heytoday/新闻采集

export LLM_MODEL="${LLM_MODEL:-kimi-for-coding}"

# 重写 SUPABASE_DB_URL 指向本地隧道（不打印密码，结果仅进环境变量）
SUPABASE_DB_URL="$("$PWD/.venv/bin/python" - <<'PY'
from urllib.parse import urlparse
for line in open(".env", encoding="utf-8"):
    if line.strip().startswith("SUPABASE_DB_URL="):
        u = urlparse(line.strip().split("=", 1)[1].strip().strip('"').strip("'"))
        nl = u.netloc
        at = nl.rfind("@")
        ui = nl[: at + 1] if at >= 0 else ""
        print(u._replace(netloc=ui + "127.0.0.1:6543").geturl())
        break
PY
)"
export SUPABASE_DB_URL

exec uv run news-ingestion "$@"
