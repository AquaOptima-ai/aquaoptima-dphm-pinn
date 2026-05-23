# Sprint 19 Report — EPANET `[OPTIONS] Specific Gravity` Parsing

## Goal

Add fallback EPANET `[OPTIONS] Specific Gravity` parsing and propagate
the resulting density ratio through the two places where fluid density
actually matters in the current importer / surrogates:

1. PRV pressure-unit conversion (`pressure -> metres of fluid head`)
   for true pressure units (`PSI`, `KPA`, `BAR`); and
2. POWER pump surrogate (`H_nom = P / (rho_water * sg * g * Q_nom)`).

Sprint 19 stays a parser / unit-conversion sprint. No new hydraulics,
no EPANET runtime, no control / write path.

## Files changed

| File                                                              | Change                                                                    |
|-------------------------------------------------------------------|---------------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                                   | Sprint 19 SG resolver, parser propagation, helper SG argument.            |
| `tests/dphm/test_inp_specific_gravity.py`                         | New — 86 Sprint 19 tests (SI, US, error surface, invariants, WNTR).       |
| `tests/dphm/test_inp_power_pump.py`                               | Updated `test_surrogate_diagnostics_shape` for the new `specific_gravity` |
|                                                                   | diagnostic key (default 1.0 preserves Sprint 14 numerics).                |
| `docs/epanet-inp-import.md`                                       | New "Specific gravity (Sprint 19)" section; header + sections table.      |
| `SPRINT19_REPORT.md`                                              | New — this file.                                                          |

No new fixtures were shipped. Sprint 19 SG behaviour is fully exercised
through tmp-path INP fixtures, which keep the SG surface auditable
without growing `docs/examples/` (which is already at ten files).

## Specific gravity — design

- `resolve_specific_gravity(opts: dict[str, str]) -> float` is the
  public helper (mirrors the Sprint 18 `resolve_demand_multiplier`
  shape).
- Default `1.0` when the directive is absent or empty (pure water).
- Accepts any strictly-positive finite value.
- Raises `ValueError` with a clear message on zero, negative,
  non-finite, or non-numeric input.
- The directive's option key is two whitespace-separated tokens
  (`Specific Gravity`); the fallback `_parse_options` collapses extra
  whitespace and accepts any case-insensitive spelling, mirroring the
  Sprint 18 `Demand Multiplier` precedent.

Constants:

- `_SPECIFIC_GRAVITY_KEY = "SPECIFIC GRAVITY"` — canonical map key.
- `_DEFAULT_SPECIFIC_GRAVITY = 1.0`.
- `_TRUE_PRESSURE_UNITS = frozenset({"PSI", "KPA", "BAR"})` — the units
  whose PRV conversion depends on density.

## Pressure conversion behaviour

- For `[OPTIONS] Pressure` of `PSI`, `KPA`, or `BAR`:
  ```
  prv_setting_to_m = pressure_to_head_m / specific_gravity
  head_m = pressure_value * prv_setting_to_m
  ```
  For `sg = 2.0`, the metres of fluid head are exactly half the metres
  of water head; for `sg = 0.5`, exactly double.
- For `[OPTIONS] Pressure` of `METERS`, `M`, `FEET`, `FT`: the
  conversion is a pure length conversion and is **not** divided by
  `sg`. These aliases are already metres / feet of head.
- For the default no-`Pressure` path (Sprint 16 contract): PRV
  settings follow the flow-unit family's `head_to_m` (metres for SI,
  feet for US) and are **not** scaled by `sg`. SG only affects
  *pressure-to-head* conversions; flow-unit family head conversions
  are length conversions.

## POWER pump behaviour

- `fit_power_pump_surrogate` gains a keyword-only argument
  `specific_gravity: float = 1.0`. The default preserves Sprint 14
  numerics byte-for-byte.
