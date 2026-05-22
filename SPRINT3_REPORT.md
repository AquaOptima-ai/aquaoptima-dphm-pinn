# AquaOptima dPHM-PINN — Sprint 3 Report

## Scope delivered

Sprint 3 adds the **graph / data foundations and the dPHM-PINN model
skeleton** on top of the Sprint 2 differentiable hydraulic model:

1. **Topology module** that projects a dPHM `Network` onto ML-ready
   tensors (`x_node`, `edge_index`, `edge_attr`, `sensor_mask`).
2. **Sensor-mask helpers** that distinguish observed (SCADA) nodes from
   virtual nodes the model must predict.
3. **Synthetic SCADA generator** that produces deterministic, seeded,
   shape-correct pressure / flow / demand series for any fixture
   network.
4. **Sliding 32-step `WindowDataset`** with strict no-future-leakage
   indexing.
5. **dPHM-PINN model skeleton** consisting of a graph encoder, a
   per-node GRU temporal encoder, and four output heads (pressure,
   flow, demand forecast, setpoint advisory).
6. **PyG / fallback parity** — the graph encoder works on PyG when
   available and on a plain-PyTorch message-passing fallback otherwise.

Per the brief, **no physics training loop, no dPL, no ONNX/TensorRT,
and no PLC/PID integration** was built in this sprint.

## Files created

### Production code (`src/aquaoptima/`)
- `topology/__init__.py` — exports `GraphFeatures`,
  `build_graph_features`, `sensor_mask_from_indices`,
  `virtual_node_mask`, and the fixed feature-dim constants.
- `topology/graph_builder.py` — `GraphFeatures` dataclass and
  `build_graph_features(network, sensor_mask=None)`. Node features:
  `[demand, fixed_head_flag, fixed_head_value]` (3 columns). Edge
  features: `[length, diameter, c_factor, pump_flag, pump_a0, pump_a1,
  pump_a2, pump_speed]` (8 columns, non-pipe / non-pump entries zeroed
  by mask).
- `topology/masks.py` — `sensor_mask_from_indices(num_nodes, observed)`
  and `virtual_node_mask(sensor_mask)`. Strict bounds checking.
- `dataio/__init__.py` — exports `ScadaSeries`,
  `generate_synthetic_scada`, `WindowDataset`.
- `dataio/synthetic_scada.py` — deterministic seeded generator. Per-node
  demand is a sinusoidal cycle around the nominal demand with low-amp
  noise. Pressure is a damped mirror around a 50 m baseline with fixed-
  head nodes pinned. Flow is a 0.05 m³/s baseline with a daily cycle.
- `dataio/window_dataset.py` — `WindowDataset(series, window=32)`. Item
  layout: `x_seq[T, N, 2]` (demand, pressure), plus `target_pressure`,
  `target_flow`, `target_demand` from step `idx + window`. Index range
  enforced so the target is always strictly outside the window.
- `models/__init__.py` — exports the full model surface.
- `models/graph_encoder.py` — `FallbackGraphEncoder` (always available)
  and `PyGGraphEncoder` (two-layer `GATv2Conv` stack, used only when
  `torch_geometric` is importable). `GraphEncoder(...)` is a factory
  that selects the right one and accepts `force_fallback=True`.
- `models/gru_encoder.py` — `GRUTemporalEncoder` that maps
  `x_seq[T, N, F] -> [N, hidden]` using the GRU's final hidden state,
  treating nodes as the batch dimension.
- `models/heads.py` — `PressureHead`, `FlowHead`, `DemandForecastHead`,
  `SetpointAdvisoryHead`. Output shapes match the Sprint 3 tensor
  contract.
- `models/dphm_pinn.py` — `DPHMPINN` module. Forward path:
  graph_encoder → temporal_encoder → fusion MLP → 4 heads. Returns
  `{pressure[N], flow[E], demand_forecast[N], setpoint_advisory[k]}`.

