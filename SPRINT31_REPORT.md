# Sprint 31 Report — `rows_for_section` accessor on `EpanetImportDiagnostics`

## Goal

Add a read-only `rows_for_section(name)` accessor on
`EpanetImportDiagnostics` so UI / API / report consumers can retrieve
diagnostics records for an EPANET section without knowing which
internal diagnostics channel (`status_rows`, `control_rule_rows`,
`pattern_energy_rows`, `emitter_demand_rows`, `water_quality_rows`)
owns that section.

Sprint 30 added summary / count ergonomics on the multi-channel
container. Sprint 31 adds the matching section-keyed retrieval
ergonomics. No new EPANET semantics are introduced; the loader and
the loaded `Network` are unchanged.

## Files changed

| File | Change |
|------|--------|
| `src/aquaoptima/dphm/inp_io.py` | Added module-level `_ROWS_FOR_SECTION_CHANNEL` lookup table; added `EpanetImportDiagnostics.rows_for_section(name)` method; extended the class docstring to mention the new helper. |
| `tests/dphm/test_inp_rows_for_section.py` | **New file.** 26 tests covering API existence, all row channels, name normalisation (case, whitespace, bracket notation), unknown / empty input, source-order preservation, tuple-backed return, read-only contract, parser integration (fallback + WNTR optional), no-double-count vs `row_count_by_section`, hydraulic inertness against the baseline fixture, default `load_network_from_inp` shape, Sprint 22 `[STATUS]` rejection. |
| `docs/epanet-inp-import.md` | New **“Section-keyed row retrieval (Sprint 31)”** section: public API, section → channel mapping, name normalisation, row-vs-presence semantics, hydraulic inertness, WNTR asymmetry, tests inventory. |

`SPRINT31_REPORT.md` (this file) — new.

## `rows_for_section` API design

```python
diagnostics.rows_for_section("STATUS")     # status_rows
diagnostics.rows_for_section("controls")   # control_rule_rows where section == "CONTROLS"
diagnostics.rows_for_section(" Rules ")    # whitespace tolerant
diagnostics.rows_for_section("[PATTERNS]") # EPANET bracket notation
diagnostics.rows_for_section("NOPE")       # () — non-throwing
diagnostics.rows_for_section("")           # ()
```

### Section → channel mapping

| Section      | Backing channel       | Notes                                       |
|--------------|-----------------------|---------------------------------------------|
| `STATUS`     | `status_rows`         | Returned as a freshly-allocated tuple.      |
| `CONTROLS`   | `control_rule_rows`   | Filtered by `record.section == "CONTROLS"`. |
| `RULES`      | `control_rule_rows`   | Filtered by `record.section == "RULES"`.    |
| `PATTERNS`   | `pattern_energy_rows` | Filtered by `record.section == "PATTERNS"`. |
| `ENERGY`     | `pattern_energy_rows` | Filtered by `record.section == "ENERGY"`.   |
| `EMITTERS`   | `emitter_demand_rows` | Filtered by `record.section == "EMITTERS"`. |
| `DEMANDS`    | `emitter_demand_rows` | Filtered by `record.section == "DEMANDS"`.  |
| `QUALITY`    | `water_quality_rows`  | Filtered by `record.section == "QUALITY"`.  |
| `SOURCES`    | `water_quality_rows`  | Filtered by `record.section == "SOURCES"`.  |
| `REACTIONS`  | `water_quality_rows`  | Filtered by `record.section == "REACTIONS"`.|
| `MIXING`     | `water_quality_rows`  | Filtered by `record.section == "MIXING"`.   |

Anything else → `()`.

### Name normalisation

```
strip whitespace → strip leading "[" / trailing "]" → strip whitespace → upper()
```

Empty / whitespace-only / bare-bracket input (`""`, `"   "`, `"[]"`,
`"[ ]"`) returns `()`. The accessor never raises on lookup — it is
deliberately non-throwing so UI / API / report code can call it with
arbitrary user input.

### Return value

