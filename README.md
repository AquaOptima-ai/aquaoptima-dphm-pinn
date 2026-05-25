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

## Shared Contracts / SDK (Sprint 41 MVP + Sprint 42 / 43 / 44 / 45 projections)

The Shared Contracts / SDK package ships under
`src/aquaoptima_contracts/` and exposes the cross-component vocabulary
every Phase 2+ deployable depends on. Sprint 41 shipped the MVP
foundation; Sprint 42 added the first batch of contract *shape*
projections from the Phase 1 runtime artifacts; Sprint 43 closed the
first-batch list with calibration, advisory, and EPANET
import-quality projections; Sprint 44 adds the deployment package
manifest contracts plus the model / artifact registry projection;
Sprint 45 promotes the Advantech AMAX-5580 to the primary Edge target
and ships the deny-by-default Edge package validator (CPU-first x86_64
PAC profile) consuming a Sprint 44 `DeploymentPackageManifest`.

Sprint 41 MVP:

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

Sprint 42 additions:

- `Checksum` (algorithm + hex digest + size), `Provenance`
  (component + version + optional build id / signer identity),
  extended `ArtifactReference` (now carries optional `checksum` +
  `uri`);
- `TelemetryAxis` canonical axis vocabulary + `UnitSpec` canonical
  unit / dimension record;
- `TelemetryTagSpec` / `TelemetryTagMap` / `TelemetryTagMapDiagnostics`
  shape projections + a Phase 1 fixture adapter
  (`project_phase1_tag_map_document`);
- `ShadowReplayFrame` / `ShadowReplayDataset` /
  `ShadowReplayDiagnostics` shape projections + a Phase 1 CSV body
  adapter (`project_phase1_replay_csv_text`);
- `ShadowDeploymentArtifact` / `ShadowDeploymentManifest` /
  `ShadowDeploymentPackageDiagnostics` shape projections;
- `ShadowRuntimeStepReport` / `ShadowRuntimeReport` /
  `ShadowRuntimeDiagnostics` shape projections.

Sprint 43 additions:

- `DPLResidual` / `CalibrationLossSummary` /
  `DPLCalibrationDiagnostics` / `DPLCalibrationLossReport` —
  dPL calibration loss shape projections, plus a duck-typed Phase 1
  adapter (`project_phase1_dpl_calibration_loss_report`);
- `AdvisoryRule` / `AdvisoryContract` / `AdvisoryProposal` /
  `AdvisoryDecision` / `AdvisoryEvaluation` /
  `AdvisoryRejectionReason` — audit-only advisory shape projections
  with a canonical rejection vocabulary
  (`out_of_bounds`, `delta_exceeded`, `deny_rule_match`,
  `no_allow_rule_match`, `insufficient_evidence`,
  `axis_loss_exceeded`, `malformed_proposal`) and a duck-typed
  Phase 1 adapter (`project_phase1_advisory_decisions`);
- `ImportQualitySeverity` / `TopologyReference` /
  `EpanetImportQualitySectionReport` /
  `EpanetImportQualitySurrogateReport` /
  `EpanetImportDiagnosticsRecord` /
  `EpanetImportQualityReport` — EPANET import-quality shape
  projections (Console-facing), plus a duck-typed Phase 1 adapter
  (`project_phase1_import_quality_report`).

Sprint 44 additions:

- `PackageValidationDiagnostic` — deterministic warnings / errors
  tuples for package validation diagnostics.
- `PackageSafetyDeclaration` — mandatory `SafetyFlagSet` plus
  `CapabilityRequirement` bundle attached to every deployment
  package; rejects forbidden vocabulary tokens used in any string
  field.
- `ArtifactManifest` — per-artifact descriptor composed from
  `ArtifactReference` (with optional `Checksum` and `uri`) and
  `Provenance`; constrained to the canonical
  `PACKAGE_ARTIFACT_ROLES` vocabulary.
- `ArtifactBundleRecord` — optional grouping of related artifact
  manifests inside a larger package.
