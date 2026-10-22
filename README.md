# BTC Agentic Paper-Trader

**PAPER TRADING ONLY.** This project cannot place orders and contains no exchange-key,
order-placement, or live-trading configuration. It is not financial advice.

All strategy and cost defaults are assumptions to test, not validated choices.

## Forward-test news boundary

Issue #25 admits only the official BLS release calendar, and only for prospective collection.
It is not a general news feed, is not historical replay evidence, and does not predict BTC returns.
`fetched_at` is the injected-clock receipt time; source `published_at` is nullable and untrusted.
An item is visible at `T` exactly when `available_at <= T`, where live collection sets
`available_at = fetched_at`; publication time can never make it visible earlier. This resolves the
as-of ambiguity conservatively.

## Optional Jev sensor

Issue #26 adds an isolated, disabled-by-default typed Jev sensor. When explicitly enabled, it sends
only bounded, sanitized BLS schedule headlines that were already visible at the snapshot timestamp to
Vercel AI Gateway. Set `AI_GATEWAY_API_KEY` only in ignored `.env` or a secret manager, then set
`TRADER_JEV__ENABLED=true` after completing the calibration plan in
[`docs/analysis/jev_calibration_plan.md`](docs/analysis/jev_calibration_plan.md). The client uses a
pinned HTTPS gateway host, a total deadline, bounded retries and response size, and a circuit breaker.

Jev creates typed nullable snapshot evidence only. It is not wired into the worker, risk engine,
broker, router, replay, account policy, or API, and cannot trade or affect a risk value. Its BLS-only
input is forward-test-only; it makes no claim that news or Jev predicts BTC returns. Use
`trader jev calibrate` to check human-label readiness; it never contacts the gateway.

The pure pipeline is: bounded fetch, calendar parse, HTML entity decoding (at most three passes),
tag/script/style removal, NFKC normalization, control/format removal, whitespace collapse,
URL/email/markup removal, length cap, then deterministic guardrail classification. The guardrail
reuses Issue #19 injection patterns and adds hard rules for instructions, role markers, tool syntax,
embedded structured data, and forced yes/no answers. Hard matches are quarantined; padding is only
flagged. A false-positive quarantine loses a real schedule item, which is safer than passing an
instruction-shaped string. Pattern matching is not an attack-proof boundary: any future consumer
must use only bounded typed `SanitizedHeadline`/`NewsView` fields, never prose as authority.

`news_items` and `news_polls` are isolated by migration `0008_news_ingestion`; no API endpoint,
dashboard display, worker import, model call, or trading path is added. BLS terms recorded in
[`0002-news-and-jev.md`](docs/decisions/0002-news-and-jev.md) permit schedule metadata with
attribution/disclaimer; this issue does not expose it publicly. The poller is deliberately separate
from the hourly worker because receipt-time evidence needs more frequent collection; deployment is
deferred to #32. Retention is also deferred, so table growth is proportional to polls and unique
calendar entries.

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
`D` use agent-veto account configurations after Issue #27. B is `base`, C is `jev` and is strictly
forward-test-only, and D is `memory`; unknown variants fail fast when the database config is loaded.
`trader seed-accounts` promotes only an unchanged `skip_all` placeholder and appends an audit record,
never overwriting an operator-selected policy. Safe defaults remain agent off and shadow on, so this
plumbing does not make a model, Jev, or memory call by itself. C additionally requires global and
per-account Jev controls; no historical-news replay is enabled or implied.
Each account has an editable,
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

## Live paper worker

`trader worker` is the only continuous worker entrypoint. It is **PAPER TRADING ONLY**: it uses the
public Binance candle endpoint, PostgreSQL, and the existing paper replay/router/risk path; it has no
exchange keys, signed requests, account endpoints, or order-placement endpoints. Run migrations and
seed accounts first:

```powershell
trader migrate
trader seed-accounts
trader worker
```

The worker waits for each configured candle close plus `TRADER_WORKER__CANDLE_CLOSE_BUFFER_SECONDS`
(default `10`), backfills only closed candles, then routes every not-yet-routed candle chronologically.
`TRADER_WORKER__POLL_RETRY_SECONDS`, `TRADER_WORKER__MAX_CYCLE_FAILURES`, and
`TRADER_WORKER__LOCK_KEY` control failure retries, the consecutive-failure exit threshold, and the
PostgreSQL session advisory-lock key. PostgreSQL and Amazon RDS for PostgreSQL support advisory locks.

