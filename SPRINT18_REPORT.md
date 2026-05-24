# Sprint 18 Report — EPANET `[OPTIONS] Demand Multiplier`

## Goal

Add fallback support for the EPANET `[OPTIONS] Demand Multiplier`
directive — a single non-negative scalar that scales every junction's
baseline demand at load time, applied after the flow-unit conversion.
Sprint 18 keeps every Sprint 11–17 pump / valve / unit / pressure
behaviour intact.

## Files changed

| File                                                                                | Status   | Purpose                                                                   |
|-------------------------------------------------------------------------------------|----------|---------------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                                                     | modified | New `resolve_demand_multiplier`, multi-word option-key parsing, fallback parser applies multiplier to junction demands, WNTR adapter applies `wn.options.hydraulic.demand_multiplier`. |
| `docs/epanet-inp-import.md`                                                         | modified | New "Demand multiplier (Sprint 18)" section, updated fixtures table, updated test list, updated roadmap. |
| `docs/examples/epanet_reference_loop_gpm_demand_multiplier.inp`                     | added    | Shipped Sprint 18 fixture: GPM/ft/in loop with `Demand Multiplier 2.0`.   |
| `tests/dphm/test_inp_demand_multiplier.py`                                          | added    | 41 new tests covering resolver, fallback parsing, scaling, validation, invariants, and optional WNTR parity. |
| `SPRINT18_REPORT.md`                                                                | added    | This report.                                                              |

## Demand multiplier design

- **Public resolver**: `resolve_demand_multiplier(opts) -> float` —
  takes the normalised options map returned by the fallback parser's
  `_parse_options`, looks for the canonical key `"DEMAND MULTIPLIER"`,
  returns `1.0` when absent. Validates that the value is numeric,
  finite, and non-negative; raises clear `ValueError`s otherwise.
- **Default**: missing directive → `1.0` (EPANET 2.2 default).
- **Acceptance**: `0.0` accepted (loads a network with all-zero
  junction demand). Negative, NaN, Inf, and non-numeric values raise
  `ValueError` with explicit messages.
- **Key parsing**: `Demand Multiplier` is the only shipped EPANET
  option whose canonical form spans two whitespace-separated tokens.
  `_parse_options` special-cases this combination: when the first two
  tokens are `Demand` and `Multiplier` (case-folded), the third token
  is stored under the canonical key `"DEMAND MULTIPLIER"`. Extra
  whitespace between tokens is already collapsed by the line-tokeniser,
  so any of `Demand Multiplier 2.0`, `DEMAND  MULTIPLIER 2.0`, or
  `demand multiplier 2.0` parse identically.
- **Application**: applied inline in the JUNCTIONS row loop as
  `demand_si = raw_demand * flow_to_m3s * demand_multiplier`. No
  separate dataclass / manifest — a single scalar suffices.

## Fallback parser behaviour

- Junction demands scaled by the multiplier, after the flow-unit
  conversion.
- Reservoir / tank fixed-head boundaries: **not** scaled.
- Pipe / pump / valve lengths, diameters, c_factors: **not** scaled.
- Pump `HEAD` curve points (`[CURVES]`): **not** scaled.
- TCV settings (the dimensionless `K`) and the `MinorLoss` column:
  **not** scaled.
- POWER pump nominal-flow anchor: sees the **multiplied** demand,
  because the anchor is resolved from the parser's normalised
  `demands` list after junction-demand scaling. A multiplier of `2.0`
  doubles `Q_nom`, halves `H_nom = P / (rho g Q_nom)`, and halves the
  surrogate's shut-off head `a0` (verified directly in the test
  suite).
- TCV resistance surrogate: also anchored on total positive demand,
  so the effective length shifts when the multiplier shifts the
  anchor. The surrogate's diameter and c_factor remain unchanged.
- The default-zero-multiplier branch loads cleanly and produces a
  network whose junction demands are all zero. The shipped tests
  exercise the load path; solve convergence depends on topology and
  is intentionally not asserted on the zero-demand path.

## WNTR behaviour

WNTR 1.4.0 (the installed version) exposes the directive as
`wn.options.hydraulic.demand_multiplier` and does **not** pre-scale
`Junction.base_demand` with it — the multiplier is applied later by
WNTR's internal simulator. Since the dPHM core never invokes that
simulator, the WNTR adapter applies the multiplier explicitly via the
new helper `_wntr_extract_demand_multiplier(wn)`:

- Defaults to `1.0` when the attribute chain is missing.
- Validation mirrors `resolve_demand_multiplier`: non-numeric,
  non-finite, or negative values raise `ValueError`.
- Applied inline in the junction loop as `base_demand *=
  demand_multiplier`.