### Tests (`tests/`)
- `tests/topology/test_graph_builder.py` — 8 tests: shape contracts on
  branch / single-loop / pump fixtures, edge-index passthrough, node
  features encode demand + fixed-head flag, pump-flag column behaves
  on pump edges, sensor / virtual masks, mask-bounds rejection.
- `tests/dataio/test_window_dataset.py` — 10 tests: SCADA shape +
  seedability + reproducibility + finite values + too-short-rejection,
  window length excludes target, item shapes, no-future-leakage,
  out-of-range raises, window=0 rejection.
- `tests/models/test_dphm_pinn.py` — 8 tests: graph-encoder forward on
  branch, fallback works without PyG, GRU encoder shape, full forward
  on branch / single-loop / pump fixtures, backward produces finite
  gradients, `force_fallback=True` constructs the fallback encoder
  explicitly.

**New tests this sprint: 26. Total tests in repo: 118, all passing.**

## TDD evidence summary

Each module went through a strict red → green cycle. The red phase was
observed as an `ImportError` from pytest collection (e.g.
`cannot import name 'GraphFeatures' from 'aquaoptima.topology'`) before
any production code existed; the green phase ran the same pytest
command after implementing only the minimum code needed to satisfy the
tests.

| Module             | Red (observed)                                                                | Green (final)  |
|--------------------|-------------------------------------------------------------------------------|----------------|
| topology           | `ImportError: cannot import name 'GraphFeatures' from 'aquaoptima.topology'`  | 8 / 8          |
| dataio             | `ImportError: cannot import name 'ScadaSeries' from 'aquaoptima.dataio'`      | 10 / 10        |
| models             | `ImportError: cannot import name 'DPHMPINN' from 'aquaoptima.models'`         | 8 / 8          |

One mid-cycle adjustment was made to `generate_synthetic_scada`: the
initial implementation required `num_steps >= window + 1`, but the
seeded-reproducibility tests construct `num_steps=32` with the default
`window=32`. The check was loosened to `num_steps >= window`, which
still rejects the explicit too-short case (`num_steps=10, window=32`)
that has its own test. No test was relaxed.

## Commands run

```bash
# Strict TDD loop per module
python -m pytest tests/topology -q          # red, then green (8/8)
python -m pytest tests/dataio -q            # red, then green (10/10)
python -m pytest tests/models -q            # red, then green (8/8)

# Final validation (per task spec)
python -m pytest tests/dphm tests/topology tests/dataio tests/models -q  # 118 passed
python -m pytest tests -q                                                # 118 passed
```

## Pass / fail status

- `python -m pytest tests/dphm tests/topology tests/dataio tests/models -q` → **118 passed**
- `python -m pytest tests -q` → **118 passed**

No skips, no xfails, no new warnings. Sprint 1 + Sprint 2's 92 tests
continue to pass alongside Sprint 3's 26 new tests.

## Tensor contract honoured

| Tensor                    | Shape                          | Producer                          |
|---------------------------|--------------------------------|-----------------------------------|
| `x_seq`                   | `[T=32, N, F_seq=2]`           | `WindowDataset.__getitem__`       |
| `edge_index`              | `[2, E]`                       | `build_graph_features`            |
| `edge_attr`               | `[E, F_edge=8]`                | `build_graph_features`            |
| `sensor_mask`             | `[N]` (bool)                   | `sensor_mask_from_indices`        |
| `pressure`                | `[N]`                          | `DPHMPINN.forward["pressure"]`    |
| `flow`                    | `[E]`                          | `DPHMPINN.forward["flow"]`        |
| `demand_forecast`         | `[N]`                          | `DPHMPINN.forward["demand_forecast"]` |
| `setpoint_advisory`       | `[num_setpoint_outputs]`       | `DPHMPINN.forward["setpoint_advisory"]` |

## Known limitations

