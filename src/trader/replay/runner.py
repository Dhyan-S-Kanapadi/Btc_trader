"""Offline loop around the pure replay step function."""

from collections.abc import Sequence
from datetime import UTC
from decimal import Decimal

from trader.config import Settings
from trader.models import Candle, Trade
from trader.risk import AccountState

from .engine import DecisionPolicy, EquityPoint, RecordedDecision, ReplayState, history_window, step


class ReplayResult:
    """Deterministic aggregate returned by an offline replay."""

    def __init__(
        self,
        state: ReplayState,
        trades: list[Trade],
        decisions: list[RecordedDecision],
        equity: list[EquityPoint],
    ) -> None:
        self.state, self.trades, self.decisions, self.equity = (
            state,
            tuple(trades),
            tuple(decisions),
            tuple(equity),
        )


def run_replay(
    candles: Sequence[Candle],
    policy: DecisionPolicy,
    config: Settings,
    account_id: str = "A",
    cash: Decimal = Decimal("10000"),
) -> ReplayResult:
    """Replay candles with bounded history and no I/O, clock, randomness, or persistence."""

    if not candles:
        raise ValueError("candles are required")
    state = ReplayState(
        account_id=account_id,
        cash=cash,
        risk=AccountState(
            account_id=account_id,
            equity=cash,
            peak_equity=cash,
            day_start_equity=cash,
            current_day=candles[0].open_time.astimezone(UTC).date(),
            open_position_count=0,
        ),
    )
    decisions: list[RecordedDecision] = []
    trades: list[Trade] = []
    equity: list[EquityPoint] = []
    bounded = history_window(config)
    for index, candle in enumerate(candles):
        result = step(
            state, candles[max(0, index - bounded + 1) : index + 1], candle, policy, config
        )
        state = result.state
        decisions.extend(result.decisions)
        trades.extend(result.trades)
        equity.append(result.equity_point)
    return ReplayResult(state, trades, decisions, equity)
