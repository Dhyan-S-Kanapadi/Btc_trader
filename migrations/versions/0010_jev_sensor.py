"""Add isolated Jev sensor audit metadata; no trading-path changes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_jev_sensor"
down_revision: str | None = "0009_merge_news_and_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jev_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(64), nullable=False, unique=True),
        sa.Column("candidate_idempotency_key", sa.String(256), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("questions_version", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("item_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("answers", sa.JSON()),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("cost_usd", sa.Numeric(20, 12)),
        sa.Column("cost_estimated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("price_table_version", sa.String(64), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_jev_calls_created_at", "jev_calls", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_jev_calls_created_at", table_name="jev_calls")
    op.drop_table("jev_calls")
