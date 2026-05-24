# Sprint 25 — EPANET `[CONTROLS]` / `[RULES]` per-row read-only diagnostics

**Branch:** `sprint25` (worktree based on Sprint 24 commit
`9a223b0 feat: surface epanet ignored-section diagnostics`).

## Goal recap

Add a *read-only*, per-row diagnostics surface for the two ignored
sections most often carried by EPANET-exported fixtures —
`[CONTROLS]` and `[RULES]` — on top of the Sprint 24 ignored-section
diagnostics. Analysts can see the exact unsupported rows declared in
an imported `.inp` file. Sprint 25 is **visibility only**: every
control / rule row is still dropped on the floor at parse time, the
loaded `Network` is byte-for-byte identical to one loaded from a
fixture without `[CONTROLS]` / `[RULES]`, and the Sprint 22 `[STATUS]`
rejection behaviour is preserved.

Sprint 25 deliberately does NOT:

- activate `[CONTROLS]` / `[RULES]` semantics;
- model closed links, check valves, pump-speed changes, or
  fixed-head changes from `[STATUS]`;
- parse `[PATTERNS]` for time-varying demand;
- parse `[ENERGY]` for energy-cost modelling;
- add Darcy-Weisbach or any new hydraulic physics;
- wire a real PLC/PAC/SCADA adapter or write/control path;
- bring in a real EPANET binary/runtime;
- download anything during tests;
- claim production or savings.

## Files changed

```
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/__init__.py
 M src/aquaoptima/dphm/inp_io.py
?? tests/dphm/test_inp_control_rule_row_diagnostics.py
```

- `src/aquaoptima/dphm/inp_io.py` — adds the
  `EpanetControlRuleDiagnostic` frozen dataclass, the
  `EpanetImportDiagnostics.control_rule_rows` field, the
  `_collect_control_rule_row_diagnostics` helper, fallback-parser
  wiring, and updates the module docstring + `__all__`. The WNTR
  back-end's empty-diagnostics comment is extended to mention
  Sprint 25 asymmetry.
- `src/aquaoptima/dphm/__init__.py` — re-exports
  `EpanetControlRuleDiagnostic` alongside the existing Sprint 23 / 24
  diagnostic types.
- `docs/epanet-inp-import.md` — new "Read-only [CONTROLS] / [RULES]
  row diagnostics (Sprint 25)" section, leading-paragraph update,
  title bumped to "Sprint 11–25".
- `tests/dphm/test_inp_control_rule_row_diagnostics.py` — new TDD
  test module: 42 tests covering the new API surface, ordering,
  exclusion of other sections, hydraulic inertness, Newton-solve
  invariance, return-diagnostics tuple, Sprint 22 rejection
  preservation, and the optional WNTR smoke check.

No other files were touched.

## Control/rule row diagnostics API design

### New dataclass

```python
@dataclass(frozen=True)
class EpanetControlRuleDiagnostic:
    section: str                   # "CONTROLS" or "RULES" (upper-case)
    row_index: int                 # 0-based, resets per section
    tokens: tuple[str, ...]        # parser-tokenised row, single-space split
    text: str                      # tokens joined by a single space
    message: str = (
        "Row present but ignored by the steady-state dPHM importer."
    )
```

Pinned `message` is a module-level constant so two records do not
surface spurious string variation.

### Container extension

```python
@dataclass(frozen=True)
class EpanetImportDiagnostics:
    status_rows: tuple[EpanetStatusDiagnostic, ...] = ()
    ignored_sections: tuple[EpanetIgnoredSectionDiagnostic, ...] = ()
    control_rule_rows: tuple[EpanetControlRuleDiagnostic, ...] = ()
```

The new field defaults to `()` so Sprint 23 / 24 callers stay
backwards-compatible. Both classes remain `frozen=True` and every
tuple field is a real `tuple` (not a list), so the diagnostics
surface is structurally read-only.

### Helper contract

