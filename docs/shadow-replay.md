# Cold-start replay / shadow dataset builder (Sprint 35)

Sprint 35 turns **offline telemetry rows** (Python mappings or CSV
rows) into a typed, deterministic
:class:`ShadowReplayDataset` keyed by canonical dPHM axis and id, on
top of the Sprint 34 :class:`TelemetryTagMap`. It is the second
read-only shadow-mode plumbing layer: Sprint 34 named the dPHM ids
operators see on the plant floor; Sprint 35 normalises offline
measurement *values* into canonical units against those names so a
future shadow-mode validation harness can join frames to the dPHM
:class:`Network` without touching a live OT system.

The Sprint 35 surface answers, given a loaded `Network`, a built
:class:`TelemetryTagMap`, and a sequence of offline rows:

- For each timestamp, what node pressure / edge flow / pump speed /
  status / power / etc. values are available?
- Which values were missing, invalid, stale, or out of range?
- What canonical units do those values use?
- Can future shadow-mode evaluation consume these frames without
  touching live OT systems?

No live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST adapter
is activated; no write / control / setpoint path is exposed; no
dPHM forward solve is invoked.

## Where it lives

`src/aquaoptima/dphm/shadow_replay.py`, re-exported through
`aquaoptima.dphm`.

## Public API

```python
from aquaoptima.dphm import (
    # Frozen dataclasses
    ShadowReplayDiagnostics,
    ShadowReplayFrame,
    ShadowReplayDataset,
    # Builder / loader
    build_shadow_replay_dataset,
    load_shadow_replay_csv,
    # Sprint 34 surface the builder consumes
    TelemetryTagSpec,
    TelemetryTagMap,
    build_telemetry_tag_map,
)
```

## Offline row shape

Each row is a plain Python mapping (`dict`, `MappingProxy`, etc.):

```python
{
    "timestamp": <any object>,           # required (key configurable)
    "PT_DISCHARGE_01": 1.05,             # operator-facing tag → value
    "FT_PUMP_01": 25.0,                  # … etc
    "PUMP_01_SPEED": 0.8,
    "PUMP_01_STATUS": "running",
}
```

- The `timestamp` key name is configurable via the
  `timestamp_key` keyword (defaults to `"timestamp"`).
- The timestamp object is forwarded verbatim into the frame — Sprint
  35 never parses it. The only operation Sprint 35 performs on a
  timestamp is an *optional* float / `datetime` subtraction for the
  staleness check.
- Tags absent from the row produce a warning (not an error).
- Tags whose value is `None` produce a warning (not an error).
- Tags whose value is non-numeric for a numeric axis (or unrecognised
  for the status axis) produce an *error* — strict mode raises,
  non-strict mode omits the sample and records the error string.

## API shape

```python
build_shadow_replay_dataset(
    rows: Iterable[Mapping[str, object]],
    tag_map: TelemetryTagMap,
    *,
    timestamp_key: str = "timestamp",
    strict: bool = True,
    max_stale_seconds: float | None = None,
) -> ShadowReplayDataset
```

```python
load_shadow_replay_csv(
    path,
    tag_map,
    *,
    timestamp_key: str = "timestamp",
    strict: bool = True,
    max_stale_seconds: float | None = None,
) -> ShadowReplayDataset
```

The CSV loader uses the stdlib `csv.DictReader`; no pandas
dependency is introduced. Empty cells are treated as missing.

## Unit conversion

Sprint 34 declared the *accepted unit family* per measurement.
Sprint 35 implements the explicit value conversion to canonical
units.

| Measurement      | Canonical | Input          | Conversion                          |
|------------------|-----------|----------------|-------------------------------------|
| `pressure`       | `m`       | `m`, `meter`   | identity                            |
| `pressure`       | `m`       | `bar`          | × 10.197162129779283                |
| `pressure`       | `m`       | `kpa`          | × 0.10197162129779283               |
| `pressure`       | `m`       | `psi`          | × 0.703249614902                    |
| `flow`/`demand`  | `m3/s`    | `m3/s`         | identity                            |
| `flow`/`demand`  | `m3/s`    | `l/s`          | × 0.001                             |
| `flow`/`demand`  | `m3/s`    | `gpm`          | × 6.309019640343866e-5              |
| `level`          | `m`       | `m`, `meter`   | identity                            |
| `level`          | `m`       | `ft`           | × 0.3048                            |
| `pump_speed`     | `fraction`| `fraction`     | identity                            |
| `pump_speed`     | `fraction`| `percent`      | / 100                               |
| `pump_speed`     | `fraction`| `rpm`          | **conservative warning + omitted**  |
| `valve_position` | `fraction`| `fraction`     | identity                            |
| `valve_position` | `fraction`| `percent`      | / 100                               |
| `power`          | `kw`      | `kw`           | identity                            |
| `power`          | `kw`      | `w`            | / 1000                              |
| `status`         | `boolean` | `bool`, `0/1`, ...| see status parser below          |

### Status parser

A status sample is accepted as `bool`, numeric `0` / `1`
(`int` or `float`), or one of the case-insensitive strings:

- truthy: `"true"`, `"1"`, `"on"`, `"open"`, `"running"`,
  `"active"`, `"yes"`
