# Sprint 8 — Larger Realistic-Network Experiment

## Goal

Validate that the verified Sprint 7 dPHM-PINN stack (vectorized batched
residual assembly, DataLoader-driven training, sensor-only vs
sensor+physics ablation harness) scales to a network materially larger
than the toy branch / single-loop / pump fixtures, *without*
introducing any field adapters, control paths, or
deployment-environment changes.

Deliverables: a source-agnostic JSON topology loader for EPANET-style
network descriptions, a deterministic O(50-100) node grid fixture,
physics-consistent telemetry on that fixture, a larger-network science
gate, residual-assembly timing data, and a dense-vs-sparse incidence
recommendation for Sprint 9.

## Files changed / created

```text
src/aquaoptima/dphm/network_io.py            NEW   JSON topology loader + validation
src/aquaoptima/dphm/large_fixtures.py        NEW   make_grid_network deterministic builder
src/aquaoptima/dphm/__init__.py              EDIT  export load_network_from_json, make_grid_network
src/aquaoptima/training/ablations.py         EDIT  register fixture="grid" (uses default 7x8 mesh)
tests/dphm/test_network_io.py                NEW   25 tests on JSON loader (happy path + 14 error paths)
tests/dphm/test_large_fixtures.py            NEW   13 tests on grid builder
tests/dataio/test_large_physics_telemetry.py NEW    6 tests on physics-consistent telemetry on grid
tests/training/test_sprint8_large_network_gate.py NEW 3 tests: harness extension, science gate, scaling
tests/training/test_physics_informed_improvement.py EDIT update FIXTURES contract test for "grid"
SPRINT8_REPORT.md                            NEW   this file
```

No existing source modules in `src/aquaoptima/{dphm,dataio,models,training,topology}/`
were modified beyond the two listed `EDIT`s.

## JSON topology schema

Canonical form:

```json
{
  "nodes": [
    {"id": "n0", "demand": -0.05, "fixed_head": true,
     "head_value": 100.0, "elevation": 0.0},
    {"id": "n1", "demand": 0.0,   "fixed_head": false}
  ],
  "edges": [
    {"id": "p0", "source": "n0", "target": "n1", "kind": "pipe",
     "length": 200.0, "diameter": 0.20, "c_factor": 130.0},
    {"id": "pu0", "source": "n5", "target": "n6", "kind": "pump",
     "pump_coeffs": [40.0, 0.0, -800.0], "pump_speed": 1.0}
  ]
}
```

Node fields:

| Field        | Type   | Required                         | Meaning |
|--------------|--------|----------------------------------|---------|
| `id`         | string | yes                              | Stable unique node identifier |
| `demand`     | float  | no (default 0.0)                 | Positive = consumption (m^3/s), negative = supply |
| `fixed_head` | bool   | no (default false)               | Reservoir / tank / pressurised boundary |
| `head_value` | float  | yes iff `fixed_head=true`        | Pinned hydraulic head in metres |
| `elevation`  | float  | no (default 0.0)                 | Informational; reserved for future elevation-aware energy residual |

Edge fields:

| Field         | Type    | Required                  | Meaning |
|---------------|---------|---------------------------|---------|
| `id`          | string  | yes                       | Stable unique edge identifier |
| `source`      | string  | yes                       | Upstream node id |
| `target`      | string  | yes                       | Downstream node id |
| `kind`        | string  | yes (`"pipe"` or `"pump"`)| Edge classification |
| `length`      | float   | yes for pipes (>0)        | Pipe length in metres |
| `diameter`    | float   | yes for pipes (>0)        | Internal diameter in metres |
| `c_factor`    | float   | yes for pipes (>0)        | Hazen-Williams roughness coefficient |
| `pump_coeffs` | [a0,a1,a2] | yes for pumps (`a0 > 0`)| Pump curve coefficients (shut-off head, linear term, quadratic droop) |
| `pump_speed`  | float   | no for pumps (default 1.0)| Affinity-law speed multiplier |

The loader is **source-agnostic**: it carries only structural hydraulic
topology, never PLC / PAC / SCADA tag bindings. Tag-to-channel mapping
remains the responsibility of `aquaoptima.dataio.tag_map`. Either a
path-like (`str` / `pathlib.Path` to a `.json` file) or an already-
decoded in-memory `dict` is accepted; the return value is the
existing `aquaoptima.dphm.Network` dataclass, not a new incompatible
type.

### Validation surface

`load_network_from_json` raises `ValueError` with a descriptive message
for every one of these cases (each has a dedicated test):

