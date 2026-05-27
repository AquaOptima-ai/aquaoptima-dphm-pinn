# Sprint 24 Report — Read-only EPANET ignored-section diagnostics

## Goal

Extend the Sprint 23 read-only `EpanetImportDiagnostics` container so
analysts can see **which `IGNORED_SECTIONS` were actually present** in
an imported EPANET `.inp` file (e.g. `[CONTROLS]`, `[RULES]`,
`[PATTERNS]`, `[ENERGY]`). The diagnostics path must not change any
hydraulic field on the loaded `Network`, must preserve the Sprint 21
byte-for-byte ignored-section invariance contract, must exclude
`[STATUS]` (Sprint 22 removed it from `IGNORED_SECTIONS`), and must
keep `load_network_from_inp(path)` backward-compatible.

## Files changed

| Path                                                                       | Change                                                                                                                                                                                                              |
|----------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                                            | Added `EpanetIgnoredSectionDiagnostic` frozen dataclass; added `_IGNORED_SECTION_NOOP_MESSAGE`; extended `EpanetImportDiagnostics` with a new tuple-backed `ignored_sections` field (default `()`); added `_collect_ignored_section_diagnostics` helper; wired both into `_fallback_parse`; added module-docstring preamble and Sprint 24 mention; extended `load_inp_diagnostics` docstring; updated `__all__`. |
| `src/aquaoptima/dphm/__init__.py`                                          | Re-exported `EpanetIgnoredSectionDiagnostic` at the top-level `aquaoptima.dphm` namespace.                                                                                                                                                                                                                                                                                                                       |
| `docs/epanet-inp-import.md`                                                | Title bumped to Sprint 11–24; added Sprint 24 preamble paragraph; added new "Read-only ignored-section diagnostics (Sprint 24)" section with public API, dataclass shape, behaviour, hydraulic-inertness statement, WNTR back-end asymmetry, and test list.                                                                                                                                                       |
| `tests/dphm/test_inp_ignored_section_diagnostics.py`                       | New test module — 39 tests pinning the Sprint 24 contract end-to-end.                                                                                                                                                                                                                                                                                                                                              |
| `SPRINT24_REPORT.md`                                                       | This report.                                                                                                                                                                                                                                                                                                                                                                                                       |

No fixture files added, no Python dependencies changed, no secrets
introduced.

## Ignored-section diagnostics API design

The richer typed-record shape was chosen over the simpler
`tuple[str, ...]` because the existing diagnostics code style heavily
favours typed frozen records (`EpanetStatusDiagnostic`,
`EpanetUnitSystem`, `EpanetPressureUnit`). Typed records also leave
room to grow the per-record surface (e.g. a future `severity` field)
without breaking the API.

```python
from aquaoptima.dphm import (
    EpanetIgnoredSectionDiagnostic,
    EpanetImportDiagnostics,
    load_inp_diagnostics,
    load_network_from_inp,
)
```

Two equally-valid entry points (unchanged from Sprint 23):

```python
# A) Explicit read-only diagnostics accessor.
diagnostics = load_inp_diagnostics(path, parser="fallback")
for rec in diagnostics.ignored_sections:
    print(rec.section, rec.row_count, rec.message)

# B) One call returning both the Network and the diagnostics.
network, diagnostics = load_network_from_inp(
    path, parser="fallback", return_diagnostics=True,
)
```

`load_network_from_inp(path)` (without `return_diagnostics=True`)
**continues to return only a `Network`** — Sprint 11–23 callers need
no changes.

Dataclasses (both `frozen=True`):

```python
@dataclass(frozen=True)
class EpanetIgnoredSectionDiagnostic:
    section: str                   # canonical upper-case section name
    row_count: int                 # non-blank, comment-stripped rows
    message: str = "Section present but ignored by the steady-state dPHM importer."


@dataclass(frozen=True)
class EpanetImportDiagnostics:
    status_rows: tuple[EpanetStatusDiagnostic, ...] = ()
    ignored_sections: tuple[EpanetIgnoredSectionDiagnostic, ...] = ()
```

`ignored_sections` is a `tuple` (not a list); the dataclass is frozen;
both fields default to `()` so Sprint 23 callers stay
backwards-compatible.

## Fallback parser behaviour

- `_collect_ignored_section_diagnostics(sections)` iterates the
  per-section tokenised rows produced by `_split_sections` and emits
  one `EpanetIgnoredSectionDiagnostic` for every section header that
  is both declared in the source file **and** a member of
  `IGNORED_SECTIONS`.
- Records appear in **source order** — `_split_sections` is built on
  a regular `dict`, which preserves insertion order on Python 3.7+.