`_collect_control_rule_row_diagnostics(sections)` walks the per-section
tokenised rows produced by `_split_sections` and emits one record per
row inside a `[CONTROLS]` or `[RULES]` section. Iteration uses dict
order, which preserves the first-appearance source-file order of each
section header. `row_index` is 0-based within each section bucket and
preserves the source-file row order.

### Public accessors

```python
diagnostics = load_inp_diagnostics(path, parser="fallback")
network, diagnostics = load_network_from_inp(
    path, parser="fallback", return_diagnostics=True,
)
```

`load_network_from_inp(path)` (without `return_diagnostics=True`)
continues to return just a `Network`, preserving Sprint 11–24
backwards compatibility for every existing caller.

## Fallback parser behaviour

`_fallback_parse` calls `_collect_control_rule_row_diagnostics`
*after* parsing every hydraulic section, immediately after the
Sprint 24 ignored-section collection and before constructing the
`EpanetImportDiagnostics`. The helper:

- emits one record per row in `[CONTROLS]` and one per row in
  `[RULES]` — *every* tokenised row, including rows that semantically
  belong to the same multi-line EPANET `RULE` block (`RULE`, `IF`,
  `THEN`, `AND`, …). The dPHM importer does not interpret rule
  structure; each parser line stands on its own;
- excludes every other ignored section (`PATTERNS`, `ENERGY`,
  `EMITTERS`, `QUALITY`, `SOURCES`, `REACTIONS`, `MIXING`,
  `DEMANDS`, `TIMES`, `REPORT`, and the inert layout sections). Those
  still surface at the section level via `ignored_sections`;
- excludes `[STATUS]` — Sprint 22 removed it from `IGNORED_SECTIONS`;
  accepted `OPEN` rows flow through `status_rows`, rejected rows
  raise as in Sprint 22;
- excludes hydraulically active sections (`JUNCTIONS`, `RESERVOIRS`,
  `TANKS`, `PIPES`, `PUMPS`, `VALVES`, `OPTIONS`, `CURVES`) by
  construction — they are not in `_CONTROL_RULE_SECTIONS`;
- preserves source-file ordering: section ordering follows
  `_split_sections`' insertion order (first-appearance), and within
  each section `row_index` follows file order. Repeated `[CONTROLS]`
  headers collapse into one bucket because `_split_sections` already
  accumulates them, and the rows preserve their combined order;
- preserves the exact parser tokens. `_split_sections` strips inline
  `; …` comments and drops blank rows before any row enters the
  per-section bucket; the diagnostics surface therefore never carries
  comments or blank rows;
- builds `text` by joining `tokens` with single spaces. The original
  whitespace pattern is not preserved (the parser tokeniser already
  collapses it), but every parsed token appears in order.

## WNTR behaviour and asymmetry

The WNTR back-end is documented as **fallback-authoritative** for
the diagnostics surface, mirroring the Sprint 23 (`status_rows`) and
Sprint 24 (`ignored_sections`) contract. When `parser="wntr"`:

- the dPHM WNTR adapter does NOT re-emit any `[CONTROLS]` /
  `[RULES]` rows as diagnostics — the returned
  `EpanetImportDiagnostics` has `control_rule_rows == ()`;
- WNTR has its own `[CONTROLS]` / `[RULES]` parser and interprets
  some of those rows internally; the dPHM adapter does not consume
  the WNTR-parsed structure;
- the diagnostics container shape and frozen contract are preserved
  so callers can branch on parser explicitly if they ever need
  WNTR-side records;
- the test
  `test_wntr_back_end_returns_container_without_raising` enforces
  the empty-tuple contract via `pytest.importorskip("wntr")`;
- this is the same asymmetry the report calls out for Sprint 23 / 24
  — fallback authoritative, WNTR documented rather than papered over.

## Read-only / no-op evidence

Multiple independent invariants pin the read-only contract:

- **API shape:**
  `EpanetControlRuleDiagnostic` is `frozen=True`. Reassigning any
  field (`section`, `row_index`, `tokens`, `text`) raises
  `dataclasses.FrozenInstanceError`. `tokens` is a `tuple`.
  `EpanetImportDiagnostics.control_rule_rows` is also a `tuple` and
  the container is `frozen=True`.

