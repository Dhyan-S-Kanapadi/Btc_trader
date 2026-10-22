# Issue #27 — account variants

- [x] B and D account configuration promotes only the legacy `skip_all` placeholder.
- [x] Variant values are validated from the database config: B=`base`, C=`jev`, D=`memory`.
- [x] C remains `skip_all`: the governing news/Jev decision defers Jev and permits no replay source.
- [x] Global/per-account evidence controls default off and are audited through the existing control plane.
- [ ] C/Jev wiring is deferred until the Jev decision is formally superseded and replay-safe news exists.
