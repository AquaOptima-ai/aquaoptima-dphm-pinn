# EPANET `.inp` Topology Import (Sprint 11–23)

Sprint 11 extends the dPHM topology loader stack with optional
EPANET-style `.inp` import, alongside the Sprint 8 JSON loader.
Sprint 12 adds HEAD-curve pump translation to the fallback parser
(see "Pump HEAD curves" below). Sprint 13 brings the optional
WNTR-backed parser into parity with the fallback parser for the same
HEAD-curve pumps. Sprint 14 adds `POWER`-pump support to both
back-ends via a bounded quadratic surrogate (see "POWER pumps"
below). Sprint 15 adds conservative `[VALVES]` translation for the
two steady-state-compatible forms `PRV` and `TCV` (see "Valves"
below). Sprint 16 widens the fallback parser to handle the
US-customary EPANET flow-unit family (`GPM`, `CFS`, `MGD`, `IMGD`,
`AFD`) on top of the SI family (see "Unit conventions" below).
Sprint 17 adds explicit `[OPTIONS] Pressure` parsing so PRV settings
can be declared in psi / kPa / bar / metres / feet independently of
the flow-unit family (see "Pressure units" below). Sprint 18 adds
fallback support for the `[OPTIONS] Demand Multiplier` directive
(see "Demand multiplier" below). Sprint 19 adds fallback support for
the `[OPTIONS] Specific Gravity` directive and propagates the fluid
density ratio to PRV pressure-unit conversions (for `PSI`/`KPA`/`BAR`)
and to the POWER pump surrogate (see "Specific gravity" below).
Sprint 20 adds fallback support for the `[OPTIONS] Viscosity`
directive as a parser-only compatibility feature; the dPHM core uses
Hazen-Williams head loss, which has no viscosity term, so the
directive is parsed and validated but never propagated to any
hydraulic field (see "Viscosity" below).
Sprint 21 makes the fallback parser's ignored-section contract
*explicit*: the public `IGNORED_SECTIONS` frozenset enumerates every
EPANET section the parser deliberately treats as a silent no-op
(`[TIMES]`, `[REPORT]`, `[CONTROLS]`, `[RULES]`, `[EMITTERS]`,
`[QUALITY]`, `[SOURCES]`, `[REACTIONS]`, `[MIXING]`, plus the inert
layout sections), and ships explicit tests pinning the invariance
that adding any of those sections to a fixture leaves the loaded
`Network` byte-for-byte unchanged (see "Ignored sections" below).
Sprint 22 narrows the Sprint 21 contract for `[STATUS]`: the
fallback parser now actively validates `[STATUS]` rows so EPANET-
exported files that declare explicit `<link_id> OPEN` rows load
without pretending to implement closed-link or active status physics
(see "Explicit [STATUS] no-op rows (Sprint 22)" below).
Sprint 23 builds on Sprint 22 by surfacing accepted `[STATUS] OPEN`
rows as a read-only diagnostics container (`EpanetImportDiagnostics`),
accessed via the new `load_inp_diagnostics(path)` accessor or via
`load_network_from_inp(path, return_diagnostics=True)`. Diagnostics
are hydraulically inert — the returned `Network` is unchanged — and
the Sprint 22 rejection behaviour for status-changing rows is
preserved (see "Read-only [STATUS] diagnostics (Sprint 23)" below).
The public entry point is one function:

```python
from aquaoptima.dphm import load_network_from_inp

network = load_network_from_inp(
    "docs/examples/epanet_reference_loop.inp",
    parser="auto",        # "auto" | "fallback" | "wntr"
    units="si",           # only "si" supported in Sprint 11
    default_c_factor=130, # used when a pipe row omits roughness
)
```

`load_network_from_inp` returns the same `aquaoptima.dphm.Network`
dataclass every other loader and fixture produces — so any code that
already consumes a `Network` from the JSON loader, the hand-built
fixtures, or `make_grid_network` works with an INP-loaded network
unchanged.

This is **topology import only**. The loader does not:

- start or talk to an EPANET binary / runtime;
- run a hydraulic simulation;
- bind PLC / PAC / SCADA tags (that responsibility stays in
  `aquaoptima.dataio.tag_map`);
- provide any write or control path.

See `docs/safety-boundary.md` for the full safety / boundary diagram.

## Back-ends

