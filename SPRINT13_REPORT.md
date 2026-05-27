# Sprint 13 Report — WNTR Pump-Curve Parity

## Goal

Bring the optional WNTR-backed EPANET `.inp` loader into parity with
the Sprint 12 fallback parser for HEAD-curve pumps, while keeping
WNTR optional and the default test suite deterministic.

## Verdict

**APPROVED.**

All Sprint 13 hard approval gates pass. WNTR was installed during
this run, so the additional WNTR-installed gates were exercised in
addition to the WNTR-absent gates.

## Files changed

| Path | Kind | Note |
|------|------|------|
| `src/aquaoptima/dphm/inp_io.py` | edit | Added `_wntr_extract_pump_curve_points` and `_wntr_translate_pump` helpers; widened `_wntr_parse` to translate HEAD-curve pumps and rebalance demand for parity with the fallback parser; updated module docstring. |
| `tests/dphm/test_wntr_pump_helpers.py` | new | 16 helper unit tests against duck-typed fake WNTR pump/curve objects (no WNTR import). |
| `tests/dphm/test_wntr_optional_import.py` | edit | Replaced the Sprint 12 "WNTR refuses pumps" test with Sprint 13 pump-parity, solver, and unsupported-form tests. |
| `docs/epanet-inp-import.md` | edit | Documented the WNTR pump path, the SI-unit assumption, the WNTR API surface used, and the Sprint 13 fixture parity expectations. |
| `SPRINT13_REPORT.md` | new | This report. |

## WNTR pump translation design

The translation is split into two new helpers in
`src/aquaoptima/dphm/inp_io.py`:

- `_wntr_extract_pump_curve_points(pump) -> list[(Q, H)]` — touches
  only the stable WNTR public surface (`pump.pump_type`,
  `pump.get_pump_curve()`, `Curve.points`, `Curve.curve_type`) and
  returns SI-unit points. Non-HEAD pump forms (`POWER`, anything
  else) raise a clear `ValueError`. Defensive against:
  - missing `pump_type`,
  - missing or non-callable `get_pump_curve`,
  - `get_pump_curve()` raising,
  - a `Curve.curve_type` that exists but is not `"HEAD"`,
  - an empty `points` list,
  - a malformed point tuple.
- `_wntr_translate_pump(pump) -> (coeffs, base_speed, diag)` — calls
  the extractor and reuses **the same** `fit_pump_head_curve` helper
  the fallback parser uses, so coefficients are numerically
  identical for the same SI-unit curve points. `base_speed` defaults
  to `1.0` if missing, non-finite, or non-positive.

`_wntr_parse` now iterates `wn.pump_name_list`, calls the translator
for each pump, and appends the resulting pump edge after the pipes —
matching the fallback parser's `[pipes…, pumps…]` edge ordering. The
demand-rebalance step is also mirrored from the fallback parser so
loaded networks have `sum(demands) ≈ 0` regardless of back-end.

## WNTR API assumptions and defensive handling

The adapter touches only attributes/methods that have been stable
in WNTR for several releases:

| WNTR surface                              | Use                                                        |
|-------------------------------------------|------------------------------------------------------------|
| `wn.pump_name_list`                       | Iterate pumps                                              |
| `wn.get_link(name)`                       | Resolve a pump by name                                     |
| `pump.start_node_name` / `.end_node_name` | Edge endpoints                                             |
| `pump.pump_type`                          | `"HEAD"` / `"POWER"` discrimination (string)               |
| `pump.get_pump_curve()`                   | Returns a `Curve` for HEAD-curve pumps                     |
| `pump.base_speed`                         | Static nominal speed, defaults to `1.0` on bad values      |
| `Curve.points`                            | List of `(Q, H)` tuples in SI                              |
| `Curve.curve_type`                        | Sanity check — must be `"HEAD"` when present               |
| `wn.valve_name_list`                      | Reject valves                                              |

All access is via `getattr(..., default)` or `hasattr` so that
slight WNTR-version differences (e.g. older Curves lacking
`curve_type`) degrade gracefully. The helpers are pure Python and
do not import WNTR, so they are unit-testable without WNTR
installed.

## Unit conversion behavior

The crucial difference between the two parser back-ends:

- **Fallback parser**: reads raw INP text, applies the
  `[OPTIONS] Units` flow-unit factor (`LPS → 1e-3`, etc.) to curve
  X-values before fitting.
- **WNTR parser**: trusts WNTR's internal SI conversion. When
  `WaterNetworkModel(inp_path)` loads a file, WNTR normalises all
  hydraulic quantities to SI (junction `base_demand` in m³/s,
  reservoir `base_head` in m, `Curve.points` in `(m³/s, m)`). The
  WNTR adapter therefore **does not** apply a second conversion;
  doing so would double-convert and produce nonsense coefficients.

This is documented in `docs/epanet-inp-import.md` under
"Unit conversion in the WNTR path".

The on-disk shipped fixture `docs/examples/epanet_reference_pump.inp`
uses `LPS` flow units. Live numerical check:

```
fallback pump coeffs: [45.0, ≈0, -800.0]
wntr     pump coeffs: [45.0, ≈0, -800.0]      (agreement to ~1e-6 a0/a1, ~1e-3 a2)
fallback demands sum: 0.0    wntr demands sum: 0.0
```

## Tests added / updated

### Added — `tests/dphm/test_wntr_pump_helpers.py` (16 tests, no WNTR import required)

`_wntr_extract_pump_curve_points`:
- returns SI points unchanged (no double-conversion),
- accepts a Curve with `curve_type=None`,
- rejects non-HEAD `curve_type` (e.g. `"EFFICIENCY"`),
- rejects a `POWER` pump,
- rejects an unknown `pump_type` (e.g. `"LINEAR"`),
- rejects a pump missing `pump_type`,
- rejects a pump missing `get_pump_curve`,
- rejects an empty curve,
- rejects a malformed point tuple,
- propagates errors from `get_pump_curve()` as a `ValueError`.

`_wntr_translate_pump`:
- matches `fit_pump_head_curve` output on the same SI points,
- preserves a non-unity `base_speed`,
- defaults `base_speed` to `1.0` when missing,
- defaults `base_speed` to `1.0` on non-finite values,
- defaults `base_speed` to `1.0` on negative values,
- propagates fit errors (e.g. too-few points).

### Updated — `tests/dphm/test_wntr_optional_import.py`

Replaced the Sprint 12 "WNTR refuses pumps" test with Sprint 13
parity coverage (all gated by `pytest.importorskip("wntr")`):

- shipped pump fixture loads via `parser="wntr"` and has exactly
  one pump edge,
- WNTR and fallback parser pump coefficients agree on the shipped
  fixture (tight absolute tolerances),
- WNTR-loaded pump fixture solves with
  `newton_solve(jacobian_mode="analytic")` to `residual_norm < 1e-8`,
- WNTR and fallback solved heads/flows agree to `1e-6` absolute,
- WNTR adapter rejects a `POWER` pump with a clear `ValueError`,
- existing Sprint 11 loop-fixture parity and solver tests retained.

The Sprint 11 negative test `test_wntr_parser_explicit_raises_importerror_when_missing`
is retained — it skips when WNTR is installed and runs when WNTR is
absent.

### Unchanged but still passing

- `tests/dphm/test_inp_pump_curves.py` — fallback pump-parser tests
  from Sprint 12 (all 22 tests pass).
- `tests/dataio/test_inp_pump_telemetry.py` — analytic-Newton solve
  and physics-consistent telemetry on the fallback path (all pass).
- Every other test in `tests/{dphm,models,training,dataio,...}`.

## Validation commands and results

### Run 1 — with WNTR installed (`wntr==1.4.0`)

```bash
python -m pip install -e .                                        # OK
python -m pytest tests/dphm tests/models tests/training tests/dataio -q
#   441 passed, 1 skipped, 3 warnings
python -m pytest tests -q
#   449 passed, 1 skipped, 3 warnings
python -m compileall src tests                                    # OK, exit 0
git status --short
#  M docs/epanet-inp-import.md
#  M src/aquaoptima/dphm/inp_io.py
#  M tests/dphm/test_wntr_optional_import.py
# ?? tests/dphm/test_wntr_pump_helpers.py
# ?? SPRINT13_REPORT.md
```

The 1 skip is the WNTR-absent `ImportError` negative test, which
correctly does not run when WNTR is available.

