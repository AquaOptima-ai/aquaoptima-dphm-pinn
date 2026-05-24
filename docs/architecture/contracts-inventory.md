# Shared Contracts / SDK — First Contract Inventory

This document is the Sprint 40 inventory of contract types the Shared
Contracts / SDK package will eventually own. It does **not** implement
anything. It names, categorizes, and version-tags every candidate
contract so that:

1. The Sprint 41 SDK MVP slice is unambiguous.
2. Sprint 42+ work has an agreed-upon backlog and order.
3. Cross-component contract drift becomes detectable.
4. Safety vocabulary stays centralized and de-duplicated.

The mandatory safety boundary applies to every contract listed here:

- No live OT binding.
- No PLC/PAC/SCADA write (required exact phrase: no PLC/PAC/SCADA write).
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated
  and approved.

No contract in this inventory represents a command, setpoint, write,
actuation, or control payload. Advisory proposals remain audit /
review payloads.

## Inventory legend

- **MVP (Sprint 41)** — implemented during Sprint 41.
- **First batch (Sprint 42)** — first batch of contracts after the SDK
  foundation.
- **Phase 2 (Sprints 43–51)** — added as Phase 2 features require them.
- **Phase 3 (Sprints 52–70)** — added during qualified PAC-like edge
  preparation. Phase 3 additions are lab-only until separately
  approved.

Every Sprint 41+ contract is required to:

1. Carry the `ContractEnvelope` schema metadata fields described in
   [`shared-contracts-sdk.md`](shared-contracts-sdk.md) (`schema_family`,
   `schema_name`, `schema_version`, `sdk_version`, plus recommended
   `created_at`, `created_by_component`, `artifact_id`,
   `correlation_id`, `provenance`).
2. Be JSON-serializable through the SDK deterministic writer.
3. Reject unknown required capabilities and unsafe safety declarations.
4. Have a golden fixture (positive case) and at least one negative
   test (missing safety flag, unsafe capability, or unknown schema
   major).

## 1. Safety contracts

The single source of truth for the product safety boundary.

| Type | Status | Notes |
|---|---|---|
| `SafetyFlagSet` | **MVP (Sprint 41)** | Frozen set of canonical safety flag tokens; rejects unknown flags. Must be derivable from Phase 1 `SAFETY_BOUNDARY_PHRASES`. |
| `CapabilityDeclaration` | **MVP (Sprint 41)** | Declares advertised capabilities (Edge) and required capabilities (package). Deny-by-default. |
| `CapabilityRequirement` | First batch (Sprint 42) | Embeds in deployment package manifests; rejected if exceeds Edge advertised set. |
| `CapabilityGate` | First batch (Sprint 42) | Helper combining declaration + requirement + enforcement result. |
| `SafetyViolation` | First batch (Sprint 42) | Machine-readable violation record (rule id, reason, evidence). |
| `SafetyBoundaryAcknowledgement` | First batch (Sprint 42) | Operator acknowledgement record (actor, timestamp, package id, safety flags). |
| `LLMSafetyRestriction` | Phase 2 (Sprint 66) | Declared restrictions for the local LLM assistant. |

Canonical Sprint 41 safety flag tokens (initial set):

```text
offline
read_only
no_write
no_control
no_live_ot_binding
no_setpoint_output
packaging_audit_only
```

Forbidden vocabulary for the entire approved planning window (must
**never** appear as a recognized safety flag, capability, or contract
verb):

```text
live_ot_bind_write
plc_write
pac_write
scada_write
setpoint_output
command_emit
actuator_control
closed_loop_control
remote_control_api
llm_command_execution
operator_chat_to_control
unreviewed_package_activation
```

See
[`docs/safety/capability-model-and-safety-gates.md`](../safety/capability-model-and-safety-gates.md)
for the full allowed / forbidden capability lists.

## 2. Envelope and identity contracts

These wrap every other contract and supply schema metadata, identity,
and timing fields.

| Type | Status | Notes |
|---|---|---|
| `ContractEnvelope` | **MVP (Sprint 41)** | `schema_family`, `schema_name`, `schema_version`, `sdk_version`, optional `created_at`, `created_by_component`, `artifact_id`, `correlation_id`, `provenance`. |
| `SchemaVersion` | **MVP (Sprint 41)** | SemVer triple with explicit reader/writer behavior. |
| `ArtifactReference` | First batch (Sprint 42) | `{kind, id, version, checksum, uri?}`. |
| `Checksum` | First batch (Sprint 42) | Algorithm + hex digest + byte length. |
| `Provenance` | First batch (Sprint 42) | Component name, version, build id, optional signing identity (deferred). |
| `ContractError` | First batch (Sprint 42) | Standard validation/decoding error envelope. |
| `Pagination` | Phase 2 (Sprint 43) | Cursor/limit fields for API queries. |

