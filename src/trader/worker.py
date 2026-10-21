"""Single-process, paper-only worker scheduling around existing ingestion and routing."""

import inspect
import logging
import signal
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import text

from trader.config import Settings
from trader.control import ControlConfig, resolve_agent_gate
from trader.data.binance import BinanceIngestor, interval_delta, latest_freshness
from trader.db.storage import PostgresStorage
from trader.logging import configure_logging
from trader.replay import AccountConfig, load_account_state, route_candle


class Clock(Protocol):
    """Injectable source of UTC time and interruptible sleeping."""

    def now(self) -> datetime: ...
    def sleep_until(self, target: datetime) -> None: ...


class RealClock:
    """Production clock; worker logic itself never calls datetime.now or time.sleep."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep_until(self, target: datetime) -> None:
        self._interrupted.wait(max(0, (target - self.now()).total_seconds()))
        self._interrupted.clear()

    def interrupt(self) -> None:
        """Wake a waiting worker after SIGTERM/SIGINT without touching persistence."""

        self._interrupted.set()


class WorkerLock:
    """Dedicated session advisory lock; a failed heartbeat means the worker must stop."""

    def __init__(self, storage: PostgresStorage, key: int) -> None:
        self.connection = storage._engine.connect()
        self.key = key

    def acquire(self) -> bool:
        return bool(
            self.connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key})
        )

    def healthy(self) -> bool:
        try:
            return bool(self.connection.scalar(text("SELECT 1")))
        except Exception:
            return False

    def close(self) -> None:
        try:
            if not self.connection.closed:
                self.connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
        finally:
            self.connection.close()


@dataclass(frozen=True)
class CycleResult:
    processed_candle_time: datetime | None
    routed_candle_count: int
    stale: bool
    equity: dict[str, str]
    open_positions: dict[str, bool]
    agent_gates: dict[str, str]


def run_cycle(storage: PostgresStorage, accounts, settings: Settings, now: datetime) -> CycleResult:
    """Fetch closed public candles, then route unpersisted candles in chronological order."""

    try:
        control = storage.load_agent_control()
    except Exception:
        logging.getLogger("trader.worker").exception(
            "control plane unreadable", extra={"alarm": "control_plane_unreadable"}
        )
        control = ControlConfig(readable=False)
    freshness = latest_freshness(storage, settings.strategy.symbol, settings.strategy.interval, now)
    candles = storage.load_candles(settings.strategy.symbol, settings.strategy.interval)
    if not candles:
        return CycleResult(None, 0, freshness.stale, {}, {}, {})
    history_size = max(settings.strategy.atr_period, settings.strategy.breakout_lookback) + 1
    routed = 0
    enabled_ids = list(accounts)
    latest_open = candles[-1].open_time
    for index, candle in enumerate(candles):
        history = candles[max(0, index - history_size + 1) : index + 1]
        if storage.candle_routed_for_accounts(
            candle.symbol, settings.strategy.interval, candle.open_time, enabled_ids
        ):
            continue
        catchup = latest_open - candle.open_time > interval_delta(settings.strategy.interval)
        kwargs = {"allow_entries": not catchup}
        # Small compatibility seam for test doubles; production router always receives the snapshot.
        if "control" in inspect.signature(route_candle).parameters:
            kwargs["control"] = control
        results = route_candle(accounts, history, candle, settings, freshness.stale, **kwargs)
        storage.persist_routed_candle(
            settings.strategy.interval, candle, results, "stale_catchup" if catchup else None
        )
        for account_id, result in results.items():
            accounts[account_id] = (result.state, accounts[account_id][1])
        routed += 1
    logger = logging.getLogger("trader.worker")
    if freshness.stale:
        age = now - (candles[-1].open_time + interval_delta(settings.strategy.interval))
        logger.warning(
            "stale data",
            extra={"alarm": "stale_data", "latest_candle_age_seconds": age.total_seconds()},
        )
    return CycleResult(
        candles[-1].open_time,
        routed,
        freshness.stale,
        {account_id: str(state.risk.equity) for account_id, (state, _) in accounts.items()},
        {account_id: state.position is not None for account_id, (state, _) in accounts.items()},
        {
            account_id: ("A" if account_id == "A" else resolve_agent_gate(control, account_id).mode)
            for account_id in accounts
        },
    )


def run_worker(settings: Settings, clock: Clock | None = None) -> int:
    """Run until SIGINT/SIGTERM or lock loss; never contacts authenticated exchange endpoints."""

    if settings.database_url is None:
        raise ValueError("DATABASE_URL is required for trader worker")
    configure_logging()
    logger = logging.getLogger("trader.worker")
    storage = PostgresStorage(settings.database_url)
    clock = clock or RealClock()
    lock = WorkerLock(storage, settings.worker.lock_key)
    if not lock.acquire():
        logger.error("worker lock unavailable", extra={"alarm": "worker_lock_unavailable"})
        lock.close()
        return 1
    stopping = False

    def stop_handler(signum, frame):
        nonlocal stopping
        stopping = True
        if isinstance(clock, RealClock):
            clock.interrupt()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    ingestor = None
    failures = 0
    exit_code = 0
    try:
        # A single query verifies the dedicated database endpoint before loading durable state.
        if not lock.healthy():
            logger.error("worker lock lost", extra={"alarm": "worker_lock_lost"})
            exit_code = 1
            return exit_code
        storage.verify_worker_schema()
        accounts = {}
        for account_id in storage.report_account_ids():
            account = AccountConfig.model_validate(storage.load_account_config(account_id))
            if account.enabled:
                accounts[account_id] = (load_account_state(storage, account), account)
        if not accounts:
            raise ValueError("no enabled paper accounts")
        ingestor = BinanceIngestor(settings.data)
        logger.info("worker started")
        while not stopping:
            if not lock.healthy():
                logger.error("worker lock lost", extra={"alarm": "worker_lock_lost"})
                exit_code = 1
                break
            now = clock.now()
            close = now.replace(minute=0, second=0, microsecond=0) + interval_delta(
                settings.strategy.interval
            )
            clock.sleep_until(
                close + timedelta(seconds=settings.worker.candle_close_buffer_seconds)
            )
            if stopping:
                break
            try:
                now = clock.now()
                start = storage.latest_candle_time(
                    settings.strategy.symbol, settings.strategy.interval
                )
                start = start or now - timedelta(days=settings.data.backfill_days)
                ingestor.backfill(
                    storage, settings.strategy.symbol, settings.strategy.interval, start, now, now
                )
                started = clock.now()
                cycle = run_cycle(storage, accounts, settings, now)
                logger.info(
                    "worker heartbeat",
                    extra={
                        "processed_candle_time": cycle.processed_candle_time.isoformat()
                        if cycle.processed_candle_time
                        else None,
                        "routed_candle_count": cycle.routed_candle_count,
                        "stale": cycle.stale,
                        "equity": cycle.equity,
                        "open_positions": cycle.open_positions,
                        "agent_gates": cycle.agent_gates,
                        "cycle_latency_seconds": (clock.now() - started).total_seconds(),
                    },
                )
                failures = 0
            except Exception:
                failures += 1
                logger.exception("worker cycle failed", extra={"failures": failures})
                if failures >= settings.worker.max_cycle_failures:
                    logger.error("worker cycle failures", extra={"alarm": "worker_cycle_failures"})
                    exit_code = 1
                    break
                clock.sleep_until(
                    clock.now() + timedelta(seconds=settings.worker.poll_retry_seconds)
                )
    finally:
        if ingestor is not None:
            ingestor.close()
        lock.close()
    if exit_code == 0:
        logger.info("worker shutdown")
    return exit_code

    def __init__(self) -> None:
        self._interrupted = threading.Event()
