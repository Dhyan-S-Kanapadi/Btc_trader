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
| Risk | 1% risk per trade, 3% daily loss cap, 10% drawdown halt, one open position |
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

## Make targets

| Target | Action |
| --- | --- |
| `make install` | Install the package with test and lint tools. |
| `make test` | Run pytest with a writable temporary directory. |
| `make lint` | Run Ruff lint and formatting checks. |
| `make up` | Build and start the local Compose stack in the background. |
| `make down` | Stop the local Compose stack. |
