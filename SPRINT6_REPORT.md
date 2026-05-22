# Sprint 6 Report — PyG/GATv2Conv first-class + Batched training

Sprint 6 promoted the PyG/GATv2Conv path to the default graph encoder
and extended the model + training stack to accept batched
``[B, T, N, F]`` telemetry windows alongside the existing single-window
``[T, N, F]`` path. The Sprint 5 science gate (sensor+physics beats
sensor-only on physics residual) was re-run under the new batched code
path and continues to hold by a wide margin.

All work followed strict TDD: every behaviour change had a failing
test recorded before the implementation landed. Sprint 7+ items were
not implemented.

---

## Files changed

```
src/aquaoptima/models/graph_encoder.py       upgraded — configurable num_layers (default 3)
src/aquaoptima/models/gru_encoder.py         batched [B,T,N,F] path
src/aquaoptima/models/dphm_pinn.py           batched forward; broadcast topology embedding
src/aquaoptima/models/heads.py               batched per-head broadcasting
src/aquaoptima/models/losses.py              physics_residual_loss batched path
src/aquaoptima/training/train.py             collate_windows + TrainConfig.batch_size
src/aquaoptima/training/ablations.py         exposes batch_size to run_ablation
pyproject.toml                               adds [project.optional-dependencies].pyg
```

## Files created

```
tests/models/test_graph_encoder_pyg.py       9 tests — PyG factory, 3-layer default, edge_dim, smoke
tests/models/test_batched_dphm_pinn.py      14 tests — GRU/heads/DPHMPINN batched + parity
tests/models/test_batched_losses.py         11 tests — masked_supervised + physics + composite
tests/training/test_batch_training.py        8 tests — collate, TrainConfig, train_step/loop
tests/training/test_batched_science_gate.py  3 tests — batched science gate + B=1 parity
SPRINT6_REPORT.md                            this report
```

No existing test was modified or deleted; backward compatibility was
preserved by every new code path.

---

## Validation commands run

```bash
python -m pytest tests/models tests/training tests/dataio tests/dphm -q
#  → 240 passed, 3 warnings

python -m pytest tests -q
#  → 248 passed, 3 warnings

python -m compileall src tests
#  → no errors
```

PyG / GATv2Conv smoke command:

```bash
python - <<'PY'
import torch
from torch_geometric.nn import GATv2Conv
conv = GATv2Conv(3, 4, heads=2, edge_dim=2, concat=False)
x = torch.randn(5, 3)
edge_index = torch.tensor([[0,1,2,3],[1,2,3,4]])
edge_attr = torch.randn(4, 2)
y = conv(x, edge_index, edge_attr)
print(y.shape, torch.isfinite(y).all().item())
PY
```

Output:

```
torch.Size([5, 4]) True
```

Environment:

| Package          | Version    |
|------------------|------------|
| torch            | 2.12.0+cpu |
| torch-geometric  | 2.7.0      |

---

## Pass / fail status

| Suite                                | Tests | Status |
|--------------------------------------|------:|--------|
| tests/models                         |    65 | pass   |
| tests/training                       |    32 | pass   |
| tests/dataio                         |   ... | pass   |
| tests/dphm                           |   ... | pass   |
| tests (full)                         |   248 | pass   |
| `python -m compileall src tests`     |     – | clean  |

---

## Batched tensor shape contract

Input layouts accepted by every model component:

| Component             | Unbatched (legacy)  | Batched (Sprint 6)         |
|-----------------------|---------------------|----------------------------|
| `GRUTemporalEncoder`  | `[T, N, F] → [N,H]` | `[B, T, N, F] → [B, N, H]` |
| `PressureHead`        | `[N, H] → [N]`      | `[B, N, H] → [B, N]`       |
| `FlowHead`            | `[N, H] → [E]`      | `[B, N, H] → [B, E]`       |
| `DemandForecastHead`  | `[N, H] → [N]`      | `[B, N, H] → [B, N]`       |
| `SetpointAdvisoryHead`| `[N, H] → [K]`      | `[B, N, H] → [B, K]`       |
| `DPHMPINN.forward`    | dict of `[N]/[E]/[K]` | dict of `[B,N]/[B,E]/[B,K]` |

Loss primitives:

| Loss                       | Unbatched          | Batched                    |
|----------------------------|--------------------|----------------------------|
| `masked_supervised_loss`   | `[N], [N], [N]`    | `[B,N], [B,N], [B,N]`      |
| `physics_residual_loss`    | `[N], [E]`         | `[B,N], [B,E]` (sum over B)|
| `composite_loss`           | any matching rank  | any matching rank          |

Determinism: in `model.eval()`, a `B=1` batched forward equals the
unbatched forward elementwise to within `1e-5` on every head — proven
by `test_dphm_pinn_b1_matches_unbatched`.

---

## Batch science gate

Sprint 5 gate, re-run under the Sprint 6 batched path (branch fixture,
60 iterations, 48 steps, `LinearRampLambda(0, 1e-4, 20)` warmup):

