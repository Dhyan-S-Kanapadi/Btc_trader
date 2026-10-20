# BTC Agentic Paper-Trader

**PAPER TRADING ONLY.** This project cannot place orders and contains no exchange-key,
order-placement, or live-trading configuration. It is not financial advice.

All strategy and cost defaults are assumptions to test, not validated choices.

## Quickstart

Requires Python 3.12 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

## Configuration

Configuration is read only from environment variables. It uses the `TRADER_` prefix and
`__` to address a nested section. For example:

```powershell
$env:TRADER_RISK__RISK_PER_TRADE = "0.02"
```

See [`.env.example`](.env.example) for commented defaults. It is a reference only; the
application does not require or load a dotenv file.

| Section | Assumption defaults |
| --- | --- |
| Strategy | `BTCUSDT`, `1h`, 24-bar breakout lookback, 14-bar ATR, 96-bar trend SMA, 1.5 initial-stop ATR, 2.0 trailing-stop ATR, 48-bar time stop |
| Risk | 1% risk per trade, 3% daily loss cap, 10% drawdown halt, one open position, 10,000 starting paper equity |
| Costs | 10 bps fee per side and 5 bps slippage |

Prices and quantities use `Decimal`, rather than `float`, so later accounting and fee
calculations do not inherit binary floating-point rounding errors.

## Breakout rule

The proposed rule evaluates only information available at each closed candle. True range is
`max(high - low, abs(high - previous close), abs(low - previous close))`; the first candle has no
previous close, so it has no true range. ATR is the simple average of the trailing configured
`atr_period` true ranges, including the signal candle, and is unavailable until that history exists.

A candidate requires its close to be strictly above the highest high of the prior configured
`breakout_lookback` candles. The signal candle is excluded from that level. Its stable idempotency
key is `<symbol>:<interval>:<signal-time-UTC-ISO-8601>`; it does not contain the series-local bar
index, so it remains the same when the same candle is evaluated from a later slice. Signal time is
the candle `open_time`, because that is the timestamp available on the shared `Candle` type.

## Evidence snapshots

`build_snapshot` freezes v1 JSON evidence at the candidate candle. It internally slices candles at
the signal timestamp, so later candles cannot affect the result. The self-contained fields are
`schema_version`, idempotency key, symbol, signal time, reference price, ATR, and breakout level.
All fractions use `0.01` for 1%, not a percent number.

| Field | Definition |
| --- | --- |
| `volume_ratio` | Signal volume divided by the mean of the prior `breakout_lookback` volumes; null without enough history or a zero mean. |
| `breakout_strength_atr` | `(reference_price - breakout_level) / atr`, in ATR units. |
| `atr_pct` | `atr / reference_price`, as a fraction. |
| `range_24h_pct` | `(highest high - lowest low) / reference_price` over the final inclusive `breakout_lookback` candles; null without enough history. |
| `trend_vs_sma` | `reference_price / SMA(close, trend_sma_period) - 1`, including the signal candle; null without enough history. |

The 96-bar trend SMA is an assumption to test. `snapshot_to_json` and `snapshot_from_json` provide
lossless HTTP-ready JSON; any v1 field-set change requires a new schema version.

## Risk engine

The pure risk engine gates **new entries only**; exits belong to Issue #8. Limits come only from
environment-backed `Settings`; no model or caller can override them. In order it checks: existing
halt, stale data, UTC day rollover, drawdown halt, daily equity-loss cap, open-position cap,
positive inputs, stop validity, then sizing. Daily loss compares marked equity (including caller
marked unrealized P&L) to UTC `day_start_equity`. A drawdown halt persists until an external,
audited reset. Entry price is an estimate at signal time; Issue #7 will re-size after actual fill.

## Paper broker

Paper fills use only recorded candles: entries use the next open, stops use the open on a gap or
the stop otherwise, and all buys add slippage while all sells subtract it. Fees apply on both sides.
When stop and target both touch, stop wins; targets are only a safeguard for now. Fee (10 bps/side)
and slippage (5 bps) are assumptions to verify, not exchange facts. Risk sizing must be re-run at
actual fill price; this module never talks to an exchange or network.

## Docker and Compose

The image uses Python 3.12 slim and runs the single `trader` CLI as a non-root user. The
Compose stack starts local-only PostgreSQL 16, waits for its health check, then runs
`trader --help`. `make up` runs it detached so database tests can connect from the host.

```powershell
docker compose up --build
docker compose down
```

`DATABASE_URL` is the only database connection setting. The Compose credentials are local-only
defaults; they are not production credentials.

## PostgreSQL schema and migrations

All durable paper-trading state uses PostgreSQL. Prices and quantities use `Decimal` and map to
`NUMERIC(30,12)`. The initial Alembic revision creates candles, candidates, snapshots, accounts,
decisions, orders, positions, trades, equity_curve, configs, and run_metadata. The `configs` JSON
document must never contain credentials, tokens, or exchange keys.

Start the local database, apply the migration as the one-off command, then run the integration
tests:

```powershell
make up
$env:DATABASE_URL = "postgresql+psycopg://paper:paper@localhost:5432/paper_trader"
trader migrate
make test
docker compose logs app
make down
```

`trader migrate` runs `alembic upgrade head`; it makes no trades and is intended to become a
one-off Fargate task. `make test` exports the same local-only `DATABASE_URL` default. Outside
Make, set that single environment variable before running the database tests.

## Public Binance candle ingestion

Issue #9 reads only the unauthenticated public `GET /api/v3/klines` endpoint at
`https://data-api.binance.vision`; it has no exchange credentials, account access, or order
operations. Binance returns a 12-item kline array: open time, OHLC and volume fields, close time,
then market statistics. Prices and volumes are parsed as `Decimal`. Requests use the strategy
symbol and interval, page forward from `startTime`, and retain only rows whose close time is no
later than the passed current UTC time.

