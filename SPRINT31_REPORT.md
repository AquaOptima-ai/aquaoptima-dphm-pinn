# Sprint 31 Report — AOPSO Pillar B specific-energy (kWh/m³) engine

## Goal

Build the offline, advisory-only Pillar B foundation: a unit-confirmed
specific-energy (SE = kWh/m³) calculation, valid-interval filtering with
named exclusion reasons, 15-minute and 30-minute aggregation, an
`OperatingPoint` export the Sprint 32 matched-condition search will consume,
and a Pillar B unit-and-validity scorecard with an honest acceptance gate.

> **Hard safety boundary:** offline-only, advisory-only, no setpoints, no
> control language, no live integration, no actuation, no edge imports.
> `evaluation_mode="offline_only"`, `advisory_only=True` on every artifact.
> March 2026 is the **frozen holdout** and must not appear in any Sprint 31
> input.

## What was built

| File | Change |
|------|--------|
| `src/aquaoptima/advisory/specific_energy.py` | **New.** End-to-end SE engine: `confirm_units`, `compute_intervals`, `validity_waterfall`, `aggregate_operating_points`, `OperatingPoint` record, `assert_no_march_2026_in_keys`, `build_sprint31_scorecard`, `run_sprint31_scorecard`, `main` CLI. |
| `tests/advisory/test_sprint31_specific_energy.py` | **New.** 14 tests covering the five acceptance criteria + scorecard shape on a clean fixture. |
| `data/eval/pillarB/sprint31_unit_validity_scorecard.json` | **New artifact** (the Pillar B unit-and-validity scorecard). |
| `data/eval/pillarB/operating_points_15min_2025.csv` | **New artifact** — 18,764 valid operating points, 15-minute aggregation. |
| `data/eval/pillarB/operating_points_30min_2025.csv` | **New artifact** — 9,414 valid operating points, 30-minute aggregation. |
| `SPRINT31_REPORT.md` (this file) | **Overwritten** for the AOPSO Pillar B Sprint 31 narrative (the previous file documented an unrelated EPANET diagnostics ergonomics sprint and was not the AOPSO Pillar B work). |

The engine **reuses** the existing Pillar A infrastructure rather than
duplicating it: axis taxonomy and units come from
`aquaoptima.advisory.label_schema.AXIS_UNITS` and
`aquaoptima.dataio.yilan_axis_map.CANONICAL_AXIS_TO_COLUMN`; the operating-mode
filter uses `aquaoptima.dataio.yilan_profiler.derive_mode`; the
March-2026 leakage tripwire is the Sprint-27 governance guard
`aquaoptima.advisory.governance.assert_holdout_isolated`. No edge SDK
imports, no `aquaoptima.edge` references, no actuation tokens.

## Unit confirmation (PRD Q2)

The unit gate reads the single source of truth (`AXIS_UNITS`) and checks every
quantity SE depends on against an expected unit. If any unit cannot be
confirmed the gate emits an explicit `errors` list and the whole scorecard
FAILs. From the live scorecard:

```json
"unit_confirmation": {
  "confirmed": true,
  "units": {
    "edge_power":      "kW",
    "edge_flow":       "m3_per_h",
    "edge_pump_speed": "hz",
    "node_demand":     "m3_per_h",
    "node_level":      "m",
    "node_pressure":   "m_head"
  },
  "expected_units": { /* identical */ },
  "conversion_notes": [
    "energy_kwh = trapezoidal_integral(power_kw * dt) with dt in hours; kW * h = kWh.",
    "volume_m3 = trapezoidal_integral(flow_m3_per_h * dt) with dt in hours; (m^3 / h) * h = m^3.",
    "specific_energy_kwh_per_m3 = energy_kwh / volume_m3 (interval-integrated, never an instantaneous ratio).",
    "interval delta-t is computed as (ts[i+1] - ts[i]) in seconds and converted to hours via /3600.0; intervals exceeding the gap threshold are excluded."
  ],
  "errors": []
}
```

### Why SE is interval-integrated, never instantaneous

For each consecutive sample pair `(t_i, t_{i+1})`:

