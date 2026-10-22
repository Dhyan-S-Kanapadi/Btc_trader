import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App, { drawdowns } from "./App";
import { fixture } from "./fixtures";

const payloads = [fixture.accounts, fixture.positions, fixture.trades, fixture.equity, fixture.pnl, fixture.risk, fixture.decisions];
beforeEach(() => { let index = 0; vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(payloads[index++]), { status: 200 })))); });
afterEach(() => vi.unstubAllGlobals());

test("renders every dashboard view, fixed banner, and only GET requests", async () => {
  render(<App />);
  await screen.findByRole("heading", { name: "Overview" });
  for (const heading of ["Open trades", "Equity and drawdown — A", "Total and daily P&L", "Risk", "Account comparison", "Trade history", "Decisions"]) expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
  expect(screen.getByText(/PAPER TRADING ONLY/)).toBeTruthy();
  expect(getComputedStyle(screen.getByText(/PAPER TRADING ONLY/)).position).toBe("fixed");
  expect(vi.mocked(fetch).mock.calls.every(([, init]) => (init as RequestInit).method === "GET")).toBe(true);
  fireEvent.click(screen.getAllByRole("button", { name: "View chart" })[0]);
});
test("keeps banner for loading and failed requests", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
  render(<App />);
  expect(screen.getByText(/PAPER TRADING ONLY/)).toBeTruthy();
  await screen.findByRole("alert");
  expect(screen.getByText(/PAPER TRADING ONLY/)).toBeTruthy();
});
test("drawdown matches hand calculation: 100, 120, 90 => 0, 0, .25", () => {
  expect(drawdowns([{ equity: "100" }, { equity: "120" }, { equity: "90" }] as never)).toEqual([0, 0, 0.25]);
  expect(drawdowns([{ equity: "100" }] as never)).toEqual([0]);
  expect(drawdowns([{ equity: "100" }, { equity: "100" }] as never)).toEqual([0, 0]);
});