- Internally, the surrogate computes:
  ```
  rho_eff = rho_water * specific_gravity
  H_nom   = P_watts / (rho_eff * g * Q_nom)
  a0      = shutoff_multiplier * H_nom
  a2      = (H_nom - a0) / Q_nom**2
  ```
  Therefore `sg = 2.0` halves `H_nom`, `a0`, and `|a2|`; `sg = 0.5`
  doubles them.
- The diagnostics dict gains a new `specific_gravity` entry.
- Validation extended to reject zero, negative, NaN, and Inf values
  (same surface as `resolve_specific_gravity`).
- The fallback parser passes `specific_gravity=` into the helper from
  the parsed options map, so the parser path and the helper path
  produce identical surrogate coefficients on the same SG input.

## Fallback parser behaviour

- Parses `Specific Gravity` as a two-word key, case- and
  whitespace-tolerant.
- Applies SG to PRV pressure-unit conversion **only** for `PSI`,
  `KPA`, `BAR`.
- Does **not** apply SG to:
  - PRV settings under `Pressure METERS/M/FEET/FT`,
  - PRV settings under the default no-Pressure path,
  - TCV settings or the `MinorLoss` column,
  - pipe / pump / valve / tank / reservoir / junction dimensions,
  - HEAD pump curve coefficients,
  - junction demands (Demand Multiplier remains the orthogonal
    demand-scaling axis).
- Applies SG to the POWER pump surrogate (downstream-demand-anchored;
  identical to Sprint 18, with `specific_gravity=` threaded through).

## WNTR behaviour

WNTR's handling of `[OPTIONS] Specific Gravity` has shifted across
releases (it may be stored under `wn.options.hydraulic.specific_gravity`
in some versions, ignored in others, or applied internally during
simulation). To avoid double-conversion or hidden discrepancies,
Sprint 19 **leaves the WNTR adapter structurally unchanged**:

- The fallback parser is authoritative for Sprint 19 SG behaviour.
- All Sprint 11–18 WNTR parity (HEAD / POWER / PRV / TCV / demand
  multiplier) remains green; the targeted suite reports
  767 passed / 1 skipped with WNTR 1.4.0 installed.
- A new optional WNTR parity test in
  `tests/dphm/test_inp_specific_gravity.py` covers the existing
  Sprint 17 GPM+PSI PRV fixture (no SG directive — defaults to 1.0)
  and the SI loop fixture; tolerance on the PSI fixture is
  intentionally loose (~5 cm of head) because WNTR uses its own
  internal PSI conversion that diverges from our NIST-exact constant
  by ~0.01 m. This is a pre-existing WNTR discrepancy, not a
  Sprint 19 regression.

`docs/epanet-inp-import.md` documents the WNTR ambiguity explicitly
under "Specific gravity (Sprint 19) → WNTR adapter behaviour" and
adds an entry to the Roadmap.

## Test / solve / scaling evidence

86 new tests in `tests/dphm/test_inp_specific_gravity.py`, organised
into the following groups:

- `resolve_specific_gravity` defaults and validation (8 tests).
- Two-word option key case / whitespace tolerance (5 tests).
- Parser rejects invalid SG values with clear messages (7 tests).
- PRV `PSI`/`KPA`/`BAR` scaled by SG (15 parametrised cases × 5 SG
  values = 15 actual tests).
- PRV PSI default `sg = 1.0` matches Sprint 17 numerics exactly.
- PRV PSI `sg = 2.0` halves the head and `sg = 0.5` doubles it.
- PRV `METERS`/`M`/`FEET`/`FT` unaffected by SG (4 directives ×
  3 SG values = 12 cases).
- Default no-`Pressure` PRV behaviour unaffected by SG (SI + US).
- `fit_power_pump_surrogate` SG scaling (5 SG values; reflects the
  documented `1 / sg` relationship on `a0` and `a2`).
- `fit_power_pump_surrogate` rejects invalid SG (zero, negative,
  NaN, Inf).
