# Sprint 22 Report — EPANET `[STATUS]` no-op validation

## Summary

Sprint 22 narrows the Sprint 21 ignored-section contract for
`[STATUS]`. Through Sprint 21 the fallback parser tokenised
`[STATUS]` rows and then never read them; from Sprint 22 onwards the
parser **actively validates** the section so EPANET-exported files
that include explicit `<link_id> OPEN` rows load without pretending
to implement closed-link or active-status physics.

Sprint 22 is **parser-only**. No new hydraulic physics, no
closed-link or check-valve modelling, no `[CONTROLS]` / `[RULES]`
activation, no WNTR-adapter changes, no Sprint 23 work.

## Files changed

| File                                            | Change                                                                                                            |
|-------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                 | Added `_validate_status_rows`. Removed `STATUS` from `IGNORED_SECTIONS`. Wired the validator into `_fallback_parse`. Updated module docstring (Sprint 22 boundary) and the `IGNORED_SECTIONS` block comment. |
| `tests/dphm/test_inp_status.py` (new)           | 29 tests covering the Sprint 22 contract (accept `OPEN` no-ops on pipes/pumps/PRV/TCV, case/whitespace tolerance, ordering invariance, rejection of `CLOSED` / `CV` / numeric / unknown id / unknown token / short row, Sprint 11 `[PIPES] ... CLOSED` rejection preserved, Sprint 21 `[CONTROLS]` / `[RULES]` ignore preserved, optional WNTR smoke). |
| `tests/dphm/test_inp_ignored_sections.py`       | Updated module docstring to reflect Sprint 22. Added `test_status_is_not_globally_ignored_after_sprint_22` pinning the public-surface change. |
| `docs/epanet-inp-import.md`                     | Header bumped to Sprint 11–22. Added "Explicit `[STATUS]` no-op rows (Sprint 22)" section with accept/reject tables, "what it does NOT do", and test list. Removed `[STATUS]` row from the IGNORED_SECTIONS table; added an inline pointer to the Sprint 22 section. |

No test fixtures were added under `docs/examples/`. The Sprint 22
surface is exercised through tmp-path fixtures only, matching the
Sprint 20 / 21 style.

## `[STATUS] OPEN` design

### Validator

`_validate_status_rows(rows, known_link_ids)`:

* For each row in `sections.get("STATUS", [])`:
  * Row must have **≥ 2 tokens** (`link_id`, status token). Short
    rows raise `ValueError` with `[STATUS]` and `at least 2 tokens`
    in the message.
  * `link_id` is matched **exact-case** against the union of
    `[PIPES]` / `[PUMPS]` / `[VALVES]` ids that the parser has
    already registered. This is consistent with the parser's
    existing exact-case id handling (e.g. pipe `node1` /
    `node2` lookups) — the parser does **not** introduce a
    broad case-insensitive id table just for `[STATUS]`. Unknown
    ids raise with the id and `[STATUS]` in the message.
  * The status token is upper-cased before comparison. `OPEN`
    (any spelling) is accepted as a no-op (`continue`).
  * `CLOSED` and `CV` (case-folded) raise with the link id and
    the original-case token in the message.
  * If the token parses as `float(...)`, it is treated as a
    numeric pump speed / status declaration and raises with the
    link id and the numeric value in the message.
  * Any other token raises a generic "unsupported status token"
    error naming the link id and the offending token.
* The function is a pure side-effect-free validator: accepted
  rows are no-ops, so the loaded `Network` is byte-for-byte
  identical to the same fixture with no `[STATUS]` section.

### Parser wiring

The validator is invoked from `_fallback_parse` **after** the
`[PIPES]`, `[PUMPS]`, and `[VALVES]` loops have all run, just
before the parse-time demand rebalancing. This guarantees:

* Every link id registered in the file is in `seen_edge_ids` by
  the time `_validate_status_rows` runs.
* `[STATUS]` may appear anywhere in the file (before, after, or
  interleaved with the link sections) and still validate against
  the complete link set.
* The validator runs before the `torch.tensor(...)` Network
  construction, so a `ValueError` aborts the load cleanly.

### `IGNORED_SECTIONS` change

