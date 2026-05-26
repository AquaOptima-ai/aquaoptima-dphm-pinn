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



## Sprint 52 - AMAX vendor PAC software inventory

Sprint 52 adds a manual-grounded AMAX vendor PAC software inventory and
integration-boundary contract. It is not replan-only: it ships SDK
records, tests, and `docs/hardware/amax-5580-vendor-pac-software-inventory.md`.

The important architecture correction is that AMAX/CODESYS is the
PAC/control substrate. The AMAX-5580 CODESYS Ready PAC manual entry
lists Windows 10 LTSC, 128 GB M.2, 2 MB NVRAM, and CODESYS V3 Pure
Control with Visu(HMI). AquaOptima remains a sidecar advisory/evidence
layer for model inference, validation, dry-run proposals, and read-only
health/status evidence.

The Linux driver package does not prove CODESYS Linux availability or
licensing. It confirms EC/platform support such as watchdog, hwmon,
LED, GPIO, and EEPROM. Vendor confirmation is still required before
assuming CODESYS Linux Control or protocol package availability on a
Linux AMAX image.

Sprint 52 preserves the safety boundary: no live OT binding, no
PLC/PAC/SCADA write, no command emission, no setpoint output, no
control-loop closure, no CODESYS project generation, and no Python
EtherCAT master/control implementation.



### AMAX-8580 supplier update

Supplier guidance after Sprint 52 indicates that **AMAX-5580 will stop
production** and that **AMAX-8580** is the replacement platform, with
product release expected in approximately three months. Detailed
AMAX-8580 user-manual / ordering / licensing evidence is not yet fully
available, so AMAX-8580 is now the intended forward Edge hardware target
but remains behind vendor-confirmation gates.

The AMAX-5580 inventory remains useful as historical / fallback evidence
for the PAC boundary: AMAX/CODESYS owns PAC/control/HMI/EtherCAT field
I/O, while AquaOptima remains the sidecar advisory/evidence layer.

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

## Shared Contracts / SDK (Sprint 41 MVP + Sprint 42 / 43 / 44 / 45 / 46 / 47 / 48 / 49 projections)

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
PAC profile) consuming a Sprint 44 `DeploymentPackageManifest`. Sprint
46 is an evidence and decision-gate sprint that turns AMAX-5580
datasheet facts into deterministic SDK evidence (`AMAXSkuProfile`,
`AMAXRuntimeOption`, `AMAXFeasibilityDecision`) and the
`docs/hardware/amax-5580-feasibility.md` feasibility note that pins
the recommended SKU / OS / runtime path before deeper Edge
implementation begins; Sprint 47 is the CPU inference benchmark /
packaging smoke harness *only after the Sprint 46 evidence gate is
accepted*.

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

Sprint 46 additions (under `src/aquaoptima_contracts/edge/feasibility.py`):

- **Sprint 46 ships the AMAX feasibility evidence / SKU & OS decision
  gate.** The deliverables are SDK evidence shapes plus the
  `docs/hardware/amax-5580-feasibility.md` feasibility note. No live
  OT integration, no Edge Runtime daemon, no model loading, and no
  HTTP / database / message-broker code is introduced.
- `AMAXSkuProfile` — frozen Advantech AMAX-5580 CPU / RAM SKU
  evidence record (Celeron 3955U / 4 GB constrained fallback, Core
  i5-6300U / 8 GB serious candidate, Core i7-6600U / 8 GB recommended
  candidate). Deterministic `to_dict` / `from_dict`. Canonical helper:
  `canonical_amax_sku_profiles()`.
- `AMAXRuntimeOption` — frozen OS / CODESYS / ML packaging evidence
  record covering AdvLinuxTU v2.0.5.4 (Ubuntu 18 based) + CODESYS
  Linux Control V3 SP20 + PyTorch CPU; Windows 10 LTSC 2019 + CODESYS
  Control RTE V3.5 SP20 + PyTorch CPU; and a Linux container sidecar
  low-risk fallback. Deterministic `to_dict` / `from_dict`. Canonical
  helper: `canonical_amax_runtime_options()`.