- **Network bytes:**
  `test_control_rule_diagnostics_do_not_change_network` loads the
  baseline fixture and the same fixture with a 2-row `[CONTROLS]`
  block + a 3-row `[RULES]` block, and asserts byte-for-byte
  equality across `edge_index`, `pipe_mask`, `pump_mask`,
  `fixed_head_mask`, `demands`, `fixed_head_values`, `lengths`,
  `diameters`, `c_factors`, `pump_speeds`, and `pump_coeffs`.

- **Newton solve:**
  `test_control_rule_diagnostics_do_not_change_solve` runs
  `newton_solve(..., jacobian_mode="analytic", tol=1e-9)` on both
  the baseline and the perturbed network and asserts the heads /
  flows match to `atol=1e-9` / `atol=1e-12`.

- **Status rejection preserved:**
  `test_rejected_status_rows_still_raise_with_controls_present`
  parametrises every Sprint 22 rejection path (`CLOSED`, `CV`,
  numeric pump speed, unknown link id, arbitrary token) co-occurring
  with a `[CONTROLS]` block and asserts both
  `load_inp_diagnostics` and `load_network_from_inp(...,
  return_diagnostics=True)` raise `ValueError` with no partial
  diagnostics emitted.

- **Sprint 23 / 24 channels preserved:**
  `test_status_ignored_and_control_rule_diagnostics_coexist` asserts
  the same import surfaces `status_rows`, `ignored_sections`, and
  `control_rule_rows` together, with each channel preserving its
  earlier-sprint contract (`status_rows` carries Sprint 23 records
  for `OPEN` rows; `ignored_sections` carries Sprint 24 records for
  every present `IGNORED_SECTIONS` member; `control_rule_rows`
  carries only `CONTROLS` / `RULES` rows).

- **Default loader unchanged:**
  `test_default_load_network_from_inp_still_returns_only_network`
  confirms `load_network_from_inp(path)` (no `return_diagnostics`)
  still returns just a `Network` even when `[CONTROLS]` / `[RULES]`
  are present.

## Tests added / updated

New: `tests/dphm/test_inp_control_rule_row_diagnostics.py` — 42
tests, all passing. Coverage groups (with names):

- public surface — `test_control_rule_diagnostic_is_dataclass`,
  `_is_frozen`, `_defaults`, `_tokens_is_tuple`,
  `test_diagnostics_container_has_control_rule_rows_field`,
  `_is_frozen_for_control_rule_rows`;
- empty / absent cases —
  `test_diagnostics_empty_when_no_controls_or_rules`,
  `_when_bare_controls_header`, `_when_bare_rules_header`;
- single CONTROLS row —
  `test_single_controls_row_emits_one_diagnostic`;
- ordering / row_index —
  `test_multiple_controls_rows_preserve_order_and_row_index`,
  `test_rules_rows_emit_one_record_per_parser_line`,
  `test_mixed_controls_and_rules_source_order_controls_first`,
  `_source_order_rules_first`;
- token / text fidelity —
  `test_inline_comment_stripped_from_control_row`,
  `test_blank_rows_inside_controls_are_dropped`;
- section exclusions — parametrised
  `test_other_ignored_sections_not_in_control_rule_rows`
  (`PATTERNS`, `ENERGY`, `EMITTERS`, `QUALITY`, `SOURCES`,
  `REACTIONS`, `MIXING`, `TIMES`, `REPORT`, `DEMANDS`),
  `test_status_section_never_in_control_rule_rows`,
  `test_hydraulic_sections_never_in_control_rule_rows`,
  `test_emitted_records_only_carry_controls_or_rules_section`;
- Sprint 24 channel preserved —
  `test_ignored_sections_still_lists_controls_and_rules`;
- hydraulic inertness —
  `test_control_rule_diagnostics_do_not_change_network`,
  `_do_not_change_solve`,
  `test_return_diagnostics_network_matches_default_load`,
  `test_default_load_network_from_inp_still_returns_only_network`;
