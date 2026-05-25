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

## Sprint 45 — AMAX-5580 Edge Package Validator / Capability Profile

Promotes the **Advantech AMAX-5580** (or equivalent x86_64 PAC-class
industrial controller) to the primary Edge target and ships the
deny-by-default SDK Edge package validator that consumes a Sprint 44
`DeploymentPackageManifest`. The Jetson / Orin / TensorRT path stays
as an optional accelerator profile only — it is not the default Edge
deployment path. Sprint 45 does not introduce Edge Runtime daemon
code, model loading, live OT integration, or any new HTTP / database /
message-broker dependency. The validator is a pure value function
over Sprint 41–44 SDK contract shapes.

Shipped in Sprint 45 (under `src/aquaoptima_contracts/edge/`):

- `EdgeHardwareProfile` — frozen hardware / runtime capability
  metadata (`profile_id`, `vendor`, `model`, `architecture`,
  `os_family`, `runtime_class`, `accelerators`,
  `supported_model_frameworks`, `python_versions`, audit-only
  `notes`). The canonical `amax_5580_cpu_profile()` helper returns
  the x86_64 / Linux / `industrial_pac` profile with CPU-first
  framework support (`audit_only`, `onnx`, `pytorch`, `tflite`) and
  no CUDA / TensorRT / Jetson / Orin acceleration.
- `EDGE_RUNTIME_CLASSES` (`industrial_pac` / `edge_x86_generic` /
  `edge_gpu_optional`) and the `EDGE_REJECTED_ACCELERATOR_TOKENS`
  denylist (`aarch64`, `arm64`, `cuda`, `jetson`, `orin`,
  `tensorrt`) the AMAX default validator refuses by default.
- `EdgeCapabilityDeclaration` — pairs a Sprint 41
  `CapabilityDeclaration` with an `EdgeHardwareProfile`. Ships
  `default_amax_edge_capability_declaration()` for the canonical
  package-validation-only declaration
  (`load_signed_or_hashed_package`, `validate_manifest`,
  `validate_checksums`, `validate_schema_versions`,
  `validate_safety_flags`, `validate_tag_map`) plus audit-only notes
  recording the non-negotiable safety boundary.
- `EdgePackageValidationResult` — deterministic
  `accepted` / `errors` / `warnings` bundle with optional
  `profile_id`, `package_id`, `missing_capabilities`,
  `rejected_accelerator_tokens`, and `rejected_frameworks` evidence.
- `validate_deployment_package_for_edge(manifest, edge)` — pure
  value function. Deny-by-default checks: capability gate
  (manifest- and model-artifact-level requirements merged together);
  AMAX accelerator-token denylist scan over notes, descriptions, and
  summaries; model framework compatibility against the profile's
  `supported_model_frameworks`; per-artifact architecture summary
  sanity. Accelerator-aware profiles can opt-in to specific
  accelerators by adding them to `EdgeHardwareProfile.accelerators`,
  which downgrades the corresponding denylist hits from errors to
  warnings.

The non-negotiable boundary stays explicit:

- AMAX-5580 is the primary Edge target; Orin / TensorRT is an
  optional accelerator profile only;
- the site PLC / pump-station PLC remains the direct VFD / pump /
  actuator authority;
- no live OT binding by default;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop;
- no HTTP / database / message-broker code, no Edge Runtime daemon
  / service implementation, no AI / Optimization Server runtime,
  no Operations Console runtime;
- no CUDA / TensorRT runtime dependency, no model loading, no
  inline model weights;
- no Phase 1 `aquaoptima.*` import path removals or renames;
- no movement of `evaluate_advisory_proposals`,
  `run_shadow_runtime`, EPANET `.inp` import, or `Network` into the
  SDK.

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

Suggested Sprint 46+ sequence after Sprint 45 passes (corrected by
the Sprint 46 evidence gate — see the Sprint 46 section below):

1. **Sprint 46 — AMAX feasibility evidence / SKU & OS decision gate.**
   Evidence and decision-gate sprint, **not** a benchmark sprint. Turns
   AMAX-5580 datasheet facts and the Sprint 45 SDK assumptions into a
   feasibility note and SDK evidence projection
   (`AMAXSkuProfile`, `AMAXRuntimeOption`, `AMAXFeasibilityDecision`)
   so the product owner can pin a SKU / OS / runtime path before
   deeper Edge implementation begins. No live OT integration, no
   Edge Runtime daemon code.