Each account/candle completion is an atomic transaction containing candle evidence, decisions/orders,
trades, equity, serialized engine state, and a `routed_candles` checkpoint. The checkpoint is the
already-routed marker; a restart reloads durable engine state and cannot skip a partially persisted
candle or duplicate its effects. The lock remains on one dedicated PostgreSQL connection; a probe on
that same connection detects loss and exits non-zero.

Freshness is calculated once per cycle and passed to the risk path, so stale data prevents new entries
while exit, trailing-stop, time-stop, and equity processing continue. During catch-up, candles more
than one interval behind the newest closed candle also process exits and marks but cannot create a
pending entry; their per-account durable checkpoint has reason `stale_catchup`. The newest eligible
candle may create a pending entry. This explicitly resolves the catch-up ambiguity.

## Variant report

## Read-only API

`trader api` serves paper-trading data only. It has no write routes, exchange credentials, signed
requests, or order operations. It requires `DATABASE_URL_READONLY`; it deliberately never falls back
to `DATABASE_URL`. Uvicorn binds `TRADER_API__HOST=0.0.0.0` and `TRADER_API__PORT=8000` by default.
OpenAPI is available at `/docs` and `/openapi.json`.

The API database role is created outside Alembic because role creation requires elevated database
privileges that managed migrations should not hold. Local Compose applies
[`docker/init-readonly.sql`](docker/init-readonly.sql) only to a fresh database volume. For RDS, run
the same SQL once as an administrator, replacing the local-only password with a secret-manager value:

```sql
CREATE ROLE paper_readonly LOGIN PASSWORD '<managed-secret>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
GRANT CONNECT ON DATABASE paper_trader TO paper_readonly;
GRANT USAGE ON SCHEMA public TO paper_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO paper_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE paper IN SCHEMA public GRANT SELECT ON TABLES TO paper_readonly;
```

The API also executes `SET default_transaction_read_only = on` when opening a connection. CORS has no
wildcard default: set `TRADER_API__ALLOWED_ORIGINS` to comma-separated allowed origins; credentials
are disabled and only `GET`/`OPTIONS` are allowed.

All versioned endpoints use typed JSON models and offset pagination (`limit`, `offset`; default 100,
hard maximum 500, rejected above that): `/v1/accounts`, `/v1/positions`, `/v1/trades`, `/v1/equity`,
`/v1/pnl`, `/v1/risk`, and `/v1/decisions`. `/health` returns
`{"status":"ok","paper_trading":true}` or `503`. List responses include `meta`; it marks
synthetic replay metadata, or explicitly reports `metadata_status: "missing"`.

`/v1/pnl` defines total P&L as latest equity minus stored starting equity (and total return as that
fraction). Daily P&L is the final equity for each UTC day minus the previous UTC-day final equity;
the first day uses starting equity. Closed-trade realized net P&L is returned separately per day.
This is the explicit resolution of the daily-P&L ambiguity; it aligns with the report's after-fee
trade arithmetic while preserving mark-to-market equity.

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

## Agent operations control plane

Issue #17 adds operator controls for agent-gated entry decisions only. They cannot change risk,
position size, stops, exits, broker behavior, or account A. Missing controls fail closed: agents are
off, shadows default on, kill switches are off, model/prompt versions are null, and cap assumptions
are `0.10` per candidate and `1.00` per day. Caps are stored and exposed only; spend tracking is not
implemented.

The worker reads one immutable control snapshot per cycle. An unreadable control plane emits
`control_plane_unreadable` and kills only agent-gated entries for that cycle; account A and exits
continue. Shadow records the inner verdict with `shadow=true`, while the fixed `skip_all` fallback
determines the actual result. Agent errors become `SKIP agent_error`.

```powershell
trader control seed
trader control show
trader control set global agent_enabled true --actor operator-name
trader control set B shadow false --actor operator-name
trader control kill B --actor operator-name
```

The CLI has strict typed, allowlisted updates. Each change and its self-reported actor are written
atomically to an append-only PostgreSQL audit table; a PostgreSQL 16 trigger rejects audit updates
and deletes. Offline replay accepts `--control path/to/control.json` and never reads DB controls.

## Read-only agent tools

`trader.agent_tools` provides evidence only; it cannot write, trade, change risk, or access exchange
credentials. A candle is known at `as_of` only when `open_time + interval <= as_of`; equality is
included. The harness binds `ToolRegistry(as_of=...)` to the candidate signal time. Model-facing
schemas omit `as_of`, and an attempted supplied value is rejected. The API, HTTP source, and tool
layer each enforce the boundary; a future candle is an `asof_violation`, never silently discarded.

