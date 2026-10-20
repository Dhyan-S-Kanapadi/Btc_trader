"""Small SQLAlchemy storage boundary for paper-trading state."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from trader.models import Candidate, Candle, Snapshot

from .models import (
    AccountRow,
    CandidateRow,
    CandleRow,
    DecisionRow,
    EquityPointRow,
    OrderRow,
    PositionRow,
    SnapshotRow,
    TradeRow,
)


@dataclass(frozen=True)
class DecisionWrite:
    """The persisted fields for one candidate verdict."""

    account_id: str
    candidate_id: UUID
    candidate_idempotency_key: str
    action: str
    reason: str
    verdict: dict[str, object] | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class OrderWrite:
    """The minimal fields required for a future paper-broker order."""

    account_id: str
    candidate_id: UUID
    candidate_idempotency_key: str
    side: str
    qty: Decimal
    status: str
    reference_price: Decimal | None = None
    filled_price: Decimal | None = None
    filled_time: datetime | None = None
    fees: Decimal = Decimal("0")


class PaperStorage(Protocol):
    """Purpose-specific persistence operations used by future paper-trading issues."""

    def save_candle(self, candle: Candle, interval: str) -> UUID: ...

    def save_candidate(self, candidate: Candidate, candle_id: UUID) -> UUID: ...

    def save_snapshot(self, candidate_id: UUID, snapshot: Snapshot) -> UUID: ...

    def save_account_state(
        self,
        account_id: str,
        cash: Decimal,
        equity: Decimal,
        peak_equity: Decimal,
        halted: bool = False,
    ) -> None: ...

    def save_decision_and_order(
        self, decision: DecisionWrite, order: OrderWrite
    ) -> tuple[UUID, UUID]: ...

    def save_position(self, position: PositionRow) -> UUID: ...

    def save_trade(self, trade: TradeRow) -> UUID: ...

    def save_equity_point(
        self, account_id: str, recorded_at: datetime, equity: Decimal
    ) -> UUID: ...

    def load_account_state(self, account_id: str) -> AccountRow | None: ...


class PostgresStorage:
    """PostgreSQL implementation with transactions scoped to each write operation."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    def save_candle(self, candle: Candle, interval: str) -> UUID:
        with self._sessions.begin() as session:
            row = CandleRow(
                symbol=candle.symbol,
                interval=interval,
                open_time=candle.open_time,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )
            session.add(row)
            session.flush()
            return row.id

    def save_candidate(self, candidate: Candidate, candle_id: UUID) -> UUID:
        with self._sessions.begin() as session:
            row = CandidateRow(candle_id=candle_id, **candidate.model_dump())
            session.add(row)
            session.flush()
            return row.id

    def save_snapshot(self, candidate_id: UUID, snapshot: Snapshot) -> UUID:
        with self._sessions.begin() as session:
            row = SnapshotRow(
                candidate_id=candidate_id,
                schema_version=snapshot.schema_version,
                snapshot=snapshot.model_dump(mode="json"),
            )
            session.add(row)
            session.flush()
            return row.id

    def save_account_state(
        self,
        account_id: str,
        cash: Decimal,
        equity: Decimal,
        peak_equity: Decimal,
        halted: bool = False,
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(AccountRow, account_id)
            if row is None:
                session.add(
                    AccountRow(
                        account_id=account_id,
                        cash=cash,
                        equity=equity,
                        peak_equity=peak_equity,
                        halted=halted,
                    )
                )
            else:
                row.cash, row.equity, row.peak_equity, row.halted = (
                    cash,
                    equity,
                    peak_equity,
                    halted,
                )

    def load_account_state(self, account_id: str) -> AccountRow | None:
        with self._sessions() as session:
            return session.get(AccountRow, account_id)

    def save_decision_and_order(
        self, decision: DecisionWrite, order: OrderWrite
    ) -> tuple[UUID, UUID]:
        """Write both records in one transaction or roll back both on any failure."""

        if (decision.account_id, decision.candidate_id, decision.candidate_idempotency_key) != (
            order.account_id,
            order.candidate_id,
            order.candidate_idempotency_key,
        ):
            raise ValueError("decision and order must describe the same account and candidate")
        with self._sessions.begin() as session:
            decision_row = DecisionRow(**decision.__dict__)
            order_row = OrderRow(**order.__dict__)
            session.add_all((decision_row, order_row))
            session.flush()
            return decision_row.id, order_row.id

    def save_position(self, position: PositionRow) -> UUID:
        with self._sessions.begin() as session:
            session.add(position)
            session.flush()
            return position.id

    def save_trade(self, trade: TradeRow) -> UUID:
        with self._sessions.begin() as session:
            session.add(trade)
            session.flush()
            return trade.id

    def save_equity_point(self, account_id: str, recorded_at: datetime, equity: Decimal) -> UUID:
        with self._sessions.begin() as session:
            row = EquityPointRow(account_id=account_id, recorded_at=recorded_at, equity=equity)
            session.add(row)
            session.flush()
            return row.id

    def decision_count(self, account_id: str, candidate_key: str) -> int:
        """Return a narrow verification query used by database tests."""

        with self._sessions() as session:
            return len(
                session.scalars(
                    select(DecisionRow).where(
                        DecisionRow.account_id == account_id,
                        DecisionRow.candidate_idempotency_key == candidate_key,
                    )
                ).all()
            )