- `AMAXFeasibilityDecision` — frozen Sprint 46 recommendation record
  carrying the recommended SKU profile id, OS / runtime
  recommendation, packaging strategy, ML runtime recommendation,
  evidence gaps that remain surrogate until real AMAX hardware
  testing, and the next gate. Canonical helper:
  `default_amax_feasibility_decision()`.
- `recommended_amax_hardware_profile()` — bridge to the Sprint 45
  `amax_5580_cpu_profile()` helper that enriches `notes` with Sprint
  46 evidence-gap language. The Sprint 45 default helper is
  unchanged.
- `docs/hardware/amax-5580-feasibility.md` — feasibility evidence
  document with executive decision summary, SKU comparison, OS /
  CODESYS decision matrix, runtime / package strategy matrix, CODESYS
  / PLC integration option matrix (read-only / audit-only), OT
  hardware facts to carry forward, and the recommendation /
  acceptance gate for Sprint 47.

Sprint 47 additions (under `src/aquaoptima_contracts/edge/benchmark.py`,
`src/aquaoptima/edge/benchmark.py`, and `scripts/run_amax_cpu_benchmark.py`):

- **Sprint 47 ships an offline AMAX CPU dPHM-PINN benchmark / packaging
  smoke harness.** Host-derived benchmarks are **surrogate** until run
  on real AMAX-5580 hardware. The harness proves package / runtime
  feasibility evidence only; it does **not** prove real-time control
  safety.
- `AMAXBenchmarkScenario` — frozen scenario record (graph size,
  sequence length, batch size, hidden dim, framework, thread count,
  target hardware profile id). Canonical helper:
  `canonical_amax_benchmark_scenarios()` enumerates the branch /
  single-loop / pump smoke scenarios.
- `AMAXBenchmarkMetrics` — frozen latency p50 / p95 / p99 envelope
  plus iteration / warmup counts, measured framework, Python version,
  torch version, host label, optional max-RSS, and an explicit
  `surrogate_hardware` flag (defaults to `True`).
- `AMAXBenchmarkReport` — frozen scenario + metrics + supervisory
  cadence classification + feasibility / package references +
  warnings record. Deterministic `to_dict` / `from_dict`.
- `classify_supervisory_cadence(p95_ms)` — pure evidence-only helper
  that maps a measured p95 latency to one of
  `sub_1s_supervisory` / `sub_5s_supervisory` / `sub_60s_supervisory`
  / `slower_than_60s`. **Evidence classification only, not a
  control-loop guarantee.**
- `aquaoptima.edge.benchmark.run_amax_cpu_benchmark` — offline,
  CPU-only runner that builds a `DPHMPINN` with deterministic seeds,
  exercises the branch / single-loop / pump fixtures under
  `torch.inference_mode()`, and returns `AMAXBenchmarkReport` records.
  No CUDA path; no model artifact loading from disk; no HTTP /
  network / database / message-broker dependency.
- `scripts/run_amax_cpu_benchmark.py` — CLI smoke harness; writes a
  deterministic JSON report to a path such as
  `artifacts/amax_cpu_benchmark_report.json` via the SDK's canonical
  JSON writer. Defaults to surrogate host mode and CPU-only.

Sprint 47 must **not** introduce live OT binding, PLC/PAC/SCADA write,
command emission, setpoint output, control-loop closure, Edge Runtime
daemon code, AI / Optimization Server runtime, Operations Console
runtime, live PLC/SCADA/OPC UA/Modbus client, HTTP / network /
database / message-broker code, CUDA / TensorRT runtime, model
artifact loading from disk, or inline model weights.

Sprint 48 additions (under
`src/aquaoptima_contracts/edge/read_only_integration.py`):

- **Sprint 48 ships read-only integration contracts, not live
  adapters.** The SDK module is stdlib-only and introduces no live
  OPC UA, Modbus, CODESYS, SCADA, PLC, MQTT, HTTP, database, or
  message-broker client.
- `ReadOnlyIntegrationProtocol` — canonical protocol identifier
  surface (`opc_ua`, `modbus_tcp`, `modbus_rtu`, `codesys_symbol`,
  `codesys_shared_memory`, `mqtt_sparkplug_read_only`).
