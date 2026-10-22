"""Add isolated forward-test news ingestion records; no trading table changes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_news_ingestion"
down_revision: str | None = "0007_agent_call_trace_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_polls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quarantined", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revisions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("not_modified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retry_after_seen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("etag", sa.String(512)),
        sa.Column("last_modified", sa.String(512)),
        sa.CheckConstraint("status IN ('ok', 'partial', 'failed')"),
    )
    op.create_table(
        "news_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("source_item_id", sa.String(512), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.String(200)),
        sa.Column("text_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("revision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_of", sa.Uuid(), sa.ForeignKey("news_items.id")),
        sa.Column("guardrail_version", sa.String(64), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("poll_id", sa.Uuid(), sa.ForeignKey("news_polls.id"), nullable=False),
        sa.UniqueConstraint("source_id", "source_item_id", name="uq_news_source_item"),
        sa.CheckConstraint("status IN ('clean', 'flagged', 'quarantined', 'duplicate')"),
    )
    op.create_index("ix_news_items_available", "news_items", ["available_at"])


def downgrade() -> None:
    op.drop_index("ix_news_items_available", table_name="news_items")
    op.drop_table("news_items")
    op.drop_table("news_polls")
