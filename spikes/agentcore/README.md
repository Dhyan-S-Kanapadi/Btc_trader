# AgentCore throwaway spike

This directory is not imported by `src/trader` and is not production agent code. It records the documented entrypoint and invocation shape only; no AWS profile was selected, no dependency was installed, no resource was created, and no invocation was claimed.

For an approved future smoke test: choose a profile and region, create only a tagged `project=btc-paper-trader-spike` direct-code Runtime, invoke once with a synthetic snapshot, record cold/warm latency, then delete it and verify deletion. Do not place credentials, account IDs, runtime ARNs, or real snapshots here.
