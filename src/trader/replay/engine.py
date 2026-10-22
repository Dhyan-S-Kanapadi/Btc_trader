"""Pure single-account replay engine shared with the future live worker."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import Field

from trader.broker import Fill, cash_change, fill_entry
from trader.config import Settings
from trader.models import Candidate, Candle, FrozenModel, Position, Snapshot, Trade
from trader.risk import AccountState, evaluate_entry, process_candle, roll_day, trade_from_exit
from trader.strategy import atr_at, build_snapshot, evaluate_candle


class PolicyDecision(FrozenModel):
    """A policy action at one candidate; WAIT intentionally has no deferral semantics."""

    action: Literal["TAKE", "SKIP", "WAIT"]
    reason: str = Field(min_length=1)
    verdict: dict[str, object] | None = None
    shadow: bool = False
    model_version: str | None = None
    prompt_version: str | None = None


class DecisionPolicy(Protocol):
    """The small agent-replaceable decision seam."""

    def decide(self, snapshot: Snapshot, candidate: Candidate) -> PolicyDecision: ...


class TakeAllPolicy:
    """Baseline policy that accepts every candidate."""

    def decide(self, snapshot: Snapshot, candidate: Candidate) -> PolicyDecision:
        return PolicyDecision(action="TAKE", reason="take_all")


class VolumeFilterPolicy:
    """Baseline policy accepting only candidates with sufficient snapshot volume ratio."""

    def __init__(self, minimum: Decimal) -> None:
        self.minimum = minimum

    def decide(self, snapshot: Snapshot, candidate: Candidate) -> PolicyDecision:
        if snapshot.volume_ratio is None:
            return PolicyDecision(action="SKIP", reason="volume_ratio_unavailable")
        if snapshot.volume_ratio < self.minimum:
            return PolicyDecision(action="SKIP", reason="volume_ratio_below_minimum")
        return PolicyDecision(action="TAKE", reason="volume_ratio_approved")


class PendingEntry(FrozenModel):
    """A validated signal that may only fill at the following candle open."""

    candidate: Candidate
    snapshot: Snapshot


class SharedSignal(FrozenModel):
    """Account-independent candidate evidence computed once by the router."""

    candidate: Candidate
    snapshot: Snapshot


class ReplayState(FrozenModel):
    """Small immutable state for one account and no external resources."""

    account_id: str = Field(min_length=1)
    cash: Decimal
    position: Position | None = None
    pending_entry: PendingEntry | None = None
    risk: AccountState


class RecordedDecision(FrozenModel):
    """One policy and risk outcome for a candidate."""

    candidate: Candidate
    snapshot: Snapshot
    action: Literal["TAKE", "SKIP", "WAIT"]
    reason: str
    risk_code: str | None = None
    verdict: dict[str, object] | None = None
    shadow: bool = False
    model_version: str | None = None
    prompt_version: str | None = None


class EquityPoint(FrozenModel):
    """End-of-bar marked account equity."""

    recorded_at: datetime
    equity: Decimal


class StepResult(FrozenModel):
    """State and append-only events resulting from exactly one closed candle."""

    state: ReplayState
    decisions: tuple[RecordedDecision, ...] = ()
    fills: tuple[Fill, ...] = ()
    trades: tuple[Trade, ...] = ()
    equity_point: EquityPoint


class PhaseOneResult(FrozenModel):
    """Durable, agent-free portion of a bar transition.

    This deliberately ends before candidate policy evaluation so a worker can
    persist fills, exits and marks for every account before any remote call.
    """

    state: ReplayState
    decisions: tuple[RecordedDecision, ...] = ()
    fills: tuple[Fill, ...] = ()
    trades: tuple[Trade, ...] = ()
    equity_point: EquityPoint


def history_window(config: Settings) -> int:
    """Return enough trailing candles for ATR, breakout and snapshot trend calculations."""

    return max(
        config.strategy.atr_period + 1,
        config.strategy.breakout_lookback + 1,
        config.strategy.trend_sma_period,
    )


def phase_one(
    state: ReplayState,
    history: Sequence[Candle],
    candle: Candle,
    config: Settings,
    data_is_stale: bool = False,
) -> PhaseOneResult:
    """Process fills, exits and marking; this function has no policy or agent path."""

    if not history or history[-1] != candle:
        raise ValueError("history must end with the newly closed candle")
    if candle.symbol != config.strategy.symbol:
        raise ValueError("candle symbol must match strategy symbol")
    cash, position, pending, risk = state.cash, state.position, state.pending_entry, state.risk
    fills: list[Fill] = []
    trades: list[Trade] = []
    decisions: list[RecordedDecision] = []

    # 1. Fill at this bar open and re-size at the actual slippage-adjusted price.
    if pending is not None:
        estimated = candle.open * (Decimal("1") + config.costs.slippage_bps / Decimal("10000"))
        fill_risk = evaluate_entry(
            pending.candidate,
            estimated,
            risk.model_copy(update={"open_position_count": 0}),
            candle.open_time,
            data_is_stale,
            config,
        )
        risk = fill_risk.updated_state
        if (
            fill_risk.approved
            and fill_risk.quantity is not None
            and fill_risk.stop_price is not None
        ):
            entry = fill_entry(fill_risk.quantity, candle, cash, config.costs)
            if isinstance(entry, Fill):
                cash += cash_change(entry)
                fills.append(entry)
                position = Position(
                    account_id=state.account_id,
                    candidate_idempotency_key=pending.candidate.idempotency_key,
                    symbol=candle.symbol,
                    qty=entry.quantity,
                    entry_price=entry.price,
                    entry_time=entry.fill_time,
                    stop_price=fill_risk.stop_price,
                    initial_stop_price=fill_risk.stop_price,
                    fees=entry.fee,
                    reason=pending.candidate.idempotency_key,
                    entry_fee=entry.fee,
                )
                risk = risk.model_copy(update={"open_position_count": 1})
            else:
                decisions.append(
                    RecordedDecision(
                        candidate=pending.candidate,
                        snapshot=pending.snapshot,
                        action="SKIP",
                        reason="entry_unfilled",
                        risk_code=entry.reason_code,
                    )
                )
        else:
            decisions.append(
                RecordedDecision(
                    candidate=pending.candidate,
                    snapshot=pending.snapshot,
                    action="SKIP",
                    reason="fill_time_risk_rejected",
                    risk_code=fill_risk.reason.code,
                )
            )
        pending = None

    # 2. Exit processing includes a newly filled position.
    atr = atr_at(history, len(history) - 1, config.strategy)
    if position is not None:
        exit_result = process_candle(position, candle, atr, config, config.costs)
        if exit_result.exit_fill is not None:
            cash += cash_change(exit_result.exit_fill)
            fills.append(exit_result.exit_fill)
            trades.append(
                trade_from_exit(position, exit_result.exit_fill, exit_result.reason_code or "exit")
            )
            position = None
            risk = risk.model_copy(update={"open_position_count": 0})
        else:
            position = exit_result.position

    # 3 and 4. Mark first, then establish a new UTC day from that first bar mark.
    equity = cash + (position.qty * candle.close if position is not None else Decimal("0"))
    risk = roll_day(risk, equity, candle.open_time)

    return PhaseOneResult(
        state=ReplayState(
            account_id=state.account_id,
            cash=cash,
            position=position,
            pending_entry=pending,
            risk=risk,
        ),
        decisions=tuple(decisions),
        fills=tuple(fills),
        trades=tuple(trades),
        equity_point=EquityPoint(recorded_at=candle.open_time, equity=equity),
    )


def phase_two(
    phase: PhaseOneResult,
    history: Sequence[Candle],
    candle: Candle,
    policy: DecisionPolicy,
    config: Settings,
    signal: SharedSignal | None = None,
    data_is_stale: bool = False,
    allow_entries: bool = True,
) -> StepResult:
    """Apply the candidate decision after phase one has been durably persisted."""

    state = phase.state
    cash, position, pending, risk = state.cash, state.position, state.pending_entry, state.risk
    decisions = list(phase.decisions)
    # Candidate construction uses only the supplied history ending at this candle.
    if signal is None:
        candidate = evaluate_candle(history, len(history) - 1, config.strategy)
        signal = (
            None
            if candidate is None
            else SharedSignal(
                candidate=candidate, snapshot=build_snapshot(history, candidate, config.strategy)
            )
        )
    if signal is not None and allow_entries:
        candidate, snapshot = signal.candidate, signal.snapshot
        policy_decision = policy.decide(snapshot, candidate)
        risk_decision = None
        if policy_decision.action == "TAKE":
            occupied = int(position is not None or pending is not None)
            risk_decision = evaluate_entry(
                candidate,
                candidate.reference_price,
                risk.model_copy(update={"open_position_count": occupied}),
                candle.open_time,
                data_is_stale,
                config,
            )
            risk = risk_decision.updated_state
            if risk_decision.approved:
                pending = PendingEntry(candidate=candidate, snapshot=snapshot)
        decisions.append(
            RecordedDecision(
                candidate=candidate,
                snapshot=snapshot,
                action=policy_decision.action,
                reason=policy_decision.reason,
                risk_code=None if risk_decision is None else risk_decision.reason.code,
                verdict=policy_decision.verdict,
                shadow=policy_decision.shadow,
                model_version=policy_decision.model_version,
                prompt_version=policy_decision.prompt_version,
            )
        )

    return StepResult(
        state=ReplayState(
            account_id=state.account_id,
            cash=cash,
            position=position,
            pending_entry=pending,
            risk=risk,
        ),
        decisions=tuple(decisions),
        fills=phase.fills,
        trades=phase.trades,
        equity_point=phase.equity_point,
    )


def step(
    state: ReplayState,
    history: Sequence[Candle],
    candle: Candle,
    policy: DecisionPolicy,
    config: Settings,
    signal: SharedSignal | None = None,
    data_is_stale: bool = False,
    allow_entries: bool = True,
) -> StepResult:
    """Compose the two pure phases for replay callers that need no persistence boundary."""

    return phase_two(
        phase_one(state, history, candle, config, data_is_stale),
        history,
        candle,
        policy,
        config,
        signal,
        data_is_stale,
        allow_entries,
    )
