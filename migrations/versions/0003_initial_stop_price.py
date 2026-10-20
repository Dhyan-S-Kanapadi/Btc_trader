"""Preserve entry-time stops for post-trade risk reporting."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_initial_stop_price"
down_revision: str | None = "0002_account_engine_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(30, 12)


def upgrade() -> None:
    """Add nullable historical initial-stop columns without rewriting prior paper records."""

    op.add_column("positions", sa.Column("initial_stop_price", MONEY, nullable=True))
    op.add_column("trades", sa.Column("initial_stop_price", MONEY, nullable=True))


def downgrade() -> None:
    """Remove the initial-stop columns."""

    op.drop_column("trades", "initial_stop_price")
    op.drop_column("positions", "initial_stop_price")
