# EPANET `.inp` Topology Import (Sprint 11–14)

Sprint 11 extends the dPHM topology loader stack with optional
EPANET-style `.inp` import, alongside the Sprint 8 JSON loader.
Sprint 12 adds HEAD-curve pump translation to the fallback parser
(see "Pump HEAD curves" below). Sprint 13 brings the optional
WNTR-backed parser into parity with the fallback parser for the same
HEAD-curve pumps. Sprint 14 adds `POWER`-pump support to both
back-ends via a bounded quadratic surrogate (see "POWER pumps"
below). The public entry point is one function:

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
| `[OPTIONS]`      | `Units` (flow-unit family) and `Headloss` (must be `H-W`).                                               |
| `[PUMPS]`        | Sprint 12: `HEAD curve_id` pump rows translate via least-squares curve fit. Sprint 14: `POWER value` pump rows translate via the constant-power surrogate. |
| `[CURVES]`       | Sprint 12: pump HEAD curves are parsed into `(Q, H)` points. The X column is converted to m³/s using the file's flow-unit factor. Unused curves are tolerated. |
| `[TITLE]`, `[COORDINATES]`, `[PATTERNS]`, `[REPORT]`, `[TIMES]`, `[END]`, ... | Silently ignored.                                  |

### Sections that fail loudly

| Section          | Reason                                                                                                                                |
|------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `[PUMPS]` (unsupported keyword) | Raises `ValueError`. The parser supports `HEAD curve_id` (Sprint 12) and `POWER value` (Sprint 14). `SPEED` and any custom keyword still raise. |
| `[VALVES]`       | Raises `ValueError`. The dPHM steady-state core does not model valves.                                                                |

The WNTR back-end still refuses `[VALVES]`. As of Sprint 14, the
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

EPANET picks per-flow-unit conventions for length and diameter:

- **SI flow units** (`LPS`, `LPM`, `CMH`, `CMS`, `MLD`):
  length in metres, diameter in **millimetres**, head/elevation in
  metres. Supported.
- **US-customary flow units** (`CFS`, `GPM`, `MGD`, `IMGD`, `AFD`):
  length in feet, diameter in inches, head in feet. **Not
  supported.** US-style files raise a clear `ValueError`. Convert
  upstream, or use WNTR which performs its own conversion to SI
  before our adapter reads its `WaterNetworkModel`.

Demand conversions (file → m³/s) implemented in the fallback parser:

| `Units` directive | factor                |
|-------------------|-----------------------|
| `LPS`             | `× 1e-3`              |
| `LPM`             | `× 1 / 60_000`        |
| `CMH`             | `× 1 / 3600`          |
| `CMS`             | `× 1` (no conversion) |
| `MLD`             | `× 1000 / 86_400`     |

If `[OPTIONS]` is absent or omits `Units`, the parser assumes the
EPANET default of `LPS`. If `Headloss` is not `H-W`, the parser
raises — the dPHM core is Hazen-Williams.

## Mass balancing

EPANET INP files often declare junction demands without a matching
explicit supply row; the reservoir(s) implicitly supply the deficit.
Our `Network` dataclass expects `sum(demands) ≈ 0` for downstream
clarity, so the fallback parser **absorbs the demand sum onto the
fixed-head node(s)** at load time. Fixed-head nodes drop out of the
mass-balance residual term anyway — this is purely cosmetic, but it
keeps loaded networks comparable with the JSON loader and the
hand-built fixtures.

## Shipped fixture

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
  comparison (loop + Sprint 13 HEAD pump + Sprint 14 POWER pump
  fixtures), skipped when WNTR is not installed.
- `tests/dphm/test_wntr_pump_helpers.py` — Sprint 13/14 WNTR pump
  translation helpers (HEAD and POWER paths), exercised against
  duck-typed fakes (no WNTR dependency).
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

- US-customary flow units (`GPM`, `CFS`, …) on the fallback parser.
- Pump curve translation for the `SPEED` / `LINEAR` /
  multi-point efficiency forms (HEAD-curve form shipped in Sprint
  12, POWER form shipped in Sprint 14).
- A more faithful POWER-pump model (e.g. solving the implicit
  constant-power constraint inside Newton instead of an upfront
  surrogate).
- Larger reference fixtures (e.g. the EPANET `Net1` / `Net3` shipped
  examples) routed through the WNTR back-end.

See `docs/sprint-roadmap.md` for the current ordering.