| Mode                  | batch_size | final `loss_physics` | sp/so ratio |
|-----------------------|-----------:|---------------------:|------------:|
| sensor_only           |          1 | 1.59 × 10¹⁰          | —           |
| sensor_plus_physics   |          1 | 2.32 × 10⁷           | 1.46 × 10⁻³ |
| sensor_only           |          4 | 6.35 × 10¹⁰          | —           |
| sensor_plus_physics   |          4 | 6.47 × 10⁵           | 1.02 × 10⁻⁵ |

* Both batch sizes pass the conservative `< 0.1 × sensor_only` bar by
  multiple orders of magnitude.
* The batched path improves the *separation* (sp/so ratio): with
  `B=4` the physics-informed arm beats sensor-only by ~98 000×,
  versus ~700× at `B=1`. This is consistent with each step now
  seeing four windows of physics signal per gradient update.
* Test `test_batched_b1_recovers_unbatched_gate` confirms the new
  code path is a strict superset: a `B=1` ablation reproduces the
  Sprint 5 separation contract.

---

## PyG/GATv2Conv first-class

* `GraphEncoder(...)` factory now defaults to `PyGGraphEncoder` when
  `torch_geometric` is importable (no `force_fallback` toggle needed).
* `PyGGraphEncoder` is a configurable stack — default 3 layers — of
  `GATv2Conv` with `edge_dim=edge_in_dim`, `heads=2`, `concat=False`.
* Layer 1 maps `node_in_dim → hidden_dim`; layers 2..N operate at
  `hidden_dim`. ReLU between layers, no activation after the final
  layer (so downstream fusion sees unbounded features).
* `force_fallback=True` still selects `FallbackGraphEncoder` — used by
  the training loop and ablation harness for deterministic CPU runs
  (the `test_train_loop_batch_size_one_matches_unbatched` parity test
  depends on this).
* `pyproject.toml` adds `[project.optional-dependencies].pyg =
  ["torch-geometric>=2.7"]`. PyG is installed in this environment and
  required for the `test_graph_encoder_pyg.py` suite (the suite uses
  `pytest.importorskip("torch_geometric")` defensively so the same
  tests degrade to skips on a no-PyG installation).

---

## Compatibility notes

* Every legacy call site (Sprint 4/5 tests, the existing science gate
  in `test_physics_informed_improvement.py`, the `ablations.run_ablation`
  default invocation) keeps working with `batch_size=1` and the
  unbatched dict layout — no shape changes propagate out.
* `train_step` accepts either dict layout transparently. Detection is
  by `x_seq.dim()` — `3` is unbatched, `4` is batched.
* `composite_loss` is shape-agnostic; the sensor mask is expanded to
  match the prediction shape inside `train_step` rather than at every
  loss call site.
* `physics_residual_loss` on batched inputs returns the *sum* of
  per-batch residual norms — matching the legacy semantics under a
  `B=1` reduction and aggregating cleanly under SGD.
* The training-loop indexing uses cyclic dataset sampling
  (`i % len(dataset)`) for batches, so callers can request more
  iterations × batch_size than dataset size.

---

## Known limitations

* `physics_residual_loss` batched path is a Python loop over the
  batch axis. It is correct and differentiable, but it does not
  exploit any batched-jacobian primitives. For batch sizes up to ~8
  on the synthetic fixtures the overhead is negligible (~20s for the
  full 248-test suite). A vmap-style refactor of
  `assemble_residuals` is the obvious Sprint 7+ optimisation.
* The PyG path is exercised by all 65 model tests and an extra 9
  PyG-specific tests, but the training ablation harness still passes
  `force_fallback=True` — this is intentional (CPU-deterministic
  reproducibility) and not a soundness gap.
* Batched flow targets / flow sensor masks are wired through
  `composite_loss` but are not yet used by `train_step` (the current
  caller passes `target_flow=None`). Adding flow-supervised data is a
  Sprint 7 concern.
* No GPU / TPU testing — Sprint 6 explicitly targets CPU. PyG installs
  CPU-only torch in this environment.

---

## Sprint 7 recommendation

Use Sprint 6's batched, PyG-default stack as the launchpad and focus
Sprint 7 on **scaling the physics residual evaluation**:

1. **vmap / batched assemble_residuals.** Replace the Python loop in
   `physics_residual_loss` with a single `torch.func.vmap` or an
   explicit batched assembly. This is the only remaining serial axis
   on the gradient path and is the bottleneck once batch sizes grow
   past ~16.
2. **Multi-window batching in the science gate.** With the Python
   loop removed, raise the science gate batch size to 16+ and add an
   `optimizer_steps_per_epoch` metric so we can compare wall-clock
   convergence vs Sprint 5/6.
3. **Real PyG dataloader.** Introduce a `torch.utils.data.DataLoader`
   wrapper around `WindowDataset` with `collate_fn=collate_windows`
   so multi-process data loading becomes available. The collate
   function and `batch_size` field already exist; this is just
   wiring.

Scope guardrails that should *not* be relaxed in Sprint 7:
real PLC/PAC/SCADA adapters, EPANET/WNTR, dPL, ONNX/TensorRT, write
path. Those are still post-Sprint-7 items per the roadmap.