- Fallback parser POWER pump SG scaling (3 SG values, plus the
  default no-SG case).
- POWER pump `sg = 2.0` halves `a0`; `sg = 0.5` doubles `a0`.
- POWER pump network with `sg = 2.0` solves under Newton-analytic.
- HEAD pump curve coefficients unaffected by SG.
- TCV surrogate length / diameter / c_factor unaffected by SG.
- Reservoir head, tank initial water surface, junction elevations
  unaffected by SG.
- Pipe geometry (length / diameter / c_factor) unaffected by SG.
- Demand multiplier behaviour independent of SG; combined directive
  test confirms both two-word keys parse together cleanly.
- Sprint 11 / 16 / 17 SI loop, GPM loop, and GPM+PSI PRV fixtures
  preserved byte-for-byte (no SG directive → SG defaults to 1.0).
- Sprint 14 POWER pump fixture still loads with a positive shut-off
  head.
- Optional WNTR parity tests (gated by `pytest.importorskip("wntr")`).

## Tests added / updated

Added:
- `tests/dphm/test_inp_specific_gravity.py` (86 tests).

Updated:
- `tests/dphm/test_inp_power_pump.py::test_surrogate_diagnostics_shape`
  — the diagnostics dict now contains the new `specific_gravity`
  entry. Default value asserted as `1.0`, so Sprint 14 numerics are
  preserved on every other key.

## Validation commands and results

```bash
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
767 passed, 1 skipped, 3 warnings in 89.32s

$ python -m pytest tests -q
775 passed, 1 skipped, 3 warnings in 86.69s

$ python -m compileall src tests
(clean — no SyntaxErrors reported)

$ git status --short
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/inp_io.py
 M tests/dphm/test_inp_power_pump.py
?? SPRINT19_REPORT.md
?? tests/dphm/test_inp_specific_gravity.py
```

The single `SKIPPED` test is the pre-existing
`tests/dphm/test_wntr_optional_import.py::test_wntr_unavailable_message`
guard, which intentionally skips when WNTR is installed.

## Compatibility notes

- `fit_power_pump_surrogate`'s default `specific_gravity=1.0`
  preserves Sprint 14 numerics byte-for-byte on every call site that
  does not pass the argument. Inspecting the existing diagnostics
  dict shape changes by one new key (`specific_gravity`), which is
  accounted for in the updated Sprint 14 test.
- `resolve_specific_gravity` follows the same defensive shape as
  `resolve_demand_multiplier`: the resolver itself is consumed
  directly by tests, and the fallback parser invokes it once per
  load.
- The fallback parser's two-word option key handling is now shared
  between `Demand Multiplier` and `Specific Gravity`; the canonical
  storage keys (`"DEMAND MULTIPLIER"`, `"SPECIFIC GRAVITY"`) keep
  the options map flat and inspectable.
- WNTR back-end behaviour is preserved on every Sprint 11–18 fixture.
- The Sprint 11 / 16 / 17 / 18 shipped fixtures are unchanged and
  load with identical demands, fixed-head values, and pump / valve
  coefficients (no `Specific Gravity` directive in any of them).
- The exported public surface gains `resolve_specific_gravity` in
  `aquaoptima.dphm.inp_io.__all__`. (Like `resolve_demand_multiplier`
  before it, it is not re-exported from the top-level
  `aquaoptima.dphm` package — direct import from `inp_io` follows the
  Sprint 18 precedent.)

## Known limitations

- **No WNTR-side SG translation.** Documented in
  `docs/epanet-inp-import.md` and listed in the roadmap. WNTR-loaded
  networks with `[OPTIONS] Specific Gravity` may show subtly different
  PRV fixed-head and POWER pump `a0` values depending on the WNTR
  release; the fallback parser is authoritative for Sprint 19.
- **No `Specific Gravity` shipped fixture.** Sprint 19 covers the SG
  surface with tmp-path fixtures only, to keep `docs/examples/` small.
