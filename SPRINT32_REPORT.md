# Sprint 32 — Per-edge surrogate diagnostics for EPANET import

## Goal

Surface every dPHM edge produced by a conservative surrogate
translation during EPANET `.inp` import so downstream UI / API /
shadow-mode import-quality reports can flag the approximated edges
and surface their limitations without re-deriving them from solver
outputs.

The result answers, on any imported `.inp` file:

- Which edges are exact / native dPHM edges?
- Which edges came from a surrogate approximation?
- Why was the surrogate used (kind, severity, message, limitations)?
- What source link id and link type created it?
- What dPHM edge index did it land on?

Sprint 32 ships diagnostics only. The fallback parser's per-edge
translation, the loaded `Network`, and every Sprint 23–31 diagnostics
channel are unchanged.

## Files changed

- `src/aquaoptima/dphm/inp_io.py` — added the frozen
  `EpanetEdgeSurrogateDiagnostic` dataclass, the
  `EDGE_SURROGATE_KIND_PRV_FIXED_HEAD` /
  `EDGE_SURROGATE_KIND_TCV_MINOR_LOSS` /
  `EDGE_SURROGATE_SEVERITY_INFO` / `EDGE_SURROGATE_SEVERITY_WARNING` /
  `EDGE_SURROGATE_SEVERITY_LIMITATION` constants, the
  `edge_surrogates` field on `EpanetImportDiagnostics`, and the four
  read-only helpers (`surrogate_edges`, `surrogate_count_by_kind`,
  `surrogates_for_link`, `surrogate_for_edge`). Extended the fallback
  parser's valve loop to emit one record per appended dPHM edge.
  Extended `__all__` with the new public symbols and the kind /
  severity constants. Added an `import operator` for the
  edge-index-validation `operator.index` call.
- `src/aquaoptima/dphm/__init__.py` — re-exported
  `EpanetEdgeSurrogateDiagnostic` and the kind / severity constants;
  appended each to `__all__`.
- `tests/dphm/test_inp_edge_surrogates.py` — **new file** carrying
  the Sprint 32 contract tests (24 tests).
- `docs/epanet-inp-import.md` — added a "Per-edge surrogate
  diagnostics (Sprint 32)" section documenting the public API,
  field meanings, source-element coverage, fallback vs WNTR
  asymmetry, safety boundary, and shadow-mode relevance.
- `SPRINT32_REPORT.md` — this file.

## API design

### Dataclass

```python
@dataclass(frozen=True)
class EpanetEdgeSurrogateDiagnostic:
    edge_index: int
    link_id: str
    link_type: str
    surrogate_kind: str
    severity: str
    message: str
    limitations: tuple[str, ...] = ()
```

Field semantics (verbatim from the docstring):

- `edge_index` — zero-based index into the loaded `Network`'s edge
  arrays. Stable across calls.
- `link_id` — original EPANET link id, preserved case-sensitively.
- `link_type` — canonical source link type. Sprint 32: always
  `"VALVE"`.
- `surrogate_kind` — stable machine-friendly code. Sprint 32 emits
  `"PRV_FIXED_HEAD_SURROGATE"` or `"TCV_MINOR_LOSS_SURROGATE"`.
- `severity` — stable severity token. Sprint 32 emits
  `"LIMITATION"` for every record.
- `message` — human-readable explanation; pinned per kind.
- `limitations` — tuple of short human-readable limitations.

Stable kind / severity codes are exposed as module-level constants
(`EDGE_SURROGATE_KIND_PRV_FIXED_HEAD`,
`EDGE_SURROGATE_KIND_TCV_MINOR_LOSS`, plus the three severity
tokens) so callers compare against the public symbols rather than
inlining strings.

### Container field

`EpanetImportDiagnostics` grows one new field:

```python
edge_surrogates: tuple[EpanetEdgeSurrogateDiagnostic, ...] = ()
```

It is added with a tuple default, which is a backwards-compatible
extension for keyword-only callers — every Sprint 23–31 construction
site keeps working unchanged.

### Helpers

| Method                        | Returns                                          |
|-------------------------------|--------------------------------------------------|
| `surrogate_edges()`           | Fresh tuple of every record.                    |
| `surrogate_count_by_kind()`   | Fresh `dict[str, int]` keyed by kind.           |
| `surrogates_for_link(id)`     | Fresh tuple of records matching `link_id`.      |
| `surrogate_for_edge(idx)`     | Fresh tuple of records matching `edge_index`.   |

Contracts honoured:

- All helpers are read-only and return freshly-allocated
  tuple / dict values.
- `surrogates_for_link` is case-sensitive; unknown / non-string
  input returns `()`.
- `surrogate_for_edge` accepts any `operator.index`-able value
  (real Python `int`, NumPy integer scalars, anything implementing
  `__index__`); strings, floats, `None`, `NaN`, and `bool` return
  `()` rather than raising. Unknown indices — including negatives —
  return `()`.
