# dPL calibration prototype (Sprint 36)

Sprint 36 closes the offline / read-only loop opened by Sprints 34
and 35: it consumes the Sprint 35
:class:`ShadowReplayDataset` (canonicalised offline frames keyed by
dPHM axis and id) together with a per-frame predictions sequence,
and emits a frozen :class:`DPLCalibrationLossReport` carrying the
per-observation residuals, per-axis MSE / MAE, and a deterministic
weighted MSE suitable as a calibration loss term for a future dPL
training loop.

The Sprint 36 surface answers, given a Sprint 35 dataset and any
sequence of supplied predictions:

- For each frame, what replay observations are available?
- For each `(axis, target_id)`, what is the residual against the
  supplied prediction?
- Which observations were missing from the predictions?
- Which predictions were unused?
- What is the weighted MSE / per-axis MSE / per-axis MAE the future
  dPL training loop would minimise?
- Can future dPL calibration loops consume this without touching
  live OT systems?

No live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST adapter
is activated; no write / control / setpoint path is exposed; no
dPHM forward solve is invoked; no advisory output is produced.

## Where it lives

`src/aquaoptima/dphm/dpl_calibration.py`, re-exported through
`aquaoptima.dphm`.

## Public API

```python
from aquaoptima.dphm import (
    # Frozen dataclasses
    DPLCalibrationDiagnostics,
    DPLResidual,
    DPLCalibrationLossReport,
    # Builder
    build_dpl_calibration_loss_report,
    # Axis constants
    DPL_AXES,
    DPL_NUMERIC_AXES,
    DPL_STATUS_AXES,
    # Sprint 35 surface this consumes
    ShadowReplayDataset,
)
```

## Predictions input shape

```python
predictions = [
    {
        "node_pressure":      {0: 42.0, 1: 38.5},
        "edge_flow":          {0: 0.012},
        "edge_pump_speed":    {0: 0.75},
    },
    # ... one mapping per replay frame, in the same order
]
```

- The outer sequence has one entry per replay frame, in the same
  order as `replay.frames`.
- Each entry is a `Mapping[str, Mapping[int, value]]` keyed by the
  canonical dPHM axis token (see `DPL_AXES`) and then by the dPHM
  zero-based `target_id`.
- Predicted values must already be in the same canonical unit as
  Sprint 35 emits (`m` for pressure / level, `m3/s` for flow /
  demand, `fraction` for pump speed / valve position, `kW` for
  power, `bool` / `0|1` for status). Sprint 36 deliberately does
  *not* re-run any unit conversion.

## API shape

```python
def build_dpl_calibration_loss_report(
    replay: ShadowReplayDataset,
    predictions: Sequence[Mapping[str, Mapping[int, float]]],
    *,
    axis_weights: Mapping[str, float] | None = None,
    strict: bool = True,
) -> DPLCalibrationLossReport: ...
```

## Supported axes

| Axis                  | Source field on `ShadowReplayFrame` | Kind     |
|-----------------------|-------------------------------------|----------|
| `node_pressure`       | `node_pressure`                     | numeric  |
| `node_demand`         | `node_demand`                       | numeric  |
| `node_level`          | `node_level`                        | numeric  |
| `node_status`         | `node_status`                       | status   |
| `edge_flow`           | `edge_flow`                         | numeric  |
| `edge_pump_speed`     | `edge_pump_speed`                   | numeric  |
| `edge_status`         | `edge_status`                       | status   |
| `edge_power`          | `edge_power`                        | numeric  |
| `edge_valve_position` | `edge_valve_position`               | numeric  |

Status axes (`node_status`, `edge_status`) accept `bool` or numeric
`0` / `1` on both the observation and prediction side; they are
coerced to `0.0` / `1.0` before residual math. Numeric / out-of-set
values are rejected with the same strict / non-strict contract as
other malformed predictions.

## Residual / loss formulas

For every `(frame_index, axis, target_id)` triple where the replay
frame carries an observation and the supplied prediction carries a
matching value:

```
residual           = predicted - observed                 (per record)
mse_by_axis[axis]  = mean( residual ** 2 ) over residuals on that axis
mae_by_axis[axis]  = mean( abs(residual) ) over residuals on that axis
```

The weighted MSE aggregates across all residuals using the axis
weights (default `1.0`):

```
weighted_mse = sum_i ( weight(axis_i) * residual_i ** 2 )
               -----------------------------------------
                          sum_i weight(axis_i)
```

When `observation_count == 0` (no residuals), `weighted_mse` is
exactly `0.0`. `mse_by_axis` / `mae_by_axis` only carry keys for
axes that actually produced at least one residual.

The residuals tuple is in deterministic order:

1. frame index (outer);
2. canonical axis order from `DPL_AXES` (middle);
3. ascending `target_id` (inner).