- API parity —
  `test_load_inp_diagnostics_matches_load_network_from_inp_tuple`;
- combined channels —
  `test_status_ignored_and_control_rule_diagnostics_coexist`;
- Sprint 22 rejection preservation — parametrised
  `test_rejected_status_rows_still_raise_with_controls_present`
  (`CLOSED`, `CV`, numeric, unknown id, arbitrary token);
- WNTR optional smoke —
  `test_wntr_back_end_returns_container_without_raising`
  (`pytest.importorskip("wntr")`).

No existing tests required edits. Sprint 23 / 24 / 22 / 21 / 20 / 19 /
18 / 17 / 16 / 15 / 14 / 13 / 12 / 11 tests all pass unchanged.

## Validation commands and results

```
python -m pip install -e .
# Successfully installed aquaoptima-dphm-pinn-0.1.0

python -m pytest tests/dphm tests/models tests/training tests/dataio -q
# 1050 passed, 1 skipped, 3 warnings in 88.46s

python -m pytest tests -q
# 1058 passed, 1 skipped, 3 warnings in 83.71s

python -m compileall src tests
# exit 0 — no errors

git status --short
#  M docs/epanet-inp-import.md
#  M src/aquaoptima/dphm/__init__.py
#  M src/aquaoptima/dphm/inp_io.py
# ?? tests/dphm/test_inp_control_rule_row_diagnostics.py
```

The single skipped test is the pre-existing
`tests/dphm/test_wntr_optional_import.py::test_..._import_error_path`
which skips because WNTR is installed in this environment (it only
runs to validate the ImportError surface when WNTR is missing).

Targeted Sprint 25 module: 42 / 42 passed in 4.6s.

Targeted Sprint 23 + 24 + 22 + 21 diagnostics modules combined:
215 / 215 passed.

Targeted Sprint 11–18 regression modules (pump curves, power pump,
valves, US fixtures, pressure units, demand multiplier, specific
gravity, viscosity, WNTR pump / valve helpers): 404 / 404 passed.

## Compatibility notes

- `load_network_from_inp(path)` (no `return_diagnostics`) is
  unchanged. Every Sprint 11–24 caller works exactly as before.
- `load_inp_diagnostics(path)` and `load_network_from_inp(path,
  return_diagnostics=True)` now expose the third diagnostics channel
  via the existing `EpanetImportDiagnostics` container — adding a
  new optional field with a default value is backwards-compatible.
- `EpanetImportDiagnostics()` with no kwargs is still valid and now
  defaults all three tuple fields to `()`.
- The Sprint 23 (`status_rows`) and Sprint 24 (`ignored_sections`)
  channels are preserved bit-for-bit: same shape, same records,
  same source-order semantics.
- Sprint 22 `[STATUS]` rejection paths are preserved bit-for-bit:
  `CLOSED`, `CV`, numeric pump speed, unknown link id, short row,
  arbitrary token all still raise `ValueError` (validated by
  `test_rejected_status_rows_still_raise_with_controls_present`).
- The Sprint 21 ignored-section byte-for-byte network invariance
  contract is preserved: adding `[CONTROLS]` / `[RULES]` to a
  fixture leaves every `Network` field unchanged
  (`test_control_rule_diagnostics_do_not_change_network`).
- Sprint 11–20 unit-system, demand-multiplier, specific-gravity,
  viscosity, PRV/TCV, HEAD pump, POWER pump, US-fixture, pressure-
  unit behaviour is untouched.
- WNTR optional tests skip cleanly when WNTR is not installed (the
  Sprint 25 WNTR smoke test uses `pytest.importorskip("wntr")`).

## Known limitations

- Sprint 25 surfaces visibility only. `[CONTROLS]` and `[RULES]`
  semantics remain unsupported: closed-link state, pump speed
  changes, check-valve behaviour, fixed-head changes driven by
  rules, and time-conditioned operating modes are all dropped on
  the floor at parse time.
- Records are **tokenised parser rows**, not semantic EPANET rule
  blocks. A three-line EPANET rule (`RULE Rn` / `IF …` / `THEN …`)
  surfaces as three separate records. Reconstructing semantic rule
  blocks would require a real EPANET rule grammar parser and is
  out of scope for this sprint.