| `parser`     | Behaviour                                                                                                         |
|--------------|-------------------------------------------------------------------------------------------------------------------|
| `"auto"`     | Prefer the WNTR back-end if `wntr` is importable, otherwise use the built-in fallback parser. **Default.**        |
| `"fallback"` | Always use the built-in fallback parser. Dependency-free.                                                          |
| `"wntr"`     | Use the upstream [WNTR](https://github.com/USEPA/WNTR) loader. Raises `ImportError` if `wntr` is not installed.    |

WNTR is an **optional** dependency. The base test suite and base
install never require it. To opt in:

```bash
pip install 'aquaoptima-dphm-pinn[epanet]'    # pulls in wntr>=1.0
# or
pip install wntr
```

When WNTR is not installed, the optional test module
`tests/dphm/test_wntr_optional_import.py` skips cleanly via
`pytest.importorskip("wntr")`.

## Fallback parser — supported INP subset

The fallback parser is intentionally small. It supports the subset
needed to load steady-state reference fixtures.

### Honoured sections

| Section          | Notes                                                                                                    |
|------------------|----------------------------------------------------------------------------------------------------------|
| `[JUNCTIONS]`    | id, elevation, baseline demand. Pattern column is ignored (steady-state).                                |
| `[RESERVOIRS]`   | id, head. Pattern column is ignored.                                                                     |
| `[TANKS]`        | id, elevation, init-level → mapped to a fixed-head boundary at `elev + init_level`. Curves ignored.       |
| `[PIPES]`        | id, node1, node2, length, diameter, roughness, optional minor-loss (ignored), optional status (`OPEN`).  |
| `[OPTIONS]`      | `Units` (flow-unit family), `Headloss` (must be `H-W`), `Pressure` (Sprint 17: optional pressure-display unit for PRV settings), `Demand Multiplier` (Sprint 18: optional non-negative scalar that scales every junction's baseline demand at load time), `Specific Gravity` (Sprint 19: optional strictly-positive density ratio that scales PRV pressure conversions for `PSI`/`KPA`/`BAR` and the POWER pump surrogate's effective density), and `Viscosity` (Sprint 20: optional strictly-positive kinematic-viscosity ratio — parsed and validated but NOT propagated to any hydraulic field because the dPHM core is Hazen-Williams). |
| `[PUMPS]`        | Sprint 12: `HEAD curve_id` pump rows translate via least-squares curve fit. Sprint 14: `POWER value` pump rows translate via the constant-power surrogate. |
| `[VALVES]`       | Sprint 15: `PRV` and `TCV` valve rows translate via the conservative pressure-boundary / resistance surrogates. See "Valves" below.   |
| `[CURVES]`       | Sprint 12: pump HEAD curves are parsed into `(Q, H)` points. The X column is converted to m³/s using the file's flow-unit factor. Unused curves are tolerated. |
| `[TITLE]`, `[COORDINATES]`, `[PATTERNS]`, `[REPORT]`, `[TIMES]`, `[END]`, ... | Silently ignored.                                  |

### Sections that fail loudly

| Section          | Reason                                                                                                                                |
|------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `[PUMPS]` (unsupported keyword) | Raises `ValueError`. The parser supports `HEAD curve_id` (Sprint 12) and `POWER value` (Sprint 14). `SPEED` and any custom keyword still raise. |
| `[VALVES]` (unsupported type)   | Raises `ValueError` with the valve id. Sprint 15 supports `PRV` and `TCV` only; `FCV`, `PSV`, `PBV`, and `GPV` are deferred (they impose constraints — flow setpoints, pressure-sustaining / breaker, custom head-loss curves — that don't map cleanly onto the steady-state core). |

As of Sprint 15, the WNTR back-end mirrors the fallback parser's
valve translation: `PRV` and `TCV` route through the same
`translate_valve_to_surrogate` helper, and other valve types raise
a clear `ValueError` referencing the valve id. As of Sprint 14, the
WNTR back-end translates both HEAD-curve and POWER pumps; any
remaining pump type (custom strings, future EPANET extensions)
raises `ValueError` from the WNTR adapter, matching the fallback
parser's behaviour.

## Pump HEAD curves (Sprint 12)

EPANET pump rows can specify their characteristic as a `HEAD` curve:

```text
[PUMPS]
;ID    Node1   Node2   Parameters
 PU1   R1      J1      HEAD   PUMPCURVE1

[CURVES]
;ID          X-Value   Y-Value
 PUMPCURVE1   0.0      45.00
 PUMPCURVE1  20.0      44.68
 PUMPCURVE1  50.0      43.00
```

The Sprint 12 fallback parser translates each such pump into a
single dPHM pump edge via the helper
`aquaoptima.dphm.fit_pump_head_curve`. The fit is a 3-parameter
least-squares solve against the dPHM affinity quadratic at the
static nominal speed `s = 1`:

```
H(Q) = a0 + a1·Q + a2·Q²
```

The X-column of the curve is converted from the file-declared
flow unit (e.g. L/s under `LPS`) to m³/s **before** fitting, so the
resulting `[a0, a1, a2]` are directly compatible with the dPHM
pump-affinity API (which consumes flows in m³/s).

`fit_pump_head_curve` returns the coefficients together with a
diagnostics dict:

| key              | meaning                                                                  |
|------------------|--------------------------------------------------------------------------|
| `a0`, `a1`, `a2` | Fitted dPHM quadratic coefficients (at `s = 1`).                         |
| `rmse`           | Root-mean-square residual of the fit against the input points (m).      |
| `max_abs_error`  | Maximum absolute residual of the fit (m).                                |
| `num_points`     | Number of `(Q, H)` points consumed.                                      |
| `q_min`, `q_max` | Flow domain spanned by the input points (m³/s).                          |
| `droop_ok`       | `1.0` iff `a2 ≤ 0` (physically sensible centrifugal-pump droop).         |

### Constraints and failure modes

The fitter and pump-row parser fail loudly on input that cannot
sustain a credible dPHM pump model:

- Fewer than 3 curve points → `ValueError` (quadratic fit is
  under-determined).
- Negative or non-finite flow values → `ValueError`.
- Non-positive or non-finite head values → `ValueError`.
- Fitted shut-off head `a0 ≤ 0` → `ValueError` (no curve EPANET
  considers valid would produce this; the data is almost certainly
  mislabeled).
- Pump row references a curve id not declared under `[CURVES]` →
  `ValueError`.
- Pump row uses any keyword other than `HEAD` (e.g. `POWER`,
  `SPEED`) → `ValueError`.
- Duplicate pump id (with another pump or with a pipe) → `ValueError`.

The fitter additionally records `droop_ok = 0` when the fit produces
`a2 > 0` (head rises with flow). Sprint 12 *accepts* such fits — the
solver does not require `a2 ≤ 0` — but the diagnostic is exposed so
downstream code can warn on physically suspicious curves.

### Edge ordering

Pipes come first, then pumps, in file order within each section.
A file with `[PIPES]` rows `P1, P2` followed by `[PUMPS]` rows
`PU1, PU2` produces an edge index `[P1, P2, PU1, PU2]`. The
`pipe_mask` / `pump_mask` partition is preserved exactly.

### Shipped pump fixture

`docs/examples/epanet_reference_pump.inp` is a tiny three-node
topology (one reservoir, one pump, one pipe, two junctions) with a
6-point HEAD curve. The curve points lie exactly on
`H = 45 − 800·Q²` so the fit recovers `[a0, a1, a2] = [45, 0, −800]`
to float-precision tolerances. The network solves with
`newton_solve(..., jacobian_mode="analytic")` to a residual norm at
or below the working tolerance.

## POWER pumps (Sprint 14)

EPANET also accepts a constant-power pump declaration:

```text
[PUMPS]
;ID    Node1   Node2   Parameters
 PU1   R1      J1      POWER   7.5     ; 7.5 kW shaft power
```

A constant-power pump describes its shaft power as

```
P = rho * g * Q * H
=> H = P / (rho * g * Q)
```

That curve is **hyperbolic** in `Q` and **singular** at `Q -> 0`,
which is fundamentally incompatible with the dPHM core's quadratic
pump characteristic `H(Q, s) = a0 s² + a1 s Q + a2 Q²`. Sprint 14
therefore does **not** translate POWER pumps faithfully. Instead it
ships a deliberately conservative, bounded **surrogate**:

`aquaoptima.dphm.fit_power_pump_surrogate(power_kw, nominal_flow_m3s,
*, shutoff_multiplier=1.5)` returns `[a0, a1, a2]` constructed so:

1. The surrogate passes through one anchor operating point
   `(Q_nom, H_nom)` where `H_nom = P_watts / (rho * g * Q_nom)`.
2. The shut-off head is fixed at `a0 = shutoff_multiplier * H_nom`
   (default 1.5×, i.e. 50% above the operating head).
3. The linear term `a1 = 0` — a constant-power declaration carries
   no information about it.
4. The quadratic term `a2 = (H_nom - a0) / Q_nom²` is therefore
   strictly negative (drooping curve) whenever
   `shutoff_multiplier > 1`.

Internally the helper uses `rho = 1000 kg/m³` and `g = 9.80665 m/s²`,
matching EPANET's defaults.

### Nominal-flow anchor

The most important input to the surrogate is the nominal-flow
anchor `Q_nom`. The fallback parser and the WNTR adapter both pick
it from the loaded network in the same order:

1. **Downstream node's base demand**, if positive — when the pump
   directly feeds a single consumer.
2. **Total positive demand** across the network, if positive —
   when the pump is the only source.
3. **1 L/s default**, as a finite last-resort anchor. The
   surrogate diagnostics record `nominal_flow_m3s = 1e-3` so
   downstream code can detect this branch.

### Conventions and assumptions

| Assumption                            | Reason                                                                            |
|---------------------------------------|-----------------------------------------------------------------------------------|
| EPANET `POWER` value is in **kW**     | The standard EPANET SI convention. Both parsers convert to W internally.          |
| WNTR `Pump.power` is in **W**         | WNTR normalises all hydraulic quantities to SI on load. We divide by 1000 to get kW. |
| `rho = 1000 kg/m³`, `g = 9.80665 m/s²` | Matches EPANET's internal pump-energy calculation.                                |
| `shutoff_multiplier = 1.5`            | A conservative droop default. Tuneable via the keyword argument.                  |

### `fit_power_pump_surrogate` diagnostics

| key                  | meaning                                                  |
|----------------------|----------------------------------------------------------|
| `approximation`      | Always `"constant_power_surrogate"`.                     |
| `power_kw`           | Input shaft power in kW.                                 |
| `nominal_flow_m3s`   | Anchor flow used to compute `H_nom`.                     |
| `head_at_nominal_m`  | `H_nom = P / (rho * g * Q_nom)`.                         |
| `shutoff_head_m`     | `a0 = shutoff_multiplier * H_nom`.                       |
| `shutoff_multiplier` | The ratio `a0 / H_nom`.                                  |
| `a0`, `a1`, `a2`     | Resulting dPHM quadratic coefficients.                   |

No `rmse` is reported: the surrogate is constructed analytically
from one point and a shape choice, not fitted to multiple points.

### Failure modes

- `power_kw <= 0` or non-finite → `ValueError`.
- `nominal_flow_m3s <= 0` or non-finite → `ValueError`.
- `shutoff_multiplier <= 1` → `ValueError` (would not produce a
  drooping curve).
- Fallback parser: `POWER` value column is non-numeric or
  non-positive → `ValueError`.
- WNTR adapter: missing `power` attribute, non-numeric, or
  non-positive → `ValueError`.

### What the surrogate is NOT

- It is **not** a faithful translation of the constant-power
  declaration away from `Q_nom`. The product `Q * H(Q)` is not
  constant under the surrogate; only the operating point matches.
- It is **not** a substitute for a real HEAD curve. If the source
  network has a known pump curve, replace the `POWER` row with a
  `HEAD curve_id` declaration and the matching `[CURVES]` rows.
- It does **not** model power loss, efficiency, or motor curves.

### Shipped POWER fixture

`docs/examples/epanet_reference_power_pump.inp` is a three-node
topology (one reservoir, one pump, one pipe, two junctions). The
pump declares `POWER 7.5` (kW). With the default
`shutoff_multiplier = 1.5` and the anchor flow `Q_nom = 15 L/s`
(total positive demand), the surrogate evaluates to:

- `H_nom = 7500 / (1000 * 9.80665 * 0.015) ≈ 50.99 m`
- `a0 = 1.5 * H_nom ≈ 76.48 m`
- `a1 = 0`
- `a2 = (H_nom - a0) / Q_nom² ≈ -113,288 m·s²/m⁶`

The network solves with `newton_solve(jacobian_mode="analytic")` to a
residual norm at or below the working tolerance, and round-trips
through `generate_physics_consistent_telemetry`.

## Valves (Sprint 15)

EPANET valve rows live in a `[VALVES]` section:

```text
[VALVES]
;ID  Node1  Node2  Diameter  Type  Setting  MinorLoss
 V1  J1     J2     150       PRV   35       0
 V2  J2     J3     150       TCV   2.5      0
```

The dPHM steady-state core does not model active valve-control
state as a first-class hydraulic constraint. Sprint 15 therefore
imports the two **conservative, steady-state-compatible** valve
forms via a deliberately approximate translation:

- `PRV` — pressure-reducing valve — translated as a **pressure-
  boundary surrogate**.
- `TCV` — throttle control valve — translated as a **resistance
  surrogate** (an equivalent Hazen-Williams pipe edge).

Other valve forms (`FCV` flow-control, `PSV` pressure-sustaining,
`PBV` pressure-breaker, `GPV` general-purpose) raise a clear
`ValueError` with the valve id.

The public translator is `translate_valve_to_surrogate(...)`. The
public TCV helper is `fit_tcv_resistance_surrogate(...)`. Both are
re-exported from `aquaoptima.dphm`.

### PRV — pressure-boundary surrogate

For a `PRV` row `V1 N1 N2 D PRV setting K_minor`:

1. The downstream node `N2` is pinned as a fixed-head boundary at
   `head = elev(N2) + setting`. The setting is interpreted in
   metres of pressure head (the EPANET SI convention).
2. The valve edge itself becomes a short, permissive pipe-like
   resistance edge (`length = max(2 * D, 1 m)`, file diameter,
   `c_factor = 130`).
3. The translation records `approximation =
   "prv_pressure_boundary_surrogate"` in the helper's diagnostics.

Hard constraints:

- `N2` must not already be a fixed-head boundary (reservoir or
  tank). Overwriting an existing boundary would silently change
  the network's physics, so the parser refuses with a clear error
  referencing the valve id.
- `setting` must be strictly positive and finite.
- `diameter` must be strictly positive and finite.

**What the PRV surrogate is NOT:**

- It does **not** enforce active flow / pressure regulation. Mass
  balance on the now-fixed downstream node is dropped from the
  residual, so the flow through the PRV edge is determined by the
  upstream pressure budget, *not* by downstream demand. The two
  may differ.
- It does **not** model the EPANET active-control state machine
  (active / open / closed branches).
- The shipped fixture `epanet_reference_prv.inp` deliberately uses
  a long, narrow upstream pipe so the upstream pressure budget
  caps the through-valve flow close to the downstream demand —
  this is the recommended pattern when building hand-crafted PRV
  fixtures.

### TCV — resistance surrogate

For a `TCV` row `V1 N1 N2 D TCV K K_minor`:

1. `K_total = K + K_minor`.
2. Anchor flow `Q_nom` = network's total positive demand (or 1 L/s
   default if the network has no positive demand; the diagnostic
   field `nominal_flow_m3s` records the actual value used).
3. Minor-loss head loss at anchor:
   `h_minor = K_total * Q_nom² / (2 g A²)`, where `A = π D² / 4`.
4. Equivalent Hazen-Williams pipe length so the HW head loss at
   `Q_nom` matches `h_minor`:
   `L_eff = h_minor / (10.67 * Q_nom^1.852 / (C^1.852 * D^4.87))`.
5. The surrogate edge has `length = L_eff` (floored at 1e-6 m to
   keep the `Network` invariants intact), the file diameter, and
   the default `c_factor = 130`.
6. The translation records `approximation =
   "tcv_resistance_surrogate"` and the chosen anchor in the
   helper's diagnostics.

Hard constraints:

- `setting` (K) must be non-negative and finite.
- `K_minor` must be non-negative and finite.
- `diameter` must be strictly positive and finite.

**What the TCV surrogate is NOT:**

- HW scales as `|Q|^1.852` while the true minor-loss term scales
  as `K * Q²`. The two match exactly at `Q_nom` and diverge as
  `Q` moves away from the anchor. The surrogate is therefore a
  *single-anchor* approximation, not a faithful valve model.
- It does not model the valve as an active control element. The
  effective length is fixed at parse time and the dPHM solver
  treats the edge as an ordinary pipe.

### `fit_tcv_resistance_surrogate` diagnostics

| key                  | meaning                                                  |
|----------------------|----------------------------------------------------------|
| `approximation`      | Always `"tcv_resistance_surrogate"`.                     |
| `valve_type`         | Always `"TCV"`.                                          |
| `diameter_m`         | Input diameter in metres.                                |
| `setting`            | Input minor-loss coefficient `K`.                        |
| `minor_loss`         | Input `K_minor` column.                                  |
| `nominal_flow_m3s`   | Anchor flow used for `L_eff`.                            |
| `effective_length_m` | Resulting `L_eff` (after the 1e-6 m floor).              |
| `effective_c_factor` | Roughness used for the surrogate pipe.                   |
| `head_loss_at_nominal_m` | `K_total * V_nom² / (2 g)` at the anchor.             |
| `limitations`        | Free-text reminder of the off-design divergence.         |

### `translate_valve_to_surrogate` failure modes

- Unsupported valve types (`FCV`, `PSV`, `PBV`, `GPV`): `ValueError`
  tagged with the valve id and the list of supported types.
- Unknown valve type string: `ValueError` tagged with the valve id
  and the literal token from the file.
- Non-positive / non-finite `diameter_m`: `ValueError`.
- Non-positive / non-finite PRV `setting`: `ValueError`.
- Negative / non-finite TCV `setting` or `minor_loss`: `ValueError`.
- PRV `downstream_elev_m` is non-finite: `ValueError`.
- TCV without a `nominal_flow_m3s`: `ValueError` (the parser always
  supplies one — at worst the 1 L/s default).
- PRV whose downstream is already a fixed-head boundary: the
  *parser* raises before calling the translator, because that
  state cannot be represented without overwriting an existing
  reservoir / tank.

### Shipped valve fixtures

- `docs/examples/epanet_reference_tcv.inp` — three-node TCV
  fixture: 50 m reservoir → TCV (K = 2.5, 150 mm) → J1 → 200 m
  pipe → J2 (15 L/s consumer). Solves with analytic Newton; the
  TCV head loss at the solved flow matches the closed-form
  minor-loss head loss at `Q_nom = 15 L/s`.
- `docs/examples/epanet_reference_prv.inp` — four-node PRV
  fixture: 50 m reservoir → 2000 m / 80 mm pipe → J1 → PRV (setting
  20 m, 80 mm) → J2 (pinned at 20 m) → 200 m / 80 mm pipe → J3
  (2 L/s consumer). Solves with analytic Newton; J2's head equals
  the PRV setting. The flow through the PRV does *not* equal the
  downstream demand — that is the documented pressure-boundary
  limitation, asserted explicitly in the test suite.

### WNTR-side valve translation

When `parser="wntr"` (or `parser="auto"` with WNTR installed), the
adapter iterates `wn.valve_name_list` and routes each valve via
`_wntr_translate_valve`, which calls the same
`translate_valve_to_surrogate` helper the fallback parser uses.

The adapter touches only the **stable** WNTR public surface:

| WNTR attribute / method               | Use                                                     |
|---------------------------------------|---------------------------------------------------------|
| `wn.valve_name_list`                  | Iterate valves                                          |
| `wn.get_link(name)`                   | Resolve a valve by name                                 |
| `valve.start_node_name` / `.end_node_name` | Edge endpoints                                     |
| `valve.valve_type`                    | `"PRV"` / `"TCV"` / unsupported discrimination          |
| `valve.diameter`                      | SI metres                                               |
| `valve.initial_setting` (preferred) / `valve.setting` (fallback) | Numeric setting (m of head for PRV, K for TCV) |
| `valve.minor_loss`                    | Additional minor-loss coefficient                       |

WNTR itself refuses `PRV` / `PSV` / `FCV` valves directly connected
to a reservoir or tank (it requires a separating pipe). Author your
fixtures with a buffer pipe upstream of those valve types, or use
the fallback parser which has no such restriction.

WNTR-side fixture parity:

- The shipped TCV and PRV fixtures load identically through both
  back-ends.
- Solved heads and flows agree to 1e-5 absolute.
- Unsupported valve types raise `ValueError` referencing the valve
  id from both back-ends.

## WNTR-backed pump translation (Sprint 13)

When `parser="wntr"` (or `parser="auto"` with WNTR installed), the
adapter iterates `wn.pump_name_list` and routes each pump by its
`pump_type`:

- `"HEAD"` pumps share the fallback parser's `fit_pump_head_curve`
  helper. The two back-ends therefore produce numerically
  identical pump coefficients for the same curve points.
- `"POWER"` pumps (Sprint 14) share the fallback parser's
  `fit_power_pump_surrogate` helper with the same downstream- /
  total-positive-demand anchor rule. WNTR exposes the constant
  power as `Pump.power` in SI watts; the adapter divides by 1000
  before invoking the surrogate.

Any other `pump_type` raises `ValueError`.

### Unit conversion in the WNTR path

WNTR normalises all hydraulic quantities to its internal SI
representation when a `WaterNetworkModel` is loaded — regardless of
the file's `[OPTIONS] Units` directive. That means
`pump.get_pump_curve().points` are already `(Q in m³/s, H in m)`
when our adapter reads them. The WNTR path therefore **does not**
apply the fallback parser's `[OPTIONS] Units`-driven `demand_factor`
to curve points; doing so would double-convert and yield
nonsense coefficients. The fallback parser performs the conversion
itself; the WNTR adapter trusts WNTR's conversion.

### WNTR API surface assumed

The adapter touches only the WNTR public surface that has been
stable across recent WNTR releases:

| WNTR attribute / method               | Use                                                         |
|---------------------------------------|-------------------------------------------------------------|
| `wn.pump_name_list`                   | Iterate pumps                                               |
| `wn.get_link(name)`                   | Resolve a pump by name                                      |
| `pump.start_node_name` / `.end_node_name` | Edge endpoints                                          |
| `pump.pump_type`                      | `"HEAD"` / `"POWER"` discrimination (string-typed)         |
| `pump.get_pump_curve()`               | Returns a `Curve` object for HEAD-curve pumps               |
| `pump.base_speed`                     | Static nominal speed; defaults to `1.0` if missing or bad   |
| `Curve.points`                        | List of `(Q, H)` tuples in SI                               |
| `Curve.curve_type`                    | Sanity check — must be `"HEAD"` when present                |
| `wn.valve_name_list`                  | Reject valves                                               |

Sprint 14: in addition, the adapter touches `pump.power` (SI watts)
for `pump_type == "POWER"` pumps. Any other pump form
(multi-point efficiency, custom future strings) raises a clear
`ValueError` referencing the WNTR `pump_type`. Speed patterns
(`speed_pattern_name`) are silently ignored — the dPHM core is
steady-state, so only `base_speed` is consumed.

### Sprint 13 fixture parity

On `docs/examples/epanet_reference_pump.inp`, the WNTR-backed and
fallback parsers produce:

- Identical structural fields (`num_nodes`, `num_edges`,
  `num_fixed_heads`, `pipe_mask`, `pump_mask`).
- Pump coefficients agreeing to ~1e-6 absolute on `a0`/`a1` and
  ~1e-3 absolute on the large-magnitude `a2`.
- Solved heads and flows from `newton_solve(jacobian_mode="analytic")`
  agreeing to 1e-6 absolute.

## Unit conventions

Sprint 16 centralises every per-flow-unit conversion the fallback
parser needs into a single frozen dataclass,
`aquaoptima.dphm.inp_io.EpanetUnitSystem`, returned by
`resolve_unit_system(unit_name)`. The parser passes that manifest
to every section that scales a file-declared value, so no ad-hoc
unit constants are sprinkled across the parser body. Lookup is
case-insensitive (`gpm`, `GPM`, and `Gpm` all resolve to the same
manifest).

EPANET picks per-flow-unit conventions for length and diameter:

- **SI flow units** (`LPS`, `LPM`, `MLD`, `CMH`, `CMD`):
  length in metres, diameter in **millimetres**, head/elevation in
  metres. Supported.
- **US-customary flow units** (`CFS`, `GPM`, `MGD`, `IMGD`, `AFD`):
  length in feet, diameter in inches, head/elevation in feet.
  Supported from Sprint 16 onwards.

Flow-to-m³/s conversions implemented in the unit manifest. All
constants are exact (NIST conversion factors / EPANET 2.2 user
manual section 4.2):

| `Units` directive | factor (× → m³/s)                          |
|-------------------|---------------------------------------------|
| `LPS`             | `× 1e-3`                                    |
| `LPM`             | `× 1 / 60_000`                              |
| `MLD`             | `× 1000 / 86_400`                           |
| `CMH`             | `× 1 / 3600`                                |
| `CMD`             | `× 1 / 86_400`                              |
| `CFS`             | `× 0.3048³` (≈ 0.028316846592)              |
| `GPM`             | `× 0.003785411784 / 60` (≈ 6.30901964e-5)   |
| `MGD`             | `× 1e6 × 0.003785411784 / 86_400`           |
| `IMGD`            | `× 1e6 × 0.00454609 / 86_400`               |
| `AFD`             | `× 1233.48183754752 / 86_400`               |

Length / diameter / head conversions, also captured in the manifest:

| Family   | length     | diameter           | head/elevation | PRV setting    |
|----------|------------|--------------------|----------------|----------------|
| SI       | `× 1.0`    | `× 1e-3` (mm → m)  | `× 1.0`        | `× 1.0`        |
| US       | `× 0.3048` | `× 0.0254` (in → m)| `× 0.3048`     | `× 0.3048`     |

`TCV` settings (the dimensionless minor-loss coefficient `K`) and
the `MinorLoss` column are **never** scaled by the unit system.
`POWER` pump values are declared in **kW** under SI flow units and
**HP** under US flow units; the parser converts HP → kW using the
EPANET-internal constant `0.7457 kW/HP` before invoking the bounded
quadratic surrogate (`fit_power_pump_surrogate`).

If `[OPTIONS]` is absent or omits `Units`, the parser assumes the
EPANET default of `LPS`. If `Headloss` is not `H-W`, the parser
raises — the dPHM core is Hazen-Williams.

Unsupported tokens (e.g. `CMS`, `BARRELS`) raise a clear
`ValueError` listing the ten supported units.

## Pressure units (Sprint 17)

EPANET's `[OPTIONS]` section accepts an orthogonal `Pressure`
directive that selects the pressure-display unit used for pressure-
related fields, most importantly the `PRV` valve `Setting` column.
The flow-unit family alone does not pin the pressure unit: a GPM
network can still declare its PRV setting in psi, kPa, or metres of
head, and an LPS network can declare its setting in bar.

Sprint 17 captures every supported pressure unit in
`aquaoptima.dphm.inp_io.EpanetPressureUnit`, a frozen dataclass with
one field (`pressure_to_head_m`) that converts a file-declared
pressure to metres of water head:

```python
from aquaoptima.dphm.inp_io import (
    SUPPORTED_PRESSURE_UNITS,
    resolve_pressure_unit,
)

resolve_pressure_unit("PSI").pressure_to_head_m
# 0.7030695796...
```

Conversion factors. All Pa-pivot derivations use the EPANET pump-
energy constants `rho = 1000 kg/m³` and `g = 9.80665 m/s²`, so
`1 m of water head = 9806.65 Pa`:

| `Pressure` directive | factor (× → metres of water head)                |
|----------------------|--------------------------------------------------|
| `METERS`             | `× 1.0`                                          |
| `M`                  | `× 1.0` (alias for `METERS`)                     |
| `FEET`               | `× 0.3048`                                       |
| `FT`                 | `× 0.3048` (alias for `FEET`)                    |
| `KPA`                | `× 1000 / 9806.65` ≈ `0.10197162129779281`       |
| `PSI`                | `× 6894.757293168 / 9806.65` ≈ `0.7030695796`    |
| `BAR`                | `× 100000 / 9806.65` ≈ `10.197162129779281`      |

`SUPPORTED_PRESSURE_UNITS` is the tuple of the canonical (upper-case)
tokens the resolver accepts. Lookup is case-insensitive (`PSI`,
`psi`, and `Psi` all resolve to the same manifest entry).
Unsupported tokens (e.g. `PASCAL`, `MMHG`) raise a clear
`ValueError` listing the supported units.

### Parser semantics

- When `[OPTIONS] Pressure` is **present**, every PRV setting in the
  file is multiplied by `pressure_to_head_m` before being interpreted
  as a downstream fixed-head boundary. The flow-unit family's
  `head_to_m` factor is bypassed for PRV settings only.
- When `[OPTIONS] Pressure` is **absent**, the parser falls back to
  the Sprint 16 contract: PRV settings follow the flow-unit family's
  `pressure_setting_to_m` (= `head_to_m` — metres for SI flow units,
  feet for US flow units). Existing fixtures load unchanged.
- TCV settings (the dimensionless minor-loss coefficient `K`) and
  the `MinorLoss` column are **never** scaled by either the flow-unit
  manifest or the pressure-unit manifest. They remain dimensionless.
- Junction / reservoir / tank elevations and heads continue to use
  the flow-unit family's `head_to_m`. The pressure-unit manifest
  applies only to PRV setting columns.

### Shipped PSI fixture

`docs/examples/epanet_reference_prv_gpm_psi.inp` is a four-node
topology in GPM/ft/in with the PRV setting declared in PSI:

- `R1` reservoir at 164 ft (~50 m).
- `P1`: long, narrow upstream pipe (6562 ft, 3.15 in, C = 130).
- `V1`: PRV with setting **30 PSI**, 3.15 in diameter.
- `J2`: downstream of the PRV (pinned by the import).
- `P2`: short downstream pipe (656 ft, 3.15 in, C = 130).
- `J3`: 32 GPM consumer (~2 L/s).

The fallback parser converts the 30 PSI setting via the Sprint 17
pressure-unit manifest to ~21.09 m of water head — NOT via the
flow-unit family's feet → m factor, which would silently give
30 × 0.3048 = 9.144 m. The network solves with
`newton_solve(..., jacobian_mode="analytic")` to a residual norm
below the working tolerance.

### WNTR adapter behaviour

WNTR normalises all hydraulic quantities (including PRV settings) to
its internal SI representation when a `WaterNetworkModel` is loaded,
regardless of the source file's `[OPTIONS] Pressure` directive. The
WNTR adapter therefore **does not** apply a second pressure-unit
conversion in Sprint 17 — doing so would double-convert and yield
nonsense. The fallback parser performs the conversion itself; the
WNTR adapter trusts WNTR's conversion.

Implication: on a `[OPTIONS] Units GPM` / `[OPTIONS] Pressure PSI`
file, the two back-ends agree on the downstream-pinned fixed-head
value only when WNTR's `[OPTIONS] Pressure` interpretation matches
the dPHM pressure manifest. The shipped SI PRV fixture (with no
`Pressure` directive) demonstrates byte-for-byte fallback-vs-WNTR
parity on the pinned fixed-head value; for arbitrary `Pressure`
declarations, the parity is constrained by WNTR's own pressure-unit
table. The fallback parser remains the authoritative path for
Sprint 17 behaviour and is exercised by both shipped and tmp-path
test fixtures.

## Demand multiplier (Sprint 18)

EPANET's `[OPTIONS]` section accepts an optional `Demand Multiplier`
directive — a single non-negative scalar that scales every junction's
baseline demand at load time, regardless of the active flow-unit
family. The directive's option key is the only shipped EPANET option
whose canonical form spans two whitespace-separated tokens. The
fallback parser collapses extra whitespace and accepts any
case-insensitive spelling (`Demand Multiplier 2.0`,
`DEMAND  MULTIPLIER 2.0`, `demand multiplier 2.0`).

The public resolver is `resolve_demand_multiplier(opts)`:

```python
from aquaoptima.dphm.inp_io import resolve_demand_multiplier

resolve_demand_multiplier({})                              # 1.0 (default)
resolve_demand_multiplier({"DEMAND MULTIPLIER": "2.0"})    # 2.0
resolve_demand_multiplier({"DEMAND MULTIPLIER": "0"})      # 0.0 (allowed)
resolve_demand_multiplier({"DEMAND MULTIPLIER": "-1"})     # ValueError
```

### Parser semantics

- When `[OPTIONS] Demand Multiplier` is **present**, every junction's
  baseline demand is multiplied by the directive value **after** the
  flow-unit conversion:

  ```
  base_demand_m3s = raw_demand * flow_to_m3s * demand_multiplier
  ```

- When the directive is **absent**, the EPANET default of `1.0`
  applies; Sprint 11–17 behaviour on existing fixtures is preserved
  byte-for-byte.
- The multiplier scales **junction demands only**. Reservoir and tank
  fixed-head boundaries, pipe / pump / valve dimensions, pump `HEAD`
  curve points (`[CURVES]`), `TCV` settings (`K`), and the `MinorLoss`
  column are **never** touched.
- The POWER pump nominal-flow anchor sees the **multiplied** demand,
  because the anchor is resolved from the parser's normalised
  junction-demand list after the multiplier has been applied. A
  multiplier of `2.0` therefore doubles `Q_nom`, which halves
  `H_nom = P / (rho g Q_nom)` and halves the surrogate's shut-off
  head `a0`. The TCV resistance surrogate is similarly anchored on
  total positive demand and shifts accordingly.

### Validation

The resolver and the fallback parser fail loudly on:

- Negative multipliers → `ValueError` ("must be non-negative").
- Non-finite multipliers (NaN or Inf) → `ValueError` ("must be finite").
- Non-numeric multipliers → `ValueError` ("is not numeric").

`0.0` is **accepted**: the parser loads a network whose junctions all
have zero baseline demand. Whether such a network solves depends on
its topology — the parser will load it cleanly regardless.

### Shipped fixture

`docs/examples/epanet_reference_loop_gpm_demand_multiplier.inp` is a
GPM/ft/in copy of the Sprint 16 loop fixture with the single added
row `Demand Multiplier 2.0`. The fallback parser loads it with every
junction demand exactly twice that of `epanet_reference_loop_gpm.inp`,
while pipe and reservoir dimensions remain identical. The network
solves with `newton_solve(..., jacobian_mode="analytic")` to a
residual norm below the working tolerance.

### WNTR adapter behaviour

WNTR loads the `[OPTIONS] Demand Multiplier` directive into
`wn.options.hydraulic.demand_multiplier` and stores it as a separate
option; `Junction.base_demand` returns the **raw** baseline demand
without the multiplier applied (WNTR's internal simulator multiplies
later, but the dPHM core never invokes that simulator).

Sprint 18 therefore extracts the multiplier from
`wn.options.hydraulic.demand_multiplier` and applies it explicitly to
each junction's `base_demand` in the WNTR adapter. The fallback parser
and the WNTR adapter then produce identical demand sums on the shipped
GPM-with-multiplier fixture (asserted in the optional WNTR parity
test).

Existing WNTR fixtures (Sprints 11–17) do not declare a
`Demand Multiplier`, so WNTR defaults the option to `1.0` and the
adapter is a no-op for them — pre-Sprint-18 parity is preserved.

## Specific gravity (Sprint 19)

EPANET's `[OPTIONS]` section accepts an optional `Specific Gravity`
directive — a single strictly-positive scalar describing the ratio
of fluid density to that of water. The directive's option key is a
two-word form (mirroring `Demand Multiplier`); the fallback parser
collapses extra whitespace and accepts any case-insensitive spelling
(`Specific Gravity 0.85`, `SPECIFIC  GRAVITY 0.85`,
`specific gravity 0.85`).

The public resolver is `resolve_specific_gravity(opts)`:

```python
from aquaoptima.dphm.inp_io import resolve_specific_gravity

resolve_specific_gravity({})                             # 1.0 (default, water)
resolve_specific_gravity({"SPECIFIC GRAVITY": "2.0"})    # 2.0 (e.g. brine)
resolve_specific_gravity({"SPECIFIC GRAVITY": "0"})      # ValueError
resolve_specific_gravity({"SPECIFIC GRAVITY": "-1"})     # ValueError
```

### What specific gravity does scale

The fallback parser propagates the directive to the two places where
fluid density appears in the current importer / surrogates:

1. **PRV `[OPTIONS] Pressure` conversion for true pressure units.**
   When `[OPTIONS] Pressure` is one of `PSI`, `KPA`, or `BAR`, the
   PRV setting converts to metres of *fluid* head by:

   ```
   head_m = setting * pressure_to_head_m / specific_gravity
   ```

   For a denser-than-water fluid (`sg = 2.0`), the same pressure
   produces half as many metres of fluid head; for a lighter fluid
   (`sg = 0.5`), twice as many.

2. **POWER pump surrogate effective density.** The Sprint 14 surrogate
   evaluates `H_nom = P / (rho_eff * g * Q_nom)` with
   `rho_eff = rho_water * sg`. For the same `P` and `Q_nom`, doubling
   `sg` halves `H_nom` (and the surrogate's `a0`/`a2` magnitudes);
   halving `sg` doubles them. The helper exposes a keyword-only
   `specific_gravity=` argument with default `1.0` so Sprint 14
   numerics are preserved when the directive is absent.

### What specific gravity does NOT scale

The directive must NOT touch any of the following, by design:

- Junction elevations and reservoir / tank fixed-head boundaries.
  Reservoirs and tanks are *length* boundaries (metres or feet of
  surface elevation); SG is dimensionless density and cannot scale
  geometric height.
- PRV settings under head-length pressure units (`METERS`, `M`,
  `FEET`, `FT`). Those aliases already declare metres / feet of head
  directly, so the conversion is a pure length conversion.
- HEAD-curve pump coefficients (`[CURVES]`). EPANET HEAD curves are
  head-vs-flow tables — already metres of head — so SG is a no-op.
- TCV settings (the dimensionless minor-loss coefficient `K`) and the
  `MinorLoss` column.
- Pipe / pump / valve dimensions (length, diameter, c_factor).
- Junction demands (Demand Multiplier remains the orthogonal axis
  on demand scaling and is unaffected by SG).

### Validation

The resolver and the fallback parser fail loudly on:

- Zero specific gravity → `ValueError` ("must be strictly positive").
  Zero density would singularise the pressure-to-head and POWER-pump
  conversions.
- Negative specific gravity → `ValueError` ("must be strictly
  positive").
- Non-finite specific gravity (NaN or Inf) → `ValueError` ("must be
  finite").
- Non-numeric values → `ValueError` ("is not numeric").

### WNTR adapter behaviour

WNTR's handling of `[OPTIONS] Specific Gravity` has shifted across
releases (the directive may be stored under
`wn.options.hydraulic.specific_gravity` in some versions, ignored in
others, or applied internally during simulation). Sprint 19
**leaves the WNTR adapter structurally unchanged** to avoid
double-conversion or hidden discrepancies: the fallback parser is
authoritative for Sprint 19 SG behaviour, and the documented
WNTR-fallback parity tests cover only fixtures without an
`[OPTIONS] Specific Gravity` directive (where the default `1.0`
trivially matches across back-ends). Future sprints may add explicit
WNTR-side SG handling once the WNTR API is pinned to a stable
release surface.

### Tests

- `tests/dphm/test_inp_specific_gravity.py` — Sprint 19 specific
  gravity resolver (defaults, validation surface, case / whitespace
  tolerance), fallback parser PRV PSI/KPA/BAR scaling, head-length
  alias invariants, POWER pump surrogate SG scaling (helper +
  parser), HEAD-curve / TCV / reservoir / tank / pipe-geometry /
  demand-multiplier invariants, and existing-fixture preservation.

## Viscosity (Sprint 20)

EPANET's `[OPTIONS]` section accepts an optional `Viscosity` directive
— a single strictly-positive scalar describing the ratio of fluid
kinematic viscosity to that of water at 20 °C. The directive's option
key is a single token; the fallback parser's standard single-token
`[OPTIONS]` branch handles it case-insensitively (`Viscosity 1.0`,
`VISCOSITY 0.8`, `viscosity   2.0`).

The public resolver is `resolve_viscosity(opts)`:

```python
from aquaoptima.dphm.inp_io import resolve_viscosity

resolve_viscosity({})                       # 1.0 (default, water at 20 °C)
resolve_viscosity({"VISCOSITY": "0.8"})     # 0.8 (warmer / less viscous)
resolve_viscosity({"VISCOSITY": "2.0"})     # 2.0 (cooler / more viscous)
resolve_viscosity({"VISCOSITY": "0"})       # ValueError
resolve_viscosity({"VISCOSITY": "-1"})      # ValueError
```

### Why Hazen-Williams is viscosity-independent

EPANET's `Viscosity` directive only affects friction calculations that
involve a Reynolds number, i.e. the Darcy-Weisbach head-loss model
through the Colebrook-White / Swamee-Jain explicit friction factor.
Hazen-Williams head loss

```
h_L = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87)
```

has **no viscosity term**: the empirical roughness coefficient `C`
absorbs the fluid's frictional behaviour, and the exponent on flow is
fixed at `1.852` independent of Reynolds number. The current dPHM
core (`aquaoptima.dphm.hazen_williams`, `residuals.py`, the analytic
Jacobian, and `newton_solve`) implements only the Hazen-Williams
branch. Adding viscosity to any of those would have no mathematical
meaning under H-W; Sprint 20 therefore treats viscosity strictly as a
parser-compatibility surface.

### What Sprint 20 does with the directive

The fallback parser:

1. Reads `[OPTIONS] Viscosity` through `_parse_options` (single-token
   key path).
2. Resolves it via `resolve_viscosity(opts)`, which validates the
   value (defaults to `1.0`, must be finite and strictly positive)
   and raises `ValueError` on zero, negative, NaN, Inf, or
   non-numeric input. This preserves the fail-fast contract for
   EPANET-produced fixtures even though the value is never consumed.
3. Discards the resolved value. No demand, fixed head, geometry,
   HEAD pump coefficient, POWER pump surrogate coefficient, PRV or
   TCV surrogate parameter, or Newton-solve output is a function of
   viscosity under Hazen-Williams.

The Sprint 20 test suite asserts hydraulic invariance across a
representative cross-section of fixtures (LPS loop, GPM loop, HEAD
pump, POWER pump, PRV with PSI + SG, TCV) by loading each fixture
with and without the directive and comparing demands / fixed heads /
geometry / pump coefficients / Newton-solve heads & flows.

### What Sprint 20 does NOT do

- It does **not** add a Darcy-Weisbach head-loss branch. Viscosity
  would matter there but is deferred.
- It does **not** add a Reynolds / friction-factor model.
- It does **not** propagate viscosity into Specific Gravity / Demand
  Multiplier / Pressure directive behaviour — the three axes are
  orthogonal under the current H-W core.
- It does **not** ship a `Viscosity` example fixture under
  `docs/examples/`; tmp-path fixtures cover the parser surface
  without growing the shipped-fixture inventory.

### Validation

The resolver and the fallback parser fail loudly on:

- Zero viscosity → `ValueError` ("must be strictly positive"). Zero
  viscosity would imply an inviscid fluid and would singularise any
  future Reynolds calculation.
- Negative viscosity → `ValueError` ("must be strictly positive").
- Non-finite viscosity (NaN or Inf) → `ValueError` ("must be finite").
- Non-numeric values → `ValueError` ("is not numeric").

### WNTR adapter behaviour

WNTR's treatment of `[OPTIONS] Viscosity` is **ambiguous across
releases**: some versions parse it into
`wn.options.hydraulic.viscosity`, others into the deprecated
`wn.options.hydraulic.viscosity` alias, others ignore it, and the
simulator itself only consults the value when the Darcy-Weisbach
formula is selected. Sprint 20 therefore **leaves the WNTR adapter
structurally unchanged**:

- The fallback parser is authoritative for Sprint 20 viscosity
  parsing and validation.
- WNTR's HEAD / POWER / PRV / TCV / demand-multiplier parity from
  Sprints 13–19 remains green.
- The optional WNTR parity test
  (`test_wntr_fallback_parity_with_viscosity_directive`) only
  asserts that adding a `Viscosity` directive does not break either
  back-end; it does not assert agreement on a viscosity-derived
  quantity (because, under Hazen-Williams, no such quantity exists).

A future sprint may pin WNTR to a stable surface and add explicit
WNTR-side viscosity handling at the same time it adds a
Darcy-Weisbach branch to the dPHM core.

### Tests

- `tests/dphm/test_inp_viscosity.py` — Sprint 20 viscosity resolver
  (defaults, validation surface, case / whitespace tolerance),
  fallback parser invalid-value rejection, hydraulic invariance under
  Hazen-Williams across SI and US flow-unit families (demands,
  fixed heads, geometry, HEAD pump coefficients, POWER pump
  coefficients, PRV PSI conversion with and without SG, TCV
  effective resistance, Newton-solve heads / flows), orthogonality
  with Demand Multiplier and Specific Gravity, and existing-fixture
  preservation.

## Ignored sections (Sprint 21)

Sprint 21 makes the fallback parser's *no-op* behaviour for every
out-of-scope EPANET section explicit, tested, and documented.

The constant `aquaoptima.dphm.inp_io.IGNORED_SECTIONS` is the public
surface for this contract — a `frozenset[str]` enumerating every
section header the parser tolerates and then deliberately drops:

| Section        | Reason it is ignored                                                                                                 |
|----------------|---------------------------------------------------------------------------------------------------------------------|
| `[TIMES]`      | Simulation timestep / duration. Only meaningful to an EPANET runtime; the dPHM importer never spawns one.            |
| `[REPORT]`     | EPANET report-file directives. Output formatting, no hydraulic content.                                              |
| `[CONTROLS]`   | Simple link-status / pump-speed controls. Active controls are not modelled by the steady-state dPHM core.            |
| `[RULES]`      | Rule-based controls. Same limitation as `[CONTROLS]` — deferred.                                                     |
| `[EMITTERS]`   | Pressure-driven leakage. Not modelled in the steady-state Hazen-Williams branch.                                     |
| `[QUALITY]`    | Initial water-quality concentrations. Outside the current hydraulic scope.                                            |
| `[SOURCES]`    | Quality source declarations. Outside the current hydraulic scope.                                                     |
| `[REACTIONS]`  | Bulk / wall reaction-rate coefficients. Outside the current hydraulic scope.                                          |
| `[MIXING]`     | Tank mixing model. The dPHM core does not integrate tank volumes; mixing is moot.                                     |
| `[TITLE]`      | Free-form network description.                                                                                       |
| `[END]`        | EPANET file terminator.                                                                                              |
| `[PATTERNS]`   | Time-varying demand patterns. The dPHM core is steady-state; the Sprint 18 `Demand Multiplier` is the only honoured scalar. |
| `[COORDINATES]`| Node positions for plotting.                                                                                         |
| `[VERTICES]`   | Mid-pipe vertex positions for plotting.                                                                              |
| `[LABELS]`     | Free-text labels for the network plot.                                                                               |
| `[BACKDROP]`   | Background image / drawing dimensions for the EPANET GUI.                                                            |
| `[TAGS]`       | Free-form node / link annotations.                                                                                   |
| `[ENERGY]`     | Energy-cost / efficiency definitions. Active controls would consume these; deferred with `[CONTROLS]` / `[RULES]`.   |
| `[DEMANDS]`    | Per-junction supplemental demand list. The Sprint 11 importer reads junction demand from the `[JUNCTIONS]` column.   |

> **`[STATUS]` is no longer ignored.** Sprint 22 removed `[STATUS]` from
> the no-op set and validates it actively — see
> "Explicit [STATUS] no-op rows (Sprint 22)" below.

### Contract

Adding any section in `IGNORED_SECTIONS` to a fixture must leave the
loaded `Network` byte-for-byte unchanged:

- node count, edge count, fixed-head count, `edge_index`;
- `demands`, `fixed_head_values`, `fixed_head_mask`;
- `pipe_mask`, `pump_mask`, `lengths`, `diameters`, `c_factors`;
- `pump_coeffs`, `pump_speeds`.

This holds regardless of where the section appears (before, after, or
interleaved with the hydraulic sections), how many such sections are
stacked into one file, and how malformed-looking the per-section rows
are. The parser does not validate the body of any ignored section —
it tokenises every row through `_split_sections` and never reads the
result.

`[CURVES]` is **not** in this set: Sprint 12's HEAD-curve pump
translation consumes it. Sprint 21 ships an explicit regression test
that adding every target ignored section to a HEAD-pump fixture
still produces identical pump coefficients, so the active /
ignored distinction cannot drift silently.

### Documented limitations

`[CONTROLS]` and `[RULES]` are ignored, **not** enforced. A control
rule that would close a pipe, change a pump speed, or modify a
fixed-head boundary is dropped on the floor at parse time. Importing
EPANET fixtures whose hydraulics depend on active control logic will
therefore *not* reproduce EPANET's solved state under the dPHM
steady-state core. A future sprint that adds control-state logic
will be the place this changes.

`[EMITTERS]`, `[QUALITY]`, `[SOURCES]`, `[REACTIONS]`, and `[MIXING]`
are similarly dropped. None of these contribute to the
Hazen-Williams steady-state residual; the relevant physics
(pressure-driven demand for emitters, advection-reaction transport
for the quality family) is out of scope for the current core.

### WNTR adapter behaviour

Sprint 21 documents but does not enforce WNTR-side handling of the
target ignored sections. WNTR has its own parsers for several of
them (e.g. `[MIXING]` is validated against the network's tank set,
`[CONTROLS]` is validated against link / node references). The
Sprint 21 contract is about *our* fallback parser's no-op behaviour;
the optional WNTR back-end is exercised in
`tests/dphm/test_inp_ignored_sections.py::test_wntr_smoke_ignored_sections_do_not_break_back_end`
only for the subset of ignored sections WNTR is happy to round-trip
(`[TIMES]`, `[REPORT]`, `[QUALITY]` against an existing node).

### Tests

- `tests/dphm/test_inp_ignored_sections.py` — Sprint 21:
  - public-surface checks (every target section in
    `IGNORED_SECTIONS`, every hydraulically-active section NOT in
    `IGNORED_SECTIONS`, `[CURVES]` not globally ignored,
    `IGNORED_SECTIONS` is a `frozenset`);
  - per-section invariance (loaded `Network` byte-for-byte identical
    between baseline and baseline + ignored section);
  - all-target-sections-at-once invariance;
  - position robustness (ignored section before hydraulic sections,
    after hydraulic sections, interleaved between them, repeated
    headers);
  - malformed-row tolerance for every target section;
  - documented `[CONTROLS]` / `[RULES]` limitation (link-close rules
    dropped, network and Newton-solve state unchanged);
  - `[CURVES]` still active under ignored-section noise (HEAD pump
    and PRV / TCV surrogate invariants);
  - optional WNTR back-end smoke check on the subset WNTR
    round-trips cleanly.

## Explicit `[STATUS]` no-op rows (Sprint 22)

Sprint 22 narrows the Sprint 21 ignored-section contract for the
`[STATUS]` section. Through Sprint 21 `[STATUS]` was a global no-op —
the parser tokenised the rows and then never read them. Sprint 22
keeps the *steady-state hydraulic boundary* in place but starts
validating the section so EPANET-exported files that include explicit
`<link_id> OPEN` declarations load without pretending to implement
closed-link or active status physics.

### What Sprint 22 accepts

Rows of the form

```text
[STATUS]
 <link_id>   OPEN
 <link_id>   open       ; case-insensitive
   <link_id>    OPEN    ; extra whitespace is tolerated
```

are accepted as **redundant no-ops**. Every pipe, pump, and valve the
fallback parser loads is already implicitly open, so a `<link_id> OPEN`
row carries no new information — but the validator still:

1. Confirms the row has at least two tokens (link id + status token).
2. Confirms the link id appears in the union of parsed
   `[PIPES]` / `[PUMPS]` / `[VALVES]` ids. The `[STATUS]` section may
   appear before or after those sections in the file; validation runs
   after every link is known, so the ordering does not matter.
3. Confirms the status token (case-folded) is `OPEN`.

Accepted `[STATUS]` rows leave the loaded `Network` **byte-for-byte
identical** to the same fixture with no `[STATUS]` section.

### What Sprint 22 rejects

| Row shape                              | Behaviour                                                                                                  |
|----------------------------------------|------------------------------------------------------------------------------------------------------------|
| `<link_id>` (single token)             | `ValueError` — "row needs at least 2 tokens".                                                              |
| `<unknown_id> OPEN`                    | `ValueError` — "references unknown link id".                                                               |
| `<link_id> CLOSED` / `closed`          | `ValueError` — the steady-state core does not model closed links.                                          |
| `<link_id> CV`                         | `ValueError` — the steady-state core does not model check valves.                                          |
| `<link_id> 1.0` / `0` (numeric)        | `ValueError` — the steady-state core does not consume per-link pump speed/status multipliers from `[STATUS]`. |
| `<link_id> MAYBE_LATER` (other token)  | `ValueError` — the only accepted token is `OPEN`.                                                          |

Every error message names `[STATUS]`, the link id, and the offending
token so the source row is easy to find. Case-folding applies only to
the comparison — the original-case token is echoed back in the message.

### What Sprint 22 does NOT do

- It does **not** model closed-link behaviour. `[STATUS] P1 CLOSED`
  raises rather than silently dropping pipe `P1` from the flow
  equation.
- It does **not** model check valves. `[STATUS] P1 CV` raises rather
  than adding a sign-restricted unilateral edge.
- It does **not** model pump speed/status multipliers from `[STATUS]`.
  Numeric values raise — pump speed in the steady-state core is the
  `s = 1` static nominal speed used by `fit_pump_head_curve`.
- It does **not** alter the per-row `[PIPES]` status column. A
  `[PIPES] ... CLOSED` / `CV` row continues to raise from the pipe-row
  loop exactly as it did from Sprint 11 onwards.
- It does **not** activate `[CONTROLS]` or `[RULES]`. The Sprint 21
  documented limitation (control-state logic deferred) is unchanged.
- It does **not** change the WNTR back-end. WNTR has its own
  `[STATUS]` parser that validates link references and applies any
  closed-state semantics to its internal link state; the dPHM
  WNTR adapter reads the resulting pipe/pump/valve list but does not
  re-validate `[STATUS]`. The fallback parser is therefore
  authoritative for Sprint 22 `[STATUS]` behaviour. The optional
  WNTR smoke test in `tests/dphm/test_inp_status.py` only confirms
  that the demand sum / node / edge counts agree between back-ends
  on `[STATUS] <id> OPEN` fixtures.

### Public surface change

`aquaoptima.dphm.inp_io.IGNORED_SECTIONS` no longer contains
`"STATUS"`. The Sprint 21 ignored-section invariance tests still pass
because they iterate over the documented Sprint 21 target list which
never included `STATUS`. An explicit regression test in
`tests/dphm/test_inp_ignored_sections.py::test_status_is_not_globally_ignored_after_sprint_22`
pins this removal — a future sprint that reintroduces global
`[STATUS]` ignoring will trip that test.

### Tests

- `tests/dphm/test_inp_status.py` — Sprint 22:
  - public-surface check (`STATUS` not in `IGNORED_SECTIONS`);
  - accepted-no-op invariance on pipes, HEAD-curve pumps, PRV
    valves, and TCV valves (loaded `Network` byte-for-byte
    identical to baseline);
  - case-insensitive `OPEN` token (every spelling accepted);
  - extra-whitespace tolerance;
  - multiple `OPEN` rows in one block;
  - `[STATUS]` section before and after the link sections;
  - unknown link id raises with id in message;
  - short row (< 2 tokens) raises with shape error;
  - `CLOSED` / `closed` raises with link id and token in message;
  - `CV` raises with link id and token in message;
  - numeric pump speed `1.0` and `0` both raise;
  - arbitrary token raises with link id and token in message;
  - mixed `OPEN`/`CLOSED` block raises on the closed row;
  - per-row `[PIPES] ... CLOSED` / `CV` rejection still raises
    (Sprint 11 behaviour preserved);
  - `[CONTROLS]` / `[RULES]` still ignored alongside `[STATUS] OPEN`
    (Sprint 21 limitation preserved);
  - HEAD pump `[CURVES]` resolution unaffected by `[STATUS] PU1 OPEN`;
  - empty `[STATUS]` section accepted;
  - optional WNTR back-end smoke check (`pytest.importorskip("wntr")`).

## Read-only `[STATUS]` diagnostics (Sprint 23)

Sprint 22 made accepted `[STATUS] OPEN` rows validated no-ops — the
loaded `Network` is byte-for-byte identical with or without
`[STATUS]`. Sprint 23 adds a small, explicit *diagnostics surface*
so analysts can see **which** status rows were declared in an
imported file. The diagnostics are deliberately read-only and
hydraulically inert: they do not change any field on the returned
`Network`, and the Sprint 22 rejection behaviour for status-changing
rows (`CLOSED`, `CV`, numeric pump speed/status, unknown link id,
short row, arbitrary token) is unchanged — rejected rows still
raise `ValueError` and never appear as diagnostics.

### Public API

```python
from aquaoptima.dphm import (
    EpanetImportDiagnostics,
    EpanetStatusDiagnostic,
    load_inp_diagnostics,
    load_network_from_inp,
)

# Option A — explicit, read-only diagnostics accessor.
diagnostics = load_inp_diagnostics(
    "docs/examples/epanet_reference_loop.inp",
    parser="fallback",   # "auto" | "fallback" | "wntr"
)
for row in diagnostics.status_rows:
    print(row.link_id, row.status, row.is_noop, row.message)

# Option B — fetch the Network and the diagnostics together.
network, diagnostics = load_network_from_inp(
    "docs/examples/epanet_reference_loop.inp",
    parser="fallback",
    return_diagnostics=True,
)
```

The default `load_network_from_inp(path)` (without
`return_diagnostics=True`) **continues to return only a `Network`**,
so every Sprint 11–22 caller works unchanged.

### Shape

```python
@dataclass(frozen=True)
class EpanetStatusDiagnostic:
    link_id: str            # spelling preserved from the source file
    status: str             # normalised, e.g. "OPEN"
    section: str = "STATUS"
    is_noop: bool = True
    message: str = "OPEN accepted as a no-op; status-changing semantics are unsupported."


@dataclass(frozen=True)
class EpanetImportDiagnostics:
    status_rows: tuple[EpanetStatusDiagnostic, ...] = ()
```

Both dataclasses are `frozen=True`. `status_rows` is a `tuple`
(not a list) so the diagnostics surface is structurally read-only:
attempting to reassign a field raises
`dataclasses.FrozenInstanceError`.

### What gets recorded

The fallback parser emits **one `EpanetStatusDiagnostic` per
accepted `<link_id> OPEN` row**, in source order:

- the `link_id` is echoed verbatim from the file (link ids are
  case-sensitive in the dPHM fallback parser);
- the `status` token is normalised to upper-case `OPEN`
  (case-insensitive matching: `OPEN` / `open` / `Open` all
  normalise here);
- `is_noop=True` and the no-op `message` are set so consumers can
  filter without re-checking the string;
- the row order in `status_rows` matches the row order in the
  source `[STATUS]` block.

Diagnostics are empty when:

- the file has no `[STATUS]` section, or
- the `[STATUS]` section header is present but the body is empty.

Rejected rows (Sprint 22) abort the validator **before** any
diagnostic is appended — a block mixing `OPEN` and `CLOSED` rows
raises with no partial diagnostics leaking out.

### Hydraulic inertness

The diagnostics path **does not** mutate the loaded `Network`:

- `load_network_from_inp(path, return_diagnostics=True)` returns
  the *exact same* `Network` object shape that
  `load_network_from_inp(path)` does — same `edge_index`, same
  `pipe_mask` / `pump_mask`, same `demands`, `fixed_head_values`,
  `lengths`, `diameters`, `c_factors`, `pump_coeffs`, and
  `pump_speeds`.
- `load_inp_diagnostics(path)` returns *only* an
  `EpanetImportDiagnostics` — never a `Network`.
- The diagnostic records themselves are frozen, so consumers
  cannot mutate them in place and accidentally inject state back
  into a future parse.

Tests in
`tests/dphm/test_inp_status_diagnostics.py` pin the byte-for-byte
network-equality contract on top of the Sprint 22 invariance tests.

### What Sprint 23 does NOT do

- It does **not** model closed-link, check-valve, or pump-speed
  semantics. Sprint 22 rejections are unchanged.
- It does **not** activate `[CONTROLS]` or `[RULES]`. Those
  sections remain in `IGNORED_SECTIONS` and are explicitly *not*
  emitted as diagnostics — even in a file that also declares
  `[STATUS] OPEN`, `[CONTROLS]` and `[RULES]` rows are silently
  ignored exactly as in Sprint 21.
- It does **not** attach diagnostic state to `Network`. The
  `Network` dataclass surface is unchanged.
- It does **not** make the WNTR back-end emit diagnostics. The
  fallback parser is authoritative for Sprint 23 `[STATUS]`
  diagnostics. When `parser="wntr"` is requested, the WNTR
  back-end relies on WNTR's own `[STATUS]` parser (which handles
  closed-link state internally inside the WNTR engine) and the
  dPHM WNTR adapter returns an **empty**
  `EpanetImportDiagnostics`. Asymmetry between back-ends is
  documented rather than papered over — see also
  `SPRINT22_REPORT.md` for the same fallback-authoritative split.

### Tests

`tests/dphm/test_inp_status_diagnostics.py` — Sprint 23:

- public-surface checks: dataclasses are importable, frozen, and
  use a tuple-backed container;
- accepted-row records for pipes, HEAD-curve pumps, and PRV
  valves;
- case-insensitive `OPEN` normalisation; link id casing preserved;
- multiple-row count + order invariance;
- empty diagnostics for files with no `[STATUS]` and for an
  empty `[STATUS]` section;
- `Network` equality between default and `return_diagnostics=True`
  loads, and between fixtures with and without `[STATUS]`;
- backwards compatibility: default `load_network_from_inp(path)`
  still returns only a `Network`;
- every Sprint 22 rejection (CLOSED / CV / numeric / unknown id /
  short row / arbitrary token) still raises through both
  `load_inp_diagnostics` and `load_network_from_inp(..., return_diagnostics=True)`;
- mixed OPEN+CLOSED blocks raise with no partial diagnostics
  leaked out;
- `[CONTROLS]` / `[RULES]` content does **not** appear in
  diagnostics, even in files that also declare `[STATUS] OPEN`;
- parser selector + units kwargs reach the diagnostics path
  (unknown parser / non-SI units raise);
- optional WNTR back-end smoke check
  (`pytest.importorskip("wntr")`) confirms the API does not raise
  and returns the read-only container shape — it does **not**
  require diagnostic parity with the fallback back-end.

## Mass balancing

EPANET INP files often declare junction demands without a matching
explicit supply row; the reservoir(s) implicitly supply the deficit.
Our `Network` dataclass expects `sum(demands) ≈ 0` for downstream
clarity, so the fallback parser **absorbs the demand sum onto the
fixed-head node(s)** at load time. Fixed-head nodes drop out of the
mass-balance residual term anyway — this is purely cosmetic, but it
keeps loaded networks comparable with the JSON loader and the
hand-built fixtures.

## Shipped fixtures

Ten small fixtures are shipped under `docs/examples/`:

| Fixture                                            | Family | Notes                                                  |
|----------------------------------------------------|--------|--------------------------------------------------------|
| `epanet_reference_loop.inp`                        | SI     | Sprint 11 — five-node looped distribution, LPS units.  |
| `epanet_reference_pump.inp`                        | SI     | Sprint 12 — HEAD-curve pump.                           |
| `epanet_reference_power_pump.inp`                  | SI     | Sprint 14 — POWER pump (kW under SI).                  |
| `epanet_reference_prv.inp`                         | SI     | Sprint 15 — PRV pressure-boundary surrogate.           |
| `epanet_reference_tcv.inp`                         | SI     | Sprint 15 — TCV resistance surrogate.                  |
| `epanet_reference_loop_gpm.inp`                    | US     | Sprint 16 — looped distribution, GPM/ft/in.            |
| `epanet_reference_pump_gpm.inp`                    | US     | Sprint 16 — HEAD-curve pump, GPM/ft/in.                |
| `epanet_reference_tcv_gpm.inp`                     | US     | Sprint 16 — TCV surrogate, GPM/ft/in.                  |
| `epanet_reference_prv_gpm_psi.inp`                 | US     | Sprint 17 — PRV with explicit `[OPTIONS] Pressure PSI`. |
| `epanet_reference_loop_gpm_demand_multiplier.inp`  | US     | Sprint 18 — looped distribution with `Demand Multiplier 2.0`. |

Each US fixture mirrors the structure of its SI counterpart but uses
US-customary EPANET conventions (length in feet, diameter in inches,
head/elevation in feet, demand in GPM). The fallback parser converts
every dimension to SI through the `EpanetUnitSystem` manifest before
populating the `Network` dataclass; analytic-Newton solves both
SI and US fixtures unchanged.

The original Sprint 11 loop fixture
`docs/examples/epanet_reference_loop.inp` is a tiny 5-node looped
distribution sample (1 reservoir + 4 junctions, 5 pipes) in SI
(`LPS`) flow units. It is small enough to read at a glance and large
enough to exercise pipe loops, reservoir boundaries, and mm→m
diameter conversion.

Round-trip:

```python
from pathlib import Path
from aquaoptima.dphm import load_network_from_inp, newton_solve

net = load_network_from_inp(
    Path("docs/examples/epanet_reference_loop.inp"),
    parser="fallback",
)
result = newton_solve(net, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
assert result.converged
```

Tests:

- `tests/dphm/test_inp_network_io.py` — fallback parser, full error
  surface, solver compatibility, batched residual compatibility.
- `tests/dphm/test_inp_pump_curves.py` — Sprint 12 pump-curve parser
  and `fit_pump_head_curve` helper, including malformed inputs.
- `tests/dphm/test_inp_power_pump.py` — Sprint 14 POWER pump
  surrogate, fallback parser POWER row handling, shipped fixture
  load + solve + per-pump residual checks.
- `tests/dphm/test_wntr_optional_import.py` — optional WNTR
  comparison (loop + Sprint 13 HEAD pump + Sprint 14 POWER pump +
  Sprint 15 PRV / TCV fixtures), skipped when WNTR is not
  installed.
- `tests/dphm/test_wntr_pump_helpers.py` — Sprint 13/14 WNTR pump
  translation helpers (HEAD and POWER paths), exercised against
  duck-typed fakes (no WNTR dependency).
- `tests/dphm/test_inp_valves.py` — Sprint 15 fallback parser for
  PRV / TCV valves, fit helper, translator, shipped fixture load +
  solve + diagnostic evidence, error surface.
- `tests/dphm/test_wntr_valve_helpers.py` — Sprint 15 WNTR valve
  helpers exercised against duck-typed fakes (no WNTR dependency).
- `tests/dphm/test_inp_unit_systems.py` — Sprint 16 unit-system
  manifest, every supported flow unit's conversion factors, case-
  insensitive lookup, and the unsupported-token error path.
- `tests/dphm/test_inp_us_fixtures.py` — Sprint 16 US-customary
  fixture loads, dimension conversions, analytic-Newton solves,
  POWER pump nominal flow under US units, PRV setting conversion,
  and fallback-vs-WNTR parity on every shipped US fixture
  (`pytest.importorskip("wntr")`).
- `tests/dphm/test_inp_pressure_units.py` — Sprint 17 pressure-unit
  manifest, every supported pressure unit's conversion factor, the
  case-insensitive lookup surface, GPM+PSI PRV fixture load + solve,
  tmp-path kPa / bar / metres / feet PRV conversion, TCV-not-affected
  invariant, and Sprint 16 default-behaviour preservation.
- `tests/dphm/test_inp_demand_multiplier.py` — Sprint 18 demand
  multiplier resolver (defaults, validation surface, case / whitespace
  tolerance), fallback parser scaling under LPS / SI and GPM / US,
  shipped GPM-with-multiplier fixture load + solve, POWER pump
  nominal-flow anchor scaling, TCV / HEAD curve / reservoir / tank
  invariants, and optional WNTR parity.
- `tests/dataio/test_inp_physics_telemetry.py` — physics-consistent
  telemetry round-trip on the INP-loaded loop network.
- `tests/dataio/test_inp_pump_telemetry.py` — Sprint 12 analytic-Newton
  solve and physics-consistent telemetry on the HEAD pump fixture.
- `tests/dataio/test_inp_power_pump_telemetry.py` — Sprint 14
  analytic-Newton solve and physics-consistent telemetry on the
  POWER pump fixture.

## What this loader is **not**

- Not an EPANET runtime — no hydraulic simulation, no extended-period
  integration, no quality / age modelling.
- Not a SCADA / PLC / PAC adapter — no Modbus, OPC-UA, MQTT, or
  historian binding.
- Not a write or control path — all loaded topologies are read-only
  inputs to the differentiable forward model.
- Not field-validated — Sprint 11 only proves that the topology
  *parses and solves*; on-site accuracy claims remain out of scope.

## Roadmap

Deferred to a future sprint:

- Pump curve translation for the `SPEED` / `LINEAR` /
  multi-point efficiency forms (HEAD-curve form shipped in Sprint
  12, POWER form shipped in Sprint 14).
- A more faithful POWER-pump model (e.g. solving the implicit
  constant-power constraint inside Newton instead of an upfront
  surrogate).
- A more faithful PRV / TCV model — e.g. an active-control
  state machine (active / open / closed branches) and a
  mass-balanced PRV that enforces the demand invariant
  (Sprint 15 ships the conservative pressure-boundary surrogate
  only).
- The remaining EPANET valve forms `FCV`, `PSV`, `PBV`, `GPV`.
- Larger reference fixtures (e.g. the EPANET `Net1` / `Net3` shipped
  examples) routed through the WNTR back-end.
- Time-varying demand support via the `[PATTERNS]` section. Sprint 18
  honours the steady-state `[OPTIONS] Demand Multiplier` scalar only;
  the dPHM core remains steady-state and pattern-aware demands are
  out of scope.
- Explicit WNTR-side `[OPTIONS] Specific Gravity` handling. Sprint 19
  ships SG support in the fallback parser only — WNTR's handling of
  the directive has drifted across releases and is left untouched.
  A future sprint may pin WNTR to a stable surface and add parity.
- A Darcy-Weisbach head-loss branch (and the Reynolds / friction-
  factor model it requires) — the place where `[OPTIONS] Viscosity`
  would actually be propagated. Sprint 20 ships parser support only
  because the current dPHM core is Hazen-Williams and is viscosity-
  independent by construction.
- Explicit WNTR-side `[OPTIONS] Viscosity` handling. Sprint 20 ships
  viscosity parsing in the fallback parser only — WNTR's handling of
  the directive has shifted across releases and is left untouched.

See `docs/sprint-roadmap.md` for the current ordering.
