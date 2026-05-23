# Sprint 28 Report — EPANET `[EMITTERS]` / `[DEMANDS]` per-row diagnostics

Branch: `sprint28` (worktree at
`/home/hunter_lin/projects/aquaoptima-dphm-pinn-sprint28`).

Based on Sprint 27 head `9d78a63 feat: classify epanet control diagnostics`.

## Sprint goal

Add **read-only per-row `[EMITTERS]` / `[DEMANDS]` diagnostics** on top
of the existing EPANET import diagnostics surface (Sprints 23–27),
continuing the analyst-visibility ladder for ignored EPANET sections
without changing hydraulics.

## Files changed

```
 M docs/epanet-inp-import.md       | +221 lines
 M src/aquaoptima/dphm/__init__.py |   +2 lines
 M src/aquaoptima/dphm/inp_io.py   | ~225 lines (additions only; no semantic changes to prior code)
?? tests/dphm/test_inp_emitter_demand_row_diagnostics.py  (NEW, 46 tests)
```

No edits to any active hydraulic field, helper, parser branch, or
WNTR adapter logic beyond:

* a new `EpanetEmitterDemandDiagnostic` frozen dataclass;
* a new `_collect_emitter_demand_row_diagnostics` helper;
* an additional `emitter_demand_rows` tuple field on the existing
  `EpanetImportDiagnostics` container (default `()`);
* one new call site in `_fallback_parse` that collects the diagnostics
  and attaches them to the returned container;
* one extended comment on the WNTR adapter's empty-container return
  (no behaviour change — still returns an empty
  `EpanetImportDiagnostics` as documented);
* package `__init__.py` exporting the new dataclass.

## API design

```python
@dataclass(frozen=True)
class EpanetEmitterDemandDiagnostic:
    section: str            # always "EMITTERS" or "DEMANDS"
    row_index: int          # 0-based within the section bucket
    tokens: tuple[str, ...] # exact parser tokens, comments stripped
    text: str               # single-space-joined token text
    message: str            # human-readable no-op explanation


@dataclass(frozen=True)
class EpanetImportDiagnostics:
    status_rows: tuple[EpanetStatusDiagnostic, ...] = ()                  # Sprint 23
    ignored_sections: tuple[EpanetIgnoredSectionDiagnostic, ...] = ()     # Sprint 24
    control_rule_rows: tuple[EpanetControlRuleDiagnostic, ...] = ()       # Sprint 25 + Sprint 27 `kind`
    pattern_energy_rows: tuple[EpanetPatternEnergyDiagnostic, ...] = ()   # Sprint 26
    emitter_demand_rows: tuple[EpanetEmitterDemandDiagnostic, ...] = ()   # Sprint 28
```

Public entry points (unchanged signatures):

* `load_inp_diagnostics(path, parser="fallback")` returns a fully
  populated `EpanetImportDiagnostics`.
* `load_network_from_inp(path, parser="fallback", return_diagnostics=True)`
  returns `(Network, EpanetImportDiagnostics)`.
* `load_network_from_inp(path)` (no `return_diagnostics`) still returns
  the bare `Network` (backwards compatible — explicitly tested).

Naming and shape mirror the Sprint 25 / Sprint 26 per-row channels for
consistency. The records are tuple-backed and frozen; reassignment
raises `dataclasses.FrozenInstanceError`.

## Fallback parser behaviour

`_collect_emitter_demand_row_diagnostics(sections)` walks the
per-section tokenised rows that `_split_sections` already produces and
emits one `EpanetEmitterDemandDiagnostic` for every row whose section
is `"EMITTERS"` or `"DEMANDS"`. Rules:

* Section ordering follows source-file order
  (`_split_sections` is built on a regular `dict`; Python 3.7+
  preserves insertion order).
* `row_index` resets per section, 0-based within the section bucket.
* `tokens` is a `tuple` (parser-emitted lists are coerced); token
  order matches the source row.
* Inline `; ...` comments are stripped before tokenisation by
  `_strip_comment`; blank rows are dropped by `_split_sections`
  before they can reach the collector.
* Bare `[EMITTERS]` / `[DEMANDS]` headers with no body emit no row
  diagnostics (no rows to surface), but Sprint 24 still surfaces the
  section name through `ignored_sections`.
