# Sprint 35 — Cold-start replay / shadow dataset builder

## Goal

Add a deterministic cold-start replay / shadow dataset builder that
turns offline telemetry rows into typed replay frames aligned to a
loaded `Network` and the Sprint 34 `TelemetryTagMap`. The dataset
answers, given an offline row sequence:

- For each timestamp, what node pressure / edge flow / pump speed /
  status / power / etc. values are available?
- Which values were missing, invalid, stale, or out of range?
- What canonical units do those values use?
- Can future shadow-mode evaluation consume these frames without
  touching live OT systems?

The builder is read-only / offline-only. It activates no live SCADA
/ PLC / PAC / historian / OPC-UA / MQTT / REST binding, exposes no
write / control / setpoint path, and invokes no dPHM forward solve.

## Files changed

- `src/aquaoptima/dphm/shadow_replay.py` (new module) — frozen
  dataclasses (`ShadowReplayDiagnostics`, `ShadowReplayFrame`,
  `ShadowReplayDataset`), the per-axis canonical unit conversion
  tables, the public builder `build_shadow_replay_dataset`, and the
  stdlib-only CSV loader `load_shadow_replay_csv`.
- `src/aquaoptima/dphm/__init__.py` (updated) — re-exports the three
  new dataclasses, the builder, and the CSV loader. Sprint 34 surface
  is unchanged.
- `tests/dphm/test_shadow_replay.py` (new) — 46 focused tests covering
  the surface, the strict / non-strict contract, every unit
  conversion, the status parser, the staleness check, and the
  read-only boundary.
- `docs/shadow-replay.md` (new) — Sprint 35 surface documentation
  including the canonical conversion table, strict / non-strict
  semantics, diagnostics semantics, and the reaffirmed safety
  boundary.
- `SPRINT35_REPORT.md` (this file).

No other source file is touched. The new module imports only the
Sprint 34 `telemetry_tag_map` symbols plus stdlib `csv`, `math`,
`dataclasses`, `pathlib`, and `typing`. No parser, solver, training,
or data-IO module is modified.

## API design

Three frozen dataclasses:

- `ShadowReplayDiagnostics(warnings: tuple[str, ...] = (), errors: tuple[str, ...] = ())`
  — deterministic warning / error tuples, identical surface to
  Sprint 34's diagnostics.
- `ShadowReplayFrame(timestamp, node_pressure, node_demand,
  node_level, node_status, edge_flow, edge_pump_speed, edge_status,
  edge_power, edge_valve_position, diagnostics)` — single-timestamp
  frame keyed by canonical axis. Each numeric axis is a
  `Mapping[int, float]`; status axes are `Mapping[int, float | bool]`.
- `ShadowReplayDataset(frames, tag_map, diagnostics)` — frozen
  top-level container; ``frames`` is an immutable tuple in input
  order.

Two builders:

- `build_shadow_replay_dataset(rows, tag_map, *, timestamp_key,
  strict, max_stale_seconds)` — pure offline builder over an
  iterable of Python mappings.
- `load_shadow_replay_csv(path, tag_map, *, timestamp_key, strict,
  max_stale_seconds)` — stdlib-only CSV loader that produces the
  same `ShadowReplayDataset` as the builder.

All public symbols are re-exported through `aquaoptima.dphm`.

## Unit conversion behaviour

Sprint 34 declared the accepted unit family per measurement. Sprint
35 implements the explicit value conversion to canonical units:

| Measurement      | Canonical | Input          | Factor                                  |
|------------------|-----------|----------------|------------------------------------------|
| `pressure`       | `m`       | `m`, `meter`   | identity                                 |
| `pressure`       | `m`       | `bar`          | × 10.197162129779283                     |
| `pressure`       | `m`       | `kpa`          | × 0.10197162129779283                    |
| `pressure`       | `m`       | `psi`          | × 0.703249614902                         |
| `flow` / `demand`| `m3/s`    | `m3/s`         | identity                                 |
| `flow` / `demand`| `m3/s`    | `l/s`          | × 0.001                                  |
| `flow` / `demand`| `m3/s`    | `gpm`          | × 6.309019640343866e-5                   |
| `level`          | `m`       | `m`, `meter`   | identity                                 |
| `level`          | `m`       | `ft`           | × 0.3048                                 |
| `pump_speed`     | `fraction`| `fraction`     | identity                                 |
| `pump_speed`     | `fraction`| `percent`      | / 100                                    |
| `pump_speed`     | `fraction`| `rpm`          | **omitted with warning (conservative)**  |
| `valve_position` | `fraction`| `fraction`     | identity                                 |
| `valve_position` | `fraction`| `percent`      | / 100                                    |
| `power`          | `kw`      | `kw`           | identity                                 |
| `power`          | `kw`      | `w`            | / 1000                                   |
| `status`         | `boolean` | `bool` / `0/1` / strings | see status parser              |

