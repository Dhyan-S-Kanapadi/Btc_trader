"""Add fail-closed operator controls for agent-gated paper accounts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_agent_control_plane"
down_revision: str | None = "0004_routed_candles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create controls/audit tables and mark shadow decisions without touching risk state."""

    shadow_column = sa.Column("shadow", sa.Boolean(), nullable=False, server_default=sa.false())
    op.add_column("decisions", shadow_column)
    op.create_table(
        "agent_global_controls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kill_switch", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_version", sa.String(length=128)),
        sa.Column("prompt_version", sa.String(length=128)),
        sa.Column("per_candidate_cap", sa.Numeric(30, 12), nullable=False),
        sa.Column("per_day_cap", sa.Numeric(30, 12), nullable=False),
        sa.CheckConstraint("id = 1"),
    )
    op.create_table(
        "agent_account_controls",
        sa.Column("account_id", sa.String(length=64), primary_key=True),
        sa.Column("agent_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shadow", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("kill_switch", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("per_candidate_cap", sa.Numeric(30, 12)),
        sa.Column("per_day_cap", sa.Numeric(30, 12)),
        sa.Column(
            "fallback_policy", sa.String(length=32), nullable=False, server_default="skip_all"
        ),
    )
    op.create_table(
        "agent_control_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("actor", sa.String(length=256), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.JSON()),
        sa.Column("new_value", sa.JSON()),
    )
    op.execute("""
        CREATE FUNCTION reject_agent_control_audit_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'agent control audit is append-only'; END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER agent_control_audit_append_only
        BEFORE UPDATE OR DELETE ON agent_control_audit
        FOR EACH ROW EXECUTE FUNCTION reject_agent_control_audit_mutation();
    """)


def downgrade() -> None:
    """Remove the isolated controls schema cleanly."""

    op.execute("DROP TRIGGER agent_control_audit_append_only ON agent_control_audit")
    op.execute("DROP FUNCTION reject_agent_control_audit_mutation()")
    op.drop_table("agent_control_audit")
    op.drop_table("agent_account_controls")
    op.drop_table("agent_global_controls")
    op.drop_column("decisions", "shadow")
