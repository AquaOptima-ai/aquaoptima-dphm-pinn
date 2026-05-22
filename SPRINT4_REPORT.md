# AquaOptima dPHM-PINN — Sprint 4 Report

## Scope delivered

Sprint 4 wires the **physics-informed training loop** on top of the
Sprint 3 dPHM-PINN skeleton:

1. **Masked supervised loss** (`masked_supervised_loss`) that only
   averages MSE over observed sensor entries — virtual nodes
   contribute exactly nothing, including the corner case of an
   all-virtual mask (returns a zero scalar instead of NaN from a
   divide-by-zero).
2. **Physics residual loss** (`physics_residual_loss`) wrapping the
   Sprint 2 differentiable `assemble_residuals` so gradients flow
   through both mass-balance and energy-balance terms onto the
   predicted heads/flows tensors.
3. **Composite loss** (`composite_loss`) returns the data term, the
   physics term, and the lambda-weighted aggregate **separately** so
   the training loop can log them independently.
4. **Lambda schedulers**: `FixedLambda` and `LinearRampLambda` with a
   `make_scheduler({"kind": ...})` factory.
5. **Training loop** (`train_step` + `train_loop`) — Adam over the
   `WindowDataset` with per-iteration metrics capture.
6. **Training metrics** container (`TrainingMetrics`) with history +
   `summary()` accessors.
7. **Ablation harness** (`run_ablation`) supporting `sensor_only` and
   `sensor_plus_physics` modes that share data, model, optimizer, and
   seed — the only difference is the physics-loss weight.

Per the brief, **no dPL, no ONNX/TensorRT, no PLC/PID integration,
and no savings claims** were built in this sprint.

## Files changed / created

### Production code (`src/aquaoptima/`)
- `models/losses.py` — `masked_supervised_loss`, `physics_residual_loss`,
  `composite_loss`. Strict shape and dtype checks at the boundary.
- `models/lambda_scheduler.py` — `FixedLambda`, `LinearRampLambda`,
  abstract `LambdaScheduler`, and `make_scheduler` factory.
- `training/__init__.py` — exports `TrainConfig`, `TrainingMetrics`,
  `train_step`, `train_loop`, `run_ablation`, `ABLATION_MODES`.
- `training/metrics.py` — `TrainingMetrics` container with `record()`,
  `summary()`, and `num_iterations`.
- `training/train.py` — `train_step` (single forward / backward /
  optimizer step) and `train_loop` (N-iteration driver) with
  `TrainConfig` dataclass.
- `training/ablations.py` — `run_ablation(mode=..., ...)` that builds
  identical model + dataset across modes and only varies the lambdas.

### Tests (`tests/`)
- `tests/models/test_losses.py` — 10 tests: masked loss ignores
  virtual nodes, averages over observed only, empty mask → zero,
  gradients flow only through observed positions, physics residual
  loss finite on branch + pump fixtures, physics loss ≈ 0 on a
  converged solver state, composite returns components and obeys
  lambdas, zero-lambda physics reduces total to data, shape mismatch
  raises.
- `tests/models/test_lambda_scheduler.py` — 13 tests: fixed returns
  constant + accepts zero + rejects negative, linear ramp anchors at
  start, hits end at `ramp_steps`, halfway at midpoint, clamps after
  ramp, supports descending ramps, rejects zero `ramp_steps` and
  negative bounds, `make_scheduler` builds both kinds and rejects
  unknown.
- `tests/training/test_training_smoke.py` — 6 tests: train_step
  returns finite components, updates at least one parameter,
  produces finite gradients, multi-iteration loop stays finite,
  sensor-only mode collapses total to data, summary keys present.
- `tests/training/test_ablations.py` — 7 tests: modes constant
  present, both modes run and return metrics, `sensor_only` has
  zero physics weight (so total == data), `sensor_plus_physics`
  reports non-zero physics weight per step, unknown mode raises,
  summary records iteration count.