- **No new hydraulics.** SG affects only the two density-dependent
  conversions described above; the dPHM solver, residuals, and
  feasibility logic are unchanged.
- **POWER pump remains a bounded surrogate.** SG scales the surrogate
  uniformly but the underlying `H = P / (rho_eff g Q)` hyperbola is
  still approximated by a single-point-anchored droop quadratic.
- **Active valve / control physics remains out of scope.** PRV
  pressure-boundary surrogate semantics are unchanged; SG only
  changes the *value* of the boundary head for PSI/KPA/BAR
  declarations.
- **No `Specific Gravity` interaction with `[ENERGY]`, `[PATTERNS]`,
  or any time-varying state.** All of those remain out of scope per
  Sprint 19's hard scope boundaries.

## Verdict

**APPROVED.**

All Sprint 19 hard gates met:

- Targeted pytest: 767 passed, 1 skipped (pre-existing WNTR-install
  skip).
- Full pytest: 775 passed, 1 skipped.
- compileall: clean.
- `SPRINT19_REPORT.md` written.
- `resolve_specific_gravity` exercised by 8 dedicated unit tests
  plus integration through the parser.
- PRV `PSI`/`KPA`/`BAR` + SG scaling proven across 15 parametrised
  cases.
- POWER pump SG scaling proven via both the helper directly and
  through the fallback parser (network-level evidence on `a0`).
- HEAD pump curves unaffected by SG (parametric comparison).
- TCV settings / effective resistance unaffected by SG.
- Default no-SG / no-`Pressure` path preserved byte-for-byte.
- Demand multiplier behaviour preserved and independent of SG.
- Sprint 11 / 16 / 17 / 18 fixtures unchanged.
- HEAD pump tests still pass; POWER pump tests still pass; PRV / TCV
  valve tests still pass.
- WNTR optional tests pass cleanly (with documented loose tolerance
  on the WNTR PSI constant).
- No secret files / strings introduced.
- `git status` contains only Sprint 19 changes.

Additional WNTR-installed gates met:

- Sprint 13 HEAD parity unchanged.
- Sprint 14 POWER parity unchanged.
- Sprint 15 PRV / TCV parity unchanged.
- Sprint 18 demand-multiplier WNTR parity still passes.
- WNTR ambiguity around `Specific Gravity` is documented in
  `docs/epanet-inp-import.md` and called out in the Known
  limitations section above.

## Sprint 20 recommendation

**Recommended Sprint 20 focus: fallback EPANET `[OPTIONS] Viscosity`
parsing**, in the same shape as Sprint 19 SG:

- Add `resolve_viscosity(opts) -> float` mirroring the Sprint 19
  resolver (default `1.0` for water at 20 °C as a dimensionless ratio
  to reference kinematic viscosity, validated strictly positive and
  finite).
- Document why the dPHM Hazen-Williams core is *insensitive* to
  viscosity: the H-W headloss model has no viscosity term, so the
  directive cannot directly scale anything in the residual. The
  Sprint 20 deliverable is parsing + documentation + a test that
  asserts the directive parses cleanly and that all hydraulic
  outputs remain numerically unchanged.
- This deliberately matches the Sprint 18 / 19 cadence (parse-then-
  propagate-where-meaningful) and keeps the scope bounded — viscosity
  is the natural next `[OPTIONS]` directive after `Specific Gravity`
  in the EPANET 2.2 manual.
- Defer to a future sprint: introducing a Darcy-Weisbach branch where
  viscosity would matter, time-varying `[PATTERNS]`, `[ENERGY]`
  parsing, and any WNTR-side SG/Viscosity translation work.

This keeps Sprint 20 a parser sprint, just like Sprints 17 / 18 / 19,
and avoids leaping into hydraulics changes before the entire
`[OPTIONS]` surface is auditable end-to-end.
