# Issue #27 — account variants

- [x] B and D account configuration promotes only the legacy `skip_all` placeholder.
- [x] Variant values are validated from the database config: B=`base`, C=`jev`, D=`memory`.
- [x] C is promoted from the legacy `skip_all` placeholder only when that placeholder is unchanged; it remains forward-test-only and its Jev evidence is opt-in.
- [x] Global/per-account evidence controls default off and are audited through the existing control plane.
- [x] C/Jev wiring is composed outside the worker and runs only behind global and per-account Jev controls. Replay still has no approved news source.
- [x] D's agent-service runner binds the separate, time-gated memory reader only for the `memory` variant; B and C cannot receive that tool.