* missing `nodes` / `edges` keys, or empty `edges`;
* missing `id` on nodes, missing `source` / `target` on edges;
* duplicate node ids; duplicate edge ids;
* edges referencing unknown source / target node ids;
* fixed-head nodes missing `head_value`;
* topologies with zero fixed-head nodes (singular hydraulic system);
* unknown edge `kind` (must be `"pipe"` or `"pump"`);
* non-positive `length`, `diameter`, or `c_factor` on a pipe edge;
* pump edges missing or malformed `pump_coeffs`, or with non-positive
  shut-off head `a0`.

The returned `Network` re-runs all `Network.__post_init__` checks, so
any residual shape / dimension issue surfaces there.

## Larger deterministic grid network

`make_grid_network(rows, cols, seed=0, *, with_pump=False, ...)`
lays out `rows * cols` nodes on a regular mesh, connects every
horizontally / vertically adjacent pair with a pipe directed toward
increasing node id, pins node `(0, 0)` as the only fixed-head
reservoir at 100 m, and assigns a small jittered positive demand at
every non-reservoir node (reservoir balanced to `-sum(demands)`).
Pipe parameters (length, diameter, c_factor) are drawn from seeded
uniform ranges around physically reasonable defaults.

Default (`rows=8, cols=8`):

| Property             | Value                                           |
|----------------------|-------------------------------------------------|
| Nodes                | 64                                              |
| Edges                | 112 (8·7 horizontal + 7·8 vertical)             |
| Fixed-head nodes     | 1 (node 0 = corner reservoir at 100 m)          |
| Demand at consumers  | ~3·10⁻³ m³/s ± 50% jitter                       |
| Edge pipe params     | length 60-180 m, diameter 0.15-0.30 m, C 120-135 |
| Pump edges           | 0 (default; `with_pump=True` adds one)          |
| Newton convergence   | ✅ 6 iters, ‖r‖ = 1.05·10⁻¹⁰                    |

Sprint 8 also validates `5×5`, `6×6`, `7×7`, `7×8`, `10×10` variants
in tests / report timing tables. The science gate uses a `7×8 = 56`
node / 97-edge mesh — inside the O(50-200) target range and within
the runtime budget that keeps CPU tests <30 s.

## Larger-network telemetry

`generate_physics_consistent_telemetry` (Sprint 5) is topology-
agnostic: it runs `newton_solve` at every timestep on a `replace()`-ed
network whose demands carry the daily-cosine modulation plus a seeded
noise term. Sprint 8 verifies that this generator works unchanged on
the new grid fixture.

`tests/dataio/test_large_physics_telemetry.py` (module-scoped fixture
shares the telemetry across 5 of 6 tests so the test file runs in
~22 s rather than ~60 s):

* shape and finiteness;
* per-step `assemble_residuals` norm < 1·10⁻³ across all 40 steps on
  the `5×5` mesh (generated at `solver_tol=1e-7`);
* batched-vs-unbatched parity on the energy-residual block at `B=8`;
* `WindowDataset` compatibility (40 steps + 32 window = 8 samples);
* determinism for fixed seed.

## Larger-network science gate

### Automated test (`tests/training/test_sprint8_large_network_gate.py`)

Uses a 7×8 = 56-node / 97-edge grid (inside the O(50-200) range) with
`B=8`, 60 iterations, `LinearRampLambda(end=1e-4, ramp_steps=20)`
warmup. Telemetry is generated **once** via a module-scoped fixture
and re-used across the two ablation arms — calling `train_loop`
directly rather than `run_ablation` twice would otherwise double the
telemetry cost.

| Mode                 | final_physics    | training time |
|----------------------|------------------|---------------|
| `sensor_only`        | 5.37·10⁹         | 1.53 s        |
| `sensor_plus_physics`| 1.02·10⁶         | 1.49 s        |
| ratio (sp / so)      | **1.90·10⁻⁴**    |               |

Gate passes: `sensor_plus_physics < sensor_only` AND
`sensor_plus_physics < 0.1 × sensor_only`. Margin is ~500× under the
0.1× bar, so the gate is conservative on this fixture.

Test runs in 25.4 s on the worktree environment (one-time telemetry
generation dominates).

### Manual cross-size table (run via `/tmp/sprint8_manual_gate.py`)

Same hyperparameters as above, varying grid size and batch size:

| Grid | nodes / edges | B  | sensor_only final_physics | sensor+physics final_physics | ratio   |
|------|---------------|----|--------------------------:|-----------------------------:|--------:|
| 7×8  | 56 / 97       | 8  | 5.37·10⁹                  | 1.02·10⁶                     | 1.9·10⁻⁴|
| 8×8  | 64 / 112      | 8  | 5.51·10⁹                  | 3.91·10⁵                     | 7.1·10⁻⁵|
| 7×8  | 56 / 97       | 16 | 1.07·10¹⁰                 | 6.87·10⁶                     | 6.4·10⁻⁴|

