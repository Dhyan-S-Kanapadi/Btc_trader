"""SQLAlchemy mappings for durable paper-trading state."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

MONEY = Numeric(30, 12)


class Base(DeclarativeBase):
    """Base for the paper-trader database mappings."""


class CandleRow(Base):
    """Shared market candle."""

    __tablename__ = "candles"
    __table_args__ = (UniqueConstraint("symbol", "interval", "open_time"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    symbol: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(16))
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[Decimal] = mapped_column(MONEY)
    high: Mapped[Decimal] = mapped_column(MONEY)
    low: Mapped[Decimal] = mapped_column(MONEY)
    close: Mapped[Decimal] = mapped_column(MONEY)
    volume: Mapped[Decimal] = mapped_column(MONEY)


class CandidateRow(Base):
    """Idempotent signal candidate linked to its source candle."""

    __tablename__ = "candidates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candle_id: Mapped[UUID] = mapped_column(ForeignKey("candles.id"))
    symbol: Mapped[str] = mapped_column(String(32))
    bar_index: Mapped[int] = mapped_column()
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reference_price: Mapped[Decimal] = mapped_column(MONEY)
    atr: Mapped[Decimal] = mapped_column(MONEY)
    breakout_level: Mapped[Decimal] = mapped_column(MONEY)
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True)


class SnapshotRow(Base):
    """Versioned JSON evidence for a candidate."""

    __tablename__ = "snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"))
    schema_version: Mapped[int] = mapped_column()
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountRow(Base):
    """Per-account paper state."""

    __tablename__ = "accounts"
    __table_args__ = (CheckConstraint("account_id IN ('A', 'B', 'C', 'D')"),)

    account_id: Mapped[str] = mapped_column(String(1), primary_key=True)
    cash: Mapped[Decimal] = mapped_column(MONEY)
    equity: Mapped[Decimal] = mapped_column(MONEY)
    peak_equity: Mapped[Decimal] = mapped_column(MONEY)
    halted: Mapped[bool] = mapped_column(default=False)
    engine_state: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DecisionRow(Base):
    """Per-account verdict for a candidate."""

    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("account_id", "candidate_idempotency_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"))
    candidate_idempotency_key: Mapped[str] = mapped_column(String(256))
    action: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str] = mapped_column(Text)
    verdict: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderRow(Base):
    """Minimal paper-broker order record."""

    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("account_id", "candidate_idempotency_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"))
    candidate_idempotency_key: Mapped[str] = mapped_column(String(256))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(32))
    reference_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    filled_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    filled_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fees: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PositionRow(Base):
    """Minimal per-account long-only spot position."""

    __tablename__ = "positions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    symbol: Mapped[str] = mapped_column(String(32))
    qty: Mapped[Decimal] = mapped_column(MONEY)
    entry_price: Mapped[Decimal] = mapped_column(MONEY)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stop_price: Mapped[Decimal] = mapped_column(MONEY)
    exit_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fees: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    reason: Mapped[str] = mapped_column(Text)


class TradeRow(Base):
    """Minimal completed long-only spot trade."""

    __tablename__ = "trades"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    symbol: Mapped[str] = mapped_column(String(32))
    qty: Mapped[Decimal] = mapped_column(MONEY)
    entry_price: Mapped[Decimal] = mapped_column(MONEY)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stop_price: Mapped[Decimal] = mapped_column(MONEY)
    exit_price: Mapped[Decimal] = mapped_column(MONEY)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fees: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    reason: Mapped[str] = mapped_column(Text)


class EquityPointRow(Base):
    """Per-account equity time series point."""

    __tablename__ = "equity_curve"
    __table_args__ = (UniqueConstraint("account_id", "recorded_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    equity: Mapped[Decimal] = mapped_column(MONEY)


class ConfigRow(Base):
    """Per-account non-secret configuration snapshot."""

    __tablename__ = "configs"
    __table_args__ = (UniqueConstraint("account_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    # Never write credentials, tokens, or exchange keys to this JSON document.
    config: Mapped[dict[str, object]] = mapped_column(JSON, comment="Never store secrets here.")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RunMetadataRow(Base):
    """Versioned process-run metadata."""

    __tablename__ = "run_metadata"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(64))
    code_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