Every call returns a freshly-allocated `tuple`. The tuple itself is
immutable (a `TypeError` is raised by Python on item assignment), and
copying the tuple to a list and mutating the copy cannot affect the
diagnostics container (it carries no references to internal state
that could be reached through the returned records).

## Row diagnostics vs ignored-section presence semantics

`rows_for_section` reads **row diagnostics only**: the five row
channels populated by Sprints 23 / 25 / 26 / 28 / 29. It never
returns `EpanetIgnoredSectionDiagnostic` records.

This keeps the surfaces orthogonal and prevents double-counting:

- A fixture with both `ignored_sections=[CONTROLS]` (a
  presence record) and `control_rule_rows` for `[CONTROLS]` (per-row
  records) returns only the row diagnostics from
  `rows_for_section("CONTROLS")`. The presence record stays on the
  presence channel (`ignored_section_names()`).
- A fixture declaring only `[TITLE]` or `[REPORT]` — sections that
  never emit per-row diagnostics — returns `()` from
  `rows_for_section("TITLE")` / `rows_for_section("REPORT")` even
  though both names appear in `ignored_section_names()`.
- For every section that **can** be populated by a row channel, the
  identity
  `len(rows_for_section(s)) == row_count_by_section()[s]` holds.
  This is asserted directly in the test suite.

## Fallback parser behaviour

The fallback parser is unchanged. Sprints 23 / 25 / 26 / 28 / 29
already populate the five row channels in source-file order;
`rows_for_section` is a pure read-only view over those channels.

- `status_rows` already only contains `STATUS` records → returned
  directly as a tuple.
- `control_rule_rows`, `pattern_energy_rows`, `emitter_demand_rows`,
  and `water_quality_rows` all carry a `.section` field whose value is
  one of the canonical EPANET section names; the accessor filters in
  source-channel order.

The Sprint 22 `[STATUS]` rejection contract (`CLOSED`, `CV`, numeric
pump-status, unknown link id, arbitrary token) is preserved
unchanged: rejected rows raise `ValueError` before any diagnostics
container is constructed, so `rows_for_section` is never called on
partial state.

## WNTR back-end behaviour / asymmetry

When diagnostics are obtained via `parser="wntr"` the WNTR adapter
does not populate any row diagnostic channels (Sprint 23–30
asymmetry, intentional). `rows_for_section(name)` therefore returns
`()` for every section, mirroring the empty `row_count_by_section()`
/ `summary()` output the WNTR back-end already produces.

`tests/dphm/test_inp_rows_for_section.py::test_wntr_rows_for_section_is_empty`
exercises this on a WNTR-parseable fixture
(`[STATUS]` / `[PATTERNS]` / `[QUALITY]` / `[SOURCES]`) and is
guarded by `pytest.importorskip("wntr")` so it skips cleanly when
WNTR is not installed.

## Read-only / no-op evidence

- `EpanetImportDiagnostics` remains `frozen=True` (asserted in
  `test_container_remains_frozen_dataclass`).
- Calling `rows_for_section` with every canonical section name plus
  unknown / empty input leaves the underlying tuple identities
  unchanged (`test_helpers_do_not_mutate_container`).
- The return value is a `tuple` (`test_return_value_is_tuple_backed`)
  and is structurally immutable
  (`test_returned_tuple_cannot_mutate_diagnostics`).
- The `Network` loaded from the all-channels fixture is bit-equal on
  every field the dPHM core consumes to the network loaded from the
  baseline fixture (`test_network_identical_with_and_without_diagnostic_sections`).
  Compared fields: `num_nodes`, `num_edges`, `num_fixed_heads`,
  `edge_index`, `pipe_mask`, `pump_mask`, `fixed_head_mask`,
  `demands`, `fixed_head_values`, `lengths`, `diameters`,
  `c_factors`, `pump_speeds`.
- Default `load_network_from_inp(path)` continues to return only the
  `Network` (`test_load_network_from_inp_default_remains_network_only`).
- Sprint 22 rejection still raises
  (`test_status_rejection_still_raises`).

