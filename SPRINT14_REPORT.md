# Sprint 14 Report — EPANET POWER pump support via a conservative surrogate

**Branch:** `sprint14`
**Base commit:** `5bcaf28` (Sprint 13, `feat: add wntr pump curve parity`)
**Scope:** Bounded EPANET `POWER` pump support for the `.inp` import
surface (fallback + WNTR) via an explicit, documented, conservative
quadratic surrogate. No SCADA, no real EPANET runtime, no Sprint 15.

## Files changed

```
 M src/aquaoptima/dphm/__init__.py
 M src/aquaoptima/dphm/inp_io.py
 M tests/dphm/test_inp_pump_curves.py
 M tests/dphm/test_wntr_optional_import.py
 M tests/dphm/test_wntr_pump_helpers.py
 M docs/epanet-inp-import.md
?? docs/examples/epanet_reference_power_pump.inp
?? tests/dphm/test_inp_power_pump.py
?? tests/dataio/test_inp_power_pump_telemetry.py
?? SPRINT14_REPORT.md
```

## POWER pump surrogate design

EPANET `POWER` pumps declare a constant shaft power

```
P = rho * g * Q * H   =>   H = P / (rho * g * Q)
```

which is hyperbolic in `Q` and singular at `Q -> 0`. This cannot be
reduced losslessly to the dPHM core's quadratic pump characteristic
`H(Q, s) = a0 s² + a1 s Q + a2 Q²`. Sprint 14 therefore ships a
**bounded, conservative surrogate** rather than a faithful conversion.

### Public helper

```python
aquaoptima.dphm.fit_power_pump_surrogate(
    power_kw: float,
    nominal_flow_m3s: float,
    *,
    shutoff_multiplier: float = 1.5,
) -> (list[float], dict[str, object])
```

### Formula

Given pump power `P` (kW), an anchor flow `Q_nom` (m³/s), and a
shut-off multiplier `m > 1`:

```
P_W   = power_kw * 1000
H_nom = P_W / (rho * g * Q_nom)         # rho=1000, g=9.80665
a0    = m * H_nom
a1    = 0
a2    = (H_nom - a0) / Q_nom²
      = H_nom * (1 - m) / Q_nom²
```

`m > 1` guarantees `a2 < 0` (a drooping centrifugal-style curve).
The surrogate passes through one operating point `(Q_nom, H_nom)`
exactly and remains finite and Newton-stable everywhere.

### Diagnostics

The helper returns `(coeffs, diagnostics)` where `diagnostics` is:

| key                  | meaning                                                  |
|----------------------|----------------------------------------------------------|
| `approximation`      | `"constant_power_surrogate"`                             |
| `power_kw`           | Input shaft power in kW                                  |
| `nominal_flow_m3s`   | Anchor flow used to compute `H_nom`                      |
| `head_at_nominal_m`  | `H_nom = P / (rho * g * Q_nom)`                          |
| `shutoff_head_m`     | `a0 = m * H_nom`                                         |
| `shutoff_multiplier` | The ratio `a0 / H_nom`                                   |
| `a0`, `a1`, `a2`     | Resulting dPHM quadratic coefficients                    |

No `rmse` is exposed because the surrogate is not fitted to multiple
points.

### Validation

- `power_kw <= 0` or non-finite -> `ValueError`.
- `nominal_flow_m3s <= 0` or non-finite -> `ValueError`.
- `shutoff_multiplier <= 1` or non-finite -> `ValueError`.

## Fallback parser behavior

`[PUMPS]` rows of the form `id n1 n2 POWER value` are now recognised
in the fallback parser (Sprint 12 already supported `HEAD curve_id`;
Sprint 14 adds the POWER branch). Concretely:

- The POWER `value` column is read as **kilowatts** (EPANET SI
  convention) and converted to watts internally.
- Non-numeric / non-positive power raises `ValueError` with a
  pump-id-tagged message.
