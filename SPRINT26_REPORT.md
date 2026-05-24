# Sprint 26 — Read-only `[PATTERNS]` / `[ENERGY]` row diagnostics

Sprint 26 extends the Sprint 24/25 EPANET `.inp` diagnostics surface
with per-row visibility for the two remaining EPANET-exported ignored
sections that most often carry tabular content: `[PATTERNS]` and
`[ENERGY]`. The dPHM steady-state safety boundary is unchanged —
neither time-varying demand support nor energy-cost modelling is
activated.

## Files changed

| File                                                                  | Change                                                                                            |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                                       | Added `EpanetPatternEnergyDiagnostic`, `_collect_pattern_energy_row_diagnostics`, `_PATTERN_ENERGY_SECTIONS`, `_PATTERN_ENERGY_ROW_NOOP_MESSAGE`. Extended `EpanetImportDiagnostics` with the `pattern_energy_rows` tuple field. Wired the new helper into `_fallback_parse` and populated the new field on the returned diagnostics container. Updated WNTR docstring and module preamble. Added the new symbol to `__all__`. |
| `src/aquaoptima/dphm/__init__.py`                                     | Re-exported `EpanetPatternEnergyDiagnostic`.                                                       |
| `tests/dphm/test_inp_pattern_energy_row_diagnostics.py`               | New (45 tests) — full Sprint 26 contract coverage: public surface, single/multi-row diagnostics for `[PATTERNS]` and `[ENERGY]`, deterministic mixed ordering, comment / blank-row tokeniser inheritance, exclusion of every other section (other ignored, `[STATUS]`, active hydraulic), Sprint 25 channel disjointness, hydraulic-inertness proofs (`Network` equality and Newton-solve heads/flows to 1e-9 / 1e-12), `load_inp_diagnostics` ↔ `load_network_from_inp(..., return_diagnostics=True)` parity, Sprint 22 `[STATUS]` rejection preserved, Sprint 23 + 24 + 25 + 26 coexistence, optional WNTR back-end smoke. |
| `docs/epanet-inp-import.md`                                           | Added the "Read-only [PATTERNS] / [ENERGY] row diagnostics (Sprint 26)" section. Updated the document title and the preamble paragraph to reference Sprint 26. |
| `SPRINT26_REPORT.md`                                                  | This report (new).                                                                                 |

## Pattern/energy row diagnostics API design

```python
@dataclass(frozen=True)
class EpanetPatternEnergyDiagnostic:
    section: str                   # "PATTERNS" or "ENERGY" (upper-case)
    row_index: int                 # 0-based, resets per section, preserves source order
    tokens: tuple[str, ...]        # tokenised parser row, single-space split
    text: str                      # " ".join(tokens) — comments and blanks excluded
    message: str = "Row present but ignored by the steady-state dPHM importer."


@dataclass(frozen=True)
class EpanetImportDiagnostics:
    status_rows: tuple[EpanetStatusDiagnostic, ...] = ()
    ignored_sections: tuple[EpanetIgnoredSectionDiagnostic, ...] = ()
    control_rule_rows: tuple[EpanetControlRuleDiagnostic, ...] = ()
    pattern_energy_rows: tuple[EpanetPatternEnergyDiagnostic, ...] = ()
```

Both dataclasses remain `frozen=True`; every container field is a
`tuple`, so the diagnostics surface is structurally read-only and
field reassignment raises `dataclasses.FrozenInstanceError`.

Public entry points (unchanged signatures, both surfaces gain the new
field):

- `load_inp_diagnostics(path, *, parser="auto", units="si",
  default_c_factor=130.0) -> EpanetImportDiagnostics`
- `load_network_from_inp(path, *, parser="auto", units="si",
  default_c_factor=130.0, return_diagnostics=False)` returns a bare
  `Network` by default (Sprint 11–25 backwards-compatible) and the
  `(Network, EpanetImportDiagnostics)` tuple when
  `return_diagnostics=True`.

## Fallback parser behavior

`_collect_pattern_energy_row_diagnostics(sections)` walks the
per-section tokenised rows produced by `_split_sections` in insertion
order (which preserves source-file first-appearance order on Python
3.7+) and emits one `EpanetPatternEnergyDiagnostic` for every row
inside a `[PATTERNS]` or `[ENERGY]` section. The helper is invoked
once in `_fallback_parse` after `_collect_control_rule_row_diagnostics`,
and the result is attached to the diagnostics container returned by
the fallback parser.