* The collector is read-only — it never mutates `sections` and never
  affects parsing outcomes. The existing hydraulic pipeline is
  untouched.

## Read-only / no-op evidence

Hydraulic invariance is proven by two pytest tests:

* `test_emitter_demand_diagnostics_do_not_change_network` — loads a
  baseline fixture and a perturbed fixture (with two `[EMITTERS]`
  rows + two `[DEMANDS]` rows) and asserts byte-for-byte equality of
  every `Network` field: `edge_index`, `pipe_mask`, `pump_mask`,
  `demands`, `fixed_head_values`, `lengths`, `diameters`,
  `c_factors`, `pump_speeds`, `pump_coeffs` (via
  `_assert_networks_identical`).
* `test_emitter_demand_diagnostics_do_not_change_solve` — runs
  `newton_solve(..., max_iterations=200, tol=1e-9,
  jacobian_mode="analytic")` on both networks and asserts heads match
  to 1e-9 and flows match to 1e-12.

Additionally:

* Sprint 22 `[STATUS]` rejection paths still raise: a parametrised
  test mixes each rejected status token (`CLOSED`, `CV`, numeric
  pump-status, unknown link id, arbitrary token) with `[EMITTERS]` +
  `[DEMANDS]` rows and confirms `load_inp_diagnostics` and
  `load_network_from_inp(..., return_diagnostics=True)` both still
  raise `ValueError`. No partial diagnostics leak out of the failure.
* Sprint 25 `control_rule_rows` and Sprint 26 `pattern_energy_rows`
  channels never include `[EMITTERS]` / `[DEMANDS]` rows
  (explicitly tested).
* Sprint 24 `ignored_sections` continues to surface `EMITTERS` /
  `DEMANDS` at the section level when those sections are present.
* Default `load_network_from_inp(path)` (no `return_diagnostics`)
  still returns only a `Network` (explicitly tested).

## WNTR back-end behaviour / asymmetry

The WNTR adapter (`_wntr_parse`) continues to return an empty
`EpanetImportDiagnostics()` — i.e. `status_rows = ()`,
`ignored_sections = ()`, `control_rule_rows = ()`,
`pattern_energy_rows = ()`, `emitter_demand_rows = ()`. WNTR has its
own `[EMITTERS]` / `[DEMANDS]` handling, and the dPHM WNTR adapter
does not re-emit emitter/demand row diagnostics — the fallback parser
is documented as authoritative for every diagnostics channel.

The asymmetry is documented in `docs/epanet-inp-import.md` and tested
via `test_wntr_back_end_returns_container_without_raising`, which is
gated by `pytest.importorskip("wntr")` (currently runs because WNTR
1.4.0 is installed in the environment; would skip cleanly without).

The WNTR HEAD / POWER / PRV / TCV / demand-multiplier hydraulic parity
tests from Sprints 13–27 all still pass (full suite is green).

## Tests added/updated

`tests/dphm/test_inp_emitter_demand_row_diagnostics.py` — 46 new
tests, all passing:

* **Public surface (6 tests).** `EpanetEmitterDemandDiagnostic` is a
  frozen dataclass; reassigning any field raises
  `FrozenInstanceError`; defaults; `tokens` is a `tuple`;
  `EpanetImportDiagnostics.emitter_demand_rows` defaults to `()` and
  is itself tuple-backed and frozen.
* **Empty / absent cases (3 tests).** Fixtures without
  `[EMITTERS]` / `[DEMANDS]`, bare `[EMITTERS]` header, bare
  `[DEMANDS]` header — all produce empty `emitter_demand_rows`; the
  bare-header fixtures still surface the section via
  `ignored_sections`.
* **Single rows (2 tests).** One `[EMITTERS]` row and one `[DEMANDS]`
  row each produce exactly one record with the expected section,
  `row_index = 0`, exact tokens, and reconstructed text.
* **Multi-row order preservation (2 tests).** Three `[EMITTERS]`
  rows / three `[DEMANDS]` rows preserve `row_index = [0, 1, 2]` and
  source order.
* **Mixed source order (2 tests).** `[EMITTERS]` first then
  `[DEMANDS]`, and the reverse; section ordering follows source-file
  order; `row_index` resets per section.
* **Comments + blanks (2 tests).** Inline `; ...` stripped before
  tokenisation; blank rows dropped before `row_index` assignment.