## 3. Telemetry contracts

| Type | Status | Notes |
|---|---|---|
| `TelemetryTagMap` | First batch (Sprint 42) | SDK projection of Phase 1 Sprint 34 surface. |
| `TelemetryTagSpec` | First batch (Sprint 42) | Single tag entry: source tag, canonical axis, target id, unit. |
| `CanonicalTelemetryTag` | First batch (Sprint 42) | Canonical-axis-side identity. |
| `TelemetryTagMapDiagnostics` | First batch (Sprint 42) | Errors/warnings; rejects unknown axes and ambiguous units. |
| `TelemetryFrame` | Phase 2 (Sprint 46) | Single replay/mock-live frame. |
| `ShadowReplayDataset` | First batch (Sprint 42) | SDK projection of Phase 1 Sprint 35 surface. |
| `ShadowReplayFrame` | First batch (Sprint 42) | Per-timestamp frame inside the dataset. |
| `ShadowReplayDiagnostics` | First batch (Sprint 42) | Missing/invalid/stale/out-of-range counts. |
| `TelemetryAxis` | First batch (Sprint 42) | Canonical axis token enum. |
| `UnitSpec` | First batch (Sprint 42) | Unit name + dimension; explicit, never inferred. |

## 4. dPL / calibration contracts

| Type | Status | Notes |
|---|---|---|
| `DPLCalibrationLossReport` | First batch (Sprint 42) | SDK projection of Phase 1 Sprint 36 report. |
| `DPLResidual` | First batch (Sprint 42) | Per-observation residual record. |
| `DPLCalibrationDiagnostics` | First batch (Sprint 42) | Missing / unused predictions and per-axis counts. |
| `CalibrationLossSummary` | First batch (Sprint 42) | Weighted MSE / per-axis MSE / per-axis MAE. |

## 5. Advisory contracts

| Type | Status | Notes |
|---|---|---|
| `AdvisoryContract` | First batch (Sprint 42) | Allow-list + deny-list of `AdvisoryRule`. |
| `AdvisoryRule` | First batch (Sprint 42) | `(axis, target_id)` plus value bounds plus rule mode (allow/deny). |
| `AdvisoryProposal` | First batch (Sprint 42) | Hypothetical proposal payload; **audit-only**; must not be reinterpreted as a command. |
| `AdvisoryDecision` | First batch (Sprint 42) | Accepted / rejected / skipped / unsupported. |
| `AdvisoryEvaluation` | First batch (Sprint 42) | Decision + rule violations + evidence references. |
| `AdvisoryRejectionReason` | First batch (Sprint 42) | Machine-readable rejection enum. |

## 6. Operator review contracts

| Type | Status | Notes |
|---|---|---|
| `OperatorReviewRequest` | Phase 2 (Sprint 49) | Request to review a package or report. |
| `OperatorReviewDecision` | Phase 2 (Sprint 49) | Review decision token + acknowledgement. |
| `OperatorNote` | Phase 2 (Sprint 49) | Audit-only operator-authored note. |
| `DeploymentApprovalRecord` | Phase 2 (Sprint 49) | Authorizes shadow distribution / review only. |
| `ReviewWorkflowEvent` | Phase 2 (Sprint 49) | Immutable workflow audit envelope. |

## 7. Deployment manifest contracts

| Type | Status | Notes |
|---|---|---|
| `ShadowDeploymentManifest` | First batch (Sprint 42) | SDK projection of Phase 1 Sprint 39 manifest. |
| `ShadowDeploymentArtifact` | First batch (Sprint 42) | Per-artifact record (kind, version, id, checksum, provenance). |
| `ShadowDeploymentPackageDiagnostics` | First batch (Sprint 42) | Missing / invalid artifact diagnostics. |
| `DeploymentPackageManifest` | Phase 2 (Sprint 44) | Full deployment package manifest used by Edge validator. |
| `ArtifactManifest` | Phase 2 (Sprint 44) | Top-level artifact descriptor list. |
| `PackageSafetyDeclaration` | Phase 2 (Sprint 44) | Mandatory safety flag bundle for every package. |

## 8. Edge capability contracts

