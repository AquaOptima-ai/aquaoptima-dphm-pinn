# Phase 1 Shadow-Mode E2E Validation Checkpoint — Report

**Branch:** `phase1-shadow-e2e`
**Base:** Sprint 39 commit `fb0b5b3465f6c65b97cd7c463ae5055ad35bde45`
**Scope:** Phase 1 offline shadow-mode MVP validation **only** — no
Phase 2 / Sprint 40 product work.

This branch adds a deterministic end-to-end test and a docs/report
pair that prove the Phase 1 offline shadow-mode chain closes from a
small topology/telemetry fixture through deployment-manifest
packaging. It exercises only the existing Sprint 11–39 public APIs;
no core logic is reimplemented.

## Files added

| Path | Purpose |
| --- | --- |
| `tests/e2e/__init__.py` | New empty package marker for the E2E test directory. |
| `tests/e2e/test_phase1_shadow_mode_pipeline.py` | The Phase 1 E2E pipeline test (2 test cases). |
| `tests/fixtures/shadow_phase1/tag_map.json` | Four-tag telemetry tag-map fixture. |
| `tests/fixtures/shadow_phase1/telemetry.csv` | Three-row offline replay CSV fixture. |
| `tests/fixtures/shadow_phase1/README.md` | Fixture provenance + read-only declaration. |
| `docs/validation/phase1-shadow-mode-e2e.md` | Phase 1 validation checkpoint documentation. |
| `PHASE1_SHADOW_E2E_REPORT.md` | This report. |

No `src/` change was made — Phase 1 product surface is unchanged. The
test exercises existing Sprint 11–39 public APIs only.

## Pipeline summary

```
docs/examples/epanet_reference_loop.inp
  → load_network_from_inp(..., parser="fallback", return_diagnostics=True)
     ⇒ Network                              (Sprint 11 — 5 nodes, 5 edges, 1 fixed-head)
     ⇒ EpanetImportDiagnostics              (Sprints 23–32)
  → build_import_quality_report(diagnostics, network, parser="fallback")
     ⇒ EpanetImportQualityReport            (Sprint 33)
  → load_telemetry_tag_map_json(tests/fixtures/shadow_phase1/tag_map.json, network)
     ⇒ TelemetryTagMap                      (Sprint 34 — 4 canonical tags)
  → load_shadow_replay_csv(tests/fixtures/shadow_phase1/telemetry.csv, tag_map)
     ⇒ ShadowReplayDataset                  (Sprint 35 — 3 frames)
  → build_dpl_calibration_loss_report(replay, predictions, strict=True)
     ⇒ DPLCalibrationLossReport             (Sprint 36 — 12 residuals)
  → build_advisory_contract(allow_rules=..., deny_rules=...)
     ⇒ AdvisoryContract                     (Sprint 37 — 2 allow + 1 deny)
  → run_shadow_runtime(replay, predictions, advisory_contract, proposals_by_frame)
     ⇒ ShadowRuntimeReport                  (Sprint 38 — 3 proposals, 1 accept / 2 reject)
  → build_shadow_deployment_manifest(summary_objects=[...], references={...})
     ⇒ ShadowDeploymentManifest             (Sprint 39 — 4 summary artifacts)
  → write_shadow_deployment_manifest_json(manifest, tmp_path / "...")
     ⇒ Path                                  (Sprint 39 — the only filesystem write)
```

## Fixture scenario

- Topology: five-node looped distribution fixture shipped at
  `docs/examples/epanet_reference_loop.inp` (`J1..J4` junctions + `R1`
  reservoir, pipes `P1..P5`, Hazen–Williams head loss, SI/LPS).
- Telemetry tags (four):
  - `PT_J1`, `PT_J2` → `node_pressure`, units `m`.
  - `FT_P1`, `FT_P2` → `edge_flow`, units `m3/s`.
- Replay rows (three) at `timestamp ∈ {0.0, 1.0, 2.0}` with linearly
  increasing values.
- Predictions: observed value + constant per-axis bias
  (`+0.5 m` on `node_pressure`, `+0.001 m³/s` on `edge_flow`).
- Advisory contract:
  - `allow` on `(node_pressure, 0)` ∈ `[10.0, 80.0]`.
  - `allow` on `(edge_flow, 1)` ∈ `[0.001, 0.040]`.
  - `deny` on `(node_pressure, 1)`.
- Hypothetical advisory proposals on frame 0:
  - `ACCEPT_PRESSURE_J1` — node_pressure 50.0 on target 0 → accepted.
  - `REJECT_FLOW_BOUNDS` — edge_flow 0.060 on target 1 → rejected.
  - `REJECT_DENY_PRESSURE_J2` — node_pressure 25.0 on target 1 →
    rejected.

## Expected-value checks (asserted by the test)

