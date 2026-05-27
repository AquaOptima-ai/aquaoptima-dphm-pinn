# Sprint 29 Report — EPANET water-quality per-row diagnostics

Branch: `sprint29` (worktree at
`/home/hunter_lin/projects/aquaoptima-dphm-pinn-sprint29`).

Based on Sprint 28 head `b8ace61 feat: add epanet emitter demand
diagnostics`.

## Sprint goal

Add **read-only per-row diagnostics for the four water-quality-family
ignored sections** (`[QUALITY]`, `[SOURCES]`, `[REACTIONS]`,
`[MIXING]`) on top of the existing EPANET import diagnostics surface
(Sprints 23–28), closing the analyst-visibility ladder for every
content-bearing member of `IGNORED_SECTIONS` without changing
hydraulics.

## Files changed

```
 M docs/epanet-inp-import.md       | +260 lines (new Sprint 29 section + intro updates)
 M src/aquaoptima/dphm/__init__.py |   +2 lines (new symbol export)
 M src/aquaoptima/dphm/inp_io.py   | ~140 lines (additions only; no semantic changes to prior code)
?? tests/dphm/test_inp_water_quality_row_diagnostics.py  (NEW, 50 tests)
```

No edits to any active hydraulic field, helper, parser branch, or
WNTR adapter logic beyond:

* a new `EpanetWaterQualityDiagnostic` frozen dataclass;
* a new `_collect_water_quality_row_diagnostics` helper;
* an additional `water_quality_rows` tuple field on the existing
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
class EpanetWaterQualityDiagnostic:
    section: str            # one of "QUALITY", "SOURCES", "REACTIONS", "MIXING"
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
    water_quality_rows: tuple[EpanetWaterQualityDiagnostic, ...] = ()     # Sprint 29