* **Exclusion of other sections (11 parametrised + 3 explicit).**
  Other ignored sections (`CONTROLS`, `RULES`, `PATTERNS`, `ENERGY`,
  `QUALITY`, `SOURCES`, `REACTIONS`, `MIXING`, `TIMES`, `REPORT`),
  `STATUS`, and active hydraulic sections (`JUNCTIONS`,
  `RESERVOIRS`, `TANKS`, `PIPES`, `PUMPS`, `VALVES`, `OPTIONS`,
  `CURVES`) never appear in `emitter_demand_rows`. A combined test
  asserts every emitted record's section is one of `EMITTERS` /
  `DEMANDS`.
* **Cross-channel disjointness (2 tests).** The Sprint 25
  `control_rule_rows` channel and the Sprint 26
  `pattern_energy_rows` channel never include `[EMITTERS]` /
  `[DEMANDS]` rows; conversely they still cover their own sections.
* **Sprint 24 coverage (1 test).** `ignored_sections` still lists
  `EMITTERS` and `DEMANDS` when those sections are present.
* **Hydraulic inertness (2 tests).** `Network` byte-for-byte
  invariance and Newton-solve heads/flows invariance.
* **Return-diagnostics API (3 tests).**
  `load_network_from_inp(..., return_diagnostics=True)` returns the
  same `Network` as the default call, and the same diagnostics as
  `load_inp_diagnostics`. Default `load_network_from_inp(path)`
  remains backwards-compatible.
* **Combined Sprint 23+24+25+26+28 coexistence (2 tests).** A
  five-channel fixture and a status-only fixture confirm `[STATUS]`
  is never surfaced through `ignored_sections` or
  `emitter_demand_rows`.
* **Sprint 22 rejection preservation (5 parametrised tests).** Every
  rejected `[STATUS]` token (`CLOSED`, `CV`, numeric pump-status,
  unknown link id, arbitrary token) still raises when `[EMITTERS]` +
  `[DEMANDS]` are also present; no partial diagnostics leak out.
* **WNTR asymmetry (1 test).** With WNTR installed,
  `load_inp_diagnostics(..., parser="wntr")` returns an
  `EpanetImportDiagnostics` with empty `emitter_demand_rows`.
  Skipped via `pytest.importorskip` when WNTR is not installed.

## Validation commands & results

```bash
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
1173 passed, 1 skipped, 3 warnings in 87.31s (0:01:27)

$ python -m pytest tests -q
1181 passed, 1 skipped, 3 warnings in 85.01s (0:01:25)

$ python -m compileall src tests
(clean — no SyntaxError, no compile failures)

$ git status --short
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/__init__.py
 M src/aquaoptima/dphm/inp_io.py
?? tests/dphm/test_inp_emitter_demand_row_diagnostics.py
```

Sprint 27 baseline: 1127 passed, 1 skipped (targeted) / 1135 passed,
1 skipped (full). Sprint 28 delta: +46 new tests (1173 / 1181). No
prior-sprint test regressed.

Secret-scan grep over the diff: zero matches for private-key headers,
`aws_access_key`, or quoted `api_key` assignments.

## Compatibility notes

* `load_network_from_inp(path)` (default — no
  `return_diagnostics`) is **byte-for-byte backwards compatible**.
  Every Sprint 11–27 caller continues to receive a bare `Network`.
* `EpanetImportDiagnostics()` (no kwargs) keeps the Sprint 23 / 24 /
  25 / 26 surface intact: the new `emitter_demand_rows` field
  defaults to `()`, so any keyword-only consumer that ignores the
  new field continues to work.
* The Sprint 22 `[STATUS]` rejection contract is fully preserved.
* The Sprint 21 ignored-section no-op contract is fully preserved:
  `EMITTERS` and `DEMANDS` remain members of `IGNORED_SECTIONS`, the
  fallback parser never reads their content for any hydraulic
  purpose, and the loaded `Network` is unchanged.
* The Sprint 25 `control_rule_rows` channel and Sprint 26
  `pattern_energy_rows` channel are unchanged.
* The Sprint 27 `EpanetControlKind` classification is unchanged.
* The Sprint 24 `ignored_sections` channel is unchanged.
* `__all__` exports gain `EpanetEmitterDemandDiagnostic` from both
  `aquaoptima.dphm.inp_io` and the top-level `aquaoptima.dphm`
  package.