`STATUS` was removed from the frozenset. The Sprint 21 ignored-
section invariance tests still pass because they iterate over
`_TARGET_SECTION_NAMES`, which is the keys of
`_TARGET_SECTION_BODIES`, and that dict never included `STATUS`.
An explicit Sprint 22 regression test
(`test_status_is_not_globally_ignored_after_sprint_22`) pins this
removal so a future sprint that reintroduces global `[STATUS]`
ignoring will trip the test.

The module-level comment block above `IGNORED_SECTIONS` and the
parser's docstring now describe the new Sprint 22 boundary explicitly.

## Fallback parser behaviour

Accepted (no-op — `Network` byte-for-byte identical to no-`[STATUS]`
baseline):

| Row                                  | Behaviour                                                                  |
|--------------------------------------|----------------------------------------------------------------------------|
| `P1 OPEN` (pipe id)                  | Accepted no-op.                                                            |
| `PU1 OPEN` (HEAD-curve pump id)      | Accepted no-op. Pump quadratic `[a0, a1, a2]` is unchanged.                |
| `V1 OPEN` (PRV valve id)             | Accepted no-op. Pressure-boundary surrogate is unchanged.                  |
| `V1 OPEN` (TCV valve id)             | Accepted no-op. Resistance surrogate is unchanged.                         |
| `p1 open` / `P1 Open` / `P1 OpEn`    | Case-insensitive — accepted.                                                |
| `   P1   OPEN  ` (extra whitespace)  | Tokeniser collapses whitespace — accepted.                                 |
| Multiple `OPEN` rows in one block    | Each row validated independently — accepted.                                |
| `[STATUS]` placed before `[PIPES]`   | Validation runs after all link sections — accepted.                         |
| `[STATUS]` placed after `[PIPES]`    | Accepted.                                                                    |
| Empty `[STATUS]\n` (no rows)         | Accepted (validator iterates zero rows).                                    |

Rejected (`ValueError`):

| Row                              | Error message contains                                                                  |
|----------------------------------|-----------------------------------------------------------------------------------------|
| `P1` (single token)              | `[STATUS]`, `at least 2 tokens`.                                                        |
| `QQQ_unknown OPEN`               | `[STATUS]`, `QQQ_unknown`, `unknown link id`.                                           |
| `P1 CLOSED`                      | `[STATUS]`, `P1`, `CLOSED`, "models only OPEN links".                                   |
| `P1 closed` (case-folded)        | `[STATUS]`, `P1`, original-case `closed`, "models only OPEN links".                     |
| `P1 CV`                          | `[STATUS]`, `P1`, `CV`.                                                                  |
| `PU1 1.0`                        | `[STATUS]`, `PU1`, `1.0`, "numeric pump speed/status".                                  |
| `PU1 0`                          | `[STATUS]`, `PU1`, "numeric pump speed/status".                                         |
| `P1 MAYBE_LATER`                 | `[STATUS]`, `P1`, `MAYBE_LATER`, "only accepted token is OPEN".                         |
| `P1 OPEN \n P2 CLOSED`           | Fails on the `P2 CLOSED` row.                                                            |

`[PIPES] ... CLOSED` / `CV` per-row status column still raises in
the pipe-row loop exactly as it did from Sprint 11 onwards. Sprint
22 only adds standalone `[STATUS]`-section handling.

## WNTR behaviour

The WNTR back-end (`_wntr_parse`) is **structurally unchanged** by
Sprint 22:

* WNTR has its own `[STATUS]` parser. It validates link references
  against the network's link set internally (raising at the
  `WaterNetworkModel(...)` constructor for unknown ids), applies
  any `CLOSED` / `OPEN` semantics to its internal link state, and
  then exposes the pipe / pump / valve lists unchanged.
* The dPHM WNTR adapter reads `wn.pipe_name_list`,
  `wn.pump_name_list`, and `wn.valve_name_list` plus the basic
  geometric / pump-curve / valve-setting attributes — it does not
  re-validate `[STATUS]` from the source file.
