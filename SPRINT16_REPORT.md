# Sprint 16 — EPANET US-customary unit-system hardening

**Branch:** `sprint16` (worktree of
`/home/hunter_lin/projects/aquaoptima-dphm-pinn-sprint16`)
**Base commit:** `ca28b44 feat: add epanet valve import surrogates`
**Verdict:** **APPROVED**

## Goal

Harden the fallback EPANET `.inp` parser's unit-system handling so it
can load EPANET fixtures declared in any of the ten EPANET-recognised
flow-unit tokens — both SI and US-customary — without relying on
WNTR. Sprint 16 is **mechanical unit-conversion hardening only**; no
new physics, no new pump/valve forms, no Sprint 17 work.

## Files changed

```
SPRINT16_REPORT.md                                 | new
docs/epanet-inp-import.md                          | revised unit + fixture sections
docs/examples/epanet_reference_loop_gpm.inp        | new (US loop fixture)
docs/examples/epanet_reference_pump_gpm.inp        | new (US HEAD pump fixture)
docs/examples/epanet_reference_tcv_gpm.inp         | new (US TCV fixture)
src/aquaoptima/dphm/inp_io.py                      | EpanetUnitSystem manifest + US conversion paths
tests/dphm/test_inp_network_io.py                  | repurposed US-rejection test as US-acceptance
tests/dphm/test_inp_unit_systems.py                | new (manifest constants + lookup)
tests/dphm/test_inp_us_fixtures.py                 | new (US fixture loads + solves + parity)
```

## Unit system design

A single frozen dataclass `EpanetUnitSystem` carries every per-flow-
unit conversion the fallback parser needs:

```python
@dataclass(frozen=True)
class EpanetUnitSystem:
    units: str                  # canonical upper-case token
    flow_to_m3s: float          # demand / flow factor
    length_to_m: float          # pipe length factor
    diameter_to_m: float        # pipe/valve diameter factor
    head_to_m: float            # head / elevation factor
    pressure_setting_to_m: float  # PRV/PSV/PBV setting factor
```

The lookup helper `resolve_unit_system(name)` is case-insensitive and
raises a clear `ValueError` for unknown or unsupported tokens. The
parser body never reads ad-hoc unit constants — every conversion goes
through the manifest, which keeps the conversion contract auditable
in one place.

A small helper `_convert_power_value_to_kw` handles the special-case
HP → kW conversion for `[PUMPS] POWER` rows under US-customary flow
units (EPANET 2.2 declares POWER in kW under SI and HP under US, and
uses the internal `0.7457 kW/HP` constant).

## Conversion constants

All constants are exact (NIST conversion factors / EPANET 2.2 user
manual section 4.2):

| Unit  | flow_to_m3s                                | length_to_m | diameter_to_m | head_to_m | pressure_setting_to_m |
|-------|--------------------------------------------|-------------|---------------|-----------|-----------------------|
| LPS   | `1e-3`                                     | `1.0`       | `1e-3`        | `1.0`     | `1.0`                 |
| LPM   | `1 / 60_000`                               | `1.0`       | `1e-3`        | `1.0`     | `1.0`                 |
| MLD   | `1_000 / 86_400`                           | `1.0`       | `1e-3`        | `1.0`     | `1.0`                 |
| CMH   | `1 / 3600`                                 | `1.0`       | `1e-3`        | `1.0`     | `1.0`                 |
| CMD   | `1 / 86_400`                               | `1.0`       | `1e-3`        | `1.0`     | `1.0`                 |
| CFS   | `0.3048³ ≈ 0.028316846592`                 | `0.3048`    | `0.0254`      | `0.3048`  | `0.3048`              |
| GPM   | `0.003785411784 / 60 ≈ 6.30901964e-5`      | `0.3048`    | `0.0254`      | `0.3048`  | `0.3048`              |
| MGD   | `1e6 × 0.003785411784 / 86_400`            | `0.3048`    | `0.0254`      | `0.3048`  | `0.3048`              |
| IMGD  | `1e6 × 0.00454609 / 86_400`                | `0.3048`    | `0.0254`      | `0.3048`  | `0.3048`              |
| AFD   | `1233.48183754752 / 86_400`                | `0.3048`    | `0.0254`      | `0.3048`  | `0.3048`              |

