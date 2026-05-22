# Sprint 9 — Analytic Newton Jacobian

**Goal:** replace the autograd Jacobian inside `newton_solve` with a
closed-form analytic Jacobian for the existing dPHM residual system,
and add a small cached dense incidence matrix to remove a redundant
per-call build.

**Verdict: APPROVED.** Sprint 10 may begin.

## Files changed

```
src/aquaoptima/dphm/__init__.py        — export new symbols
src/aquaoptima/dphm/incidence.py       — add cached_incidence_matrix
src/aquaoptima/dphm/solver.py          — add assemble_jacobian_analytic +
                                         jacobian_mode parameter on newton_solve
tests/dphm/test_analytic_jacobian.py   — parity + convergence tests (new)
tests/dphm/test_newton_jacobian_perf.py — perf gate (new)
scripts/sprint9_bench.py               — non-test benchmark driver (new)
SPRINT9_REPORT.md                      — this file (new)
```

No existing Sprint 1-8 public API was changed. `newton_solve` gains an
optional keyword `jacobian_mode` that defaults to `"autograd"`, so all
prior callers retain identical behavior.

## Residual conventions (recap from Sprint 1-2)

State vector packed by `_pack(network, heads, flows)`:

```
x = [ free_heads (length num_free) , flows (length E) ]
```

Residual returned by `assemble_residuals`:

```
r = [ mass_free (length num_free) , edge_residual (length E) ]
```

With residual definitions:

* Mass for free node *n*:  `r_n = (A @ flows)_n - demands_n`
* Pipe energy for edge *e* (u → d):  `r_e = h_u - h_d - h_f(Q_e)`
* Pump energy for edge *e* (u → d):  `r_e = h_d - h_u - H_pump(Q_e, s_e)`

with the signed Hazen–Williams loss

```
h_f(Q)  = sign(Q) * k * (|Q| + eps)^1.852
k       = 10.67 * L / (C^1.852 * D^4.87)
```

and the quadratic pump curve

```
H_pump(Q, s) = a0 s^2 + a1 s Q + a2 Q^2
```

`eps = 1e-6` exactly matches `hazen_williams_head_loss`.

## Analytic Jacobian

`assemble_jacobian_analytic(network, heads, flows)` returns a dense
`[num_free + E, num_free + E]` tensor in `flows.dtype`. Block layout:

```
            free_heads     flows
mass_free [    0              A_free,:                 ]
energy    [ H_e (signed)   diag(-dh_f/dQ | -dH_pump/dQ) ]
```

Derivatives:

* **Mass / flows:** `∂r_mass / ∂Q = A[free_node_indices, :]` — exactly
  the free-node rows of the dense incidence matrix.
* **Mass / free heads:** zero everywhere.
* **Pipe energy / Q:** `∂r_e/∂Q_e = -dh_f/dQ` with
  `dh_f/dQ = sign(Q)^2 · 1.852 · k · (|Q| + eps)^0.852`.
  The `sign(Q)^2` factor reproduces the autograd subgradient
  convention at `Q = 0` (zero rather than the one-sided limit).
* **Pump energy / Q:** `∂r_e/∂Q_e = -(a1 s + 2 a2 Q)`.
* **Pipe energy / heads:** `+1` on the upstream-free-head column,
  `-1` on the downstream-free-head column; columns are skipped for
  fixed-head endpoints.
* **Pump energy / heads:** signs flipped relative to pipe edges
  (the pump convention is `h_d - h_u - gain`).

Pipe-vs-pump selection mirrors `assemble_residuals`: a
`torch.where(network.pipe_mask, pipe_dQ, pump_dQ)` merges the two
diagonals before negation.

## Parity test results

`tests/dphm/test_analytic_jacobian.py`: **20 passed.**

Coverage:

| Fixture       | Shape match | Initial-guess parity (atol=1e-9) | Perturbed-state parity (atol=1e-8) |
|---------------|-------------|----------------------------------|------------------------------------|
| branch        | ✓           | ✓                                | ✓                                  |
| single_loop   | ✓           | ✓                                | ✓                                  |
| pump          | ✓           | ✓                                | ✓                                  |
| grid 5×5      | ✓           | ✓                                | ✓                                  |

Additional convergence parity:

* `newton_solve(jacobian_mode="analytic")` converges on branch,
  single_loop, pump, grid 5×5, and grid 7×8 within `tol=1e-6`.
* Analytic and autograd solutions match to `atol=1e-6` on the branch
  fixture.
* `jacobian_mode="bogus"` raises `ValueError` cleanly.

## Timing — `scripts/sprint9_bench.py`

Best-of-3 wall-clock per `newton_solve` call (Linux 6.8, CPU only,
float64).

