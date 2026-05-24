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

## Sprint 42 — First SDK Schema Projections

First batch of contract *shape* projections from the Phase 1 runtime
artifacts into the Shared Contracts / SDK package. Sprint 42 keeps
every Phase 1 `aquaoptima.*` import path, runtime module, and on-disk
fixture intact; it only adds SDK-side projections downstream
deployables can read without depending on the runtime.

Shipped in Sprint 42:

- Envelope / identity additions: `Checksum`, `Provenance`, extended
  `ArtifactReference` (now carries optional `checksum` and `uri`).
- Telemetry projections: `TelemetryAxis` (canonical axis vocabulary),
  `UnitSpec` (canonical unit / dimension), `TelemetryTagSpec`,
  `TelemetryTagMap`, `TelemetryTagMapDiagnostics`. Phase 1 fixture
  adapter: `project_phase1_tag_map_document`.
- Shadow replay projections: `ShadowReplayFrame`,
  `ShadowReplayDataset`, `ShadowReplayDiagnostics`. Phase 1 CSV body
  adapter: `project_phase1_replay_csv_text` (read-only audit only;
  the Phase 1 runtime keeps `load_shadow_replay_csv`).
- Manifest projections: `ShadowDeploymentArtifact`,
  `ShadowDeploymentManifest`, `ShadowDeploymentPackageDiagnostics`.
- Runtime report projections: `ShadowRuntimeStepReport`,
  `ShadowRuntimeReport`, `ShadowRuntimeDiagnostics`.

Out of scope: no advisory rule body, no calibration loss report
projection (deferred to Sprint 43 with the stretch scope), no live
OT binding, no PLC/PAC/SCADA write, no command emission, no setpoint
output, no control-loop closure, no HTTP / database / message-broker
code, no migration / removal / rename of Phase 1 import paths, no
movement of `evaluate_advisory_proposals`, `run_shadow_runtime`, or
EPANET `.inp` import into the SDK.

## Sprint 43 — Calibration / Advisory / Import Quality SDK Projections

Closes the first-batch SDK projection list named in
`docs/architecture/contracts-inventory.md`. Sprint 43 lifts the
remaining Phase 1 read-only artifacts into SDK schemas without
changing AI / Edge runtime behavior, without moving any runtime
evaluator, and without introducing any new HTTP / database /
message-broker code.

Shipped in Sprint 43:

- dPL calibration projections: `DPLResidual`,
  `CalibrationLossSummary`, `DPLCalibrationDiagnostics`,
  `DPLCalibrationLossReport`. Phase 1 duck-typed adapter:
  `project_phase1_dpl_calibration_loss_report` — projects a Phase 1
  `aquaoptima.dphm.dpl_calibration.DPLCalibrationLossReport` into the
  SDK shape without importing `aquaoptima.*` from inside SDK package
  code.
- Advisory projections (audit-only): `AdvisoryRule`,
  `AdvisoryContract`, `AdvisoryProposal`, `AdvisoryDecision`,
  `AdvisoryEvaluation`, `AdvisoryRejectionReason`, plus the canonical
  rejection vocabulary
  (`out_of_bounds`, `delta_exceeded`, `deny_rule_match`,
  `no_allow_rule_match`, `insufficient_evidence`,
  `axis_loss_exceeded`, `malformed_proposal`). Phase 1 duck-typed
  adapter: `project_phase1_advisory_decisions`.
- EPANET import-quality projections (Console-facing):
  `ImportQualitySeverity`, `TopologyReference`,
  `EpanetImportQualitySectionReport`,
  `EpanetImportQualitySurrogateReport`,
  `EpanetImportDiagnosticsRecord`, `EpanetImportQualityReport`.
  Phase 1 duck-typed adapter:
  `project_phase1_import_quality_report`.

Boundary (reaffirmed):

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no HTTP / database / message-broker code;
- no AI / Optimization Server runtime, no Edge Runtime, no
  Operations Console runtime;
- no migration / removal / rename of Phase 1 `aquaoptima.*` import
  paths;
- no movement of `evaluate_advisory_proposals`,
  `run_shadow_runtime`, or EPANET `.inp` import into the SDK.

The SDK advisory module is **audit only**. The advisory dataclasses
deliberately omit any actuation-shaped field; the decision status
vocabulary is restricted to `accepted` / `rejected`.

## Sprint 44 — Deployment Package Manifest SDK Contracts

Adds the full SDK contract *shapes* for deployment package manifests
and the model / artifact registry record named in
`docs/architecture/contracts-inventory.md`. Sprint 44 keeps the
existing Phase 1 `aquaoptima.*` import paths, runtime modules, and
on-disk fixtures intact and adds no new HTTP / database /
message-broker code paths. The SDK projection is audit / packaging
evidence only.

Shipped in Sprint 44 (under `src/aquaoptima_contracts/package/`):

- `PackageValidationDiagnostic` — deterministic warnings / errors
  tuples for package-side validation diagnostics.
- `PackageSafetyDeclaration` — mandatory `SafetyFlagSet` plus
  `CapabilityRequirement` bundle attached to every deployment
  package. Every string field is scanned for forbidden vocabulary
  tokens at construction.
- `ArtifactManifest` — per-artifact descriptor composed from
  `ArtifactReference` (with optional `Checksum` and `uri`) and
  `Provenance`. Roles are constrained to the canonical
  `PACKAGE_ARTIFACT_ROLES` vocabulary.