| Type | Status | Notes |
|---|---|---|
| `EdgeCapabilityDeclaration` | Phase 2 (Sprint 45) | Edge-advertised capability set; deny-by-default. |
| `EdgePackageValidationResult` | Phase 2 (Sprint 45) | Result of every package validation attempt, including rejections. |
| `EdgeHealthReport` | Phase 2 (Sprint 47) | Process / replay / report health. |
| `EdgeStatusSnapshot` | Phase 2 (Sprint 47) | Read-only status snapshot. |
| `EdgeAuditEvent` | Phase 2 (Sprint 47) | Immutable audit event envelope. |
| `EdgeRuntimeMode` | Phase 2 (Sprint 46) | One of `offline_replay`, `mock_live_read`, `advisory_audit_only`, `package_validation_only`, `dry_run_read_only` (gated). |

## 9. Model registry contracts

| Type | Status | Notes |
|---|---|---|
| `ModelArtifactRecord` | Phase 2 (Sprint 44) | Artifact descriptor (no inline weights); includes checksum and provenance. |
| `ModelVersionRecord` | Phase 3 (Sprint 57) | Model version metadata. |
| `ModelEvaluationRecord` | Phase 3 (Sprint 57) | Evaluation metrics linked to a model version. |
| `ModelRegistryQuery` | Phase 3 (Sprint 57) | Query / response envelope for registry API. |
| `ModelCompatibilityReport` | Phase 3 (Sprint 57) | Edge-capability compatibility check. |
| `RetrainingJobRecord` | Phase 3 (Sprint 58–59) | Dataset, config, output artifact, evaluation references. |

## 10. Shadow runtime report contracts

| Type | Status | Notes |
|---|---|---|
| `ShadowRuntimeReport` | First batch (Sprint 42) | SDK projection of Phase 1 Sprint 38 report. |
| `ShadowRuntimeStepReport` | First batch (Sprint 42) | Per-frame step result. |
| `ShadowRuntimeDiagnostics` | First batch (Sprint 42) | Missing-prediction, unused-proposal, rejection counts. |

## 11. Topology / import contracts (consumer-facing projections)

| Type | Status | Notes |
|---|---|---|
| `EpanetImportQualityReport` | First batch (Sprint 42) | SDK projection of Phase 1 Sprint 33 surface; Console-facing. |
| `EpanetImportDiagnosticsRecord` | Phase 2 (Sprint 43) | Slim, Console-friendly projection of `EpanetImportDiagnostics`. The full diagnostics object stays on the AI side. |
| `TopologyReference` | Phase 2 (Sprint 43) | Reference (id + version + checksum) to a topology stored on the AI Server. |

## 12. API payload contracts (Phase 2)

These describe the wire shapes used between Edge ↔ AI and Console ↔ AI.
None of them carry command / setpoint / control verbs.

| Contract / endpoint | Status | Notes |
|---|---|---|
| `GET /api/v1/models` | Phase 2 (Sprint 43) | Returns paged `ModelArtifactRecord`. |
| `GET /api/v1/calibration-reports/{id}` | Phase 2 (Sprint 43) | Returns `DPLCalibrationLossReport`. |
| `POST /api/v1/deployment-packages` | Phase 2 (Sprint 44) | AI builds a package; refuses unsafe capabilities. |
| `GET /api/v1/deployment-packages/{id}` | Phase 2 (Sprint 44) | Read-only. |
| `GET /api/v1/deployment-packages/{id}/manifest` | Phase 2 (Sprint 44) | Read-only manifest. |
| `POST /api/v1/edge/reports/shadow-runtime` | Phase 2 (Sprint 47) | Edge → AI report ingestion. |
| `POST /api/v1/edge/health` | Phase 2 (Sprint 47) | Edge → AI. |
| `POST /api/v1/edge/package-validation-results` | Phase 2 (Sprint 47) | Edge → AI. |
| `GET /api/v1/edge/status` | Phase 2 (Sprint 47) | Read-only Edge status (Console / AI). |
| `GET /api/v1/edge/capabilities` | Phase 2 (Sprint 47) | Read-only Edge capability declaration. |
| `POST /api/v1/operator/reviews` | Phase 2 (Sprint 49) | Console → AI; `OperatorReviewRequest` + `OperatorReviewDecision`. |
| `POST /api/v1/retraining-jobs` | Phase 3 (Sprint 59) | AI internal lifecycle; not edge-exposed. |
| `GET /api/v1/retraining-jobs/{id}` | Phase 3 (Sprint 59) | Read-only. |
| `POST /api/v1/advisory-proposal-batches` | Phase 3 (Sprint 61) | Audit-only advisory proposal batches. |

