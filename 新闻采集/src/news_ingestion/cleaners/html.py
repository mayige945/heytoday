"""HTML → 纯文本通用清洗（plan §6.2）。

用标准库 ``html.parser.HTMLParser`` 实现，移除脚本 / 样式 / 导航 / 广告 / 推荐等
噪声，只保留可见正文。来源特定解析规则放在 ``parsers/sources/`` 中，可覆盖。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# 整块丢弃的标签
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "nav", "footer", "header", "aside", "form",
     "button", "svg", "iframe", "template", "figure", "figcaption"}
)
# 块级标签：结束后补换行，帮助分段
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
     "section", "article", "blockquote", "tr", "td", "th", "hr", "pre", "table"}
)
# 常见广告 / 推荐容器 class 关键词（命中即丢弃该块文本）
_AD_CLASS_HINTS = ("ad", "advert", "promo", "recommend", "related", "comment",
                   "share", "newsletter", "subscribe", "breadcrumb", "sidebar",
                   "popup", "modal", "cookie", "paywall")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pieces: list[str] = []
        self._skip_depth = 0
        self._ad_stack: list[bool] = []

    def handle_starttag(self, tag, attrs):  # type: ignore[override]
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        classes = dict(attrs).get("class", "") or ""
        is_ad = any(hint in classes.lower() for hint in _AD_CLASS_HINTS)
        self._ad_stack.append(is_ad)
        if tag == "br":
            self._pieces.append("\n")

    def handle_endtag(self, tag):  # type: ignore[override]
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self._ad_stack:
            self._ad_stack.pop()
        if tag in _BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_data(self, data):  # type: ignore[override]
        if self._skip_depth > 0:
            return
        if any(self._ad_stack):
            return
        text = data.strip()
        if text:
            self._pieces.append(text)

    def get_text(self) -> str:
        raw = "\n".join(self._pieces)
        # 合并被拆散的换行与多余空白
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str | None) -> str:
    """把 HTML 转为纯文本，去除脚本 / 样式 / 导航 / 广告等噪声。"""
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # HTML 异常不应中断采集链路（plan §16.5）；返回已收集部分
        pass
    return parser.get_text()


def extract_title(html: str | None) -> str | None:
    """粗提取 <title>，来源特定解析可覆盖。"""
    if not html:
        return None
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    text = re.sub(r"\s+", " ", match.group(1)).strip()
    return text or None
