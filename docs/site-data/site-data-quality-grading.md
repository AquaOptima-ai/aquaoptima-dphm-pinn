# Site Data Quality Grading (Sprint 53)

This document defines how AquaOptima grades an exported / uploaded
pump-system dataset against the Sprint 53 site-data intake contract.
Grading is performed by
`aquaoptima_contracts.assess_site_data_readiness(...)` and returns a
`SiteDataReadinessAssessment`. The grade determines whether the
dataset is ready for dPHM testing without AMAX and without live OT
integration.

## Boundary

Sprint 53 grading is hardware-independent and read-only. It introduces:

- no live OT binding
- no PLC/PAC/SCADA write
- no command emission
- no setpoint output
- no control-loop closure
- no AMAX hardware probing

AquaOptima evaluates the supplied export. The site PLC retains direct
VFD / pump / actuator authority.

## Grade vocabulary

```
DPHM_READINESS_GRADE_GOOD    = "good"
DPHM_READINESS_GRADE_USABLE  = "usable"
DPHM_READINESS_GRADE_POOR    = "poor"
DPHM_READINESS_GRADE_BLOCKED = "blocked"
```

## Inputs

`assess_site_data_readiness(available_fields, *, schema=None,
units_declared=False, timezone_declared=False)`.

- `available_fields`: canonical role tokens that the dataset
  actually contains (e.g. `("timestamp", "pump_status",
  "discharge_pressure", "flow_rate", "pump_speed_rpm")`).
- `schema`: a `SiteDataExportSchema`. Defaults to
  `default_pump_site_data_export_schema()`.
- `units_declared`: whether pressure and flow / tank-level units have
  been declared (in the column header or tag-map spreadsheet).
- `timezone_declared`: whether the timestamp timezone is unambiguous
  (UTC or IANA label).

## Grading rules

The function evaluates the dataset in this deterministic order:

1. **Blocking gaps.** The grade is `blocked` if **any** of the
   following are true:
   - `timestamp` is not in `available_fields`;
   - none of `pump_status` / `pump_running` are present;
   - none of `discharge_pressure` / `suction_pressure` / `flow_rate`
     / `tank_level` are present.
   When the grade is `blocked`, the assessment carries a non-empty
   `blocking_gaps` tuple naming each missing channel class.
2. **`good`.** No blocking gaps **and**:
   - at least one pressure channel (`discharge_pressure` or
     `suction_pressure`),
   - at least one of `flow_rate` or `tank_level`,
   - `discharge_pressure` is present,
   - `flow_rate` is present,
   - at least one pump-state channel,
   - at least one speed proxy (`pump_speed_rpm` / `vfd_frequency_hz`
     / `speed_percent`),
   - `units_declared` is `True`,
   - `timezone_declared` is `True`.
3. **`usable`.** No blocking gaps and the dataset has at least one
   pressure channel, at least one flow or tank-level channel, at
   least one pump-state channel, declared units, and a declared
   timezone — but does not satisfy the full `good` criteria.
4. **`poor`.** No blocking gaps, but key optional / hydraulic
   channels or unit / timezone declarations are missing. The data is
   inspectable but dPHM testing is not confident.

## Warnings

Warnings never escalate the grade to `blocked` on their own (a
blocking gap does that). Typical warnings include:

- `timezone policy not declared` — even if a timestamp series is
  present, the `timezone_clarity` quality rule will block import
  until the timezone is confirmed.
- `pressure channel present but units not declared` — the
  `unit_presence` quality rule will block import until units are
  confirmed.
- `flow or tank-level channel present but units not declared` —
  same as above for flow / level.
- `no pump speed proxy exported` — VFD-driven pumps are harder to
  model without a speed channel.
- `flow_rate missing; tank_level trend will be used as the
  hydraulic-output substitute`.
- `ignored unknown field tokens: ...` — any unknown tokens you pass
  in are listed here so the caller can map them later.

## Quality rules

`default_site_data_quality_rules()` returns ten canonical checks the
import pipeline applies after the readiness verdict:

| Rule id                       | Check kind                  | Severity  |
|-------------------------------|-----------------------------|-----------|
| `coverage_min_window`         | coverage                    | blocking  |
| `missingness_per_channel`     | missingness                 | warning   |
| `unit_presence_required`      | unit_presence               | blocking  |
| `timestamp_monotonicity`      | timestamp_monotonicity      | blocking  |
| `duplicate_timestamps`        | duplicate_timestamps        | blocking  |
| `sampling_interval_drift`     | sampling_interval_drift     | warning   |
| `pressure_plausibility`       | pressure_plausibility       | warning   |
| `flow_plausibility`           | flow_plausibility           | warning   |
| `pump_state_availability`     | pump_state_availability     | blocking  |
| `timezone_clarity`            | timezone_clarity            | blocking  |

`blocking` severities prevent training until resolved; `warning`
severities are captured as caveats on any model-quality metrics
AquaOptima reports.

## Worked examples

**Example 1 — good.** A pump station exports timestamp (UTC),
`pump_status`, `pump_speed_rpm`, `discharge_pressure` (bar),
`flow_rate` (m³/h), `pump_power_kw` for 14 days at 1 s cadence. Units
and timezone are declared. Grade: `good`.

**Example 2 — usable.** Same station as Example 1 but without
`pump_speed_rpm`, `vfd_frequency_hz`, or `speed_percent`. Grade:
`usable`. Warning: `no pump speed proxy exported`.

**Example 3 — poor.** The dataset has timestamp, `pump_status`, and
`discharge_pressure` but no `flow_rate` or `tank_level`. Grade:
`poor`. (No blocking gap because the schema allows pressure-only
datasets, but dPHM training cannot fit hydraulic output.) Wait —
that case is actually `blocked` because no hydraulic-output channel
is present; see Example 5. **A real `poor` case:** timestamp,
`pump_status`, `discharge_pressure`, `tank_level`, but units are
**not** declared. Grade: `poor` (no blocking gap, but missing unit
declaration disqualifies `usable`).

**Example 4 — blocked, no timestamp.** Dataset has every other
channel but no timestamp series. Grade: `blocked`. Blocking gap:
`timestamp series is missing`.

**Example 5 — blocked, no hydraulic channels.** Timestamp,
`pump_status`, and `pump_speed_rpm` only — no pressure, no flow, no
tank level. Grade: `blocked`. Blocking gap: `all hydraulic channels
are missing (no pressure, flow, or tank-level data)`.

**Example 6 — blocked, no pump state.** Timestamp,
`discharge_pressure`, `flow_rate`, units and timezone declared, but
no `pump_status` or `pump_running`. Grade: `blocked`. Blocking gap:
`pump state channel is missing (pump_status or pump_running)`.
