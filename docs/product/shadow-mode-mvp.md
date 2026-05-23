# Shadow-mode MVP

## Definition

Shadow mode is a read-only operating mode where dPHM/dPHM-PINN observes historical or live-mirrored telemetry, runs model/replay/evaluation logic, logs what it would infer or recommend, and compares against actual operation without controlling the plant.

## Non-negotiable boundary

Shadow mode does not write to PLC, PAC, SCADA, VFDs, valves, pumps, historian command topics, or operator setpoints.

## MVP capabilities

- Import-quality report from EPANET diagnostics.
- Telemetry tag-map adapter for canonical node/edge axes.
- Offline replay dataset builder from historical telemetry rows.
- Calibration-loss prototype against replay observations.
- Safety contract skeleton for future advisory output.
- Runtime harness for read-only execution and reporting.
- Export/deployment packaging with versioned artifacts.

## Required evidence before advisory phase

- Stable residuals over replay windows.
- Deterministic diagnostics for missing/invalid/stale telemetry.
- Known unsupported EPANET semantics visible in reports.
- Clear distinction between native edges and surrogate approximations.
- Operator-reviewable safety limits and rejection reasons.