- The `text` field is reconstructed from the parser tokens with
  single-space joins; original whitespace (tabs, multi-space
  indentation) is not preserved. Comments are stripped before
  tokenisation and therefore not preserved.
- The WNTR back-end is fallback-authoritative for `control_rule_rows`
  (returns `()`). Sprint 25 does not require WNTR parity for this
  channel and does not implement it — the diagnostics surface is
  documented as fallback-authoritative for the new field.
- Only `[CONTROLS]` and `[RULES]` are surfaced per-row. Other
  ignored sections (`[PATTERNS]`, `[ENERGY]`, `[EMITTERS]`,
  `[QUALITY]`, `[SOURCES]`, `[REACTIONS]`, `[MIXING]`,
  `[DEMANDS]`, `[TIMES]`, `[REPORT]`) remain visible at the
  section level via Sprint 24's `ignored_sections` only. The dPHM
  importer has no use for their row content, so the diagnostics
  surface is intentionally narrow.

## Sprint 25 hard approval gates — checklist

- [x] targeted pytest exits 0 (1050 passed, 1 skipped)
- [x] full pytest exits 0 (1058 passed, 1 skipped)
- [x] compileall exits 0
- [x] `SPRINT25_REPORT.md` exists (this file)
- [x] control/rule row diagnostics API exists and is tested
      (`EpanetControlRuleDiagnostic`, `control_rule_rows`)
- [x] row diagnostics surface only `[CONTROLS]` and `[RULES]` rows
      (parametrised exclusion tests for `PATTERNS`, `ENERGY`,
      `EMITTERS`, `QUALITY`, `SOURCES`, `REACTIONS`, `MIXING`,
      `TIMES`, `REPORT`, `DEMANDS`, plus hydraulic-section
      exclusion test)
- [x] ignored-section diagnostics from Sprint 24 still work
      (`test_ignored_sections_still_lists_controls_and_rules`,
      and the entire Sprint 24 module passes)
- [x] `[STATUS] OPEN` diagnostics from Sprint 23 still work
      (Sprint 23 module passes; coexistence test asserts
      `status_rows == ["P1", "P2"]` on a mixed file)
- [x] `STATUS` is not listed as ignored-section or control/rule
      row diagnostic
      (`test_status_section_never_in_control_rule_rows` + Sprint 24's
      `test_status_section_never_in_ignored_diagnostics`)
- [x] diagnostics are proven read-only and hydraulically inert / no-op
      (frozen-dataclass tests + byte-for-byte network test +
      Newton-solve invariance test)
- [x] `load_network_from_inp(path)` remains backward compatible by
      default (`test_default_load_network_from_inp_still_returns_only_network`)
- [x] Sprint 22 / 23 rejection behaviour remains intact for
      status-changing/invalid `[STATUS]` rows
      (`test_rejected_status_rows_still_raise_with_controls_present`)
- [x] `[CONTROLS]` / `[RULES]` remain ignored, not implemented
      (`test_control_rule_diagnostics_do_not_change_network` +
      `test_control_rule_diagnostics_do_not_change_solve`)
- [x] existing SI / GPM / pressure / demand / SG / viscosity /
      ignored-section / STATUS fixture behaviour still passes
      (full pytest passes)
- [x] HEAD pump tests still pass (Sprint 12 / 13)
- [x] POWER pump tests still pass (Sprint 14)
- [x] PRV / TCV valve tests still pass (Sprint 15)
- [x] WNTR optional tests skip / pass cleanly
      (`pytest.importorskip("wntr")` guards used throughout;
      `test_wntr_back_end_returns_container_without_raising` runs
      with WNTR installed)
- [x] no obvious secret files / strings introduced (secret scan clean)
- [x] git status contains only intended Sprint 25 changes
      (3 modified files + 1 new test module)

## Sprint 25 extra WNTR gates

WNTR `1.4.0` is installed in this environment, so the additional
gates apply:

- [x] WNTR HEAD pump parity (Sprint 13) — passes
- [x] WNTR POWER pump parity (Sprint 14) — passes
- [x] WNTR PRV / TCV parity (Sprint 15) — passes
- [x] WNTR demand-multiplier parity (Sprint 18) — passes
- [x] WNTR `[STATUS]` / ignored-section asymmetry documented
      (fallback authoritative; WNTR returns empty diagnostics)
- [x] WNTR `[CONTROLS]` / `[RULES]` per-row asymmetry documented
      and tested (fallback authoritative; WNTR returns
      `control_rule_rows == ()`)

## Verdict

**APPROVED**

All hard gates pass:

- 1050 / 1051 targeted tests pass (1 skipped is the pre-existing
  WNTR-absent ImportError-path test that skips when WNTR is
  installed);
- 1058 / 1059 full tests pass (same single pre-existing skip);
- compileall clean on `src` and `tests`;
- the new public API (`EpanetControlRuleDiagnostic`,
  `EpanetImportDiagnostics.control_rule_rows`) is documented,
  tested, frozen / read-only, hydraulically inert, and exported
  from `aquaoptima.dphm`;
- Sprint 21 ignored-section invariance is preserved bit-for-bit;
- Sprint 22 `[STATUS]` rejection paths are preserved bit-for-bit;
- Sprint 23 / 24 diagnostics channels are preserved bit-for-bit;
- WNTR optional behaviour matches the Sprint 23 / 24 asymmetry
  contract;
- no secrets introduced; git status carries only Sprint 25 changes.

## Recommendation for Sprint 26

Sprint 25 closed the diagnostics surface for the two most
operationally interesting ignored sections without changing
hydraulics. The next sensible visibility-only step that does not
violate the steady-state safety boundary is one of these (pick one,
do not bundle):

**Recommended (single Sprint 26 scope):**
**Read-only `[PATTERNS]` / `[ENERGY]` row diagnostics.**

Add `EpanetPatternRowDiagnostic` and `EpanetEnergyRowDiagnostic`
(or a single unified row-diagnostic type) on the existing
`EpanetImportDiagnostics` container so analysts can see the
declared diurnal demand patterns and energy-cost directives without
the parser activating them. Same shape, same frozen / tuple
contract, same `_split_sections`-driven helper, same WNTR
fallback-authoritative asymmetry. Specifically:

- emit one record per row inside `[PATTERNS]` and `[ENERGY]`
  (these are by far the next two most-carried ignored sections);
- exclude `[CONTROLS]`, `[RULES]`, `[STATUS]`, and every
  hydraulic section, mirroring Sprint 25's exclusion contract;
- preserve byte-for-byte `Network` invariance and Newton-solve
  invariance;
- preserve the Sprint 22 / 23 / 24 / 25 channels bit-for-bit;
- document `[PATTERNS]` rows as parser tokens, not semantic
  multipliers (matching Sprint 25's tokens-vs-semantics caveat);
- document WNTR asymmetry the same way (fallback authoritative,
  WNTR returns empty).

This keeps the steady-state safety boundary intact (no
time-varying demand, no energy-cost modelling) while continuing the
incremental visibility-only theme of Sprints 21–25.

Alternative scopes to **defer beyond Sprint 26**:

- *Activating* `[CONTROLS]` rules (closed-link state, pump-speed
  changes) — this is a hydraulic-physics change, not a visibility
  change, and requires solver work plus an explicit safety-boundary
  review.
- Darcy-Weisbach + Reynolds-based friction (which is where
  `[OPTIONS] Viscosity` would finally propagate). Big sprint;
  separate.
- Time-varying demand from `[PATTERNS]` semantics. Requires
  steady-state-vs-transient solver scoping.
- `[CONTROLS]` / `[RULES]` semantic parsing into structured rule
  objects (still read-only, but a much larger grammar). Probably a
  later sprint once Sprint 26 has expanded the per-row diagnostic
  pattern to all ignored sections.
- Any real PLC / PAC / SCADA adapter or write/control path —
  permanently out of scope until a separate safety review.
