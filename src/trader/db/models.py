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
    shadow: Mapped[bool] = mapped_column(default=False)
    guardrail_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_call_id: Mapped[UUID | None] = mapped_column(nullable=True)
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
    candidate_idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32))
    qty: Mapped[Decimal] = mapped_column(MONEY)
    entry_price: Mapped[Decimal] = mapped_column(MONEY)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stop_price: Mapped[Decimal] = mapped_column(MONEY)
    initial_stop_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fees: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    reason: Mapped[str] = mapped_column(Text)


class TradeRow(Base):
    """Minimal completed long-only spot trade."""

    __tablename__ = "trades"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    candidate_idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32))
    qty: Mapped[Decimal] = mapped_column(MONEY)
    entry_price: Mapped[Decimal] = mapped_column(MONEY)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stop_price: Mapped[Decimal] = mapped_column(MONEY)
    initial_stop_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
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


class RoutedCandleRow(Base):
    """Durable worker checkpoint: one fully persisted account/candle transition."""

    __tablename__ = "routed_candles"
    __table_args__ = (UniqueConstraint("account_id", "candle_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    candle_id: Mapped[UUID] = mapped_column(ForeignKey("candles.id"))
    phase: Mapped[str] = mapped_column(String(16), default="complete")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentCallRow(Base):
    """Sanitized reusable outcome of one agent request; never contains credentials."""

    __tablename__ = "agent_calls"
    __table_args__ = (UniqueConstraint("request_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_key: Mapped[str] = mapped_column(String(128))
    variant: Mapped[str] = mapped_column(String(64))
    candidate_key: Mapped[str] = mapped_column(String(256))
    snapshot_digest: Mapped[str] = mapped_column(String(128))
    target: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


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


class AgentGlobalControlRow(Base):
    """The singleton operator-owned global agent gate."""

    __tablename__ = "agent_global_controls"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_enabled: Mapped[bool] = mapped_column(default=False)
    kill_switch: Mapped[bool] = mapped_column(default=False)
    jev_enabled: Mapped[bool] = mapped_column(default=False)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    per_candidate_cap: Mapped[Decimal] = mapped_column(MONEY)
    per_day_cap: Mapped[Decimal] = mapped_column(MONEY)


class AgentAccountControlRow(Base):
    """Per-account gate without an account FK, so future accounts can be seeded first."""

    __tablename__ = "agent_account_controls"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_enabled: Mapped[bool] = mapped_column(default=False)
    shadow: Mapped[bool] = mapped_column(default=True)
    kill_switch: Mapped[bool] = mapped_column(default=False)
    memory_enabled: Mapped[bool] = mapped_column(default=False)
    jev_enabled: Mapped[bool] = mapped_column(default=False)
    per_candidate_cap: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    per_day_cap: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    fallback_policy: Mapped[str] = mapped_column(String(32), default="skip_all")


class AgentControlAuditRow(Base):
    """Append-only operator change record, protected by a database trigger."""

    __tablename__ = "agent_control_audit"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor: Mapped[str] = mapped_column(String(256))
    scope: Mapped[str] = mapped_column(String(64))
    field: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[object | None] = mapped_column(JSON, nullable=True)


class NewsPollRow(Base):
    """One bounded source poll; errors contain stable codes only."""

    __tablename__ = "news_polls"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    items_seen: Mapped[int] = mapped_column(default=0)
    items_new: Mapped[int] = mapped_column(default=0)
    duplicates: Mapped[int] = mapped_column(default=0)
    quarantined: Mapped[int] = mapped_column(default=0)
    revisions: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    not_modified: Mapped[bool] = mapped_column(default=False)
    retry_after_seen: Mapped[bool] = mapped_column(default=False)
    etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(512), nullable=True)


class NewsItemRow(Base):
    """Sanitized news input; never stores a raw article body or a secret."""

    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("source_id", "source_item_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(String(64))
    source_item_id: Mapped[str] = mapped_column(String(512))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    flags: Mapped[list[str]] = mapped_column(JSON)
    revision_count: Mapped[int] = mapped_column(default=0)
    duplicate_of: Mapped[UUID | None] = mapped_column(ForeignKey("news_items.id"), nullable=True)
    guardrail_version: Mapped[str] = mapped_column(String(64))
    synthetic: Mapped[bool] = mapped_column(default=False)
    poll_id: Mapped[UUID] = mapped_column(ForeignKey("news_polls.id"))


class JevCallRow(Base):
    """Sanitized Jev audit metadata; no headline text, raw response, or secret."""

    __tablename__ = "jev_calls"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_key: Mapped[str] = mapped_column(String(64), unique=True)
    candidate_idempotency_key: Mapped[str] = mapped_column(String(256))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_hours: Mapped[int] = mapped_column()
    questions_version: Mapped[str] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(64))
    item_ids: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    attempts: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    answers: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str] = mapped_column(String(128))
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 12), nullable=True)
    cost_estimated: Mapped[bool] = mapped_column(default=True)
    price_table_version: Mapped[str] = mapped_column(String(64))
    synthetic: Mapped[bool] = mapped_column(default=False)