| Stage | Field | Expected |
| --- | --- | --- |
| Network | `num_nodes`, `num_edges`, `num_fixed_heads` | `5`, `5`, `1` |
| Import-quality report | `parser` | `"fallback"` |
| Import-quality report | `len(limitations)` | `>= 2` |
| Tag map | `len(tags)`, `errors` | `4`, `()` |
| Replay | `len(frames)`, per-frame pressure / flow counts, `errors` | `3`, `2 / 2`, `()` |
| dPL loss | `observation_count` | `12` |
| dPL loss | `mse_by_axis["node_pressure"]` | `0.25` (exact) |
| dPL loss | `mse_by_axis["edge_flow"]` | `1.0e-6` (exact) |
| Runtime | `frame_count`, `proposal_count` | `3`, `3` |
| Runtime | `accepted_count`, `rejected_count` | `1`, `2` |
| Runtime | accepted ids | `{"ACCEPT_PRESSURE_J1"}` |
| Runtime | rejected ids | `{"REJECT_FLOW_BOUNDS", "REJECT_DENY_PRESSURE_J2"}` |
| Manifest | `len(artifacts)` | `4` |
| Manifest | artifact kinds (in order) | `shadow_replay_dataset`, `dpl_calibration_loss_report`, `advisory_contract`, `shadow_runtime_report` |
| Manifest | `safety_boundary` | exactly `SAFETY_BOUNDARY_PHRASES` |
| Manifest | every `safety_flags` value | `True` |
| Manifest | `runtime_artifact.summary["frame_count"]` | `3` |
| Manifest | `runtime_artifact.summary["proposal_count"]` | `3` |
| Manifest | `runtime_artifact.summary["accepted_count"]` | `1` |
| Manifest | `runtime_artifact.summary["rejected_count"]` | `2` |
| Manifest JSON | second-run byte equality (`sha256`) | identical to first run |
| `tmp_path` | files produced | exactly `{manifest_path}` |

## Verification output

All commands were run on this worktree against the editable install.

```
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -c "import aquaoptima, pathlib; print(pathlib.Path(aquaoptima.__file__).resolve())"
/home/hunter_lin/projects/aquaoptima-dphm-pinn-phase1-e2e/src/aquaoptima/__init__.py

$ python -c "import wntr; print('wntr', wntr.__version__)"
wntr 1.4.0

$ python -m pytest tests/e2e/test_phase1_shadow_mode_pipeline.py -q
..                                                                       [100%]
2 passed in 2.05s

$ python -m pytest tests/dphm tests/models -q
........................................................                 [100%]
SKIPPED [1] tests/dphm/test_wntr_optional_import.py:371: WNTR is installed; ImportError path not exercised here
1495 passed, 1 skipped, 3 warnings in 13.87s

$ python -m pytest -q
..................................................                       [100%]
SKIPPED [1] tests/dphm/test_wntr_optional_import.py:371: WNTR is installed; ImportError path not exercised here
1633 passed, 1 skipped, 3 warnings in 97.77s

$ python -m compileall -q src tests
# (no errors, no output)

$ git diff --check
# (clean)

$ git status --short
?? docs/validation/
?? tests/e2e/
?? tests/fixtures/
```

A targeted secret scan (PEM/RSA/DSA/EC/OPENSSH private-key block
headers, AWS access-key-id prefixes, AWS secret-access-key
assignments, password / secret / api-key / token literals, bearer
tokens, Slack / GitHub / OpenAI / Anthropic tokens, and postgres /
mysql / mongo connection strings with embedded credentials) over
the seven files touched by this branch produced no matches. The credential-marker regexes used by the test
itself are assembled from string fragments so the test source does not
embed a raw secret-scan trigger string.

## Safety boundary / limitations

- The pipeline is **offline / read-only / no-write / no-control /
  no live OT binding / no setpoint output / packaging audit only**.
- The single filesystem write is the Sprint 39 manifest JSON, into a
  caller-supplied `pytest` `tmp_path`. A dedicated second test
  (`test_phase1_shadow_mode_pipeline_writes_only_the_manifest`)
  re-runs the chain and enumerates every file under `tmp_path` to
  reaffirm that this is the only write.
- No live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter, no actuator / setpoint surface, and no advisory emission
  layer is added. Hypothetical advisory proposals are *audit only* —
  even an accepted decision is **never** transformed into a setpoint
  write here.
- No credentials, API keys, tokens, passwords, secrets, or connection
  strings are read, hashed, embedded, or written by the pipeline or
  by the test fixtures.
- The fixture is intentionally tiny (5 nodes, 5 edges, 3 frames). It
  is a deterministic-shape end-to-end smoke check; it does not
  certify performance on real distribution networks, does not tune
  the dPL prediction, and does not produce an operationally-tuned
  advisory envelope.
- The validation checkpoint is the gate immediately *before* Phase 2
  may begin. The dPHM forward solver is **not** invoked here; that
  remains an option for future shadow-mode evaluation work, **out of
  scope** for this checkpoint.

## Recommendation

**Pause before Phase 2 and request user approval.**

This branch is a validation checkpoint, not a Phase 2 / Sprint 40
launch. The Phase 1 chain has been demonstrated end-to-end with
deterministic expected-value assertions, the safety boundary has been
reaffirmed in code and in docs, and the full pre-existing test suite
remains green (`1633 passed, 1 skipped`). Before any Phase 2 /
advisory-control / supervised-control work is taken on, the team
should explicitly approve:

1. that the Phase 1 boundary as documented here is correct;
2. that the Phase 2 trust-boundary plumbing, live-OT adapter scope,
   write authorisation model, and operator-in-the-loop sign-off path
   are agreed in advance; and
3. that this branch is acceptable to land as a validation checkpoint
   (no `src/` change) ahead of any Phase 2 work.

Hermes will independently verify, commit, push, and update Plane. No
commit or push has been made from this worktree.
