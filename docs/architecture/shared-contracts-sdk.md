# Shared Contracts / SDK Architecture

## Recommendation and approval gate

`aquaoptima-contracts-sdk` should be the shared, non-deployable stability layer for the 3+1 architecture. It is used by Edge Runtime, AI / Optimization Server, and Operations Console, but it is not itself a runtime service.

**Do not start Sprint 40 implementation until the user explicitly approves the replan.** Sprint 40 should confirm this SDK boundary, the contract inventory, schema versioning rules, safety vocabulary, and component dependency rules before any implementation begins.

The mandatory safety boundary encoded by the Shared Contracts / SDK is:

- No live OT binding.
- No PLC / PAC / SCADA write.
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated and approved.
- Future edge/PAC work must begin mock, offline, simulated, dry-run, read-only, and capability-gated.

## Purpose

The Shared Contracts / SDK is the single source of truth for all data exchanged between the three deployable components:

1. **Edge Runtime**
2. **AI / Optimization Server**
3. **Operations Console**

It owns stable wire/file/in-process contract types, deterministic serialization, safety vocabulary, and compatibility fixtures. It prevents schema drift and supports independent deployment.

## Non-goals

The Shared Contracts / SDK must not own:

- dPHM/dPHM-PINN inference.
- Model training or retraining.
- Optimization algorithms.
- Edge runtime execution.
- Telemetry adapter behavior.
- UI rendering.
- Operator workflow state machines.
- Database persistence implementation.
- Job scheduling.
- Package distribution orchestration.
- OT binding behavior.
- PLC/PAC/SCADA writes.
- Command or setpoint emission.

The SDK may define payload shapes for approved capabilities only. Current contracts must preserve Phase 1 safety: offline/read-only by default, no live OT binding, no writes, no commands, no setpoints, and audit-only advisory proposals.

For **Phase 2**, the SDK should first stabilize advisory-readiness, operator-review, retraining-dataset, model-evaluation, and deployment-package contracts without enabling a live write path. For **Phase 3**, the same SDK should extend into edge capability, safety-interlock, dry-run envelope, watchdog, package-verification, and PAC qualification evidence contracts. Schema additions across both phases must remain backward-compatible and must not authorize live OT binding or setpoint output merely by existing as types.

## Recommended package structure

Package name:

```text
aquaoptima-contracts-sdk
```

Python import root:

```python
aquaoptima_contracts
```

Recommended module layout:

```text
aquaoptima_contracts/
  __init__.py
  version.py

  base/
    envelope.py
    identifiers.py
    timestamps.py
    pagination.py
    errors.py
    validation.py
    serialization.py

  telemetry/
    tag_map.py
    replay_dataset.py
    telemetry_frame.py
    units.py

  advisory/
    contract.py
    proposal.py
    evaluation.py
    rules.py

  operator/
    review.py
    approval.py
    notes.py
    workflow_events.py

  edge/
    health.py
    status.py
    capability.py
    package_validation.py
    audit.py

  manifests/
    deployment_manifest.py
    package_manifest.py
    artifact_manifest.py
    checksums.py

  model_registry/
    model_artifact.py
    model_version.py
    evaluation_record.py
    registry_queries.py

  safety/
    boundary.py
    flags.py
    capability_gates.py
    vocabulary.py
    violations.py

  api/
    ai_server.py
    edge_status.py
    console.py
    common.py

  clients/
    ai_server_client.py
    edge_status_client.py

  jsonschema/
    generated/

  fixtures/
    phase1_shadow/

  testing/
    builders.py
    assertions.py
    golden_files.py
    compatibility.py
```

## Design rules

1. All externally exchanged payloads must be defined in the SDK.
2. All top-level contracts must carry schema metadata.
3. All contracts must be JSON-serializable.
4. Manifest and audit serialization must be deterministic.
5. Safety-related enums, phrases, and flags must live in `safety/`.
6. Thin clients may call public APIs only.
7. No deployable may import another deployable's internal models.
8. No contract may silently default unsafe capability state.
9. Unknown required capabilities must be rejected.
10. Current contracts must avoid command/write/setpoint semantics.

## Contract families

### 1. Safety contracts

Safety contracts centralize the product boundary and capability vocabulary.

Initial types:

- `SafetyFlagSet`
- `CapabilityGate`
- `CapabilityDeclaration`
- `CapabilityRequirement`
- `SafetyViolation`
- `SafetyBoundaryAcknowledgement`

Canonical Phase 1 safety flags:

```text
offline
read_only
no_write
no_control
no_live_ot_binding
no_setpoint_output
packaging_audit_only
```

Rules:

- Safety vocabulary must not be duplicated in deployables.
- Deployment manifests must include safety declarations.
- Edge Runtime enforces capability requirements locally.
- Operations Console displays safety boundaries during review.
- AI / Optimization Server refuses to package artifacts whose capabilities exceed the approved boundary.

### 2. Telemetry contracts

Initial types:

- `TelemetryTagMap`
- `TelemetryTag`
- `TelemetryFrame`
- `ShadowReplayDataset`
- `TelemetryAxis`
- `UnitSpec`

Rules:

- Tag maps bind source tags to canonical dPHM axes and target IDs.
- Units must be explicit.
- Unknown or unsupported tags must be validation errors, not silently ignored.
- Replay datasets are offline/read-only artifacts.

### 3. Advisory contracts

Initial types:

