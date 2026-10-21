import { money, percent, timestamp } from "./format";

test("formats fractions, money and UTC times without NaN", () => {
  expect(percent("0")).toBe("0%");
  expect(percent("-0.0001")).toBe("-0.01%");
  expect(percent("999999999")).not.toContain("NaN");
  expect(money("0")).toBe("$0.00");
  expect(money("-2.5")).toBe("-$2.50");
  expect(money(null)).toBe("—");
  expect(money("Infinity")).toBe("—");
  expect(timestamp("2026-01-01T00:00:00Z")).toContain("UTC");
  expect(timestamp(null)).toBe("—");
});