1. **No batch dimension.** `DPHMPINN.forward(x_seq, features)` expects
   `x_seq` of shape `[T, N, F]` and processes a single sample at a time.
   The tensor contract explicitly allowed MVP without batching; a
   `[B, T, N, F]` path needs reshape gymnastics through the GRU and
   the graph encoder, and is deferred to Sprint 4.
2. **GAT path is untested in CI.** `PyGGraphEncoder` is constructed and
   exercised only when `torch_geometric` imports successfully. The
   current environment has no PyG, so the PyG branch is marked
   `pragma: no cover`. The fallback path is fully covered.
3. **Fallback encoder is one message-passing layer.** It is a
   correctness-first reference implementation — mean-aggregated
   incoming messages followed by an MLP update. It is not a GATv2
   replacement; attention, multiple layers, and residual connections
   are deferred until Sprint 4 needs measurable predictive performance.
4. **Synthetic SCADA is not physically calibrated.** Demand cycles
   around the nominal demand vector and pressure is a hand-tuned mirror
   — values are shape-correct and seedable but do not satisfy
   Hazen-Williams or any other physical law. Sprint 4 should replace
   this with a `newton_solve`-driven generator that produces
   physics-consistent synthetic series.
5. **`WindowDataset` does not iterate batches itself.** It is a plain
   `torch.utils.data.Dataset`; batching is the consumer's job (via a
   `DataLoader`) and was out of Sprint 3 scope.
6. **Setpoint advisory head uses mean pooling.** This is the simplest
   permutation-invariant graph readout. Attention pooling or
   per-actuator nodes will be needed once real PLC / PID integration
   lands.
7. **Sensor mask is structural, not used in training.** The mask is
   propagated through `GraphFeatures` but no module currently consumes
   it (no supervised data loss yet). It will gate the data loss in
   Sprint 4.
8. **Float dtype.** All Sprint 3 code runs at the global default dtype
   (float32). The dPHM solver from Sprint 2 internally promotes to
   float64; bridging the two will need an explicit downcast on the
   solver output once the physics loss is added.

## Sprint 4 recommendation — exact entry point

**Wire the dPHM solver in as a differentiable physics layer and turn
the skeleton into a trainable PINN.** Concretely, in order:

1. **Hook the dPHM solver into the model.** Add a
   `PhysicsResidualLayer` that takes `DPHMPINN.forward`'s `pressure`
   and `flow` and feeds them into `aquaoptima.dphm.assemble_residuals`
   together with `Network` parameters. The output is the residual
   vector; gradients already flow through `assemble_residuals`. No
   new physics code is needed.
2. **Define the composite loss.** Combine:
   - data loss on `sensor_mask` for pressure (and flow where SCADA
     covers it),
   - residual loss = `‖assemble_residuals(...)‖²`,
   - forecast loss against `target_demand` from `WindowDataset`,
   - boundary loss anchoring `pressure[fixed_head_mask]` to
     `fixed_head_values`.
   Make each term weight a configurable hyperparameter.
3. **Add a minimal training loop.** PyTorch + `DataLoader` over
   `WindowDataset`, Adam optimiser, log per-component loss. Five-epoch
   smoke test on `make_branch_network()` is enough to prove the
   gradient path; convergence quality is a Sprint 5 concern.
4. **Batchify the model.** Promote `x_seq` to `[B, T, N, F]` and adapt
   the GRU / graph encoder / heads. The graph encoder can either be
   replicated per-batch or stay shared if topology is constant. Add a
   `[B, ...]` path through the heads and update tests.
5. **Physics-consistent synthetic SCADA.** Replace the hand-tuned
   sinusoid in `generate_synthetic_scada` with a per-step
   `newton_solve` call driven by a randomised demand schedule. The
   resulting pressure / flow tensors will satisfy `assemble_residuals
   ≈ 0` by construction — the cleanest possible supervision signal
   for the new physics loss.

PyG installation, dPL parameter calibration, ONNX/TensorRT export, and
PLC/PID integration remain explicitly out of scope until the Sprint 4
training loop converges on at least one fixture.
