"""新闻采集完整运行的唯一工作流定义。"""

from __future__ import annotations

from .contracts import StageDefinition, WorkflowDefinition


NEWS_INGESTION_WORKFLOW = WorkflowDefinition(
    name="news_ingestion.run",
    version="1",
    stages=(
        StageDefinition("fetch", 1, unit="article"),
        StageDefinition("metadata_dedup", 2, unit="article", prerequisites=("fetch",)),
        StageDefinition("classify", 3, unit="article", prerequisites=("metadata_dedup",)),
        StageDefinition("content", 4, unit="article", prerequisites=("classify",)),
        StageDefinition("content_dedup", 5, unit="article", prerequisites=("content",)),
        StageDefinition("cluster", 6, unit="article", prerequisites=("content_dedup",)),
        StageDefinition("score", 7, unit="event", prerequisites=("cluster",)),
        StageDefinition("safety", 8, unit="event", prerequisites=("score",)),
    ),
)