## Tests added / updated

New file: `tests/dphm/test_inp_rows_for_section.py` — 26 tests:

- **API existence (2):** method is present and callable; empty
  container returns `()` for every section.
- **Per-channel routing (5):** `STATUS`, `CONTROLS` / `RULES`,
  `PATTERNS` / `ENERGY`, `EMITTERS` / `DEMANDS`, `QUALITY` /
  `SOURCES` / `REACTIONS` / `MIXING`.
- **Name normalisation (5):** case-insensitive lookup, whitespace
  stripping, bracket notation, unknown section, empty / whitespace /
  bracket-only input.
- **Surface separation (2):** ignored-section presence is never
  surfaced; `len(rows_for_section(s)) == row_count_by_section()[s]`
  for every row-channel section.
- **Determinism / read-only (4):** source-order preservation;
  `tuple` return type; mutation of the returned value cannot reach
  the container; calling the accessor with many section names leaves
  underlying tuple identities unchanged.
- **Container immutability (1):** `EpanetImportDiagnostics` is still
  `frozen=True`.
- **Parser integration (5):** fallback parser routes every section to
  the channel-filtered tuple; row counts match
  `row_count_by_section()`; `load_inp_diagnostics` and
  `load_network_from_inp(..., return_diagnostics=True)` agree; default
  `load_network_from_inp(path)` returns only a `Network`; the
  `Network` loaded with and without diagnostic-row sections is
  hydraulically identical.
- **Backwards compatibility (1):** Sprint 22 `[STATUS] CLOSED` still
  raises.
- **WNTR asymmetry (1):** every section returns `()` under
  `parser="wntr"` (skipped if WNTR is not installed).

No existing tests were modified.

## Validation commands & results

```
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
1278 passed, 1 skipped, 3 warnings in 92.00s

$ python -m pytest tests -q
1286 passed, 1 skipped, 3 warnings in 84.31s

$ python -m compileall -q src tests
exit=0

$ git status --short
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/inp_io.py
?? tests/dphm/test_inp_rows_for_section.py
```

Sprint 30 baseline (for comparison):

```
1252 passed, 1 skipped (targeted)
1260 passed, 1 skipped (full)
```

Sprint 31 deltas:

```
+26 new tests in tests/dphm/test_inp_rows_for_section.py
   targeted: 1252 → 1278 (+26)
   full:     1260 → 1286 (+26)
```

The single `SKIPPED` is the long-standing
`tests/dphm/test_wntr_optional_import.py:371` "WNTR is installed;
ImportError path not exercised here" skip — unchanged from Sprint 30.

## Compatibility notes

- The Sprint 11 contract on `load_network_from_inp(path)` returning
  only a `Network` is preserved.
- The Sprint 22 / 23 `[STATUS]` rejection contract is preserved
  (`CLOSED`, `CV`, numeric pump-status, unknown link id, arbitrary
  token).
- Every Sprint 11–30 test still passes; no existing test was
  modified.
- HEAD pump, POWER pump, PRV, TCV, demand-multiplier, SI / GPM,
  pressure-unit, specific-gravity, viscosity, ignored-section,
  control-rule, pattern-energy, emitter-demand, water-quality, and
  summary tests all pass.
- The diagnostics container is still `frozen=True` and the public
  `EpanetImportDiagnostics(...)` constructor signature is unchanged
  (no new fields). Adding a new method to a frozen dataclass is a
  backwards-compatible change.

## Known limitations

- WNTR-back-end `rows_for_section` always returns `()` because the
  WNTR adapter does not populate any row diagnostic channels.
  Cross-parser diagnostic parity is **not** a Sprint 31 goal; this
  matches the documented Sprint 23–30 asymmetry.
- The accessor is for **row** diagnostics. Ignored-section presence
  remains a separate surface (`ignored_section_names()`); a
  single combined accessor was deliberately not added because it
  would re-introduce the double-counting risk Sprint 30 designed
  out.