The status parser accepts `bool`, numeric `0` / `1`, and the
case-insensitive strings `"true"` / `"false"`, `"on"` / `"off"`,
`"open"` / `"closed"`, `"running"` / `"stopped"`, `"active"` /
`"inactive"`, `"yes"` / `"no"`, `"0"` / `"1"`. Any other input is an
error.

`rpm` pump speed is handled conservatively: Sprint 34 accepted it as
schema metadata but Sprint 35 cannot fabricate a rated speed, so it
emits a deterministic warning, omits the sample from the frame, and
records the warning in both the per-frame and dataset diagnostics.
This is a *warning*, not an error: strict mode does not raise on
`rpm` pump speed.

## Strict / non-strict behaviour

`strict=True` (default) raises `ValueError` if any of these
structural errors are encountered:

- row is not a mapping;
- row missing the `timestamp` key, or `timestamp` is `None`;
- a numeric sample cannot be coerced to a finite float
  (booleans, empty strings, NaN, inf, or unsupported types);
- a status sample is not one of the accepted forms;
- a unit is in Sprint 34's accepted family but is unknown to the
  Sprint 35 conversion table (a programmer error — currently
  unreachable).

`strict=False` returns a populated dataset; the offending sample is
omitted from the frame; the error string is appended to
`diagnostics.errors` in input order. Whole rows are only omitted
when the timestamp itself cannot be read.

Missing / `None` tag values and `rpm` pump-speed declarations are
**warnings**, not errors. They never raise in strict mode.

`max_stale_seconds` is optional and, when supplied, must be
strictly positive (the builder raises `ValueError` immediately on a
non-positive value). The check is silently skipped for pairs whose
timestamps cannot be subtracted as floats or `datetime` instances —
Sprint 35 never invents a parser.

## Tests added

`tests/dphm/test_shadow_replay.py` — 46 tests covering, in order:

1. Frozen dataclass surfaces (and default-constructed
   `ShadowReplayDataset`).
2. Empty row list returns an empty dataset.
3. Valid node-pressure row populates `node_pressure`.
4. Valid edge-flow row populates `edge_flow`.
5. Pump-speed percent → fraction (and fraction identity).
6. Pressure conversions: `bar` / `kpa` / `psi` → metres of head
   (plus `m` / `meter` aliases).
7. Flow conversions: `l/s` / `gpm` → m3/s.
8. Level conversion: `ft` → m.
9. Power conversion: `w` → kw (plus `kw` identity).
10. Status parsing: `bool`, `0` / `1`, and the accepted strings
    (`on` / `off` / `running` / `closed`); unknown string raises in
    strict and is omitted in non-strict.
11. Missing-timestamp handling (strict raises; non-strict skips the
    row and records the error; `None` timestamp is rejected).
12. Missing-tag-value handling (warning, not error; strict still
    succeeds; `None` tag value also a warning).
13. Invalid-numeric handling (string raises; `bool` for numeric
    rejected; `NaN` rejected; whitespace-padded numeric strings
    accepted).
14. `rpm` pump-speed handled conservatively (warning + omitted in
    both strict and non-strict, no raise).
15. Deterministic frame ordering (two builds equal; input order
    preserved).
16. Read-only: input rows / tag-map snapshot unchanged; `tag_map`
    identity preserved on `ShadowReplayDataset.tag_map`.
17. CSV loader happy path (with bar / l/s conversion).
18. CSV loader malformed shape: empty file, missing timestamp
    column, custom timestamp column name.
19. Sprint 34 `build_telemetry_tag_map` output consumed verbatim;
    empty tag map produces empty axis maps with no errors.
20. No live adapter / write / control surface exposed (substring
    screen across `__all__` plus stdlib networking module absence).
21. `max_stale_seconds` warnings on numeric and `datetime`
    timestamps; skipped for strings; rejected if non-positive.

Plus an explicit "row mutation after build" regression check, an
"empty CSV cell is missing not zero" check, and a `repeat build ==
build` determinism check.

## Validation commands / results