- Section names are canonical upper-case (`"PATTERNS"` / `"ENERGY"`),
  inherited from `_split_sections`.
- Records carry the exact tokens `_split_sections` extracted; token
  order matches the source row. `tokens` is materialised as a tuple
  before being stored in the (frozen) record.
- `text` is `" ".join(tokens)` — comments and blank rows are filtered
  by `_strip_comment` / `_split_sections` before any record can be
  emitted.
- `row_index` is the 0-based index into the per-section bucket;
  it resets per section.
- Section ordering follows `_split_sections`' dict iteration order
  (first-appearance source order). Tests pin both
  `PATTERNS-then-ENERGY` and `ENERGY-then-PATTERNS`.
- Repeated `[PATTERNS]` / `[ENERGY]` headers collapse to one bucket
  because `_split_sections` already accumulates rows under the first
  occurrence; `row_index` covers the combined source order.

The Sprint 21 ignored-section no-op contract is preserved by
construction: the parser never reads any field of these rows; it only
tokenises them, accumulates them in the section bucket, and the new
helper iterates the bucket to produce records. No hydraulic field on
the loaded `Network` consumes any pattern / energy datum.

## WNTR behaviour / asymmetry

The WNTR back-end remains structurally unchanged for Sprint 26. WNTR
has its own `[PATTERNS]` / `[ENERGY]` parser that stores those
declarations on the `WaterNetworkModel` (and uses them internally
during its simulator runs that the dPHM importer never invokes).

The dPHM WNTR adapter does **not** re-emit any `pattern_energy_rows`
records — `_wntr_parse` returns an empty `EpanetImportDiagnostics()`
exactly as it did in Sprints 23–25. The asymmetry mirrors every prior
diagnostics sprint: the fallback parser is authoritative, the WNTR
back-end is documented rather than papered over.

`test_wntr_back_end_returns_container_without_raising` confirms the
WNTR back-end returns an `EpanetImportDiagnostics` with
`pattern_energy_rows == ()` and skips cleanly when WNTR is not
installed via `pytest.importorskip("wntr")`.

WNTR HEAD / POWER / PRV / TCV / demand-multiplier parity from
Sprints 13–25 is preserved — no WNTR-side parsing or surrogate logic
changed.

## Read-only / no-op evidence

- `EpanetPatternEnergyDiagnostic` is `frozen=True`; every field is
  immutable. Tests assert `dataclasses.FrozenInstanceError` on
  reassignment of `section`, `row_index`, `tokens`, `text`.
- `tokens` is materialised as a `tuple`; `EpanetImportDiagnostics`
  remains `frozen=True` with tuple-backed
  `pattern_energy_rows`; reassignment of the container field also
  raises.
- The fallback parser never reads any field of a `[PATTERNS]` or
  `[ENERGY]` row before, during, or after diagnostic collection.
  `_collect_pattern_energy_row_diagnostics` is read-only by
  inspection (no mutation of `sections`, no side effects).
- `test_pattern_energy_diagnostics_do_not_change_network` reloads
  the baseline fixture and the perturbed fixture (baseline + multi-
  row `[PATTERNS]` + multi-row `[ENERGY]`) and asserts byte-for-byte
  equality on `edge_index`, `pipe_mask`, `pump_mask`,
  `fixed_head_mask`, `demands`, `fixed_head_values`, `lengths`,
  `diameters`, `c_factors`, `pump_speeds`, `pump_coeffs`.
- `test_pattern_energy_diagnostics_do_not_change_solve` runs
  `newton_solve(..., max_iterations=200, tol=1e-9,
  jacobian_mode="analytic")` on both networks and asserts the heads
  match to atol=1e-9 and flows match to atol=1e-12.
- `test_default_load_network_from_inp_still_returns_only_network`
  asserts the default loader still returns a bare `Network` when
  pattern / energy rows are present.

## Tests added/updated

Added one new file with 45 tests:

`tests/dphm/test_inp_pattern_energy_row_diagnostics.py`

The 45 tests fall in the following groups:

- **Public surface** (6): dataclass-ness, frozen-ness, defaults,
  `tokens`-is-tuple, container field default + frozen-ness.
- **Empty / absent** (3): no pattern/energy sections, bare
  `[PATTERNS]` header, bare `[ENERGY]` header.
- **Single-row** (2): one `[PATTERNS]` row, one `[ENERGY]` row.
- **Multi-row ordering** (2): multiple `[PATTERNS]` rows, multiple
  `[ENERGY]` rows.
- **Mixed deterministic ordering** (2): patterns-first,
  energy-first.
- **Tokeniser inheritance** (2): inline comments stripped, blank
  rows dropped.
- **Exclusion** (14): each of `CONTROLS`, `RULES`, `EMITTERS`,
  `QUALITY`, `SOURCES`, `REACTIONS`, `MIXING`, `TIMES`, `REPORT`,
  `DEMANDS` (parametrized, 10), `[STATUS]` (1), hydraulic sections
  (1), section-set membership (1), Sprint 25 channel exclusion (1).
- **Sprint 24 channel preservation** (1): `ignored_sections` still
  lists `PATTERNS` and `ENERGY`.
- **Hydraulic inertness** (4): network equality, Newton-solve
  parity, `return_diagnostics` tuple network parity, default
  loader returns bare `Network`.
- **Tuple ↔ accessor parity** (1):
  `load_inp_diagnostics(path) == load_network_from_inp(path,
  return_diagnostics=True)[1]` on all four diagnostic fields.
- **Coexistence** (2): all four diagnostic channels populated on
  one fixture, `[STATUS]` excluded from both ignored and
  pattern/energy channels.
- **Sprint 22 rejection preservation** (5, parametrized):
  CLOSED / CV / numeric / unknown id / arbitrary token still raise
  with `[PATTERNS]` and `[ENERGY]` present, through both public
  entry points.
- **Optional WNTR smoke** (1): `pytest.importorskip("wntr")` —
  returns `EpanetImportDiagnostics` with empty
  `pattern_energy_rows`.

The Sprint 23/24/25 test files are unchanged and continue to pass
unchanged.

## Validation commands / results

All run on the Sprint 26 worktree at branch `sprint26` head.

```bash
python -m pip install -e .
# (no output; editable install succeeds)

python -m pytest tests/dphm tests/models tests/training tests/dataio -q
# 1095 passed, 1 skipped, 3 warnings in 95.31s
# Skipped: tests/dphm/test_wntr_optional_import.py:371 ("WNTR is installed;
# ImportError path not exercised here") — same Sprint 25 conditional.

python -m pytest tests -q
# 1103 passed, 1 skipped, 3 warnings in 85.14s

python -m compileall -q src tests
# rc=0 (no errors, silent on success)

git status --short
#  M docs/epanet-inp-import.md
#  M src/aquaoptima/dphm/__init__.py
#  M src/aquaoptima/dphm/inp_io.py
# ?? tests/dphm/test_inp_pattern_energy_row_diagnostics.py
```

Sprint 25 baseline was 1050 / 1058 (targeted / full); Sprint 26 adds
exactly 45 tests through one new file. The 45-row delta matches:

- Targeted: 1050 + 45 = 1095 ✓
- Full: 1058 + 45 = 1103 ✓

Sprint 26-only test verification (run separately for clarity):

```bash
python -m pytest tests/dphm/test_inp_pattern_energy_row_diagnostics.py -q
# 45 passed in 5.23s
```

Combined diagnostics regression check (Sprint 23 + 24 + 25 + 26):

```bash
python -m pytest tests/dphm/test_inp_status_diagnostics.py \
    tests/dphm/test_inp_ignored_section_diagnostics.py \
    tests/dphm/test_inp_control_rule_row_diagnostics.py \
    tests/dphm/test_inp_pattern_energy_row_diagnostics.py -q
# 165 passed in 4.85s
```

Secret scan over the changed files (no findings):

```bash
# Looking for private keys, AWS access keys, credentials, etc.
# rc=0 (no matches)
```

## Compatibility notes

- `load_network_from_inp(path)` without `return_diagnostics=True`
  still returns a bare `Network` — every Sprint 11–25 caller works
  unchanged. Asserted by
  `test_default_load_network_from_inp_still_returns_only_network`.
