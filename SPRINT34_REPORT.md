# AOPSO Sprint 34 — Unified A+B offline evidence package

> **SAFETY:** ADVISORY-ONLY OFFLINE EVIDENCE - NOT FOR ACTUATION OR CONTROL - NO LIVE SITE INTEGRATION - SITE DEPLOYMENT NOT AUTHORIZED IN THIS VERSION

## Status

**SPRINT34_STATUS: COMPLETE**

**SPRINT34_GATE: PASS** — packaging-gate verdict only. The packaging gate
validates the *package boundary*, not the pillar verdicts. Both pillar
verdicts are reported HONESTLY below.

## Honest pillar verdicts (reproduced verbatim from source scorecards)

- **Pillar A — verdict: PASS** (Sprint 30b locked-March-2026 holdout under
  pre-registered acceptance gate v2;
  `data/eval/pillarA/sprint30b_fullyear_holdout_scorecard.json`).
  Detector AUROC `0.9436` vs baseline `0.9175`, detector false-alarm rate
  `0.0128` vs baseline `0.0518` (~4.05× reduction), detector mean
  lead-time `15.82` rows vs baseline `4.84` rows on 32 injected-fault
  episodes.
- **Pillar B — verdict: FAIL** (Sprint 33 locked-March-2026 holdout under
  Sprint-32 frozen envelope;
  `data/eval/pillarB/sprint33_locked_march_scorecard.json`). The
  conservative-quantile robustness criterion failed: counterfactual
  opportunity at the primary p25 quantile was `0.0` kWh across 21
  supported intervals (the aggressive p10 quantile showed `1.31` kWh on
  the same intervals). 37 of 58 March OperatingPoints were honestly
  REJECTED with `insufficient_support`; no savings claim is made on any
  rejected interval.

## Product status

> Pillar A validated; Pillar B FAILED its locked-March acceptance gate
> (honest result). Advisory evidence only; deployment NOT authorized in
> this version.

This is the honest dual-pillar status. Per PRD §10.5, the correct
response to a Pillar-B FAIL is to PUBLISH the FAIL truthfully — never to
repackage it as success — and that is exactly what this package does.

## Files changed

- `src/aquaoptima/advisory/sprint34_unified_package.py` (new) — the
  unified packager: scorecard builder, dashboard renderer, exec /
  plant-manager / ML-audit Markdown renderers, health-event and
  efficiency-advisory exporters (JSON+CSV), artifact-manifest builder
  (contracts-SDK `ModelArtifactRecord`-shaped), packaging gate. No
  network, no actuation, no live OT binding, no edge import.
- `scripts/sprint34_unified_package.py` (new) — runner that writes every
  surface to `data/eval/unified/`. Argparse-driven, deterministic when
  `--generated-at` is pinned.
- `tests/advisory/test_sprint34_unified.py` (new) — 51 tests pinning
  the safety / honesty contract (banner, both verdicts, cannot-claim
  block, read-only dashboard, governance scan, manifest conformance,
  no-claim-on-unsupported-interval boundary, packaging-gate).
- `SPRINT34_REPORT.md` (this file, replacing the unrelated pre-existing
  Sprint 34 telemetry-tag-map report that was carried in from the
  upstream dPHM-PINN repo).

## Artifacts written to `data/eval/unified/`

| File | Purpose |
|---|---|
| `sprint34_unified_scorecard.json`   | Unified scorecard — BOTH pillar verdicts + packaging gate + governance scan |
| `sprint34_dashboard.html`           | Static, read-only HTML dashboard (no `<form>`, `<input>`, `<button>`, `<script>`, no `fetch`/XHR) |
| `sprint34_executive_report.md`      | Plant-manager executive report (Markdown) |
| `sprint34_plant_manager_summary.md` | One-page plant-manager summary |
| `sprint34_ml_audit_appendix.md`     | Full methodology, gate versions, pre-registration hashes, leakage checks, both verdicts, every cannot-claim |
| `health_event_export.csv` / `.json` | Pillar A injected-fault evidence (32 episodes) with advisory-only banner |
| `efficiency_advisory_export.csv` / `.json` | Pillar B counterfactual evidence (supported intervals only; 37 unsupported intervals carry zero claim) with advisory-only banner |
| `sprint34_artifact_manifest.json`   | Two `ModelArtifactRecord`s (Pillar A + B) with the canonical all-True `SafetyFlagSet`, real sha256 over the upstream scorecards, `edge_export: BLOCKED_in_sprint34` |

