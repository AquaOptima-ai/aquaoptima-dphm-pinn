# AquaOptima dPHM-PINN

Differentiable Pressurised Hydraulic Model (dPHM) PINN primitives for
pressurised clean-water pipe networks.

The repository is the AquaOptima physics-informed-neural-network stack,
built sprint-by-sprint via strict TDD. As of Sprint 4.5 the codebase
contains the physics core, the model skeleton, the physics-informed
training loop, and a generalised telemetry abstraction that treats
SCADA as one possible source alongside PLC, PAC, historian, MQTT, and
CSV.

## Module map (through Sprint 4.5)

```
src/aquaoptima/
├── dphm/         # Differentiable physics core
│                 # (Hazen-Williams, pump affinity, incidence,
│                 #  residuals, Newton solver, diagnostics,
│                 #  feasibility, fixtures, autograd checks)
├── topology/     # Graph feature builder (GraphFeatures, masks)
├── dataio/       # Telemetry container, sliding-window dataset,
│                 # tag-map / quality flags for source adapters
├── models/       # Graph encoder, GRU encoder, fusion, heads,
│                 # losses (masked supervised + physics residual),
│                 # lambda schedulers
└── training/     # train_step, train_loop, TrainingMetrics,
                  # run_ablation
```

Detailed map: see [`docs/architecture.md`](docs/architecture.md).

## Status

- **Tests:** 183 tests, all passing (Sprint 4 had 154; Sprint 4.5
  adds 29 new dataio tests covering telemetry aliases, tag map, and
  quality flags).
- **Coverage:** physics primitives, network dataclass, Newton solver,
  diagnostics, feasibility, graph features, telemetry abstraction,
  model forward pass, loss components, lambda schedulers, training
  smoke loops, ablation harness.
- **What is wired end-to-end today:** synthetic telemetry →
  `WindowDataset` → `DPHMPINN` → `composite_loss` → `train_loop` /
  `run_ablation`.

## Source-adapter strategy

`TelemetrySeries` is the canonical model input. Any of the following
sources may produce one:

| Source       | Status (Sprint 4.5)                          |
|--------------|----------------------------------------------|
| Synthetic    | Wired (sinusoidal; physics-consistent in S5) |
| CSV          | Metadata only — adapter pending              |
| PLC          | Metadata only — adapter pending              |
| PAC          | Metadata only — adapter pending              |
| SCADA        | Metadata only — adapter pending              |
| Historian    | Metadata only — adapter pending              |
| MQTT         | Metadata only — adapter pending              |

The shared metadata vocabulary is `SiteTagMap` + `TagDefinition` +
`SourceType` + `TagKind` (in `aquaoptima.dataio`). See
[`docs/telemetry-abstraction.md`](docs/telemetry-abstraction.md).

## Unit & sign conventions

| Quantity        | Unit       |
|-----------------|------------|
| Flow `Q`        | m³/s       |
| Head / pressure | metres WC  |
| Length, diameter| metres     |

Positive flow follows the directed edge orientation
`source → target`. Demands: positive = consumer, negative = supplier.
Full details: [`docs/units-and-sign-conventions.md`](docs/units-and-sign-conventions.md).

## Limitations (Sprint 4.5)

- **No live PLC / PAC client.** Only the metadata layer
  (`SiteTagMap`, `TagDefinition`) exists.
- **No write path.** `TagDefinition.writable` defaults to `False`;
  there is no code path that writes commands to a controller. See
  [`docs/safety-boundary.md`](docs/safety-boundary.md).
- **No EPANET validation yet.** Solver fixtures are synthetic
  (branch / single-loop / pump).
- **No dPL parameter calibration.**
- **No ONNX / TensorRT export.**
- **No batch dimension** on the model — training iterates one window
  at a time.
- **Synthetic telemetry is not physics-consistent.** Sprint 5 will
  replace the generator internals with a `newton_solve`-driven
  series; the public signature stays the same.

## Install

```bash
pip install -e .[dev]
```

If `torch` cannot be resolved from PyPI directly, install a CPU build:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

## Test

```bash
python -m pytest tests/dataio -q                 # dataio subset
python -m pytest tests/dphm -q                   # physics core subset
python -m pytest tests -q                        # whole suite
python -m compileall src tests                   # bytecode sanity
```

## Next — Sprint 5

**Physics-consistent telemetry training.** Replace the synthetic
generator internals with a per-step `newton_solve`-driven series,
add a convergence-assertion CI test that proves
`sensor_plus_physics` beats `sensor_only` on the new dataset, ramp
the physics lambda, batchify, generalise the ablation harness
across fixtures. See [`docs/sprint-roadmap.md`](docs/sprint-roadmap.md).

## Shared Contracts / SDK (Sprint 41 MVP)

The Sprint 41 Shared Contracts / SDK package ships under
`src/aquaoptima_contracts/` and exposes the cross-component vocabulary
every Phase 2+ deployable depends on:

- `SchemaVersion` SemVer triple + same-major reader compatibility;
- `ContractEnvelope` schema metadata wrapper used by every contract;
- `SafetyFlagSet` with the seven canonical Sprint 41 flag tokens;
- `CapabilityDeclaration` / `CapabilityRequirement` + the deny-by-
  default `evaluate_capability_gate` helper;
- the forbidden-vocabulary denylist enforced by a grep-style scan;
- deterministic JSON helpers (`dump_canonical_json`,
  `load_canonical_json`, `write_canonical_json`) that match the Phase
  1 manifest writer byte-for-byte;
- a golden-fixture harness (`assert_golden_roundtrip`).

The SDK is stdlib-only at runtime and never imports any
`aquaoptima.*` deployable module. It does not introduce live OT
binding, PLC/PAC/SCADA write, command emission, setpoint output,
control-loop closure, HTTP, database, or message-broker code paths.

Planning references:

- [`docs/product/sprint40-3plus1-approval-gate.md`](docs/product/sprint40-3plus1-approval-gate.md)
- [`docs/product/sprint41-shared-contracts-sdk-plan.md`](docs/product/sprint41-shared-contracts-sdk-plan.md)
- [`docs/architecture/contracts-inventory.md`](docs/architecture/contracts-inventory.md)
- [`docs/safety/capability-model-and-safety-gates.md`](docs/safety/capability-model-and-safety-gates.md)

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — module map and data flow
- [`docs/telemetry-abstraction.md`](docs/telemetry-abstraction.md) — adapter strategy
- [`docs/units-and-sign-conventions.md`](docs/units-and-sign-conventions.md) — unit policy
- [`docs/testing-strategy.md`](docs/testing-strategy.md) — how we test
- [`docs/sprint-roadmap.md`](docs/sprint-roadmap.md) — what shipped, what is next
- [`docs/safety-boundary.md`](docs/safety-boundary.md) — read vs. write policy
