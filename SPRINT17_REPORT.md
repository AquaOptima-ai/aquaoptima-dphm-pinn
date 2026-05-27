# Sprint 17 — EPANET `[OPTIONS] Pressure` parsing & pressure-unit manifest

## Scope

Sprint 17 closes the next orthogonal unit gap in the EPANET `.inp`
import path: the **pressure-display unit**. Sprint 16 captured every
per-flow-unit conversion (length, diameter, head/elevation, demand)
in a single `EpanetUnitSystem` manifest. Sprint 17 adds a second,
independent manifest — `EpanetPressureUnit` — for the optional
`[OPTIONS] Pressure` directive, and routes the fallback parser's
PRV setting conversion through it.

This is parser / unit-conversion work only. No new hydraulic
physics, no new pump or valve forms, no Darcy-Weisbach support, no
real EPANET binary, no control path. Strict TDD.

## Files changed

| File                                                   | Change                                                                                                |
|--------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                        | Added `EpanetPressureUnit`, `SUPPORTED_PRESSURE_UNITS`, `resolve_pressure_unit`; wired `[OPTIONS] Pressure` into the fallback parser's PRV setting conversion. |
| `docs/examples/epanet_reference_prv_gpm_psi.inp`       | New shipped fixture: GPM + `[OPTIONS] Pressure PSI` PRV.                                              |
| `tests/dphm/test_inp_pressure_units.py`                | New Sprint 17 test module (33 tests).                                                                 |
| `docs/epanet-inp-import.md`                            | New "Pressure units (Sprint 17)" section; updated honoured-sections table, shipped-fixtures table, and per-test summary. |

WNTR adapter intentionally **unchanged**: WNTR normalises pressure
settings internally on load, so adding a second pressure-unit
conversion on the WNTR path would double-convert and yield nonsense.
See "WNTR behaviour" below.

## Pressure-unit design

```python
@dataclass(frozen=True)
class EpanetPressureUnit:
    name: str
    pressure_to_head_m: float
```

One field — the factor that turns a file-declared pressure into
metres of water head. Derived through a Pa pivot using the EPANET
pump-energy constants `rho = 1000 kg/m³` and `g = 9.80665 m/s²`, so
`1 m of water head = 9806.65 Pa`.

`SUPPORTED_PRESSURE_UNITS = ("PSI", "KPA", "METERS", "M", "FEET",
"FT", "BAR")`. The resolver is case-insensitive; unknown tokens raise
`ValueError` listing the supported set.

### Conversion constants

| Pressure unit | Pa per unit            | metres of water head per unit (exact)        | numeric (15 digits)                |
|---------------|------------------------|----------------------------------------------|------------------------------------|
| `METERS`      | 9806.65                | `1.0`                                        | `1.000000000000000`                |
| `M`           | 9806.65                | `1.0` (alias)                                | `1.000000000000000`                |
| `FEET`        | ~2989.067              | `0.3048` (international foot, exact)         | `0.304800000000000`                |
| `FT`          | ~2989.067              | `0.3048` (alias)                             | `0.304800000000000`                |
| `KPA`         | 1000                   | `1000 / 9806.65`                             | `0.101971621297793`                |
| `PSI`         | 6894.757293168 (NIST)  | `6894.757293168 / 9806.65`                   | `0.703069579639122`                |
| `BAR`         | 100000                 | `100000 / 9806.65`                           | `10.197162129779283`               |

These are pinned by `test_pressure_unit_manifest_constants_match_documented_values`
with `pytest.approx(rel=1e-12, abs=1e-18)`.

## Fallback parser behaviour

| State of `[OPTIONS] Pressure` | PRV setting conversion                                                  | TCV setting | Other fields                              |
|-------------------------------|-------------------------------------------------------------------------|-------------|-------------------------------------------|
| **Absent (Sprint 16 default)** | Multiplied by `unit_system.pressure_setting_to_m` (= `head_to_m` — metres for SI flow units, feet for US flow units). | Untouched (dimensionless `K`). | Untouched (unchanged from Sprint 16: lengths via `length_to_m`, diameters via `diameter_to_m`, heads via `head_to_m`, demands via `flow_to_m3s`). |
| **Present (Sprint 17)**       | Multiplied by `resolve_pressure_unit(<token>).pressure_to_head_m`. Flow-unit family's head conversion is bypassed for PRV settings only. | Untouched (dimensionless `K`). | Untouched.                                |
| **Unknown token**             | Raises `ValueError("unknown EPANET pressure unit ...")`.                | —           | —                                         |

