# Phase 1 Shadow-Mode End-to-End Validation

This document describes the **Phase 1 shadow-mode MVP validation
checkpoint** added on the `phase1-shadow-e2e` branch. It is a
*validation document* — it does **not** introduce new Phase 2 /
Sprint 40 product surface. It exercises the existing Sprint 11–39
public APIs end to end against a small deterministic fixture so that a
reviewer can confirm the offline shadow-mode loop closes before any
Phase 2 work is unblocked.

## Scope

Phase 1 shadow-mode MVP is **offline / read-only / no-write /
no-control / no live OT binding / no setpoint output / packaging audit
only**. The validation checkpoint reaffirms that boundary by running
the full Sprint 11–39 chain through caller-controlled inputs and a
caller-supplied `pytest` `tmp_path` for the single manifest-JSON write.
No live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST adapter,
write path, control surface, or setpoint output is added by this
checkpoint, and none is invoked during the test.

## Pipeline

The validated chain is:

```
EPANET-style .inp topology fixture
    → load_network_from_inp(..., return_diagnostics=True)
        → Network                          (Sprint 11)
        → EpanetImportDiagnostics          (Sprints 23–32)
    → build_import_quality_report(...)
        → EpanetImportQualityReport        (Sprint 33)
    → load_telemetry_tag_map_json(...)
        → TelemetryTagMap                  (Sprint 34)
    → load_shadow_replay_csv(...)
        → ShadowReplayDataset              (Sprint 35)
    → build_dpl_calibration_loss_report(...)
        → DPLCalibrationLossReport         (Sprint 36)
    → build_advisory_contract(...) + AdvisoryProposal(...)
        → AdvisoryContract                 (Sprint 37)
    → run_shadow_runtime(...)
        → ShadowRuntimeReport              (Sprint 38)
    → build_shadow_deployment_manifest(...)
        → ShadowDeploymentManifest         (Sprint 39)
    → write_shadow_deployment_manifest_json(manifest, tmp_path / "...")
        → Path                              (Sprint 39 — only write)
```

Every step uses an existing public API — no core logic is
reimplemented here.

## Fixture

The fixture is a five-node looped distribution network shipped at
`docs/examples/epanet_reference_loop.inp` (four junctions + one
reservoir, five pipes, Hazen–Williams head loss, SI/LPS units).

Telemetry plumbing fixtures live under
`tests/fixtures/shadow_phase1/`:

- `tag_map.json` — four canonical telemetry tags
  (`PT_J1`, `PT_J2`, `FT_P1`, `FT_P2`) bound to dPHM node / edge ids 0
  and 1 on each axis.
- `telemetry.csv` — three offline replay rows at `timestamp` ∈
  `{0.0, 1.0, 2.0}` with deterministic observed values.

The prediction sequence is built by biasing every observed value with
a constant per-axis offset (+0.5 m on `node_pressure`, +0.001 m³/s on
`edge_flow`). With a constant bias, each per-axis MSE collapses to the
square of the bias, which makes the expected-value assertion exact and
host-independent.

## Advisory contract

The contract is the operator-visible **read-only safety contract**:

- Allow rule on `(node_pressure, target_id=0)` (J1) — bounds
  `[10.0, 80.0]`.
- Allow rule on `(edge_flow, target_id=1)` (P2) — bounds
  `[0.001, 0.040]`.
- Deny rule on `(node_pressure, target_id=1)` (J2) — operator-locked.

Three hypothetical proposals are audited (frame 0 only; frames 1 and 2
have empty proposal lists):

| `proposal_id`                | Axis            | target | Value  | Expected   |
| ---------------------------- | --------------- | ------ | ------ | ---------- |
| `ACCEPT_PRESSURE_J1`         | `node_pressure` | 0      | 50.0   | accepted   |
| `REJECT_FLOW_BOUNDS`         | `edge_flow`     | 1      | 0.060  | rejected   |
| `REJECT_DENY_PRESSURE_J2`    | `node_pressure` | 1      | 25.0   | rejected   |