## Known limitations

Sprint 28 deliberately does **not**:

* model pressure-dependent emitter outflow
  (`Q_emitter = C * P^gamma`) on any junction;
* model background leakage / pressure-dependent demand;
* parse multi-category demands, demand patterns, or per-category
  pattern multipliers — the `[OPTIONS] Demand Multiplier` (Sprint 18)
  remains the only steady-state demand scalar honoured;
* reject malformed `[EMITTERS]` / `[DEMANDS]` rows — a row with
  non-numeric tokens still surfaces as a diagnostic with the
  offending tokens; this is row-visibility, not row-validation;
* re-emit `emitter_demand_rows` from the WNTR back-end — the
  fallback parser is authoritative for every diagnostics channel.
  Documented asymmetry preserved.

These are deferred to future sprints if and when the dPHM core grows
the corresponding physics (pressure-dependent demand, multi-category
demands, time-varying patterns).

## Verdict

`VERDICT: APPROVED`

All Sprint 28 hard approval gates pass:

* targeted pytest exits 0 (1173 passed, 1 skipped);
* full pytest exits 0 (1181 passed, 1 skipped);
* compileall exits 0;
* `SPRINT28_REPORT.md` exists (this file);
* emitter/demand row diagnostics API exists, is exported, and is
  tested (46 new tests);
* row diagnostics surface only `[EMITTERS]` and `[DEMANDS]` rows
  (parametrised exclusion tests confirm every other ignored
  section, `[STATUS]`, and every active hydraulic section is
  excluded);
* Sprint 23 status diagnostics, Sprint 24 ignored-section
  diagnostics, Sprint 25 control/rule row diagnostics + Sprint 27
  classification, and Sprint 26 pattern/energy row diagnostics all
  still work (combined coexistence test);
* no active emitter / demand / control / rule / pattern / energy
  semantics are implemented;
* diagnostics are proven read-only and hydraulically inert
  (`Network` invariance + Newton-solve invariance);
* `load_network_from_inp(path)` remains backward compatible by
  default;
* Sprint 22 / 23 rejection behaviour remains intact for
  status-changing / invalid `[STATUS]` rows even when `[EMITTERS]`
  / `[DEMANDS]` rows are present;
* existing SI / GPM / pressure / demand / SG / viscosity /
  diagnostics fixture behaviour passes;
* HEAD pump tests pass; POWER pump tests pass; PRV / TCV valve
  tests pass;
* WNTR optional tests pass (WNTR 1.4.0 installed) with the
  documented empty-container asymmetry; would skip cleanly without
  WNTR;
* no obvious secret files / strings introduced (diff secret-scan
  zero);
* `git status` contains only intended Sprint 28 changes.

WNTR-installed additional gates:

* WNTR HEAD / POWER / PRV / TCV / demand-multiplier parity from
  Sprints 13–27 still pass.
* WNTR asymmetry around emitter/demand row diagnostics is documented
  in `docs/epanet-inp-import.md` and asserted by the WNTR
  smoke-check test.

## Sprint 29 recommendation

Extend the per-row visibility surface to the remaining
content-bearing members of `IGNORED_SECTIONS` — specifically
`[QUALITY]`, `[SOURCES]`, `[REACTIONS]`, and `[MIXING]` — through a
single `EpanetWaterQualityDiagnostic` dataclass and a
`water_quality_rows` field on `EpanetImportDiagnostics`. The shape
should mirror Sprints 25 / 26 / 28 exactly: frozen dataclass,
section / row_index / tokens / text / message, tuple-backed,
section-name normalised to upper-case, source order preserved, no
hydraulic side effects, fallback parser authoritative, WNTR adapter
returns empty.

This closes the per-row visibility ladder for every ignored section
that carries semantic row content in EPANET-exported fixtures, and
sets up a future Sprint 30 to add a single
`EpanetImportDiagnostics.summary()` view across all channels (or a
`row_count_by_section()` accessor) for downstream UI consumers.

Out of scope for Sprint 29 (and explicitly **not** recommended yet):
real water-quality modelling, real pressure-dependent emitter
physics, real demand-pattern support, real control/rule
interpretation, WNTR-side diagnostic parity, or any write/control
path.
