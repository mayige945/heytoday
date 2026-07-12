"""错误类型与固定退出码。

退出码字面值由 plan §15 / CLAUDE.md「必守硬约束 7」锁定，任何改动都属于
契约变更。
"""

from __future__ import annotations

import enum


class ExitCode(enum.IntEnum):
    """CLI 退出码（字面值固定）。"""

    SUCCESS = 0  # 成功，包括合法的空导出
    CONFIG_OR_ARG_ERROR = 2  # 参数或配置校验失败
    ALL_SOURCES_FAILED = 3  # 本次所有启用外部来源均失败
    PARTIAL_SUCCESS = 4  # 部分成功：成功来源已提交，至少一个启用来源失败
    LOCK_CONFLICT = 5  # 进程锁冲突，已有实例运行
    DB_INFRA_FAILURE = 6  # 数据库连接 / 迁移 / 事务基础设施失败
    LLM_CREDS_NOT_CONFIGURED = 7  # 显式 LLM 命令或 run 需要 LLM，但凭据未配置
    SCHEMA_VALIDATION_FAILED = 8  # 人工批准或导出 Schema 校验失败
    BUSINESS_PRECONDITION = 9  # 访问策略拒绝 / 事实核验闸门 / 其它业务前置未满足


class NewsIngestionError(Exception):
    """模块业务错误基类。"""


class FetchError(NewsIngestionError):
    """采集 HTTP 错误基类。"""


class BlockedTargetError(FetchError):
    """SSRF / 非法协议 / 私网目标被拒。"""


class ResponseTooBigError(FetchError):
    """响应体超过 max_bytes。"""


class ContentTypeRejectedError(FetchError):
    """响应 content-type 不在允许列表。"""


class HttpStatusError(FetchError):
    """非重试类 HTTP 状态错误（如 401/403/404）。"""

    def __init__(self, status: int, detail: str = ""):
        super().__init__(f"HTTP {status}: {detail[:200]}")
        self.status = status


class ConfigError(NewsIngestionError):
    """配置或参数校验失败 → 退出码 2。"""


class DbInfraError(NewsIngestionError):
    """数据库连接 / 迁移 / 事务基础设施失败 → 退出码 6。"""


class LockBusyError(NewsIngestionError):
    """进程锁冲突 → 退出码 5。"""


class SchemaValidationError(NewsIngestionError):
    """JSON Schema 校验失败 → 退出码 8。"""


class BusinessPreconditionError(NewsIngestionError):
    """访问策略 / 事实核验闸门 / 其它业务前置未满足 → 退出码 9。"""


class LlmNotConfiguredError(NewsIngestionError):
    """显式 LLM 命令或 run 需要 LLM 但凭据未配置 → 退出码 7。"""
