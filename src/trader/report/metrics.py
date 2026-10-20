"""Pure after-cost metrics for closed paper trades and equity points."""

# ruff: noqa: E501

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import mean

from trader.models import Trade


@dataclass(frozen=True)
class EquityPoint:
    """One marked equity value used for return and drawdown calculations."""

    recorded_at: datetime
    equity: Decimal


@dataclass(frozen=True)
class AccountMetrics:
    """Machine-readable metrics; fractions stay fractions rather than percentages."""

    trade_count: int
    open_position_count: int
    total_return: Decimal | None
    max_drawdown: Decimal
    win_rate: Decimal | None
    profit_factor: Decimal | None
    average_r: Decimal | None
    fees_paid: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    average_holding_bars: Decimal | None
    exit_reasons: dict[str, int]
    rejected_candidates: int


def max_drawdown(equity: list[EquityPoint]) -> Decimal:
    """Return the largest peak-to-trough equity decline as a positive fraction of its peak."""

    peak: Decimal | None = None
    result = Decimal("0")
    for point in equity:
        if peak is None or point.equity > peak:
            peak = point.equity
        elif peak > 0:
            result = max(result, (peak - point.equity) / peak)
    return result


def calculate_metrics(
    trades: list[Trade],
    equity: list[EquityPoint],
    open_position_count: int = 0,
    rejected_candidates: int = 0,
    bar_seconds: Decimal | None = None,
) -> AccountMetrics:
    """Calculate documented closed-trade metrics; equity metrics include any unrealized P&L."""

    gross = [trade.qty * (trade.exit_price - trade.entry_price) for trade in trades]
    net = [value - trade.fees for value, trade in zip(gross, trades, strict=True)]
    profits = sum((value for value in net if value > 0), Decimal("0"))
    losses = -sum((value for value in net if value < 0), Decimal("0"))
    risks = [
        net_value / (trade.qty * (trade.entry_price - trade.initial_stop_price))
        for trade, net_value in zip(trades, net, strict=True)
        if trade.entry_price > trade.initial_stop_price
    ]
    holding = (
        [
            Decimal((trade.exit_time - trade.entry_time).total_seconds()) / bar_seconds
            for trade in trades
        ]
        if bar_seconds is not None and bar_seconds > 0
        else []
    )
    start = equity[0].equity if equity else None
    end = equity[-1].equity if equity else None
    return AccountMetrics(
        trade_count=len(trades),
        open_position_count=open_position_count,
        total_return=None if start in (None, Decimal("0")) or end is None else end / start - 1,
        max_drawdown=max_drawdown(equity),
        win_rate=None if not trades else Decimal(sum(value > 0 for value in net)) / len(trades),
        profit_factor=None if losses == 0 else profits / losses,
        average_r=None if not risks else sum(risks) / len(risks),
        fees_paid=sum((trade.fees for trade in trades), Decimal("0")),
        gross_pnl=sum(gross, Decimal("0")),
        net_pnl=sum(net, Decimal("0")),
        average_holding_bars=None if not holding else Decimal(mean(holding)),
        exit_reasons=dict(sorted(Counter(trade.reason for trade in trades).items())),
        rejected_candidates=rejected_candidates,
    )