```

Public entry points (unchanged signatures):

* `load_inp_diagnostics(path, parser="fallback")` returns a fully
  populated `EpanetImportDiagnostics`.
* `load_network_from_inp(path, parser="fallback", return_diagnostics=True)`
  returns `(Network, EpanetImportDiagnostics)`.
* `load_network_from_inp(path)` (no `return_diagnostics`) still returns
  the bare `Network` (backwards compatible — explicitly tested).

Naming and shape mirror the Sprint 25 / Sprint 26 / Sprint 28 per-row
channels for consistency. The records are tuple-backed and frozen;
reassignment raises `dataclasses.FrozenInstanceError`.

## Fallback parser behaviour

`_collect_water_quality_row_diagnostics(sections)` walks the
per-section tokenised rows that `_split_sections` already produces and
emits one `EpanetWaterQualityDiagnostic` for every row whose section
is `"QUALITY"`, `"SOURCES"`, `"REACTIONS"`, or `"MIXING"`. Rules:

* Section ordering follows source-file order (`_split_sections` is
  built on a regular `dict`; Python 3.7+ preserves insertion order).
* `row_index` resets per section, 0-based within the section bucket.
* `tokens` is a `tuple` (parser-emitted lists are coerced); token
  order matches the source row.
* Inline `; ...` comments are stripped before tokenisation by
  `_strip_comment`; blank rows are dropped by `_split_sections`
  before they can reach the collector.
* Bare `[QUALITY]` / `[SOURCES]` / `[REACTIONS]` / `[MIXING]` headers
  with no body emit no row diagnostics (no rows to surface), but
  Sprint 24 still surfaces the section name through
  `ignored_sections`.
* The collector is read-only — it never mutates `sections` and never
  affects parsing outcomes. The existing hydraulic pipeline is
  untouched.

## Read-only / no-op evidence

Hydraulic invariance is proven by two pytest tests:

* `test_water_quality_diagnostics_do_not_change_network` — loads a
  baseline fixture and a perturbed fixture (with two rows in each of
  `[QUALITY]`, `[SOURCES]`, `[REACTIONS]`, `[MIXING]`) and asserts
  byte-for-byte equality of every `Network` field: `edge_index`,
  `pipe_mask`, `pump_mask`, `demands`, `fixed_head_values`, `lengths`,
  `diameters`, `c_factors`, `pump_speeds`, `pump_coeffs` (via
  `_assert_networks_identical`).
* `test_water_quality_diagnostics_do_not_change_solve` — runs
  `newton_solve(..., max_iterations=200, tol=1e-9,
  jacobian_mode="analytic")` on both networks and asserts heads match
  to 1e-9 and flows match to 1e-12.

Additionally:

* Sprint 23 accepted `[STATUS] OPEN` diagnostics are preserved:
  `test_status_section_never_in_water_quality_rows` loads
  `[STATUS]\n P1 OPEN\n` and asserts `diag.status_rows` still contains
  the accepted row (`link_id == "P1"`) while `STATUS` remains absent from
  `water_quality_rows`; `test_all_diagnostics_coexist` loads a combined
  fixture containing `[STATUS]\n P1 OPEN\n P2 OPEN\n` plus every
  diagnostics family and asserts `diag.status_rows == ["P1", "P2"]` with
  every status record normalised to `OPEN`. Thus Sprint 29 preserves the
  Sprint 23 accepted-OPEN status channel rather than shadowing or
  reclassifying it as water-quality metadata.
* Sprint 22 `[STATUS]` rejection paths still raise: a parametrised
  test mixes each rejected status token (`CLOSED`, `CV`, numeric
  pump-status, unknown link id, arbitrary token) with all four
  water-quality sections present and confirms `load_inp_diagnostics`
  and `load_network_from_inp(..., return_diagnostics=True)` both
  still raise `ValueError`. No partial diagnostics leak out of the
  failure.
* Sprint 25 `control_rule_rows`, Sprint 26 `pattern_energy_rows`, and
  Sprint 28 `emitter_demand_rows` channels never include water-quality
  rows (explicitly tested).
* Sprint 24 `ignored_sections` continues to surface `QUALITY` /
  `SOURCES` / `REACTIONS` / `MIXING` at the section level when those
  sections are present.
* Default `load_network_from_inp(path)` (no `return_diagnostics`) still
  returns only a `Network` (explicitly tested).

## WNTR back-end behaviour / asymmetry

The WNTR adapter (`_wntr_parse`) continues to return an empty
`EpanetImportDiagnostics()` — i.e. `status_rows = ()`,
`ignored_sections = ()`, `control_rule_rows = ()`,
`pattern_energy_rows = ()`, `emitter_demand_rows = ()`,
`water_quality_rows = ()`. WNTR has its own `[QUALITY]` / `[SOURCES]`
/ `[REACTIONS]` / `[MIXING]` parsers, and the dPHM WNTR adapter does
not re-emit water-quality row diagnostics — the fallback parser is
documented as authoritative for every diagnostics channel.

The asymmetry is documented in `docs/epanet-inp-import.md` and tested
via `test_wntr_back_end_returns_container_without_raising`, which is
gated by `pytest.importorskip("wntr")` (currently runs because WNTR
1.4.0 is installed in the environment; would skip cleanly without).

WNTR-side note: WNTR's `[MIXING]` parser raises `KeyError` if the
referenced tank id is not declared in `[TANKS]`, and its `[SOURCES]`
parser is similarly strict about node ids. Those raises are WNTR-side
behaviour, not Sprint 29 behaviour — the fallback parser tolerates
such rows as diagnostics. The WNTR smoke fixture therefore uses only
`[QUALITY]` + `[REACTIONS]` (which WNTR accepts on a tank-less loop
fixture); the other two sections are exercised against the fallback
parser elsewhere in the test file. The asymmetry is documented in
both the docs and the test docstring.

The WNTR HEAD / POWER / PRV / TCV / demand-multiplier hydraulic parity
tests from Sprints 13–28 all still pass (82 passed, 1 skipped on the
focused WNTR test set; full suite is green).

## Tests added/updated

`tests/dphm/test_inp_water_quality_row_diagnostics.py` — 50 new
tests, all passing:

* **Public surface (6 tests).** `EpanetWaterQualityDiagnostic` is a
  frozen dataclass; reassigning any field raises
  `FrozenInstanceError`; defaults; `tokens` is a `tuple`;
  `EpanetImportDiagnostics.water_quality_rows` defaults to `()` and
  is itself tuple-backed and frozen.
* **Empty / absent cases (5 tests).** Fixture without any water-
  quality section, plus four parametrised bare-header cases (one per
  section) — all produce empty `water_quality_rows`; the bare-header
  fixtures still surface the section via `ignored_sections`.
* **Single rows (4 tests).** One `[QUALITY]`, one `[SOURCES]`, one
  `[REACTIONS]`, and one `[MIXING]` row each produce exactly one
  record with the expected section, `row_index = 0`, exact tokens,
  and reconstructed text.
* **Multi-row order preservation (2 tests).** Three `[QUALITY]` rows
  / three `[REACTIONS]` rows preserve `row_index = [0, 1, 2]` and
  source order.
* **Mixed source order (3 tests).** All four sections in canonical
  order, all four sections in reverse order, plus a multi-row-per-
  section all-four-mixed test confirming `row_index` resets per
  section.
* **Comments + blanks (2 tests).** Inline `; ...` stripped before
  tokenisation; blank rows dropped before `row_index` assignment.
* **Exclusion of other sections (8 parametrised + 3 explicit).**
  Other ignored sections (`CONTROLS`, `RULES`, `PATTERNS`, `ENERGY`,
  `EMITTERS`, `DEMANDS`, `TIMES`, `REPORT`), `STATUS`, and active
  hydraulic sections (`JUNCTIONS`, `RESERVOIRS`, `TANKS`, `PIPES`,
  `PUMPS`, `VALVES`, `OPTIONS`, `CURVES`) never appear in
  `water_quality_rows`. A combined test asserts every emitted
  record's section is one of `QUALITY` / `SOURCES` / `REACTIONS`
  / `MIXING`.
* **Cross-channel disjointness (3 tests).** The Sprint 25
  `control_rule_rows` channel, the Sprint 26 `pattern_energy_rows`
  channel, and the Sprint 28 `emitter_demand_rows` channel never
  include water-quality rows; conversely they still cover their own
  sections.
* **Sprint 24 coverage (1 test).** `ignored_sections` still lists
  `QUALITY`, `SOURCES`, `REACTIONS`, and `MIXING` when those sections
  are present.
* **Hydraulic inertness (2 tests).** `Network` byte-for-byte
  invariance and Newton-solve heads/flows invariance.
* **Return-diagnostics API (3 tests).**
  `load_network_from_inp(..., return_diagnostics=True)` returns the
  same `Network` as the default call, and the same diagnostics as
  `load_inp_diagnostics`. Default `load_network_from_inp(path)`
  remains backwards-compatible.
* **Combined Sprint 23 + 24 + 25 + 26 + 28 + 29 coexistence (2 tests).**
  A six-channel fixture (all twelve content-bearing ignored
  sections plus `[STATUS]`) and a status-only fixture confirm
  `[STATUS]` is never surfaced through `ignored_sections` or
  `water_quality_rows`.
* **Sprint 22 rejection preservation (5 parametrised tests).** Every
  rejected `[STATUS]` token (`CLOSED`, `CV`, numeric pump-status,
  unknown link id, arbitrary token) still raises when all four
  water-quality sections are also present; no partial diagnostics
  leak out.
* **WNTR asymmetry (1 test).** With WNTR installed,
  `load_inp_diagnostics(..., parser="wntr")` returns an
  `EpanetImportDiagnostics` with empty `water_quality_rows`. Skipped
  via `pytest.importorskip` when WNTR is not installed.

## Validation commands & results

```bash
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
1223 passed, 1 skipped, 3 warnings in 88.40s (0:01:28)

