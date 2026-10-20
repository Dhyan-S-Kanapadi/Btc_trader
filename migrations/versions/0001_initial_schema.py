"""Initial paper-trader PostgreSQL schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(30, 12)
UTC = sa.DateTime(timezone=True)


def _id_column() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), primary_key=True, nullable=False)


def upgrade() -> None:
    """Create durable paper-trading state tables."""

    op.create_table(
        "candles",
        _id_column(),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.String(length=16), nullable=False),
        sa.Column("open_time", UTC, nullable=False),
        sa.Column("open", MONEY, nullable=False),
        sa.Column("high", MONEY, nullable=False),
        sa.Column("low", MONEY, nullable=False),
        sa.Column("close", MONEY, nullable=False),
        sa.Column("volume", MONEY, nullable=False),
        sa.UniqueConstraint("symbol", "interval", "open_time"),
    )
    op.create_table(
        "accounts",
        sa.Column("account_id", sa.String(length=1), primary_key=True, nullable=False),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("equity", MONEY, nullable=False),
        sa.Column("peak_equity", MONEY, nullable=False),
        sa.Column("halted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", UTC, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("account_id IN ('A', 'B', 'C', 'D')"),
    )
    op.create_table(
        "run_metadata",
        _id_column(),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("code_version", sa.String(length=128), nullable=True),
        sa.Column("started_at", UTC, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.create_table(
        "candidates",
        _id_column(),
        sa.Column("candle_id", sa.Uuid(), sa.ForeignKey("candles.id"), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("bar_index", sa.Integer(), nullable=False),
        sa.Column("signal_time", UTC, nullable=False),
        sa.Column("reference_price", MONEY, nullable=False),
        sa.Column("atr", MONEY, nullable=False),
        sa.Column("breakout_level", MONEY, nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False, unique=True),
    )
    op.create_table(
        "snapshots",
        _id_column(),
        sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", UTC, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "decisions",
        _id_column(),
        sa.Column(
            "account_id", sa.String(length=1), sa.ForeignKey("accounts.account_id"), nullable=False
        ),
        sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("candidate_idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("verdict", sa.JSON(), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", UTC, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("account_id", "candidate_idempotency_key"),
    )
    op.create_table(
        "orders",
        _id_column(),
        sa.Column(
            "account_id", sa.String(length=1), sa.ForeignKey("accounts.account_id"), nullable=False
        ),
        sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("candidate_idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("qty", MONEY, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reference_price", MONEY, nullable=True),
        sa.Column("filled_price", MONEY, nullable=True),
        sa.Column("filled_time", UTC, nullable=True),
        sa.Column("fees", MONEY, nullable=False, server_default="0"),
        sa.Column("created_at", UTC, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("account_id", "candidate_idempotency_key"),
    )
    op.create_table(
        "positions",
        _id_column(),
        sa.Column(
            "account_id", sa.String(length=1), sa.ForeignKey("accounts.account_id"), nullable=False
        ),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("qty", MONEY, nullable=False),
        sa.Column("entry_price", MONEY, nullable=False),
        sa.Column("entry_time", UTC, nullable=False),
        sa.Column("stop_price", MONEY, nullable=False),
        sa.Column("exit_price", MONEY, nullable=True),
        sa.Column("exit_time", UTC, nullable=True),
        sa.Column("fees", MONEY, nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.create_table(
        "trades",
        _id_column(),
        sa.Column(
            "account_id", sa.String(length=1), sa.ForeignKey("accounts.account_id"), nullable=False
        ),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("qty", MONEY, nullable=False),
        sa.Column("entry_price", MONEY, nullable=False),
        sa.Column("entry_time", UTC, nullable=False),
        sa.Column("stop_price", MONEY, nullable=False),
        sa.Column("exit_price", MONEY, nullable=False),
        sa.Column("exit_time", UTC, nullable=False),
        sa.Column("fees", MONEY, nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.create_table(
        "equity_curve",
        _id_column(),
        sa.Column(
            "account_id", sa.String(length=1), sa.ForeignKey("accounts.account_id"), nullable=False
        ),
        sa.Column("recorded_at", UTC, nullable=False),
        sa.Column("equity", MONEY, nullable=False),
        sa.UniqueConstraint("account_id", "recorded_at"),
    )
    op.create_table(
        "configs",
        _id_column(),
        sa.Column(
            "account_id", sa.String(length=1), sa.ForeignKey("accounts.account_id"), nullable=False
        ),
        sa.Column("config", sa.JSON(), nullable=False, comment="Never store secrets here."),
        sa.Column("updated_at", UTC, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("account_id"),
    )


def downgrade() -> None:
    """Drop the initial schema in dependency order."""

    for table in (
        "configs",
        "equity_curve",
        "trades",
        "positions",
        "orders",
        "decisions",
        "snapshots",
        "candidates",
        "run_metadata",
        "accounts",
        "candles",
    ):
        op.drop_table(table)