**New tests this sprint: 36. Total tests in repo: 154, all passing.**

## TDD evidence

Strict red → green per module. The red phase was an `ImportError`
during pytest collection before any production code existed; green
was the same pytest command after implementing only what the tests
required.

| Module                      | Red (observed)                                                          | Green (final)  |
|-----------------------------|-------------------------------------------------------------------------|----------------|
| `models.losses`             | `ModuleNotFoundError: No module named 'aquaoptima.models.losses'`       | 10 / 10        |
| `models.lambda_scheduler`   | `ModuleNotFoundError: No module named 'aquaoptima.models.lambda_scheduler'` | 13 / 13    |
| `training.train` + metrics  | `ModuleNotFoundError: No module named 'aquaoptima.training'`            | 6 / 6          |
| `training.ablations`        | `ModuleNotFoundError: No module named 'aquaoptima.training.ablations'`  | 7 / 7          |

No production code was written without a failing test first. No test
was relaxed to make a green pass.

## Commands run

```bash
# Per-module TDD loop
python -m pytest tests/models/test_losses.py -q                 # red → green (10/10)
python -m pytest tests/models/test_lambda_scheduler.py -q       # red → green (13/13)
python -m pytest tests/training/test_training_smoke.py -q       # red → green (6/6)
python -m pytest tests/training/test_ablations.py -q            # red → green (7/7)

# Final validation (per task spec)
python -m pytest tests/dphm tests/topology tests/dataio tests/models tests/training -q   # 154 passed
python -m pytest tests -q                                                                # 154 passed
```

## Pass / fail status

- `python -m pytest tests/dphm tests/topology tests/dataio tests/models tests/training -q` → **154 passed**
- `python -m pytest tests -q` → **154 passed**

No skips, no xfails, no new warnings. Sprint 1–3's 118 tests continue
to pass alongside Sprint 4's 36 new tests.

## Required behaviour — coverage map

| Required behaviour                                                          | Covered by                                                                  |
|-----------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| Supervised loss applies only on observed sensor mask                        | `test_masked_supervised_loss_ignores_virtual_nodes`, `..._gradients_flow`   |
| Physics residual loss uses dPHM `assemble_residuals` on predicted h/q       | `test_physics_residual_loss_finite_on_branch_network`, `..._pump_network`   |
| Physics loss ≈ 0 on a converged solver state                                | `test_physics_residual_loss_zero_on_consistent_state`                       |
| Loss terms returned separately, not only aggregate                          | `test_composite_loss_returns_components`                                    |
| Lambda scheduler supports fixed                                             | `test_fixed_lambda_returns_constant`, `..._accepts_zero`                    |
| Lambda scheduler supports linear ramp                                       | `test_linear_ramp_starts_at_start_value`, `..._reaches_end_value...`, `..._midpoint_is_halfway`, `..._clamps_after_end`, `..._supports_descending` |
| Training smoke runs a few iterations on synthetic data, loss finite         | `test_train_loop_runs_a_few_iterations_finite`                              |
| Training step updates at least one parameter                                | `test_train_step_updates_at_least_one_parameter`                            |
| Gradients finite (no NaN/Inf)                                               | `test_train_step_gradients_are_finite`                                      |
| Ablation harness can run `sensor_only` and `sensor_plus_physics`            | `test_sensor_only_runs_and_returns_metrics`, `..._plus_physics_runs...`     |
| Ablation modes return metrics dictionaries                                  | `test_ablation_summary_has_num_iterations`                                  |
| Training metrics logging                                                    | `TrainingMetrics.record/summary` exercised by every smoke test              |

## Known limitations

1. **No batching.** The Sprint 3 model takes a single `[T, N, F]`
   sample; training iterates one window at a time. A `[B, T, N, F]`
   path is still deferred.
