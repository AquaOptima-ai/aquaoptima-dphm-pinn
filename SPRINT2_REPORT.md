# AquaOptima dPHM-PINN — Sprint 2 Report

## Scope delivered

Sprint 2 builds the **dPHM steady-state foundation** on top of the
Sprint 1 primitives: a structured `Network` dataclass, three synthetic
topology fixtures (branch / single-loop / pump), a residual-assembly +
damped-Newton solver, and explicit failure-classified diagnostics.

No Sprint 3+ work was started (no GATv2/PyG model, no training loop, no
dPL, no TensorRT/ONNX, no PLC/PID integration, no real-Yilan claims).

## Files created

### Production code (`src/aquaoptima/dphm/`)
- `network.py` — `Network` dataclass. Holds `edge_index`, `pipe_mask`,
  `pump_mask`, `lengths`, `diameters`, `c_factors`, `pump_coeffs`,
  `pump_speeds`, `demands`, `fixed_head_mask`, `fixed_head_values`.
  Validates every shape, dtype, and mask invariant in `__post_init__`
  (no silent coercion; bad input raises `ValueError`).
- `fixtures.py` — `make_branch_network()`, `make_single_loop_network()`,
  `make_pump_network()`. Every fixture is mass-balanced
  (`sum(demands) == 0`) and uses hand-traceable topology.
- `solver.py` — `assemble_residuals(network, heads, flows)` returns
  `[mass_free | edge_energy]`. `residual_norm(...)` is the scalar L2.
  `initial_guess(...)` produces a smooth, non-zero starting state.
  `newton_solve(...)` is a dense, damped Newton iteration that uses
  `torch.autograd.functional.jacobian` and `torch.linalg.solve`, with
  fallback to `lstsq`. Returns a structured `SolveResult`.
- `diagnostics.py` — `SolveResult` dataclass and `SolveFailureReason`
  string-enum (`max_iterations`, `diverged`, `nan_residual`,
  `singular_jacobian`). `classify_failure(...)` deterministically maps
  the solver's terminal state to a reason (or `None` if converged).
  `SolveResult.__post_init__` rejects `converged=True` paired with a
  non-finite norm or a non-null `reason` — the solver cannot lie.

### Tests (`tests/dphm/`)
- `test_network.py` — 12 tests covering construction, shape validation,
  mask overlap/unclassified detection, fixed-head sanity, accessor
  correctness.
- `test_fixtures.py` — 8 tests confirming each fixture is a valid
  `Network` and is globally mass-balanced.
- `test_solver.py` — 12 tests covering residual shape, the
  hand-calibrated zero-residual branch state, residual-norm gradient
  flow, Newton convergence on branch / pump / single-loop, max-iteration
  failure handling, residual self-consistency on failed solves, and an
  end-to-end gradient w.r.t. `demands`.
- `test_diagnostics.py` — 8 tests covering `SolveResult` invariants,
  failure classification (max-iter / diverge / NaN / converged), and
  the public enum values.

### Package wiring
- `src/aquaoptima/dphm/__init__.py` — exports the new public surface
  (`Network`, fixtures, `assemble_residuals`, `residual_norm`,
  `newton_solve`, `initial_guess`, `SolveResult`,
  `SolveFailureReason`, `classify_failure`).

**New tests this sprint: 40. Total tests in repo: 92, all passing.**

## TDD evidence summary

Each module went through a strict red → green cycle. The red phase was
observed as a `ModuleNotFoundError` from pytest collection before any
production code existed; the green phase ran the same command after
implementing the minimum code to satisfy the tests.

| Module | Red (observed) | Green (final) |
|---|---|---|
| network | `ModuleNotFoundError: aquaoptima.dphm.network` | 12/12 |
| fixtures | `ModuleNotFoundError: aquaoptima.dphm.fixtures` | 8/8 |
| diagnostics | `ModuleNotFoundError: aquaoptima.dphm.diagnostics` | 8/8 |
| solver | `ModuleNotFoundError: aquaoptima.dphm.solver` | 12/12 |

No test was relaxed after the red phase. The branch-state energy-balance
test (`test_assemble_residuals_zero_for_balanced_branch_at_consistent_state`)
uses `atol=1e-5` because heads are reconstructed from a Hazen-Williams
forward pass in float32 by default; this is the same float-precision
realism the Sprint 1 tests already adopted.

## Commands run

