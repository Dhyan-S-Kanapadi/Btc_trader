# Proposed agent interface for #20 and #21

`investigate(snapshot: SnapshotJson) -> VerdictJson` is the only core contract. The worker supplies immutable snapshot JSON; it receives a versioned verdict JSON with `action` restricted to `VETO` or `SKIP`, `reason_code`, `reason`, `agent_version`, `prompt_version`, `model_id`, and `trace_id` when present.

The target adapter is selected by configuration: local function for tests, HTTP Fargate, or AgentCore Runtime. It uses a fresh opaque session ID per candidate, a hard client deadline, at most one bounded retry only for clearly transient transport errors, and maps every timeout, malformed response, permission failure, and unavailable target to `SKIP` with an error reason. The worker never imports an AgentCore SDK or agent implementation.

Every verdict persists the snapshot idempotency key and version fields. Tools and memory must enforce `known_at <= snapshot.signal_time` in their own query boundary; no model or memory feature is trusted to infer that gate.