This is the **minimal defensive adjustment** to the WNTR adapter that
the spec permits. It is required to keep the WNTR back-end and the
fallback parser at the same demand sums on the new shipped fixture;
existing WNTR fixtures (with no `Demand Multiplier` directive)
multiply by `1.0` and behave identically to Sprint 17.

The fallback parser remains the authoritative Sprint 18 path. WNTR
parity is verified end-to-end in
`test_wntr_applies_demand_multiplier_for_parity` and the existing
GPM-fixture parity check.

## Shipped fixture

`docs/examples/epanet_reference_loop_gpm_demand_multiplier.inp` — a
copy of the Sprint 16 GPM loop fixture with `Demand Multiplier 2.0`
added to the `[OPTIONS]` section. The fallback parser loads it with
every junction demand exactly twice that of
`epanet_reference_loop_gpm.inp`. Pipe geometry, reservoir head, and
roughness are byte-for-byte identical. The network solves with
`newton_solve(jacobian_mode="analytic")` to residual norm < 1e-7.

## Solve / scaling / parity evidence

- LPS scaling: `tests/dphm/test_inp_demand_multiplier.py
  ::test_fallback_scales_lps_demands_by_multiplier[0.5..10.0]` — 5
  parametrised cases, each verifying that junction demands scale
  exactly by the multiplier under SI flow units.
- GPM scaling: `test_shipped_gpm_demand_multiplier_fixture_doubles_demand_sum`
  + `test_shipped_gpm_demand_multiplier_fixture_per_junction_demand`
  — the shipped GPM/Demand Multiplier 2.0 fixture's positive demand
  sum is exactly twice the Sprint 16 baseline, and each junction
  demand is exactly `2 * raw_gpm * GPM_TO_M3S`.
- POWER pump anchor: `test_power_pump_anchor_uses_multiplied_demand`
  — the surrogate's `a0` halves when the multiplier doubles, matching
  the closed-form `H_nom = P / (rho g Q_nom)` analytic prediction.
- Analytic-Newton solve: shipped GPM fixture solves to residual norm
  < 1e-7. Power-pump-with-multiplier fixture solves to residual
  norm < 1e-7.
- WNTR parity: optional `pytest.importorskip("wntr")` test confirms
  both back-ends produce identical positive-demand sets on the new
  fixture (1e-7 absolute tolerance).
- Sprint 11–17 regression: existing SI loop, GPM loop, PRV, TCV,
  POWER pump, HEAD pump, and pressure-unit fixtures still load with
  byte-for-byte identical demands.

## Tests added / updated

- New: `tests/dphm/test_inp_demand_multiplier.py` (41 tests). Coverage
  groups:
  - Resolver defaults and validation (9 tests).
  - Fallback default no-multiplier behaviour (1 test).
  - Multiplier=1.0 is a no-op (1 test).
  - Parametrised LPS scaling (5 tests).
  - Shipped GPM fixture (4 tests: shipped + sum + per-junction +
    geometry-unchanged + solves).
  - Zero multiplier (1 test).
  - Validation errors raised by the parser (5 parametrised cases).
  - Case / whitespace tolerance for the option key (5 parametrised
    cases).
  - POWER pump anchor scaling + solve (2 tests).
  - TCV settings / diameter / c_factor invariants (1 test).
  - Pump HEAD curve coefficients unchanged by multiplier (1 test).
  - Reservoir / tank fixed-head unchanged (2 tests).
  - Existing SI / GPM fixtures regression (2 tests).
  - Optional WNTR parity (2 tests).
- No existing tests modified or deleted; Sprint 11–17 coverage is
  preserved exactly.

## Validation commands / results

```bash
python -m pip install -e .
# ok (editable install)

python -m pytest tests/dphm tests/models tests/training tests/dataio -q
# 681 passed, 1 skipped, 3 warnings in 102.56s
# (Sprint 17 baseline: 640 passed, 1 skipped)
# (+41 new Sprint 18 tests)

python -m pytest tests -q
# 689 passed, 1 skipped, 3 warnings in 91.36s
# (Sprint 17 baseline: 648 passed, 1 skipped)

python -m compileall src tests
# exit 0 — no syntax errors

git status --short
#  M docs/epanet-inp-import.md
#  M src/aquaoptima/dphm/inp_io.py
# ?? docs/examples/epanet_reference_loop_gpm_demand_multiplier.inp
# ?? tests/dphm/test_inp_demand_multiplier.py
```

All four Sprint 18 file changes are intentional. No stray files,
no secrets, no unrelated modifications.

## Compatibility notes