Two builds on equal inputs return equal reports.

## Strict vs non-strict behaviour

`build_dpl_calibration_loss_report(..., strict=True)` (the default)
raises `ValueError` if any of the following structural mismatches
are detected:

- `len(predictions) != len(replay.frames)`;
- a predicted value is missing for an observed
  `(axis, target_id)`;
- a supplied prediction is not a `Mapping` for a frame, or the
  per-axis sub-value is not a `Mapping`;
- a supplied predicted value cannot be coerced to a finite float
  (numeric axes) or to `0.0` / `1.0` (status axes);
- `predictions` itself is not a `Sequence`.

`strict=False` returns a populated report whose
`diagnostics.errors` lists every offending pair / row in input
order; the offending residual is *omitted* from the report. The
overlapping prefix of `predictions` and `replay.frames` is still
processed deterministically.

Extra predictions that do not match any observation are **always**
a *warning*, never an error. They appear in
`diagnostics.warnings`, and the prediction is silently dropped.
Predictions that name an axis outside `DPL_AXES` are also warnings.

`axis_weights` validation is **not** gated by `strict`: negative,
zero, non-finite, or unknown-axis weights are always programmer
errors and always raise `ValueError`. This avoids silently
collapsing a weighted MSE into the wrong scalar.

## Read-only contract

The builder:

- never mutates `replay` or `predictions` (verified by deep-copy
  snapshot in the tests);
- never opens a socket / process / live binding;
- never invokes the dPHM forward solver;
- never publishes, writes, or otherwise contacts an external
  system.

Every dataclass on the public surface is `frozen=True`. The
`residuals` tuple is an immutable Python tuple. The `mse_by_axis` /
`mae_by_axis` mappings are freshly allocated `dict` objects (a
typing concession matching Sprint 35's per-axis mappings); the
dataclass binding itself is frozen.

## Safety boundary

This sprint adds **no** live binding. In particular:

- no SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST adapter
  is imported, registered, or polled;
- no write / control / setpoint path is exposed;
- no dPHM forward-solve comparator is invoked — Sprint 36 only
  *measures* the disagreement between supplied predictions and
  Sprint 35 offline observations;
- no advisory / control recommendation is surfaced;
- no setpoint optimization is performed;
- no training-loop / optimizer integration is performed — Sprint
  36 stops at deterministic loss reporting;
- no ONNX / TensorRT / Jetson deployment is performed;
- no production savings / control claim is made.

A future dPL training loop would consume the returned residuals /
weighted MSE through its own loss API; that training loop is
**out of scope** for Sprint 36.

## Worked example

```python
from aquaoptima.dphm import (
    TelemetryTagSpec,
    TELEMETRY_TARGET_EDGE,
    TELEMETRY_TARGET_NODE,
    TELEMETRY_ROLE_CONTROL_INPUT,
    build_telemetry_tag_map,
    build_shadow_replay_dataset,
    build_dpl_calibration_loss_report,
    load_network_from_inp,
)

network, _ = load_network_from_inp(inp_path, return_diagnostics=True)
specs = [
    TelemetryTagSpec("PT_DISCHARGE_01", TELEMETRY_TARGET_NODE, 2, "pressure", "bar"),
    TelemetryTagSpec("FT_PUMP_01",      TELEMETRY_TARGET_EDGE, 5, "flow",     "l/s"),
    TelemetryTagSpec(
        "PUMP_01_SPEED",
        TELEMETRY_TARGET_EDGE,
        5,
        "pump_speed",
        "percent",
        role=TELEMETRY_ROLE_CONTROL_INPUT,
    ),
]
tag_map = build_telemetry_tag_map(specs, network)
rows = [
    {
        "timestamp": "2026-05-23T00:00:00Z",
        "PT_DISCHARGE_01": 4.5,    # bar  → m
        "FT_PUMP_01": 18.0,        # L/s  → m3/s
        "PUMP_01_SPEED": 80.0,     # %    → fraction
    },
]
replay = build_shadow_replay_dataset(rows, tag_map)

# A future model / dPHM forward-solve would supply these. The
# Sprint 36 builder is agnostic to their origin — it only checks
# shape and units.
predictions = [
    {
        "node_pressure":   {2: 45.0},   # m
        "edge_flow":       {5: 0.020},  # m3/s
        "edge_pump_speed": {5: 0.75},   # fraction
    },
]
report = build_dpl_calibration_loss_report(
    replay,
    predictions,
    axis_weights={"node_pressure": 1.0, "edge_flow": 100.0},
)

assert report.observation_count == 3
print(report.mse_by_axis)        # per-axis MSE
print(report.mae_by_axis)        # per-axis MAE
print(report.weighted_mse)       # scalar suitable as calibration loss
```
