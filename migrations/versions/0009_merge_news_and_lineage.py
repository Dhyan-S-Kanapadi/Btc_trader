"""Merge independent Issue #23 and Issue #25 migration heads."""

from collections.abc import Sequence

revision: str = "0009_merge_news_and_lineage"
down_revision: tuple[str, str] = ("0008_trade_candidate_lineage", "0008_news_ingestion")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
