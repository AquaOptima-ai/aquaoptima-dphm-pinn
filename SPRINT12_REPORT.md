# Sprint 12 — EPANET `.inp` Pump HEAD-Curve Import

**Branch:** `sprint12` (worktree `aquaoptima-dphm-pinn-sprint12`)
**Base:** Sprint 11 commit `30ef7e7` ("feat: add optional epanet inp topology import")
**Verdict:** `APPROVED`

## Goal

Widen the Sprint 11 EPANET `.inp` topology loader to translate pump
HEAD curves into the existing dPHM pump-affinity quadratic model,
keeping the surface dependency-free, the dPHM core physics
unchanged, and the strict topology-import-only safety boundary
intact.

## Files changed

| Path                                                  | Status     | Purpose                                                              |
|-------------------------------------------------------|------------|----------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                       | modified   | Parse `[CURVES]`, parse `[PUMPS] ... HEAD`, fit curve, build pump edge |
| `src/aquaoptima/dphm/__init__.py`                     | modified   | Export `fit_pump_head_curve`                                          |
| `docs/epanet-inp-import.md`                           | modified   | Document Sprint 12 pump-curve translation and diagnostics             |
| `docs/examples/epanet_reference_pump.inp`             | new        | Shipped 3-node pump-bearing reference fixture                         |
| `tests/dphm/test_inp_pump_curves.py`                  | new        | Parser + fitter + fixture tests (21 cases)                            |
| `tests/dataio/test_inp_pump_telemetry.py`             | new        | Solver + physics-consistent telemetry on the pump fixture (7 cases)  |
| `tests/dphm/test_inp_network_io.py`                   | modified   | Update Sprint 11 "pumps raise" expectation to new "undefined curve raises" error path |
| `tests/dphm/test_wntr_optional_import.py`             | modified   | Add WNTR-still-refuses-pumps optional regression                      |

## Pump parser API and behaviour

### Public helper

```python
from aquaoptima.dphm import fit_pump_head_curve

coeffs, diag = fit_pump_head_curve([(0.0, 45.0), (0.02, 44.68), (0.05, 43.0)])
# coeffs == [a0, a1, a2] for H(Q) = a0 + a1*Q + a2*Q^2 at s = 1
```

`Q` values must be in **m³/s** and `H` in **metres**. The function
delegates the unit conversion of EPANET file Q-values to the
parser (which applies the `[OPTIONS] Units` factor before fitting).

The returned `diag` dict carries `a0`, `a1`, `a2`, `rmse`,
`max_abs_error`, `num_points`, `q_min`, `q_max`, and a boolean
`droop_ok` (`1.0` iff `a2 ≤ 0`).

### Parser changes in `_fallback_parse`

1. `[CURVES]` is no longer in `_IGNORED_SECTIONS`; it is parsed into
   a `dict[curve_id, list[(Q, H)]]` *up-front*, applying the file's
   demand factor so `Q` is stored in m³/s.
2. `[PUMPS]` rows of the form `id n1 n2 HEAD curve_id` are
   appended after the pipe edges, in file order. Each pump row:
   - resolves its endpoints against the node id table,
   - looks up its curve in the up-front curve map,
   - calls `fit_pump_head_curve` to obtain `[a0, a1, a2]`,
   - sets `pump_mask=True`, `pipe_mask=False`,
   - records benign positive placeholders on the pipe-only fields
     (`length=1.0`, `diameter=0.1`, `c_factor=130.0`) — the
     `Network` dataclass only enforces positivity on rows where
     `pipe_mask` is `True`,
   - sets `pump_speeds[e] = 1.0`.
3. Pump rows with any keyword other than `HEAD` (e.g. `POWER`,
   `SPEED`) raise `ValueError`.
4. Pump rows that reference an undefined curve raise `ValueError`
   with the available-curve list in the message.
5. Pump ids that collide with pipe ids raise `ValueError`
   ("duplicate edge").

### Edge ordering

Pipes first, then pumps, in file order within each section. The
Sprint 12 shipped fixture has `[P1, PU1]` -> edge index of the same
order, `pipe_mask = [True, False]`, `pump_mask = [False, True]`.

## Pump-curve fitting formula and diagnostics

The dPHM pump-affinity model is

```
H(Q, s) = a0 · s² + a1 · s · Q + a2 · Q²
```

Sprint 12 fits at the static nominal speed `s = 1`, reducing to

```
H(Q) = a0 + a1·Q + a2·Q²
```

The fit is a 3-column ordinary least-squares solve
`X · [a0, a1, a2]ᵀ = H` where `X[i, :] = [1, Q_i, Q_i²]`, via
`torch.linalg.lstsq` (float64). Validation:

- `len(points) ≥ 3` (`ValueError` otherwise).
- `Q ≥ 0`, `H > 0`, all finite (`ValueError` otherwise).
- `a0 > 0` after fit (`ValueError` otherwise).
- `droop_ok = 1.0` iff `a2 ≤ 0` (advisory; not fatal).

On the shipped 6-point curve `H = 45 − 800·Q²`:

| metric            | value          |
|-------------------|----------------|
| `a0`              | `45.0`         |
| `a1`              | `−1.5e-12`     |
| `a2`              | `−800.0`       |
| `rmse`            | `1.4e-14` m    |
| `max_abs_error`   | `2.8e-14` m    |
| `q_min`, `q_max`  | `0.0`, `0.050` m³/s |
| `droop_ok`        | `1.0`          |

## Shipped pump fixture summary

`docs/examples/epanet_reference_pump.inp`:

```
R1 (reservoir, fixed head 5 m)
 │
 +─── PU1 (pump, HEAD PUMPCURVE1) ──> J1
                                       │
                                       +─── P1 (200 m, D=150 mm, C=130) ──> J2 (15 L/s consumer)
```

- 3 nodes, 2 edges, 1 fixed-head boundary.
- Pump curve: 6 points on `H = 45 − 800·Q²` (m³/s units), fit
  recovers `[45, 0, −800]` to fp64 precision.
- SI flow units (`LPS`), Hazen-Williams head loss.

## Solver residual evidence

Analytic Newton on the shipped pump fixture:

```
converged       = True
iterations      = 3
residual_norm   = 1.110e-15
heads           = [49.8200, 48.7011, 5.0000]
flows           = [0.01500, 0.01500]
pump gain       = 44.82 m   (Q ≈ 0.015 m³/s on H = 45 − 800·Q²)
pump residual   = 0.000e+00
```

Autograd and analytic Jacobians agree to `atol=1e-7` on the solved
heads and flows (covered by
`test_pump_fixture_analytic_matches_autograd`).

## Telemetry evidence

`generate_physics_consistent_telemetry` on the pump fixture with
`num_steps=8, seed=12, demand_amplitude=0.1, demand_noise_std=0.005,
solver_tol=1e-9, jacobian_mode="analytic"`:

- All series (`pressure`, `flow`, `demand`) finite at every step.
- Per-step residual norm `< 1e-3` (float32 round-trip bound; the
  float64 solver itself converges at `< 1e-9`), covered by
  `test_pump_fixture_telemetry_residuals_are_small`.
- Pump flow remains strictly positive across the window — the pump
  never reverses, covered by
  `test_pump_fixture_telemetry_pump_flow_is_positive`.

## Tests added / updated

`tests/dphm/test_inp_pump_curves.py` (21 cases, all passing):

- `test_fit_recovers_exact_quadratic_coefficients` — noise-free
  recovery of `[a0, a1, a2]` to fp64 precision.
- `test_fit_recovers_quadratic_with_nonzero_linear_term` — fits a
  curve with non-zero `a1`.
- `test_fit_consistent_with_pump_head_gain` — fitter output round-trips
  through `pump_head_gain` at the input curve points.
- `test_fit_flags_non_droop_curve` — `droop_ok = 0` when `a2 > 0`.
- `test_fit_raises_on_too_few_points`,
  `test_fit_raises_on_negative_flow`,
  `test_fit_raises_on_non_positive_head`,
  `test_fit_raises_on_negative_shutoff_head`.
- `test_pump_fixture_exists` + `test_pump_fixture_loads_via_fallback_parser`
  + `test_pump_fixture_recovers_known_curve_coefficients`
  + `test_pump_fixture_demand_balance_and_units`.
- Integrated parser error paths: undefined curve, unsupported keyword,
  too few curve points, negative flow in curve, unknown endpoint,
  too few pump columns, duplicate pump id, pump-id-clashing-with-pipe-id,
  grouped repeated-id curves.

`tests/dataio/test_inp_pump_telemetry.py` (7 cases, all passing):

- `test_pump_fixture_solves_with_analytic_newton`.
- `test_pump_fixture_analytic_matches_autograd`.
- `test_pump_fixture_pump_residual_is_finite_and_small`.
- `test_pump_fixture_full_residual_batched`.
- `test_pump_fixture_drives_physics_consistent_telemetry`.
- `test_pump_fixture_telemetry_residuals_are_small`.
- `test_pump_fixture_telemetry_pump_flow_is_positive`.

`tests/dphm/test_wntr_optional_import.py` — added
`test_wntr_loader_still_refuses_pump_fixture_in_sprint12` (skip-guarded
behind `pytest.importorskip("wntr")`).

`tests/dphm/test_inp_network_io.py` — Sprint 11
`test_pumps_section_raises_in_fallback` renamed to
`test_pumps_section_without_curve_raises_in_fallback`, matching the
new "undefined HEAD curve" error message; remaining Sprint 11 tests
unchanged.

## Validation commands and results

```bash
python -m pip install -e .                                                # clean
python -m pytest tests/dphm tests/models tests/training tests/dataio -q   # 419 passed, 3 skipped
python -m pytest tests -q                                                 # 427 passed, 3 skipped
python -m compileall src tests                                            # exit 0
git status --short                                                        # only intended Sprint 12 changes
```

The 3 skips are the WNTR-optional tests, skipped cleanly because
`wntr` is not installed in this environment.

## Compatibility notes

