# Sprint 34 — Telemetry tag-map adapter with canonical telemetry schema

## Goal

Add a typed, read-only telemetry tag-map adapter that validates a
user-supplied mapping of operator-facing telemetry tags to canonical
dPHM `Network` node / edge quantities, producing an immutable,
reportable schema surface for shadow-mode readiness.

The adapter answers, given a loaded `Network` and a list of tag
specs:

- Is every tag uniquely named?
- Does every tag reference a valid dPHM node / edge id?
- Is every (target_type, measurement) pair declared on the right
  topology axis (pressure on nodes, flow on edges, etc.)?
- Is the supplied unit in the canonical unit family for the
  measurement, and what canonical unit will the future shadow
  dataset builder report in?
- What role does the operator believe the tag plays (observed /
  control_input / derived / quality) — purely as metadata?

No live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
adapter is activated; no write / control / setpoint path is
exposed; no measurement value is converted at runtime.

## Files changed

- `src/aquaoptima/dphm/telemetry_tag_map.py` (new module) — frozen
  dataclasses (`TelemetryTagSpec`, `CanonicalTelemetryTag`,
  `TelemetryTagMapDiagnostics`, `TelemetryTagMap`), canonical enum-
  like constants, validator/builder `build_telemetry_tag_map`, and
  JSON loader `load_telemetry_tag_map_json`.
- `src/aquaoptima/dphm/__init__.py` (updated) — re-exports the four
  new dataclasses, the builder, the loader, and the canonical
  enum-like constants for target types, measurements, roles, and
  axes. Existing exports are unchanged.
- `tests/dphm/test_telemetry_tag_map.py` (new) — 34 focused tests
  covering the surface, the strict / non-strict mode contract, and
  the read-only boundary.
- `docs/telemetry-tag-map.md` (new) — Sprint 34 surface
  documentation including the canonical schema tables and the
  reaffirmed safety boundary.

No other source file is touched. The new module imports only
`Network` and `pathlib.Path` from the project; no parser, solver,
training, or data-IO module is modified.

## API design

### Frozen dataclasses

```python
@dataclass(frozen=True)
class TelemetryTagSpec:
    tag: str
    target_type: str          # "NODE" | "EDGE"
    target_id: int
    measurement: str          # canonical measurement token
    unit: str                 # operator-supplied unit string
    role: str = "observed"
    description: str = ""

@dataclass(frozen=True)
class CanonicalTelemetryTag:
    tag: str
    target_type: str
    target_id: int
    measurement: str
    unit: str
    canonical_unit: str       # the unit the measurement reports in
    role: str
    axis: str                 # "node_pressure" | "edge_flow" | ...
    description: str = ""

@dataclass(frozen=True)
class TelemetryTagMapDiagnostics:
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

@dataclass(frozen=True)
class TelemetryTagMap:
    tags: tuple[CanonicalTelemetryTag, ...] = ()
    diagnostics: TelemetryTagMapDiagnostics = field(
        default_factory=TelemetryTagMapDiagnostics
    )
```

### Builder

```python
def build_telemetry_tag_map(
    specs: Iterable[TelemetryTagSpec | Mapping[str, object]],
    network: Network,
    *,
    strict: bool = True,
) -> TelemetryTagMap: ...
```

- Accepts both dataclass and dict-like specs (dicts are coerced
  through `TelemetryTagSpec`; unknown keys are rejected so typos do
  not silently disappear).
- Trims tag names; rejects empty tags.
- Enforces tag uniqueness across the input list.
- Validates `target_type` against `{"NODE", "EDGE"}` case-
  insensitively.
- Validates node ids against `[0, network.num_nodes)` and edge ids
  against `[0, network.edge_index.shape[1])`.
- Validates measurement names against the canonical measurement set
  and rejects measurement / target_type pairs that are not valid
  (e.g. `pressure` on `EDGE`).
- Validates roles against `{"observed", "control_input", "derived",
  "quality"}`.
- Validates units against the per-measurement canonical unit family
  and emits the canonical unit string on the output dataclass. *No
  value conversion is performed.*
- Produces a deterministic `diagnostics.errors` tuple in input order.
- `strict=True` (default) raises `ValueError` on any structural
  error; `strict=False` omits the invalid spec from `tags` and
  appends the error string to `diagnostics.errors`.
- Never mutates `network` or the input specs; never opens any
  socket, file, or process.

### JSON loader

```python
def load_telemetry_tag_map_json(
    path: PathLike,
    network: Network,
    *,
    strict: bool = True,
) -> TelemetryTagMap: ...
```

- Accepts both a list-of-objects shape and a single-object-with-
  `tags` shape.
