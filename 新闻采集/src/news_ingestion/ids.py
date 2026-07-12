"""字符串主键生成。

plan §9 各表 ``id`` 均为字符串。来源表用稳定的 ``code`` 作为主键以保证幂等
种子；文章 / 事件 / 日志等使用本模块生成的时间排序 + 随机后缀 ID，既可排序
又抗碰撞。测试可通过 ``set_id_factory`` 注入确定性生成器。
"""

from __future__ import annotations

import secrets
import time
from typing import Callable

_IdFactory = Callable[[str], str]


def _default_id_factory(prefix: str) -> str:
    timestamp = f"{time.time_ns():x}"[-12:]
    random_suffix = secrets.token_hex(5)
    core = f"{timestamp}{random_suffix}"
    return f"{prefix}_{core}" if prefix else core


_factory: _IdFactory = _default_id_factory


def set_id_factory(factory: _IdFactory | None) -> None:
    """注入自定义 ID 工厂；传 ``None`` 恢复默认。测试用。"""
    global _factory
    _factory = factory or _default_id_factory


def new_id(prefix: str = "") -> str:
    """生成新的字符串 ID。"""
    return _factory(prefix)