```bash
# strict TDD loop per module, e.g.
python -m pytest tests/dphm/test_network.py -q       # red, then green
python -m pytest tests/dphm/test_fixtures.py -q      # red, then green
python -m pytest tests/dphm/test_diagnostics.py -q   # red, then green
python -m pytest tests/dphm/test_solver.py -q        # red, then green

# final validation
python -m pytest tests/dphm -q   # 92 passed
python -m pytest tests -q        # 92 passed
```

## Pass / fail status

- `python -m pytest tests/dphm -q` → **92 passed**
- `python -m pytest tests -q` → **92 passed**

No skips, no xfails, no new warnings. Sprint 1's 52 tests continue to
pass alongside Sprint 2's 40 new tests.

## Known limitations

1. **Solver is dense and small-network only.** It evaluates a full
   Jacobian via `torch.autograd.functional.jacobian` every iteration
   and calls `torch.linalg.solve` on the resulting square matrix. This
   is fine for the Sprint 2 fixtures (≤4 edges) but will not scale to
   real distribution networks. Sparse Jacobian assembly and an
   iterative linear solve (or block-LU) are deferred.
2. **No global-loop residual primitive.** Loop closure is enforced
   implicitly through per-edge energy residuals and the directed
   incidence matrix. A dedicated `cycle_residual` could improve
   conditioning on multi-loop networks; not needed for the
   single-loop fixture used here.
3. **No EPANET cross-validation.** The solver is tested only against
   hand-traceable synthetic networks. The Sprint 1 report
   recommendation to validate against EPANET Net1 has been deliberately
   left to Sprint 3 — landing a working dense solver first lets that
   validation be a check on physics, not on solver bugs.
4. **Solver internally promotes to float64.** This makes convergence to
   `1e-6` reliable but means the returned `heads`/`flows` are float64
   regardless of input dtype. Float32-only deployments will need an
   explicit downcast at the call site.
5. **No damping schedule.** Damping is a static argument
   (default 1.0). For more aggressive networks a backtracking line
   search or Levenberg–Marquardt step will help; deferred.
6. **`SolveFailureReason.SINGULAR_JACOBIAN`** is reachable through code
   paths in `newton_solve` (both `linalg.solve` and the `lstsq`
   fallback raising) but has no dedicated test — the fixtures used
   here do not produce a singular Jacobian. Coverage will arrive when
   pathological-network tests are added in Sprint 3.
7. **Pump rows still carry placeholder pipe parameters** (e.g.
   `lengths=1.0`, `diameters=0.10`, `c_factors=130`) so that
   `hazen_williams_head_loss` passes its positivity validation. The
   masked `torch.where` in `assemble_residuals` correctly discards the
   placeholder result for pump edges, but a cleaner per-edge dispatch
   (separate vectors per edge class) would remove the foot-gun. Out of
   Sprint 2 scope.
8. **Initial guess is naive.** All free heads start at the mean of the
   fixed-head values and all flows start at `+0.01 m^3/s`. This
   converges on the included fixtures but would mis-orient flows on
   networks with strong supply asymmetry. A topology-aware initial
   guess (e.g. weighted spanning-tree flow) is deferred.

## Recommended Sprint 3 entry point

**Validate the dPHM solver against a real reference network, then start
the PINN training loop.** Concretely:

1. **EPANET Net1 (or equivalent) round-trip.** Import the topology and
   demand schedule, run `newton_solve` at one time-step, and compare
   heads/flows against the EPANET reference within
   `1e-3` relative error. Any divergence here is a physics bug to fix
   before training a PINN on top.
2. **Sparse Jacobian + iterative linear solve.** Replace
   `torch.autograd.functional.jacobian` + dense `linalg.solve` with a
   sparse Jacobian assembly (the incidence matrix is already sparse)
   and a CG / GMRES inner solver. This is the only change required to
   make the solver tractable on real networks.
3. **GATv2 head-prediction model on top of the solver.** Wire the
   solver as a differentiable layer so a PyG-based GATv2 model can be
   trained with `assemble_residuals` as the physics loss, plus
   supervised heads from EPANET as the data loss. `assert_finite_gradients`
   over the combined loss proves end-to-end differentiability before
   the first epoch.
4. **dPL parameter calibration.** Treat `c_factors` (and optionally
   pump curve coefficients) as differentiable parameters and learn
   them from observed pressure data, using the converged solver as the
   forward operator.

PLC / PID integration, TensorRT export, and any Yilan-specific
validation remain explicitly out of scope until the PINN training loop
itself is stable.
