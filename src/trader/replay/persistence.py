"""Database boundary for replay callers; the pure engine never imports this module."""

from decimal import Decimal

from trader.db.models import PositionRow, TradeRow
from trader.db.storage import DecisionWrite, OrderWrite, PostgresStorage
from trader.models import Candle

from .runner import ReplayResult


def refuse_nonempty_account(storage: PostgresStorage, account_id: str) -> None:
    """Prevent a replay from mixing its rows with prior live or replay account data."""

    if storage.account_has_replay_rows(account_id):
        raise ValueError("--persist requires an empty scratch-database account")


def persist_replay(
    storage: PostgresStorage,
    candles: list[Candle],
    interval: str,
    result: ReplayResult,
    metadata: dict[str, object],
) -> None:
    """Persist one already-computed replay through the existing transactional storage operations."""

    state = result.state
    storage.save_account_state(
        state.account_id, state.cash, state.risk.equity, state.risk.peak_equity, state.risk.halted
    )
    storage.upsert_candles(candles, interval)
    persisted: set[str] = set()
    for decision in result.decisions:
        key = decision.candidate.idempotency_key
        if key in persisted:
            continue
        persisted.add(key)
        candidate_id = storage.save_candidate(
            decision.candidate,
            storage.candle_id(decision.candidate.symbol, interval, decision.candidate.signal_time),
        )
        storage.save_snapshot(candidate_id, decision.snapshot)
        storage.save_decision_and_order(
            DecisionWrite(
                state.account_id,
                candidate_id,
                key,
                decision.action,
                decision.reason,
                verdict={"risk_code": decision.risk_code} if decision.risk_code else None,
            ),
            OrderWrite(
                state.account_id,
                candidate_id,
                key,
                "BUY",
                Decimal("0"),
                "REPLAY_RECORDED",
                reference_price=decision.candidate.reference_price,
            ),
        )
    for trade in result.trades:
        storage.save_trade(TradeRow(**trade.model_dump()))
    for point in result.equity:
        storage.save_equity_point(state.account_id, point.recorded_at, point.equity)
    if state.position is not None:
        storage.save_position(PositionRow(**state.position.model_dump()))
    storage.save_run_metadata(
        "SYNTHETIC_REPLAY" if metadata.get("source") == "synthetic" else "REPLAY", metadata
    )
