# Sprint 30 — EPANET diagnostics summary / row-count helpers

## Goal

Sprints 23–29 grew `EpanetImportDiagnostics` into a multi-channel
container with six row-style fields (`status_rows`,
`control_rule_rows`, `pattern_energy_rows`, `emitter_demand_rows`,
`water_quality_rows`) plus an ignored-section presence field
(`ignored_sections`). UI / API / report consumers that just need
"how many diagnostic rows did this file emit, grouped by EPANET
section?" had to walk every tuple themselves and dedupe by hand.

Sprint 30 closes that ergonomics gap by adding a small read-only
layer on top of the existing container — a per-section row-count
helper, a typed summary dataclass, and an ignored-section presence
helper. No new EPANET semantics are introduced.

## Scope

- Add `row_count_by_section()`, `ignored_section_names()`, and
  `summary()` methods on `EpanetImportDiagnostics`.
- Add `EpanetImportDiagnosticsSummary` frozen dataclass.
- Re-export both from `aquaoptima.dphm`.
- Document the new ergonomics layer in
  `docs/epanet-inp-import.md`.

Out of scope (deferred): water-quality simulation, active
`[EMITTERS]` / `[DEMANDS]` / `[PATTERNS]` / `[ENERGY]` /
`[CONTROLS]` / `[RULES]` semantics, closed-link / check-valve
modelling, pump speed / status changes from `[STATUS]` or controls,
new hydraulic physics, Darcy-Weisbach, real PLC/PAC/SCADA adapters,
write / control path, dPL parameter learning, ONNX / TensorRT /
Jetson deployment, real EPANET binary / runtime, production /
savings claims.

## Files changed

- `src/aquaoptima/dphm/inp_io.py` — adds
  `EpanetImportDiagnosticsSummary`, the three new helper methods on
  `EpanetImportDiagnostics`, and the canonical section-order
  constant `_CANONICAL_ROW_COUNT_SECTION_ORDER`.
- `src/aquaoptima/dphm/__init__.py` — re-exports
  `EpanetImportDiagnosticsSummary`.
- `tests/dphm/test_inp_diagnostics_summary.py` — new test module
  exercising the Sprint 30 contract (29 tests).
- `docs/epanet-inp-import.md` — new "Read-only diagnostics summary
  / row counts (Sprint 30)" section describing the public API,
  semantics, freshness / immutability, hydraulic inertness, WNTR
  asymmetry, and tests.

## Summary / count API design

```python
diagnostics.row_count_by_section() -> dict[str, int]
diagnostics.ignored_section_names() -> tuple[str, ...]
diagnostics.summary() -> EpanetImportDiagnosticsSummary
```

`EpanetImportDiagnosticsSummary` is `dataclass(frozen=True)` with:

- `row_count_by_section: Mapping[str, int]` (fresh `dict` per call)
- `total_diagnostic_rows: int`
- `ignored_section_count: int`
- `status_row_count: int`
- `control_rule_row_count: int`
- `pattern_energy_row_count: int`
- `emitter_demand_row_count: int`
- `water_quality_row_count: int`

Canonical ordering of the dict:

```
STATUS, CONTROLS, RULES, PATTERNS, ENERGY, EMITTERS, DEMANDS,
QUALITY, SOURCES, REACTIONS, MIXING
```

Unknown / future section names are appended alphabetically after
the canonical block. Sections with zero rows are omitted from the
dict.

Design rationale for using a plain `dict` (rather than
`types.MappingProxyType` or a tuple of pairs) inside the frozen
summary dataclass:

- The `summary()` method allocates a **fresh** dict on every call
  via `row_count_by_section()`, so the dict is not shared between
  summary instances. Mutation by one caller cannot leak into
  another's summary.
- A plain `dict` keeps `dataclasses.asdict(summary)` working
  (a `MappingProxyType` value breaks `deepcopy` and therefore
  `asdict`).
- The frozen dataclass prevents reassignment of the field
  reference itself, which is the property that matters for the
  surface's structural read-only contract.

## Row counts vs ignored-section presence

The two surfaces are deliberately separate so a file with both an
`ignored_sections=[CONTROLS]` record and `control_rule_rows` for
`CONTROLS` is **never double-counted**:

- `row_count_by_section()` counts row diagnostics only
  (`status_rows`, `control_rule_rows`, `pattern_energy_rows`,
  `emitter_demand_rows`, `water_quality_rows`).
- `ignored_section_names()` returns the section names from
  `ignored_sections` (section-level presence).
- `summary().ignored_section_count` is `len(ignored_sections)`.

Test `test_no_double_counting_between_channels_and_ignored_sections`
proves this on a constructed container with both surfaces
populated for `CONTROLS` and `PATTERNS`.

## Fallback parser behaviour

The fallback parser is unchanged. Every Sprint 23–29 channel still
emits exactly the same records — Sprint 30 only reads them. The
Sprint 22/23 `[STATUS]` rejection contract (raise on `CLOSED`,
`CV`, numeric pump-status, unknown link id, arbitrary token) is
preserved with no partial diagnostics leaking out of a rejection;
test `test_status_rejection_still_raises` re-asserts this.

## WNTR behaviour / asymmetry

The optional WNTR back-end remains diagnostically empty — the WNTR
adapter still produces an empty `EpanetImportDiagnostics`. The
Sprint 30 helpers therefore return:

- `row_count_by_section()` → `{}`
- `ignored_section_names()` → `()`
- `summary()` → all integer fields zero, embedded
  `row_count_by_section` empty.

This matches the Sprint 23–29 asymmetry. Test
`test_wntr_diagnostics_summary_is_empty` uses a WNTR-parseable
slice of the all-channels fixture (the bogus `[RULES]` /
`[CONTROLS]` syntax in the fallback fixture is rejected by WNTR's
own rule parser, so the test deliberately exercises a narrower
fixture for the WNTR path).

## Read-only / hydraulic-inertness evidence

- `EpanetImportDiagnostics` is `dataclass(frozen=True)`; field
  references cannot be reassigned.
- All tuple fields remain `tuple` (structurally immutable).
- `row_count_by_section()` constructs and returns a fresh `dict`
  on each call. Test
  `test_mutating_returned_dict_does_not_affect_diagnostics` proves
  that mutating the returned dict has no effect on subsequent
  calls or on the underlying tuples.
- `summary()` returns a fresh `EpanetImportDiagnosticsSummary`
  with a fresh embedded dict on each call. Test
  `test_summary_row_count_dict_is_fresh` proves identity
  separation between calls.
- `EpanetImportDiagnosticsSummary` is `dataclass(frozen=True)`;
  test `test_summary_dataclass_is_frozen_dataclass` asserts
  `FrozenInstanceError` on attribute reassignment.
- Test `test_helpers_do_not_mutate_container` invokes every
  helper and asserts that the source tuples retain their identity
  (`is` check).
- The loaded `Network` is not touched anywhere in the new code
  path — Sprint 30 only reads existing diagnostic tuples. Test
  `test_load_network_from_inp_default_remains_network_only`
  re-asserts that the default `load_network_from_inp(path)`
  signature still returns only a `Network`.
- 1260-test full suite passes (incl. all Sprint 11–29 fixtures
  and the HEAD / POWER / PRV / TCV / SI / GPM / pressure / demand
  multiplier / SG / viscosity / diagnostics regression set).

## Tests added / updated

New module: `tests/dphm/test_inp_diagnostics_summary.py` — 29
tests covering:

- public surface (`row_count_by_section`, `ignored_section_names`,
  `summary` callable; `EpanetImportDiagnosticsSummary` frozen);
- empty container (every helper returns empty / zero value);
- single-channel counts (one test per row channel: `STATUS`,
  `CONTROLS`/`RULES`, `PATTERNS`/`ENERGY`, `EMITTERS`/`DEMANDS`,
  `QUALITY`/`SOURCES`/`REACTIONS`/`MIXING`);
- canonical ordering of the returned dict + alphabetical tail for
  unknown sections;
- freshness: distinct dict instances per call, mutation
  isolation;
- ignored-section presence helper (tuple type, source-file order
  preserved);
- summary aggregation (per-channel `len`s, total, ignored count);
- no-double-counting between channels and ignored-section
  presence;
- read-only contract: helpers do not mutate container tuples;
- parser integration: an all-channels `.inp` fixture produces the
  expected per-section counts and a matching summary;
