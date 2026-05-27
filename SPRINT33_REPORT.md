# Sprint 33 — EPANET import-quality report

## Goal

Compose the read-only EPANET `.inp` import diagnostics surfaces grown
across Sprints 23–32 (`status_rows`, `ignored_sections`,
`control_rule_rows`, `pattern_energy_rows`, `emitter_demand_rows`,
`water_quality_rows`, `edge_surrogates`, plus the Sprint 30 / 31 / 32
ergonomics helpers) into a single typed, immutable, read-only
import-quality report a UI / API / shadow-mode caller can render
verbatim — without changing any forward-model behaviour, without
activating any deferred EPANET semantics, and without mutating the
loaded `Network`.

The report answers, on any imported `.inp` file:

- What did the importer accept?
- Which sections produced diagnostics?
- Which ignored sections are present?
- Which unsupported / deferred row semantics exist?
- Which dPHM edges are surrogate approximations?
- What limitations / warnings should a shadow-mode operator see?

## Files changed

- `src/aquaoptima/dphm/inp_import_quality_report.py` (new module)
  carrying the three frozen dataclasses, the public builder
  `build_import_quality_report`, and the convenience loader
  `load_inp_import_quality_report`. Composition-only — no parser
  changes, no semantics changes.
- `src/aquaoptima/dphm/__init__.py` (updated) re-exporting the three
  new dataclasses, the builder, and the loader, and adding them to
  `__all__`.
- `tests/dphm/test_inp_import_quality_report.py` (new) — 34 tests
  covering the surface and the read-only contract.
- `docs/epanet-inp-import.md` (updated) — adds a Sprint 33 section
  describing the public API, composition behaviour, fallback / WNTR
  asymmetry, shadow-mode relevance, safety boundary, and tests.
  Updates the document title to `Sprint 11–33` and appends the new
  test file to the tests table.

No other source file is touched. `inp_io.py` is unchanged — the new
composition layer lives in its own module and only imports the
existing public diagnostics surface.

## API design

### Dataclasses (frozen, immutable)

```python
@dataclass(frozen=True)
class EpanetImportQualitySectionReport:
    section: str
    row_count: int
    ignored_present: bool
    message: str

@dataclass(frozen=True)
class EpanetImportQualitySurrogateReport:
    edge_index: int
    link_id: str
    link_type: str
    surrogate_kind: str
    severity: str
    message: str
    limitations: tuple[str, ...]

@dataclass(frozen=True)
class EpanetImportQualityReport:
    parser: str
    total_diagnostic_rows: int
    ignored_section_count: int
    row_count_by_section: Mapping[str, int]
    ignored_sections: tuple[str, ...]
    sections: tuple[EpanetImportQualitySectionReport, ...]
    surrogates: tuple[EpanetImportQualitySurrogateReport, ...]
    surrogate_count_by_kind: Mapping[str, int]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
```

### Builder

```python
def build_import_quality_report(
    diagnostics: EpanetImportDiagnostics,
    network: Network | None = None,
    *,
    parser: str = "fallback",
) -> EpanetImportQualityReport: ...
```

- Read-only / no-op: never mutates `diagnostics` or `network`, never
  re-tokenises the `.inp` source, never activates deferred EPANET
  semantics, and preserves hydraulic inertness by leaving parser and
  `Network` construction behaviour unchanged.
- Works without `network`; when supplied, validates every surrogate's
  `edge_index` against `network.edge_index.shape[1]` and surfaces a
  deterministic out-of-range warning string without raising.
- Trusts the caller for `parser` (validated against
  `{"fallback", "wntr"}`); does not re-derive from the diagnostics
  container.
- Uses `diagnostics.summary()`,
  `diagnostics.row_count_by_section()`,
  `diagnostics.ignored_section_names()`, and
  `diagnostics.surrogate_count_by_kind()` rather than re-deriving
  counts.

### Convenience loader

```python
def load_inp_import_quality_report(
    source: PathLike,
    *,
    parser: str = "fallback",
    units: str = "si",
    default_c_factor: float = 130.0,
) -> EpanetImportQualityReport: ...
```

- Thin wrapper over
  `load_network_from_inp(..., return_diagnostics=True)` +
  `build_import_quality_report`.
- Rejects `parser="auto"` explicitly so the WNTR-asymmetry surface
  always tracks the back-end choice.

### Public exports