2. **Sprint 47 — AMAX CPU inference benchmark / packaging smoke
   harness** (*after Sprint 46 evidence is accepted*). Measure
   dPHM-PINN CPU inference latency, memory envelope, thread policy,
   and packaging manifest compatibility on a real AMAX-5580 (or
   representative i5-6300U / i7-6600U / 8 GB surrogate). Still
   offline / mock OT execution, not live OT integration.
3. **Sprint 48 — AMAX read-only PLC/SCADA adapter contract.** Define
   read-only OPC UA / Modbus / CODESYS-facing adapter contracts and
   replay fixtures. No write path, no commands, no setpoints.
4. **Sprint 49 — AMAX supervised-control dry-run contract.** Define
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

## Sprint 46 — AMAX Feasibility Evidence / SKU & OS Decision Gate

Sprint 46 is an evidence and decision-gate sprint, **not** an
implementation-heavy Edge Runtime sprint and **not** the CPU
inference smoke profile that the older Sprint 45+ sequence text once
described. It turns Advantech AMAX-5580 datasheet facts and the
Sprint 45 SDK assumptions into a feasibility note and SDK evidence
projection so the product owner can pin a SKU / OS / runtime path
before deeper Edge implementation begins.

Shipped in Sprint 46:

- `docs/hardware/amax-5580-feasibility.md` — feasibility evidence
  document with executive decision summary, AMAX-5580 SKU comparison
  (Celeron 3955U / 4 GB constrained fallback vs Core i5-6300U / 8 GB
  serious candidate vs Core i7-6600U / 8 GB recommended candidate),
  OS / CODESYS decision matrix (AdvLinuxTU + CODESYS Linux Control
  V3 SP20 vs Windows 10 LTSC 2019 + CODESYS Control RTE V3.5 SP20),
  runtime / package strategy decision matrix (direct PyTorch CPU,
  container sidecar, service sidecar outside CODESYS runtime, ONNX
  Runtime CPU, OpenVINO), CODESYS / PLC integration option matrix
  (OPC UA, Modbus TCP / RTU, CODESYS PLC Handler / shared memory,
  MQTT / Sparkplug — all read-only / audit-only), OT hardware facts
  to carry forward (2 x GbE / 4 x USB 3.0 / 2 x RS-232/422/485,
  dual 24 VDC input with alarm output, AMAX-5000 EtherCAT Slice I/O,
  AMAX-5400 PCIe expansion, retain / persistence memory, -10 to
  60 °C, CE / FCC / CB / UL62368 plus shock / vibration), and the
  recommendation / acceptance gate for Sprint 47.
- SDK projection under `src/aquaoptima_contracts/edge/feasibility.py`:
  - `AMAXSkuProfile` — frozen Advantech AMAX-5580 SKU evidence
    record with deterministic `to_dict` / `from_dict`. Canonical
    helper `canonical_amax_sku_profiles()` enumerates the three
    in-scope SKU records and their recommendation tiers.
  - `AMAXRuntimeOption` — frozen OS / CODESYS runtime / Python
    packaging risk / ML runtime / integration evidence record with
    deterministic `to_dict` / `from_dict`. Canonical helper
    `canonical_amax_runtime_options()` enumerates the Linux +
    CODESYS Linux Control, Windows + CODESYS RTE, and Linux
    container sidecar options.
  - `AMAXFeasibilityDecision` — frozen Sprint 46 recommendation
    record carrying recommended SKU profile id, OS / runtime
    recommendation, packaging strategy, ML runtime recommendation,
    surrogate-evidence-gap tuple, and the next gate. Canonical
    helper `default_amax_feasibility_decision()` recommends the
    `advantech-amax-5580-i5-or-i7-8gb-linux-codesys-cpu-first`
    profile.
  - `recommended_amax_hardware_profile()` — bridge that returns an
    `EdgeHardwareProfile` matching the Sprint 45
    `amax_5580_cpu_profile()` identifier and enriches `notes` with
    Sprint 46 evidence-gap language. The Sprint 45 default helper
    is unchanged.

Recommended target profile:
`advantech-amax-5580-i5-or-i7-8gb-linux-codesys-cpu-first` — i5-6300U
or i7-6600U at 8 GB, AdvLinuxTU v2.0.5.4 + CODESYS Linux Control V3
SP20, direct PyTorch CPU install — unless a customer site explicitly
requires the Windows 10 LTSC 2019 + CODESYS Control RTE V3.5 SP20
fallback.

What the Sprint 46 gate must approve before Sprint 47 starts:

- SKU tier (i5-6300U / 8 GB or i7-6600U / 8 GB);
- OS path (AdvLinuxTU + CODESYS Linux Control primary, Windows +
  CODESYS RTE only as a site-required fallback);
- packaging strategy (direct PyTorch CPU baseline, container sidecar
  fallback);