- API parity: `load_inp_diagnostics(...)` and
  `load_network_from_inp(..., return_diagnostics=True)` produce
  identical summary / counts; `dataclasses.asdict` parity;
- backwards compatibility: default `load_network_from_inp(path)`
  still returns only `Network`;
- empty fixture (no row sections, but `[TITLE]`/`[END]` ignored
  sections present) summary;
- WNTR asymmetry: WNTR back-end returns empty / zero from every
  helper;
- Sprint 22 `[STATUS] CLOSED` rejection still raises.

No existing tests required modification; the Sprint 23–29 channel
contracts are untouched.

## Validation commands & results

```bash
python -m pip install -e .
# Successfully installed aquaoptima-dphm-pinn-0.1.0

python -m pytest tests/dphm tests/models tests/training tests/dataio -q
# 1252 passed, 1 skipped in 93.57s
# (only skip: tests/dphm/test_wntr_optional_import.py::… "WNTR is installed;
# ImportError path not exercised here" — unrelated to Sprint 30)

python -m pytest tests -q
# 1260 passed, 1 skipped in 83.91s

python -m compileall -q src tests
# (no output → clean)

python -m pytest tests/dphm/test_inp_diagnostics_summary.py -q
# 29 passed in 4.47s

python -m pytest \
  tests/dphm/test_inp_diagnostics_summary.py \
  tests/dphm/test_inp_water_quality_row_diagnostics.py \
  tests/dphm/test_inp_emitter_demand_row_diagnostics.py \
  tests/dphm/test_inp_pattern_energy_row_diagnostics.py \
  tests/dphm/test_inp_control_rule_row_diagnostics.py \
  tests/dphm/test_inp_status_diagnostics.py \
  tests/dphm/test_inp_ignored_section_diagnostics.py -q
# 290 passed in 5.30s
#  (all six prior diagnostics-channel test modules + the new Sprint 30 module)

git status --short
#  M docs/epanet-inp-import.md
#  M src/aquaoptima/dphm/__init__.py
#  M src/aquaoptima/dphm/inp_io.py
# ?? tests/dphm/test_inp_diagnostics_summary.py
```

Secret scan (`grep -rn 'AKIA\|BEGIN PRIVATE\|BEGIN RSA\|api_key…'
src tests docs`) returns zero hits. The diff contains only the four
files listed above.

## Compatibility notes

- `EpanetImportDiagnostics()` constructor signature is unchanged —
  every Sprint 23–29 keyword-only field default remains `()`. New
  callers that rely on the previous shape continue to compile and
  run.
- Default `load_network_from_inp(path)` still returns only a
  `Network` (test
  `test_load_network_from_inp_default_remains_network_only`).
- `load_inp_diagnostics(path)` and
  `load_network_from_inp(path, return_diagnostics=True)` produce
  identical summary / counts (test
  `test_load_network_from_inp_with_return_diagnostics_matches_summary`).
- Sprint 22 `[STATUS] CLOSED` / `CV` / numeric pump-status /
  unknown-link-id / arbitrary-token rejection paths still raise
  with no partial diagnostics (test
  `test_status_rejection_still_raises`).
- `tests/dphm/test_inp_pressure_units.py`,
  `tests/dphm/test_inp_demand_multiplier.py`,
  `tests/dphm/test_inp_specific_gravity.py`,
  `tests/dphm/test_inp_viscosity.py`,
  `tests/dphm/test_inp_pump_curves.py`,
  `tests/dphm/test_inp_power_pump.py`,
  `tests/dphm/test_inp_valves.py`,
  `tests/dphm/test_wntr_pump_helpers.py`, and
  `tests/dphm/test_wntr_valve_helpers.py` all still pass under
  the full-suite run.

## Known limitations

- The summary's `row_count_by_section` field is a plain `dict`.
  A frozen dataclass does not freeze nested `dict` contents, so
  in principle a caller could mutate
  `summary.row_count_by_section`. Because each `summary()` call
  builds a fresh dict, mutation by one caller cannot leak into
  another's summary — but a caller that holds on to one summary
  and mutates its dict will observe that mutation on that
  specific instance. This is a deliberate trade-off:
  `MappingProxyType` would break `dataclasses.asdict(summary)`
  (the proxy is not picklable / deepcopyable).
