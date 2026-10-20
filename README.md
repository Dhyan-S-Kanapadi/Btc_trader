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
`trader --help`. It does not implement database access or trading logic.

```powershell
docker compose up --build
docker compose down
```

`DATABASE_URL` is passed to the app container only as a local Compose environment value;
Issue #3 will add database configuration. It is not read by the current Settings class.

## Make targets

| Target | Action |
| --- | --- |
| `make install` | Install the package with test and lint tools. |
| `make test` | Run pytest with a writable temporary directory. |
| `make lint` | Run Ruff lint and formatting checks. |
| `make up` | Build and start the local Compose stack. |
| `make down` | Stop the local Compose stack. |