- The nominal-flow anchor is chosen in preference order:
  1. The pump's downstream node's base demand if positive.
  2. The network's total positive demand if positive.
  3. `_POWER_PUMP_DEFAULT_NOMINAL_FLOW = 1e-3` m³/s as a finite
     last-resort anchor (documented in diagnostics).
- The pump edge is appended after pipe edges, with `pump_mask=True`,
  `pipe_mask=False`, `pump_speeds=1.0`, and the surrogate's
  `[a0, a1, a2]` in `pump_coeffs`.
- Existing HEAD curve translation is unchanged.
- `SPEED` and any other pump keyword still raise `ValueError`
  ("unsupported keyword").

## WNTR behavior

`_wntr_translate_pump` routes by `pump.pump_type`:

- `"HEAD"` (Sprint 13) — unchanged. Reuses
  `_wntr_extract_pump_curve_points` + `fit_pump_head_curve`.
- `"POWER"` (Sprint 14) — new path. Reads `pump.power` as **SI
  watts** via the new helper `_wntr_extract_power_pump_kw`, divides
  by 1000 to get kW, then calls `fit_power_pump_surrogate` with the
  same downstream- / total-positive-demand anchor rule the
  fallback parser uses.
- Any other `pump_type` raises `ValueError` via the HEAD-extract
  helper.

`_wntr_extract_power_pump_kw` defensively rejects missing,
non-numeric, non-positive, and non-finite power values.

The unit assumption (WNTR stores `Pump.power` in SI W) is
documented in the helper docstring and `docs/epanet-inp-import.md`.
WNTR HEAD-pump parity from Sprint 13 is preserved.

## Shipped POWER fixture

`docs/examples/epanet_reference_power_pump.inp`:

```
R1 (reservoir, 5 m fixed head)
  --PU1 (POWER, 7.5 kW)--> J1
                            --P1 (200 m, 150 mm, C=130)--> J2 (15 L/s consumer)
```

SI units (`LPS`, H-W headloss). Loads through both fallback and
WNTR back-ends.

### Surrogate evaluation on the fixture

With the default `shutoff_multiplier = 1.5` and the
total-positive-demand anchor `Q_nom = 0.015 m³/s`:

| quantity              | value                  |
|-----------------------|------------------------|
| `H_nom`               | `50.9858 m`            |
| `a0`                  | `76.4787 m`            |
| `a1`                  | `0`                    |
| `a2`                  | `-1.1330e5 m·s²/m⁶`    |

## Solve / telemetry residual evidence

Solver: `newton_solve(net, max_iterations=200, tol=1e-9,
jacobian_mode="analytic")` on the fallback-loaded fixture.

| evidence                          | value                |
|-----------------------------------|----------------------|
| `converged`                       | `True`               |
| `residual_norm`                   | `1.11e-15`           |
| Solved `H[R1, J1, J2]`            | `[5.00, 55.99, 54.87] m` |
| Solved `Q[P1, PU1]`               | `[0.0150, 0.0150] m³/s` |
| Pump gain at solved Q             | `50.99 m`            |
| Per-pump energy residual          | `0.000e+00`          |
| Assembled residual norm           | `1.11e-15`           |

Telemetry: `generate_physics_consistent_telemetry` runs over
6/8-step windows with per-step assembled residual norm `< 1e-3`
(matching the bound the existing HEAD-pump telemetry tests use).
Pump flow remains strictly positive across every telemetry step.

## Tests added/updated

New files:

- `tests/dphm/test_inp_power_pump.py` — 25 tests covering the
  surrogate helper (formula, droop sign, diagnostics shape,
  validation), the fallback parser POWER path, the shipped
  fixture (load + coefficients + demand balance + analytic Newton
  solve + per-pump residual + gain sanity), and POWER row error
  paths (non-numeric, zero, negative, unknown endpoint,
  default-anchor fallback, HEAD-after-POWER interop).
