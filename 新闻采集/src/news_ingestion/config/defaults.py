"""配置默认值：阈值、停用字、追踪参数、媒体后缀、别名词典。

这些是 plan §10 / §11 在代码里落地的「可配置常量」。调整阈值属于配置变更，
必须同步增/更新「应合并/不应合并」测试夹具（plan §10.4）。
"""

from __future__ import annotations

# --- 事件聚类四条件阈值（plan §10.4）---------------------------------------
CLUSTERING_DEFAULTS: dict[str, float | int] = {
    "title_keyword_jaccard": 0.60,
    "entity_overlap_coefficient": 0.80,
    "time_window_hours_general": 72,
    "time_window_hours_ongoing": 7 * 24,
    "time_window_hours_science": 30 * 24,
}

# --- 内容去重（plan §10.3）-------------------------------------------------
CONTENT_DEDUP_DEFAULTS: dict[str, int] = {
    "simhash_hamming_threshold": 3,
    "min_chinese_chars_for_simhash": 200,
    "simhash_hash_bits": 64,
}

# --- URL 追踪 / 分享参数（plan §10.1）--------------------------------------
# 精确匹配移除；utm_ / mc_ / _hs / hsCt / igshid 等按前缀移除。
URL_TRACKING_EXACT: frozenset[str] = frozenset(
    {
        "ref", "ref_src", "ref_url", "referrer",
        "source", "src",
        "ch", "channel",
        "share", "share_source", "share_from", "shared", "sharer",
        "spm",
        "sns",
        "from", "fromCopy", "fromSingleMessage",
        "md", "pd", "tn",
        "fbclid", "gclid", "dclid", "msclkid", "yclid", "twclid",
        "_ga", "_gid", "_gl", "gclsrc",
        "feature", "app", "uc_param_str",
        "timestamp", "ts", "_t", "t",
        "rand", "random",
    }
)
URL_TRACKING_PREFIXES: tuple[str, ...] = ("utm_", "mc_", "_hs", "hsCt", "igshid", "oqid", "scm")

# 无意义锚点片段：命中即丢弃 #fragment
URL_MEANINGLESS_FRAGMENTS: frozenset[str] = frozenset(
    {"", "content", "main", "top", "comments", "comment", "reply", "share", "read-more", "more"}
)

# --- 标题去重（plan §10.2）-------------------------------------------------
# 媒体后缀：标题末尾出现的媒体名 / 栏目名，归一时去除。
MEDIA_SUFFIXES: tuple[str, ...] = (
    "少数派", "sspai",
    "澎湃新闻", "澎湃", "thepaper",
    "界面新闻", "界面",
    "极客公园", "geepark",
    "果壳", "guokr",
    "Solidot", "solidot",
    "少年報導者", "少年报导者",
    "NASA", "MIT News", "Smithsonian", "BBC", "Guardian", "The Conversation",
    "知乎", "B站", "哔哩哔哩", "bilibili",
)

# 重复标点压缩：连续重复标点压成单个
TITLE_PUNCTUATION = "。，、；：？！…—·.,;:?!~-"

# --- 中文关键词停用字（plan §10.4 连续二元字组去停用字）---------------------
CHINESE_STOP_CHARS: frozenset[str] = frozenset(
    "的了是在和与及或等对为把被让使这那一上个们上下中里也都又还就只"
    "而但却由从到向于以其之此该各每某么呢吧啊呀哦嗯地得着过来到去回给同"
    "并你我他她它个位种类件名次号点节项组批场处所时地人事物我你他她它们"
    "将已曾正将要刚刚刚已即将被把让使令请愿欲以之其此那个这个些么怎哪谁"
    "吗呢吧啊哦嗯哈呵呃哎"
)

# 拉丁停用词（小写）
LATIN_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
        "with", "at", "by", "from", "as", "is", "are", "was", "were", "be",
        "been", "being", "this", "that", "these", "those", "it", "its",
        "into", "over", "after", "new", "says", "said", "will", "can",
    }
)

# --- 实体别名词典（plan §10.4 实体经别名归一）------------------------------
# alias → canonical；聚类前把实体先映射到规范名。
ALIAS_DICT: dict[str, str] = {
    "马斯克": "马斯克",
    "Elon Musk": "马斯克",
    "NASA": "NASA",
    "美国宇航局": "NASA",
    "美国航天局": "NASA",
    "SpaceX": "SpaceX",
    "太空探索技术公司": "SpaceX",
    "OpenAI": "OpenAI",
    "ChatGPT": "ChatGPT",
    "苹果": "苹果",
    "Apple": "苹果",
    "谷歌": "谷歌",
    "Google": "谷歌",
    "微软": "微软",
    "Microsoft": "微软",
    "B站": "哔哩哔哩",
    "哔哩哔哩": "哔哩哔哩",
    "bilibili": "哔哩哔哩",
    "知乎": "知乎",
}

# --- HTTP 采集约束默认值 ----------------------------------------------------
HTTP_DEFAULTS: dict[str, int | float | str] = {
    "request_interval_seconds": 5.0,
    "max_concurrency_per_host": 1,
    "timeout_seconds": 20.0,
    "max_redirects": 5,
    "max_response_bytes": 5_000_000,
    # HTTP 头必须为 latin-1 可编码（ASCII）；项目名用拼音，中文不可放入 UA。
    "user_agent": "WeiJinTian-NewsIngestion/0.1 (+https://github.com/mayige945/heytoday; local MVP)",
}

ALLOWED_CONTENT_TYPES_DEFAULT: tuple[str, ...] = (
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/json",
    "text/plain",
)

# --- 运行期 ----------------------------------------------------------------
RUNTIME_DEFAULTS: dict[str, int] = {
    "busy_timeout_ms": 5000,
    "stale_run_recovery_minutes": 30,
    "llm_max_retries": 2,
    "llmlight_max_tokens": 512,
    "llmfull_max_tokens": 2048,
}

# 热点雷达 unit_code（plan §4.1）
TREND_RADAR_UNIT_CODE = "S14"
TREND_RADAR_CATEGORY = "trend_radar"