- `ArtifactBundleRecord` — optional grouping of related artifact
  manifests for larger packages.
- `ModelArtifactRecord` — audit-only model / artifact registry
  projection. References model artifacts only by
  `ArtifactReference` + mandatory `Checksum`; carries `Provenance`,
  the canonical `SafetyFlagSet`, and a `CapabilityRequirement`. No
  inline weights, no filesystem writes outside tests, no runtime
  loading of model artifacts.
- `DeploymentPackageManifest` — top-level audit-evidence manifest.
  Composes `ContractEnvelope` (schema family `manifest`),
  `PackageSafetyDeclaration`, `CapabilityRequirement`, `Provenance`,
  and tuples of `ArtifactManifest` / `ModelArtifactRecord` /
  `ArtifactBundleRecord` plus a `PackageValidationDiagnostic`.
  `package_id` consistency across the declaration / requirement /
  manifest is enforced; setpoint-shaped field names are rejected in
  `from_dict`.
- `build_deployment_package_manifest_from_shadow` — pure-SDK builder
  that lifts a Sprint 42 `ShadowDeploymentManifest` into the Sprint
  44 `DeploymentPackageManifest` shape without importing any
  `aquaoptima.*` runtime module.

Boundary (reaffirmed):

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no HTTP / database / message-broker code;
- no AI / Optimization Server runtime, no Edge Runtime, no
  Operations Console runtime;
- no migration / removal / rename of Phase 1 `aquaoptima.*` import
  paths;
- no movement of `evaluate_advisory_proposals`,
  `run_shadow_runtime`, or EPANET `.inp` import into the SDK;
- no inline model weights, no filesystem writes outside tests, no
  runtime loading of model artifacts.

## Sprint 45+ — AMAX-5580 primary Edge target plan

The primary Edge hardware target for Sprint 45+ is now the
**Advantech AMAX-5580** class of PAC / industrial controller, not an
NVIDIA Jetson / Orin-first EPC-R profile. The Edge package should be
planned as an OT-side, CPU-first, x86_64 industrial runtime that can
coexist with site PLCs and pump-station PLCs. The site PLC remains the
direct VFD / pump / actuator authority; AquaOptima Edge remains a
supervisory validation, inference, audit, and eventually bounded
setpoint-proposal layer after explicit safety approval.

This target change does not require a rewrite of the current codebase:
the current implementation is platform-neutral Python / PyTorch and
Shared Contracts / SDK code. Jetson / TensorRT should be treated as an
optional accelerator variant only, not the default deployment path.

Hardware / runtime assumptions for Sprint 45+:

- primary target: AMAX-5580 or equivalent PAC-class industrial
  controller;
- architecture: x86_64;
- acceleration: CPU-first PyTorch inference, with optional ONNX
  Runtime CPU or OpenVINO later if benchmarking justifies it;
- PAC / OT integration posture: CODESYS / industrial-protocol capable
  controller coexisting with existing site PLCs;
- no CUDA / TensorRT / Jetson / Orin requirement in the default Edge
  package;
- TensorRT artifacts may remain valid manifest vocabulary for an
  optional Orin accelerator profile, but AMAX validation must reject
  packages that require unavailable GPU acceleration.

Sprint 45 should therefore be reframed as:

**Sprint 45 — AMAX-5580 Edge Package Validator / Capability Profile**

Expected scope:

- `EdgeHardwareProfile` / `EdgeCapabilityDeclaration` for
  `advantech-amax-5580` or a generic `x86_64-pac-cpu` profile;
- `EdgePackageValidationResult` consuming Sprint 44
  `DeploymentPackageManifest`;
- checks that reject default-edge packages requiring CUDA, TensorRT,
  Jetson, Orin, ARM64, inline model weights, runtime model loading, or
  write/control capabilities;
- checks that accept CPU-first PyTorch artifacts and future
  ONNX-Runtime-CPU/OpenVINO-compatible metadata;
- deterministic diagnostics for architecture, OS/runtime,
  Python/PyTorch compatibility, safety declaration, capability gates,
  provenance signer identity, and AMAX/PAC profile compatibility;
- docs that state AMAX Edge is an OT-side supervisory controller while
  the site PLC / pump-station PLC remains final actuator authority.

Suggested Sprint 46+ sequence after Sprint 45 passes:

1. **Sprint 46 — AMAX CPU inference smoke profile.** Add benchmark /
   evidence contracts for dPHM-PINN CPU inference latency, memory
   envelope, thread policy, and package manifest compatibility. This
   is still offline/mock execution, not live OT integration.
2. **Sprint 47 — AMAX read-only PLC/SCADA adapter contract.** Define
   read-only OPC UA / Modbus / CODESYS-facing adapter contracts and
   replay fixtures. No write path, no commands, no setpoints.
3. **Sprint 48 — AMAX supervised-control dry-run contract.** Define
   dry-run handoff records, PLC gatekeeper expectations, fallback
   evidence, and operator-enable requirements. This remains simulated
   unless a later safety gate explicitly approves supervised writes.

Boundary for all Sprint 45+ AMAX work:

- no live OT binding by default;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop;
- no assumption that AMAX certification alone certifies the full
  deployed AquaOptima control system.
