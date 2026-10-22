"""Add a durable phase marker before agent-gated entry decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_agent_client_phase"
down_revision: str | None = "0005_agent_control_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Existing completed rows retain their original semantics."""

    op.add_column(
        "routed_candles",
        sa.Column("phase", sa.String(length=16), nullable=False, server_default="complete"),
    )
    op.create_table(
        "agent_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("request_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("variant", sa.String(length=64), nullable=False),
        sa.Column("candidate_key", sa.String(length=256), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.JSON()),
    )
    op.add_column("decisions", sa.Column("guardrail_version", sa.String(length=64)))
    op.add_column("decisions", sa.Column("agent_status", sa.String(length=64)))
    op.add_column("decisions", sa.Column("agent_call_id", sa.Uuid()))


def downgrade() -> None:
    op.drop_column("decisions", "agent_call_id")
    op.drop_column("decisions", "agent_status")
    op.drop_column("decisions", "guardrail_version")
    op.drop_table("agent_calls")
    op.drop_column("routed_candles", "phase")