```
dt_hours_i  = (t_{i+1} - t_i)_seconds / 3600
energy_kwh_i = 0.5 * (P_i + P_{i+1}) * dt_hours_i        # trapezoidal
volume_m3_i  = 0.5 * (Q_i + Q_{i+1}) * dt_hours_i        # trapezoidal
SE_bin       = Σ_i_in_bin energy_kwh_i  /  Σ_i_in_bin volume_m3_i
```

The bin SE is the ratio of integrated energy to integrated volume across
all kept intervals in the bin — the only definition that produces correct
kWh/m³ when flow and power vary across the bin. This is verified by a
known-answer test on a constant-signal fixture and by a known-answer test
on a linear-ramp fixture (`test_energy_volume_trapezoidal_on_known_constant_fixture`,
`test_energy_volume_trapezoidal_on_linear_ramp`).

## Valid-interval filtering with named reasons

Every excluded interval carries exactly one exclusion reason. Order of
precedence (first match wins): `non_positive_interval`, `gap_too_long`,
`nan_input`, `unprofiled_mode_other`, `pump_off`, `low_flow`,
`zero_or_negative_volume`. The bucket set is frozen — downstream consumers
can rely on the schema. Low-flow / pump-off are first-class filters:

| Filter | Condition |
|---|---|
| `non_positive_interval` | `dt ≤ 0` or `dt` is NaN |
| `gap_too_long` | `dt > 300 s` (Sprint-27 gap threshold) |
| `nan_input` | either flow or power is NaN at either endpoint |
| `unprofiled_mode_other` | mode at either endpoint is `other` (unprofiled) or `manual` (not in the auto envelope) |
| `pump_off` | `edge_status < 0.5` at either endpoint (or NaN) |
| `low_flow` | either-endpoint flow `< 1.0 m³/h` |
| `zero_or_negative_volume` | integrated volume is `≤ 0` or NaN |