Disallowed endpoints in the SDK and in every deployable:

```text
POST /command
POST /setpoint
POST /control
POST /actuate
POST /write
POST /dispatch
```

## Schema versioning expectations

All contracts use **semantic versioning** (`MAJOR.MINOR.PATCH`):

- **PATCH** — documentation updates, safe validation fixes, non-wire
  behavior fixes.
- **MINOR** — backward-compatible additions (new optional fields,
  new enum members that are tolerated by older readers).
- **MAJOR** — breaking field, enum, meaning, requiredness, or safety
  changes.

Sprint 41 starts every MVP contract at `1.0.0`. The SDK package version
starts at `0.1.0`.

Reader rules:

1. Reject unsupported MAJOR versions.
2. Tolerate unknown OPTIONAL fields.
3. Reject missing REQUIRED fields.
4. Reject unknown REQUIRED capabilities.
5. Reject unsafe or ambiguous safety declarations.
6. Reject unknown safety flag tokens (additions require an SDK
   release).

Writer rules:

1. Write the lowest compatible schema version unless a newer field is
   required by the producer.
2. Use deterministic rendering for manifests (sorted keys, stable
   numeric formatting, stable ordering of arrays where required).
3. Include explicit safety flags in every manifest.
4. Include explicit capability requirements in every deployment
   package.
5. Never emit forbidden-vocabulary tokens.

Deprecation policy:

- Each MAJOR bump must overlap with the previous MAJOR for at least
  two minor releases (deprecation window).
- The SDK must ship a compatibility-matrix test that runs both the
  previous-major and current-major shapes through the readers.
- Phase 1 fixtures must remain valid through the entire approved
  planning window. Breaking them is a release-blocking event.

## Sprint 41 MVP cut (exact list)

For Sprint 41 only, the SDK delivers:

1. Package skeleton (`aquaoptima_contracts/` under `src/`).
2. `ContractEnvelope` with all required fields.
3. `SchemaVersion` SemVer helper.
4. `SafetyFlagSet` with the canonical token list and unknown-flag
   rejection.
5. `CapabilityDeclaration` with deny-by-default semantics.
6. Deterministic JSON helper (sorted keys, fixed numeric format,
   stable arrays).
7. Golden fixture harness (read fixture, decode, re-encode, byte
   equality check).
8. Golden fixtures copied from `tests/fixtures/shadow_phase1/` into
   `aquaoptima_contracts/fixtures/phase1_shadow/`.
9. Negative tests:
   - missing safety flag → reject;
   - unknown safety flag → reject;
   - unknown required capability → reject;
   - any forbidden-vocabulary token in input → reject;
   - non-deterministic JSON output → fail.
10. No new APIs are introduced on the AI / Edge / Console side.
    Phase 1 imports continue to work unchanged.

See
[`docs/product/sprint41-shared-contracts-sdk-plan.md`](../product/sprint41-shared-contracts-sdk-plan.md)
for the corresponding implementation plan.

## Phase 2 first batch (Sprint 42) recap

Sprint 42 lifts the Phase 1 deterministic chain into SDK schemas
without changing AI / Edge runtime behavior. It must keep the Phase 1
end-to-end test passing and add an SDK-routed twin.

Sprint 42 contracts (minimum):

- `TelemetryTagMap`, `TelemetryTagSpec`, `CanonicalTelemetryTag`,
  `TelemetryTagMapDiagnostics`, `TelemetryAxis`, `UnitSpec`.
- `ShadowReplayDataset`, `ShadowReplayFrame`,
  `ShadowReplayDiagnostics`.
- `DPLCalibrationLossReport`, `DPLResidual`,
  `DPLCalibrationDiagnostics`, `CalibrationLossSummary`.
- `AdvisoryContract`, `AdvisoryRule`, `AdvisoryProposal`,
  `AdvisoryDecision`, `AdvisoryEvaluation`, `AdvisoryRejectionReason`.
- `ShadowRuntimeReport`, `ShadowRuntimeStepReport`,
  `ShadowRuntimeDiagnostics`.
- `ShadowDeploymentManifest`, `ShadowDeploymentArtifact`,
  `ShadowDeploymentPackageDiagnostics`.
- `EpanetImportQualityReport`.

All Sprint 42 contracts must round-trip the Phase 1 fixtures
byte-for-byte through the SDK deterministic writer.