* The fallback parser is therefore the **authoritative path** for
  Sprint 22 `[STATUS]` behaviour. Documented in
  `docs/epanet-inp-import.md` ("Explicit `[STATUS]` no-op rows
  (Sprint 22)" → "What Sprint 22 does NOT do").
* The optional WNTR parity tests from Sprints 13–21 (HEAD pump,
  POWER pump, PRV, TCV, demand multiplier) **remain green** — no
  Sprint 22 change touches those fixtures.
* The new
  `test_wntr_smoke_status_open_does_not_break_back_end` smoke
  check confirms that adding `[STATUS] P1 OPEN` to the Sprint 21
  loop fixture does not perturb demand sums / node counts / edge
  counts across the two back-ends. It guards with
  `pytest.importorskip("wntr")` so it skips cleanly without WNTR.

WNTR is currently installed (`wntr==1.4.0` per the environment
contract); the smoke test passes against the live WNTR back-end.

## Test/invariance evidence

`tests/dphm/test_inp_status.py` — 29 tests:

* `test_status_no_longer_in_ignored_sections` — public surface.
* `test_status_open_on_pipe_is_no_op` — byte-for-byte invariance
  on the Sprint 21 loop fixture.
* `test_status_open_on_pump_is_no_op` — byte-for-byte invariance
  on the HEAD-curve pump fixture.
* `test_status_open_on_prv_valve_is_no_op` — byte-for-byte
  invariance on the PRV pressure-boundary surrogate.
* `test_status_open_on_tcv_valve_is_no_op` — byte-for-byte
  invariance on the TCV resistance surrogate.
* `test_status_token_is_case_insensitive[OPEN|open|Open|OpEn]` —
  4 parametrised tests.
* `test_status_extra_whitespace_is_tolerated`.
* `test_status_multiple_open_rows_accepted`.
* `test_status_before_pipes_section_validates_against_known_links`
  — `[STATUS]` ordered before `[PIPES]`.
* `test_status_after_link_sections_still_validates`.
* `test_status_unknown_link_id_raises`.
* `test_status_short_row_raises`.
* `test_status_closed_token_raises`.
* `test_status_closed_token_is_case_insensitive_for_rejection`.
* `test_status_cv_token_raises`.
* `test_status_numeric_pump_speed_raises` (`1.0`).
* `test_status_numeric_zero_speed_raises` (`0`).
* `test_status_arbitrary_token_raises`.
* `test_status_open_then_closed_raises_on_the_closed_row`.
* `test_pipes_row_closed_status_column_still_raises` — Sprint 11
  behaviour preserved.
* `test_pipes_row_cv_status_column_still_raises` — Sprint 11
  behaviour preserved.
* `test_controls_still_ignored_alongside_status` — Sprint 21
  limitation preserved.
* `test_rules_still_ignored_alongside_status` — Sprint 21
  limitation preserved.
* `test_head_pump_coefficients_unaffected_by_status_open_on_pump`
  — confirms `[CURVES]` HEAD-curve fit is unaffected by an
  accepted `[STATUS] PU1 OPEN` row.
* `test_empty_status_section_is_accepted`.
* `test_wntr_smoke_status_open_does_not_break_back_end` —
  `pytest.importorskip("wntr")`.

`tests/dphm/test_inp_ignored_sections.py` — added 1 test:

* `test_status_is_not_globally_ignored_after_sprint_22` — pins
  that `STATUS` is not in `IGNORED_SECTIONS`.

All other Sprint 11–21 tests in the package remain unchanged and
green:

* Loop, pump (HEAD), POWER pump, PRV / TCV fixtures still load.
* SI / GPM unit-system invariants preserved.
* Pressure / demand-multiplier / specific-gravity / viscosity
  resolvers still resolve / validate.
* Sprint 21 ignored-section invariance still holds (every target
  section in `_TARGET_SECTION_NAMES` still load-invariant; the
  `_TARGET_SECTION_BODIES` dict never named `STATUS`).
* `[PIPES]` row-status `CLOSED` / `CV` rejection still raises.
* `[CONTROLS]` / `[RULES]` still no-ops.
* `[CURVES]` HEAD-curve consumption still active.

## Validation commands and results

```
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
930 passed, 1 skipped, 3 warnings in 104.05s

$ python -m pytest tests -q
938 passed, 1 skipped, 3 warnings in 113.01s

$ python -m compileall src tests
(no errors; exit 0)

$ git status --short
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/inp_io.py
 M tests/dphm/test_inp_ignored_sections.py
?? tests/dphm/test_inp_status.py
```

Comparison with Sprint 21 baselines:

| Metric                       | Sprint 21    | Sprint 22    | Delta            |
|------------------------------|--------------|--------------|------------------|
| Targeted pytest passed       | 900          | 930          | +30 tests        |
| Targeted pytest skipped      | 1            | 1            | unchanged        |
| Full pytest passed           | 908          | 938          | +30 tests        |
| Full pytest skipped          | 1            | 1            | unchanged        |
| compileall                   | clean        | clean        | unchanged        |

The +30 figure is the 29 new tests in `test_inp_status.py` plus
the 1 new test in `test_inp_ignored_sections.py`.

The 1 skipped test (`test_wntr_optional_import.py:371`) is the
pre-existing Sprint 11 fixture that asserts the `ImportError` path
when WNTR is **not** installed — it is `pytest.skip(...)`-ed when
WNTR is present (as here). Sprint 22 does not touch it.

## Compatibility notes

* **Backwards-compatible** for every fixture that did not declare a
  `[STATUS]` section. The Sprint 21 ignored-section invariance is
  preserved (`_TARGET_SECTION_BODIES` does not include `STATUS`).
* **Backwards-compatible** for every fixture that already declared
  per-row `OPEN` status on `[PIPES]` (the existing column-7
  check in the pipe loop is untouched).
* **Backwards-compatible** for every Sprint 11–21 shipped fixture
  under `docs/examples/`. None declare a standalone `[STATUS]`
  section. Inspection confirms no shipped fixture mentions
  `[STATUS]`.
* **Backwards-incompatible** only for previously-undocumented
  fixtures that declared `[STATUS] ... CLOSED` / `CV` / numeric /
  arbitrary tokens and were relying on Sprint 21's silent
  swallowing. Those fixtures now fail loudly. This is the
  intended behaviour change — the Sprint 22 contract is "no
  pretending to implement closed-link physics".
* `IGNORED_SECTIONS` no longer contains `"STATUS"`. External code
  that imported the constant to introspect the no-op contract will
  now correctly report `STATUS` as not-no-op. The `frozenset`
  immutability and `_IGNORED_SECTIONS` private alias are
  preserved.
* The WNTR adapter is structurally unchanged.

## Known limitations

Sprint 22 does **not**:

* Model closed pipes / pumps / valves. `[STATUS] P1 CLOSED` raises.
* Model check valves. `[STATUS] P1 CV` raises. The Sprint 11
  per-row `[PIPES] ... CV` rejection is preserved unchanged.
* Model pump speed multipliers from `[STATUS]`. Numeric tokens
  raise. The static nominal speed `s = 1` consumed by
  `fit_pump_head_curve` is the only pump-speed convention the
  current core supports.
* Activate `[CONTROLS]` or `[RULES]`. Both remain Sprint 21-style
  silent no-ops with the documented limitation that control-state
  logic is deferred.
* Add `[PATTERNS]` time-varying demand support, `[ENERGY]` parsing,
  Darcy-Weisbach head loss, real EPANET runtime / WNTR-simulator
  coupling, dPL parameter learning, ONNX / TensorRT / Jetson
  deployment, PLC / PAC / SCADA adapters, write / control path,
  or any production / savings claim. Each of those is explicitly
  deferred per the Sprint 22 scope boundary.
* Add an `[OPTIONS] STATUS` or per-link runtime override. The
  steady-state core is stateless across loads.
* Validate `[STATUS]` from the WNTR adapter. The WNTR back-end
  trusts WNTR's own `[STATUS]` parser (which may apply different
  semantics — see WNTR documentation). The fallback parser is
  authoritative for Sprint 22 `[STATUS]` behaviour.