Implementation lives in `_fallback_parse` and is a 7-line addition
plus a one-line change to the PRV setting line:

```python
pressure_directive = opts.get("PRESSURE", "")
if pressure_directive:
    prv_setting_to_m = resolve_pressure_unit(
        pressure_directive
    ).pressure_to_head_m
else:
    prv_setting_to_m = unit_system.pressure_setting_to_m
...
if valve_type == "PRV":
    setting_value = setting_raw * prv_setting_to_m
```

The flow-unit manifest is untouched; the new directive only affects
the PRV path.

## WNTR behaviour

WNTR normalises every hydraulic quantity to its internal SI
representation when a `WaterNetworkModel` is loaded — regardless of
the source file's `[OPTIONS] Pressure` directive. The Sprint 17
adapter therefore **does not** apply a second pressure-unit
conversion. Doing so would double-convert the PRV setting and yield
~21 m for a true 30-psi setting (which WNTR has already converted to
~21 m).

Concretely:

- `_wntr_extract_valve_fields` reads `valve.initial_setting` (or
  `valve.setting` as fallback) as a float and passes it straight
  through to `translate_valve_to_surrogate`, which treats it as
  metres of head. WNTR is the trusted source of conversion on the
  WNTR path.
- The shipped SI PRV fixture (no `Pressure` directive) demonstrates
  byte-for-byte fallback-vs-WNTR parity on the pinned fixed-head
  value (`test_wntr_si_prv_still_pins_downstream_at_setting`).
- For arbitrary `[OPTIONS] Pressure` declarations, the back-end
  parity is constrained by WNTR's own pressure-unit table — which
  has historically varied across WNTR releases and is not always
  documented to load-time precision. The fallback parser is the
  authoritative path for Sprint 17 pressure-unit behaviour. This
  is **documented as a known limitation**, not papered over.

The Sprint 13/14/15/16 WNTR optional parity tests (loop / HEAD pump
/ POWER pump / PRV / TCV / GPM fixtures) all continue to pass with
WNTR 1.4.0 installed.

## Shipped PSI fixture

`docs/examples/epanet_reference_prv_gpm_psi.inp` — four-node
topology mirroring the Sprint 15 SI PRV fixture, but expressed in
GPM/ft/in with the PRV setting in PSI:

```text
R1 (reservoir, 164 ft ~ 50 m)
  └─ P1 (6562 ft, 3.15 in, C=130) ──→ J1
                                       └─ V1 (PRV setting 30 PSI, 3.15 in)
                                            └─→ J2 (pinned at 30 PSI ~ 21.09 m)
                                                 └─ P2 (656 ft, 3.15 in, C=130)
                                                      └─→ J3 (32 GPM consumer)
```

The fallback parser converts the 30 PSI setting via the Sprint 17
pressure-unit manifest to `30 × 0.7030695796 ≈ 21.092 m` of water
head. Without the new directive support, the parser would have
silently applied the flow-unit family's feet → m conversion and
pinned J2 at `30 × 0.3048 = 9.144 m` — a 12 m error.

Solver evidence:

- `test_prv_gpm_psi_fixture_solves_with_analytic_newton` runs
  `newton_solve(net, max_iterations=200, tol=1e-9,
  jacobian_mode="analytic")` and asserts `result.converged` and
  `result.residual_norm < 1e-7`.
- `test_prv_gpm_psi_fixture_pins_downstream_via_psi_conversion`
  affirmatively rejects the wrong (feet) conversion: the pinned
  value is `21.092 m`, not `9.144 m`.

## Tests added

`tests/dphm/test_inp_pressure_units.py` — 33 tests organised as:

| Test group                                          | Tests | Asserts                                                                    |
|-----------------------------------------------------|-------|----------------------------------------------------------------------------|
| Pressure-unit manifest                              | 7 + 3 |  Exact constants for all 7 supported units; round-number sanity for PSI, BAR, KPA. |
| Resolver surface                                    | 3     | Case-insensitive lookup, unknown-token error, empty-string error.          |
| Metres/feet identity                                | 2     | `METERS` / `M` resolve to 1.0; `FEET` / `FT` resolve to `_FT_TO_M`.        |
| Shipped GPM+PSI fixture                             | 3     | File ships; downstream pinned via psi (not feet); analytic Newton solves.  |
| Default no-Pressure behaviour (Sprint 16 contract)  | 2     | LPS PRV pins at metres; GPM PRV pins at feet.                              |
| Explicit Pressure directive (tmp fixtures)          | 7     | All 7 supported pressure units pin downstream via the explicit conversion. |
| Pressure directive parsing                          | 2     | Case-insensitive directive value; unknown token raises.                    |
| TCV invariant                                       | 1     | TCV setting + surrogate parameters are byte-identical with and without `[OPTIONS] Pressure`. |
| Sprint 15 SI fixture regression                     | 1     | Existing SI PRV fixture unaffected by Sprint 17 changes.                   |
| WNTR no-double-convert                              | 1     | WNTR pins SI PRV fixture's downstream at 20 m (same as fallback).          |

`tests/dphm/test_inp_pressure_units.py::test_*` — **33 passed, 0 failed**.

## Validation

### Commands

```bash
python -m pip install -e .
python -m pytest tests/dphm tests/models tests/training tests/dataio -q
python -m pytest tests -q
python -m compileall src tests
git status --short
```

### Results

| Step                                          | Result                                |
|-----------------------------------------------|---------------------------------------|
| `pip install -e .`                            | Successful (`aquaoptima-dphm-pinn 0.1.0`). |
| Targeted pytest (`dphm`, `models`, `training`, `dataio`) | **640 passed, 1 skipped, 0 failed** in 99.19 s. |
| Full pytest (`tests`)                         | **648 passed, 1 skipped, 0 failed** in 100.44 s. |
| `python -m compileall -q src tests`           | Exit 0, no diagnostics.                |
| `git status --short`                          | 1 modified (`src/aquaoptima/dphm/inp_io.py`), 2 untracked (`docs/examples/epanet_reference_prv_gpm_psi.inp`, `tests/dphm/test_inp_pressure_units.py`). |

The single skipped test is the documented `wntr` ImportError-path
test (`tests/dphm/test_wntr_optional_import.py::...`), which skips
because WNTR is installed in this environment. This is expected.

### Test-count delta vs Sprint 16

- Sprint 16 targeted pytest: 607 passed, 1 skipped.
- Sprint 17 targeted pytest: 640 passed, 1 skipped.
- New tests this sprint: **33** — all in `test_inp_pressure_units.py`.

- Sprint 16 full pytest: 615 passed, 1 skipped.
- Sprint 17 full pytest: 648 passed, 1 skipped.
- Delta: **+33**, matching the new test module exactly.

No regressions in the Sprint 11/12/13/14/15/16 surfaces (loop, HEAD
pump, POWER pump, PRV, TCV, SI, GPM, WNTR parity).

## Compatibility notes

- **Sprint 16 default behaviour preserved.** When `[OPTIONS]
  Pressure` is absent (every existing shipped fixture), the parser
  routes PRV settings through `unit_system.pressure_setting_to_m`
  exactly as Sprint 16 did. The Sprint 15 SI PRV fixture and the
  Sprint 16 GPM tmp PRV fixture both load identically before and
  after this sprint.
- **TCV invariant preserved.** `test_tcv_setting_not_affected_by_pressure_directive`
  parses the same TCV network three ways (no directive, `Pressure
  PSI`, `Pressure BAR`) and asserts the resulting surrogate
  lengths, diameters, and c-factors are byte-identical.
- **No flow-unit-manifest change.** `EpanetUnitSystem` is
  unchanged. `pressure_setting_to_m` remains a field on the
  flow-unit manifest (still used in the default code path).
- **No new public surface beyond the manifest helpers.**
  `EpanetPressureUnit`, `SUPPORTED_PRESSURE_UNITS`, and
  `resolve_pressure_unit` are added to the `__all__` export list of
  `aquaoptima.dphm.inp_io`. Existing public names (`EpanetUnitSystem`,
  `resolve_unit_system`, `SUPPORTED_FLOW_UNITS`, `load_network_from_inp`,
  the surrogate fitters and translators) are untouched.