- A bare header with an empty body still produces a diagnostic with
  `row_count = 0` because the file declared the section.
- Repeated headers (e.g. two `[CONTROLS]` blocks in one file) collapse
  to a single record whose `row_count` reflects the total rows that
  `_split_sections` accumulated under that section.
- `[STATUS]` is excluded by construction because it is not in
  `IGNORED_SECTIONS` from Sprint 22 onwards. Accepted `[STATUS] OPEN`
  rows continue to surface through `status_rows`; rejected rows still
  raise.
- Hydraulically-active sections (`[JUNCTIONS]`, `[PIPES]`,
  `[OPTIONS]`, `[CURVES]`, …) are excluded by construction because
  they are not in `IGNORED_SECTIONS`.
- `_fallback_parse(...)` returns `(Network, EpanetImportDiagnostics)`
  with the same `Network` it built in Sprint 23 — the new diagnostics
  are computed alongside the parse and never mutate any hydraulic
  field.

## WNTR back-end behaviour

- `_wntr_parse(...)` continues to return an
  `EpanetImportDiagnostics` whose **both** `status_rows` and
  `ignored_sections` are empty (defaults). The dPHM WNTR adapter does
  not re-parse `[STATUS]` (Sprint 23) and does not enumerate
  WNTR-side per-section presence (Sprint 24). WNTR has its own
  per-section handling and the dPHM importer is documented as
  fallback-authoritative for the diagnostics surface.
- The documented asymmetry mirrors Sprint 23's
  fallback-authoritative split. The optional WNTR smoke test in
  `tests/dphm/test_inp_ignored_section_diagnostics.py` only asserts
  the WNTR API does not raise and returns the read-only container
  shape; it does **not** require parity with the fallback
  diagnostics.

## Read-only / hydraulically-inert evidence

The Sprint 24 test suite explicitly proves the no-op contract:

- `test_ignored_section_diagnostics_do_not_change_network` — loads a
  fixture with `[CONTROLS]` + `[RULES]` + `[PATTERNS]` + `[ENERGY]`
  added and a baseline fixture without any of those; uses the same
  `_assert_networks_identical` helper as the Sprint 21/22/23 suites
  to confirm `num_nodes`, `num_edges`, `num_fixed_heads`,
  `edge_index`, `pipe_mask`, `pump_mask`, `fixed_head_mask`,
  `demands`, `fixed_head_values`, `lengths`, `diameters`,
  `c_factors`, `pump_speeds`, and `pump_coeffs` are byte-for-byte
  identical.
- `test_return_diagnostics_network_matches_default_load` — confirms
  the `Network` returned by
  `load_network_from_inp(..., return_diagnostics=True)` is identical
  to the one returned by the default
  `load_network_from_inp(...)`.
- `test_default_load_network_from_inp_still_returns_only_network` —
  confirms the default load returns a bare `Network` even when
  ignored sections are present.
- `test_ignored_section_diagnostic_is_frozen` and
  `test_diagnostics_container_is_frozen_for_ignored_sections` —
  confirm `FrozenInstanceError` on attempted reassignment and
  tuple-backed storage.
- `test_controls_remain_ignored_not_enforced` — Newton-solve heads /
  flows match the baseline to `1e-9` / `1e-12` with `[CONTROLS]`
  declared in the file, proving the Sprint 21 limitation holds.

## Tests added / updated

**Added:** `tests/dphm/test_inp_ignored_section_diagnostics.py` —
39 tests:

- public-surface checks (`EpanetIgnoredSectionDiagnostic` is a frozen
  dataclass, default message contains "ignored",
  `EpanetImportDiagnostics.ignored_sections` defaults to `()` and is
  tuple-backed and frozen);
- empty diagnostics for fixtures with no ignored sections declared
  (no `[TITLE]`/`[END]`);
- baseline fixture with `[TITLE]` and `[END]` surfaces both as
  records;
- per-section presence records for all eleven of `CONTROLS`,
  `RULES`, `PATTERNS`, `ENERGY`, `EMITTERS`, `QUALITY`, `SOURCES`,
  `REACTIONS`, `MIXING`, `TIMES`, `REPORT` (parametrised);
- bare `[CONTROLS]` header (no body) still produces a record with
  `row_count = 0`;
- multiple ignored sections recorded together;
- source-order preservation (records ordered by first-declaration
  position in the source file);
- repeated `[CONTROLS]` headers collapse to one record with the
  combined row count;
- `[STATUS]` never appears in `ignored_sections` — both alone and
  alongside `[CONTROLS]` / `[RULES]`;
