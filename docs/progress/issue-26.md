# Issue #26 — Jev sensor

The Jev boundary is opt-in and disabled by default. It can send only bounded, sanitized, forward-collected BLS schedule headlines to Vercel AI Gateway using an environment-only `AI_GATEWAY_API_KEY`; no key, raw response, or headline text is written to Jev audit records or logs. User approval for this narrow data sharing was recorded on 2026-10-22.

It is a typed snapshot sensor only. It is not imported by the worker, risk engine, broker, router, replay, policy, or API, and it cannot trade or alter a risk value. BLS is forward-test-only and neither BLS nor Jev output makes a predictive claim about BTC.

The current typed parser intentionally accepts only the documented answer shape used in tests. Gateway response-envelope compatibility needs one controlled runtime validation before enabling `TRADER_JEV__ENABLED=true` outside a test environment.