Notes:

* `CMS` (cubic-metres-per-second) is intentionally **not** in the
  supported set. EPANET 2.2 does not recognise `CMS` as a `[OPTIONS]
  Units` token; Sprint 11–15 carried it as a defensive alias but
  Sprint 16 narrows the table to the documented set of ten.
  Fixtures that previously declared `CMS` should be updated to
  `LPS` / `CMH` / `CMD` as appropriate.
* `POWER` values under US flow units are scaled by `0.7457 kW/HP`
  outside the manifest because power is not a column on any other
  parsed row.
* `TCV` settings (the dimensionless minor-loss coefficient `K`) and
  the `MinorLoss` column are never scaled by the unit system —
  these are explicitly dimensionless in EPANET's grammar.

## Fallback parser behavior

Conversions applied by the fallback parser, by section:

* `[OPTIONS] Units` — read case-insensitively via
  `resolve_unit_system`; unsupported tokens raise `ValueError`.
* `[JUNCTIONS]` — elevation × `head_to_m`, demand × `flow_to_m3s`.
* `[RESERVOIRS]` — head × `head_to_m`.
* `[TANKS]` — elevation × `head_to_m`, init level × `head_to_m`.
* `[PIPES]` — length × `length_to_m`, diameter × `diameter_to_m`.
  Roughness (C-factor) is unitless and pass-through.
* `[PUMPS] HEAD curve_id` — curve `(Q, H)` points converted by
  `flow_to_m3s` and `head_to_m` before fitting the quadratic.
* `[PUMPS] POWER value` — value scaled HP → kW under US flow
  units, then passed to the bounded quadratic surrogate. The
  nominal-flow anchor is the network's already-SI demand, so the
  surrogate's head-at-nominal is correct regardless of input
  family.
* `[VALVES]` — diameter × `diameter_to_m`; PRV `Setting` ×
  `pressure_setting_to_m`; TCV `Setting` and `MinorLoss` are
  dimensionless and pass-through.

## WNTR behavior

WNTR (`wntr==1.4.0`, installed in this environment) parses the
`.inp` and normalises every value to SI internally before exposing
its `WaterNetworkModel`. The Sprint 11/13/14/15 WNTR adapter reads
those already-SI values directly and **does not apply a second
conversion**. Sprint 16 leaves that contract unchanged — no double-
conversion can occur.

The fallback-vs-WNTR parity tests for every US fixture confirm both
back-ends land on the same dimensions and demand sums to within
float32 representation precision.

## Shipped US fixtures

| Fixture                                 | Topology                              | Units family | Notes                                       |
|------------------------------------------|----------------------------------------|--------------|---------------------------------------------|
| `epanet_reference_loop_gpm.inp`          | 1 reservoir + 4 junctions, 5 pipes    | GPM/ft/in    | Looped distribution, mirrors SI loop shape  |
| `epanet_reference_pump_gpm.inp`          | 1 reservoir + 2 junctions, 1 pipe + HEAD pump | GPM/ft/in | Quadratic-recoverable curve points          |
| `epanet_reference_tcv_gpm.inp`           | 1 reservoir + 2 junctions, 1 pipe + TCV | GPM/ft/in  | Tests `K` is not scaled by `head_to_m`      |

The optional PRV / POWER US fixtures listed in the task spec are
exercised by tmp-path fixtures inside `tests/dphm/test_inp_us_fixtures.py`
(`test_prv_setting_under_us_units_converts_feet_of_head_to_metres`
and `test_power_pump_nominal_flow_uses_converted_us_demand`) rather
than as shipped files; this keeps the on-disk fixture count small
while still pinning the conversion contract for both surrogates.

## Solve / parity evidence

Run-time evidence captured during validation:

