"""喂今天 · 新闻采集模块（Content Intelligence 层）。

本模块是「喂今天」当前唯一获准独立工程化的子模块。它通过人工触发的
``news-ingestion`` CLI，把 RSS、网页栏目与 RSSHub 材料处理成带来源、
事实核验、年龄适配和安全分级的「新闻素材库」（v0.5：宽口径素材池，采集阶段只挡红线），停在可选人工策展队列。

约束与边界见 ``新闻采集/CLAUDE.md`` 与 ``news-source-ingestion-plan-v0.4.md``。
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
