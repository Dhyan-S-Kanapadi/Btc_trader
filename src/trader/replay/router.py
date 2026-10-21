"""One-candle multi-account routing over the shared replay engine."""

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from pydantic import Field

from trader.config import Settings
from trader.control import ControlConfig, GatedPolicy, resolve_agent_gate
from trader.db.storage import PostgresStorage
from trader.models import Candle, FrozenModel
from trader.risk import AccountState
from trader.strategy import build_snapshot, evaluate_candle

from .engine import (
    DecisionPolicy,
    PolicyDecision,
    ReplayState,
    SharedSignal,
    StepResult,
    TakeAllPolicy,
    VolumeFilterPolicy,
    step,
)
from .runner import ReplayResult


class AccountConfig(FrozenModel):
    """Non-secret per-account settings stored in the existing configs JSON document."""

    account_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    policy_name: str = Field(min_length=1)
    starting_equity: Decimal = Field(gt=0)
    enabled: bool = True
    risk: dict[str, object] = Field(default_factory=dict)


class SkipAllPolicy:
    """Temporary B-D baseline until Issue #27 provides real policies."""

    def decide(self, snapshot, candidate) -> PolicyDecision:
        return PolicyDecision(action="SKIP", reason="agent not wired yet (#27)")


def policy_for(name: str, settings: Settings) -> DecisionPolicy:
    """Return a configured policy or fail fast while loading account configuration."""

    policies: dict[str, DecisionPolicy] = {
        "take_all": TakeAllPolicy(),
        "skip_all": SkipAllPolicy(),
        "volume_filter": VolumeFilterPolicy(settings.strategy.volume_ratio_min),
    }
    try:
        return policies[name]
    except KeyError as error:
        raise ValueError(f"unknown paper-account policy: {name}") from error


def route_candle(
    accounts: Mapping[str, tuple[ReplayState, AccountConfig]],
    history: Sequence[Candle],
    candle: Candle,
    settings: Settings,
    data_is_stale: bool = False,
    allow_entries: bool = True,
    control: ControlConfig | None = None,
    policies: Mapping[str, DecisionPolicy] | None = None,
) -> dict[str, StepResult]:
    """Route one closed candle independently, sharing exactly one candidate and snapshot."""

    candidate = evaluate_candle(history, len(history) - 1, settings.strategy)
    signal = (
        None
        if candidate is None
        else SharedSignal(
            candidate=candidate, snapshot=build_snapshot(history, candidate, settings.strategy)
        )
    )
    results: dict[str, StepResult] = {}
    logger = logging.getLogger("trader.replay.router")
    for account_id, (state, account) in accounts.items():
        if not account.enabled:
            continue
        try:
            policy = (
                policies.get(account_id)
                if policies is not None
                else policy_for(account.policy_name, settings)
            )
            if policy is None:
                raise ValueError(f"missing policy for account: {account_id}")
            if account_id != "A" and control is not None:
                gate = resolve_agent_gate(control, account_id)
                policy = GatedPolicy(gate, policy, SkipAllPolicy())
            results[account_id] = step(
                state,
                history,
                candle,
                policy,
                settings,
                signal,
                data_is_stale,
                allow_entries,
            )
        except Exception:
            logger.exception("account routing failed", extra={"account_id": account_id})
    return results


def run_routed_replay(
    candles: Sequence[Candle],
    accounts: Mapping[str, tuple[ReplayState, AccountConfig]],
    settings: Settings,
    on_candle: Callable[[Candle, Mapping[str, StepResult]], None] | None = None,
    control: ControlConfig | None = None,
) -> dict[str, ReplayResult]:
    """Replay one shared candle stream through independent account states and policies."""

    if not candles:
        raise ValueError("candles are required")
    states = dict(accounts)
    decisions: dict[str, list] = {account_id: [] for account_id in states}
    trades: dict[str, list] = {account_id: [] for account_id in states}
    equity: dict[str, list] = {account_id: [] for account_id in states}
    bounded = max(
        settings.strategy.atr_period + 1,
        settings.strategy.breakout_lookback + 1,
        settings.strategy.trend_sma_period,
    )
    for index, candle in enumerate(candles):
        results = route_candle(
            states,
            candles[max(0, index - bounded + 1) : index + 1],
            candle,
            settings,
            control=control,
        )
        if on_candle is not None:
            on_candle(candle, results)
        for account_id, result in results.items():
            account = states[account_id][1]
            states[account_id] = (result.state, account)
            decisions[account_id].extend(result.decisions)
            trades[account_id].extend(result.trades)
            equity[account_id].append(result.equity_point)
    return {
        account_id: ReplayResult(
            state, trades[account_id], decisions[account_id], equity[account_id]
        )
        for account_id, (state, _) in states.items()
    }


def load_account_state(storage: PostgresStorage, account: AccountConfig) -> ReplayState:
    """Load all durable engine state, or initialize a newly seeded account deterministically."""

    payload = storage.load_engine_state(account.account_id)
    if payload is not None:
        return ReplayState.model_validate(payload)
    row = storage.load_account_state(account.account_id)
    cash = account.starting_equity if row is None else row.cash
    equity = cash if row is None else row.equity
    peak = cash if row is None else row.peak_equity
    return ReplayState(
        account_id=account.account_id,
        cash=cash,
        risk=AccountState(
            account_id=account.account_id,
            equity=equity,
            peak_equity=peak,
            day_start_equity=equity,
            current_day=date(1970, 1, 1),
            open_position_count=0,
            halted=False if row is None else row.halted,
        ),
    )


def save_account_state(storage: PostgresStorage, state: ReplayState) -> None:
    """Save both queryable account balances and full engine state after each routed bar."""

    storage.save_account_state(
        state.account_id,
        state.cash,
        state.risk.equity,
        state.risk.peak_equity,
        state.risk.halted,
    )
    storage.save_engine_state(state.account_id, state.model_dump(mode="json"))


def persist_routed_candle(
    storage: PostgresStorage,
    interval: str,
    candle: Candle,
    results: Mapping[str, StepResult],
) -> None:
    """Persist one routed bar, writing shared evidence once and account decisions atomically."""

    storage.persist_routed_candle(interval, candle, results)
