# Sprint 7 Report — Vectorized residuals + DataLoader wiring

## Goal

Scale the physics residual evaluation and wire real PyTorch
``DataLoader`` batching into the training path. Preserve all Sprint
1-6 behaviour; do not change dPHM equations or open the write/control
path.

## Files changed

```text
src/aquaoptima/dphm/__init__.py          # re-export assemble_residuals_batched
src/aquaoptima/dphm/solver.py            # new assemble_residuals_batched helper
src/aquaoptima/models/losses.py          # physics_residual_loss batched path now vectorized
src/aquaoptima/training/__init__.py      # re-export make_window_dataloader + train_loop_dataloader
src/aquaoptima/training/train.py         # make_window_dataloader + train_loop_dataloader
src/aquaoptima/training/ablations.py     # wall-clock timing + batch_size on summary
src/aquaoptima/training/metrics.py       # elapsed_seconds / batch_size fields on summary
tests/models/test_batched_losses.py      # +2 Sprint 7 tests (vectorized call, B=16 parity)
tests/dphm/test_batched_residuals.py     # new — 16 tests
tests/training/test_dataloader_training.py  # new — 8 tests
tests/training/test_sprint7_science_gate.py # new — 3 tests
SPRINT7_REPORT.md                        # this file
```

## Tests added (29 new tests; 277 total, 248 prior)

* ``tests/dphm/test_batched_residuals.py`` (16 tests, all 3 fixtures
  parametrised):
  * shape contract ``[B, N] + [B, E] -> [B, num_free + E]``
  * B=1 parity with unbatched ``assemble_residuals`` (atol 1e-10)
  * B=4 parity with manual stack of unbatched residuals (atol 1e-10)
  * gradients finite through both inputs
  * float32 / float64 dtype preservation
  * rank-mismatch + batch-mismatch rejection

* ``tests/models/test_batched_losses.py`` (+2 tests on top of Sprint
  6 coverage):
  * monkeypatch-counted assertion that the batched path calls
    ``assemble_residuals_batched`` exactly once and never falls back
    into the unbatched Python loop
  * B=16 parity vs the stacked unbatched sum

