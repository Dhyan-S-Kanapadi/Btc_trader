"""Add explicit opt-in evidence switches for Issue #27 variants."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_variant_gates"
down_revision: str | None = "0010_jev_sensor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_global_controls",
        sa.Column("jev_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "agent_account_controls",
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "agent_account_controls",
        sa.Column("jev_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agent_account_controls", "jev_enabled")
    op.drop_column("agent_account_controls", "memory_enabled")
    op.drop_column("agent_global_controls", "jev_enabled")
