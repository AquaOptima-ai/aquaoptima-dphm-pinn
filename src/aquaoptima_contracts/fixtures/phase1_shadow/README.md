# `aquaoptima_contracts/fixtures/phase1_shadow/`

Sprint 41 SDK copies of the Phase 1 offline shadow-mode fixtures, plus
a representative SDK manifest snapshot derived from the Phase 1
chain.

The originals at `tests/fixtures/shadow_phase1/` remain in place and
continue to power `tests/e2e/test_phase1_shadow_mode_pipeline.py`. A
Sprint 41 test
(`tests/aquaoptima_contracts/test_phase1_fixture_compat.py`) asserts
that the SDK copies are byte-identical to the originals.

Files

- `tag_map.json` — byte-for-byte copy of
  `tests/fixtures/shadow_phase1/tag_map.json`. Four canonical
  telemetry tags (`PT_J1`, `PT_J2`, `FT_P1`, `FT_P2`) bound to the
  dPHM node / edge ids produced by the shipped EPANET fixture
  `docs/examples/epanet_reference_loop.inp`.
- `telemetry.csv` — byte-for-byte copy of
  `tests/fixtures/shadow_phase1/telemetry.csv`. Three offline replay
  rows; timestamps are forwarded verbatim to the replay builder.
- `manifest_snapshot.json` — representative SDK projection of a Phase
  1 manifest, covering the **envelope / safety / capability subset
  only**. The full `ShadowDeploymentManifest` SDK schema lands in
  Sprint 42. The snapshot is regenerated deterministically by
  `aquaoptima_contracts.base.serialization.write_canonical_json` and
  round-trips byte-for-byte through `dump_canonical_json`.

Safety boundary

The fixtures are read-only inputs only. The SDK does not open any
network connection, does not bind any live OT source, does not emit a
write / dispatch / setpoint payload, and does not introduce a control
surface. The manifest snapshot is a packaging / audit-evidence bundle.
