"""Persist a trace link only when the agent actually created one."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_agent_call_trace_id"
down_revision: str | None = "0006_agent_client_phase"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_calls", sa.Column("trace_id", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_calls", "trace_id")
