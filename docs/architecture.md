# AquaOptima dPHM-PINN — Architecture

This document is the system-level map of the code base through Sprint
4.5. Use it as the first stop when you (or a future agent) need to
locate "where does X live?" or "what depends on what?".

## Module map

```
aquaoptima/
├── dphm/             # Differentiable physics core (Sprint 1–2)
│   ├── network.py            # `Network` topology + parameter dataclass
│   ├── hazen_williams.py     # signed, differentiable pipe head loss
│   ├── pump_affinity.py      # pump head-gain curve
│   ├── incidence.py          # node ↔ edge incidence matrix
│   ├── residuals.py          # mass + energy residual helpers
│   ├── solver.py             # `newton_solve` steady-state solver
│   ├── diagnostics.py        # `SolveResult`, `SolveFailureReason`
│   ├── feasibility.py        # bound checks → `FeasibilityResult`
│   ├── fixtures.py           # branch / single-loop / pump fixtures
│   └── autograd_checks.py    # `assert_finite_gradients` helper
├── topology/         # Graph features for the GNN (Sprint 3)
│   ├── graph_builder.py      # `GraphFeatures` builder
│   └── masks.py              # observation / virtual node masks
├── dataio/           # Telemetry abstraction (Sprint 3–4.5)
│   ├── telemetry.py          # `TelemetrySeries` + synthetic generator
│   ├── synthetic_scada.py    # legacy re-export, kept for back-compat
│   ├── window_dataset.py     # sliding-window torch.Dataset
│   ├── tag_map.py            # `SiteTagMap`, `TagDefinition`, `SourceType`, `TagKind`
│   └── quality.py            # `QualityFlag`, `is_usable`
├── models/           # dPHM-PINN model (Sprint 3)
│   ├── dphm_pinn.py          # `DPHMPINN` top-level module
│   ├── graph_encoder.py      # PyG encoder + pure-PyTorch fallback
│   ├── gru_encoder.py        # `GRUTemporalEncoder`
│   ├── heads.py              # pressure / flow / demand / setpoint heads
│   ├── losses.py             # masked supervised + physics residual losses
│   └── lambda_scheduler.py   # `FixedLambda`, `LinearRampLambda`
└── training/         # Training loop & ablation harness (Sprint 4)
    ├── train.py              # `train_step`, `train_loop`, `TrainConfig`
    ├── metrics.py            # `TrainingMetrics`
    └── ablations.py          # `run_ablation`
```

## Data flow at a glance

1. **Topology in** — a :class:`aquaoptima.dphm.Network` describes the
   physical pipe network. Strict validation at construction; all
   downstream code assumes invariants.
2. **Telemetry in** — a :class:`aquaoptima.dataio.TelemetrySeries`
   carries time-aligned pressure, flow, demand (and optional quality
   flags). Source: synthetic today, PLC/PAC/SCADA/historian/MQTT/CSV
   in later sprints (see `telemetry-abstraction.md`).
3. **Window dataset** — `WindowDataset` produces 32-step training
   samples with strict no-future-leakage guarantees.
4. **Model** — `DPHMPINN` fuses graph + temporal encodings and emits
   per-node pressure, per-edge flow, per-node demand forecast, and a
   per-node setpoint advisory.
5. **Loss** — `composite_loss` combines a masked MSE on observed
   sensors with a physics residual computed via the differentiable
   `assemble_residuals` from the dPHM core.
6. **Training** — `train_loop` drives the above and records metrics;
   `run_ablation` exercises the sensor-only vs. sensor+physics
   comparison.

## Boundaries that are deliberately not crossed yet

- **No real PLC/PAC client.** Only `SiteTagMap` metadata exists; the
  adapter implementations (Modbus, OPC-UA, MQTT, historian REST,
  CSV) are scheduled for later sprints.
- **No write path.** `TagDefinition.writable` defaults to `False` and
  there is no code today that writes a command back to a controller.
- **No EPANET validation.** Solver fixtures are synthetic.
- **No dPL / ONNX / TensorRT.** Pure-PyTorch end to end.
- **No batch dimension on the model.** Training iterates one window
  at a time; promotion to `[B, T, N, F]` is a Sprint 5 task.

See `sprint-roadmap.md` for the sequencing of all the above.