- `ModelArtifactRecord` — audit-only model / artifact registry
  projection carrying `ArtifactReference` + mandatory `Checksum`,
  `Provenance`, `SafetyFlagSet`, and `CapabilityRequirement`. No
  inline weights, no filesystem writes, no runtime loading; the SDK
  never opens a model file.
- `DeploymentPackageManifest` — top-level audit-evidence deployment
  package manifest. Composes `ContractEnvelope` (schema family
  `manifest`), `PackageSafetyDeclaration`, `CapabilityRequirement`,
  `Provenance`, and tuples of `ArtifactManifest` /
  `ModelArtifactRecord` / `ArtifactBundleRecord` plus a
  `PackageValidationDiagnostic`. `package_id` consistency across
  declaration / requirement / manifest is enforced; setpoint-shaped
  field names (`setpoint`, `command`, `control`, `actuate`, `write`,
  `dispatch`, `weights`, `binary`, `raw`) are rejected in
  `from_dict`.
- `build_deployment_package_manifest_from_shadow` — pure-SDK helper
  that lifts a Sprint 42 `ShadowDeploymentManifest` into the
  Sprint 44 `DeploymentPackageManifest` shape without importing
  any `aquaoptima.*` runtime module.

Sprint 45 additions (under `src/aquaoptima_contracts/edge/`):

- **Primary Edge target is now the Advantech AMAX-5580** (or
  equivalent x86_64 PAC-class industrial controller). The
  Jetson / Orin / TensorRT path remains an optional accelerator
  profile only — it is *not* the default Edge deployment path.
- `EdgeHardwareProfile` — frozen hardware / runtime capability
  metadata (profile_id, vendor, model, architecture, OS family,
  runtime class, accelerators, supported model frameworks, Python
  versions, audit-only notes). Ships with the canonical
  `amax_5580_cpu_profile()` helper (x86_64, CPU-first, PAC class,
  no CUDA / TensorRT / Jetson / Orin / ARM64 default).
- `EdgeCapabilityDeclaration` — pairs a Sprint 41
  `CapabilityDeclaration` with an `EdgeHardwareProfile`. Ships
  `default_amax_edge_capability_declaration()` for the canonical
  package-validation-only declaration. No direct write / control /
  setpoint / actuation capability is declared (the underlying
  allowed-token list cannot include any forbidden vocabulary
  anyway).
- `EdgePackageValidationResult` — deterministic
  `accepted` / `errors` / `warnings` bundle with optional
  `profile_id`, `package_id`, `missing_capabilities`,
  `rejected_accelerator_tokens`, and `rejected_frameworks` evidence.
- `validate_deployment_package_for_edge(...)` — pure value function
  that consumes a Sprint 44 `DeploymentPackageManifest` and an
  `EdgeCapabilityDeclaration` and returns an
  `EdgePackageValidationResult`. Default AMAX rejection covers
  CUDA / TensorRT / Jetson / Orin / ARM64 / aarch64 metadata,
  runtime-loading-implied frameworks outside the profile's allow
  list, and packages whose merged capability requirements are not
  satisfied by the Edge declaration.

Boundary for all Sprint 45 AMAX work (reaffirmed):

- AMAX-5580 is the primary Edge target; Orin / TensorRT is an
  optional accelerator profile only;
- the site PLC / pump-station PLC remains the direct VFD / pump /
  actuator authority;
- no live OT binding by default;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge.

The SDK is stdlib-only at runtime and never imports any
`aquaoptima.*` deployable module. It does not introduce live OT
binding, PLC/PAC/SCADA write, command emission, setpoint output,
control-loop closure, HTTP, database, or message-broker code paths.
The full Phase 1 runtime modules
(`aquaoptima.dphm.telemetry_tag_map`, `aquaoptima.dphm.shadow_replay`,
`aquaoptima.dphm.shadow_deployment`, `aquaoptima.dphm.shadow_runtime`,
`aquaoptima.dphm.advisory_contract`, `aquaoptima.dphm.dpl_calibration`)
remain the authority for in-network runtime behavior; the SDK only
owns deterministic *shape* and JSON projections.

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