- `EpanetImportDiagnostics` gained one optional field with a default
  value (`pattern_energy_rows: tuple[...] = ()`). Sprint 23 / 24 / 25
  callers that construct, compare, or destructure the container by
  the earlier fields keep working — the older fields keep their
  positions and defaults. Default-constructed
  `EpanetImportDiagnostics()` still equals the empty-everything
  container.
- Sprint 25 `control_rule_rows`, Sprint 24 `ignored_sections`, and
  Sprint 23 `status_rows` are all preserved byte-for-byte. Tests
  pinning the Sprint 24 ignored-section contract still see both
  `PATTERNS` and `ENERGY` listed (and the per-row channel is
  additive on top, not a replacement).
- The Sprint 22 `[STATUS]` rejection behaviour is preserved.
  Parametrized regression covers CLOSED / CV / numeric pump status /
  unknown link id / arbitrary token with `[PATTERNS]` and `[ENERGY]`
  also present.
- HEAD pump (`fit_pump_head_curve`), POWER pump
  (`fit_power_pump_surrogate`), and PRV / TCV
  (`translate_valve_to_surrogate`) tests are unchanged and pass.
- WNTR HEAD / POWER / PRV / TCV / demand-multiplier parity from
  Sprints 13–25 is preserved — the WNTR back-end is untouched.
- The optional `tests/dphm/test_wntr_optional_import.py` continues
  to skip cleanly when WNTR is not installed (it currently skips
  the "WNTR-missing" branch only because WNTR happens to be
  installed in this environment; the cross-back-end parity tests
  inside it still pass).
- No new fixtures shipped under `docs/examples/`. Sprint 26 covers
  the parser surface entirely through tmp-path fixtures, matching
  Sprint 20 / 24 / 25.

## Known limitations

- `[PATTERNS]` rows are still **dropped** at parse time. Time-varying
  demand is not activated — the dPHM core remains steady-state.
  Sprint 18's `[OPTIONS] Demand Multiplier` is still the only honoured
  demand-scaling axis.
- `[ENERGY]` rows (`GLOBAL PRICE`, `GLOBAL EFFIC`, `PUMP <id>
  PRICE`, etc.) are still **dropped** at parse time. Energy-cost
  modelling and per-pump efficiency curves are not activated. The
  POWER pump surrogate continues to use `rho_water * sg` for its
  effective density, with no per-pump efficiency multiplier.
- `[CONTROLS]` and `[RULES]` rows continue to surface only via
  `control_rule_rows` (Sprint 25); their semantics remain
  unimplemented.
- `[STATUS]` accepted-`OPEN` rows continue to surface via
  `status_rows`; `CLOSED`, `CV`, numeric pump-status, and unknown
  link ids continue to raise (Sprint 22). No closed-link / check-
  valve / pump-speed semantics are activated.
- The WNTR adapter remains documented as fallback-authoritative for
  every diagnostics channel. WNTR-side per-row records for any
  ignored section are not emitted in Sprint 26.
- Pattern / energy diagnostics are *tokenised parser rows*, not
  semantic EPANET pattern / energy structures. A multi-row pattern
  declaration surfaces as one record per source line, not one
  record per semantic profile. Multi-line `[ENERGY]` declarations
  with the same form (e.g. several `PUMP <id> PRICE` rows) surface
  as one record per row.
- No active PLC / PAC / SCADA adapter, no write/control path, no
  Darcy-Weisbach branch, no ONNX / TensorRT / Jetson deployment, no
  closed-link or check-valve modelling, no real EPANET binary /
  runtime.

## Sprint 26 hard approval gates