- `tests/dataio/test_inp_power_pump_telemetry.py` — 3 tests on the
  physics-consistent telemetry round-trip for the POWER fixture
  (finite series, per-step residual bound, positive pump flow).

Updated files:

- `tests/dphm/test_inp_pump_curves.py` — the obsolete
  `test_pump_with_unsupported_keyword_raises` now exercises
  `SPEED` instead of `POWER` (POWER is supported from Sprint 14).
- `tests/dphm/test_wntr_optional_import.py` — replaced the
  Sprint 13 `test_wntr_loader_rejects_power_pump_form` with three
  Sprint 14 tests: WNTR POWER acceptance, WNTR POWER fixture
  analytic-Newton solve, and WNTR-vs-fallback POWER surrogate
  agreement on the shipped fixture.
- `tests/dphm/test_wntr_pump_helpers.py` — added 9 tests for the
  new POWER paths: `_wntr_extract_power_pump_kw` validation
  (missing attr, non-numeric, non-positive, non-finite) and
  `_wntr_translate_pump` POWER routing (downstream anchor, total
  positive anchor, default anchor, base-speed preservation,
  non-positive power rejection).

All Sprint 12/13 HEAD pump tests continue to pass unchanged.

## Validation commands and results

```bash
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
481 passed, 1 skipped, 3 warnings in 107.97s (0:01:47)

$ python -m pytest tests -q
489 passed, 1 skipped, 3 warnings in 82.06s (0:01:22)

$ python -m compileall src tests
(compileall clean — no errors)

$ git status --short
 M src/aquaoptima/dphm/__init__.py
 M src/aquaoptima/dphm/inp_io.py
 M tests/dphm/test_inp_pump_curves.py
 M tests/dphm/test_wntr_optional_import.py
 M tests/dphm/test_wntr_pump_helpers.py
 M docs/epanet-inp-import.md
?? SPRINT14_REPORT.md
?? docs/examples/epanet_reference_power_pump.inp
?? tests/dataio/test_inp_power_pump_telemetry.py
?? tests/dphm/test_inp_power_pump.py
```

The single skipped test is the WNTR-absent `ImportError` branch in
`tests/dphm/test_wntr_optional_import.py:test_wntr_parser_explicit_raises_importerror_when_missing`,
which can only run when `wntr` is not installed. WNTR is installed
in this environment (the Sprint 13 + Sprint 14 optional WNTR tests
all pass) so this skip is expected and matches the Sprint 13
baseline.

Counts: Sprint 13 final = 449 passed, 1 skipped. Sprint 14 final =
489 passed, 1 skipped. Net delta = +40 tests, all green.

## Compatibility notes

- `Network` dataclass signature is unchanged.
- `load_network_from_inp` signature is unchanged.
- HEAD-curve pump translation (Sprint 12 fallback, Sprint 13 WNTR)
  is preserved bit-for-bit; tests pass unchanged.
- New `fit_power_pump_surrogate` is additive to the public API.
- Internal helper `_wntr_translate_pump` gained two optional
  keyword arguments (`downstream_demand`, `total_positive_demand`),
  both defaulting to `0.0`. Existing HEAD-pump callers (the WNTR
  parser, the duck-typed fakes in tests) continue to work without
  passing them — the HEAD branch does not consult them.
- One Sprint 13 test that asserted WNTR POWER pumps were rejected
  has been replaced with three Sprint 14 tests that assert WNTR
  POWER pumps are accepted via the surrogate. This is the
  intended behavioural change for Sprint 14 and the only
  user-visible regression in the test surface.

## Known limitations

1. **The surrogate is not a faithful constant-power conversion.**
   `Q · H` is not preserved away from the anchor flow. The
   surrogate matches EPANET POWER pump behaviour at exactly one
   operating point. Operating far from `Q_nom` produces head
   values that diverge from a true constant-power curve. Callers
   that need physical accuracy should replace `POWER` with a real
   `HEAD curve_id`.
