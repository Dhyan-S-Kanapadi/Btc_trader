# Issue #34 — AgentCore Runtime

## Delivered

- `Dockerfile.agent` hosts only the investigator on AgentCore's `/ping` and `/invocations` contract.
- The runtime calls Groq directly through its OpenAI-compatible endpoint. The key is read from a
  local `GROQ_API_KEY` only for development or from the runtime role's `GROQ_SECRET_ARN` in AWS.
- Terraform creates a VPC-attached runtime, scoped worker invoke permission, ECR pull permission,
  narrowly scoped Groq-secret read permission, and exports the runtime ARN.
- The runtime uses the existing read-only candle API and existing time-gated memory reader; it does
  not import worker, risk, broker, or routing code. B–D remain default-off and failure maps to SKIP.

## Deployment steps

1. Build and push `Dockerfile.agent` to the Terraform-managed ECR repository with an immutable tag.
2. Set the Groq key value in the existing Secrets Manager secret outside Terraform.
3. Run Terraform with `app_image_tag`, `agent_image_tag`, and `budget_alert_email` values.
4. Enable AgentCore CloudWatch observability in the target account, then invoke the runtime with a
   synthetic candidate before enabling any B–D agent control.
5. Put the output `agentcore_runtime_arn` in the worker's `TRADER_AGENT_CLIENT__SERVICE_URL` and set
   `TRADER_AGENT_CLIENT__TARGET=agentcore`.

## Assumptions and limitations

- `openai/gpt-oss-20b`, 10-second Groq timeout, 15-second investigator wall clock, and the existing
  512-token cap are operational assumptions, not validated settings.
- The runtime needs NAT egress for Groq. It uses temporary HTTP egress to the read-only API until
  Issue #33 provides HTTPS.
- CloudWatch traces and a real-runtime timeout failure require an AWS apply and smoke test; they are
  not asserted by local tests and no resources are created by this change.
- Existing control cap fields are not usage accounting; this change does not claim spend enforcement.