| Gate                                                                                  | Status |
|---------------------------------------------------------------------------------------|--------|
| Targeted pytest exits 0 (1095 passed, 1 skipped)                                      | ✓      |
| Full pytest exits 0 (1103 passed, 1 skipped)                                          | ✓      |
| compileall exits 0                                                                     | ✓      |
| `SPRINT26_REPORT.md` exists                                                            | ✓      |
| Pattern/energy row diagnostics API exists and is tested                                | ✓      |
| Row diagnostics surface only `[PATTERNS]` and `[ENERGY]` rows                          | ✓      |
| Control/rule row diagnostics from Sprint 25 still work                                 | ✓      |
| Ignored-section diagnostics from Sprint 24 still work                                  | ✓      |
| `[STATUS] OPEN` diagnostics from Sprint 23 still work                                  | ✓      |
| `STATUS` is not listed as ignored-section or pattern/energy row diagnostic             | ✓      |
| Diagnostics are proven read-only and hydraulically inert/no-op                         | ✓      |
| `load_network_from_inp(path)` remains backward compatible by default                   | ✓      |
| Sprint 22/23 rejection behavior remains intact for invalid `[STATUS]` rows             | ✓      |
| `[PATTERNS]` / `[ENERGY]` remain ignored, not implemented                              | ✓      |
| `[CONTROLS]` / `[RULES]` remain ignored, not implemented                               | ✓      |
| Existing SI/GPM/pressure/demand/SG/viscosity/ignored-section/STATUS/control-rule       | ✓      |
| fixture behavior still passes                                                          |        |
| HEAD pump tests still pass                                                             | ✓      |
| POWER pump tests still pass                                                            | ✓      |
| PRV/TCV valve tests still pass                                                         | ✓      |
| WNTR optional tests skip/pass cleanly                                                  | ✓      |
| No obvious secret files/strings introduced                                             | ✓      |
| git status contains only intended Sprint 26 changes                                    | ✓      |
| WNTR HEAD/POWER/PRV/TCV/demand-multiplier parity from Sprints 13–25 still pass         | ✓      |
| WNTR asymmetry around pattern/energy row diagnostics documented                        | ✓      |

All gates pass.

## Verdict

**APPROVED.**

## Sprint 27 recommendation

Sprint 26 has now closed the per-row visibility gap for every ignored
section EPANET-exported fixtures realistically carry with tabular
content (`[CONTROLS]`, `[RULES]`, `[PATTERNS]`, `[ENERGY]`). The
diagnostics surface is feature-complete for the steady-state dPHM
importer; further per-row channels for sections like `[EMITTERS]` /
`[QUALITY]` / `[SOURCES]` / `[REACTIONS]` / `[MIXING]` would add
maintenance cost without clear analyst value, since those sections
rarely carry meaningful per-row content in steady-state fixtures.

The recommended Sprint 27 work is:

**Sprint 27 — read-only `[CONTROLS]` row *classification* (not
activation).**

Sprint 25 surfaces each `[CONTROLS]` row as a single tokenised
record; Sprint 27 should add a `kind` field on the existing
`EpanetControlRuleDiagnostic` (or a parallel
`EpanetControlClassification` record on `EpanetImportDiagnostics`) that
categorises each `[CONTROLS]` row by the EPANET shape it most closely
matches, *without* implementing the semantics:

- `LINK_CLOSE` — `LINK <id> CLOSED [IF | AT TIME] ...`
- `LINK_OPEN` — `LINK <id> OPEN [IF | AT TIME] ...`
- `PUMP_SPEED` — `LINK <id> <numeric> [IF | AT TIME] ...`
- `NODE_HEAD` — `LINK <id> <state> IF NODE <id> [ABOVE|BELOW] <value>`
- `TIME_TRIGGER` — `LINK <id> <state> AT [CLOCKTIME] <value>`
- `UNKNOWN` — anything else.

Constraints (Sprint 27):
- still ignored, not implemented;
- read-only, hydraulically inert;
- `Network` byte-for-byte identical;
- Sprint 22 rejection behaviour preserved;
- WNTR back-end remains fallback-authoritative;
- no `[RULES]` semantic interpretation (multi-line rules stay one
  record per tokenised line, with `kind` derived from the leading
  keyword: `RULE` / `IF` / `THEN` / `ELSE` / `AND` / `PRIORITY`);
- no new physics, no write/control path, no PLC adapter.

The classification gives analysts the same kind of "did EPANET
export anything I should worry about?" answer that Sprint 24 / 25 /
26 deliver at the section / row levels, with one more axis of
granularity. It is mechanically straightforward (string matching on
the first 1–3 tokens of each row), preserves the strict no-op
guarantee, and naturally leaves space for a future "activate the
`LINK_CLOSE` subset" sprint to consume the same classification.