- The Sprint 11 fallback contract that *any* `[PUMPS]` section
  raises has been **softened**, not removed. Well-formed
  `HEAD curve_id` rows now translate to a dPHM pump edge; every
  other pump form (`POWER`, `SPEED`, multi-curve `HEAD` with
  efficiency, etc.) still raises with the message
  `"unsupported keyword"`. The single Sprint 11 test that asserted
  the old "any pump raises" contract has been updated to the new
  "undefined curve raises" contract; the rest of the Sprint 11 surface
  is untouched.
- The WNTR-backed parser is **unchanged** in Sprint 12. WNTR-loaded
  INP files that declare pumps still raise the Sprint 11
  `"Sprint 11 WNTR adapter does not yet translate pump curves"`
  message. Pump curve translation through WNTR is deferred.
- `Network.pump_coeffs`, `pump_speeds`, `pipe_mask`, `pump_mask` shapes
  and validation rules are unchanged. Pump rows use benign positive
  placeholders for pipe-only fields, matching the convention in
  `make_pump_network`.
- The dPHM physics core (Hazen-Williams pipe loss, pump-affinity
  quadratic, mass-balance residual) is unchanged. Sprint 12 only
  fits new EPANET curve points into the existing quadratic; no new
  equations were introduced.
- No new dependencies. No internet access. No external EPANET
  runtime. No PLC/PAC/SCADA adapters. No write/control path.

## Known limitations

- Only `HEAD curve_id` pump rows are supported. `POWER`, `SPEED`,
  multi-segment / LINEAR forms still raise.
- The fitter accepts curves with `a2 > 0` (`droop_ok = 0`) without
  failing. Callers that need strict-droop input should inspect the
  diagnostic. This was a deliberate choice: real-world curves can
  have monotonically rising regions near the shut-off point, and
  the dPHM solver does not require `a2 ≤ 0`.
- Pump speeds are pinned to `s = 1.0` at load time. Variable-speed
  operation requires the caller to update `network.pump_speeds`
  post-load.
- WNTR's pump support is deferred. The WNTR adapter still refuses
  pumps and points users at the fallback parser.
- The shipped fixture is intentionally tiny (3 nodes, 1 pump). It
  is a credibility gate, not a benchmark — large pump-bearing
  reference networks remain out of scope.

## Sprint 12 hard approval gates

| Gate                                                       | Status |
|------------------------------------------------------------|--------|
| Targeted pytest exits 0                                    | ✅ 419 passed, 3 skipped (WNTR optional) |
| Full pytest exits 0                                        | ✅ 427 passed, 3 skipped |
| `compileall src tests` exits 0                             | ✅ no output to stderr |
| `SPRINT12_REPORT.md` exists                                | ✅ this file |
| Pump HEAD curve parser and fit tests pass                  | ✅ 21 / 21 in `test_inp_pump_curves.py` |
| Shipped pump fixture loads and solves with analytic Newton | ✅ converged in 3 iterations, `residual_norm = 1.1e-15` |
| Pump residual / telemetry evidence                         | ✅ pump residual `0.000e+00` at solution; telemetry `< 1e-3` per step |
| Optional WNTR tests skip / pass cleanly                    | ✅ 3 skipped + 1 passed (negative-path) |
| No obvious secret files / strings                          | ✅ only INP fixtures, tests, docs, module edits |
| `git status --short` contains only intended Sprint 12 changes | ✅ 8 files (5 modified, 3 new) |

## Verdict

**`APPROVED`**

All hard gates pass. The Sprint 12 surface is small, dependency-free,
and physics-unchanged — it only widens the fallback INP parser to
translate EPANET HEAD curves into the existing dPHM pump-affinity
quadratic. The shipped fixture exercises the full parse → fit → solve
→ telemetry chain end-to-end.

## Sprint 13 recommendation

**Strict scope, in priority order.** Pick one of:

1. **WNTR-backed pump translation (recommended).** Extend the
   WNTR adapter to mirror the Sprint 12 fallback path: read
   `wntr.network.WaterNetworkModel.pump_name_list`, extract
   `Pump.get_pump_curve()` / `Pump.pump_curve_name`, evaluate the
   curve at its declared points, and call the same
   `fit_pump_head_curve` helper. This is the smallest credible
   expansion of the Sprint 11+12 import surface — it brings the two
   back-ends back into parity *and* opens the door to larger
   pump-bearing reference networks (e.g. EPANET `Net1`, `Net3`,
   `ky` series) that ship with WNTR. Same scope rules as Sprint 12:
   topology import only, no EPANET runtime, no write/control path.

2. **`POWER` / fixed-power pump form.** EPANET pump rows can also
   declare a constant-power model (`id n1 n2 POWER kW`). Translate
   this to the dPHM quadratic at the network's nominal flow by
   anchoring `a0` at the shut-off head implied by `P = ρ g Q H` at
   the operating point. Smaller scope than (1) but materially less
   credible — power-only pump declarations are common in legacy
   files but ambiguous about the droop shape.

Either path keeps Sprint 13 within the safety boundary documented
in `docs/safety-boundary.md`. **Defer everything else** —
US-customary unit support, controls/rules, time-varying patterns,
dPL parameter learning on pump curves, ONNX/Jetson deployment, and
any field-validation work remain out of scope.
