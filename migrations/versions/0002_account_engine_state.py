"""Persist replay engine state per paper account."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_account_engine_state"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add serializable state required to resume an account without in-memory state."""

    op.add_column("accounts", sa.Column("engine_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove the account engine-state document."""

    op.drop_column("accounts", "engine_state")
