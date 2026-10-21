# 0001: AgentCore Runtime spike

**Status:** GO-WITH-CHANGES (research only)  
**Read:** 2026-10-21. **AWS resources created:** none. **Cost incurred:** $0.

## Context and verdict

AgentCore Runtime can host a small LangGraph wrapper and provides an AWS-SDK invocation path, but its current Runtime V2 region list excludes Mumbai. Use **Tokyo (`ap-northeast-1`) plus Claude through Bedrock** only if cross-region placement is acceptable; otherwise use the Fargate fallback. The time-gate is a hard invariant and must be enforced by project-owned Postgres queries, not AgentCore Memory.

### Findings

1. **VERIFIED — regions.** Runtime V2 lists `us-east-1`, `us-east-2`, `us-west-2`, `eu-west-1`, and Tokyo `ap-northeast-1`; Mumbai `ap-south-1` is not listed. Mumbai appears in the separate VPC-AZ table, which does not prove Runtime V2 availability. Bengaluru is therefore closer to Mumbai geographically, but Tokyo is the documented Runtime V2 option; this changes latency/data-location assumptions. Source: [Runtime microVMs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html), read 2026-10-21.
2. **VERIFIED — packaging.** A Python zip direct deploy may use `@app.entrypoint`; an image instead serves `GET /ping` and `POST /invocations` on 8080. Python 3.12 is supported, as are 3.13/3.14. The minimal hello is a `BedrockAgentCoreApp` entrypoint returning JSON. Image-size and cold-start duration limits were **UNVERIFIED**: no precise value was found. Sources: [code deploy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html), [runtimes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-code-deploy-supported-runtimes.html), read 2026-10-21.
3. **VERIFIED — invocation.** ECS calls `boto3.client("bedrock-agentcore").invoke_agent_runtime` with runtime ARN, session ID, bytes payload, optional qualifier, and receives a stream; documented payload maximum is 100 MB. A worker can impose its own synchronous timeout around the call. Cold-start time is **UNVERIFIED** until measured; reusing the same session reuses its microVM. Sources: [invoke](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html), [lifecycle](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html), read 2026-10-21.
4. **VERIFIED — IAM.** Worker: `bedrock-agentcore:InvokeAgentRuntime` scoped to the runtime ARN/endpoint. Runtime execution role trusts `bedrock-agentcore.amazonaws.com`, gets only `bedrock:InvokeModel`/stream on selected model ARNs plus narrowly scoped read-only API/secrets/log permissions actually used. Source: [Runtime IAM](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html), read 2026-10-21.
5. **VERIFIED — networking.** VPC Runtime has no internet by default; RDS/internal API need security-group paths. Anthropic/Jev/LangSmith public APIs need private subnet -> NAT -> IGW; public subnet alone is insufficient. Bedrock uses AWS endpoints; add VPC endpoints (ECR API/DKR, S3 gateway, logs) to reduce NAT traffic. NAT hourly/data charges are extra and region-specific, so amount is **UNVERIFIED**. Source: [VPC](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html), read 2026-10-21.
6. **VERIFIED recommendation — Bedrock.** Prefer Bedrock in Tokyo: IAM authorization avoids an Anthropic API key, `ChatBedrock` is documented in the LangGraph example, and the execution role already needs AWS credentials. Direct Anthropic remains a fallback when a required Claude model/region is absent, but requires a secret and NAT egress. Exact selected Bedrock Claude model ID, rate quota and Bedrock price are **UNVERIFIED** until model access is checked in the chosen account/region; do not hard-code remembered IDs. Sources: [LangGraph example](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/configuration-bundles-runtime.html), [model regional compatibility](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html), read 2026-10-21.
7. **VERIFIED — state.** A LangGraph Postgres checkpointer is feasible only with VPC RDS connectivity and short-lived connection discipline. AgentCore Memory does not document a temporal predicate that can prove it excludes post-candidate outcomes; it therefore cannot enforce the time-gate. Own Postgres, with `known_at <= snapshot.signal_time`, is required. Source: [VPC](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html), read 2026-10-21. Memory time-gate conclusion is an **UNVERIFIED inference from absent documented control**, treated as a no-go for that requirement.
8. **VERIFIED — observability.** AgentCore supports CloudWatch metrics/logs and OpenTelemetry-related configuration; LangSmith can emit separately over public egress, but compatibility/conflict has not been live-tested and is **UNVERIFIED**. Source: [AgentCore interfaces](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/develop-agents.html), read 2026-10-21.
9. **VERIFIED arithmetic; UNVERIFIED operational estimate.** Local synthetic replay (`seed=1`, 3,000 one-hour bars) produced 587 candidate decisions, or 141/month. It is not market evidence. C/D require different evidence, so do not share one verdict across accounts; up to three calls/candidate means 423 expected calls/month. See table below.
10. **VERIFIED — local development.** `agentcore dev --no-browser` hosts the same `/invocations` interface locally on port 8080. Keep `investigate(snapshot) -> verdict` framework-independent, and wrap it locally/AgentCore/HTTP at the edge. Source: [direct Python deploy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html), read 2026-10-21.
11. **VERIFIED — limits/risks.** Default idle session is 15 minutes, microVM lifetime defaults to 8 hours, data-plane quota is 1,000 TPS and new sessions 25 TPS (adjustable). Treat Runtime V2 and model/region availability as deployment-time checks; use versioned endpoints and keep Fargate-compatible HTTP. Source: [quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html), read 2026-10-21.
12. **VERIFIED fallback design.** A second ECS Fargate service exposes `POST /invocations`, shares the container/core function, has worker timeout/retry then SKIP, uses the same VPC/RDS paths, and removes AgentCore invoke/IAM/runtime cost while adding always-on or task-per-request Fargate cost. #20 owns core investigator, #21 target selection/client, #34 AgentCore deployment, and #31 optional IaC; none are built here.