- ML runtime sequence (PyTorch CPU first, ONNX Runtime CPU and
  OpenVINO as follow-up benchmarks);
- surrogate evidence acceptance — every claim is surrogate until
  real AMAX-5580 hardware is in hand.

**Sprint 47 (next gate, after Sprint 46 evidence is accepted)** is a
CPU inference benchmark / packaging smoke harness only. Sprint 47
must not introduce live OT binding, PLC/PAC/SCADA write, command
emission, setpoint output, control-loop closure, or any Edge Runtime
daemon implementation.

Boundary (reaffirmed):

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop;
- no HTTP / network / database / message-broker code added in this
  sprint;
- no Edge Runtime daemon / service implementation;
- no AI / Optimization Server runtime, no Operations Console runtime;
- no CUDA / TensorRT runtime dependency, no model loading, no inline
  model weights;
- no Phase 1 `aquaoptima.*` import path removals or renames;
- no movement of `evaluate_advisory_proposals`,
  `run_shadow_runtime`, EPANET `.inp` import, or `Network` into the
  SDK.

## Sprint 47 — AMAX CPU dPHM-PINN Benchmark / Packaging Smoke Harness

Sprint 47 ships an **offline, CPU-only** AMAX CPU dPHM-PINN benchmark
and packaging smoke harness. The deliverables prove package / runtime
feasibility evidence only; they do **not** prove real-time control
safety. Host-derived benchmarks are **surrogate** until executed on
real AMAX-5580 hardware.

Shipped in Sprint 47:

- SDK projection under `src/aquaoptima_contracts/edge/benchmark.py`:
  - `AMAXBenchmarkScenario` — frozen scenario record (graph size,
    sequence length, batch size, hidden dim, framework, thread
    count, target hardware profile id). Canonical helper
    `canonical_amax_benchmark_scenarios()` enumerates the
    `amax_cpu_branch_smoke`, `amax_cpu_single_loop_smoke`, and
    `amax_cpu_pump_smoke` scenarios.
  - `AMAXBenchmarkMetrics` — frozen latency p50 / p95 / p99 envelope
    plus iteration / warmup counts, measured framework, Python
    version, torch version, host label, optional max-RSS, and an
    explicit `surrogate_hardware` flag (defaults to `True`). The
    SDK never imports torch; the runner passes the torch version
    as a string.
  - `AMAXBenchmarkReport` — frozen scenario + metrics + cadence
    classification + feasibility / package references + warnings /
    notes record. Carries `surrogate_hardware: bool` explicitly.
    Deterministic `to_dict` / `from_dict`.
  - `classify_supervisory_cadence(p95_ms)` — pure evidence-only
    helper that maps a measured p95 latency to one of
    `sub_1s_supervisory` (`p95 <= 1000 ms`),
    `sub_5s_supervisory` (`p95 <= 5000 ms`),
    `sub_60s_supervisory` (`p95 <= 60000 ms`), or
    `slower_than_60s`. Evidence classification only — not a
    control-loop guarantee.
- Runtime helper under `src/aquaoptima/edge/benchmark.py`:
  - `run_amax_cpu_benchmark` / `run_amax_cpu_benchmark_scenario` —
    deterministic, CPU-only runners that drive `DPHMPINN` over the
    branch / single-loop / pump fixtures under
    `torch.inference_mode()` and return `AMAXBenchmarkReport`
    records. No CUDA path; no model artifact loading from disk; no
    HTTP / network / database / message-broker dependency.
- CLI under `scripts/run_amax_cpu_benchmark.py`: writes a
  deterministic JSON report to the requested path (e.g.
  `artifacts/amax_cpu_benchmark_report.json`) via the SDK's
  canonical JSON writer; prints a concise per-scenario summary;
  defaults to surrogate host mode and CPU-only.
- New audit-only doc:
  `docs/hardware/amax-5580-cpu-benchmarking.md`.

What Sprint 47 does **not** ship:

- no live OT binding by default;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- no HTTP / network / database / message-broker code;
- no Edge Runtime daemon / service implementation;
- no AI / Optimization Server runtime, no Operations Console runtime;
- no live PLC/SCADA/OPC UA/Modbus client;
- no CUDA / TensorRT runtime dependency, no model artifact loading
  from disk, no inline model weights;
- no Phase 1 `aquaoptima.*` import path removals or renames;
- no movement of `evaluate_advisory_proposals`, `run_shadow_runtime`,
  EPANET `.inp` import, or `Network` into the SDK.