- Rejects any other top-level JSON shape (scalar, mapping without
  `"tags"`, nested list) with `ValueError`.
- Forwards the rows to `build_telemetry_tag_map`.
- No YAML dependency is introduced.

### Public exports

`aquaoptima.dphm.__init__` now re-exports:

- `TelemetryTagSpec`, `CanonicalTelemetryTag`,
  `TelemetryTagMapDiagnostics`, `TelemetryTagMap`
- `build_telemetry_tag_map`, `load_telemetry_tag_map_json`
- Canonical token sets: `TELEMETRY_TARGET_TYPES`,
  `TELEMETRY_MEASUREMENTS`, `TELEMETRY_ROLES`, `TELEMETRY_AXES`
- Stable per-token constants (`TELEMETRY_TARGET_NODE`,
  `TELEMETRY_MEASUREMENT_PRESSURE`, `TELEMETRY_AXIS_EDGE_FLOW`, …)

All are added to `__all__`. Existing exports are unchanged.

## Validation behavior

Measurement → canonical unit:

| Measurement      | Canonical unit | Accepted units                     |
|------------------|----------------|------------------------------------|
| `pressure`       | `m`            | `m`, `meter`, `bar`, `psi`, `kpa`  |
| `flow`           | `m3/s`         | `m3/s`, `l/s`, `gpm`               |
| `demand`         | `m3/s`         | `m3/s`, `l/s`, `gpm`               |
| `pump_speed`     | `fraction`     | `fraction`, `percent`, `rpm`       |
| `level`          | `m`            | `m`, `meter`, `ft`                 |
| `status`         | `boolean`      | `boolean`, `bool`, `0/1`           |
| `power`          | `kw`           | `kw`, `w`                          |
| `valve_position` | `fraction`     | `percent`, `fraction`              |

(`target_type`, `measurement`) → axis token, e.g. `(NODE, pressure)`
→ `node_pressure`, `(EDGE, flow)` → `edge_flow`,
`(EDGE, pump_speed)` → `edge_pump_speed`. The full table lives in
`docs/telemetry-tag-map.md` and is the single source of truth for
which combinations are legal.

## Tests added

`tests/dphm/test_telemetry_tag_map.py` (34 tests). Each of the 22
required test cases is covered:

1. Frozen dataclass surfaces — `test_dataclasses_are_frozen_and_immutable`.
2. Empty spec list — `test_empty_specs_returns_empty_map_with_empty_diagnostics`.
3. Dataclass and dict inputs — `test_dataclass_and_dict_inputs_both_accepted` (+ unknown-key and missing-required-key tests).
4. Node pressure tag — `test_node_pressure_tag_canonical_axis_and_unit`, `test_node_pressure_alternate_units_canonicalise_to_m`.
5. Edge flow tag — `test_edge_flow_tag_canonical_axis_and_unit`, `test_edge_flow_alternate_units_canonicalise_to_m3_s`.
6. Pump speed percent/fraction — `test_pump_speed_percent_and_fraction_canonicalise_to_fraction` (+ rpm).
7. Status boolean — `test_status_boolean_canonicalisation`.
8. Duplicate tag — `test_duplicate_tag_raises_in_strict_mode`, `test_duplicate_tag_records_error_in_non_strict_mode`.
9. Empty tag — `test_empty_tag_rejected`.
10. Unknown target type — `test_unknown_target_type_rejected`.
11. Out-of-range node id — `test_out_of_range_node_id_rejected`.
12. Out-of-range edge id — `test_out_of_range_edge_id_rejected`.
13. Unknown measurement — `test_unknown_measurement_rejected`, `test_measurement_target_type_mismatch_rejected`.
14. Unknown unit — `test_unknown_unit_rejected`, `test_empty_unit_rejected`.
15. Unknown role — `test_unknown_role_rejected`.
16. Read-only inputs — `test_builder_does_not_mutate_inputs`.
17. Deterministic ordering — `test_deterministic_ordering_of_valid_and_invalid_specs`, `test_repeat_build_returns_equal_map`.
18. JSON loader list shape — `test_load_telemetry_tag_map_json_list_shape`.
19. JSON loader object shape — `test_load_telemetry_tag_map_json_object_shape`.
20. JSON loader malformed shapes — `test_load_telemetry_tag_map_json_rejects_malformed_shapes`, `test_load_telemetry_tag_map_json_non_strict_propagates_errors`.
21. No write / control path — `test_no_write_or_control_path_exposed`.
22. Existing test suite — verified by `pytest tests -q`: 1378 passed, 1 skipped (pre-existing WNTR-not-installed skip path), 3 warnings (pre-existing `torch_geometric` / `torch.jit.script` deprecation warnings).

