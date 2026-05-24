# Sprint Roadmap

This file is the long-form sequence of what has shipped and what is
queued. The short version: dPHM physics first, then the model and
training loop, then a clean telemetry abstraction, then physics-
consistent training, then live adapters and the safe write path.

## Shipped

### Sprint 1 — dPHM physics primitives
- Hazen-Williams head loss, pump affinity head gain, incidence matrix,
  node-level mass balance, pipe and pump energy residuals.
- Feasibility checks for pressures, pump speeds, flows.
- Autograd finite-gradient helper.

### Sprint 2 — dPHM solver
- `Network` dataclass with strict validation.
- `newton_solve` steady-state solver with dense Jacobian and structured
  `SolveResult` / `SolveFailureReason` diagnostics.
- Branch / single-loop / pump synthetic fixtures.

### Sprint 3 — Model skeleton + topology + synthetic SCADA
- `DPHMPINN` with graph encoder, per-node GRU temporal encoder,
  fusion MLP, and four task heads.
- `GraphFeatures` builder + observation/virtual masks.
- Synthetic SCADA generator + `WindowDataset` (no future leakage).

### Sprint 4 — Physics-informed training loop
- `composite_loss = masked_supervised_loss + λ * physics_residual_loss`.
- `FixedLambda` / `LinearRampLambda` schedulers.
- `train_step` / `train_loop` / `TrainingMetrics`.
- Ablation harness for `sensor_only` vs `sensor_plus_physics`.

### Sprint 4.5 — Telemetry abstraction & documentation (current)
- `TelemetrySeries` canonical container; `ScadaSeries` kept as alias.
- `generate_synthetic_telemetry`; `generate_synthetic_scada` kept as
  alias.
- `SiteTagMap` + `TagDefinition` + `SourceType` + `TagKind` for the
  PLC/PAC/SCADA/historian/MQTT/CSV adapter foundation.
- `QualityFlag` + `is_usable` vocabulary.
- New docs: `architecture.md`, `units-and-sign-conventions.md`,
  `telemetry-abstraction.md`, `testing-strategy.md`, `sprint-roadmap.md`,
  `safety-boundary.md`.
- Missing class docstrings filled in (`Network`, `SolveResult`,
  `SolveFailureReason`, `FeasibilityResult`, `DPHMPINN`,
  `GRUTemporalEncoder`).

## Next — Sprint 5: physics-consistent telemetry training

The headline goal is to make the physics-informed loss *measurably*
improve on a sensor-only baseline, on data the physics actually
satisfies.

1. **Physics-consistent synthetic generator.** Replace the Sprint 3
   sinusoid internals of `generate_synthetic_telemetry` with a
   per-step `newton_solve` over a randomised demand schedule. The
   `(pressure, flow, demand)` triples will satisfy
   `assemble_residuals ≈ 0` by construction. Keep the public signature
   — `WindowDataset` and existing tests must continue to work.
2. **Convergence assertion in CI.** Add a test that runs
   `run_ablation("sensor_plus_physics")` for ~200 iterations on the
   new generator and asserts the final virtual-node masked MSE is
   *lower* than the same model run under `sensor_only`. Locks in the
   value claim of the PINN approach.
3. **Lambda warmup.** Promote the smoke loop from `λ=1e-4` to a
   `LinearRampLambda(start=0, end=tuned, ramp_steps=...)` so the
   physics term ramps in once the data loss has stabilised.
4. **Batchify.** Promote `x_seq` to `[B, T, N, F]` end-to-end (GRU
   batch dim absorbs `B*N`; heads broadcast over `B`; losses reduce
   over `B`).
5. **Generalise the ablation harness.** Parametrise `run_ablation` by
   fixture (`branch | single_loop | pump`) so CI exercises all three.

## Future sprints (sketch)

- **Sprint 6 — Real source adapters.** First adapter (likely CSV +
  MQTT) producing real `TelemetrySeries` and consuming a `SiteTagMap`.
- **Sprint 7 — EPANET validation.** Read a real INP file, build a
  `Network`, run the solver, diff against EPANET's own steady-state
  results.
- **Sprint 8 — dPL parameter calibration.** Differentiable parameter
  learning over `c_factors`, `pump_coeffs`, etc.
- **Sprint 9 — Live read-only PLC.** Modbus or OPC-UA adapter, telemetry
  in only, no write path enabled.
- **Sprint 10 — Safety-gated write path.** Setpoint advisory commits
  back to controllers under explicit `TagDefinition.writable=True` and
  per-site policy. See `safety-boundary.md` before touching this.
- **Sprint 11 — Deployment.** ONNX / TensorRT export, dashboards,
  uptime monitoring.

Order is indicative, not contractual. If a customer engagement makes
EPANET validation higher priority than calibration, swap them. Do not
swap *anything* in front of the write-path safety boundary.

## Sprint 40 — Phase 2 3+1 architecture planning gate

Approval-gate sprint that locked in the **Edge Runtime / AI &
Optimization Server / Operations Console + Shared Contracts / SDK**
component split and the capability / safety vocabulary that every
Phase 2+ sprint must reuse. No runtime code changed. Planning
artifacts:

- [`docs/product/sprint40-3plus1-approval-gate.md`](product/sprint40-3plus1-approval-gate.md)
- [`docs/architecture/contracts-inventory.md`](architecture/contracts-inventory.md)
- [`docs/architecture/component-ownership-matrix.md`](architecture/component-ownership-matrix.md)
- [`docs/architecture/phase1-api-to-component-map.md`](architecture/phase1-api-to-component-map.md)
- [`docs/safety/capability-model-and-safety-gates.md`](safety/capability-model-and-safety-gates.md)

## Sprint 41 — Shared Contracts / SDK MVP

First implementation sprint after the Sprint 40 approval gate. Ships
the in-tree Python package `aquaoptima_contracts` (under `src/`) with:

- `SchemaVersion` SemVer triple, parse / render / same-major reader
  compatibility;
- `ContractEnvelope` frozen schema metadata wrapper with the eleven
  allowed schema families;
- `SafetyFlagSet` with the canonical seven-token list and
  unknown / forbidden / false-value rejection;
- `CapabilityDeclaration`, `CapabilityRequirement`, and the
  deny-by-default `evaluate_capability_gate` helper;
- the forbidden-vocabulary denylist plus a grep-style scan test that
  fails the build on any leak outside the canonical module;
- deterministic JSON helpers (`dump_canonical_json`,
  `load_canonical_json`, `write_canonical_json`) that match the Phase
  1 manifest writer byte-for-byte;
- a golden-fixture round-trip harness (`assert_golden_roundtrip`);
- Phase 1 fixtures copied (not moved) under
  `src/aquaoptima_contracts/fixtures/phase1_shadow/` with a byte-
  equality test against the originals;
- a representative SDK manifest snapshot covering the envelope /
  safety / capability subset only.

The SDK is stdlib-only, has no HTTP / database / message-broker
code, never imports `aquaoptima.*`, and adds no Edge / AI / Console
runtime surface. The non-negotiable boundary holds: no live OT
binding, no PLC/PAC/SCADA write, no command emission, no setpoint
output, no control-loop closure. Plan:
[`docs/product/sprint41-shared-contracts-sdk-plan.md`](product/sprint41-shared-contracts-sdk-plan.md).