$ python -m pytest tests -q
1231 passed, 1 skipped, 3 warnings in 83.25s (0:01:23)

$ python -m compileall src tests
(clean — no SyntaxError, no compile failures)

$ git status --short
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/__init__.py
 M src/aquaoptima/dphm/inp_io.py
?? tests/dphm/test_inp_water_quality_row_diagnostics.py
```

Sprint 28 baseline: 1173 passed, 1 skipped (targeted) / 1181 passed,
1 skipped (full). Sprint 29 delta: +50 new tests (1223 / 1231). No
prior-sprint test regressed.

Secret-scan grep over the diff (private-key headers, `aws_access_key`,
quoted `api_key` assignments): zero matches.

## Compatibility notes

* `load_network_from_inp(path)` (default — no `return_diagnostics`) is
  **byte-for-byte backwards compatible**. Every Sprint 11–28 caller
  continues to receive a bare `Network`.
* `EpanetImportDiagnostics()` (no kwargs) keeps the Sprint 23 / 24 /
  25 / 26 / 28 surface intact: the new `water_quality_rows` field
  defaults to `()`, so any keyword-only consumer that ignores the new
  field continues to work.
* The Sprint 22 `[STATUS]` rejection contract is fully preserved.
* The Sprint 21 ignored-section no-op contract is fully preserved:
  `QUALITY`, `SOURCES`, `REACTIONS`, and `MIXING` remain members of
  `IGNORED_SECTIONS`, the fallback parser never reads their content
  for any hydraulic purpose, and the loaded `Network` is unchanged.
* The Sprint 25 `control_rule_rows` channel, Sprint 26
  `pattern_energy_rows` channel, and Sprint 28 `emitter_demand_rows`
  channel are unchanged.
* The Sprint 27 `EpanetControlKind` classification is unchanged.
* The Sprint 24 `ignored_sections` channel is unchanged.
* `__all__` exports gain `EpanetWaterQualityDiagnostic` from both
  `aquaoptima.dphm.inp_io` and the top-level `aquaoptima.dphm`
  package.

## Known limitations

Sprint 29 deliberately does **not**:

* run any water-quality simulation, age modelling, or
  contaminant-transport integration;
* interpret `[QUALITY]` rows as initial-concentration boundary
  conditions on `Network` nodes;
* interpret `[SOURCES]` rows as source-injection terms (`CONCEN`,
  `MASS`, `FLOWPACED`, `SETPOINT`) on `Network` nodes;
* interpret `[REACTIONS]` rows as bulk / wall reaction coefficients
  (`Order Bulk`, `Order Wall`, `Global Bulk`, `Global Wall`, per-pipe
  / per-tank coefficients, `Limiting Potential`, `Roughness
  Correlation`);
* interpret `[MIXING]` rows as tank-mixing models (`MIXED`, `2COMP`,
  `FIFO`, `LIFO`) — the dPHM steady-state core does not model tank
  dynamics in the first place;
* reject malformed water-quality rows — a row with non-numeric or
  unknown tokens still surfaces as a diagnostic with the offending
  tokens; this is row-visibility, not row-validation;
* re-emit `water_quality_rows` from the WNTR back-end — the fallback
  parser is authoritative for every diagnostics channel. Documented
  asymmetry preserved.

These are deferred to future sprints if and when the dPHM core grows
the corresponding physics (water-quality simulation, transport,
reactions, tank mixing).

## Verdict

`VERDICT: APPROVED`

All Sprint 29 hard approval gates pass:

* targeted pytest exits 0 (1223 passed, 1 skipped);
* full pytest exits 0 (1231 passed, 1 skipped);
* compileall exits 0;
* `SPRINT29_REPORT.md` exists (this file);
* water-quality row diagnostics API exists, is exported, and is
  tested (50 new tests);
* row diagnostics surface only `[QUALITY]`, `[SOURCES]`,
  `[REACTIONS]`, and `[MIXING]` rows (parametrised exclusion tests
  confirm every other ignored section, `[STATUS]`, and every active
  hydraulic section is excluded);
* Sprint 23 status diagnostics, Sprint 24 ignored-section
  diagnostics, Sprint 25 control/rule row diagnostics + Sprint 27
  classification, Sprint 26 pattern/energy row diagnostics, and
  Sprint 28 emitter/demand row diagnostics all still work (combined
  coexistence test);
* no active water-quality / emitter / demand / control / rule /
  pattern / energy semantics are implemented;
* diagnostics are proven read-only and hydraulically inert
  (`Network` invariance + Newton-solve invariance);
* `load_network_from_inp(path)` remains backward compatible by
  default;
* Sprint 22 / 23 rejection behaviour remains intact for
  status-changing / invalid `[STATUS]` rows even when water-quality
  rows are present;
* existing SI / GPM / pressure / demand / SG / viscosity /
  diagnostics fixture behaviour passes;
* HEAD pump tests pass; POWER pump tests pass; PRV / TCV valve
  tests pass;
* WNTR optional tests pass (WNTR 1.4.0 installed) with the
  documented empty-container asymmetry; would skip cleanly without
  WNTR;
* no obvious secret files / strings introduced (diff secret-scan
  zero);
* `git status` contains only intended Sprint 29 changes.

WNTR-installed additional gates:

* WNTR HEAD / POWER / PRV / TCV / demand-multiplier parity from
  Sprints 13–28 still pass.
* WNTR asymmetry around water-quality row diagnostics is documented
  in `docs/epanet-inp-import.md` and asserted by the WNTR smoke-check
  test. The WNTR-side `[MIXING]` / `[SOURCES]` strict-id behaviour is
  also documented; the WNTR smoke fixture uses only `[QUALITY]` +
  `[REACTIONS]` because of that strict-id behaviour.

## Sprint 30 recommendation

With Sprint 29, every content-bearing member of `IGNORED_SECTIONS`
now has a dedicated per-row diagnostic channel:

| Section family                  | Channel                | Sprint |
|---------------------------------|------------------------|--------|
| `[STATUS]` (accepted rows)      | `status_rows`          | 23     |
| All ignored sections (presence) | `ignored_sections`     | 24     |
| `[CONTROLS]` / `[RULES]`        | `control_rule_rows`    | 25 / 27|
| `[PATTERNS]` / `[ENERGY]`       | `pattern_energy_rows`  | 26     |
| `[EMITTERS]` / `[DEMANDS]`      | `emitter_demand_rows`  | 28     |
| `[QUALITY]` / `[SOURCES]` / `[REACTIONS]` / `[MIXING]` | `water_quality_rows`   | 29     |

Sprint 30 should pivot from *channel expansion* to *channel
ergonomics*: a single read-only `EpanetImportDiagnostics.summary()`
view (or `row_count_by_section()` accessor) that aggregates row
counts across every channel for downstream UI consumers, without
adding any new semantic processing. The accessor must remain
diagnostics-only (no hydraulic side effects, no `Network` changes,
no rejection-path changes, no WNTR asymmetry change), should
preserve the Sprint 21 ignored-section no-op contract, and should
be tested both standalone (correct counts) and in combination with
the existing per-channel tests (no double-counting, no leakage
between channels).

Out of scope for Sprint 30 (and explicitly **not** recommended yet):
real water-quality modelling, real pressure-dependent emitter
physics, real demand-pattern support, real control / rule
interpretation, WNTR-side diagnostic parity, or any write / control
path.