Supplementary coverage:
`test_canonical_constants_are_stable_strings`,
`test_default_tag_map_diagnostics_is_empty`,
`test_canonical_tag_field_set`.

## Validation commands / results

```bash
python -m pip install -e .
python -m pytest tests/dphm/test_telemetry_tag_map.py -q
python -m pytest tests/dphm tests/models tests/training tests/dataio -q
python -m pytest tests -q
python -m compileall -q src tests
git diff --check
```

Results:

- `pip install -e .` — editable install succeeded (`Successfully installed aquaoptima-dphm-pinn-0.1.0`).
- `pytest tests/dphm/test_telemetry_tag_map.py` — **34 passed** in ~2.2s.
- `pytest tests/dphm tests/models tests/training tests/dataio` — **1370 passed, 1 skipped** in ~115s (the pre-existing WNTR-not-installed skip path).
- `pytest tests` — **1378 passed, 1 skipped** in ~100s.
- `compileall -q src tests` — clean.
- `git diff --check` — clean.

## Compatibility notes

- All Sprint 11–33 surfaces are unchanged. `Network`, `load_network_from_inp`, `load_inp_diagnostics`, `build_import_quality_report`, and every previously-exported dataclass keep their existing field set and behaviour.
- The new module imports only `Network` and standard-library `json` / `pathlib`. No optional dependency is added.
- `aquaoptima.dataio` Sprint 4.5 telemetry abstraction (`SiteTagMap` / `TagDefinition` / `TelemetrySeries`) is independent of the Sprint 34 dPHM-side adapter — the two surfaces can coexist and a future Sprint 35 dataset builder can consume both.
- The new public exports widen `aquaoptima.dphm.__all__` but do not rename or remove any existing export.

## Known limitations

- Sprint 34 stores `canonical_unit` as metadata only — no value conversion is performed, and no telemetry frame is read. Value normalisation belongs to a future shadow-mode dataset builder.
- The validator only checks dPHM id range; it does *not* cross-check that a tag's measurement axis is hydraulically meaningful on the specific dPHM element (e.g. an `edge_flow` tag on a pump-edge is accepted because the `Network` has the edge at that id, not because the dPHM model represents the physical flow at that pump correctly). That cross-check belongs to Sprint 35.
- The canonical unit family is intentionally narrow. Extending the table (e.g. adding `mbar`, `cfs`, `mgd` for pressure / flow) is a one-line addition to `_MEASUREMENT_UNIT_TABLE` and does not affect the public surface; it should still be exercised through tests when added.
- No YAML loader is provided. A JSON-shaped document is the only supported on-disk schema for Sprint 34. The single-object-with-`tags` shape leaves room for sibling top-level keys in future sprints (metadata, version, etc.) without breaking compatibility.

## Verdict

Ship.

- Surface is read-only, frozen, deterministic, and composes only the
  Sprint 11–33 public `Network` surface.
- Loaded `Network` and input specs are byte-for-byte unchanged; no
  EPANET semantics are activated; no parser / solver behaviour is
  modified.
- 34 new tests pin the contract; the full pre-existing 1344-test
  suite still passes (1378 total with the new tests).
- Documentation is added; safety boundary is reaffirmed verbatim.

## Sprint 35 recommendation

Cold-start replay / shadow dataset builder consuming
`TelemetryTagMap` and offline telemetry rows.

The Sprint 34 tag-map names every (operator-facing tag → canonical
dPHM axis) mapping the future shadow dataset will join on. The next
bottleneck is a deterministic, read-only builder that takes:

- a loaded `Network` (Sprint 11–32 surface);
- a `TelemetryTagMap` (Sprint 34 surface);
- an offline telemetry frame (CSV / Parquet rows with per-tag value
  columns and a timestamp column);

and produces a typed, immutable replay dataset (per-step tensors of
node-pressure, edge-flow, pump-speed, etc.) for shadow-mode
side-by-side comparison against the dPHM forward model. Recommended
scope:

- Sprint 35.1: in-memory `ShadowReplayFrame` dataclass (timestamps,
  per-axis tensors), built from a pandas DataFrame against a
  `TelemetryTagMap`;
- Sprint 35.2: value normalisation through the canonical unit
  table — explicit conversion from operator-supplied unit to
  canonical unit, with deterministic warnings on missing /
  out-of-range / stale samples;
- Sprint 35.3: read-only side-by-side comparator producing
  per-element residuals between the dPHM forward solve and the
  replay frame, for shadow-mode credibility checks only.

The safety boundary stays the same as Sprint 34: no live binding,
no writes, no advisory / control recommendation, no production
savings claim.
