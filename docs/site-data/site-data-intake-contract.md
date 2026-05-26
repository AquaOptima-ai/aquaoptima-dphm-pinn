# Site Data Intake Contract (Sprint 53)

Sprint 53 starts the **Site Data Validation / dPHM Readiness** phase.
AMAX-specific work is paused until AMAX-8580 documentation and vendor
details are mature; in the meantime AquaOptima tests
dPHM / dPL / dPHM-PINN **without AMAX** and **without live OT
integration** by reading an exported / uploaded customer site dataset.

This document defines the **site data intake contract**: what a
customer or operator must supply so AquaOptima can grade whether the
dataset is `good`, `usable`, `poor`, or `blocked` for model testing.

## Boundary (non-negotiable)

Sprint 53 is read-only and hardware-independent. It introduces:

- no live OT binding
- no PLC/PAC/SCADA write
- no command emission
- no setpoint output
- no control-loop closure
- no direct VFD / pump / actuator control
- no live OPC UA / Modbus / CODESYS / SCADA / PLC / MQTT / HTTP /
  database / message-broker client
- no Edge Runtime daemon / service
- no AMAX hardware probing
- no credentials, passwords, tokens, API keys, license keys, or
  connection secrets in docs, tests, or source

AquaOptima reads only the supplied export. The site PLC retains direct
VFD / pump / actuator authority.

## SDK module

The contract lives in
[`src/aquaoptima_contracts/site_data/intake.py`](../../src/aquaoptima_contracts/site_data/intake.py).
Public surface:

- `SiteDataFieldRequirement` — one expected field (id, display name,
  telemetry role, required / optional, accepted units, expected type,
  description, example tags, quality notes).
- `SiteDataExportSchema` — one minimum viable export shape (schema id,
  site type, timestamp field, timezone policy, sampling policy,
  required + optional fields, unit normalisation notes, source
  evidence notes, safety notes).
- `SiteTagMapTemplate` — customer / site tag → canonical AquaOptima
  pump-system role mapping (timestamp, pump_status, pump_speed_rpm,
  suction_pressure, discharge_pressure, flow_rate, tank_level,
  valve_status, pump_power_kw, current_amp, alarm_state,
  operating_mode, …).
- `SiteDataQualityRule` — one data-quality check (coverage,
  missingness, unit presence, timestamp monotonicity, duplicate
  timestamps, sampling interval drift, pressure / flow plausibility,
  pump state availability, timezone clarity).
- `SiteDataReadinessAssessment` — grade (`good` / `usable` / `poor` /
  `blocked`), blocking gaps, warnings, available fields, missing
  required fields, optional fields present, recommendation, and
  safety notes.

Canonical helpers (`default_pump_site_data_export_schema`,
`default_site_tag_map_template`, `default_site_data_quality_rules`,
`assess_site_data_readiness`) carry the Sprint 53 defaults.

## Exported / uploaded site data only

AquaOptima accepts site data through one of the following channels:

| Channel              | Notes                                                          |
|----------------------|----------------------------------------------------------------|
| CSV                  | One row per sample; one column per tag; UTF-8 text             |
| Parquet              | Same column layout as CSV; preferred for large exports         |
| Historian export     | OSIsoft PI / AVEVA / OFS / IP.21 / etc. point-history dumps    |
| SCADA archive dump   | Wonderware, iFIX, Ignition, Citect, WinCC archive exports      |

Every channel is **batch / file-based**. AquaOptima does not open a
network connection to a historian, SCADA server, OPC UA endpoint, or
controller during Sprint 53. The site PLC / SCADA system has no
inbound write surface from AquaOptima.

## Required vs optional fields

The default schema (`default_pump_site_data_export_schema`) sets the
following minimum viable shape:

**Required**

- `timestamp` — monotonic ISO-8601 timestamps with a clearly declared
  timezone (UTC or IANA label).
- `pump_status` *(or `pump_running`)* — at least one pump on / off
  indicator must be present.
- `discharge_pressure` *(or another pressure channel)* — at least one
  pressure measurement must be present. The default required field is
  `discharge_pressure`; `suction_pressure` is an acceptable substitute
  if the customer cannot export discharge pressure.

**Optional (strongly recommended)**

- `pump_speed_rpm` / `vfd_frequency_hz` / `speed_percent` — at least
  one speed proxy for VFD-driven pumps.
- `suction_pressure`
- `flow_rate` *(or `tank_level` trend if no flow meter exists)*
- `valve_status`
- `pump_power_kw`
- `current_amp`
- `energy_kwh`
- `alarm_state`
- `trip_state`
- `operating_mode` (manual / auto / cascade / remote)
- `manual_auto_mode`
- `weather_demand_proxy` (ambient temperature, rainfall, downstream
  demand)

## Tag-map template

See
[`site-data-request-template.md`](site-data-request-template.md) for
the customer-facing request language. The SDK ships a tag-map template
under `default_site_tag_map_template()` that pairs every canonical
pump-system role with an example tag and notes. The template is
hardware-independent: it does not assume AMAX, CODESYS, OPC UA, or any
vendor controller.

## CSV / historian / SCADA export expectations

- **Encoding.** UTF-8 text. No BOM. Newline-delimited rows.
- **Timestamps.** ISO-8601 strongly preferred. Either UTC or an
  explicit IANA timezone label per series.
- **Sampling.** Target interval 1 s to 60 s. Irregular sampling is
  acceptable; the pipeline will measure drift and flag it.
- **Units.** Pressure and flow / tank-level channels must declare
  units either in the column header or in the tag-map spreadsheet.
- **Status channels.** Booleans or named enums. Free-text status is
  accepted but normalised to a canonical token before training.
- **No secrets.** Exports must not contain passwords, tokens, API
  keys, license keys, or connection strings.

## Unit normalisation

The pipeline normalises:

- Pressure: bar, kPa, psi, m, mWC → one canonical unit.
- Flow: m³/h, L/s, gpm, m³/s → one canonical unit.
- Speed: rpm, Hz, percent (at least one required for VFD pumps).

## Minimum viable dataset (rule of thumb)

A dataset is **good** when it carries:

- `timestamp` with a declared timezone,
- at least one pump-state channel (`pump_status` or `pump_running`),
- at least one pump-speed proxy (`pump_speed_rpm` /
  `vfd_frequency_hz` / `speed_percent`),
- at least one pressure channel (`discharge_pressure` and/or
  `suction_pressure`),
- at least one hydraulic-output channel (`flow_rate` and/or
  `tank_level`),
- declared units for pressure and flow / tank-level channels,
- ideally also one of `pump_power_kw`, `current_amp`, `alarm_state`,
  `operating_mode`.

A **usable** dataset still carries timestamp, pump state, at least one
pressure channel, at least one flow or tank-level channel, declared
units, and a declared timezone — but is missing the speed proxy or the
discharge / flow combination.

A **poor** dataset carries timestamp and pump state but lacks the
hydraulic measurements or unit / timezone declarations needed for
confident dPHM testing.

A **blocked** dataset is missing the timestamp series, missing all
pump-state channels, or missing every hydraulic measurement.

## Readiness grading

Use `assess_site_data_readiness(available_fields, *, schema=...,
units_declared=..., timezone_declared=...)` to grade a candidate
dataset. The function returns a `SiteDataReadinessAssessment` whose
`grade` field is `good`, `usable`, `poor`, or `blocked`. See
[`site-data-quality-grading.md`](site-data-quality-grading.md) for the
full grading rules.

## Operator-facing data request

See
[`site-data-request-template.md`](site-data-request-template.md) for
copy-pasteable language AquaOptima can hand to a customer or operator.
