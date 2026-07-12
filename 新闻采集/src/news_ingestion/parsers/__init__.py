"""解析器层：通用列表页解析 + 来源特定解析器注册表。"""

from __future__ import annotations

from typing import Callable

from ..config import SourceConfig
from ..types import DiscoveredArticle

ListParser = Callable[[str, str, SourceConfig], list[DiscoveredArticle]]

_REGISTRY: dict[str, ListParser] = {}


def register_list_parser(code: str) -> Callable[[ListParser], ListParser]:
    def decorator(func: ListParser) -> ListParser:
        _REGISTRY[code] = func
        return func

    return decorator


def get_list_parser(code: str) -> ListParser | None:
    return _REGISTRY.get(code)


# 导入来源特定模块以触发注册（按需新增；缺失则回退通用解析）