- Unknown / future EPANET section names (e.g. anything outside the
  11 canonical sections) return `()`. Sprint 32 may extend the
  routing table when new row channels are added.

## Verdict

**APPROVED**

All Sprint 31 hard approval gates are satisfied:

- targeted pytest exits 0 (1278 passed, 1 skipped)
- full pytest exits 0 (1286 passed, 1 skipped)
- `python -m compileall src tests` exits 0
- `SPRINT31_REPORT.md` exists (this file)
- `rows_for_section()` API exists and is exercised by 26 dedicated
  tests
- every Sprint 23–30 diagnostic channel is reachable through
  `rows_for_section` with the correct section → channel routing
- lookup is deterministic (canonical-name normalisation pipeline),
  read-only (`tuple` return; container `frozen=True`), and
  non-throwing
- lookup does not double-count and does not return
  `EpanetIgnoredSectionDiagnostic` presence records
- Sprint 30 `row_count_by_section()`, `ignored_section_names()`, and
  `summary()` helpers continue to work unchanged
- all Sprint 11–30 tests still pass
- no new EPANET semantics are implemented (no `[STATUS]`
  closed-link / check-valve, no `[CONTROLS]` / `[RULES]`
  evaluation, no `[PATTERNS]` / `[ENERGY]` evaluation, no
  `[EMITTERS]` / `[DEMANDS]` semantics, no water-quality
  simulation, no PLC / SCADA / write path, no dPL parameter
  learning, no Darcy-Weisbach, no ONNX / TensorRT / Jetson)
- diagnostics are proven hydraulically inert: the loaded
  `Network` is bit-equal across baseline and all-channels fixtures
  on every field the dPHM core consumes
- `load_network_from_inp(path)` remains backward compatible by
  default (returns only `Network`)
- Sprint 22 / 23 rejection behaviour is preserved for
  status-changing / invalid `[STATUS]` rows
- HEAD, POWER, PRV, TCV, demand-multiplier, SI / GPM,
  pressure-unit, SG / viscosity, ignored-section, and every
  Sprint 23–30 diagnostics test continues to pass
- WNTR optional tests skip / pass cleanly: with WNTR installed the
  Sprint 31 WNTR-asymmetry test passes (`()` for every section);
  without WNTR the test skips via `pytest.importorskip`
- no credential-bearing files / strings introduced (the repository
  credential scan reports zero flagged files)
- `git status` contains only intended Sprint 31 changes (one
  modified source file, one modified docs file, one new test
  file, plus this report)

## Sprint 32 recommendation

Stay on the **diagnostics ergonomics + visibility** track that
Sprints 23 → 31 established. Recommend:

> **Sprint 32 — Add a per-record diagnostic-record-to-source-line
> lookup, e.g. `record.line_number` populated by the fallback
> parser, plus an `EpanetImportDiagnostics.rows_at_line(line)`
> accessor that returns every row diagnostic emitted by a specific
> source line.**

Rationale:

- Sprint 31 closed the "find rows by section" gap; the next natural
  gap analysts hit is "find rows by source line" (e.g. when an
  external linter or text editor reports a problem on
  `epanet_reference_loop.inp:42`).
- It is the *exact* mirror of Sprint 31 — same surface area, same
  read-only / tuple-backed / hydraulically-inert / non-throwing
  contract, same WNTR asymmetry — so the existing test scaffolding
  carries over cleanly.
- It still does **not** activate any EPANET semantics or modify
  the loaded `Network`, so the Sprint 22 rejection contract and
  the Sprint 11 backwards-compatibility contract remain trivially
  preserved.

Out-of-scope for Sprint 32 (defer further):

- active `[CONTROLS]` / `[RULES]` / `[PATTERNS]` / `[ENERGY]` /
  `[EMITTERS]` / `[DEMANDS]` semantics,
- water-quality simulation,
- Darcy-Weisbach,
- WNTR diagnostic parity,
- PLC / PAC / SCADA adapters,
- dPL parameter learning,
- ONNX / TensorRT / Jetson deployment,
- production / savings claims.