`aquaoptima.dphm.__init__` now re-exports:

- `EpanetImportQualityReport`,
  `EpanetImportQualitySectionReport`,
  `EpanetImportQualitySurrogateReport`
- `build_import_quality_report`,
  `load_inp_import_quality_report`

All are added to `__all__`. Existing exports are unchanged.

## Composition behaviour

The builder is pure composition over the Sprint 23–32 read-only
surfaces:

| Report field             | Source on `EpanetImportDiagnostics`                                        |
|--------------------------|----------------------------------------------------------------------------|
| `total_diagnostic_rows`  | `summary().total_diagnostic_rows`                                          |
| `ignored_section_count`  | `summary().ignored_section_count`                                          |
| `row_count_by_section`   | `row_count_by_section()` (fresh dict per build)                           |
| `ignored_sections`       | `ignored_section_names()`                                                  |
| `sections`               | Union of the two surfaces above, in canonical EPANET-section order        |
| `surrogates`             | `edge_surrogates` (mirrored 1:1, in source order)                         |
| `surrogate_count_by_kind`| `surrogate_count_by_kind()` (fresh dict per build)                         |

`sections` ordering is the canonical row-channel order followed by the
layout / time-control members of `IGNORED_SECTIONS`, with any unknown /
future section name appended in alphabetical order. Each section
surfaces exactly once: a section with both row diagnostics and
ignored-section presence (e.g. `[CONTROLS]` carrying two `LINK PU1 ...`
rows) shows as a single entry with `ignored_present=True` and
`row_count > 0`.

`limitations` always includes:

- the `[STATUS]` open-only note (CLOSED / CV / numeric still raise at
  parse time);
- the ignored-sections-dropped note (CONTROLS / RULES / PATTERNS /
  ENERGY / EMITTERS / DEMANDS / QUALITY / SOURCES / REACTIONS / MIXING
  and inert layout sections are dropped at parse time).

For `parser="wntr"`, an additional asymmetry note is appended:

- the WNTR back-end does not emit Sprint 23-32 diagnostics, so the
  report is empty / minimal under WNTR.

For every surrogate kind present, the Sprint 32 per-record
`limitations` tuples are flattened and de-duplicated (first-occurrence
order preserved) onto `report.limitations`.

`warnings` is deterministic:

- when `parser="wntr"` and every diagnostic channel is empty, a single
  empty-diagnostics warning is added.
- when a `Network` is supplied, one warning per out-of-range surrogate
  `edge_index` is appended (the diagnostic record itself is preserved
  verbatim).

## Tests added

`tests/dphm/test_inp_import_quality_report.py` (34 tests):

- Frozen dataclass surface (3 dataclasses).
- Empty diagnostics produce a zero-count report with no surrogates.
- `row_count_by_section`, `ignored_sections`, `summary` parity.
- Per-section entries: row-only (STATUS), ignored-only (TITLE),
  row+ignored (CONTROLS) — no double counting; each section appears at
  most once.
- Sprint 32 edge surrogates flow through verbatim (PRV + TCV fixture);
  field-by-field equality with the source diagnostic.
- `surrogate_count_by_kind` mirrors the helper and is a fresh dict on
  each build call.
- Network-supplied validation: out-of-range surrogate `edge_index`
  surfaces a deterministic warning without raising; in-range index
  produces no warning; omitting the network skips validation.
- Determinism: two builds on the same inputs produce equal reports
  (equal tuples, equal mappings, equal warnings, equal limitations).
- Read-only / no-op: neither the diagnostics container nor the network
  is mutated; hydraulic inertness is preserved because the builder is a
  reporting layer only.
- Convenience loader matches the explicit
  `load_network_from_inp(..., return_diagnostics=True)` +
  `build_import_quality_report` pair.
- `load_inp_import_quality_report(parser="auto")` is rejected.
- Default `load_network_from_inp(path)` continues to return only the
  `Network` (Sprint 11 contract preserved).
- Parser kwarg validation: unknown tokens raise `ValueError`.
- Surrogate limitations flow into `report.limitations` and duplicates
  across multiple surrogate records are deduplicated.
- WNTR optional path (`pytest.importorskip("wntr")`): empty / minimal
  report with the documented asymmetry limitation; loader agrees with
  explicit build path under `parser="wntr"`.
- Sprint 23-32 helpers still work alongside the new builder.

