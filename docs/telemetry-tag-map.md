# Telemetry tag-map adapter (Sprint 34)

Sprint 34 adds the first read-only shadow-mode plumbing layer between
operator-facing telemetry tags and the canonical dPHM `Network`
topology imported by Sprints 11–33. It does **not** activate any live
SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST adapter, does
**not** convert a measurement *value*, and does **not** expose a
write / control / setpoint path of any kind.

The Sprint 33 import-quality report names every dPHM node / edge
produced from a surrogate (PRV / TCV) or from an implicitly-pinned
boundary (reservoirs / tanks). The Sprint 34 tag-map lets an operator
*name* those dPHM ids with the labels they actually see on the plant
floor (`PT_DISCHARGE_01`, `FT_PUMP_01`, `PUMP_01_SPEED`) so a future
shadow-mode dataset builder (Sprint 35) can join offline telemetry
frames against the same canonical schema.

## Where it lives

`src/aquaoptima/dphm/telemetry_tag_map.py`, re-exported through
`aquaoptima.dphm`. The Sprint 4.5 broader `SiteTagMap` /
`TagDefinition` surface in `aquaoptima.dataio` is untouched —
Sprint 34's adapter is the dPHM-side metadata shim only.

## Public API

```python
from aquaoptima.dphm import (
    # Frozen dataclasses
    TelemetryTagSpec,
    CanonicalTelemetryTag,
    TelemetryTagMapDiagnostics,
    TelemetryTagMap,
    # Builder / loader
    build_telemetry_tag_map,
    load_telemetry_tag_map_json,
    # Canonical target-type tokens
    TELEMETRY_TARGET_NODE,
    TELEMETRY_TARGET_EDGE,
    TELEMETRY_TARGET_TYPES,
    # Canonical measurement tokens
    TELEMETRY_MEASUREMENT_PRESSURE,
    TELEMETRY_MEASUREMENT_FLOW,
    TELEMETRY_MEASUREMENT_DEMAND,
    TELEMETRY_MEASUREMENT_PUMP_SPEED,
    TELEMETRY_MEASUREMENT_LEVEL,
    TELEMETRY_MEASUREMENT_STATUS,
    TELEMETRY_MEASUREMENT_POWER,
    TELEMETRY_MEASUREMENT_VALVE_POSITION,
    TELEMETRY_MEASUREMENTS,
    # Canonical role tokens
    TELEMETRY_ROLE_OBSERVED,
    TELEMETRY_ROLE_CONTROL_INPUT,
    TELEMETRY_ROLE_DERIVED,
    TELEMETRY_ROLE_QUALITY,
    TELEMETRY_ROLES,
    # Canonical axis tokens
    TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_AXIS_NODE_DEMAND,
    TELEMETRY_AXIS_NODE_LEVEL,
    TELEMETRY_AXIS_NODE_STATUS,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_EDGE_STATUS,
    TELEMETRY_AXIS_EDGE_POWER,
    TELEMETRY_AXIS_EDGE_VALVE_POSITION,
    TELEMETRY_AXES,
)
```

### Example

```python
from aquaoptima.dphm import (
    TelemetryTagSpec,
    TELEMETRY_TARGET_EDGE,
    TELEMETRY_TARGET_NODE,
    TELEMETRY_ROLE_CONTROL_INPUT,
    build_telemetry_tag_map,
    load_network_from_inp,
)

network, _ = load_network_from_inp(inp_path, return_diagnostics=True)
specs = [
    TelemetryTagSpec("PT_DISCHARGE_01", TELEMETRY_TARGET_NODE, 2, "pressure", "m"),
    TelemetryTagSpec("FT_PUMP_01",      TELEMETRY_TARGET_EDGE, 5, "flow",     "m3/s"),
    TelemetryTagSpec(
        "PUMP_01_SPEED",
        TELEMETRY_TARGET_EDGE,
        5,
        "pump_speed",
        "fraction",
        role=TELEMETRY_ROLE_CONTROL_INPUT,
    ),
]
tag_map = build_telemetry_tag_map(specs, network)
for ctag in tag_map.tags:
    print(ctag.tag, "->", ctag.axis, ctag.canonical_unit)
```

## Canonical schema

### Measurements → canonical units

| Measurement      | Canonical unit | Accepted unit family               |
|------------------|----------------|------------------------------------|
| `pressure`       | `m`            | `m`, `meter`, `bar`, `psi`, `kpa`  |
| `flow`           | `m3/s`         | `m3/s`, `l/s`, `gpm`               |
| `demand`         | `m3/s`         | `m3/s`, `l/s`, `gpm`               |
| `pump_speed`     | `fraction`     | `fraction`, `percent`, `rpm`       |
| `level`          | `m`            | `m`, `meter`, `ft`                 |
| `status`         | `boolean`      | `boolean`, `bool`, `0/1`           |
| `power`          | `kw`           | `kw`, `w`                          |
| `valve_position` | `fraction`     | `percent`, `fraction`              |