- `AdvisoryContract`
- `AdvisoryRule`
- `AdvisoryProposal`
- `AdvisoryEvaluation`
- `AdvisoryDecision`
- `AdvisoryRejectionReason`

Rules:

- Advisory proposals are audit/review data, not commands.
- Current advisory contracts must not represent setpoints or actuation.
- Evaluation results must be explicit: accepted, rejected, skipped, or unsupported.
- Rejection reasons must be machine-readable.

### 4. Manifest contracts

Initial types:

- `ShadowDeploymentManifest`
- `DeploymentPackageManifest`
- `ArtifactManifest`
- `ArtifactReference`
- `Checksum`
- `PackageSafetyDeclaration`

Rules:

- Manifests render deterministically.
- Every artifact includes kind, version, ID, checksum, and provenance.
- Safety flags are mandatory.
- Packages with missing or incompatible safety declarations are rejected.

### 5. Edge contracts

Initial types:

- `EdgeHealthReport`
- `EdgeStatusSnapshot`
- `EdgeCapabilityDeclaration`
- `EdgePackageValidationResult`
- `EdgeAuditEvent`

Rules:

- Edge status APIs are read-only.
- Capabilities are explicit and deny-by-default.
- `control_enabled` is not allowed in the current architecture.
- Edge rejects packages requiring unsupported capabilities.

### 6. Model registry contracts

Initial types:

- `ModelArtifactRecord`
- `ModelVersionRecord`
- `ModelEvaluationRecord`
- `ModelRegistryQuery`
- `ModelCompatibilityReport`

Rules:

- Records describe artifacts; model weights are not embedded inline.
- Artifacts include checksums.
- Hardware/runtime requirements are explicit.
- Edge compatibility can be checked from metadata.

### 7. Operator contracts

Initial types:

- `OperatorReviewRequest`
- `OperatorReviewDecision`
- `OperatorNote`
- `DeploymentApprovalRecord`
- `ReviewWorkflowEvent`

Rules:

- Operator approval is not a control command.
- Approval may authorize package distribution or review, not actuation.
- Records include actor, timestamp, artifact IDs, decision, and safety acknowledgement.

## Schema metadata

Every top-level contract must include fields equivalent to:

```json
{
  "schema_family": "telemetry",
  "schema_name": "TelemetryTagMap",
  "schema_version": "1.0.0",
  "sdk_version": "0.1.0"
}
```

Required:

- `schema_family`
- `schema_name`
- `schema_version`
- `sdk_version`

Recommended:

- `created_at`
- `created_by_component`
- `artifact_id`
- `correlation_id`
- `provenance`

## Versioning policy

Schemas use semantic versioning:

```text
MAJOR.MINOR.PATCH
```

- **PATCH**: documentation updates, safe validation fixes, non-wire behavior fixes.
- **MINOR**: backward-compatible additions.
- **MAJOR**: breaking field, enum, meaning, requiredness, or safety changes.

Readers must:

- Reject unsupported major versions.
- Tolerate unknown optional fields.
- Reject missing required fields.
- Reject unknown required capabilities.
- Reject unsafe or ambiguous safety declarations.

Writers must:

- Write the lowest compatible schema version unless a newer feature is required.
- Use deterministic rendering for manifests.
- Include explicit safety flags.

## First 10 concrete contract types

1. `SafetyFlagSet`
2. `CapabilityDeclaration`
3. `TelemetryTagMap`
4. `TelemetryFrame`
5. `ShadowReplayDataset`
6. `AdvisoryContract`
7. `AdvisoryProposal`
8. `ShadowRuntimeReport`
9. `DeploymentPackageManifest`
10. `ModelArtifactRecord`

These types should be the foundation for Sprint 41 and Sprint 42 after the Sprint 40 replan is approved.

## API payload use

Initial communication should use REST/HTTP with JSON payloads defined by the SDK.

Examples:

```text
Edge Runtime → AI Server
  POST /api/v1/edge/reports/shadow-runtime
  POST /api/v1/edge/health
  POST /api/v1/edge/package-validation-results
  GET  /api/v1/deployment-packages/{package_id}
  GET  /api/v1/deployment-packages/{package_id}/manifest

Operations Console → AI Server
  GET  /api/v1/models
  GET  /api/v1/reports/shadow-runtime
  GET  /api/v1/deployment-packages
  POST /api/v1/operator/reviews

Operations Console → Edge Runtime, read-only only where approved
  GET /api/v1/edge/status
  GET /api/v1/edge/health
  GET /api/v1/edge/capabilities
```

Disallowed current endpoints:

```text
POST /command
POST /setpoint
POST /control
POST /actuate
```

## Testing and release gates

A new SDK release is allowed only if:

1. Schema unit tests pass.
2. Golden file tests pass.
3. Compatibility matrix passes.
4. Safety validation tests pass.
5. Phase 1 shadow-mode fixtures still pass through SDK contracts.
6. Generated JSON Schemas are updated.
7. Changelog documents schema changes.
8. No deployable-specific implementation logic is added.
9. No command/write/setpoint vocabulary is introduced for current product scope.
10. Unsafe package declarations are rejected in negative tests.

## Sprint sequencing

Sprint 40 should be planning and approval. After user approval, Sprint 41 should implement the minimal Shared Contracts / SDK foundation: schema metadata, `SafetyFlagSet`, `CapabilityDeclaration`, deterministic JSON helpers, golden file harness, and negative tests. Edge, AI, and Operations Console implementation should wait for these contract foundations.