## Validation commands / results

```bash
python -m pip install -e .                                              # editable install
python -m pytest tests/dphm/test_inp_import_quality_report.py -q        # new tests
python -m pytest tests/dphm tests/models tests/training tests/dataio -q # related suites
python -m pytest tests -q                                               # full suite
python -m compileall -q src tests                                       # bytecode check
git diff --check                                                        # whitespace check
```

Results:

- `pytest tests/dphm/test_inp_import_quality_report.py` — **34 passed**
  in ~5s.
- `pytest tests/dphm tests/models tests/training tests/dataio` — **1336
  passed, 1 skipped** (the pre-existing WNTR-not-installed skip path)
  in ~100s.
- `pytest tests` — **1344 passed, 1 skipped** (same pre-existing skip)
  in ~94s.
- `compileall -q src tests` — no output (clean).
- `git diff --check` — no output (clean).

WNTR version detected by `python -c "import wntr; print(wntr.__version__)"`:
`1.4.0`.

## Compatibility notes

- Default `load_network_from_inp(path)` still returns only a
  `Network`. Sprint 11–32 callers see no behavioural change.
- `load_inp_diagnostics(path)` is unchanged.
- `EpanetImportDiagnostics`, `EpanetImportDiagnosticsSummary`, and
  every Sprint 23-32 record dataclass are unchanged (no new fields,
  no changed field defaults).
- The fallback parser and the WNTR adapter are unchanged. No new INP
  section is parsed; no existing section is parsed differently.
- The new report module imports only public surfaces from `inp_io`
  and the `Network` dataclass, so there is no circular import risk.

## Known limitations

- The WNTR back-end still emits an empty `EpanetImportDiagnostics`.
  The Sprint 33 report tracks that asymmetry through
  `warnings` / `limitations` entries but does not close it — WNTR
  parity is deferred (see roadmap).
- `network`-supplied edge-index range validation checks the
  surrogate's index against `network.edge_index.shape[1]`. It does
  not cross-check the surrogate's `link_id` against the loaded edge
  list (the importer does not retain a link-id → edge-index map on
  the `Network`); a downstream consumer that needs that mapping can
  derive it from the surrogate records themselves.
- `limitations` is human-readable text. The report is intentionally a
  rendering surface, not a structured limitation taxonomy; downstream
  callers that need a stable machine token should use the surrogate
  `surrogate_kind` codes (already exported as
  `EDGE_SURROGATE_KIND_PRV_FIXED_HEAD` /
  `EDGE_SURROGATE_KIND_TCV_MINOR_LOSS`).

## Verdict

Ship.

- Surface is read-only, frozen, deterministic, and composes only
  Sprint 23-32 public surfaces.
- Loaded `Network` is byte-for-byte unchanged; no EPANET semantics
  are activated.
- 34 new tests pin the contract; the full pre-existing 1310-test
  suite still passes (1344 total with the new tests).
- Documentation is updated; safety boundary is reaffirmed.

## Sprint 34 recommendation

Telemetry tag-map adapter with a canonical telemetry schema.

The Sprint 33 import-quality report names every dPHM edge that came
from a surrogate (PRV / TCV) and every dPHM node that the parser
implicitly pinned (reservoirs, tanks, PRV downstream nodes). A
shadow-mode operator can therefore reason about *which dPHM IDs are
load-bearing* without touching the parser. The next bottleneck is
mapping those dPHM IDs to operator-facing telemetry tags (sensor IDs,
SCADA / historian point names) so the same report can carry an
operator-facing label.

Recommended scope for Sprint 34:

- a `TelemetryTagMap` adapter (frozen dataclass + builder + loader)
  that maps an operator-supplied `{tag → dPHM node / edge}` table
  through a canonical telemetry schema (units, role, measurement
  axis) into a read-only side-channel a UI / API caller can join
  against the Sprint 33 report;
- strict validation at the boundary: tag uniqueness, dPHM id
  existence (cross-checked against the loaded `Network`), unit
  family validity, no SCADA / PLC / PAC write path activated;
- no field-validation claim, no historian / OPC-UA / MQTT binding,
  no live ingestion — read-only schema adapter only;
- a deterministic, fail-fast surface that fits behind the same
  shadow-mode safety boundary as Sprints 23-33.

This keeps the safety boundary unchanged while widening the read-only
surface dPHM exposes to an operator-facing UI.
