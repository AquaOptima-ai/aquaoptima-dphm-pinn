# Sprint 27 — Read-only `[CONTROLS]` row classification diagnostics

## Goal

Add conservative, deterministic classification (`LINK_SETTING`,
`PUMP_SETTING`, `VALVE_SETTING`, `UNKNOWN`) on top of the Sprint 25
per-row `[CONTROLS]` / `[RULES]` diagnostics. The classification tags
each `[CONTROLS]` row by its leading tokens and by the parsed network's
link-type context, without activating any control semantics, evaluating
conditions / settings, rejecting unfamiliar rows, or mutating any
hydraulic field on the loaded `Network`.

## Files changed

- `src/aquaoptima/dphm/inp_io.py` —
  - new public `EpanetControlKind(str, Enum)` enum with four members
    (`LINK_SETTING`, `PUMP_SETTING`, `VALVE_SETTING`, `UNKNOWN`);
  - new `kind: str = "UNKNOWN"` field on `EpanetControlRuleDiagnostic`
    (backwards-compatible default so every Sprint 25 / 26 constructor
    call keeps working);
  - new `_classify_control_row(tokens, *, pipe_ids, pump_ids,
    valve_ids)` helper — conservative, deterministic, never raises;
  - `_collect_control_rule_row_diagnostics(...)` now accepts optional
    `pipe_ids`, `pump_ids`, `valve_ids` frozensets (defaulting to
    empty) and tags each emitted record. `[RULES]` rows always
    classify as `UNKNOWN`;
  - `_fallback_parse(...)` derives `pipe_ids` / `pump_ids` /
    `valve_ids` from the tokenised sections and threads them into the
    diagnostics collector.
  - `__all__` exports `EpanetControlKind`.
- `src/aquaoptima/dphm/__init__.py` — re-exports `EpanetControlKind`.
- `docs/epanet-inp-import.md` — adds the **Read-only [CONTROLS] row
  classification (Sprint 27)** section: API surface, classification
  rules, hydraulic-inertness statement, "what Sprint 27 does NOT do"
  block, WNTR asymmetry, tests inventory. Updates the document title
  to "Sprint 11–27" and extends the header summary paragraph.
- `tests/dphm/test_inp_control_row_classification.py` — new TDD test
  file (32 tests, all passing).

## Control-row classification API design

```python
from enum import Enum

class EpanetControlKind(str, Enum):
    LINK_SETTING = "LINK_SETTING"     # known pipe id
    PUMP_SETTING = "PUMP_SETTING"     # known pump id
    VALVE_SETTING = "VALVE_SETTING"   # known valve id
    UNKNOWN = "UNKNOWN"               # anything else


@dataclass(frozen=True)
class EpanetControlRuleDiagnostic:
    section: str                   # "CONTROLS" or "RULES"
    row_index: int                 # 0-based, resets per section
    tokens: tuple[str, ...]
    text: str
    message: str = _CONTROL_RULE_ROW_NOOP_MESSAGE
    kind: str = "UNKNOWN"          # Sprint 27 addition
```

Design choices:

- **Option 1** from the brief (backwards-compatible field on the
  existing dataclass) — keeps the Sprint 25 constructor call working
  and avoids growing a parallel container.
- `str` subclass enum so `rec.kind == "LINK_SETTING"` and
  `rec.kind == EpanetControlKind.LINK_SETTING` both succeed.
- The field stores the enum's string `value`, not the member itself,
  which keeps the dataclass simple and the diagnostic surface plain-
  string compatible.
- `kind` defaults to `"UNKNOWN"`, so existing Sprint 25 / 26 callers
  that pass positional / keyword arguments without `kind` are
  unaffected.

## Fallback parser behavior

For each row inside `[CONTROLS]` / `[RULES]`:

- `[RULES]` rows → `kind = "UNKNOWN"` (no per-row semantic
  classification because the importer does not interpret rule
  structure; multi-line rule blocks remain per-line records).
- `[CONTROLS]` rows are classified by their first two tokens against
  the declared pipe / pump / valve id sets:
  - `LINK <id> ...` with `<id>` in `[PUMPS]` → `PUMP_SETTING`
  - `LINK <id> ...` with `<id>` in `[VALVES]` → `VALVE_SETTING`
  - `LINK <id> ...` with `<id>` in `[PIPES]` → `LINK_SETTING`
  - any other shape (non-`LINK` leading token, unknown link id, short
    row) → `UNKNOWN`.