Proposals are *hypothetical advisory proposals only*. No proposal is
ever transformed into a setpoint write, written to disk, or emitted to
any external system.

## Expected-value assertions

The test makes the following exact-value assertions:

- `network.num_nodes == 5`, `network.num_edges == 5`,
  `network.num_fixed_heads == 1`.
- `quality_report.parser == "fallback"` and at least two limitation
  strings present (status-open-only + ignored-sections-dropped).
- `len(tag_map.tags) == 4` and no tag-map errors.
- `len(replay.frames) == 3` and each frame carries exactly 2 pressure
  observations and 2 flow observations; no replay errors.
- `loss_report.observation_count == 12` (3 frames × 4 observations).
- `mse_by_axis["node_pressure"] == 0.25` and
  `mse_by_axis["edge_flow"] == 1.0e-6` (constant per-axis bias).
- `runtime_report.frame_count == 3`,
  `proposal_count == 3`, `accepted_count == 1`, `rejected_count == 2`.
- Accepted proposal id is exactly `{"ACCEPT_PRESSURE_J1"}`; rejected
  proposal ids are exactly `{"REJECT_FLOW_BOUNDS",
  "REJECT_DENY_PRESSURE_J2"}`.
- Manifest carries 4 summary artifacts in builder-input order
  (`shadow_replay_dataset`, `dpl_calibration_loss_report`,
  `advisory_contract`, `shadow_runtime_report`).
- Manifest `safety_boundary` equals `SAFETY_BOUNDARY_PHRASES`
  verbatim, and every safety flag is `True`.
- Manifest JSON written to a `pytest` `tmp_path` is the only file
  produced by the chain.
- Two independent runs of the chain produce **byte-equal** manifest
  JSON (verified by `sha256` digest).

## Safety boundary

Asserted directly by the test (and reaffirmed verbatim from Sprint
39):

- `offline`, `read-only`, `no-write`, `no-control`,
  `no live OT binding`, `no setpoint output`, `packaging/audit only`
  are all present in `manifest.safety_boundary`.
- All seven `safety_flags` (`offline`, `read_only`, `no_write`,
  `no_control`, `no_live_ot_binding`, `no_setpoint_output`,
  `packaging_audit_only`) are `True`.
- The rendered manifest JSON does **not** match any forbidden
  word-bounded pattern: live-OT control plane tokens (`PLC`,
  `OPC-UA`, `MQTT`, `live SCADA`, `actuator`), write/emit-side
  setpoint identifiers (`writeSetpoint`, `setpoint_write`,
  `setpoint_emit`), nor common credential markers (a PEM
  private-key block header, an AWS access-key-id prefix). The
  credential-marker regexes are assembled from fragments inside
  the test so the test source itself does not embed a raw
  secret-scan trigger string.
- Only one file is ever written: the caller-supplied manifest path
  under `tmp_path`. A second test
  (`test_phase1_shadow_mode_pipeline_writes_only_the_manifest`)
  enumerates every file under `tmp_path` after the run and asserts the
  set equals `{manifest_path}`.

## Limitations

- The validation fixture is intentionally small (5 nodes, 5 edges, 3
  frames). It is a deterministic-shape end-to-end smoke check; it
  does not certify performance on real distribution networks.
- The prediction sequence is a deterministic linear bias of the
  observed values. The test demonstrates that the dPL calibration
  surface is *wired* and produces the expected MSE; it does not
  attempt to evaluate model quality.
- The advisory contract is a minimal demonstration of allow / deny
  semantics on Sprint 37; it is not an operationally-tuned envelope.
- Phase 2 / Sprint 40 (advisory emission, supervised-control, live OT
  trust-boundary plumbing) is **explicitly out of scope** for this
  checkpoint. The validation checkpoint is the gate immediately
  *before* Phase 2 may begin.

## How to re-run

```sh
python -m pip install -e .
python -m pytest tests/e2e/test_phase1_shadow_mode_pipeline.py -q
```

The test is part of the default `python -m pytest` discovery — no
extra marker, no extra environment variable.