* ``tests/training/test_dataloader_training.py`` (8 tests):
  * ``make_window_dataloader`` returns a ``torch.utils.data.DataLoader``
  * batched shapes ``[B, T, N, F] / [B, N] / [B, E]``
  * ``drop_last=False`` produces a partial tail batch covering the
    whole dataset exactly once
  * batches match a direct ``collate_windows`` call (the DataLoader
    really uses Sprint 6's collator)
  * no future leakage: target pressure does not appear inside any
    window
  * ``train_loop_dataloader`` advances training, keeps finite loss
    components, and changes ≥1 model parameter
  * loop cycles the loader when ``num_iterations`` exceeds the
    number of batches
  * DataLoader ``batch_size=1`` train_step matches the legacy
    unbatched train_step on the same window (atol 1e-4)

* ``tests/training/test_sprint7_science_gate.py`` (3 tests):
  * ``B=8`` sensor+physics beats sensor-only by ≥10x on the physics
    residual
  * ``run_ablation`` emits ``elapsed_seconds`` + ``batch_size`` in
    its summary
  * ``batch_size`` round-trips through the summary

## Commands run

```bash
PYTHONPATH=$PWD/src python -m pytest tests/dphm tests/models tests/training tests/dataio -q
PYTHONPATH=$PWD/src python -m pytest tests -q
PYTHONPATH=$PWD/src python -m compileall src tests
git status --short
```

(``PYTHONPATH`` points at the worktree's ``src/`` so the worktree's
code is exercised even though the global ``pip install -e`` points at
the main repo. The pyproject editable install convention from the
main worktree is unchanged.)

## Pass / fail status

* ``pytest tests -q`` — **277 passed**, 3 warnings (pre-existing
  PyG/torch deprecations); 0 failures.
* ``compileall src tests`` — clean.
* ``git status --short`` — see "Files changed" above; no unintended
  modifications.

## Batched residual performance / shape contract

``assemble_residuals_batched(network, heads: [B, N], flows: [B, E])
-> [B, num_free_nodes + num_edges]``

* Single vectorized incidence multiply ``flows @ A.T``; no Python loop
  over the batch axis.
* Mass block: ``mass[b, n] = (flows @ A.T)[b, n] - demands[n]``,
  sliced down to free nodes via ``[:, ~fixed_head_mask]``.
* Energy block: ``h_u = heads.index_select(1, src)``,
  ``h_d = heads.index_select(1, dst)``; Hazen-Williams + pump-affinity
  broadcast naturally from ``[E]`` parameter tensors to ``[B, E]``
  flow tensors; pipe vs pump selection via a single ``torch.where``
  on a broadcast pipe mask.
* No fallback per-edge Python branch — every edge in the batched call
  is dispatched by the same masked ``torch.where``.
* dtype preservation: the output dtype matches ``flows.dtype`` (float32
  in, float32 out; float64 in, float64 out). Tested.

The unbatched ``assemble_residuals`` is untouched, so all Sprint 2-5
solver / training paths remain bit-for-bit equivalent.

## Physics-residual-loss batched path

``physics_residual_loss`` now dispatches the rank-2 branch through
``assemble_residuals_batched`` and computes ``(residual ** 2).sum()``
in one expression. The legacy semantics (sum of per-batch squared L2
norms — exactly what the Sprint 6 loop produced) is preserved.

A monkeypatch-based test asserts there is exactly one call to the
batched helper per ``physics_residual_loss`` invocation and zero
calls to the unbatched assembler — the Python loop is gone, not just
hidden.

## DataLoader usage contract

```python
from aquaoptima.training import make_window_dataloader, train_loop_dataloader

loader = make_window_dataloader(dataset, batch_size=8, shuffle=False)
metrics = train_loop_dataloader(
    model=..., loader=loader, features=..., network=..., optimizer=...,
    config=TrainConfig(
        num_iterations=60,
        lambda_data=FixedLambda(1.0),
        lambda_physics=LinearRampLambda(0.0, 1e-4, 20),
        batch_size=8,
    ),
)
```

* The collator is the Sprint 6 ``collate_windows``, so output batches
  carry ``x_seq: [B, T, N, F]``, ``target_pressure: [B, N]``,
  ``target_flow: [B, E]``, ``target_demand: [B, N]``.
* ``train_loop_dataloader`` cycles the loader when
  ``num_iterations`` exceeds ``len(loader)``, matching the legacy
  ``train_loop`` index-cycling contract.
* No future leakage: ``WindowDataset`` already guarantees
  ``x_seq[..., :, 1]`` (the pressure channel) never equals
  ``target_pressure`` for the same window; the DataLoader path tests
  this end-to-end.
* The legacy index-cycling ``train_loop`` is untouched, so existing
  callers (notably ``run_ablation``) do not see any behaviour change.

## Larger-batch science gate metric table

Branch fixture, ``physics_consistent`` telemetry, ``num_steps=48``,
``window=32``, ``num_iterations=60``, seed 0. Sensor mask = ``{0, 2}``.
``sensor_plus_physics`` uses ``LinearRampLambda(0.0 -> 1e-4 over 20
steps)``. Wall-clock measured via ``time.perf_counter`` around
``train_loop`` only.

| Batch | so final\_physics | sp final\_physics | sp / so       | so data  | sp data  | so secs | sp secs | sp λ_phys (init→final) |
|------:|------------------:|------------------:|--------------:|---------:|---------:|--------:|--------:|------------------------|
| 1     | 1.593e10          | 2.319e07          | 1.456e-3      | 2378.25  | 3517.47  | 0.80    | 0.88    | 0.0 → 1e-4             |
| 4     | 6.345e10          | 6.467e05          | 1.019e-5      | 2356.54  | 3856.78  | 0.86    | 0.97    | 0.0 → 1e-4             |
| 8     | 1.268e11          | 1.671e06          | 1.318e-5      | 2348.05  | 3698.95  | 0.96    | 0.96    | 0.0 → 1e-4             |
| 16    | 2.554e11          | 9.474e05          | 3.709e-6      | 2221.78  | 3931.65  | 1.06    | 0.98    | 0.0 → 1e-4             |

Reading:

* The science gate clears its conservative ``sp < 0.1 * so`` margin
  at every batch size B ∈ {1, 4, 8, 16}; in fact the ratio improves
  with B (the batched residual term covers more windows per step, so
  physics-informed regularisation has more signal to push against).
* ``so final_physics`` scales roughly linearly with ``B`` because
  it's a *sum* over the batch axis — that is the legacy semantics and
  it does not break the gate.
* Wall-clock barely moves with ``B`` on the branch fixture (small
  network, small hidden dim) — the vectorised assembly absorbs the
  extra batch rows without leaving the BLAS-friendly path. There's
  no per-iteration regression vs ``B=1`` despite running up to 16x as
  much physics work per step.
* The Sprint 7 test asserts the gate at ``B=8``; Sprint 6's gate at
  ``B=4`` and Sprint 5's at ``B=1`` continue to pass.

## Compatibility notes

* ``assemble_residuals`` is unchanged — all Sprint 1-6 solver,
  feasibility, fixtures, and Newton tests pass bit-for-bit.
* ``physics_residual_loss(N, E)`` for unbatched inputs takes the
  legacy unbatched code path; only the rank-2 branch is rewired.
* ``TrainConfig`` is unchanged; ``train_loop`` is unchanged.
  ``train_loop_dataloader`` is additive.
* ``run_ablation`` returns the same dict shape; ``summary`` now
  carries optional ``elapsed_seconds`` and ``batch_size`` fields.
  No existing test reads those keys with a strict-dict expectation,
  so this is additive only.
* All 248 pre-Sprint-7 tests continue to pass under the new code.

## Known limitations

* ``assemble_residuals_batched`` still builds a dense incidence
  matrix per call. For the small fixtures used by training this costs
  microseconds, but a sparse representation (and incidence caching on
  the ``Network`` object) is an obvious follow-up at production
  network sizes.
* Per-edge Hazen-Williams uses ``torch.where`` on a broadcast pipe
  mask; on pump-only edges the gradient flows through the
  pipe-branch expression too. This is the same behaviour as the
  unbatched ``assemble_residuals`` (it's already what Sprint 2
  shipped), so it does not change correctness — but in principle a
  masked compute path could shave a few flops.
* ``train_loop_dataloader`` re-iterates the loader from the
  beginning when it cycles. For shuffled loaders this means each
  epoch sees a fresh permutation, which is the standard expectation;
  for deterministic experiments use ``shuffle=False`` (the default).
* ``elapsed_seconds`` is measured around ``train_loop`` only; data
  generation / fixture build / DataLoader spin-up time is not
  counted. Use it as a relative metric, not a wall-clock budget.
* PyG ``GATv2Conv`` continues to be used by default when PyG is
  installed; ``run_ablation`` keeps ``force_fallback=True`` so the
  science gate remains deterministic.

## Sprint 8 recommendation

The vectorised residual + DataLoader wiring removes the last "Python
loop over batch axis" in the hot path. Sprint 8 should pick the
**first end-to-end realistic-network experiment**: pick a single
EPANET-style fixture (still synthetic — no real PLC), use
``WNTR``-or-equivalent topology load (a single new
``Network`` constructor from a JSON or INP-style structure), and
re-run the science gate at ``B>=8`` on a network with O(50-200)
nodes. The deliverables would be:

1. ``load_network_from_inp(path)`` (or JSON) → ``Network`` —
   topology + per-edge params only, no demand sequences.
2. A larger-network physics-consistent telemetry generator (probably
   driven by ``newton_solve`` with stochastic demand multipliers) so
   the existing science gate has something realistic to chew on.
3. Re-run the Sprint 7 ablation tables on the larger network;
   verify the ``sp < 0.1 * so`` margin still holds and the
   vectorised residual stays sub-linear in wall-clock.
4. Decide between staying with the dense incidence matrix or moving
   to ``torch.sparse_csr`` based on the measured residual-assembly
   cost on the larger graph.

Explicitly out of scope for Sprint 8: write/control path, dPL, real
SCADA adapters, ONNX/TensorRT, savings claims, EPANET-execution (only
topology load).
