"""Add atomic live-worker route checkpoints."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_routed_candles"
down_revision: str | None = "0003_initial_stop_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Track each fully committed account/candle transition."""

    op.create_table(
        "routed_candles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "account_id", sa.String(length=1), sa.ForeignKey("accounts.account_id"), nullable=False
        ),
        sa.Column("candle_id", sa.Uuid(), sa.ForeignKey("candles.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("account_id", "candle_id"),
    )


def downgrade() -> None:
    """Remove live-worker checkpoints."""

    op.drop_table("routed_candles")