- `ReadOnlyTelemetrySource` — frozen labels-only audit record for a
  read-only source (source id, canonical protocol, endpoint label,
  security zone label, polling cadence, freshness threshold,
  credential reference label, access mode, notes). Carries no
  secrets, no live connection strings, no IP-shaped literals.
- `ReadOnlyTagBinding` — links a source-path label to a Sprint 42
  `TelemetryTagSpec` (axis / role / unit / target id). Carries no
  write registers, command topics, setpoint topics, or actuator
  semantics.
- `TelemetryFreshnessPolicy` — frozen audit record (max age, stale
  behavior, missing-data behavior, quality flag mapping, replay
  equivalence expectations). Pure audit evidence, not a live timer.
- `ReadOnlyIntegrationContract` — frozen audit bundle. Canonical
  helper `default_amax_read_only_integration_contract()` enumerates
  the OPC UA / Modbus TCP / Modbus RTU / CODESYS symbol / CODESYS
  shared-memory / MQTT Sparkplug read-only source records.
- `ReadOnlyIntegrationDiagnostics` — deterministic warnings / errors
  surfaced by `diagnose_read_only_integration_contract()`.
- `ReplayToLiveEquivalenceEvidence` — frozen audit record connecting
  a Sprint 42 `ShadowReplayDataset` to a Sprint 48 source. Defaults
  to `not_evaluated` until a real source verification is signed off.

Sprint 48 reaffirms the non-negotiable safety boundary: **no live OT
binding**, **no PLC/PAC/SCADA write**, **no command emission**, **no
setpoint output**, no control-loop closure, no direct VFD / pump /
actuator control from AquaOptima Edge. Network segmentation and
credential handling use labels / references only; no secrets are
stored.

Sprint 49 additions (under
`src/aquaoptima_contracts/edge/deployment_readiness.py`):

- **Sprint 49 ships a site deployment readiness / OT certification
  evidence package, not a site install approval.** The SDK module is
  stdlib-only and introduces no live OT, PLC, SCADA, MQTT, HTTP,
  database, or message-broker client. AMAX hardware certification is
  *necessary but not sufficient* for AquaOptima system deployment.
- `DeploymentReadinessItem` — frozen labels-only audit row (item id,
  category, description, evidence reference label, owner / approver
  label, status, blocking flag, notes).
- `AMAXDeploymentReadinessChecklist` — frozen audit bundle of
  readiness items. Canonical helper
  `default_amax_deployment_readiness_checklist()` enumerates twelve
  categories (`sku`, `os_image`, `codesys_package`, `network_ports`,
  `physical_install`, `power`, `storage`, `environment`, `rollback`,
  `cybersecurity`, `fat_sat`, `safety_boundary`). Default items
  remain `pending`; real site evidence is required.
- `AMAXOTCertificationEvidence` — frozen audit record contrasting
  AMAX hardware certification with the AquaOptima system-level
  qualification evidence (FAT, SAT, cybersecurity review, rollback
  dry-run, failure-mode walkthrough, Sprint 48 replay-to-live
  equivalence sign-off). The `hardware_certifies_system` flag is
  fixed to `False`.
- `AMAXFailureMode` — frozen failure mode / effect / detection /
  fallback row. Canonical helper `canonical_amax_failure_modes()`
  covers stale telemetry, package install failure, CPU benchmark
  failure, network loss, power loss, rollback failure, operator
  disable unavailable, and CODESYS co-tenancy unresolved.
- `AMAXSiteDeploymentEvidencePackage` — frozen Sprint 49 audit
  bundle combining the checklist, certification evidence,
  failure-mode matrix, Sprint 46 / 47 / 48 evidence references, and
  the next gate. Carries explicit
  `site_specific_approval_required=True`.
- `AMAXDeploymentReadinessDiagnostics` — deterministic warnings /
  errors surfaced by
  `diagnose_amax_site_deployment_evidence_package()` for unresolved
  blocking items, missing required categories, missing failure-mode
  coverage, missing referenced evidence, and unsafe vocabulary in
  labels.