## Safety posture (every surface)

- Persistent banner string `ADVISORY-ONLY OFFLINE EVIDENCE - NOT FOR
  ACTUATION OR CONTROL - NO LIVE SITE INTEGRATION - SITE DEPLOYMENT NOT
  AUTHORIZED IN THIS VERSION` appears on every surface (10 surfaces;
  test `test_safety_banner_present_on_every_surface`).
- Dashboard HTML is 100% static: no `<form>`, `<input>`, `<button>`,
  `<textarea>`, `<select>`, `<script>`, no `method=post`, no `onclick=`
  / `onsubmit=` / `onchange=`, no `fetch(` / `XMLHttpRequest` /
  `WebSocket` (test `test_dashboard_has_no_forbidden_html_token`).
- Cannot-claim block (6 statements, verbatim) appears in every prose
  report surface (dashboard, executive report, plant-manager summary,
  ML audit) — pinned by parametrised
  `test_every_prose_surface_contains_every_cannot_claim_statement`.
- Modeling-source governance scan (advisory + training + models +
  dataio) is CLEAN: no forbidden edge import, no write/actuation
  connector token (`test_governance_scan_over_modeling_source_is_clean`).
- Artifact manifest: every `ModelArtifactRecord` carries the canonical
  all-True `SafetyFlagSet` (7 flags) and round-trips through
  `ModelArtifactRecord.from_dict`; checksums are real sha256 hashes of
  the actual scorecard files
  (`test_artifact_manifest_each_record_is_a_model_artifact_record`).
- No claim is emitted on any unsupported Pillar-B interval; the
  exclusion count (37) is recorded in the export metadata
  (`test_efficiency_export_emits_no_unsupported_advisory_rows`,
  `test_efficiency_export_metadata_records_unsupported_count`).

## Packaging gate result

**SPRINT34_GATE: PASS** — all five packaging-gate criteria pass
(`data/eval/unified/sprint34_unified_scorecard.json#packaging_gate`):

| # | Criterion | Result |
|---|---|---|
| P1 | `safety_banner_on_every_surface` | PASS — 0 surfaces missing the banner |
| P2 | `no_control_endpoint_or_ui_control_in_dashboard` | PASS — 0 forbidden HTML tokens |
| P3 | `leakage_and_safety_checks_pass` | PASS — 0 governance violations |
| P4 | `reports_include_cannot_claim_statements` | PASS — every prose surface contains every cannot-claim line |
| P5 | `edge_site_control_packaging_remains_blocked` | PASS — no ONNX export, no edge import, no UI controls that set anything, no write path |

A PASS of THIS gate is a PASS of the packaging boundary, not a
claim about deployment readiness. The product status remains the honest
dual-pillar status above.

## Acceptance gate (from the task prompt) — line-by-line

1. **Unified report includes BOTH Pillar A and Pillar B PASS/FAIL
   verdicts (truthfully).** PASS — scorecard `pillar_a_verdict=PASS`,
   `pillar_b_verdict=FAIL`; product status quotes both.
2. **Safety banner appears on every surface.** PASS — all 10 surfaces.
3. **No control endpoints and no UI controls that set anything exist
   anywhere in the package.** PASS — dashboard has 0 forbidden HTML
   tokens; no control endpoints are exposed.
4. **Leakage and safety checks pass (governance scan finds no
   forbidden connector tokens / edge imports).** PASS — 0 violations
   over `src/aquaoptima/{advisory,training,models,dataio}`.
5. **Reports include explicit "cannot-claim" statements.** PASS — 6
   statements present verbatim in every prose surface.
6. **Edge/site/control packaging remains blocked (no ONNX export,
   no edge wiring in this sprint).** PASS — manifest records carry
   `edge_export: BLOCKED_in_sprint34`; packaging-blocks inventory
   covers ONNX, edge wiring, site integration, control endpoint, UI
   controls that set anything, and write path.

## Cannot-claim section (verbatim)

- We do NOT claim guaranteed energy savings.
- We do NOT claim a deployable control policy.
- We do NOT claim field-validated fault recall or predictive maintenance
  accuracy.
