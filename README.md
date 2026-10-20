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
| Strategy | `BTCUSDT`, `1h`, 24-bar breakout lookback, 14-bar ATR, 1.5 initial-stop ATR, 2.0 trailing-stop ATR, 48-bar time stop |
| Risk | 1% risk per trade, 3% daily loss cap, 10% drawdown halt, one open position |
| Costs | 10 bps fee per side and 5 bps slippage |

Prices and quantities use `Decimal`, rather than `float`, so later accounting and fee
calculations do not inherit binary floating-point rounding errors.

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