Sprint 49 reaffirms the non-negotiable safety boundary: **no live OT
binding**, **no PLC/PAC/SCADA write**, **no command emission**, **no
setpoint output**, no control-loop closure, no site install approval
by default, no supervised writes or proposal-to-PLC path. FAT / SAT,
cybersecurity, rollback, and failure-mode evidence are required
before any pilot. The site PLC retains direct VFD / pump / actuator
authority.

Sprint 50 additions (under
`src/aquaoptima_contracts/edge/supervisory_gatekeeper.py`):

- **Sprint 50 ships a simulated supervisory proposal / PLC gatekeeper
  contract, not a live write or control authorisation.** The SDK
  module is stdlib-only and introduces no live OT, PLC, SCADA, MQTT,
  HTTP, database, or message-broker client. The default contract is
  conservative: every gatekeeper condition starts in
  `not_evaluated`, the evaluation verdict is `not_evaluated`, and
  `live_write_authorized` is fixed to `False`.
- `SupervisoryProposalValue` — frozen labels-only audit row for one
  simulated proposal value (axis label, target id, proposed value,
  unit, lower / upper envelope, confidence, validity window seconds,
  rollback / fallback reference, notes). Bounds are enforced
  (`lower_envelope <= proposed_value <= upper_envelope`); confidence
  is restricted to `[0.0, 1.0]`.
- `SupervisoryProposalDryRun` — frozen audit bundle of proposal
  values with proposal id, source evidence references, created-by
  label, overall validity window, expiration label,
  `simulation_only=True`, `dry_run=True`, and safety notes.
- `PLCGatekeeperCondition` — frozen audit row for one gate (id,
  category, required state, observed evidence label, status,
  blocking flag, notes). Categories cover operator enable, mode
  enabled, interlocks healthy, permissives healthy, stale-data
  rejection, bounds / rate limits, fallback / manual priority, and
  E-stop / manual override.
- `PLCGatekeeperEvaluation` — frozen audit bundle combining a
  proposal with a tuple of gatekeeper conditions and a deterministic
  verdict (`not_evaluated`, `blocked`, or `simulation_accepted`).
  Always carries `simulation_only=True`; the SDK refuses to produce
  any live-write / control verdict.
- `evaluate_plc_gatekeeper_dry_run()` — pure helper producing a
  deterministic simulation-only evaluation from a proposal plus a
  sequence of conditions.
- `AMAXSupervisoryDryRunContract` — frozen Sprint 50 audit bundle
  combining the proposal, the gatekeeper evaluation, Sprint 49
  referenced evidence ids / docs, warnings / errors, and the next
  gate (Sprint 51 — AMAX pilot readiness review / hardware-in-the-
  loop plan, still no live control). Carries explicit
  `live_write_authorized=False`.
- `AMAXSupervisoryDryRunDiagnostics` — deterministic warnings /
  errors record surfaced by
  `diagnose_amax_supervisory_dry_run_contract()` when the contract
  is missing gatekeeper categories, missing Sprint 49 referenced
  evidence, missing next-gate language, attempts to declare live
  write authorisation, or carries unsafe vocabulary in labels.

Sprint 50 reaffirms the non-negotiable safety boundary: **no live OT
binding**, **no PLC/PAC/SCADA write**, **no command emission**, **no
setpoint output**, no control-loop closure, no supervised writes, no
proposal-to-PLC path, no live write authorisation verdict. The site
PLC retains direct VFD / pump / actuator authority. Sprint 50 ships
contract shapes and a dry-run helper, not a pilot sign-off.

Sprint 51 additions (under
`src/aquaoptima_contracts/edge/pilot_readiness.py`):

- **Sprint 51 ships an AMAX pilot readiness review / hardware-in-the-
  loop (HIL) plan contract, not a live write or control
  authorisation.** Sprint 51 remains planning-only / HIL-readiness-
  only. It does not emit setpoints, commands, writes, or close a
  control loop. The SDK module is stdlib-only and introduces no live
  OT, PLC, SCADA, MQTT, HTTP, database, or message-broker client.
  The default review is conservative: every blocking evidence item
  starts in `pending`, the review verdict is `not_ready`, and
  `live_control_authorized` is fixed to `False`.