- falsy:  `"false"`, `"0"`, `"off"`, `"closed"`, `"stopped"`,
  `"inactive"`, `"no"`

Anything else (including unrecognised strings, numeric values
outside `{0, 1}`, NaN / inf, or unsupported object types) is an
*error* — strict mode raises; non-strict mode omits the sample and
records the error string in diagnostics.

### Conservative behaviour for `rpm` pump speed

Sprint 34's schema family accepted `rpm` as a unit for `pump_speed`
because some sites only publish raw shaft RPM. Sprint 35's value
path cannot translate RPM to a canonical fraction without a rated
speed — a value Sprint 34 deliberately does *not* model. Rather
than invent one, Sprint 35 emits a **warning** and omits the
sample from the frame. The behaviour is the same in strict and
non-strict mode (the conservative path is a warning, not an error)
so existing pipelines that already declare `rpm` continue to load
and produce a dataset; the diagnostic surface tells downstream
consumers that the pump-speed axis is unavailable for those tags.

## Strict vs non-strict behaviour

`build_shadow_replay_dataset(..., strict=True)` (default) raises
`ValueError` if any of the following structural errors are
encountered:

- a row is not a mapping;
- a row is missing the `timestamp` key, or its timestamp is `None`;
- a numeric sample cannot be coerced to a finite float (including
  bare booleans, empty strings, NaN, inf, or types other than `int`
  / `float` / `str`);
- a status sample is not one of the accepted forms above;
- a unit is in the Sprint 34 accepted family but is unknown to the
  Sprint 35 conversion table (a programmer error — currently never
  fires given the table above).

`strict=False` returns a populated dataset whose
`diagnostics.errors` lists every offending sample / row in input
order; the offending sample is *omitted from the frame* (so the
axis mapping for that target id is simply absent). Whole rows are
only omitted when the timestamp itself cannot be read.

Missing / `None` tag values and `rpm` pump-speed declarations are
**warnings**, not errors. They never raise in strict mode; they
appear in `diagnostics.warnings`.

## Diagnostics semantics

- `ShadowReplayFrame.diagnostics` carries per-row diagnostics
  (warnings / errors attached to a specific frame).
- `ShadowReplayDataset.diagnostics` carries dataset-level
  diagnostics (row-level errors that prevented a frame from being
  built, such as missing-timestamp rows, plus the per-frame
  warnings / errors echoed at the dataset level so consumers can
  filter without iterating every frame).
- Diagnostics are **deterministic**: the same inputs in the same
  order produce the same warning / error tuples.

## `max_stale_seconds`

`max_stale_seconds` is optional and, when supplied, must be
strictly positive. After each row beyond the first, Sprint 35 tries
to compute `current_ts - prev_ts` (`float` arithmetic for numeric
timestamps, `total_seconds()` for `datetime` deltas). When the gap
exceeds the threshold, a warning is appended to
`dataset.diagnostics.warnings`.

When the two timestamps cannot be subtracted (e.g. arbitrary
strings), the check is *silently skipped* — Sprint 35 never invents
a parser.

## Read-only contract

The builder and CSV loader:

- never mutate `rows`, `tag_map`, or any tensor on the originating
  `Network`;
- never open a network socket / process / live binding;
- read the CSV file at the supplied path read-only;
- never invoke the dPHM forward solver;
- never publish, write, or otherwise contact an external system.

Every dataclass on the public surface is `frozen=True`; every
top-level collection field on `ShadowReplayDataset` is an immutable
tuple. (The per-axis mappings on `ShadowReplayFrame` are freshly
allocated `dict` objects — a typing concession; callers that need
a guaranteed-immutable view can wrap them in
`types.MappingProxyType`. The dataclass itself is frozen, so the
*binding* cannot be rewritten.)

## Safety boundary

This sprint adds **no** live binding. In particular:

- no SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST adapter
  is imported, registered, or polled;
- no write / control / setpoint path is exposed;
- no dPHM forward-solve comparator is invoked — Sprint 35 only
  normalises and routes telemetry values, never simulates;
- no advisory / control recommendation is surfaced;
- no dPL calibration is performed — Sprint 36;
- no ONNX / TensorRT / Jetson deployment is performed;
- no production savings / control claim is made.

The Sprint 35 builder sits behind the same shadow-mode safety
boundary as Sprints 23–34: a typed, deterministic, read-only
offline value-normalisation surface.

## Worked example

```python
from aquaoptima.dphm import (
    TelemetryTagSpec,
    TELEMETRY_TARGET_EDGE,
    TELEMETRY_TARGET_NODE,
    TELEMETRY_ROLE_CONTROL_INPUT,
    build_telemetry_tag_map,
    build_shadow_replay_dataset,
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
        "PT_DISCHARGE_01": 4.5,    # bar → m
        "FT_PUMP_01": 18.0,        # L/s → m3/s
        "PUMP_01_SPEED": 80.0,     # percent → fraction
    },
    # …
]
dataset = build_shadow_replay_dataset(rows, tag_map)
frame = dataset.frames[0]
assert frame.node_pressure[2] == 4.5 * 10.197162129779283
assert frame.edge_flow[5] == 0.018
assert frame.edge_pump_speed[5] == 0.8
```