## Cost estimate (USD/month, direct-Anthropic comparison only)

| Case | calls | tokens/call (in/out) | Sonnet 4 list model cost | Runtime V2 estimate | total |
| --- | ---: | --- | ---: | ---: | ---: |
| low | 50 | 5k / 1k | $1.50 | $0.02 | **$1.52** |
| expected | 423 | 5k / 1k | $12.69 | $0.14 | **$12.83** |
| high | 1,000 | 5k / 1k | $30.00 | $0.34 | **$30.34** |

Assumptions: Sonnet 4 direct list pricing is $3/MTok input and $15/MTok output; Runtime V2 is estimated at 0.25 vCPU, 0.5 GB, 30 CPU-active seconds/call using $0.1276/vCPU-hour and $0.0169/GB-hour. Tool/NAT/CloudWatch/RDS/ECR/storage costs are excluded and **UNVERIFIED**. Sources: [Anthropic pricing](https://docs.anthropic.com/en/docs/about-claude/pricing), [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/), read 2026-10-21.

## Least-privilege sketches

```json
{"Effect":"Allow","Action":"bedrock-agentcore:InvokeAgentRuntime","Resource":"<runtime-endpoint-arn>"}
```

```json
{"Effect":"Allow","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"],"Resource":"<selected-model-or-inference-profile-arn>"}
```

## Resources and backlog edits

**Resources log:** no profile selected, no AWS CLI invoked, no resource created/deleted, and therefore no teardown action or charge exists.

- #17: keep AgentCore target optional; require a Fargate-compatible HTTP target.
- #18/#19: require read-only, time-gated tool queries and fail-closed SKIP.
- #20: keep pure `investigate(snapshot)->verdict`; do not embed runtime SDK calls.
- #21: implement target selection, hard deadline, bounded retry, and SKIP on all errors.
- #23: use project-owned Postgres for time-gated episodic retrieval; do not rely on AgentCore Memory for the invariant.
- #31: add optional Tokyo VPC endpoints/NAT cost decision and least-privilege roles.
- #34: deploy only after a separately approved tagged smoke test and measured cold-start sample.
