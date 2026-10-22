# Issue #23 progress

- [x] Separate agent-memory schema script and roles
- [x] Fixed deterministic embedding and exact time-gated retrieval core
- [x] Tool schema exposes only `k`; namespace/vector/as-of stay harness-owned
- [x] In-memory leak, boundary, null-embedding, and version tests
- [x] pgvector local/CI image updated to `pgvector/pgvector:0.8.6-pg16-bookworm`
- [x] Trading-DB episode sync plus `trader memory init|sync|search` commands
- [ ] Agent-service wiring with the reader URL
- [x] Dockerized pgvector integration and reader-permission tests
- [ ] Replay/Account-D integration (explicitly deferred to #27)
