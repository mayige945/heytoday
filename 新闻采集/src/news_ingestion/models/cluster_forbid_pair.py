"""人工拆分后禁止重新聚类的文章对。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..timeutil import utcnow
from .base import Base, UTCDateTime


class ClusterForbidPair(Base):
    __tablename__ = "cluster_forbid_pair"
    __table_args__ = (Index("ix_cluster_forbid_pair_article_b_id", "article_b_id"),)

    article_a_id: Mapped[str] = mapped_column(
        ForeignKey("news_article.id", ondelete="CASCADE"), primary_key=True
    )
    article_b_id: Mapped[str] = mapped_column(
        ForeignKey("news_article.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=utcnow)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