```text
$ python -m pytest tests/dphm/test_inp_us_fixtures.py -q
25 passed in 5.51s

# Per-fixture solve dump (fallback parser):
loop_gpm  : nodes=5 edges=5 res_norm=7.851e-10  converged=True
pump_gpm  : nodes=3 edges=2 res_norm=9.992e-16  converged=True
tcv_gpm   : nodes=3 edges=2 res_norm=9.992e-16  converged=True

# WNTR-parsed Networks of the same fixtures:
loop_gpm  : nodes=5 edges=5 res_norm=7.851e-10  converged=True
pump_gpm  : nodes=3 edges=2 res_norm=9.992e-16  converged=True
tcv_gpm   : nodes=3 edges=2 res_norm=9.992e-16  converged=True
```

Fallback and WNTR produce identical float32 lengths, diameters,
demand sums, and pump coefficients on each shipped US fixture.

## Tests added / updated

* `tests/dphm/test_inp_unit_systems.py` (new, 15 tests)
  * 10-parameter parametrised conversion constant check across
    every supported unit (LPS, LPM, MLD, CMH, CMD, GPM, CFS, MGD,
    IMGD, AFD)
  * Supported-unit set membership
  * Case-insensitive lookup
  * Unknown-token `ValueError`
  * `CMS` deprecation (no longer in the supported set)
  * US/SI cross-ratio sanity (e.g. `1 CFS ≈ 28.316846592 L/s`)
* `tests/dphm/test_inp_us_fixtures.py` (new, 25 tests)
  * Each US fixture exists, loads, has expected node/edge counts
  * Length / diameter / head / demand conversions to SI
  * HEAD curve quadratic recovery after (GPM, ft) → (m³/s, m)
    conversion
  * Analytic and autograd Newton convergence
  * Fallback-vs-WNTR parity on each shipped US fixture (skipped
    if WNTR is not installed)
  * Heads parity on loop fixture after analytic solve
  * POWER pump nominal-flow anchor uses *converted* demand
  * PRV setting converts ft of head → m
  * TCV setting `K` is not scaled by the unit system
* `tests/dphm/test_inp_network_io.py`
  * Replaced `test_us_customary_flow_unit_raises` with
    `test_us_customary_flow_unit_now_loads_in_fallback`, which
    asserts the fixture *parses* and produces the expected SI
    dimensions after conversion.

All previous SI-family fixture / pump / valve tests pass unchanged.

## Validation commands and results

```text
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
607 passed, 1 skipped, 3 warnings in 101.46s

$ python -m pytest tests -q
615 passed, 1 skipped in 102.x s

$ python -m compileall src tests
Listing 'src' / 'tests'... (no errors)

$ git status --short
A   SPRINT16_REPORT.md
M   docs/epanet-inp-import.md
A   docs/examples/epanet_reference_loop_gpm.inp
A   docs/examples/epanet_reference_pump_gpm.inp
A   docs/examples/epanet_reference_tcv_gpm.inp
M   src/aquaoptima/dphm/inp_io.py
M   tests/dphm/test_inp_network_io.py
A   tests/dphm/test_inp_unit_systems.py
A   tests/dphm/test_inp_us_fixtures.py
```

(Final numbers re-confirmed in the validation block below.)

## Compatibility notes

* Existing SI fixtures (`epanet_reference_loop.inp`,
  `epanet_reference_pump.inp`, `epanet_reference_power_pump.inp`,
  `epanet_reference_prv.inp`, `epanet_reference_tcv.inp`) load
  bit-for-bit identically; their associated tests pass unchanged.
* The WNTR adapter is unchanged structurally. WNTR's own conversion
  to SI already covers every flow-unit family, so no double
  conversion is applied to WNTR-parsed networks.
* Public API additions: `EpanetUnitSystem`, `resolve_unit_system`,
  and `SUPPORTED_FLOW_UNITS` are added to `__all__` so downstream
  callers can audit the manifest themselves.