- The helpers operate on the records present in the diagnostics
  container; they do not re-parse the file. A future sprint that
  adds a new row diagnostic channel will need to extend
  `row_count_by_section()` to fold that channel into the counts.
- The unknown-section alphabetical tail is exercised by a
  constructed-container test only; the fallback parser does not
  currently emit any row diagnostics outside the 11 canonical
  sections, so this branch is a forward-compatibility safeguard.

## Sprint 30 approval gates

- targeted pytest (`tests/dphm tests/models tests/training
  tests/dataio`): **exit 0**, 1252 passed, 1 skipped.
- full pytest (`tests`): **exit 0**, 1260 passed, 1 skipped.
- compileall: **exit 0**.
- `SPRINT30_REPORT.md`: present (this file).
- row-count / summary API exists and is tested: ✅
  (`EpanetImportDiagnostics.row_count_by_section`,
  `EpanetImportDiagnostics.ignored_section_names`,
  `EpanetImportDiagnostics.summary`,
  `EpanetImportDiagnosticsSummary`).
- all Sprint 23–29 channels counted correctly: ✅ (test
  `test_parser_emits_expected_counts_for_all_channels`).
- no double-counting between row diagnostics and ignored-section
  presence: ✅ (test
  `test_no_double_counting_between_channels_and_ignored_sections`).
- helpers deterministic and read-only: ✅ (tests
  `test_canonical_ordering`,
  `test_unknown_sections_sorted_alphabetically_after_canonical`,
  `test_returned_dict_is_fresh_each_call`,
  `test_mutating_returned_dict_does_not_affect_diagnostics`,
  `test_helpers_do_not_mutate_container`).
- all prior diagnostics from Sprints 23–29 still work: ✅
  (290-test diagnostics-channel run passes, 1260-test full suite
  passes).
- no new EPANET semantics implemented: ✅ (no parser change, no
  new section handling, no new physics; the diff is two new
  methods + one new frozen dataclass + a re-export).
- diagnostics proven hydraulically inert / no-op: ✅ (tests
  `test_helpers_do_not_mutate_container`,
  `test_load_network_from_inp_default_remains_network_only`).
- `load_network_from_inp(path)` backward compatibility: ✅
  (default signature returns only `Network`).
- Sprint 22/23 `[STATUS]` rejection intact: ✅
  (`test_status_rejection_still_raises`).
- HEAD / POWER / PRV / TCV / SI / GPM / pressure / demand /
  SG / viscosity / diagnostics fixture behaviour preserved: ✅
  (full-suite run passes).
- WNTR optional tests skip / pass cleanly: ✅
  (`test_wntr_diagnostics_summary_is_empty` passes; only skip in
  the suite is the unrelated `test_wntr_optional_import.py`
  ImportError-path test).
- no obvious secret files / strings introduced: ✅ (secret scan
  zero hits).
- `git status` contains only intended Sprint 30 changes: ✅
  (3 modified, 1 untracked test module).
- WNTR-installed extra gates: WNTR HEAD/POWER/PRV/TCV/demand-
  multiplier parity from Sprints 13–29 still passes (full suite),
  WNTR empty-diagnostics summary / count tested and documented.

## Verdict

**APPROVED.**

## Sprint 31 recommendation

The diagnostics ergonomics surface now exposes per-section counts
and a typed summary, but it remains a flat list of section names
and integer counts. The next natural step is a small, still-
read-only typed query layer on top — for example, a
`diagnostics.rows_for_section(section: str) -> tuple[...]`
helper that returns the underlying tuple of records for a given
section name, without exposing the channel-specific dispatch
(`control_rule_rows` vs `pattern_energy_rows` vs
`water_quality_rows` …) to the caller. That would let UI / API /
report consumers pivot from "how many rows did `[CONTROLS]`
emit?" to "give me those rows" without learning the channel map,
while preserving the Sprint 30 no-new-semantics boundary.

Suggested name: **Sprint 31 — Read-only diagnostics row accessor
(`rows_for_section`)**. Hard-no list stays identical to Sprint 30:
no new EPANET semantics, no active section behaviour, no
hydraulic changes, no new physics, no WNTR-side semantic
activation, no Darcy-Weisbach, no production / savings claims.
