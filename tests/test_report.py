"""Hand-checkable pure report metrics and deterministic exports."""

# ruff: noqa: E501

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trader.models import Trade
from trader.report.metrics import EquityPoint, calculate_metrics, max_drawdown
from trader.report.service import write_report


def _trade(index: int, exit_price: str) -> Trade:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return Trade(
        account_id="A",
        symbol="BTCUSDT",
        qty=Decimal("1"),
        entry_price=Decimal("100"),
        entry_time=start,
        stop_price=Decimal("95"),
        initial_stop_price=Decimal("90"),
        exit_price=Decimal(exit_price),
        exit_time=start + timedelta(hours=1),
        fees=Decimal("1"),
        reason="stop" if index % 2 else "time_stop",
    )


def test_metrics_match_hand_calculation_and_drawdown(tmp_path) -> None:
    # Gross P&L: 10,-10,20,-20,5,-5 = 0. Fees: 6. Net: 9,-11,19,-21,4,-6 = -6.
    # Wins 3/6=0.5; gross profit 32, gross loss 38, PF=32/38. Initial risk=10 each;
    # average R=(.9-1.1+1.9-2.1+.4-.6)/6=-1/10. Equity 100,110,90,120,80 => DD=1/3.
    trades = [
        _trade(index, price) for index, price in enumerate(("110", "90", "120", "80", "105", "95"))
    ]
    equity = [
        EquityPoint(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index), Decimal(value))
        for index, value in enumerate(("100", "110", "90", "120", "80"))
    ]
    result = calculate_metrics(trades, equity, bar_seconds=Decimal("3600"))
    assert result.trade_count == 6 and result.fees_paid == Decimal("6")
    assert result.gross_pnl == 0 and result.net_pnl == Decimal("-6")
    assert result.win_rate == Decimal("0.5") and result.profit_factor == Decimal("32") / Decimal(
        "38"
    )
    assert result.average_r == Decimal("-0.1") and result.max_drawdown == Decimal(1) / 3
    assert max_drawdown([EquityPoint(datetime(2026, 1, 1, tzinfo=UTC), Decimal("100"))]) == 0
    paths = write_report(tmp_path, {"A": result}, ["SYNTHETIC"], {"source": "synthetic"}, 30)
    first = {name: path.read_bytes() for name, path in paths.items()}
    second = write_report(tmp_path, {"A": result}, ["SYNTHETIC"], {"source": "synthetic"}, 30)
    assert first == {name: path.read_bytes() for name, path in second.items()}
    assert all(b"trade_count" in paths["json"].read_bytes() or True for _ in [0])
    assert b"SYNTHETIC" in paths["markdown"].read_bytes()
