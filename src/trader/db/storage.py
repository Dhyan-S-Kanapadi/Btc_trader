"""Small SQLAlchemy storage boundary for paper-trading state."""

# ruff: noqa: E501

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from trader.models import Candidate, Candle, Snapshot

from .models import (
    AccountRow,
    AgentAccountControlRow,
    AgentCallRow,
    AgentControlAuditRow,
    AgentGlobalControlRow,
    CandidateRow,
    CandleRow,
    ConfigRow,
    DecisionRow,
    EquityPointRow,
    OrderRow,
    PositionRow,
    RoutedCandleRow,
    RunMetadataRow,
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

    def upsert_candles(self, candles: list[Candle], interval: str) -> int: ...

    def candle_times(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[datetime]: ...

    def latest_candle_time(self, symbol: str, interval: str) -> datetime | None: ...

    def load_candles(
        self, symbol: str, interval: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]: ...

    def account_has_replay_rows(self, account_id: str) -> bool: ...

    def candle_routed_for_accounts(
        self, symbol: str, interval: str, open_time: datetime, account_ids: list[str]
    ) -> bool: ...

    def load_agent_call(self, request_key: str) -> dict[str, object] | None: ...

    def save_agent_call(self, request_key: str, payload: dict[str, object]) -> UUID: ...

    def candle_id(self, symbol: str, interval: str, open_time: datetime) -> UUID: ...

    def candidate_id(self, idempotency_key: str) -> UUID | None: ...

    def decision_exists(self, account_id: str, candidate_key: str) -> bool: ...

    def equity_exists(self, account_id: str, recorded_at: datetime) -> bool: ...

    def trade_exists(self, account_id: str, reason: str, exit_time: datetime) -> bool: ...

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

    def upsert_candles(self, candles: list[Candle], interval: str) -> int:
        """Insert or refresh shared candles by their natural unique key."""

        if not candles:
            return 0
        values = [
            {
                "symbol": candle.symbol,
                "interval": interval,
                "open_time": candle.open_time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
            for candle in candles
        ]
        statement = insert(CandleRow).values(values)
        statement = statement.on_conflict_do_update(
            constraint="candles_symbol_interval_open_time_key",
            set_={
                name: getattr(statement.excluded, name)
                for name in values[0]
                if name != "symbol" and name != "interval" and name != "open_time"
            },
        )
        with self._sessions.begin() as session:
            session.execute(statement)
        return len(candles)

    def candle_times(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[datetime]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(CandleRow.open_time)
                    .where(
                        CandleRow.symbol == symbol,
                        CandleRow.interval == interval,
                        CandleRow.open_time >= start,
                        CandleRow.open_time <= end,
                    )
                    .order_by(CandleRow.open_time)
                )
            )

    def latest_candle_time(self, symbol: str, interval: str) -> datetime | None:
        with self._sessions() as session:
            value = session.scalar(
                select(CandleRow.open_time)
                .where(CandleRow.symbol == symbol, CandleRow.interval == interval)
                .order_by(CandleRow.open_time.desc())
                .limit(1)
            )
        return None if value is None else value.astimezone(UTC)

    def load_candles(
        self, symbol: str, interval: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        """Load shared candles in chronological order for a replay."""

        statement = select(CandleRow).where(
            CandleRow.symbol == symbol, CandleRow.interval == interval
        )
        if start is not None:
            statement = statement.where(CandleRow.open_time >= start)
        if end is not None:
            statement = statement.where(CandleRow.open_time <= end)
        with self._sessions() as session:
            rows = session.scalars(statement.order_by(CandleRow.open_time)).all()
        return [
            Candle(
                symbol=row.symbol,
                open_time=row.open_time.astimezone(UTC),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            )
            for row in rows
        ]

    def account_has_replay_rows(self, account_id: str) -> bool:
        """Return whether replay persistence would mix with existing account state."""

        with self._sessions() as session:
            return any(
                session.scalar(select(model.id).where(model.account_id == account_id).limit(1))
                is not None
                for model in (DecisionRow, OrderRow, PositionRow, TradeRow, EquityPointRow)
            )

    def candle_routed_for_accounts(
        self, symbol: str, interval: str, open_time: datetime, account_ids: list[str]
    ) -> bool:
        """Return whether every enabled account durably completed this candle."""

        if not account_ids:
            return True
        with self._sessions() as session:
            candle_id = session.scalar(
                select(CandleRow.id).where(
                    CandleRow.symbol == symbol,
                    CandleRow.interval == interval,
                    CandleRow.open_time == open_time,
                )
            )
            if candle_id is None:
                return False
            count = session.scalar(
                select(func.count())
                .select_from(RoutedCandleRow)
                .where(
                    RoutedCandleRow.candle_id == candle_id,
                    RoutedCandleRow.account_id.in_(account_ids),
                    RoutedCandleRow.phase == "complete",
                )
            )
            return count == len(account_ids)

    def verify_worker_schema(self) -> None:
        """Fail startup before routing when the worker migration has not been applied."""

        with self._sessions() as session:
            session.execute(select(RoutedCandleRow.id).limit(1))

    def seed_agent_controls(self) -> None:
        """Idempotently create conservative controls; never overwrite operator choices."""

        from trader.control import DEFAULT_PER_CANDIDATE_CAP, DEFAULT_PER_DAY_CAP

        with self._sessions.begin() as session:
            if session.get(AgentGlobalControlRow, 1) is None:
                session.add(
                    AgentGlobalControlRow(
                        id=1,
                        agent_enabled=False,
                        kill_switch=False,
                        per_candidate_cap=DEFAULT_PER_CANDIDATE_CAP,
                        per_day_cap=DEFAULT_PER_DAY_CAP,
                    )
                )
            for account_id in ("B", "C", "D"):
                if session.get(AgentAccountControlRow, account_id) is None:
                    session.add(AgentAccountControlRow(account_id=account_id))

    def load_agent_control(self):
        """Read one immutable control snapshot; callers treat any exception as unreadable."""

        from trader.control import AccountControl, ControlConfig, GlobalControl

        with self._sessions() as session:
            global_row = session.get(AgentGlobalControlRow, 1)
            if global_row is None:
                return ControlConfig()
            accounts = {
                row.account_id: AccountControl(
                    account_id=row.account_id,
                    agent_enabled=row.agent_enabled,
                    shadow=row.shadow,
                    kill_switch=row.kill_switch,
                    per_candidate_cap=row.per_candidate_cap,
                    per_day_cap=row.per_day_cap,
                    fallback_policy=row.fallback_policy,
                )
                for row in session.scalars(select(AgentAccountControlRow))
            }
            return ControlConfig(
                global_control=GlobalControl(
                    agent_enabled=global_row.agent_enabled,
                    kill_switch=global_row.kill_switch,
                    model_version=global_row.model_version,
                    prompt_version=global_row.prompt_version,
                    per_candidate_cap=global_row.per_candidate_cap,
                    per_day_cap=global_row.per_day_cap,
                ),
                accounts=accounts,
            )

    def set_agent_control(self, scope: str, field: str, value: object, actor: str) -> None:
        """Atomically update one allowlisted operator field and append its audit event."""

        global_fields = {
            "agent_enabled",
            "kill_switch",
            "model_version",
            "prompt_version",
            "per_candidate_cap",
            "per_day_cap",
        }
        account_fields = {
            "agent_enabled",
            "shadow",
            "kill_switch",
            "per_candidate_cap",
            "per_day_cap",
            "fallback_policy",
        }
        is_global = scope == "global"
        if field not in (global_fields if is_global else account_fields):
            raise ValueError("field is not allowed")
        with self._sessions.begin() as session:
            if is_global:
                row = session.get(AgentGlobalControlRow, 1)
                if row is None:
                    raise LookupError("global controls are not seeded")
            else:
                row = session.get(AgentAccountControlRow, scope)
                if row is None:
                    row = AgentAccountControlRow(account_id=scope)
                    session.add(row)
                    session.flush()
            old_value = getattr(row, field)
            setattr(row, field, value)
            session.add(
                AgentControlAuditRow(
                    actor=actor,
                    scope=scope,
                    field=field,
                    old_value=str(old_value) if isinstance(old_value, Decimal) else old_value,
                    new_value=value,
                )
            )

    def persist_routed_candle(
        self,
        interval: str,
        candle: Candle,
        results: object,
        reason: str | None = None,
        phase: str = "complete",
    ) -> None:
        """Atomically persist a routed candle, states, evidence, and its durable checkpoints."""

        routed = results  # Kept structural to avoid coupling storage to the pure replay package.
        with self._sessions.begin() as session:
            values = {
                "symbol": candle.symbol,
                "interval": interval,
                "open_time": candle.open_time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
            statement = (
                insert(CandleRow)
                .values(values)
                .on_conflict_do_update(
                    constraint="candles_symbol_interval_open_time_key",
                    set_={
                        name: getattr(insert(CandleRow).excluded, name)
                        for name in values
                        if name not in {"symbol", "interval", "open_time"}
                    },
                )
            )
            session.execute(statement)
            candle_id = session.scalar(
                select(CandleRow.id).where(
                    CandleRow.symbol == candle.symbol,
                    CandleRow.interval == interval,
                    CandleRow.open_time == candle.open_time,
                )
            )
            assert candle_id is not None
            for account_id, result in routed.items():
                for decision in result.decisions:
                    candidate_id = session.scalar(
                        select(CandidateRow.id).where(
                            CandidateRow.idempotency_key == decision.candidate.idempotency_key
                        )
                    )
                    if candidate_id is None:
                        candidate = CandidateRow(
                            candle_id=candle_id, **decision.candidate.model_dump()
                        )
                        session.add(candidate)
                        session.flush()
                        candidate_id = candidate.id
                        session.add(
                            SnapshotRow(
                                candidate_id=candidate_id,
                                schema_version=decision.snapshot.schema_version,
                                snapshot=decision.snapshot.model_dump(mode="json"),
                            )
                        )
                    exists = session.scalar(
                        select(DecisionRow.id).where(
                            DecisionRow.account_id == account_id,
                            DecisionRow.candidate_idempotency_key
                            == decision.candidate.idempotency_key,
                        )
                    )
                    if exists is None:
                        session.add(
                            DecisionRow(
                                account_id=account_id,
                                candidate_id=candidate_id,
                                candidate_idempotency_key=decision.candidate.idempotency_key,
                                action=decision.action,
                                reason=reason or decision.reason,
                                verdict={"risk_code": decision.risk_code}
                                if decision.risk_code is not None
                                else decision.verdict,
                                shadow=decision.shadow,
                                model_version=decision.model_version,
                                prompt_version=decision.prompt_version,
                            )
                        )
                        session.add(
                            OrderRow(
                                account_id=account_id,
                                candidate_id=candidate_id,
                                candidate_idempotency_key=decision.candidate.idempotency_key,
                                side="BUY",
                                qty=Decimal("0"),
                                status="ROUTED",
                                reference_price=decision.candidate.reference_price,
                            )
                        )
                point = result.equity_point
                if (
                    session.scalar(
                        select(EquityPointRow.id).where(
                            EquityPointRow.account_id == account_id,
                            EquityPointRow.recorded_at == point.recorded_at,
                        )
                    )
                    is None
                ):
                    session.add(
                        EquityPointRow(
                            account_id=account_id,
                            recorded_at=point.recorded_at,
                            equity=point.equity,
                        )
                    )
                for trade in result.trades:
                    if (
                        session.scalar(
                            select(TradeRow.id).where(
                                TradeRow.account_id == account_id,
                                TradeRow.reason == trade.reason,
                                TradeRow.exit_time == trade.exit_time,
                            )
                        )
                        is None
                    ):
                        session.add(TradeRow(**trade.model_dump()))
                state = result.state
                row = session.get(AccountRow, account_id)
                if row is None:
                    raise LookupError(f"account does not exist: {account_id}")
                row.cash = state.cash
                row.equity = state.risk.equity
                row.peak_equity = state.risk.peak_equity
                row.halted = state.risk.halted
                row.engine_state = state.model_dump(mode="json")
                if (
                    session.scalar(
                        select(RoutedCandleRow.id).where(
                            RoutedCandleRow.account_id == account_id,
                            RoutedCandleRow.candle_id == candle_id,
                        )
                    )
                    is None
                ):
                    session.add(
                        RoutedCandleRow(
                            account_id=account_id, candle_id=candle_id, phase=phase, reason=reason
                        )
                    )
                else:
                    checkpoint = session.scalar(
                        select(RoutedCandleRow).where(
                            RoutedCandleRow.account_id == account_id,
                            RoutedCandleRow.candle_id == candle_id,
                        )
                    )
                    assert checkpoint is not None
                    checkpoint.phase = phase
                    checkpoint.reason = reason

    def candle_phase_one_for_accounts(
        self, symbol: str, interval: str, open_time: datetime, account_ids: list[str]
    ) -> bool:
        """Return whether the atomic no-agent phase is durable for every account."""

        if not account_ids:
            return True
        with self._sessions() as session:
            candle_id = session.scalar(
                select(CandleRow.id).where(
                    CandleRow.symbol == symbol,
                    CandleRow.interval == interval,
                    CandleRow.open_time == open_time,
                )
            )
            if candle_id is None:
                return False
            count = session.scalar(
                select(func.count())
                .select_from(RoutedCandleRow)
                .where(
                    RoutedCandleRow.candle_id == candle_id,
                    RoutedCandleRow.account_id.in_(account_ids),
                    RoutedCandleRow.phase == "phase_one",
                )
            )
            return count == len(account_ids)

    def load_agent_call(self, request_key: str) -> dict[str, object] | None:
        """Load only completed reusable outcomes; transient failures are never cached."""

        with self._sessions() as session:
            row = session.scalar(
                select(AgentCallRow).where(AgentCallRow.request_key == request_key)
            )
            if row is None or row.result_json is None:
                return None
            return dict(row.result_json)

    def save_agent_call(self, request_key: str, payload: dict[str, object]) -> UUID:
        """Persist a sanitized agent outcome in its own short transaction."""

        with self._sessions.begin() as session:
            row = session.scalar(
                select(AgentCallRow).where(AgentCallRow.request_key == request_key)
            )
            if row is None:
                row = AgentCallRow(
                    request_key=request_key,
                    variant=str(payload["variant"]),
                    candidate_key=str(payload["candidate_key"]),
                    snapshot_digest=str(payload["snapshot_digest"]),
                    target=str(payload["target"]),
                    status=str(payload["status"]),
                    trace_id=(
                        str(payload["trace_id"])
                        if payload.get("trace_id") is not None
                        else None
                    ),
                    result_json=payload,
                )
                session.add(row)
                session.flush()
            return row.id

    def candle_id(self, symbol: str, interval: str, open_time: datetime) -> UUID:
        """Return the durable natural-key candle identifier after an idempotent upsert."""

        with self._sessions() as session:
            value = session.scalar(
                select(CandleRow.id).where(
                    CandleRow.symbol == symbol,
                    CandleRow.interval == interval,
                    CandleRow.open_time == open_time,
                )
            )
        if value is None:
            raise LookupError("candle was not persisted")
        return value

    def candidate_id(self, idempotency_key: str) -> UUID | None:
        """Return a shared candidate by its stable key."""

        with self._sessions() as session:
            return session.scalar(
                select(CandidateRow.id).where(CandidateRow.idempotency_key == idempotency_key)
            )

    def decision_exists(self, account_id: str, candidate_key: str) -> bool:
        """Check per-account candidate idempotency before writing a route result."""

        with self._sessions() as session:
            return (
                session.scalar(
                    select(DecisionRow.id)
                    .where(
                        DecisionRow.account_id == account_id,
                        DecisionRow.candidate_idempotency_key == candidate_key,
                    )
                    .limit(1)
                )
                is not None
            )

    def equity_exists(self, account_id: str, recorded_at: datetime) -> bool:
        """Check the unique equity point key before a re-routed candle writes it again."""

        with self._sessions() as session:
            return (
                session.scalar(
                    select(EquityPointRow.id)
                    .where(
                        EquityPointRow.account_id == account_id,
                        EquityPointRow.recorded_at == recorded_at,
                    )
                    .limit(1)
                )
                is not None
            )

    def trade_exists(self, account_id: str, reason: str, exit_time: datetime) -> bool:
        """Check a completed trade's stable entry key and exit time before recording it again."""

        with self._sessions() as session:
            return (
                session.scalar(
                    select(TradeRow.id)
                    .where(
                        TradeRow.account_id == account_id,
                        TradeRow.reason == reason,
                        TradeRow.exit_time == exit_time,
                    )
                    .limit(1)
                )
                is not None
            )

    def save_run_metadata(self, kind: str, metadata: dict[str, object]) -> UUID:
        """Persist deterministic replay metadata without credentials."""

        with self._sessions.begin() as session:
            row = RunMetadataRow(kind=kind, metadata_json=metadata)
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

    def save_engine_state(self, account_id: str, state: dict[str, object]) -> None:
        """Persist the complete serializable replay state for restart recovery."""

        with self._sessions.begin() as session:
            row = session.get(AccountRow, account_id)
            if row is None:
                raise LookupError(f"account does not exist: {account_id}")
            row.engine_state = state

    def load_engine_state(self, account_id: str) -> dict[str, object] | None:
        """Load serialized replay state without retaining it in process memory."""

        with self._sessions() as session:
            row = session.get(AccountRow, account_id)
            return None if row is None else row.engine_state

    def seed_account(self, account_id: str, cash: Decimal, config: dict[str, object]) -> None:
        """Create a paper account/config only when absent; never overwrite operator changes."""

        with self._sessions.begin() as session:
            if session.get(AccountRow, account_id) is None:
                session.add(
                    AccountRow(
                        account_id=account_id,
                        cash=cash,
                        equity=cash,
                        peak_equity=cash,
                        halted=False,
                    )
                )
            if (
                session.scalar(select(ConfigRow.id).where(ConfigRow.account_id == account_id))
                is None
            ):
                session.add(ConfigRow(account_id=account_id, config=config))

    def load_account_config(self, account_id: str) -> dict[str, object]:
        """Load non-secret account config or fail before routing begins."""

        with self._sessions() as session:
            config = session.scalar(
                select(ConfigRow.config).where(ConfigRow.account_id == account_id)
            )
        if config is None:
            raise LookupError(f"account config does not exist: {account_id}")
        return config

    def load_account_state(self, account_id: str) -> AccountRow | None:
        with self._sessions() as session:
            return session.get(AccountRow, account_id)

    def report_account_ids(self) -> list[str]:
        """List configured paper accounts deterministically for the read-only report job."""

        with self._sessions() as session:
            return list(
                session.scalars(select(AccountRow.account_id).order_by(AccountRow.account_id))
            )

    def load_report_rows(
        self, account_id: str, start: datetime | None, end: datetime | None
    ) -> tuple[
        list[TradeRow],
        list[EquityPointRow],
        list[str],
        tuple[datetime | None, datetime | None],
        int,
        int,
        dict[str, object] | None,
        dict[str, object] | None,
    ]:
        """Load only report inputs; this method deliberately issues SELECT statements only."""

        trade_query = select(TradeRow).where(TradeRow.account_id == account_id)
        equity_query = select(EquityPointRow).where(EquityPointRow.account_id == account_id)
        candidate_query = (
            select(CandidateRow.idempotency_key, CandidateRow.signal_time)
            .join(DecisionRow, DecisionRow.candidate_id == CandidateRow.id)
            .where(DecisionRow.account_id == account_id)
        )
        if start is not None:
            trade_query = trade_query.where(TradeRow.exit_time >= start)
            equity_query = equity_query.where(EquityPointRow.recorded_at >= start)
            candidate_query = candidate_query.where(CandidateRow.signal_time >= start)
        if end is not None:
            trade_query = trade_query.where(TradeRow.exit_time <= end)
            equity_query = equity_query.where(EquityPointRow.recorded_at <= end)
            candidate_query = candidate_query.where(CandidateRow.signal_time <= end)
        with self._sessions() as session:
            trades = session.scalars(trade_query.order_by(TradeRow.exit_time, TradeRow.id)).all()
            equity = session.scalars(equity_query.order_by(EquityPointRow.recorded_at)).all()
            candidates = session.execute(candidate_query.order_by(CandidateRow.signal_time)).all()
            rejected = session.scalar(
                select(func.count())
                .select_from(DecisionRow)
                .where(DecisionRow.account_id == account_id, DecisionRow.action != "TAKE")
            )
            open_positions = session.scalar(
                select(func.count())
                .select_from(PositionRow)
                .where(PositionRow.account_id == account_id, PositionRow.exit_time.is_(None))
            )
            config = session.scalar(
                select(ConfigRow.config).where(ConfigRow.account_id == account_id)
            )
            metadata = session.scalar(
                select(RunMetadataRow.metadata_json)
                .order_by(RunMetadataRow.started_at.desc(), RunMetadataRow.id.desc())
                .limit(1)
            )
        times = [row.signal_time for row in candidates]
        return (
            trades,
            equity,
            [row.idempotency_key for row in candidates],
            (min(times) if times else None, max(times) if times else None),
            int(rejected or 0),
            int(open_positions or 0),
            config,
            metadata,
        )

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