- hydraulically-active sections (`JUNCTIONS`, `RESERVOIRS`,
  `TANKS`, `PIPES`, `PUMPS`, `VALVES`, `OPTIONS`, `CURVES`) never
  appear in `ignored_sections`;
- every emitted record's `section` is a member of
  `IGNORED_SECTIONS`;
- `Network` byte-for-byte invariance against the Sprint 21 baseline
  with `[CONTROLS]` / `[RULES]` / `[PATTERNS]` / `[ENERGY]` added;
- `return_diagnostics=True` returns the same `Network` as the default
  `load_network_from_inp(path)` call;
- backward compatibility: default `load_network_from_inp(path)`
  still returns only a `Network` when ignored sections are present;
- `[CONTROLS]` + `status_rows` co-exist (the two diagnostic channels
  populate independently);
- `[CONTROLS]` remains a dropped no-op (Newton-solve parity to
  `1e-9` / `1e-12`);
- Sprint 22 rejection paths still raise when ignored sections are
  also present in the file (`CLOSED`, `CV`, numeric, unknown id,
  arbitrary token);
- `parser="fallback"` selector reaches the diagnostics path;
- optional WNTR back-end smoke check
  (`pytest.importorskip("wntr")`) — the WNTR back-end returns an
  `EpanetImportDiagnostics` without raising; if any records are
  emitted by the WNTR back-end they are validated to have the right
  shape and section name, but parity with the fallback parser is
  **not** required.

**Unchanged but re-validated:** all 977 Sprint 11–23 tests continue
to pass; total 1016 passed, 1 skipped (same WNTR-ImportError-path
skip as Sprint 23; `wntr==1.4.0` is installed in this env so the rest
of the WNTR optional suite passes).

## Validation commands and results

```bash
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
1008 passed, 1 skipped, 3 warnings in 102.02s (0:01:42)
SKIPPED [1] tests/dphm/test_wntr_optional_import.py:371: WNTR is installed; ImportError path not exercised here

$ python -m pytest tests -q
1016 passed, 1 skipped, 3 warnings in 101.81s (0:01:41)
SKIPPED [1] tests/dphm/test_wntr_optional_import.py:371: WNTR is installed; ImportError path not exercised here

$ python -m compileall -q src tests
rc=0  # exit clean

$ git status --short
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/__init__.py
 M src/aquaoptima/dphm/inp_io.py
?? tests/dphm/test_inp_ignored_section_diagnostics.py
?? SPRINT24_REPORT.md   # this file
```

All worktree changes are deliberate Sprint 24 changes. No
secret-looking strings introduced; no unexpected files; no
modifications to existing fixtures or to `pyproject.toml`.

## Compatibility notes

- `load_network_from_inp(path)` is **fully backward-compatible**.
  Default return shape unchanged; the Sprint 23
  `return_diagnostics=True` switch returns the extended container
  with the new optional `ignored_sections` field.
- `EpanetImportDiagnostics` shape is **backwards-compatible**.
  `ignored_sections` defaults to `()`, so every Sprint 23 caller that
  only reads `status_rows` keeps working.
- `Network` shape is **unchanged** — diagnostics do not attach state
  to `Network`.
- `IGNORED_SECTIONS` is **unchanged** — the same nineteen entries
  from Sprint 21 (`STATUS` removed in Sprint 22).
- `EpanetStatusDiagnostic` and the Sprint 23 `status_rows` surface
  are unchanged.
- The fallback parser is authoritative for ignored-section
  diagnostics; the WNTR back-end returns an empty
  `ignored_sections` tuple (documented limitation). This mirrors
  Sprint 23's `[STATUS]` split.

## Known limitations

- Diagnostics surface **presence only**. The parser does not
  validate the bodies of ignored sections (Sprint 21 contract); the
  `row_count` field is informational and counts every non-blank,
  comment-stripped row including malformed-looking ones.
- The WNTR back-end does not emit ignored-section diagnostics.
  Callers that need fallback-vs-WNTR parity must use
  `parser="fallback"`.
- `[CONTROLS]` / `[RULES]` / `[PATTERNS]` / `[ENERGY]` remain
  **unimplemented**. Sprint 24 only adds visibility — no controls,
  rules, time-varying demand, or energy-cost modelling has been
  activated.
- No new fixture files. The Sprint 24 tests construct fixtures
  inline against the canonical baseline so the shipped
  `docs/examples/` set stays Sprint 11–18.
- Diagnostic ordering is deterministic given a fixed source file but
  follows file order, not a canonical sort. Two files that declare
  the same ignored sections in different orders produce diagnostics
  in different orders; this is documented and tested.