* Public API removal: the silent alias `CMS` is no longer accepted.
  Fixtures using `CMS` (none ship in this repo) will now raise
  `ValueError`. This is intentional — `CMS` is not in the EPANET
  2.2 grammar.
* `_resolve_demand_factor` was a private helper; it has been
  removed in favour of `resolve_unit_system(...).flow_to_m3s`.
  No public callers exist.

## Known limitations

* `POWER` pumps remain a *conservative* quadratic surrogate, not a
  faithful constant-power conversion. Sprint 16 only ensures the
  surrogate's nominal-flow anchor and HP→kW conversion are correct
  under US-customary fixtures; the surrogate's off-design behaviour
  carries the same caveats documented in Sprint 14.
* `PRV` valves remain a *pressure-boundary* surrogate, not an
  active flow / pressure regulator. Sprint 16 only ensures the
  setting is converted from feet of head → m under US fixtures;
  the surrogate's limitations are unchanged from Sprint 15.
* `TCV` valves remain a *minor-loss-equivalent* resistance
  surrogate. Sprint 16 only ensures the diameter conversion is
  correct under US fixtures; the surrogate's off-design behaviour
  is unchanged from Sprint 15.
* Pressure-bar / psi units (where some EPANET-derived tools store
  PRV setpoints in bar rather than head units) are not supported.
  EPANET 2.2's `[OPTIONS] Pressure` directive is documented but
  this parser does not consume it.
* No new pump / valve forms (`FCV`, `PSV`, `PBV`, `GPV`, `SPEED`)
  are added; the Sprint 15 deferred-features list still applies.
* The parser still rejects any non-Hazen-Williams `[OPTIONS]
  Headloss` value — Darcy-Weisbach support is deferred.

## Verdict

**APPROVED.**

All Sprint 16 hard gates are met:

| Gate                                                | Status |
|-----------------------------------------------------|--------|
| targeted pytest exits 0                             | ✅ 607 passed, 1 skipped |
| full pytest exits 0                                 | ✅ 615 passed, 1 skipped |
| compileall exits 0                                  | ✅      |
| SPRINT16_REPORT.md exists                           | ✅ (this file) |
| all supported unit conversion constants tested      | ✅ 10/10 |
| GPM loop, pump, and TCV fixtures load and solve     | ✅      |
| existing SI fixture behavior still passes           | ✅      |
| HEAD pump tests still pass                          | ✅      |
| POWER pump tests still pass                         | ✅      |
| PRV/TCV valve tests still pass                      | ✅      |
| WNTR optional tests skip/pass cleanly               | ✅ (WNTR installed; parity passes) |
| no secret strings introduced                        | ✅      |
| git status contains only intended Sprint 16 changes | ✅      |
| fallback-vs-WNTR parity on US fixtures              | ✅ 3/3 |

## Sprint 17 recommendation

Recommended scope: **WNTR HEAD-pump curve point parity under US flow
units, and parity tests on the shipped US fixtures through the WNTR
adapter on a Linux runner without WNTR installed.**

Concretely:

1. Add a CI matrix entry (or doc-only `pip uninstall wntr` step) that
   verifies the fallback parser still loads every shipped US fixture
   cleanly when WNTR is *absent*, complementing the WNTR-installed
   parity already covered in Sprint 16.
2. Add fallback parser support for `[OPTIONS] Pressure` (psi / bar /
   metres / kPa). This is orthogonal to flow units — EPANET allows a
   PRV setting in either pressure or head units depending on
   `Pressure` — and is the next mechanical conversion gap before
   the next physics extension.
3. Continue deferring pump `SPEED`, `LINEAR`, and multi-point
   efficiency forms; defer `FCV` / `PSV` / `PBV` / `GPV` valves.
4. Continue deferring Darcy-Weisbach head loss.
5. Continue deferring any control / write path; the loader is read-
   only by design.

No production / savings claims. No ONNX / TensorRT / Jetson work. No
real PLC/PAC/SCADA adapter. No dPL parameter learning. No Sprint 17
implementation in this commit.
