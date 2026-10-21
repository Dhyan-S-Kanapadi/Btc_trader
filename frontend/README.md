# Paper-trader dashboard

## Decision note

This is a Vite 8 + React 19 + TypeScript single page. Vite produces the requested static `dist/` output; React keeps the read-only sections manageable. Vitest and React Testing Library cover user-visible behaviour. Charts are inline SVG, so no chart, state-management, CSS-framework, or UI-component dependency is needed. Node **22.12.0** is recorded in `.nvmrc` (Vite requires Node 20.19+ or 22.12+; Vitest requires 22.12+).

The single-page sections were chosen over routes: every operational view is visible together and the permanent banner cannot disappear on navigation.

## Run locally

```powershell
# Terminal 1: API (after migrate, seed and synthetic persisted replay)
$env:TRADER_API__ALLOWED_ORIGINS = "http://localhost:5173"
$env:DATABASE_URL_READONLY = "postgresql+psycopg://paper_readonly:paper_readonly_local@localhost:5432/paper_trader"
trader api

# Terminal 2
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

Use `VITE_FIXTURE_MODE=true npm run dev` for explicitly synthetic fixtures. Fixture code is conditionally imported, so a normal production build tree-shakes it; this is checked by inspection of the generated bundle during review.

## Build-time public variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Read-only API origin, baked into static output. |
| `VITE_AUTO_REFRESH_MS` | `30000` | Modest refresh interval; values under 5 seconds disable auto-refresh. |
| `VITE_MIN_TRADES` | `30` | Assumed small-sample warning threshold, not a validated number. |
| `VITE_TRACE_URL_TEMPLATE` | unset | Optional URL containing `{trace_id}`; creates trace links. |
| `VITE_FIXTURE_MODE` | false | Development/test fixture mode only. |

`VITE_*` values are public bundle content. Do not put credentials, tokens, or secrets in them.

## Views and data definitions

The typed contracts in `src/types.ts` are handwritten from Issue #14's live `/openapi.json`. The dashboard calls only GET endpoints: accounts, positions, trades, equity, P&L, risk, and decisions. Fractions are rendered only by `src/format.ts`: money uses USD, percentages multiply API fractions by 100, and timestamps are UTC with `UTC` shown.

Total P&L is latest equity minus stored starting equity. Daily P&L uses the API’s final UTC equity mark less the previous final mark; closed-trade net P&L is separately after fees. Drawdown is peak-to-trough divided by peak. Max drawdown appears only in the selected-account chart, because it is derived there directly from equity data. The comparison intentionally omits it to avoid inventing a cross-account number from a paginated feed.

The fixed banner, synthetic/missing-metadata labels, cards, open positions, equity/drawdown chart with text alternative, P&L, risk usage, comparison, history, and decisions all explicitly distinguish missing values (`—`) from zero. Wide tables scroll inside their container on phones.

## Verify

```powershell
npm run lint
npm test
npm run build
npm run check:bundle
```

`npm run build` writes static files to `dist/`, suitable for S3. The bundle check rejects common secret markers and verifies that the Vite variable name itself is not shipped.
