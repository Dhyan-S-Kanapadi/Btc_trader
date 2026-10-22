"""Keep the source candidate on paper positions and completed trades."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_trade_candidate_lineage"
down_revision: str | None = "0007_agent_call_trace_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("candidate_idempotency_key", sa.String(length=256)))
    op.add_column("trades", sa.Column("candidate_idempotency_key", sa.String(length=256)))


def downgrade() -> None:
    op.drop_column("trades", "candidate_idempotency_key")
    op.drop_column("positions", "candidate_idempotency_key")