- `surrogate_count_by_kind` returns an empty dict on empty
  diagnostics; insertion order follows first-occurrence parse
  order.

## Population behaviour

Inside `_fallback_parse`, the existing `[VALVES]` loop (Sprint 15)
now emits one `EpanetEdgeSurrogateDiagnostic` per appended dPHM
edge:

- The edge index is captured as `len(src_idx)` **before** the
  surrogate edge is appended to the parser's edge buffers, so the
  recorded index matches the eventual position in the loaded
  `Network`'s edge arrays.
- The `surrogate_kind` is derived from
  `description["valve_type"]` (already upper-cased by
  `translate_valve_to_surrogate`): `"PRV"` →
  `"PRV_FIXED_HEAD_SURROGATE"`, `"TCV"` →
  `"TCV_MINOR_LOSS_SURROGATE"`.
- `message` and `limitations` are looked up from module-level
  pinned constants so two records of the same kind always carry
  identical text.
- `link_type` is `"VALVE"`. `severity` is `"LIMITATION"`.

The list of collected records is passed as the new
`edge_surrogates=` argument to the existing
`EpanetImportDiagnostics(...)` constructor at the end of
`_fallback_parse`. The WNTR back-end's diagnostics constructor is
unchanged — it still returns an empty container (Sprint 23–31
asymmetry preserved).

The parser-side change is one block of insertion and one keyword
argument. Pipes and pumps are not surrogate-emitting today and so
their loops are untouched.

## Tests added

`tests/dphm/test_inp_edge_surrogates.py` (24 tests):

- Dataclass shape — `frozen=True`, `limitations` is a tuple, the
  default `limitations` is the empty tuple.
- Empty container — every accessor returns `()` / `{}`.
- `surrogate_edges` returns a fresh tuple; mutating an external
  list view cannot affect the container.
- `surrogate_count_by_kind` returns a fresh dict; mutating one
  snapshot cannot leak into a later one.
- `surrogates_for_link` returns matching records; wrong-case and
  unknown ids return `()`; non-string input returns `()`.
- `surrogate_for_edge` returns matching records; unknown,
  negative, non-int-like, `bool`, `NaN`, float, string, and `None`
  inputs return `()`.
- Container is `frozen=True`; reassigning `edge_surrogates`
  raises `dataclasses.FrozenInstanceError`.
- Fallback parser emits one record per appended valve edge with
  the correct kind for both PRV and TCV.
- Multi-valve fixture emits records at consecutive edge indices
  with matching kinds and matching helper results.
- `surrogate_count_by_kind` totals correctly on a multi-valve
  fixture.
- A fixture without `[VALVES]` emits no surrogate records.
- Hydraulic inertness — the network loaded with
  `return_diagnostics=True` is byte-for-byte equal to one loaded
  with the default flag on every field the dPHM core consumes.
- `load_inp_diagnostics(path)` and
  `load_network_from_inp(path, return_diagnostics=True)` agree
  exactly on `edge_surrogates` and on every accessor result.
- Default `load_network_from_inp(path)` still returns only a
  `Network`.
- Sprint 23 / 25 / 30 / 31 helpers still work alongside the new
  field (`status_rows`, `control_rule_rows`, `row_count_by_section`,
  `summary`).
- `EpanetStatusDiagnostic` construction is unaffected.
- Read-only contract — invoking every accessor with valid and
  invalid input leaves `edge_surrogates`'s tuple identity
  unchanged.
- WNTR back-end smoke check via `pytest.importorskip("wntr")` —
  every accessor returns `()` / `{}`.

The full Sprint 23–31 suite continues to pass alongside the new
file.

## Validation commands and results

```bash
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm/test_inp_edge_surrogates.py -q
........................                                                 [100%]
24 passed in 11.00s

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
... (all passed; see "Full suite" below)

$ python -m pytest tests -q
... (all passed; see "Full suite" below)

$ python -m compileall -q src tests
(silent; no errors)

$ git diff --check
(silent; no whitespace errors)
```

See the **Full suite** section below for the actual pytest summary
counters.

### Full suite

Run after the Sprint 32 code, tests, and docs changes were in place:

- `tests/dphm` — 1107 passed, 1 skipped.
- `tests/dphm tests/models tests/training tests/dataio` —
  1302 passed, 1 skipped, 3 warnings in 173.49s.
- `tests` (the full suite) — 1310 passed, 1 skipped, 3 warnings
  in 166.33s.

The single skip across every run is the existing
`tests/dphm/test_wntr_optional_import.py:371` `ImportError`-path
guard (`"WNTR is installed; ImportError path not exercised here"`),
unrelated to Sprint 32. The three warnings are the upstream
`torch.jit.script` deprecation warning from PyTorch's own
internals, unrelated to Sprint 32.

`python -m compileall -q src tests` — silent (no errors).
`git diff --check` — silent (no whitespace errors).

