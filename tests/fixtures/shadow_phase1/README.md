# tests/fixtures/shadow_phase1/

Small deterministic fixtures used by `tests/e2e/test_phase1_shadow_mode_pipeline.py`
to validate the Phase 1 offline shadow-mode chain end-to-end.

Contents

- `tag_map.json` — four canonical telemetry tags (`PT_J1`, `PT_J2`, `FT_P1`,
  `FT_P2`) bound to the dPHM node / edge ids produced by the shipped
  EPANET fixture `docs/examples/epanet_reference_loop.inp`.
- `telemetry.csv` — three offline replay rows. Timestamps are forwarded
  verbatim to the replay builder; no live SCADA / historian / OPC-UA /
  MQTT path is involved.

The fixtures are read-only inputs only. The E2E test consumes them
through the existing `load_telemetry_tag_map_json` and
`load_shadow_replay_csv` public APIs (Sprints 34–35).