The tools return typed numbers, nulls with `insufficient_history`, and short labels only—never
external free text. This is the prompt-injection posture. `volume_vs_average` compares the latest
known volume to assumed 24-bar and 168-bar averages; the longer window supplements the snapshot's
24-bar ratio. `higher_timeframe_trend` uses only complete UTC 4-hour or daily bars. `volatility_regime`
uses the existing ATR with assumed 720-hour percentile bands (under 25% low, above 75% high).
`recent_failed_breakouts` counts a breakout as failed only when a later known close is below its
breakout level; incomplete confirmation windows are unresolved, not held. These defaults are
assumptions, not validated strategy values.

`GET /v1/candles` is read-only and returns ascending, known OHLCV candles with their derived close
time and the request `as_of`; it has the existing API limit guard and synthetic metadata. Sources can
be `InMemoryCandleSource` for local deterministic use or `HttpCandleSource` for the same read-only
API. Calls log tool name, bound arguments, status, latency, fetched count, data-through, and an output
digest without raw candle payloads. The API has no authentication today; #31/#34 must decide its
deployment boundary before exposing it beyond a trusted network.

## Agent client safety boundary

Issue #21 keeps the investigator outside the stop/exit path. Each candle has a durable phase one
(pending fills, exits, equity marks, and day rollover) before phase two evaluates a candidate policy.
The worker persists phase one for every enabled account before a policy can invoke an agent; a restart
resumes phase two rather than replaying an exit.

The worker-side client supports local development, internal HTTP, and optional AgentCore targets. It
fails closed to `SKIP`: killed/off gates make no request, and unavailable targets, timeouts, response
mismatches, and invalid output cannot approve an entry. Returned verdicts are rechecked by the worker
guardrail. Its in-memory circuit breaker resets on restart; the durable request cache remains the
restart boundary.

The internal HTTP service uses a shared `AGENT_SERVICE_TOKEN`; it is internal-service authentication,
not end-user authentication, and still requires network isolation. It has body, allowlist, and
concurrency limits. This plumbing does not claim that an agent improves trading results or profitability.

## Optional LangSmith tracing

Tracing is agent-service observation only and defaults to off (`TRADER_AGENT_TRACING__ENABLED=false`).
It cannot affect a verdict, risk rule, order, exit, or worker circuit breaker. The worker generates a
UUID v4 for each agent request; the service uses it as the optional root run id and returns it only after
a trace actually starts. Shared calls are tagged with candidate, variant, model, prompt, source and
synthetic status—never an account ID. Linked decision rows are the way to identify all accounts served
by one trace.

The agent SDK uses bounded background batching. No decision path flushes tracing; a process may perform
a bounded shutdown flush. Inputs, outputs, metadata and errors are scrubbed for configured secret values,
bearer/Authorization values and common key-shaped strings, then capped at 8 KiB per field. A trace outage
is a rate-limited warning and the investigation continues untraced. `agent_calls` and decisions stay useful
after trace retention expires. A run-id-only dashboard URL is not documented as portable: use the project
dashboard and filter by run id until a workspace-specific URL template is configured.

Tracing shows what the agent did, not whether it was right. Before raw news or Jev text is introduced,
the payload and licensing policy must be reviewed again. Dataset export/evaluation labels remain future
work; this issue deliberately does not claim they exist.

## Time-gated episodic memory

Memory is optional, agent-only, and lives in a separate `agent_memory` PostgreSQL database—not the
trading database. An episode is an Account A candidate with a closed trade: its outcome is net R after
fees, exit reason, and bars held. Candidates that A did not take have no episode; this is a selection
effect. `known_at` is the close of the candle that processed the exit, not the fill time.

Retrieval applies the same invariant three times: SQL requires `known_at <= as_of` and candidate time
strictly before `as_of`; the tool verifies every returned row and raises `asof_violation` if a source leaks;
and the service uses a SELECT-only role. Namespaces keep `live` and `synthetic:<run>` data apart. The
embedding is a fixed five-value, clipped-and-scaled deterministic vector. Its constants are assumptions,
never fitted from history; null features are not embeddable. Search is exact L2 with deterministic ties,
not ANN, because correctness matters more than speed at this scale.

Run `sql/agent_memory_init.sql` once as the memory database owner. The agent receives only
`AGENT_MEMORY_DATABASE_URL` (the reader credential); `trader memory init` and `trader memory sync` require
the separate `AGENT_MEMORY_WRITE_DATABASE_URL`. The memory tool appears only when memory is enabled and the
request variant is `memory`. It returns historical cases and distances, not probabilities or trading advice.
The agent-service composition uses `make_investigator_runner(..., memory_source=PostgresMemorySource(...))`;
that reader is passed only for D's `memory` request variant, never to the worker or B/C. This proves only that
the retrieval plumbing is time-gated; it does not prove memory improves outcomes.
