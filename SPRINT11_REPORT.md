# Sprint 11 — EPANET `.inp` Topology Import

## Scope

Add **optional EPANET / WNTR-style `.inp` topology import** to the
dPHM loader stack to widen the external credibility of the
synthetic / reference science gate, without requiring a live EPANET
binary, any field adapter, or internet access during tests.

Sprint 10 proved a 100-node grid science gate using the Sprint 9
analytic Newton path. Sprint 11 makes the topology layer accept
EPANET `.inp` files alongside the Sprint 8 JSON loader and converts
them into the existing `Network` dataclass.

## Files changed

New:

- `src/aquaoptima/dphm/inp_io.py` — fallback INP parser + optional
  WNTR back-end + the public `load_network_from_inp` entry point.
- `docs/examples/epanet_reference_loop.inp` — shipped 5-node looped
  reference fixture (1 reservoir + 4 junctions + 5 pipes, SI / LPS
  flow units, Hazen-Williams).
- `docs/epanet-inp-import.md` — full import documentation: supported
  subset, unit conventions, fallback vs WNTR back-ends, what the
  loader is **not**, and roadmap.
- `tests/dphm/test_inp_network_io.py` — fallback parser tests, error
  surface tests, solver compatibility tests, batched-residual
  compatibility test (32 tests).
- `tests/dphm/test_wntr_optional_import.py` — optional WNTR
  comparison tests, gated with `pytest.importorskip("wntr")` (3
  tests, 2 skipped + 1 ImportError negative-path executed when WNTR
  is absent).
- `tests/dataio/test_inp_physics_telemetry.py` — physics-consistent
  telemetry round-trip on the INP-loaded network (2 tests).

Modified:

- `src/aquaoptima/dphm/__init__.py` — export `load_network_from_inp`
  in the package's `__all__`.
- `pyproject.toml` — add `[project.optional-dependencies] epanet =
  ["wntr>=1.0"]` for opt-in WNTR install.

No existing source file was edited except the package `__init__`.
The dataclass `Network`, the JSON loader `load_network_from_json`,
the grid fixture `make_grid_network`, and the entire solver /
training surface are byte-identical to Sprint 10.

## INP loader API

```python
from aquaoptima.dphm import load_network_from_inp

network = load_network_from_inp(
    source,                  # str | pathlib.Path
    *,
    parser="auto",           # "auto" | "fallback" | "wntr"
    units="si",              # only "si" supported in Sprint 11
    default_c_factor=130.0,  # used when a pipe row omits roughness
)
```

- `parser="auto"` — prefer WNTR if importable, otherwise fallback.
- `parser="fallback"` — always use the dependency-free built-in.
- `parser="wntr"` — require WNTR, raise `ImportError` if absent.
- Returns the existing `aquaoptima.dphm.Network` dataclass.
- No internet access. No EPANET runtime. No PLC/PAC/SCADA binding.

## Fallback parser: supported subset

Sections honoured: `[JUNCTIONS]`, `[RESERVOIRS]`, `[TANKS]`,
`[PIPES]`, `[OPTIONS]` (`Units` + `Headloss`). Steady-state metadata
sections (`[COORDINATES]`, `[PATTERNS]`, `[REPORT]`, `[TIMES]`,
`[TITLE]`, `[END]`, …) are silently ignored — they carry nothing the
steady-state Hazen-Williams core needs.

Sections that fail loudly with `ValueError`:

- `[PUMPS]` — pump-curve translation is deferred; use JSON for pump
  fixtures or upgrade to WNTR.
- `[VALVES]` — the dPHM core does not model valves.

Unit handling:

- SI flow units (`LPS`, `LPM`, `CMH`, `CMS`, `MLD`) — supported.
  Demand converted to m³/s; diameter converted from mm to m; length
  in m.
- US-customary flow units (`GPM`, `CFS`, …) — refused with a clear
  `ValueError`.
- Default if `[OPTIONS]` is missing: `LPS`.
- `Headloss` must be `H-W`; anything else (D-W, C-M) raises.

Tank handling: `tank.elev + tank.init_level` pins the node as a
fixed-head boundary. Steady-state surrogate; volume curves are
documented as ignored.

