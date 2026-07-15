"""日志初始化：读 ``config/logging.toml``，落文件 + 控制台。

文件运行日志保留 30 天（由 ``retention prune`` 清理），日志中绝不写入密钥、
Authorization / x-api-key 头或 Cookie。
"""

from __future__ import annotations

import logging
import logging.config
import tomllib
from pathlib import Path
from typing import Any

from . import paths

_DEFAULTS: dict[str, Any] = {
    "level": "INFO",
    "file_level": "INFO",
    "console_level": "WARNING",
    "format": "%(asctime)s %(levelname)s [%(name)s] [task=%(task_id)s stage=%(stage_id)s module=%(audit_module)s operation=%(audit_operation)s] %(message)s",
    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
}

_CONFIGURED = False


def _load_logging_config() -> dict[str, Any]:
    config_path = paths.CONFIG_DIR / "logging.toml"
    data: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    return {**_DEFAULTS, **data.get("logging", {})}


def setup_logging(*, force: bool = False) -> None:
    """配置根日志。幂等，除非 ``force`` 否则重复调用无效。

    文件日志失败（目录不存在 / 无写权限等）时回退到仅控制台日志——日志配置绝不应
    拖垮整个 CLI。
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    cfg = _load_logging_config()
    paths.ensure_runtime_dirs()
    log_path = paths.log_file()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    file_handler_config = {
        "class": "logging.handlers.TimedRotatingFileHandler",
        "level": cfg["file_level"],
        "formatter": "default",
        "filename": str(log_path),
        "when": "midnight",
        "backupCount": 30,
        "encoding": "utf-8",
        "utc": False,
    }
    full_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"format": cfg["format"], "datefmt": cfg["datefmt"]}},
        "filters": {"audit_context": {"()": "news_ingestion.audit.context.AuditLogFilter"}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": cfg["console_level"],
                "formatter": "default",
                "filters": ["audit_context"],
            },
            "file": file_handler_config,
        },
        "root": {"level": cfg["level"], "handlers": ["console", "file"]},
    }
    try:
        file_handler_config["filters"] = ["audit_context"]
        logging.config.dictConfig(full_config)
    except (ValueError, OSError, FileNotFoundError):
        from .audit.context import AuditLogFilter

        handler = logging.StreamHandler()
        handler.addFilter(AuditLogFilter())
        handler.setFormatter(logging.Formatter(cfg["format"], cfg["datefmt"]))
        logging.basicConfig(level=cfg["level"], handlers=[handler], force=True)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name)
