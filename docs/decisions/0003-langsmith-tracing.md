# 0003: LangSmith tracing

**Status:** implementation-ready, OFF by default. **Read:** 2026-10-22.

## Decision

Use the optional `agent` extra only in the agent-service image. The worker, risk, broker, exit and replay
engine do not import LangSmith. The service creates a `RunTree` with the worker-provided UUID and an
explicit `Client`, then uses its built-in background batching. `Client` supports explicit endpoint, timeout,
retry, input/output/metadata hooks and bounded `flush(timeout)`; this implementation sets a two-second
client timeout, zero retries and never flushes in an investigation.

The SDK's `tracing_context` supports explicit enabled/client/project/tags/metadata context. This repository
currently has a framework-independent investigator rather than a LangGraph graph, so #22 uses the SDK's
native `RunTree` primitive at that boundary; automatic LangGraph child spans require the promised graph to
exist first. That is an inherited #20 gap, not proof of LangGraph coverage.

## Volume estimate

#0001 measured 587 synthetic candidates in 3,000 hourly bars, or 141 candidates/month. Its sharing rule
estimated up to three calls/candidate for C/D evidence variants. Therefore low: 50 candidates x 1 shared
call = 50 traces/month; expected: 141 x 3 = 423; high: 1,000 x 3 = 3,000. These are operational
assumptions, not performance evidence. Leave tracing OFF until the owner chooses a dedicated project and
checks its current plan/retention in the account.

## Pricing, retention and region

**UNVERIFIED in this PR:** public search did not yield a stable official pricing/retention table suitable
for hard-coding. Pricing, free-tier trace allowance, retention, limit-overflow behaviour and organization
data-region choice must be checked in the account immediately before enabling. LangSmith's documented
Agent Server data-plane page says Cloud deployments have US and EU data regions, implied by the organization:
https://docs.langchain.com/langsmith/data-plane (read 2026-10-22). No assumption about dropped traces is
made; tracing remains off.

## Sources

- SDK tracing context: https://github.com/langchain-ai/langsmith-sdk/blob/main/python/langsmith/run_helpers.py
- Client constructor, hooks and batching: https://github.com/langchain-ai/langsmith-sdk/blob/main/python/langsmith/client.py
- Client bounded flush: https://github.com/langchain-ai/langsmith-sdk/blob/main/python/langsmith/client.py
- Dataset example API (`example_id`): https://github.com/langchain-ai/langsmith-sdk/blob/main/python/langsmith/client.py