Demand mass-balance: any drift between declared junction demands and
the reservoir supply is absorbed onto the fixed-head node(s) at parse
time, so `sum(demands) ≈ 0` matches the JSON-loader convention.

## WNTR optional behaviour

- `wntr` is **not** required for the normal test suite.
- New optional dependency group: `pip install
  'aquaoptima-dphm-pinn[epanet]'` pulls in `wntr>=1.0`.
- `tests/dphm/test_wntr_optional_import.py` skips cleanly when WNTR
  is absent (via `pytest.importorskip("wntr")`).
- One test runs an *executed negative-path* assertion: when WNTR is
  not installed, `load_network_from_inp(..., parser="wntr")` raises
  `ImportError`.
- The WNTR adapter currently refuses INP files that declare pumps or
  valves (same scope boundary as the fallback parser).

## Shipped fixture

`docs/examples/epanet_reference_loop.inp`:

- 1 reservoir `R1` pinned at 100 m head.
- 4 junctions `J1..J4` with baseline demands 10 / 15 / 12 / 8 L/s.
- 5 pipes forming a loop (`R1→J1`, `J1→J2`, `J2→J3`, `J3→J4`,
  `J1→J4`).
- SI flow unit `LPS`; Hazen-Williams head loss; `c_factor = 130.0`
  on every pipe.
- Total junction demand: 45 L/s = 0.045 m³/s, balanced onto the
  reservoir at parse time.

## Solver / telemetry evidence

```
load_network_from_inp(epanet_reference_loop.inp, parser='fallback')
→ Network(num_nodes=5, num_edges=5, num_fixed_heads=1)
demands  = [0.010, 0.015, 0.012, 0.008, -0.045]   m^3/s
fixed    = [_, _, _, _, R1=100.0 m]
lengths  = [300, 250, 220, 200, 280]              m
diameters= [0.250, 0.200, 0.150, 0.150, 0.150]    m  (mm in file)
c_factor = [130, 130, 130, 130, 130]

newton_solve(net, jacobian_mode='analytic', tol=1e-9)
→ converged=True, residual_norm ≈ 1.6e-10, iterations=5
→ heads ≈ [98.93, 98.17, 97.79, 97.89, 100.00] m
```

The autograd and analytic Jacobian paths agree to `atol=1e-7` on the
shipped fixture. The Sprint 8 batched residual assembler accepts the
loaded network unchanged. The Sprint 5/8 physics-consistent telemetry
generator runs end-to-end on the loaded network (8 timesteps, finite
residuals throughout, float64 round-trip residual norm below 1e-3 on
a 100-m-head network — float32 cast-back precision floor).

## Tests added (Sprint 11 only)

| File                                                | Tests | Behaviour                                              |
|-----------------------------------------------------|-------|--------------------------------------------------------|
| `tests/dphm/test_inp_network_io.py`                 | 32    | Fallback parser happy / error / solver compatibility   |
| `tests/dphm/test_wntr_optional_import.py`           | 3     | Optional WNTR comparison (2 skipped without WNTR + 1 ImportError negative path executed) |
| `tests/dataio/test_inp_physics_telemetry.py`        | 2     | Physics-consistent telemetry on INP-loaded network     |

## Validation commands

```bash
python -m pip install -e .
python -m pytest tests/dphm tests/models tests/training tests/dataio -q
python -m pytest tests -q
python -m compileall src tests
git status --short
```

### Results

| Gate                                                         | Result                                  |
|--------------------------------------------------------------|-----------------------------------------|
| `pip install -e .`                                           | OK                                      |
| `pytest tests/dphm tests/models tests/training tests/dataio` | **391 passed, 2 skipped** (WNTR opt)    |
| `pytest tests`                                               | **399 passed, 2 skipped** (WNTR opt)    |
| `compileall src tests`                                       | exit 0                                  |
| `git status --short`                                         | only Sprint 11 files touched (see below)|

Sprint 10 baseline was 356 targeted / 364 full. Sprint 11 adds 35
Sprint-11 tests (32 fallback parser + 3 optional WNTR + 2 telemetry,
of which 2 WNTR-skip cleanly) → 391 / 399 with no regressions.

### `git status --short`

