# AOPSO Sprint 34 - Unified A+B Executive Report

> **SAFETY:** ADVISORY-ONLY OFFLINE EVIDENCE - NOT FOR ACTUATION OR CONTROL - NO LIVE SITE INTEGRATION - SITE DEPLOYMENT NOT AUTHORIZED IN THIS VERSION

Generated (UTC): `2026-05-29T00:00:00Z`
Report version: `sprint34.unified_ab.v1`

## What this product does

AquaOptima Pump Station Optimizer Lite is an **offline advisory evidence
product**. It evaluates two independent pillars on a locked, out-of-sample
March 2026 holdout from the Yilan site, and emits a unified evidence
bundle for review.

- **Pillar A** (Health / Anomaly Detection): observe how an anomaly
  detector responds to canonical injected faults overlaid on real,
  unseen March 2026 normal-mode telemetry.
- **Pillar B** (Efficiency / Counterfactual Opportunity): score real
  March 2026 OperatingPoints against a 2025-derived matched-condition
  efficient envelope, and report only the **counterfactual offline
  opportunity** on supported intervals.

## Product status

**Pillar A validated; Pillar B FAILED its locked-March acceptance gate (honest result). Advisory evidence only; deployment NOT authorized in this version.**

## What each pillar proved on the locked holdout

### Pillar A - verdict: **PASS**

- Benchmark: LOCKED March 2026 holdout (out-of-sample), broad full-year 2025 fit
- Gate: `v2` (pre-registered v2 product-grounded
  gate; rule: detector_auroc >= baseline_auroc - 0.01 (non-inferior) AND detector_false_alarm_rate <= baseline_false_alarm_rate / 2 AND detector_auroc >= 0.70 AND detector_mean_lead_time >= baseline_mean_lead_time - 1.0)
- Detector AUROC: `0.9435953348633261` vs baseline
  `0.9175359491438111`
- Detector false-alarm rate: `0.012800276229467765`
  vs baseline `0.05179302520593893`
- Detector mean lead-time: `15.821428571428571` rows
  vs baseline `4.838709677419355` rows
- Holdout window: `2026-03-01 00:00:53`
  to `2026-03-31 23:59:19`

### Pillar B - verdict: **FAIL**

- Frozen gate: `sprint32.envelope.v1` (rule:
  Sprint 33 PASS iff: coverage_meaningful_or_limitations_explained AND positive_opportunity_robust_under_conservative_quantile AND no_unsupported_interval_produces_savings AND mvpv1_comparison_valid_where_reported AND leakage_and_safety_checks_pass.)
- Coverage waterfall: total=`58`,
  valid=`58`, supported=`21`,
  unsupported=`37`
- Counterfactual opportunity on supported intervals:
  p25=`0.0` kWh, p10=`1.3097953444387933` kWh
- Robust under conservative quantile?
  `False`
- March-observed energy on supported intervals:
  `498.653777` kWh
- Holdout window: `2026-03-01 00:00:53`
  to `2026-03-31 23:59:19`

> 58 March-2026 OperatingPoints scored; 58 (100.0%) had finite matching-channel values; 21 (36.2%) had >= MIN_SUPPORT historical neighbours under the FROZEN matching tolerances and produced advisories. The remainder were honestly REJECTED with named reasons; no savings claim is made on any rejected interval.

## Honest limitations

- Pillar A injected faults are SYNTHETIC. AUROC / lead-time / false-alarm
  measure how the 2025-fit detector responds to canonical faults on top of
  unseen March 2026 normal data. They do **not** measure how the detector
  would score real March faults (March 2026 has no ground-truth labels).
- Pillar B reports a **counterfactual offline opportunity** only, on
  intervals with sufficient historical neighbours under the FROZEN
  matching tolerances. Realising the opportunity in operation would
  require future operational validation under the same hydraulic
  constraints.
- Unsupported intervals (insufficient historical neighbours, or no
  efficient sub-bucket) carry **zero** claim by construction.
- MVPv1 control-log comparison is produced only where the FROZEN
  alignment diagnostic passes; otherwise the comparison is marked **not
  available**, never approximated.
- Offline only. **No setpoints, no actuation, no live integration, no
  site write path of any kind.**

## Cannot claim

- We do NOT claim guaranteed energy savings.
- We do NOT claim a deployable control policy.
- We do NOT claim field-validated fault recall or predictive maintenance accuracy.
- We do NOT claim site integration, actuation, or write-path readiness.
- We do NOT claim that an advisory operating point may be used as a setpoint.
- We do NOT claim opportunity on intervals the envelope honestly REJECTED.

## Allowed Pillar-B language (verbatim)

- In offline historical replay, the matched-condition envelope identified an estimated counterfactual opportunity on supported intervals only.
- Under similar historical demand/head/level/pressure conditions, lower specific energy was observed at the reported speed range.
- This is a counterfactual offline estimate requiring future operational validation under the same hydraulic constraints.
- No control action was taken.

## What this report is, and is not

- This is an **offline evidence report**. It is **not** a deployment
  artifact, a control policy, an operating procedure, or a maintenance
  schedule.
- This report does **not** unblock edge deployment or control
  integration.
- A future, separate qualification would be required to authorize any
  deployment discussion. See PRD §9 packaging-unblock policy.