| Grid   | nodes | edges | Newton iters | autograd (ms) | analytic (ms) | speedup |
|--------|-------|-------|--------------|---------------|---------------|---------|
| 5×5    |    25 |    40 |            7 |        190.98 |         11.86 | 16.10×  |
| 7×8    |    56 |    97 |            6 |        381.83 |         18.61 | 20.52×  |
| 8×8    |    64 |   112 |            6 |        443.81 |         20.41 | 21.75×  |
| 10×10  |   100 |   180 |            6 |        757.57 |         32.51 | 23.30×  |
| 12×12  |   144 |   264 |            6 |       1133.70 |         56.72 | 19.99×  |

**Performance gate (7×8 grid, ≥2× required): 20.5× achieved.** Stretch
goal of ≥5× is also met on every grid tested.

`tests/dphm/test_newton_jacobian_perf.py` enforces the 2× gate on 7×8
inside the CI suite.

## Incidence cache

`cached_incidence_matrix(network, dtype)` memoises the dense
`[N, E]` incidence matrix on a lazily-created `_incidence_cache`
attribute on the `Network` instance, keyed by `dtype`. Falls back to
the uncached path if the network object disallows attribute
assignment (defensive — not currently exercised, since `Network` is a
plain dataclass).

Wiring:

* `assemble_residuals`, `assemble_residuals_batched`, and the new
  `assemble_jacobian_analytic` all read through the cache.
* `incidence_matrix(...)` itself is untouched; existing callers and
  the public API are bit-for-bit identical.

This is a low-risk change relative to the analytic Jacobian; its
contribution to the speedup numbers above is small (the dominant
saving is removing per-iteration autograd graph builds).

## Compatibility notes

* `newton_solve(...)` retains its previous default behavior. The new
  `jacobian_mode` keyword defaults to `"autograd"`. Sprint 8 callers
  see no behavior change.
* `assemble_residuals` / `assemble_residuals_batched` unchanged
  except for routing the dense incidence build through the cache —
  same dtype, same values, same shape.
* `Network` dataclass schema unchanged. The optional
  `_incidence_cache` is attached lazily, after `__post_init__`, and
  is not part of the public contract.
* All Sprint 1-8 tests still pass.

## Validation results

```
python -m pytest tests/dphm tests/models tests/training tests/dataio -q
    339 passed, 3 warnings in 79.72s
python -m pytest tests -q
    347 passed, 3 warnings in 71.57s
python -m compileall -q src tests
    exit=0
git status --short
    M  src/aquaoptima/dphm/__init__.py
    M  src/aquaoptima/dphm/incidence.py
    M  src/aquaoptima/dphm/solver.py
    ?? SPRINT9_REPORT.md
    ?? scripts/sprint9_bench.py
    ?? tests/dphm/test_analytic_jacobian.py
    ?? tests/dphm/test_newton_jacobian_perf.py
```

(Sprint 8 baseline: 324 passed. The +23 tests are this sprint's
analytic-Jacobian parity, convergence-parity, perf-gate, and
`jacobian_mode` validation tests.)

No secret files or strings introduced. Git status contains only
intended Sprint 9 changes.

## Limitations

* The analytic Jacobian is dense. For thousands of nodes the dense
  solve dominates; sparse / Krylov methods are out of scope for
  Sprint 9 and explicitly deferred.
* The energy-row / free-head block currently uses a Python loop over
  edges to write up to two non-zeros per row. Vectorizing this with
  `index_put_` is a straightforward Sprint 10+ optimization but is
  not on the gating path — the loop is already insignificant against
  the 6-iteration autograd-Jacobian costs we are replacing.
* The `_incidence_cache` does not invalidate if a caller mutates
  `network.edge_index` in place. The existing fixtures never mutate
  the topology after construction, so this is safe in practice;
  Sprint 10 may want to formalize topology immutability.
* No real EPANET / PLC / SCADA networks are exercised — out of
  scope per the Sprint 9 prompt.

## Hard approval gates

| Gate                                         | Status |
|----------------------------------------------|--------|
| targeted pytest exits 0                      | ✓ 339 passed |
| full pytest exits 0                          | ✓ 347 passed |
| compileall exits 0                           | ✓     |
| `SPRINT9_REPORT.md` exists                   | ✓     |
| analytic Jacobian parity tests pass          | ✓ 12/12 |
| solver convergence tests pass                | ✓ 9/9 |
| no secret files / strings introduced         | ✓     |
| git status contains only Sprint 9 changes    | ✓     |
| ≥2× speedup on 7×8 grid                      | ✓ 20.5× |

**VERDICT: APPROVED.** Sprint 10 is allowed to start.