- Leading `LINK` keyword is case-insensitive (EPANET convention);
  link ids are case-sensitive.
- Conditions (`IF NODE ... BELOW`, `IF TIME`, `AT TIME`,
  `AT CLOCKTIME`) and settings (`1.2`, `OPEN`, `CLOSED`, `0.8`, …)
  are **not** evaluated — they only affect `tokens` / `text`.
- Unknown rows are **never** rejected. The `kind = "UNKNOWN"` value
  is a diagnostic tag, not a rejection trigger.

## WNTR behavior / asymmetry

Unchanged from Sprint 23 / 24 / 25 / 26. The WNTR back-end remains
fallback-authoritative for control-row diagnostics. WNTR has its own
strict `[CONTROLS]` / `[RULES]` parser and the dPHM WNTR adapter does
not re-emit any rows. Calling `load_inp_diagnostics(path,
parser="wntr")` returns an `EpanetImportDiagnostics` whose
`control_rule_rows` is empty regardless of what the source file
declares.

The asymmetry is intentionally documented (and tested) rather than
papered over. The WNTR smoke test in
`test_inp_control_row_classification.py` uses a fixture with
`[CONTROLS]` only (no `[RULES]`) because WNTR's strict rule parser
rejects malformed multi-line `[RULES]` blocks (it cannot evaluate a
bare `RULE` header without a body). The fallback parser is
authoritative.

## Read-only / no-op evidence

The classification is hydraulically inert. The Sprint 27 test file
proves this:

- `test_classification_does_not_change_network` — adds a mix of
  `[CONTROLS]` (pipe target, unknown link id) and `[RULES]` (bare
  `RULE` header, `THEN LINK`) to the baseline fixture; asserts every
  `Network` field is byte-for-byte identical to the baseline
  (`edge_index`, `pipe_mask`, `pump_mask`, `fixed_head_mask`,
  `demands`, `fixed_head_values`, `lengths`, `diameters`,
  `c_factors`, `pump_coeffs`, `pump_speeds`).
- `test_classification_does_not_change_solve` — analytic-Newton-
  solves both networks (with and without classified controls) and
  asserts heads / flows match to atol=1e-9 / atol=1e-12.
- `test_classification_does_not_mutate_demands_on_pump_fixture` —
  pump-fixture-specific invariance test that pins the pump-coeff /
  demand path under classified `LINK PU1 ...` rows.
- `test_unknown_link_id_does_not_raise_on_network_load` — proves that
  unknown link ids in `[CONTROLS]` produce `UNKNOWN` diagnostics, not
  `ValueError`.

## Tests added/updated

New file `tests/dphm/test_inp_control_row_classification.py` (32
tests, all passing):

Public surface:

1. `test_epanet_control_kind_enum_members_exist`
2. `test_epanet_control_kind_str_subclass`
3. `test_epanet_control_kind_has_exactly_four_members`
4. `test_diagnostic_has_kind_field_with_default_unknown`
5. `test_diagnostic_kind_field_is_frozen`
6. `test_diagnostic_accepts_each_kind`
7. `test_sprint_25_default_constructor_still_works`

Classification (positive cases):

8. `test_pipe_link_control_row_classifies_as_link_setting`
9. `test_pipe_link_control_row_lowercase_link_keyword`
10. `test_pump_link_control_row_classifies_as_pump_setting`
11. `test_pump_link_open_control_row_classifies_as_pump_setting`
12. `test_valve_link_control_row_classifies_as_valve_setting`

Classification (UNKNOWN / non-rejection):

13. `test_unknown_link_id_classifies_as_unknown`
14. `test_unknown_link_id_does_not_raise_on_network_load`
15. `test_non_link_prefixed_control_row_classifies_as_unknown`
16. `test_short_control_row_classifies_as_unknown`

`[RULES]` are never narrowed beyond UNKNOWN:

17. `test_rules_rows_classify_as_unknown`
18. `test_rules_then_with_known_link_id_still_unknown`