Every row clears the 0.1× separation bar by at least 150×. Larger
grids (8×8) achieve **higher** physics-residual reduction than the
smaller 7×8 — consistent with the physics-loss carrying more
information when the unobserved interior of the network grows.

## Residual-assembly timing

Average wall-time per `assemble_residuals` / `assemble_residuals_batched`
call (50 reps, dtype `float64`, CPU only, worktree environment):

| Network                 | unbatched | B=1     | B=8     | B=16    | B=32    |
|-------------------------|----------:|--------:|--------:|--------:|--------:|
| branch (4n, 3e)         | 0.471 ms  | 0.578 ms| 0.455 ms| 0.453 ms| 0.498 ms|
| 5×5 grid (25n, 40e)     | 0.420 ms  | 0.405 ms| 0.431 ms| 0.422 ms| 0.481 ms|
| 7×8 grid (56n, 97e)     | 0.424 ms  | 0.416 ms| 0.465 ms| 0.497 ms| 0.594 ms|
| 8×8 grid (64n, 112e)    | 0.389 ms  | 0.418 ms| 0.499 ms| 0.514 ms| 0.628 ms|
| 10×10 grid (100n, 180e) | 0.422 ms  | 0.459 ms| 0.522 ms| 0.598 ms| 0.753 ms|

Two observations:

1. Single-step assembly is **sub-millisecond** across every fixture
   tested — including 100-node grids — so the dense incidence
   multiply is not the bottleneck for residual assembly at this scale.
2. Scaling with `B` is gentle (≤2× from `B=1` to `B=32`), confirming
   that the Sprint 7 batched-residual contract holds at scale.

Steady-state `newton_solve` (dense Jacobian via
`torch.autograd.functional.jacobian` + dense linear solve) on the
same grids:

| Grid     | nodes / edges | newton_solve time | iters | final residual |
|----------|---------------|------------------:|------:|---------------:|
| 5×5      | 25 / 40       | 198 ms            | 7     | 3.4·10⁻⁹       |
| 7×8      | 56 / 97       | 376 ms            | 6     | 5.5·10⁻⁸       |
| 8×8      | 64 / 112      | 427 ms            | 6     | 1.1·10⁻¹⁰      |
| 10×10    | 100 / 180     | 724 ms            | 6     | 7.6·10⁻⁷       |

## Dense-vs-sparse incidence recommendation

**Dense incidence remains the right default at this scale.** Two pieces
of evidence:

1. `incidence_matrix(...)` is rebuilt on every `assemble_residuals` /
   `assemble_residuals_batched` call. For a 100-node, 180-edge grid
   that single matrix is 100×180 = 18 000 float32s (~72 KB) — trivial.
2. The dense `flows @ A.T` mass-balance multiply runs in <1 ms even
   at `B=32` on a 100-node mesh. No sparse-format constant factor
   would beat that in PyTorch on CPU at this size.

A separate, larger lever is the **Newton solver Jacobian**. Each call
to `torch.autograd.functional.jacobian` on a (free_heads + edges)-D
state vector is O(N²) function evaluations followed by O(N³) dense
LU. At 56 nodes that is ~0.4 s; at 100 nodes ~0.7 s. Telemetry
generation (33-48 timesteps × per-step Newton) is the dominant cost
in this Sprint's tests (≈15-20 s for `7×8`).

**Sprint 9 recommendation**: do **not** rewrite the dense incidence
multiply. Instead, evaluate either an analytical Jacobian
(`assemble_residuals` is differentiable in closed form for both pipe
and pump rows) or a Krylov + sparse-LU solver. Either should shrink
the per-step Newton wall time by 5-10× at 100 nodes and unblock
larger fixtures (200+ nodes) for telemetry generation. *Caching*
the incidence matrix on the `Network` object is a small adjacent
win and could ride along, but is not the primary lever.

## Validation commands

All four commands from the Sprint 8 brief were run on the worktree
branch `sprint8` (worktree at
`/home/hunter_lin/projects/aquaoptima-dphm-pinn-sprint8`):

```bash
python -m pytest tests/dphm tests/models tests/training tests/dataio -q
# -> 316 passed, 3 warnings in 69.63s

python -m pytest tests -q
# -> 324 passed, 3 warnings in 69.46s

python -m compileall src tests
# -> clean (no errors)

git status --short
# (see below)
```

`git status --short` shows the Sprint 8 deltas only:

```
 M src/aquaoptima/dphm/__init__.py
 M src/aquaoptima/training/ablations.py
 M tests/training/test_physics_informed_improvement.py
?? src/aquaoptima/dphm/large_fixtures.py
?? src/aquaoptima/dphm/network_io.py
?? tests/dataio/test_large_physics_telemetry.py
?? tests/dphm/test_large_fixtures.py
?? tests/dphm/test_network_io.py
?? tests/training/test_sprint8_large_network_gate.py
?? SPRINT8_REPORT.md
```

## Tests added (47 new)

* `tests/dphm/test_network_io.py` — 25 tests (loader happy paths +
  round-trip equivalence with `make_branch_network` + 14 invalid-schema
  error paths + solver compatibility).
* `tests/dphm/test_large_fixtures.py` — 13 tests (shape, determinism,
  seed sensitivity, mass conservation, pipe-parameter positivity,
  edge classification, residual / batched-residual / Newton-solver /
  graph-feature compatibility).
* `tests/dataio/test_large_physics_telemetry.py` — 6 tests
  (shape, finiteness, residual closeness, batched parity, dataset
  compatibility, determinism).
* `tests/training/test_sprint8_large_network_gate.py` — 3 tests
  (harness fixture registry, science gate, batched-residual scaling).
* `tests/training/test_physics_informed_improvement.py` — 1 test
  updated to include `"grid"` in the asserted `FIXTURES` set.

## Compatibility notes

* `Network` dataclass — unchanged. The loader and the grid builder
  both return validated instances of the existing dataclass, so every
  Sprint 1-7 consumer (`assemble_residuals`,
  `assemble_residuals_batched`, `newton_solve`, `build_graph_features`,
  `DPHMPINN`, `composite_loss`) accepts them with zero adapter code.
* `TelemetrySeries` — unchanged. The Sprint 5 physics-consistent
  generator works on the new fixture without modification.
* `aquaoptima.training.ablations.run_ablation` — additive change only:
  `fixture="grid"` is now a valid arg; the four other fixture names
  and every other parameter behave as before. The existing
  Sprint 5 / 6 / 7 science-gate tests continue to pass unchanged.
* No real PLC / PAC / SCADA adapter, write path, dPL parameter
  learning, ONNX / TensorRT / Jetson deployment, or live EPANET
  execution dependency was introduced.

## Known limitations

1. The dense `torch.autograd.functional.jacobian` inside `newton_solve`
   is the single biggest contributor to test runtime on the larger
   grid. Telemetry generation for a `7×8` mesh takes ~15-20 s on
   CPU, which is why the automated science gate uses a module-scoped
   fixture rather than re-running `run_ablation` twice. For the same
   reason, `tests/dataio/test_large_physics_telemetry.py` uses a
   smaller `5×5` mesh.
2. The grid builder lays out a regular mesh with all edges directed
   toward increasing node id. Real distribution networks have
   irregular topology and bidirectional flow patterns; we accept
   that limitation here because the goal is to exercise scale, not
   topological realism.
3. Sensor-mask placement for the grid is heuristic (reservoir +
   midpoint + opposite corner). A more principled placement
   strategy (e.g. observability-driven optimisation) is out of scope.
4. Pumps inside a grid are supported via `with_pump=True` but were
   not exercised in the Sprint 8 science gate — the default
   pipe-only mesh converges more reliably and was sufficient for the
   gate.

## Exact Sprint 9 recommendation

Cache or replace the **Newton solver Jacobian**, not the dense
incidence multiply. Specifically:

1. Implement an analytical Jacobian for `assemble_residuals` (the
   Hazen-Williams head loss has a closed-form derivative; pump
   energy is quadratic in `Q`; incidence rows are constant). This
   removes the per-Newton-iteration autograd traversal.
2. Cache the dense incidence matrix on the `Network` dataclass so it
   is built once at construction and reused by every assembly call.
   Small, low-risk adjacent win.
3. With (1) + (2), re-time `newton_solve` on the `10×10` and
   `12×12` fixtures. If wall time drops by ≥5×, extend the science
   gate to a 100+ node mesh as part of the Sprint 9 deliverable. If
   the gain is smaller, evaluate a sparse-LU or Krylov path before
   raising the gate fixture size.
4. Do **not** rewrite the batched residual path; the Sprint 7
   vectorized contract (`flows @ A.T` plus `torch.where`) is already
   well under 1 ms at every batch size tested here.

Sprint 9 should *not* introduce field adapters, control paths, or
any of the Sprint 8 spec's "not allowed" items — this remains a
synthetic / reference-only experiment.
