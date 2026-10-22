import type { DashboardData, Response, Account, Position, Trade, Equity, Pnl, Risk, Decision, PagedResponse } from "./types";

const base = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${base}${path}`, { method: "GET", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json() as Promise<T>;
}
export async function loadDashboard(): Promise<DashboardData> {
  const [accounts, positions, trades, equity, pnl, risk, decisions] = await Promise.all([
    get<Response<Account>>("/v1/accounts"), get<Response<Position>>("/v1/positions"), get<PagedResponse<Trade>>("/v1/trades?limit=100"), get<PagedResponse<Equity>>("/v1/equity?limit=500"), get<Response<Pnl>>("/v1/pnl"), get<Response<Risk>>("/v1/risk"), get<PagedResponse<Decision>>("/v1/decisions?limit=100"),
  ]);
  return { accounts, positions, trades, equity, pnl, risk, decisions };
}
