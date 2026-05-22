# AquaOptima dPHM-PINN — Sprint 1 Report

## Scope delivered

Sprint 1 ships the dPHM physics primitives plus the minimal Python
packaging needed to test them. No PLC, PID, dPL, GNN, TensorRT, cloud,
or Sprint 2+ work was started.

## Files created

### Packaging / docs
- `pyproject.toml` (new) — setuptools project, `torch` dep, `dev` extra
  with pytest, `pytest.ini_options` pointing at `tests/`.
- `README.md` (new) — unit conventions, install/test commands.
- `src/aquaoptima/__init__.py` (new) — package version.
- `src/aquaoptima/dphm/__init__.py` (new) — re-exports the public surface.

### dPHM primitives (`src/aquaoptima/dphm/`)
- `hazen_williams.py` — `hazen_williams_head_loss(Q, L, D, C, eps=1e-6)`,
  signed, broadcast-safe, finite at Q=0, raises `ValueError` on
  non-positive L/D/C.
- `pump_affinity.py` — `pump_head_gain(Q, speed_ratio, coeffs)`, accepts
  batched coefficients, validates `speed_ratio ∈ [0, 1.5]`.
- `incidence.py` — `incidence_matrix(edge_index, num_nodes)` (source=-1,
  target=+1) and `node_flow_balance(edge_index, flows, demands, num_nodes)`
  returning `A @ flows - demands`.
- `residuals.py` — `mass_residual`, `pipe_energy_residual`
  (`h_u - h_d - h_loss`), `pump_energy_residual`
  (`h_d - h_u - pump_gain`).
- `feasibility.py` — `FeasibilityResult` dataclass and `check_feasibility`
  with all bounds opt-in (no unsafe defaults).
- `autograd_checks.py` — `assert_finite_gradients(loss, tensors)` that
  clears stale grads, runs backward, and asserts every tensor has a finite
  gradient.

### Tests (`tests/dphm/`)
- `test_hazen_williams.py` — 14 tests
- `test_pump_affinity.py` — 13 tests
- `test_incidence.py` — 5 tests
- `test_residuals.py` — 7 tests
- `test_feasibility.py` — 8 tests
- `test_autograd.py` — 5 tests

**Total: 52 tests, all passing.**

Each test set was written first, observed to fail with `ModuleNotFoundError`
(strict TDD red phase), then the minimum production code was written until
all of them passed (green phase).

## TDD evidence summary

| Module | Red (initial fail) | Green (pass) |
|---|---|---|
| hazen_williams | ImportError observed | 14/14 |
| pump_affinity | ImportError observed | 13/13 |
| incidence | ImportError → 1 float32 tolerance fix | 5/5 |
| residuals | ImportError observed | 7/7 |
| feasibility | ImportError observed | 8/8 |
| autograd_checks | ImportError observed | 5/5 |

The only test-side adjustment after the red phase was loosening
`atol=1e-9` to `1e-6` for a balanced-network residual, which is a
realistic float32 round-off tolerance — not a relaxation of the physics.

## Commands run

```bash
# environment
python3 -c "import torch"                              # ModuleNotFoundError
pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
pip install -e . --quiet

# strict TDD loop, per module, e.g.:
python -m pytest tests/dphm/test_hazen_williams.py -q  # red, then green

# final validation
python -m pytest tests/dphm -q   # 52 passed
python -m pytest tests -q        # 52 passed
```

## Pass / fail status

- `python -m pytest tests/dphm -q` → **52 passed**
- `python -m pytest tests -q` → **52 passed**

No skips, no xfails, no warnings beyond library defaults.

## Known limitations

1. **CPU-only torch build.** Installed from the official CPU index; no
   CUDA/TensorRT path exists yet. Sprint 1 does not need it.
2. **Float32 default dtype.** Tests use `torch.get_default_dtype()` and
   tolerate float32 round-off (`atol=1e-6` for mass balance). dPHM solvers
   that need tighter closure should opt into float64 explicitly.
3. **Hazen-Williams gradient at exactly Q=0** is zero (torch's `sign(0)=0`
   and `|Q|` subgradient choice). It is *finite* — which is what the spec
   and test require — but a PINN that camps at Q=0 may need a smoother
   `sign` surrogate (e.g. `tanh(Q/eps)`).
4. **No `cycle_residual`** primitive — energy balance is per-edge only.
   Loop closure is implicit via paired pipe residuals; a dedicated cycle
   primitive will land when the network topology API is introduced.
5. **No solver, no demo network, no PINN training loop.** Out of Sprint 1
   scope by design.
6. **Validation of `coeffs[..., 3]` only at the last dim.** Higher-order
   pump curves are not yet supported.
7. **No git repo initialised.** Repo did not exist before this sprint and
   no commits were made; primitives ship as plain files only.

## Recommended Sprint 2 entry point

**Build the dPHM steady-state solver around these primitives.** Concretely:

1. Introduce a `Network` dataclass that holds `edge_index`, edge
   metadata (pipe vs. pump, L/D/C, pump coeffs), node metadata
   (junctions / reservoirs / tanks), and demand vectors — so callers
   stop passing tensors positionally.
2. Implement a vectorised steady-state Newton solver that drives
   `mass_residual` + `pipe_energy_residual` + `pump_energy_residual` to
   zero jointly for `(heads, flows)` given demands and pump speeds.
3. Reuse `hazen_williams_head_loss` and `pump_head_gain` as the only
   constitutive calls — no duplicate physics. Verify by autograd:
   `assert_finite_gradients` over the converged loss with respect to
   demands and pump speeds proves end-to-end differentiability.
4. Validate against a known EPANET reference network (e.g. Net1 from
   the EPANET examples) so any divergence from textbook hydraulics is
   caught before training a PINN on top.

After that solver lands and is differentiable, Sprint 3 can start the
PINN training loop with confidence that the physics is correct.