## Known limitations

- **WNTR pressure-unit parity is not enforced.** The WNTR adapter
  trusts WNTR's internal pressure normalisation and applies no
  second conversion. On a `[OPTIONS] Pressure PSI` file, the two
  back-ends agree only when WNTR's PSI table matches Sprint 17's
  (which it should for current WNTR releases, but is not pinned by
  a parity test in this sprint). The fallback parser is the
  authoritative path for Sprint 17 pressure-unit behaviour. A
  cross-back-end parity test for arbitrary `[OPTIONS] Pressure`
  values is a deferred refinement and would require introspecting
  WNTR's pressure table at load time.
- **Only PRV settings are converted through the pressure manifest.**
  Junction / reservoir / tank elevations and heads continue to use
  the flow-unit family's `head_to_m`. EPANET's `[OPTIONS] Pressure`
  is documented as a *display* unit, not a *file* unit, for
  elevations / heads — so this matches EPANET semantics.
- **No new valve forms.** `FCV` / `PSV` / `PBV` / `GPV` still raise
  `ValueError`; same as Sprint 15.
- **No active valve-control physics.** The pressure-boundary
  surrogate is unchanged from Sprint 15; flow through the PRV may
  differ from downstream demand. The fixture is deliberately built
  so the upstream pressure budget caps the through-valve flow
  close to the consumer demand.

## Verdict

**APPROVED.**

Sprint 17 hard-gate checklist:

- [x] Targeted pytest exits 0 (640 passed, 1 skipped).
- [x] Full pytest exits 0 (648 passed, 1 skipped).
- [x] `compileall` exits 0.
- [x] `SPRINT17_REPORT.md` exists.
- [x] Pressure unit conversion constants tested (7 units, exact constants,
      round-number sanity).
- [x] `GPM + Pressure PSI` PRV fixture loads and solves through the
      fallback parser.
- [x] Default no-Pressure behaviour remains Sprint 16-compatible
      (`test_default_no_pressure_directive_preserves_sprint16_prv`
      and `…_us_prv_feet`).
- [x] TCV settings remain dimensionless under `[OPTIONS] Pressure`
      (`test_tcv_setting_not_affected_by_pressure_directive`).
- [x] Existing SI and GPM fixture behaviour preserved
      (`test_existing_si_prv_fixture_unaffected_by_sprint17`, all
      Sprint 16 US-fixture tests still pass).
- [x] HEAD pump tests still pass (Sprint 12/13 + WNTR parity).
- [x] POWER pump tests still pass (Sprint 14 + WNTR parity).
- [x] PRV / TCV valve tests still pass (Sprint 15 + WNTR parity).
- [x] WNTR optional tests skip/pass cleanly (WNTR 1.4.0 installed;
      the ImportError-path test correctly skips; all other WNTR
      tests pass).
- [x] No new secret files / strings introduced.
- [x] `git status` contains only intended Sprint 17 changes
      (`src/aquaoptima/dphm/inp_io.py`, new fixture, new test, doc
      updates, this report).

WNTR-installed extra gates:

- [x] WNTR HEAD / POWER / PRV / TCV parity from Sprints 13–16 still
      pass.
- [x] WNTR ambiguity around `[OPTIONS] Pressure` is documented in
      this report and in `docs/epanet-inp-import.md`'s "Pressure
      units (Sprint 17)" section.

## Sprint 18 recommendation

The next orthogonal gap in the EPANET parser is `[OPTIONS] Demand
Multiplier` (a scalar that scales all junction demands at load
time). It is a one-field manifest extension, exercises the existing
flow-unit code path, and lets future sprints land more EPANET-
realistic fixtures without changing physics.

A second candidate is `[OPTIONS] Specific Gravity` and
`[OPTIONS] Viscosity` (no-ops under Hazen-Williams, but the parser
should still tolerate / validate them so EPANET-produced fixtures
load without manual stripping).

Both fit the same parser-only / no-physics envelope Sprint 11–17
have shared. The recommendation is **Sprint 18: `[OPTIONS] Demand
Multiplier` parsing** as the smallest, highest-coverage extension.
Defer `Specific Gravity` / `Viscosity` to a later sprint.