Sprint 25 field preservation + section ordering:

19. `test_classification_preserves_tokens_text_and_row_index`
20. `test_classification_preserves_section_ordering`

Hydraulic inertness:

21. `test_classification_does_not_change_network`
22. `test_classification_does_not_change_solve`
23. `test_classification_does_not_mutate_demands_on_pump_fixture`

API parity / backwards compatibility:

24. `test_load_inp_diagnostics_and_tuple_path_return_same_kinds`
25. `test_default_load_network_from_inp_still_returns_only_network`

Coexistence:

26. `test_classification_coexists_with_other_diagnostics`

Sprint 22 rejection preserved (parametrised, 5 cases):

27. `test_status_rejection_preserved_with_classified_controls[CLOSED]`
28. `test_status_rejection_preserved_with_classified_controls[CV]`
29. `test_status_rejection_preserved_with_classified_controls[1.0]`
30. `test_status_rejection_preserved_with_classified_controls[PHANTOM OPEN]`
31. `test_status_rejection_preserved_with_classified_controls[MAYBE]`

Optional WNTR:

32. `test_wntr_back_end_classification_empty`

Sprint 25 tests in `test_inp_control_rule_row_diagnostics.py` remain
untouched and still pass (the new `kind` field's default
`"UNKNOWN"` keeps every existing test green).

## Validation commands / results

```
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm/test_inp_control_row_classification.py -q
32 passed in 4.81s

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
1127 passed, 1 skipped, 3 warnings in 97.11s

$ python -m pytest tests -q
1135 passed, 1 skipped, 3 warnings in 95.26s

$ python -m compileall src tests
(clean — no error / failed lines)

$ git status --short
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/__init__.py
 M src/aquaoptima/dphm/inp_io.py
?? tests/dphm/test_inp_control_row_classification.py
```

Sprint-over-sprint deltas:

- Targeted: Sprint 26 1095 → Sprint 27 **1127** passed (+32).
- Full: Sprint 26 1103 → Sprint 27 **1135** passed (+32).
- The single skip is `test_wntr_optional_import.py:371` ("WNTR is
  installed; ImportError path not exercised here"), identical to
  Sprint 26.

Secret scan: zero findings on the four touched files.

## Compatibility notes

- `load_network_from_inp(path)` (without `return_diagnostics`)
  unchanged — still returns only a `Network`.
- `EpanetControlRuleDiagnostic` constructor unchanged for Sprint 25 /
  26 callers — `kind` defaults to `"UNKNOWN"`.
- Every Sprint 23 / 24 / 25 / 26 diagnostic field (`status_rows`,
  `ignored_sections`, `control_rule_rows`, `pattern_energy_rows`) is
  preserved unchanged.
- Sprint 22 `[STATUS]` rejection paths (CLOSED, CV, numeric pump
  status, unknown link id, arbitrary token) still raise
  `ValueError`; no partial diagnostics leak out on rejection.
- The HEAD / POWER pump translation paths, the PRV / TCV valve
  surrogate, and the SI / GPM / pressure / demand-multiplier / SG /
  viscosity / ignored-section / `[STATUS]` / per-row diagnostics
  paths are all green (full and targeted suites).
- WNTR optional tests skip cleanly when WNTR is absent and pass with
  the installed `wntr==1.4.0` — including the Sprint 13–26 HEAD /
  POWER / PRV / TCV / demand-multiplier parity tests.

## Known limitations

- Classification is **syntactic + link-type-aware**, not semantic. It
  reads the leading tokens and looks the link id up against the
  declared pipe / pump / valve id sets; it does not interpret
  conditions or settings. Two rows that differ only in their
  condition body classify identically.
- `[RULES]` rows always classify as `UNKNOWN`. EPANET rules span
  multiple lines (`RULE` / `IF` / `THEN` / `ELSE` / `PRIORITY` …) and
  the dPHM importer does not reconstruct semantic rule blocks. A
  `THEN LINK <pipe_id> ...` row inside `[RULES]` is **not** narrowed
  to `LINK_SETTING` even though the link id would resolve.
- The classifier recognises only the `LINK <id> ...` leading shape.
  Some EPANET dialects emit `PUMP <id> ...` or other variants; those
  classify as `UNKNOWN`. This is documented and conservative — a
  future sprint can extend the recognised shapes without breaking
  callers because every new shape would simply move rows out of the
  `UNKNOWN` bucket.
- The WNTR back-end remains empty for `control_rule_rows`. Sprint 27
  does not add WNTR-side classification. The fallback parser is
  authoritative; the asymmetry is documented.
- No `[CONTROLS]` / `[RULES]` semantics are activated. Closed-link
  modelling, check valves, pump-speed changes from `[STATUS]` /
  `[CONTROLS]`, active-control state machines, time-varying demand
  via `[PATTERNS]`, and energy-cost modelling via `[ENERGY]` are all
  still deferred.

## Verdict

**APPROVED.**

All Sprint 27 hard approval gates pass:

- targeted pytest exits 0 (1127 passed, 1 skipped)
- full pytest exits 0 (1135 passed, 1 skipped)
- compileall exits 0
- `SPRINT27_REPORT.md` exists (this file)
- control-row classification API exists (`EpanetControlKind`,
  `EpanetControlRuleDiagnostic.kind`) and is tested (32 tests)
- classification surfaces only diagnostic categories for `[CONTROLS]`
  rows; `[RULES]` rows remain `UNKNOWN`
- unknown controls are diagnosed (`kind = "UNKNOWN"`), not rejected
- no active control / rule / pattern / energy semantics are
  implemented
- Sprint 26 pattern/energy diagnostics still work (regression tests
  green)
- Sprint 25 control/rule row diagnostics still work (regression
  tests green; `kind` default preserves construction surface)
- Sprint 24 ignored-section diagnostics still work
- Sprint 23 `[STATUS] OPEN` diagnostics still work
- diagnostics are proven read-only and hydraulically inert (`Network`
  byte-for-byte invariance + Newton-solve identity to 1e-9 / 1e-12)
- `load_network_from_inp(path)` remains backwards-compatible by
  default
- Sprint 22 / 23 rejection behaviour intact for status-changing /
  invalid `[STATUS]` rows
- existing SI / GPM / pressure / demand / SG / viscosity / diagnostic
  fixture behaviour still passes
- HEAD pump tests still pass; POWER pump tests still pass; PRV / TCV
  valve tests still pass
- WNTR optional tests skip / pass cleanly (and WNTR HEAD / POWER /
  PRV / TCV / demand-multiplier parity from Sprints 13–26 still
  passes)
- no secret files / strings introduced
- git status contains only the four intended Sprint 27 changes

## Sprint 28 recommendation

Continue the **read-only diagnostics ladder** with one more thin
visibility layer before any active hydraulic semantics are added.
Recommended Sprint 28 scope:

**Read-only `[EMITTERS]` / `[DEMANDS]` per-row diagnostics.**

Sprint 26 added per-row visibility for `[PATTERNS]` / `[ENERGY]`.
Sprint 27 added classification on top of the existing per-row
`[CONTROLS]` channel. The two remaining ignored sections that EPANET-
exported fixtures often carry with non-trivial per-row content —
`[EMITTERS]` (pressure-driven demand coefficients) and `[DEMANDS]`
(per-pattern / per-junction multi-demand declarations) — still
surface only at the section level via `ignored_sections`. Mirroring
the Sprint 25 / 26 pattern, Sprint 28 would add a new
`emitters_demands_rows: tuple[EpanetEmitterDemandDiagnostic, ...]`
field to `EpanetImportDiagnostics`, emit one record per tokenised
parser row, and prove byte-for-byte invariance + Newton-solve
identity exactly as Sprint 25 / 26 did.

Hard scope boundaries (matching Sprint 25 / 26 / 27):

- visibility only — no pressure-driven demand modelling, no
  per-pattern demand evaluation;
- fallback parser authoritative; WNTR back-end documented as empty;
- `Network` and Newton-solve unchanged;
- `[STATUS]` rejection contract preserved.

After Sprint 28, the per-row visibility ladder is complete for every
ignored section that carries content the analyst-facing diagnostics
should expose. A future sprint can then begin the *activation* work
(e.g. closed-link modelling, active-control state machines,
time-varying demands) on top of a stable diagnostics foundation.
