"""Worker scheduling tests without network, agents, news, or model dependencies."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from trader.config import Settings
from trader.models import Candle
from trader.worker import WorkerLock, run_cycle


def _candle(hour: int) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        open_time=datetime(2026, 1, 1, hour, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )


class _Storage:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.persisted: list[tuple[datetime, str | None]] = []

    def load_candles(self, *_args):
        return self.candles

    def candle_routed_for_accounts(self, *_args):
        return False

    def persist_routed_candle(self, _interval, candle, _results, reason=None):
        self.persisted.append((candle.open_time, reason))


def test_catchup_routes_in_order_and_marks_old_candles_without_entries(monkeypatch) -> None:
    storage = _Storage([_candle(hour) for hour in range(5)])
    calls: list[tuple[datetime, bool]] = []

    def route(accounts, history, candle, settings, stale, allow_entries=True):
        calls.append((candle.open_time, allow_entries))
        return {
            account_id: SimpleNamespace(
                state=state,
                decisions=(),
                trades=(),
                equity_point=SimpleNamespace(
                    recorded_at=candle.open_time, equity=state.risk.equity
                ),
            )
            for account_id, (state, _account) in accounts.items()
        }

    monkeypatch.setattr("trader.worker.route_candle", route)
    monkeypatch.setattr(
        "trader.worker.latest_freshness", lambda *_args: SimpleNamespace(stale=False)
    )
    state = SimpleNamespace(risk=SimpleNamespace(equity=Decimal("10000")), position=None)
    accounts = {"A": (state, SimpleNamespace())}

    result = run_cycle(storage, accounts, Settings(), datetime(2026, 1, 1, 5, tzinfo=UTC))

    assert [time for time, _ in calls] == [candle.open_time for candle in storage.candles]
    assert [allowed for _, allowed in calls] == [False, False, False, True, True]
    assert [reason for _, reason in storage.persisted] == [
        "stale_catchup",
        "stale_catchup",
        "stale_catchup",
        None,
        None,
    ]
    assert result.routed_candle_count == 5


def test_worker_lock_fails_fast_and_reports_connection_loss() -> None:
    class Connection:
        closed = False

        def __init__(self) -> None:
            self.available = True

        def scalar(self, statement, params=None):
            if not self.available:
                raise RuntimeError("connection lost")
            return True

        def execute(self, *_args):
            return None

        def close(self):
            self.closed = True

    connection = Connection()
    storage = SimpleNamespace(_engine=SimpleNamespace(connect=lambda: connection))
    first = WorkerLock(storage, 7)
    assert first.acquire()
    assert first.healthy()
    connection.available = False
    assert not first.healthy()
    first.close()
    assert connection.closed