Units are compared case-insensitively against the lower-cased input.
No value conversion is performed in Sprint 34 — `canonical_unit` is
*metadata* that a future Sprint 35 replay / shadow dataset builder
will use when normalising telemetry frames.

### Measurements × target-types → axis tokens

| Target | Measurement     | Axis token              |
|--------|-----------------|-------------------------|
| NODE   | pressure        | `node_pressure`         |
| NODE   | demand          | `node_demand`           |
| NODE   | level           | `node_level`            |
| NODE   | status          | `node_status`           |
| EDGE   | flow            | `edge_flow`             |
| EDGE   | pump_speed      | `edge_pump_speed`       |
| EDGE   | status          | `edge_status`           |
| EDGE   | power           | `edge_power`            |
| EDGE   | valve_position  | `edge_valve_position`   |

Any other `(target_type, measurement)` pair is rejected at build
time.

### Roles

`observed` (default), `control_input`, `derived`, `quality`.

Roles are *labels* the operator attaches to a tag spec — they are
metadata, not a write / actuation surface. A tag flagged
`control_input` describes *what the operator thinks the tag would
mean under a future live binding* and is hydraulically inert in
Sprint 34.

## Strict vs non-strict mode

`build_telemetry_tag_map(specs, network, *, strict=True)`:

- **`strict=True` (default)** — any structural error (empty tag,
  duplicate tag, unknown enum, out-of-range dPHM id, unknown unit)
  raises `ValueError`. The error message joins every detected error
  with `"; "` in input order so the first failure does not mask
  subsequent ones.
- **`strict=False`** — invalid specs are omitted from `tag_map.tags`;
  an error string is appended to `tag_map.diagnostics.errors` in
  input order. Valid specs in the same input list are preserved.

Tag uniqueness is enforced in both modes. The first occurrence of a
duplicate tag wins; later duplicates are rejected.

## JSON loader

`load_telemetry_tag_map_json(path, network, *, strict=True)` accepts
either a list of spec objects:

```json
[
  {"tag": "PT_DC_01", "target_type": "NODE", "target_id": 2, "measurement": "pressure", "unit": "m"},
  {"tag": "FT_PUMP_01", "target_type": "EDGE", "target_id": 5, "measurement": "flow", "unit": "l/s"}
]
```

or a single object with a `"tags"` key:

```json
{
  "tags": [
    {"tag": "PT_DC_01", "target_type": "NODE", "target_id": 2, "measurement": "pressure", "unit": "bar"}
  ]
}
```

Any other top-level JSON shape (scalar, object without `"tags"`,
nested list) raises `ValueError`. No YAML dependency is introduced.

## Read-only contract

The builder and loader:

- never mutate the supplied `Network` (no tensor field is touched);
- never mutate the supplied spec sequence;
- never open a network socket, file, or process beyond the JSON
  loader reading the supplied path;
- never convert a measurement value;
- never activate any deferred EPANET semantics from earlier Sprints.

Every dataclass on the public surface is `frozen=True`; every
collection field is an immutable tuple. Calling the builder twice on
the same inputs returns equal maps.

## Shadow-mode use

Sprint 33 produces an `EpanetImportQualityReport` describing *which
dPHM ids are load-bearing*. Sprint 34 layers an operator-facing label
on top of those ids through `TelemetryTagMap`. A shadow-mode UI can
join the two surfaces by dPHM `(target_type, target_id)` so the
operator sees, alongside each surrogate / pinned node, the tag they
already recognise. The join is purely a presentation concern: no
hydraulic field, no parser behaviour, and no dPHM solver invariant is
affected.

## Safety boundary

This sprint adds **no** live binding. In particular:

- no SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST adapter is
  imported, registered, or polled;
- no write / control / setpoint path is exposed;
- no field validation is claimed — `target_id` validity means the id
  is in range on the loaded `Network`, *not* that the dPHM model
  matches the plant;
- no value conversion is performed at runtime;
- no replay / shadow dataset is produced (that is Sprint 35);
- no dPL calibration is performed;
- no advisory / control recommendation is surfaced;
- no production savings / control claim is made.

The Sprint 34 adapter sits behind the same shadow-mode safety
boundary as Sprints 23–33: a typed, deterministic, read-only schema
surface.