The hydraulic boundary diagram in `docs/safety-boundary.md` is
unchanged: this loader is topology import only.

## Verdict

**APPROVED**.

All Sprint 22 hard approval gates are satisfied:

* targeted pytest exit 0 — 930 passed / 1 skipped.
* full pytest exit 0 — 938 passed / 1 skipped.
* compileall exit 0 — clean.
* `SPRINT22_REPORT.md` exists (this file).
* `[STATUS] OPEN` no-op behaviour is tested for pipes (`test_status_open_on_pipe_is_no_op`), HEAD-curve pumps (`test_status_open_on_pump_is_no_op`), PRV valves (`test_status_open_on_prv_valve_is_no_op`), and TCV valves (`test_status_open_on_tcv_valve_is_no_op`).
* Status-changing tokens reject clearly: `CLOSED`, `CV`, numeric (`1.0`, `0`), arbitrary token (`MAYBE_LATER`).
* Unknown link ids reject clearly (`test_status_unknown_link_id_raises`).
* `STATUS` ignored-surface change is documented in `docs/epanet-inp-import.md` and tested (`test_status_is_not_globally_ignored_after_sprint_22`, `test_status_no_longer_in_ignored_sections`).
* `[CONTROLS]` / `[RULES]` remain ignored (`test_controls_still_ignored_alongside_status`, `test_rules_still_ignored_alongside_status`).
* Existing SI / GPM / pressure / demand / SG / viscosity / ignored-section fixture behaviour passes (Sprint 11–21 test suite green).
* HEAD pump tests pass (`tests/dphm/test_inp_pump_curves.py` + Sprint 22 invariance checks).
* POWER pump tests pass (`tests/dphm/test_inp_power_pump.py`).
* PRV / TCV valve tests pass (`tests/dphm/test_inp_valves.py` + Sprint 22 invariance checks).
* WNTR optional tests pass cleanly with WNTR installed; the Sprint 22 smoke check uses `pytest.importorskip`.
* WNTR HEAD / POWER / PRV / TCV / demand-multiplier parity from Sprints 13–21 still passes (no Sprint 22 change touches the WNTR adapter).
* WNTR asymmetry around `[STATUS]` documented in `docs/epanet-inp-import.md` ("What Sprint 22 does NOT do") and `SPRINT22_REPORT.md`.
* No new secrets / credentials / tokens introduced.
* `git status` contains only the four intended Sprint 22 changes.