Run from the worktree root:

```bash
python -m pip install -e .
python -m pytest tests/dphm/test_shadow_replay.py -q
python -m pytest tests/dphm tests/models tests/training tests/dataio -q
python -m pytest tests -q
python -m compileall -q src tests
git diff --check
```

Results captured before this report:

- `python -m pytest tests/dphm/test_shadow_replay.py -q` →
  **46 passed**.
- `python -m pytest tests/dphm tests/models tests/training tests/dataio -q`
  → **1416 passed, 1 skipped** (existing WNTR optional-import skip).
- `python -m pytest tests -q` → **1424 passed, 1 skipped**.
- `python -m compileall -q src tests` → clean.
- `git diff --check` → clean.

## Compatibility notes

- Sprint 34's `TelemetryTagMap` is consumed verbatim — the
  Sprint 35 builder iterates `tag_map.tags` and never re-validates
  the schema. Calling Sprint 34's `build_telemetry_tag_map(...,
  strict=False)` and feeding the resulting map to Sprint 35 is
  fully supported; errors from Sprint 34 do not propagate into the
  dataset surface.
- No existing public symbol changes. No existing test changes.
- No new third-party dependency: pandas is not added, and only
  stdlib `csv` / `math` / `dataclasses` / `pathlib` / `typing` are
  imported by the new module.
- The `aquaoptima.dataio` Sprint 4.5 telemetry abstraction is
  untouched; Sprint 35's dPHM-side surface is a peer of, not a
  replacement for, the broader data-IO layer.

## Known limitations

- Timestamps are *not* parsed. The builder forwards them verbatim
  into the frame and only performs subtraction-style staleness
  checks when both timestamps are numeric or both are `datetime`
  instances. A future sprint could add an optional timestamp
  normaliser if a downstream consumer needs sorted, monotonic,
  timezone-aware timestamps.
- `rpm` pump speed is intentionally not converted. Sprint 35 would
  need a per-tag rated speed (not present in Sprint 34 metadata) to
  produce a canonical fraction; the conservative behaviour avoids a
  silent wrong-units bug at the cost of dropping `rpm` samples on
  the floor with a warning.
- The per-axis mappings on `ShadowReplayFrame` are plain `dict`
  objects (typed as `Mapping`). The dataclass binding is frozen,
  but a determined caller could mutate the dict in place. Callers
  that need a guaranteed-immutable view can wrap each axis in
  `types.MappingProxyType` — Sprint 35 deliberately does not
  pre-wrap to keep ergonomics simple.
- No live binding, no forward-solve comparator, no advisory
  surface, no calibration loop — strictly out of scope per the
  Sprint 35 brief.

## Verdict

Sprint 35 ships a typed, deterministic, read-only cold-start replay
/ shadow dataset builder that consumes Sprint 34's
`TelemetryTagMap` and an offline row sequence and emits a frozen
`ShadowReplayDataset` whose frames carry canonicalised node / edge
values keyed by dPHM axis and id. All 21 numbered Sprint 35
verification items are exercised by the test suite; the existing
1,378-test baseline is preserved; the new module adds no third-
party dependency. The safety boundary is unchanged: this sprint
adds no live binding, no write path, and no advisory surface.

Ready for Hermes verification.

## Sprint 36 recommendation

The Sprint 35 replay builder cleanly produces frames keyed by the
canonical dPHM axes (`node_pressure`, `node_demand`, `edge_flow`,
`edge_pump_speed`, …), which is exactly the shape a dPL calibration
loop would consume as observation targets. There are no surprise
gaps in the Sprint 34 + Sprint 35 surface that warrant a hardening
detour — both sprints landed deterministic, fully-tested, read-only
surfaces.

**Recommendation: Sprint 36 → dPL calibration prototype.** Use the
Sprint 35 `ShadowReplayDataset.frames` as observation tensors,
keying losses by `(axis, target_id)` against the existing dPHM
forward-solve output. Keep the prototype offline (no live OT
binding), keep the loss surface read-only against the dPHM solver,
and stop short of advisory / setpoint output (still out of scope
under the shadow-mode safety boundary).

If, during prototyping, a calibration-blocking limitation surfaces
in the replay builder (e.g. a need for `rpm` pump speed conversion
once a rated-speed metadata field exists, or sorted-timestamp
guarantees), the smallest possible follow-up — adding a single
metadata field plus a focused test pass — should land as a Sprint
36a hardening pass before continuing the calibration loop.
