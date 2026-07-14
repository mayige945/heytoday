"""禁止重聚文章对仓储。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ClusterForbidPair


class ClusterForbidRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, first_id: str, second_id: str, *, reason: str | None = None) -> None:
        article_a_id, article_b_id = sorted((first_id, second_id))
        if article_a_id == article_b_id:
            return
        existing = self.session.get(ClusterForbidPair, (article_a_id, article_b_id))
        if existing is None:
            self.session.add(
                ClusterForbidPair(
                    article_a_id=article_a_id,
                    article_b_id=article_b_id,
                    reason=reason,
                )
            )

    def list_pairs(self) -> frozenset[frozenset[str]]:
        rows = self.session.execute(
            select(ClusterForbidPair.article_a_id, ClusterForbidPair.article_b_id)
        )
        return frozenset(frozenset((first, second)) for first, second in rows)
