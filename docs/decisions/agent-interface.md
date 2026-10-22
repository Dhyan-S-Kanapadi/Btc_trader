# Proposed agent interface for #20 and #21

`investigate(snapshot: SnapshotJson) -> VerdictJson` is the only core contract. The worker supplies immutable snapshot JSON; it receives a versioned verdict JSON with `action` restricted by the existing guardrail to `TAKE`, `SKIP`, or `WAIT`, `reason_code`, `reason`, `agent_version`, `prompt_version`, `model_id`, and `trace_id` when present.

## Version 2 tracing extension (#22)

The request carries `schema_version: 2` and an optional worker-created UUID v4 `trace_run_id`.
The service rejects other versions clearly and ignores malformed IDs. Its response has a small `trace`
object: `enabled`, `run_id` (only when an actual root trace started), and `status`. Tracing is strictly
agent-side and opt-in; it never changes the verdict. A shared call has one trace, so it is tagged by
candidate, variant, model, prompt, source and synthetic status—not account ID. Decision rows link to
that one trace through their persisted `trace_id`.

The target adapter is selected by configuration: local function for tests, HTTP Fargate, or AgentCore Runtime. It uses a fresh opaque session ID per candidate, a hard client deadline, at most one bounded retry only for clearly transient transport errors, and maps every timeout, malformed response, permission failure, and unavailable target to `SKIP` with an error reason. The worker never imports an AgentCore SDK or agent implementation.

Every verdict persists the snapshot idempotency key and version fields. Tools and memory must enforce `known_at <= snapshot.signal_time` in their own query boundary; no model or memory feature is trusted to infer that gate.