- `HILTestCase` — frozen labels-only audit row for one HIL test case
  (id, category, objective, required evidence references, expected
  result, blocking flag, simulation_only flag, notes). Always carries
  `simulation_only=True`. Categories cover the Sprint 46–50 evidence
  chain: package install, CPU benchmark, read-only adapter,
  telemetry replay, stale-data failure, package rollback, operator
  disable, network loss, PLC gatekeeper dry-run, deployment
  readiness review.
- `HILTestMatrix` — frozen audit bundle of HIL test cases with a
  matrix id, target hardware profile label, target OS / runtime
  label, bench (or simulated) PLC label, references to Sprint 46–50
  evidence, and audit notes.
- `PilotReadinessEvidenceItem` — frozen audit row for one Sprint 51
  evidence-ledger entry (id, source sprint / doc, status, owner /
  reviewer label, blocking flag, notes). Status tokens are
  `pending`, `available`, or `blocked`.
- `PilotReadinessReview` — frozen Sprint 51 audit bundle combining
  the HIL matrix, evidence items, open risks, verdict
  (`not_ready`, `ready_for_lab_simulation`, or `blocked`),
  referenced Sprint 46–50 evidence, the next gate, and the
  reaffirmed safety boundary. Carries explicit
  `live_control_authorized=False`; the SDK refuses to record this
  flag as `True`.
- `evaluate_amax_pilot_readiness_review()` — pure helper that
  produces a deterministic, lab / simulation-only review from a
  matrix plus a sequence of evidence items. The SDK refuses to
  produce any verdict outside the lab / simulation vocabulary.
- `AMAXPilotReadinessDiagnostics` — deterministic warnings / errors
  record surfaced by `diagnose_amax_pilot_readiness_review()` when
  the review is missing required HIL categories, missing Sprint
  46–50 evidence references, attempts to declare live-control
  authorisation, or carries unsafe vocabulary in identifier / label
  fields.

Sprint 51 reaffirms the non-negotiable safety boundary: **no live OT
binding**, **no PLC/PAC/SCADA write**, **no command emission**, **no
setpoint output**, no control-loop closure, no supervised writes, no
proposal-to-PLC path, no live write or control authorisation
verdict. The site PLC retains direct VFD / pump / actuator
authority.

After Sprint 51, **Sprints 52+** are not yet well-planned and should
be replanned before implementation. The recommended next step after
Sprint 51 is a **phase checkpoint / Sprint 52–60 replanning gate**,
not automatic live-control implementation. Sprint 51 must not
introduce live OT binding, PLC/PAC/SCADA write, command emission,
setpoint output, control-loop closure, or any Edge Runtime daemon
implementation.

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
- [`docs/hardware/amax-5580-feasibility.md`](docs/hardware/amax-5580-feasibility.md) — Sprint 46 AMAX-5580 feasibility evidence / SKU & OS decision gate
- [`docs/hardware/amax-5580-cpu-benchmarking.md`](docs/hardware/amax-5580-cpu-benchmarking.md) — Sprint 47 AMAX-5580 CPU benchmark / packaging smoke harness
- [`docs/hardware/amax-5580-read-only-integration.md`](docs/hardware/amax-5580-read-only-integration.md) — Sprint 48 AMAX-5580 read-only PLC/SCADA integration contract
- [`docs/hardware/amax-5580-site-deployment-readiness.md`](docs/hardware/amax-5580-site-deployment-readiness.md) — Sprint 49 AMAX-5580 site deployment readiness / OT certification evidence package
- [`docs/hardware/amax-5580-supervisory-dry-run-gatekeeper.md`](docs/hardware/amax-5580-supervisory-dry-run-gatekeeper.md) — Sprint 50 AMAX-5580 simulated supervisory proposal / PLC gatekeeper contract
- [`docs/hardware/amax-5580-pilot-readiness-hil-plan.md`](docs/hardware/amax-5580-pilot-readiness-hil-plan.md) — Sprint 51 AMAX-5580 pilot readiness review / hardware-in-the-loop plan