## Sprint 24 hard approval gates — checklist

- [x] targeted pytest exits 0 (`1008 passed, 1 skipped`)
- [x] full pytest exits 0 (`1016 passed, 1 skipped`)
- [x] compileall exits 0 (`rc=0`)
- [x] `SPRINT24_REPORT.md` exists (this file)
- [x] ignored-section diagnostics API exists and is tested
  (`EpanetIgnoredSectionDiagnostic`,
  `EpanetImportDiagnostics.ignored_sections`)
- [x] diagnostics surface only current `IGNORED_SECTIONS` that are
  present in fallback `.inp` files
  (`test_emitted_diagnostics_are_subset_of_ignored_sections`)
- [x] `STATUS` is not listed as ignored-section diagnostic
  (`test_status_section_never_in_ignored_diagnostics`,
  `test_status_section_excluded_even_when_other_ignored_sections_present`)
- [x] accepted `[STATUS] OPEN` diagnostics from Sprint 23 still work
  (`tests/dphm/test_inp_status_diagnostics.py` still green, 39
  passed)
- [x] diagnostics are proven read-only and hydraulically inert /
  no-op (byte-for-byte network equality vs. baseline; Newton-solve
  parity)
- [x] `load_network_from_inp(path)` remains backward-compatible by
  default
- [x] Sprint 22 / 23 rejection behaviour remains intact for
  status-changing / invalid `[STATUS]` rows
  (`test_rejected_status_rows_still_raise` parametrised over
  CLOSED / CV / numeric / unknown id / arbitrary token)
- [x] `[CONTROLS]` / `[RULES]` remain ignored, not implemented
  (`test_controls_remain_ignored_not_enforced` proves Newton-solve
  parity)
- [x] existing SI / GPM / pressure / demand / SG / viscosity /
  ignored-section / STATUS fixture behaviour still passes
  (Sprint 11–23 suite green)
- [x] HEAD pump tests still pass
- [x] POWER pump tests still pass
- [x] PRV / TCV valve tests still pass
- [x] WNTR optional tests skip / pass cleanly
- [x] no obvious secret files / strings introduced
- [x] git status contains only intended Sprint 24 changes

With `wntr==1.4.0` installed, the additional WNTR gates apply:

- [x] WNTR HEAD / POWER / PRV / TCV / demand-multiplier parity from
  Sprints 13–23 still pass
- [x] WNTR-side ignored-section diagnostic asymmetry is documented
  (`docs/epanet-inp-import.md` — fallback authoritative; WNTR
  returns empty `ignored_sections`)

## Verdict

`VERDICT: APPROVED`

## Sprint 25 recommendation

Two equally-low-risk extensions stay within the steady-state
hydraulic boundary and continue Sprint 23 / 24's read-only-diagnostics
discipline:

**Option A (recommended) — surface `[CONTROLS]` / `[RULES]` row-level
diagnostics.** Today the Sprint 24 surface tells analysts a
`[CONTROLS]` block was present and how many rows it had. The natural
next step is to enrich the per-section record (or add a sibling field)
with one read-only record per parsed control / rule line, so analysts
can grep diagnostics for the *specific* control rules the dPHM
importer is dropping. This:

- builds directly on Sprint 24's typed-record shape;
- stays inside the safety boundary (no controls / rules are activated
  — still purely diagnostic);
- gives analysts concrete signal which EPANET rules a fixture relies
  on but dPHM does not enforce;
- requires no change to `Network` shape, the existing diagnostic
  records, or the fallback / WNTR parser invariants.

**Option B — surface valve / pump translation diagnostics on
`EpanetImportDiagnostics`.** `fit_power_pump_surrogate`,
`fit_tcv_resistance_surrogate`, and `translate_valve_to_surrogate`
already emit per-edge diagnostic dicts that include the surrogate's
`approximation`, anchor flow, and a free-text `limitations` string.
These currently never reach the public diagnostics surface — a
caller has to call the helpers directly. A Sprint 25 surface would
attach one read-only record per surrogate edge to
`EpanetImportDiagnostics`, so analysts can audit conservative
surrogate choices without re-parsing the file.

Either Sprint 25 option preserves Sprint 24's visibility-only
contract.

Strictly out of scope for Sprint 25 (deferred): closed-link
modelling, `[CONTROLS]` / `[RULES]` activation, Darcy-Weisbach,
`[PATTERNS]` time-varying demand, `[ENERGY]` parsing /
energy-cost modelling, real PLC/PAC/SCADA, write/control path, dPL
parameter learning, ONNX deployment, real EPANET binary.