- We do NOT claim site integration, actuation, or write-path readiness.
- We do NOT claim that an advisory operating point may be used as a
  setpoint.
- We do NOT claim opportunity on intervals the envelope honestly
  REJECTED.

## Validation commands & results

```bash
python3 scripts/sprint34_unified_package.py --generated-at 2026-05-29T00:00:00Z
python3 -m pytest tests/advisory/test_sprint34_unified.py -q
python3 -m pytest tests -q
```

Results:

- Runner: emits 10 files to `data/eval/unified/`; `packaging_gate_verdict: PASS`.
- Sprint 34 tests: **51 passed in 0.43s.**
- Full suite: **2642 passed, 1 skipped, 3 warnings in 117.39s** (the
  skip is the pre-existing WNTR optional-import path; the 3 warnings
  are pre-existing torch / torch_geometric deprecation warnings).
  +51 new tests, 0 regressions.

## Compatibility / boundary notes

- The contracts SDK is **untouched** (`src/aquaoptima_contracts/**` not
  modified). The artifact manifest uses the published
  `ModelArtifactRecord` shape via the existing builders
  (`build_health_artifact_record`, `build_efficiency_artifact_record`)
  with the canonical `default_safety_flag_set()` and `framework="onnx"`
  — the records *reference* the locked-March scorecards as their
  audit artifact, NOT model-weight blobs, because **no ONNX export is
  produced in this sprint** (`edge_export: BLOCKED_in_sprint34`).
- Frozen pillar gates (`efficiency_gate.py`, `health_gate.py`'s v2
  block) are **untouched**.
- All Sprint 27–33 surfaces, frozen constants, and scorecards are
  preserved unmodified. The unified packager reads them; it does not
  rewrite them.
- The pre-existing `SPRINT34_REPORT.md` in the working tree described
  an unrelated upstream Sprint 34 (telemetry tag-map adapter from the
  dPHM-PINN core) carried in by the merge base. This sprint's report
  replaces it because both files are named `SPRINT34_REPORT.md` and the
  AOPSO Sprint 34 task is the one the worktree is for; the unrelated
  module (`src/aquaoptima/dphm/telemetry_tag_map.py`) is itself
  preserved unchanged.

## Honest limitations preserved end-to-end

- Pillar A's injected faults are SYNTHETIC; the AUROC / lead-time /
  false-alarm metrics measure response to canonical faults overlaid on
  unseen March 2026 normal data, NOT real-world fault recall.
- Pillar B reports a counterfactual offline opportunity only, on the
  21 of 58 March OperatingPoints that had ≥ `MIN_SUPPORT=30` historical
  neighbours under the FROZEN matching tolerances. The remaining 37
  intervals carry zero claim. The conservative p25 quantile produced
  `0.0` kWh of opportunity; that is the honest result, and it is the
  reason Pillar B's gate FAILed. The exec report carries the allowed
  advisory language verbatim and never claims guaranteed savings.
- Offline only: no setpoints, no actuation, no live integration, no
  site write path of any kind.

## What is NOT in this sprint (by design)

- No ONNX export.
- No edge package / edge wiring.
- No site integration.
- No model retraining.
- No control endpoints.
- No UI controls that set anything.
- No new acceptance gates for either pillar (the existing pre-registered
  gates are the source of truth).

## Sprint 35 recommendation (advisory only)

Pillar B's `FAIL` on the conservative p25 quantile is informative, not
fatal to the product thesis: 21 of 58 intervals were supported and the
counterfactual evidence on those intervals is preserved in the export.
A Sprint-35 follow-up could honestly investigate:

1. Whether expanding the 2025 envelope (more pump-on cycles, more
   modes) materially lifts the supported-interval count without
   relaxing the FROZEN matching tolerances — i.e. coverage growth, not
   gate softening.
2. A targeted alignment-diagnostic pass for MVPv1 control logs, if
   they become available, so that a clean comparator can be reported on
   the subset where alignment passes — never approximated.
3. A documented scope-decision per PRD §10.5 (data-remediation /
   scope-reduction / stop-pause) tying the next product step to the
   honest Pillar B FAIL.

None of the above unblocks edge deployment or control integration. The
safety boundary is unchanged.