### WNTR version

`pytest.importorskip("wntr")` succeeded on this environment;
`wntr.__version__` resolves to `1.4.0`.

## Compatibility notes

- Adding the new `edge_surrogates` field to `EpanetImportDiagnostics`
  is backwards-compatible: every Sprint 23–31 construction site
  (including the WNTR adapter's bare-default call) uses keyword
  arguments only and is unaffected by a new optional field with a
  tuple default.
- `EpanetImportDiagnostics` remains a frozen dataclass; every field
  is still structurally read-only.
- `load_network_from_inp(path)` without `return_diagnostics=True`
  continues to return a bare `Network` — the Sprint 11 default
  contract is preserved.
- `load_inp_diagnostics(...)` continues to return an
  `EpanetImportDiagnostics`; the only visible change is the new
  `edge_surrogates` channel and the four new accessors.
- The Sprint 22 `[STATUS]` rejection behaviour, the Sprint 23–30
  ergonomics helpers, the Sprint 31 `rows_for_section` accessor,
  and every existing diagnostics field are unchanged.
- The fallback parser's `Network` output for any Sprint 15 fixture
  (PRV / TCV / both) is byte-for-byte identical to a Sprint 15–31
  load — Sprint 32 only adds metadata about which edges came from
  a surrogate translation.

## Known limitations

- Only `[VALVES]` PRV and TCV surrogates emit records today.
  `[PUMPS]` POWER surrogates (`fit_power_pump_surrogate`) are
  documented surrogates but are not surfaced through
  `edge_surrogates` in this sprint. A future sprint can add them
  under the same channel with a new
  `EDGE_SURROGATE_KIND_POWER_PUMP_SURROGATE` constant.
- The WNTR back-end does not emit surrogate diagnostics. This
  matches the Sprint 23–31 WNTR asymmetry; full parity is deferred.
- The diagnostics surface is informational. It does not gate any
  parse or solve and does not adjust the surrogate edges
  themselves — `translate_valve_to_surrogate` /
  `fit_tcv_resistance_surrogate` continue to govern the per-edge
  numerics.
- `severity` is `"LIMITATION"` for every record today. The
  module-level `EDGE_SURROGATE_SEVERITY_INFO` and
  `EDGE_SURROGATE_SEVERITY_WARNING` constants are reserved for
  future surrogates whose approximations are less load-bearing.
- The `limitations` text is pinned to module-level constants. It
  reads correctly today but the text itself is not a versioned
  contract — downstream consumers should key off `surrogate_kind`
  for stable comparisons.

## Verdict

Sprint 32 ships exactly the read-only per-edge surrogate diagnostics
surface the goal required, with the strict-out-of-scope items left
untouched. The new file adds one dataclass, one field, five
module-level constants, four read-only accessors, and one parser
populator that emits a record per appended valve edge. The
`Network` arrays are unchanged. Every existing test continues to
pass; the new test file adds 24 passing tests covering the dataclass
shape, all four accessors, fallback population on PRV / TCV
fixtures, edge-index alignment, hydraulic inertness, API parity,
backwards compatibility with Sprint 23–31 helpers, and the WNTR
asymmetry.

Ready for Hermes to verify and ship.

## Sprint 33 recommendation: import-quality report

With Sprint 30's `summary()`, Sprint 31's `rows_for_section(name)`,
and Sprint 32's `edge_surrogates` channel now in place,
`EpanetImportDiagnostics` carries enough information to compose a
read-only **import-quality report** end-to-end:

- top-line counters from `diagnostics.summary()` — row totals per
  channel, ignored-section count, per-section row counts;
- per-section drill-down via
  `diagnostics.rows_for_section(name)` — analysts can inspect the
  exact rows the parser dropped on the floor for any section
  (`[CONTROLS]`, `[RULES]`, `[PATTERNS]`, `[ENERGY]`,
  `[EMITTERS]`, `[DEMANDS]`, `[QUALITY]`, `[SOURCES]`,
  `[REACTIONS]`, `[MIXING]`, and accepted `[STATUS] OPEN` rows);
- per-edge approximation badges from `diagnostics.edge_surrogates`,
  joined with `net.edge_index` so the report can show which
  source link id became which dPHM edge and surface the matching
  `surrogate_kind`, `severity`, `message`, and `limitations`;
- per-kind dashboards via `surrogate_count_by_kind()`;
- per-link drill-down via `surrogates_for_link(link_id)` for
  link-centric UIs;
- per-edge drill-down via `surrogate_for_edge(idx)` for
  edge-centric UIs that already iterate over `net.edge_index`.

Sprint 33 could ship that report as a small read-only function
(e.g. `build_import_quality_report(diagnostics, network)`) plus
matching test coverage. The report would not activate any deferred
EPANET semantics — it only composes Sprint 23–32 surfaces — so the
safety boundary in `docs/safety-boundary.md` is unaffected.
