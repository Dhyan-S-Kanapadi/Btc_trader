// Hand-written from the live Issue #14 http://localhost:8000/openapi.json (API v1).
// Decimal values are strings in that schema; fractions remain fractions until formatPercent().
export type DecimalString = string;
export type Meta = { synthetic: boolean; metadata_status: "present" | "missing" };
export type Page = { limit: number; offset: number; returned: number };
export type Account = { account_id: string; label: string | null; policy_name: string | null; starting_equity: DecimalString | null; enabled: boolean; halted: boolean; halt_reason: string | null; latest_equity: DecimalString; open_position: boolean };
export type Position = { account_id: string; symbol: string; qty: DecimalString; entry_price: DecimalString; entry_time: string; stop_price: DecimalString; initial_stop_price: DecimalString | null };
export type Trade = { account_id: string; symbol: string; qty: DecimalString; entry_price: DecimalString; exit_price: DecimalString; entry_time: string; exit_time: string; fees: DecimalString; net_pnl: DecimalString; reason: string };
export type Equity = { account_id: string; recorded_at: string; equity: DecimalString };
export type Pnl = { account_id: string; total_pnl: DecimalString; total_return: DecimalString | null; daily_pnl: Record<string, DecimalString>; daily_realized_net_pnl: Record<string, DecimalString> };
export type Risk = { account_id: string; risk_per_trade: DecimalString | null; daily_loss_cap: DecimalString | null; max_drawdown_halt: DecimalString | null; max_open_positions: number | null; current_drawdown: DecimalString; today_loss: DecimalString; open_positions: number; halted: boolean; halt_reason: string | null };
export type Decision = { account_id: string; candidate_idempotency_key: string; action: string; reason: string; risk_result: string | null; verdict: Record<string, unknown> | null; model_version: string | null; prompt_version: string | null; trace_id: string | null; created_at: string };
export type Response<T> = { items: T[]; meta: Meta };
export type PagedResponse<T> = Response<T> & { page: Page };
export type DashboardData = { accounts: Response<Account>; positions: Response<Position>; trades: PagedResponse<Trade>; equity: PagedResponse<Equity>; pnl: Response<Pnl>; risk: Response<Risk>; decisions: PagedResponse<Decision> };