The waterfall is asserted to sum correctly (`kept + excluded_total == total`)
both in code (gate criterion #3) and in the test
`test_waterfall_sums_correctly_with_each_reason_present`.

### Live waterfall on 2025 (real CSV)

```
total_intervals : 489,162
kept            : 267,392   (54.66 %)
excluded_total  : 221,770   (45.34 %)

by reason:
  non_positive_interval     :     80
  gap_too_long              :     19
  nan_input                 :  7,481
  unprofiled_mode_other     : 208,049   <-- dominant bucket; consistent with
                                             Sprint-27 mode profile
  pump_off                  :  6,020
  low_flow                  :    121
  zero_or_negative_volume   :      0
sums_correctly              : true
```

The 208,049 `unprofiled_mode_other` exclusions are the expected dominant
bucket — they are the rows the Sprint-27 mode profile already flagged as
neither `auto` nor confirmed `manual` (the PRD §10.1 Q1 disposition:
*"exclude from normal training and mark as unprofiled"*). The Pillar B
envelope is fitted to the auto-mode operating regime only; manual is folded
into the same exclusion bucket because it is the same product decision
(*not in the auto envelope*).

## 15-min and 30-min aggregation (reproducible)

Per window the engine bins kept intervals by `interval_start.floor(window)`,
sums energy and volume per bin, and computes the bin SE. Means of
speed/flow/power/demand/level/pressure are time-weighted by interval `dt`
so they correctly represent the bin's operating state, not just the
arithmetic mean of point samples.

```
window_15min: 18,764 operating points
window_30min:  9,414 operating points
seed:           0
reproducible:  true   (two runs produce identical counts AND identical per-bin SE)
```

Reproducibility is also asserted as a structural test
(`test_two_runs_produce_identical_operating_point_counts`,
`test_two_runs_produce_identical_se_values`).

## `OperatingPoint` substrate for Sprint 32

Each operating point carries everything Sprint 32 needs to do the
matched-condition search:

```
window_minutes, window_start, window_end, n_intervals_used,
energy_kwh, volume_m3, specific_energy_kwh_per_m3,
mean_speed_hz, mean_flow_m3_per_h, mean_power_kw,
mean_demand_m3_per_h, mean_level_m, mean_pressure_m_head,
advisory_only=True
```

Sample line from the head of the 15-min export:

```
15, 2025-03-06T10:00:00, 2025-03-06T10:15:00, 14,
32.003 kWh, 301.687 m3, 0.10608 kWh/m3,
41.7 Hz, 1294.48 m3/h, 137.32 kW,
1416.49 m3/h demand, 5.02 m level, 1.59 m_head pressure,
advisory_only=True
```

The two CSVs are written deterministically (sort by `bin_start`, no RNG):

* `data/eval/pillarB/operating_points_15min_2025.csv` (18,764 rows)
* `data/eval/pillarB/operating_points_30min_2025.csv` ( 9,414 rows)

## Acceptance gate — honest verdict

Gate version: `sprint31.unit_validity.v1`. Rule:

> Sprint 31 PASS iff: `units_confirmed` AND `se_from_interval_energy_and_volume`
> AND `exclusion_waterfall_sums_correctly` AND `aggregation_reproducible` AND
> `march_not_used_for_tuning`.

| # | Criterion | passed | Evidence |
|---|---|---|---|
| 1 | `units_confirmed` | PASS | every unit matches `AXIS_UNITS`; `errors=[]` |
| 2 | `se_from_interval_energy_and_volume` | PASS | SE is `Σ energy_kwh / Σ volume_m3`, never `P/Q` (conversion notes embedded; test `test_energy_volume_trapezoidal_on_*`) |
| 3 | `exclusion_waterfall_sums_correctly` | PASS | `267,392 + 221,770 == 489,162` |
| 4 | `aggregation_reproducible` | PASS | two runs identical: `{15:18764, 30:9414}` |
| 5 | `march_not_used_for_tuning` | PASS | only 2025 month keys in input; Sprint-27 leakage guard wired in via `assert_no_march_2026_in_keys` |

**Verdict: PASS.** A FAIL would be a valid, valuable outcome; this is not
that. Sprint 32 (matched-condition envelope) is unblocked.

## Cannot claim

Sprint 31 establishes that the **measurement substrate** for Pillar B is
correct and auditable. It deliberately does **not** claim:

* **Energy savings.** No advisories are emitted yet. The matched-condition
  envelope, MVPv1-log comparison, and conservative quantile envelopes are
  Sprint 32 work; the locked-March 2026 evaluation is Sprint 33.
* **Generalization beyond the auto envelope.** Manual operation and the
  unprofiled "other" bucket together account for 42.5 % of the year and
  are explicitly excluded; nothing in this artifact predicts their SE.
* **Tariff-weighted cost savings.** Tariff is a PRD-§10.1-Q6 optional
  offline input that is not present in this artifact. We report kWh/m³
  only.
* **Forecast quality.** Pillar A's prior holdout FAILs against persistence
  are unchanged; Pillar B does not forecast — it characterizes the
  realized historical envelope and identifies what an offline-conservative
  efficient envelope would look like (Sprint 32+).
* **Field-realizable efficiency.** Even the eventual Pillar B advisory is
  offline evidence of historical efficient operation. It is not, and never
  will be in this PRD, a setpoint command or live-control input.
* **Demand-semantic confidence (PRD Q4).** `node_demand` is forwarded as
  context on each `OperatingPoint`; its exact provenance
  (measured/forecast/derived/target) is still tracked as a Q4 risk and
  will need a sensitivity check in Sprint 32 if it ends up driving
  matched-condition decisions.
* **Valve-position correction.** `edge_valve_position` has 0 % coverage at
  this site (the masked axis), so the envelope cannot correct for hidden
  hydraulic confounding. Sprint 32 must reject low-confidence matches
  rather than extrapolate.

## Tests + regression

```
$ pytest tests/advisory/test_sprint31_specific_energy.py
............... 14 passed

$ pytest tests/
......... 2556 passed, 1 skipped in 129.10s
```

No regressions. The 14 new tests cover all five acceptance-gate criteria
plus the scorecard shape on a clean fixture and the
`OperatingPoint` Sprint-32-substrate contract.

## How to reproduce

```
$ PYTHONPATH=src python -m aquaoptima.advisory.specific_energy
sprint31 verdict: PASS
scorecard written to data/eval/pillarB/sprint31_unit_validity_scorecard.json
```

The 2025 CSV path resolves the same way as every other Pillar A artifact:
explicit `--csv` > `YILAN_2025_CSV` env > the built-in
`/home/hunter_lin/projects/yilan-site-model-testing/yearlong_drive/source1_2025.csv`.

---

SPRINT31_STATUS: COMPLETE
SPRINT31_GATE: PASS