- Sprint 11–17 fixtures and tests load unchanged. The new code path
  defaults to `multiplier = 1.0` whenever `[OPTIONS] Demand Multiplier`
  is absent, which is a no-op.
- Public API additions: `resolve_demand_multiplier` is exported via
  `aquaoptima.dphm.inp_io` (the test module imports it directly) and
  added to `inp_io.__all__`. No symbols renamed or removed.
- WNTR adapter: the multiplier extraction is defensive (defaults to
  `1.0` if the WNTR attribute chain is missing), so older WNTR
  releases that omit the attribute degrade gracefully.

## Known limitations

- **Steady-state only**. The multiplier is a single scalar applied at
  load time. The dPHM core remains steady-state; time-varying
  `[PATTERNS]` demand is still out of scope (deferred — see the
  roadmap note in `docs/epanet-inp-import.md`).
- **Zero-multiplier solve behaviour is topology-dependent**. The
  parser accepts and loads a `Demand Multiplier 0` fixture, but the
  solver may not converge on a zero-demand network with no pumps
  (everything in equilibrium at reservoir head, but residual norm
  depends on initialisation). The Sprint 18 tests assert load
  behaviour for zero multiplier and avoid asserting convergence.
- **WNTR adapter is minimally adjusted, not refactored**. The
  multiplier is fetched via `getattr` chains; if a future WNTR
  release renames `options.hydraulic.demand_multiplier`, the adapter
  silently degrades to the `1.0` default rather than failing loudly.
  The fallback parser remains the authoritative Sprint 18 path.

## Hard approval gates

- [x] targeted pytest exits 0 (681 passed, 1 skipped)
- [x] full pytest exits 0 (689 passed, 1 skipped)
- [x] compileall exits 0
- [x] `SPRINT18_REPORT.md` exists
- [x] demand multiplier parsing is tested (41 dedicated tests)
- [x] default no-multiplier behaviour remains compatible (verified
      by `test_existing_si_loop_fixture_unaffected_by_sprint18`,
      `test_existing_gpm_loop_fixture_unaffected_by_sprint18`)
- [x] LPS and GPM demand scaling tests pass
- [x] POWER pump anchor uses multiplied demand (verified
      analytically against `fit_power_pump_surrogate`)
- [x] TCV settings remain dimensionless and unaffected
      (`test_tcv_settings_and_diameter_not_affected_by_multiplier`)
- [x] existing SI / GPM / pressure fixture behaviour still passes
      (all 230 `inp_io` tests green)
- [x] HEAD pump tests still pass
- [x] POWER pump tests still pass
- [x] PRV / TCV valve tests still pass
- [x] WNTR optional tests pass cleanly with WNTR 1.4.0 installed
- [x] no obvious secret files / strings introduced
- [x] git status contains only intended Sprint 18 changes
- [x] WNTR HEAD/POWER/PRV/TCV parity from Sprints 13–17 still passes
      (verified via the full `tests/dphm/test_wntr_optional_import.py`
      and `tests/dphm/test_inp_us_fixtures.py` parity suites)
- [x] WNTR demand-multiplier behaviour documented in
      `docs/epanet-inp-import.md` (WNTR exposes the directive
      separately; Sprint 18 applies it explicitly to match the
      fallback parser).

## Verdict

`VERDICT: APPROVED`

## Sprint 19 recommendation

The next small mechanical parser gap is the **EPANET
`[OPTIONS] Specific Gravity` directive** — a scalar that EPANET
treats as a fluid-density override (it scales pressure ↔ head
conversions for the pump-energy equation). For the dPHM core, this
would adjust the constant `_PRESSURE_RHO` used by both the pressure
unit manifest (Sprint 17) and the POWER pump surrogate (Sprint 14)
on a per-load basis. Like Sprint 18, it is a single-scalar parser
addition with no new hydraulics. Recommended order:

1. **Sprint 19** — `[OPTIONS] Specific Gravity` parsing + propagation
   through pressure-unit and POWER pump conversions. Validation
   surface mirrors Sprint 18 (non-negative, finite, default 1.0).
2. **Sprint 20** — `[OPTIONS] Viscosity` parsing as a no-op or as a
   parsed-but-unused warning, since Hazen-Williams head loss is
   viscosity-independent. Documents the boundary.
3. **Sprint 21** — `[ENERGY]` section parsing for pump efficiency
   curves, gated to Sprint-12+14 pump rows. Largest scope of the
   three; deferred behind the simpler scalar options.

Alternative: jump to `[STATUS]` rows for pipe `CLOSED` / `OPEN`
overrides; this would replace the current Sprint 11 hard-fail on
`CLOSED` with a documented edge-removal path. Slightly larger blast
radius than a scalar option, so the specific-gravity scalar is the
recommended next step.
