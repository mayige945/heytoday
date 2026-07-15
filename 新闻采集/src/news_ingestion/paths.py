"""模块运行路径解析。

所有路径相对模块根 ``新闻采集/`` 计算，使 CLI 无论从哪个工作目录发起都能
正确找到 ``config/``、``prompts/``、``data/``、``logs/``、``output/`` 与
``migrations/``。生产数据库由 ``SUPABASE_DB_URL`` 指定。
"""

from __future__ import annotations

import os
from pathlib import Path

# 本文件位于 新闻采集/src/news_ingestion/paths.py
# parents[0]=news_ingestion, parents[1]=src, parents[2]=新闻采集
_MODULE_ROOT_FROM_FILE = Path(__file__).resolve().parents[2]


def module_root() -> Path:
    """返回模块根目录（``新闻采集/``），可被 ``NEWS_MODULE_ROOT`` 覆盖。"""
    override = os.environ.get("NEWS_MODULE_ROOT")
    return Path(override).resolve() if override else _MODULE_ROOT_FROM_FILE


MODULE_ROOT = module_root()
CONFIG_DIR = MODULE_ROOT / "config"
PROMPTS_DIR = MODULE_ROOT / "prompts"
DATA_DIR = MODULE_ROOT / "data"
LOGS_DIR = MODULE_ROOT / "logs"
OUTPUT_DIR = MODULE_ROOT / "output"
MIGRATIONS_DIR = MODULE_ROOT / "migrations"

ALEMBIC_INI = MODULE_ROOT / "alembic.ini"


def lock_path() -> Path:
    override = os.environ.get("NEWS_LOCK_PATH")
    return Path(override).resolve() if override else DATA_DIR / "news-ingestion.lock"


def log_file() -> Path:
    override = os.environ.get("NEWS_LOG_FILE")
    return Path(override).resolve() if override else LOGS_DIR / "news-ingestion.log"


def log_files() -> list[Path]:
    """返回当前日志及 ``TimedRotatingFileHandler`` 轮转文件。"""
    current = log_file()
    return sorted(
        (path for path in current.parent.glob(f"{current.name}*") if path.is_file()),
        key=lambda path: path.name,
        reverse=True,
    )


def output_dir() -> Path:
    override = os.environ.get("NEWS_OUTPUT_DIR")
    return Path(override).resolve() if override else OUTPUT_DIR


def ensure_runtime_dirs() -> None:
    """创建运行所需的目录（不创建 output 以外的影响）。"""
    for directory in (DATA_DIR, LOGS_DIR, OUTPUT_DIR, MIGRATIONS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