`trader backfill` stores candles under the existing `(symbol, interval, open_time)` unique key, so
reruns are idempotent. It detects missing interval timestamps and makes one additional request per
gap. `latest_freshness` reports data stale when no candle exists or its latest open time is more
than two intervals old; the risk engine does not import it yet.

```powershell
$env:DATABASE_URL = "postgresql+psycopg://paper:paper@localhost:5432/paper_trader"
trader migrate
trader backfill --days 30
```

Public requests retry network and 5xx failures with exponential jitter, respect `Retry-After` on
429, and stop immediately on 418. `TRADER_DATA__BASE_URL`, `TIMEOUT_SECONDS`, `MAX_RETRIES`,
`MAX_RETRY_SECONDS`, and `BACKFILL_DAYS` are documented in `.env.example`.

shortcut: Gap repair assumes fixed-duration intervals; add calendar-aware handling if month candles are supported.

## Replay (synthetic only)

The replay core is the pure `step(state, history, candle, policy, config)` function. For every
closed candle it fills a prior pending entry at the new candle open, processes exits, marks equity,
rolls the UTC day, then evaluates and queues a new candidate for the next open. It reuses the
breakout, snapshot, risk, paper-fill, and exit-manager functions; it has no I/O, clock, random, or
storage calls. `WAIT` is recorded but deliberately has no deferral behavior.

`trader replay --source synthetic` generates deterministic `SYNTH-BTC` toy candles with a seed.
**SYNTHETIC data is not market data and says nothing about strategy performance.** Results are
written as `SYNTHETIC_` CSV/JSON files and a clearly labeled summary, with no wall-clock values, so
the same inputs produce byte-identical files.

```powershell
trader replay --source synthetic --seed 1 --bars 3000 --policy take_all --output-dir replay-output
```

The volume-filter baseline accepts only candidate snapshots with `volume_ratio >= 1.5`; this is an
assumption to test, not a validated threshold. `--source db` reads already-closed candles from
PostgreSQL. `--persist` records decisions/orders atomically plus trades, equity points, and replay
metadata, but it refuses an account that already has rows. Point every persisted replay at a fresh
scratch database; never mix replay output with live data. The schema has no run identifier, so one
database per persisted replay is the deliberate safety boundary until a later reporting design
changes that.

```powershell
$env:DATABASE_URL = "postgresql+psycopg://paper:paper@localhost:5432/paper_trader"
trader migrate
trader replay --source synthetic --seed 1 --bars 3000 --persist --output-dir replay-output
```

Pending entries at the final bar are retained in the final state but never reported as trades.
shortcut: Replay persistence stores final account state in the existing account row; add full
pending-position restart serialization when live-worker recovery is introduced.

## Paper-account variants

Issue #11 adds four independent paper accounts, `A` through `D`, sharing each closed candle,
candidate, and evidence snapshot while keeping cash, positions, risk limits, and decisions separate.
`trader seed-accounts` creates the idempotent local defaults: `A` uses `take_all`; `B`, `C`, and
`D` use `skip_all` with the exact reason `agent not wired yet (#27)`. Each account has an editable,
non-secret `configs` JSON document containing `account_id`, `label`, `policy_name`,
`starting_equity`, and `enabled`; an unknown policy or malformed configuration fails before replay.

For multi-account replay, seed the database first. `--accounts` defaults to `A`; comma-separated
accounts write per-account files below the output directory plus `combined_summary.json`. `--persist`
requires every selected account to be empty, then writes shared evidence once and per-account
decisions/orders atomically. The complete serialized engine state is stored in `accounts.engine_state`,
so a new process resumes the same cash, UTC-day risk state, halt status, pending entry, and position.

```powershell
$env:DATABASE_URL = "postgresql+psycopg://paper:paper@localhost:5432/paper_trader"
trader migrate
trader seed-accounts
trader replay --source synthetic --seed 1 --bars 3000 --accounts A,B,C,D --persist --output-dir replay-output
```

`A` without `--persist` remains runnable without a database for deterministic synthetic experiments;
that compatibility path uses the explicit `--policy` baseline and does not load or mutate account
configuration. All account policy names and balances are proposals to test, never validated strategy
choices.

shortcut: Completed trades are idempotently recognized by account, entry-candidate reason, and exit time; add a database unique constraint when the trade schema gains a durable execution identifier.

## Variant report

`trader report` is a read-only, one-off PostgreSQL job for comparing the selected paper accounts
from one replay scratch database. It writes deterministic CSV, JSON, and Markdown files. Closed-trade
metrics use after-fee net P&L: return is final/first equity minus one; drawdown is the largest
peak-to-trough equity fraction; win rate is profitable closed trades/trades; profit factor is gross
profit/gross loss; and Average R is net P&L divided by quantity times entry price minus the immutable
initial stop. Open positions are excluded from trade metrics but their unrealized P&L remains in
equity metrics. Profit factor is null when there are no losses.

The report warns when accounts do not share candidate keys/candle ranges or have fewer than the
assumed `TRADER_REPORT__REPORT_MIN_TRADES=30` closed trades. This is an assumption, not a validated
threshold. It reports missing stored cost/strategy metadata as missing rather than using current
settings. Results are a sample, never a forecast; synthetic reports are explicitly labeled.

## Make targets

| Target | Action |
| --- | --- |
| `make install` | Install the package with test and lint tools. |
| `make test` | Run pytest with a writable temporary directory. |
| `make lint` | Run Ruff lint and formatting checks. |
| `make up` | Build and start the local Compose stack in the background. |
| `make down` | Stop the local Compose stack. |