## Sprint 23 recommendation

Add fallback support for the optional EPANET `[STATUS]` *pump-status*
token vocabulary at the **read-only diagnostic level** — i.e. record
which pumps an EPANET fixture would have shut off at start, surface
that information through a diagnostics structure on the loaded
`Network`, but continue to reject numeric speed multipliers and
unsupported tokens with `ValueError`. This is a strict superset of
the Sprint 22 contract: every Sprint 22 accepted row still loads
identically, and every Sprint 22 rejection still raises — Sprint 23
only widens the surface to *expose* what the EPANET source declared,
not to act on it. A minimal Sprint 23 deliverable would be:

1. A new optional field `epanet_status_diagnostics` on the `Network`
   dataclass (or a sibling structure returned from
   `load_network_from_inp` via an optional kwarg) containing a list
   of `(link_id, status_token)` pairs the fixture declared.
2. Round-trip JSON serialisation through the existing dataio
   surfaces, so analysts can see "EPANET would have shut `PU1` at
   start" without the dPHM solver acting on it.
3. Hard rejection of closed-link / check-valve / numeric tokens
   preserved (so the steady-state physics boundary is unchanged).
4. Documentation updated to make the read-only nature explicit.

This is the smallest next step that adds analyst-facing value
without breaking the steady-state physics boundary. Closed-link
modelling, check-valve modelling, and active `[CONTROLS]` /
`[RULES]` logic remain deferred until a follow-on sprint that
adds the core hydraulic primitives required (signed unilateral
edges for CV, link-disable masks for CLOSED, scheduler /
state-machine for active controls).

Sprint 23 must continue the Sprint 22 boundary: parser-only,
fail-fast on unsupported semantics, no new hydraulic physics, no
WNTR-adapter changes that compromise Sprint 13–21 parity, no
production / savings claims, no internet downloads during tests.
