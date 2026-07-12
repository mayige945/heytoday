"""来源特定列表页解析器注册表入口。

新增来源专属解析器：在本目录建 ``<code>.py``，用 ``@register_list_parser("<code>")``
装饰 ``parse_list(html, base_url, source) -> list[DiscoveredArticle]``，并在本文件
import 该模块以触发注册。未登记的来源回退到 ``parsers.generic_list.parse_list``。
"""

from __future__ import annotations

# 当前未登记来源专属解析器；通用解析器覆盖简单列表页。
# 示例（接入后取消注释）：
# from . import sspai  # noqa: F401