**Sprint 48 (next gate, after Sprint 47 benchmark evidence is
accepted)** should remain a **read-only** PLC/SCADA integration
contract gate. Live OT binding, write paths, command emission,
setpoint output, and control-loop closure stay out of scope.

## Sprint 48 — AMAX Read-only PLC/SCADA Integration Contract

Sprint 48 defines how an AMAX Edge instance can **read** telemetry
from site PLC / SCADA / CODESYS-facing systems without controlling
anything. **Sprint 48 ships read-only integration contracts, not live
adapters.** The SDK module is stdlib-only and introduces no live OPC
UA, Modbus, CODESYS, SCADA, PLC, MQTT, HTTP, database, or
message-broker client.

Shipped in Sprint 48 (under
`src/aquaoptima_contracts/edge/read_only_integration.py`):

- `ReadOnlyIntegrationProtocol` — canonical protocol identifier
  surface (`opc_ua`, `modbus_tcp`, `modbus_rtu`, `codesys_symbol`,
  `codesys_shared_memory`, `mqtt_sparkplug_read_only`).
- `ReadOnlyTelemetrySource` — frozen audit record for one read-only
  source. Carries source id, canonical protocol, endpoint label,
  security zone / network segment label, polling cadence, freshness
  threshold, credential reference label, access mode, and notes. Uses
  labels / references only; no secrets, no live connection strings.
  Explicitly marks access as `read_only` / `audit_only`.
- `ReadOnlyTagBinding` — frozen audit record connecting a source
  path / register / symbol label to a Sprint 42 `TelemetryTagSpec`
  projection (axis / role / unit / target id). Carries no write
  registers, command topics, setpoint topics, or actuator semantics.
- `TelemetryFreshnessPolicy` — frozen audit record capturing max age,
  stale behavior, missing-data behavior, quality flag mapping, and
  replay-equivalence expectations. Pure audit evidence; no live
  timer.
- `ReadOnlyIntegrationContract` — frozen audit bundle combining
  sources, tag bindings, freshness policy, compatibility notes, and
  safety notes. Canonical helper
  `default_amax_read_only_integration_contract()` enumerates an OPC
  UA subscription, Modbus TCP poller, Modbus RTU serial poller,
  CODESYS symbol subscription, CODESYS shared-memory mapping, and an
  IT-zone MQTT Sparkplug read-only source.
- `ReadOnlyIntegrationDiagnostics` — deterministic warnings / errors
  surfaced by `diagnose_read_only_integration_contract()` for
  duplicate binding ids, dangling binding source references,
  unsupported protocols, missing safety notes, and unsafe vocabulary
  in labels.
- `ReplayToLiveEquivalenceEvidence` — frozen audit record connecting
  a Sprint 42 `ShadowReplayDataset` to a Sprint 48 source. Default
  status is `not_evaluated`: replay datasets are surrogate evidence
  until a real source verification is signed off.
- New audit-only doc:
  `docs/hardware/amax-5580-read-only-integration.md`.

What Sprint 48 **does not** ship:

- no live OT binding by default;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop;
- no live OPC UA client, no live Modbus client, no live CODESYS
  client, no live SCADA client;
- no HTTP / network / database / message-broker code;
- no Edge Runtime daemon / service implementation;
- no AI / Optimization Server runtime, no Operations Console runtime;
- no model artifact loading from disk, no inline model weights;
- no credentials, passwords, tokens, API keys, or connection secrets
  in docs / tests / source;
- no Phase 1 `aquaoptima.*` import path removals or renames;
- no movement of `evaluate_advisory_proposals`, `run_shadow_runtime`,
  EPANET `.inp` import, or `Network` into the SDK.

The non-negotiable safety boundary stays explicit: telemetry
freshness / staleness and replay-to-live equivalence are audit
evidence, not a live connection. Network segmentation and credential
handling use labels / references only; no secrets are stored.

**Sprint 49 (next gate, after Sprint 48 contract evidence is
accepted)** should be **AMAX Site Deployment Readiness / OT
Certification Evidence Package**. Sprint 49 must not introduce live
OT binding, PLC/PAC/SCADA write, command emission, setpoint output,
control-loop closure, or any Edge Runtime daemon implementation. The
site PLC retains direct VFD / pump / actuator authority for every
Sprint 45+ AMAX deliverable until a future safety gate explicitly
approves a supervised, bounded write surface.

## Sprint 49 — AMAX Site Deployment Readiness / OT Certification Evidence Package

Sprint 49 defines the **site deployment readiness / OT certification
evidence package** required before installing AquaOptima AMAX Edge in
an OT-side environment. **Sprint 49 ships a deployment readiness /
certification evidence package, not a site install approval.** The
SDK module is stdlib-only and introduces no live OT, PLC, SCADA,
MQTT, HTTP, database, or message-broker client. Sprint 49 does not
install software, does not connect to a live site, and does not
approve writes.