2. **Predicted "pressure" is treated as hydraulic head.** Sprint 3's
   `PressureHead` outputs `[N]` and we feed that straight into
   `assemble_residuals` as `heads`. For the synthetic SCADA cycle
   around a 50 m baseline this is a defensible identity, but a real
   pressure-to-head conversion (elevation offset, unit handling) is
   not yet implemented and will matter for any real EPANET dataset.
3. **Physics loss can swamp the data loss numerically.** On randomly
   initialised model outputs the residual norm squared can be many
   orders of magnitude larger than the masked MSE on pressure. The
   smoke tests use `lambda_physics=1e-4` (and `0.0` for `sensor_only`)
   to keep gradients finite; the schedule for production training is
   a Sprint 5 problem.
4. **No early stopping / convergence assertion.** The smoke tests
   confirm finiteness, not improvement. We do not yet claim the
   physics-informed mode converges to a lower data loss than
   sensor-only on the synthetic fixture — that's an experiment
   Sprint 5 should run with calibrated synthetic SCADA.
5. **Synthetic SCADA is still not physically consistent.** Per the
   Sprint 3 limitations, `generate_synthetic_scada` does not satisfy
   Hazen-Williams. Sprint 5's `newton_solve`-driven generator is
   needed before the physics loss becomes a true supervision signal.
6. **Single fixture in the ablation harness.** `run_ablation` hard-
   codes `make_branch_network`. Generalising to all three fixtures
   (branch / single-loop / pump) is a follow-up; tests in this
   sprint cover the branch network only.
7. **Flow supervision is plumbed but unused.** `composite_loss`
   accepts `target_flow` + `flow_sensor_mask` but the training loop
   passes `None`. Wiring a real flow-sensor mask requires per-edge
   SCADA labels that the current synthetic generator does not
   distinguish from virtual edges.
8. **Float32 only.** The training loop runs in the default dtype
   (float32) but the underlying solver internally promotes to
   float64 in `newton_solve`. We only call `assemble_residuals` from
   the loss, which respects the caller's dtype, so this is fine in
   practice — but it is a latent dtype boundary worth watching.

## Sprint 5 recommendation — exact entry point

**Make the physics-informed loss measurably improve over sensor-only on
a physics-consistent synthetic dataset.** Concretely, in order:

1. **Physics-consistent synthetic SCADA.** Replace the hand-tuned
   sinusoid in `generate_synthetic_scada` with a per-step
   `newton_solve` driven by a randomised demand schedule. The
   resulting `(pressure, flow, demand)` triples will satisfy
   `assemble_residuals ≈ 0` by construction. Reuse the existing
   `ScadaSeries` dataclass and `WindowDataset` — only the generator
   internals change.
2. **Convergence assertion in CI.** Add a new test that runs
   `run_ablation("sensor_plus_physics")` for, say, 200 iterations on
   the new physics-consistent dataset and asserts that the final
   masked-MSE on virtual nodes is *lower* than the same model run
   under `sensor_only`. This locks in the value claim of the PINN
   approach and prevents regressions.
3. **Lambda warmup schedule.** Promote the smoke loop from a fixed
   `lambda_physics=1e-4` to a `LinearRampLambda(start=0.0,
   end=tuned_value, ramp_steps=...)` so the physics term ramps in
   after the data loss has stabilised the head distribution.
4. **Batchify.** Promote `x_seq` to `[B, T, N, F]` end-to-end:
   the GRU's batch dim absorbs `B * N`, the graph encoder can stay
   shared while heads broadcast over `B`, and `composite_loss` needs
   to accept a leading batch dim and reduce over it.
5. **Generalise the ablation harness.** Parametrise `run_ablation`
   by network fixture (`branch | single_loop | pump`) so the CI run
   exercises all three Sprint 2 fixtures and surfaces fixture-specific
   stability issues before they show up on real networks.

PyG installation, dPL parameter calibration, ONNX/TensorRT export, and
PLC/PID integration remain explicitly out of scope until Sprint 5's
physics-consistent training run shows a measurable benefit from the
physics loss.