### Run 2 — verify graceful behaviour with WNTR uninstalled

```bash
python -m pip uninstall -y wntr
python -m pytest tests/dphm/test_wntr_optional_import.py \
                 tests/dphm/test_wntr_pump_helpers.py -v
#   17 passed, 7 skipped
```

All 16 helper tests pass without WNTR; all 7 WNTR-integration tests
skip cleanly via `pytest.importorskip("wntr")`; the WNTR-absent
`ImportError` negative test runs and passes. WNTR was reinstalled
after this verification step.

## Whether WNTR was installed in this environment

WNTR **was** installed in this run (`wntr==1.4.0`, pulled in from
PyPI). The WNTR-installed hard gates were therefore exercised:

- shipped pump fixture loads via `parser="wntr"` ✓
- WNTR / fallback pump coeffs close to within the test tolerances ✓
  (1e-6 abs on `a0`/`a1`, 1e-3 abs on `a2`)
- WNTR-loaded pump fixture solves with analytic Newton
  (`residual_norm < 1e-8`) ✓
- WNTR and fallback solved heads/flows agree to `1e-6` absolute ✓

The WNTR-absent hard gates were also exercised in Run 2.

## Compatibility notes

- Public API surface is unchanged: `load_network_from_inp` and
  `fit_pump_head_curve` keep their existing signatures.
- The fallback parser is byte-for-byte unchanged from Sprint 12 in
  effect — its public output on existing fixtures is identical.
- The WNTR adapter is now strictly broader: previously rejected
  pump-bearing files now succeed (for HEAD-curve pumps). Files that
  previously succeeded still succeed.
- WNTR remains optional. The default install does not depend on it,
  and the default test suite still passes without it (helpers tests
  are pure Python; integration tests skip cleanly).
- Demand-rebalance now also runs in the WNTR path. Existing fixtures
  with at least one fixed-head node (all shipped fixtures) are
  unaffected by the solver — fixed-head node demand drops out of the
  residual — so this is a cosmetic but useful parity fix.

## Known limitations

- Only `HEAD curve_id` pumps are translated by either back-end.
  `POWER`, `LINEAR`, multi-point efficiency, and other pump forms
  still raise `ValueError`. (Carried over from Sprint 12; the
  Sprint 13 widening is the WNTR path, not new pump forms.)
- `speed_pattern_name` is silently ignored — the dPHM core is
  steady-state, so only `base_speed` is consumed.
- US-customary flow units still raise from the fallback parser. The
  WNTR adapter handles US-customary INP files naturally because
  WNTR converts to SI itself.
- The fallback parser still refuses `[VALVES]`; the WNTR adapter
  does too. Valves remain out of scope for the steady-state core.
- No EPANET runtime is exercised; this remains a pure topology
  importer.

## Scope adherence

Within the Sprint 13 boundary:

- No real PLC / PAC / SCADA adapters added.
- No write or control path.
- No dPL parameter learning code.
- No ONNX / TensorRT / Jetson deployment code.
- No real EPANET binary or runtime.
- No internet downloads during tests (the WNTR install was
  preparatory and is documented above; tests do not fetch anything).
- No production / savings claims.
- No broad unit-system rewrite. Only the cosmetic demand-rebalance
  was added to the WNTR path for parity with the fallback parser.
- No Sprint 14 work.

## Sprint 14 recommendation

**Sprint 14 should land WNTR-side translation for non-HEAD pump
forms — most usefully the `POWER` form.** The WNTR adapter currently
raises `ValueError` on `POWER` pumps; widening it would unlock
several common real-world EPANET fixtures (including the EPANET
`Net1` shipped example). A clean entry point already exists:
`_wntr_extract_pump_curve_points` would be paired with a sibling
`_wntr_extract_pump_power` returning the constant-power coefficient,
and `_wntr_translate_pump` would dispatch on `pump_type`. The
fallback parser would gain the same `POWER curve_id`-or-constant
branch in parallel. This is a natural continuation of the
Sprint 12 + Sprint 13 pump-curve work and keeps the back-ends in
lockstep.

Stretch — only if `POWER` lands quickly: route the EPANET `Net1`
sample through `parser="wntr"` as an integration fixture, gated by
the existing `pytest.importorskip` pattern.