Shipped in Sprint 49 (under
`src/aquaoptima_contracts/edge/deployment_readiness.py`):

- `DeploymentReadinessItem` — frozen labels-only audit row for one
  readiness item (item id, category, description, evidence reference
  label, owner / approver label, status, blocking flag, notes).
- `AMAXDeploymentReadinessChecklist` — frozen audit bundle of
  readiness items with helpers (`categories`, `items_for_category`,
  `unresolved_blocking_items`, `is_fully_approved`). Canonical
  helper `default_amax_deployment_readiness_checklist()` enumerates
  twelve categories: `sku`, `os_image`, `codesys_package`,
  `network_ports`, `physical_install`, `power`, `storage`,
  `environment`, `rollback`, `cybersecurity`, `fat_sat`,
  `safety_boundary`. Default items remain `pending`; real site
  evidence is required.
- `AMAXOTCertificationEvidence` — frozen audit record contrasting
  AMAX hardware certification (CE, FCC, UL, EN 61131-2, IEC 61010-1,
  Class 1 Div 2 where applicable, etc.) with AquaOptima
  system-level qualification evidence (FAT, SAT, site cybersecurity
  review, rollback dry-run, failure-mode walkthrough, Sprint 48
  replay-to-live equivalence sign-off). The
  `hardware_certifies_system` flag is fixed to `False` — AMAX
  hardware certification is necessary but not sufficient for
  AquaOptima system deployment.
- `AMAXFailureMode` — frozen failure mode / effect / detection /
  fallback record. Canonical helper `canonical_amax_failure_modes()`
  covers stale telemetry, package install failure, CPU benchmark
  failure, network loss, power loss, rollback failure, operator
  disable unavailable, and CODESYS co-tenancy unresolved. Each
  fallback narrates a fall-through to site PLC authority.
- `AMAXSiteDeploymentEvidencePackage` — frozen Sprint 49 audit
  bundle combining the checklist, certification evidence,
  failure-mode matrix, Sprint 46 / 47 / 48 evidence references, and
  the next gate. Carries explicit
  `site_specific_approval_required=True`. Canonical helper
  `default_amax_site_deployment_evidence_package()` returns the
  conservative default package: every blocking item is `pending` and
  the package is not site-approved.
- `AMAXDeploymentReadinessDiagnostics` — deterministic warnings /
  errors surfaced by
  `diagnose_amax_site_deployment_evidence_package()` for unresolved
  blocking items, missing required readiness categories, missing
  failure-mode coverage, missing referenced evidence handles,
  missing next-gate language, and unsafe vocabulary in labels.
- New audit-only doc:
  `docs/hardware/amax-5580-site-deployment-readiness.md` covering
  the readiness checklist, cybersecurity posture, certification /
  evidence map, FAT / SAT outline, failure-mode matrix, and the
  explicit Sprint 49 boundary statement.

What Sprint 49 **does not** ship:

- no live OT binding by default;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop;
- no live OPC UA / Modbus / CODESYS / SCADA / PLC / MQTT / HTTP /
  database / message-broker client;
- no Edge Runtime daemon / service implementation;
- no AI / Optimization Server runtime, no Operations Console runtime;
- no model artifact loading from disk, no inline model weights;
- no credentials, passwords, tokens, API keys, or connection secrets
  in docs / tests / source;
- no site install approval by default;
- no supervised writes or proposal-to-PLC path;
- no Phase 1 `aquaoptima.*` import path removals or renames;
- no movement of `evaluate_advisory_proposals`, `run_shadow_runtime`,
  EPANET `.inp` import, or `Network` into the SDK.

The non-negotiable safety boundary stays explicit: AMAX hardware
certification is necessary but not sufficient for AquaOptima system
deployment; FAT / SAT, cybersecurity, rollback, and failure-mode
evidence are required before any pilot. The site PLC retains direct
VFD / pump / actuator authority.

**Sprint 50 (next gate, after Sprint 49 evidence is accepted)**
should remain a **simulated supervisory proposal / PLC gatekeeper
contract** sprint, not a live write / control sprint. Sprint 50 must
not introduce live OT binding, PLC/PAC/SCADA write, command emission,
setpoint output, control-loop closure, or any Edge Runtime daemon
implementation. The site PLC retains direct VFD / pump / actuator
authority for every Sprint 45+ AMAX deliverable until a future
safety gate explicitly approves a supervised, bounded write surface.