```
 M pyproject.toml
 M src/aquaoptima/dphm/__init__.py
?? docs/epanet-inp-import.md
?? docs/examples/epanet_reference_loop.inp
?? src/aquaoptima/dphm/inp_io.py
?? tests/dataio/test_inp_physics_telemetry.py
?? tests/dphm/test_inp_network_io.py
?? tests/dphm/test_wntr_optional_import.py
```

All changes are intended Sprint 11 deliverables. No secret files,
credentials, or environment artefacts introduced.

## Compatibility notes

- `Network`, `load_network_from_json`, `make_grid_network`,
  `make_branch_network`, `make_pump_network`,
  `make_single_loop_network`, `newton_solve`, `assemble_residuals*`,
  `generate_physics_consistent_telemetry`, and every existing
  training API — **unchanged**.
- No physics equation change. No solver behaviour change.
- No new mandatory dependency. The optional `epanet` extra adds
  `wntr>=1.0` only when explicitly installed.
- INP-loaded networks are bit-compatible with every downstream
  consumer (solver, batched residual assembler, physics-consistent
  telemetry, training loop).

## Known limitations

- Fallback parser does not implement EPANET pump curves. Use the
  JSON loader for pump fixtures, or install WNTR (pumps still not
  routed through the dPHM pump-affinity layer in Sprint 11 — same
  scope boundary, deferred to a future sprint).
- Valves are unsupported by the steady-state core; any valve row
  raises.
- US-customary flow units (`GPM`, `CFS`, `MGD`, …) are rejected by
  the fallback parser. Convert upstream or use WNTR which performs
  its own SI conversion before our adapter reads its
  `WaterNetworkModel`.
- Tank dynamics not modelled — a tank pins its node to its current
  surface elevation (steady-state surrogate).
- Patterns, controls, rules, quality, energy, and demand multipliers
  are ignored. The dPHM core is steady-state hydraulic; everything
  else stays out of scope.
- No real EPANET binary / runtime / SCADA / PLC / PAC adapters.
- No field accuracy claim. Sprint 11 proves the topology *parses,
  solves, and round-trips through the telemetry generator* on a
  shipped reference fixture. On-site accuracy remains out of scope.

## Verdict

**APPROVED.**

All Sprint 11 hard approval gates pass:

- targeted pytest exits 0 (391 passed, 2 skipped — WNTR optional).
- full pytest exits 0 (399 passed, 2 skipped — WNTR optional).
- compileall exits 0.
- `SPRINT11_REPORT.md` exists.
- Public INP loader `load_network_from_inp` exists, is exported, and
  is documented.
- Fallback parser tests pass without WNTR.
- Shipped `.inp` fixture loads, solves to `~1.6e-10` residual norm
  with the analytic Newton, and round-trips through the physics-
  consistent telemetry generator.
- Optional WNTR test skips cleanly when WNTR is unavailable.
- No secrets / credentials / env files introduced.
- `git status` lists only intended Sprint 11 changes.

## Sprint 12 recommendation

Extend the INP import surface to **support EPANET pump curves**:

1. Add a `[PUMPS]` parsing path (fallback + WNTR) that recognises
   the `HEAD curve_id` form and resolves it against `[CURVES]`.
2. Fit each HEAD curve to the existing
   `H(Q, s) = a0·s² + a1·s·Q + a2·Q²` pump-affinity quadratic used
   by `aquaoptima.dphm.pump_head_gain`.
3. Document fit residual / domain caveats in `docs/epanet-inp-import.md`.
4. Add a shipped pump-bearing reference fixture
   (`docs/examples/epanet_reference_pump.inp`) that loads, solves
   with `newton_solve(..., jacobian_mode="analytic")`, and exercises
   the existing pump residual.
5. Keep the same test gate structure (fallback parser tests
   mandatory, WNTR tests `importorskip`-guarded, telemetry round-trip
   test, no internet / EPANET runtime needed).

This is the smallest credible widening of external-format coverage
after Sprint 11 without crossing into hydraulic-simulator or SCADA
territory. The dPL parameter-learning track, ONNX / TensorRT /
Jetson deployment, real PLC/PAC/SCADA adapters, and field savings
claims remain explicitly out of scope.
