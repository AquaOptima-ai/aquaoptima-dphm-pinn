# AOPSO Sprint 34 - ML Audit Appendix

> **SAFETY:** ADVISORY-ONLY OFFLINE EVIDENCE - NOT FOR ACTUATION OR CONTROL - NO LIVE SITE INTEGRATION - SITE DEPLOYMENT NOT AUTHORIZED IN THIS VERSION

Generated (UTC): `2026-05-29T00:00:00Z`
Report version: `sprint34.unified_ab.v1`

## 1. Methodology overview

The Sprint 34 unified package is an OFFLINE EVIDENCE bundle assembled
from two independent pillar evaluations, each pre-registered against a
locked March 2026 holdout from the Yilan site:

- **Pillar A** (Sprint 30b): full-year-2025 stratified fit + locked
  March 2026 evaluation under pre-registered acceptance gate v2.
- **Pillar B** (Sprint 33): locked March 2026 scored against a frozen
  matched-condition efficient envelope built from 2025 OperatingPoints,
  under a pre-registered Sprint-32 frozen gate.

No model retraining, no parameter tuning, and no fresh data ingestion
were performed in this sprint. The pre-existing pillar artefacts were
loaded and projected into the unified package format.

## 2. Pre-registration & frozen gates

### Pillar A (gate v2)

| Key | Value |
|---|---|
| gate_version | `aquaoptima.advisory.health_gate.health_acceptance_gate_v2` |
| auroc_noninferiority_tol | `0.01` |
| far_improvement_factor | `2.0` |
| min_detector_auroc | `0.7` |
| lead_time_tol | `1.0` |
| preregistered_before_evaluation | `True` |
| tuned_to_outcome | `False` |
| rule | `detector_auroc >= baseline_auroc - 0.01 (non-inferior) AND detector_false_alarm_rate <= baseline_false_alarm_rate / 2 AND detector_auroc >= 0.70 AND detector_mean_lead_time >= baseline_mean_lead_time - 1.0` |

### Pillar B (Sprint-32 envelope, locked at Sprint 33 eval)

| Key | Value |
|---|---|
| gate_version | `sprint32.envelope.v1` |
| gate_file_sha256_at_eval | `f2f6bd91d429a6fe80ed7524766782346e8a4b343258f38ccbf2dcb4755b059d` |
| gate_file_sha256_post_eval | `f2f6bd91d429a6fe80ed7524766782346e8a4b343258f38ccbf2dcb4755b059d` |
| pre_eq_post | `True` |
| frozen_params_sha256 | `f7d6145492787c3c451f7334837536559939a766f4ae905f47aa83968f146e9e` |
| march_used_for_tuning | `False` |
| se_quantiles | `[0.1, 0.25]` |
| matching_tolerances | `{'mean_demand_m3_per_h': 50.0, 'mean_level_m': 0.25, 'mean_pressure_m_head': 0.5, 'mean_flow_m3_per_h': 50.0}` |
| min_support | `30` |

## 3. Holdout protocol

### Pillar A

- Holdout window: `2026-03-01 00:00:53`
  to `2026-03-31 23:59:19`,
  `42674` rows.
- Labeled eval set: synthetic frozen-seed faults injected on REAL March-2026 normal frames (faults synthetic, underlying normal is the genuinely unseen distribution)
- Labeled eval limitation: the injected faults are SYNTHETIC -- AUROC / lead-time / false-alarm measure how the 2025-fit detector responds to canonical faults on top of unseen March normal data, NOT how it would score real March faults (March 2026 has no ground-truth labels).
- Unsupervised eval set: raw un-faulted March-2026 normal frames -- detector / baseline alarm rate on truly unseen data, no labels needed.
- Leakage isolation: fit_health_detector + fit_health_baseline_suite both call the Sprint-27 assert_holdout_isolated guard on input keys; any March-2026 key in the fit input raises LeakageError BEFORE fit.
- Seasonal-confound fix: Sprint 30 fit collapsed onto late-March 2025 (head-of-CSV cap landed in the first auto block). Sprint 30b stratified-samples across ALL 2025 auto-mode months so the fit set spans >= 5 distinct months.

### Pillar B

- Holdout window: `2026-03-01 00:00:53`
  to `2026-03-31 23:59:19`,
  `44469` rows,
  `58`
  OperatingPoints.
- Sprint 33 is a HONEST out-of-sample evaluation of the Pillar B matched-condition efficiency envelope FROZEN in Sprint 32. The 2025 OperatingPoints catalogue defines the envelope; the locked March-2026 OperatingPoints are SCORED against it. March is NEVER used to fit or tune any envelope parameter. The Sprint-32 frozen gate file (efficiency_gate.py) is treated as read-only pre-registration; its SHA-256 hash is recorded here and verified by the test suite.
- Pre-registration: efficiency_gate.py SHA-256 was recorded BEFORE this evaluation and verified against the on-disk hash AFTER. Any change is pre-registration tampering.

## 4. Honest limitations

### Pillar A
- Synthetic injected faults; no real March-2026 fault labels exist.
- AUROC / lead-time / false-alarm measure response to canonical faults
  overlaid on unseen normal data, not real fault recall.

### Pillar B

- March-2026 has NO ground-truth efficiency labels. We do not (and cannot) claim 'the advisory would have saved X kWh in production'; we report a COUNTERFACTUAL OFFLINE opportunity vs the 2025-derived envelope only.
- Counterfactual energy is a hypothetical: it assumes the pump could have operated at the bucket's p25/p10 SE under the same demand/level/pressure/flow context. Realising this opportunity would require future operational validation under the same hydraulic constraints.
- Unsupported intervals (insufficient historical neighbours, or no efficient sub-bucket) carry ZERO claim by construction.
- MVPv1 control-log comparison is produced ONLY where the FROZEN alignment diagnostic passes; otherwise the comparison is marked not available, never approximated.
- Offline only. No setpoints, no actuation, no live integration, no site write path of any kind.

## 5. Both verdicts (verbatim from pillar scorecards)

- Pillar A verdict: **PASS** (Sprint 30b locked-March holdout under gate v2)
- Pillar B verdict: **FAIL** (Sprint 33 locked-March holdout under Sprint-32 frozen envelope)

## 6. Sprint 34 packaging governance

- Modeling-source governance scan:
  - files_scanned: `46`
  - clean: `True`
  - safety_status: `PASS`
  - violations: `[]`
- Edge / site / control packaging remains BLOCKED:
  - `onnx_export` -- BLOCKED -- not produced in this sprint
  - `edge_wiring` -- BLOCKED -- no aquaoptima.edge / aquaoptima_contracts.edge imports
  - `site_integration` -- BLOCKED -- not authorized in this version
  - `control_endpoint` -- BLOCKED -- no control endpoints exist
  - `ui_controls_that_set_anything` -- BLOCKED -- read-only dashboard, no form/input/button
  - `write_path` -- BLOCKED -- no setpoint, no actuation, no OT connector

## 7. Cannot claim

- We do NOT claim guaranteed energy savings.
- We do NOT claim a deployable control policy.
- We do NOT claim field-validated fault recall or predictive maintenance accuracy.
- We do NOT claim site integration, actuation, or write-path readiness.
- We do NOT claim that an advisory operating point may be used as a setpoint.
- We do NOT claim opportunity on intervals the envelope honestly REJECTED.