2. **The anchor flow `Q_nom` is a heuristic.** The fallback /
   WNTR parsers anchor on downstream demand or total positive
   demand, neither of which is necessarily the pump's true
   operating-point flow in a multi-pump network. For
   multi-pump networks the surrogate will over- or
   under-estimate `H_nom` accordingly.
3. **`shutoff_multiplier = 1.5` is arbitrary.** It is a
   conservative default (50% droop ratio). Tuneable via the
   keyword argument but not auto-inferred from the network.
4. **No efficiency or motor curve.** The surrogate models the
   head-flow shape only.
5. **WNTR `Pump.power` unit assumption.** The WNTR adapter
   assumes SI W. If a future WNTR release changes this convention,
   the adapter would silently mis-scale the surrogate; the unit
   assumption is documented in the helper docstring and in
   `docs/epanet-inp-import.md`.
6. **No US-customary unit support** (deferred from Sprint 11).

## Hard approval gates

| gate                                                              | status |
|-------------------------------------------------------------------|--------|
| targeted pytest exits 0                                           | PASS (481 passed, 1 skipped) |
| full pytest exits 0                                               | PASS (489 passed, 1 skipped) |
| compileall exits 0                                                | PASS (clean) |
| `SPRINT14_REPORT.md` exists                                       | PASS |
| POWER surrogate tests pass                                        | PASS |
| fallback POWER pump fixture loads and solves with analytic Newton | PASS (residual norm 1.11e-15) |
| HEAD curve pump tests still pass                                  | PASS (Sprint 12 fallback + Sprint 13 WNTR HEAD parity all green) |
| WNTR optional tests skip/pass cleanly                             | PASS (WNTR installed; all WNTR tests pass) |
| no obvious secret files/strings                                   | PASS |
| git status contains only intended Sprint 14 changes               | PASS |
| WNTR POWER helper/integration tests pass (WNTR installed)         | PASS |
| WNTR HEAD curve parity from Sprint 13 still passes                | PASS |

## VERDICT

**APPROVED.**

All hard gates pass. The POWER pump surrogate is implemented,
documented, and exercised on both the fallback and WNTR paths.
The shipped POWER fixture loads through both back-ends and solves
to a residual norm of `1.11e-15` with the analytic Jacobian. The
WNTR-vs-fallback agreement test confirms both back-ends produce
numerically equivalent surrogate coefficients on the shipped
fixture. The surrogate's conservative, bounded design and its
limitations are explicitly documented in the code, in
`docs/epanet-inp-import.md`, and in this report.

## Sprint 15 recommendation

Recommended Sprint 15 scope: **add EPANET `[VALVES]` topology
import in steady-state-compatible forms (PRV pressure-reducing
valves and TCV throttling valves), with the same conservative,
explicit, documented translation strategy used for POWER pumps in
Sprint 14.**

Rationale and scope guardrails:

1. The current loader refuses `[VALVES]` outright. Adding even
   read-only support for the two most common steady-state forms
   (PRV, TCV) substantially widens the set of real-world INP
   fixtures the science gate can credibly load.
2. Like POWER pumps, valves do not map cleanly onto the dPHM
   core (the steady-state core does not model active flow
   control). Sprint 15 should ship a documented surrogate
   (e.g. PRV -> fixed-head boundary on the downstream node when
   active; TCV -> effective Hazen-Williams resistance bump) with
   the same "explicit, bounded, conservative, documented
   limitations" stance Sprint 14 established.
3. Hard limits to preserve: no real EPANET runtime; no SCADA
   adapters; no write/control path; no dPL parameter learning;
   no production claims; pytest stays green and `compileall`
   stays clean; one shipped `.inp` fixture per supported valve
   form.
4. Boundary with Sprint 14: do **not** revisit the POWER
   surrogate in Sprint 15 — the limitations listed above are
   accepted, not regressions to fix. A faithful constant-power
   model (implicit Newton constraint, efficiency curves) is its
   own future sprint, not a Sprint 15 deliverable.
