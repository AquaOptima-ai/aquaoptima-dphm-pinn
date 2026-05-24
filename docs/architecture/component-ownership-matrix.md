# Component Ownership Matrix

This document is the Sprint 40 ownership matrix for the AquaOptima 3+1
architecture: **Edge Runtime**, **AI / Optimization Server**,
**Operations Console**, and the **Shared Contracts / SDK** package. It
extends the higher-level
[`product-components-3-plus-1.md`](product-components-3-plus-1.md) and
[`shared-contracts-sdk.md`](shared-contracts-sdk.md) with concrete
**owns / does-not-own / inputs / outputs / allowed dependencies** rows
that Sprint 41+ planning and code review can use as a checklist.

The mandatory safety boundary is unchanged:

- No live OT binding.
- No PLC/PAC/SCADA write (required exact phrase: no PLC/PAC/SCADA write).
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated
  and approved.
- Future edge / PAC work begins mock, offline, simulated, dry-run,
  read-only, lab-only, and capability-gated.

## Headline ownership matrix

| Component | Deployable? | Owns (high level) | Allowed dependencies | Forbidden dependencies |
|---|---:|---|---|---|
| **Edge Runtime** | Yes | Local package validation, capability enforcement, offline/mock replay, advisory evaluation, shadow runtime, health/status/audit reports, deny-by-default mode. | Shared Contracts / SDK; OS / Python runtime; deterministic stdlib JSON. | AI / Optimization Server internals; Operations Console internals; live OT adapters; PLC/PAC/SCADA writers. |
| **AI / Optimization Server** | Yes | EPANET `.inp` ingestion, network model, dPHM/dPHM-PINN inference, optimization, calibration, retraining, model registry, deployment package generation, edge report ingestion, server APIs. | Shared Contracts / SDK; persistent storage chosen for registry/reports; GB10 compute libraries. | Edge Runtime internals; Operations Console internals; live OT adapters; direct command/setpoint emission to PLC/PAC/SCADA. |
| **Operations Console** | Yes | Dashboards, operator review workflows, package approval records, audit views, model comparison, safety visibility, explanation-only local LLM. | Shared Contracts / SDK; AI / Optimization Server public APIs; Edge Runtime read-only status APIs (where approved). | AI internals; Edge internals; OT adapters; setpoint/command emission; LLM tool-use against runtime APIs. |
| **Shared Contracts / SDK** | No | Versioned schemas, safety vocabulary, capability declarations, deployment manifests, API payloads, deterministic serialization helpers, validation helpers, golden fixtures, thin clients. | Python stdlib; deterministic JSON helpers; no runtime services. | Any runtime execution, model inference/training, optimization logic, UI rendering, database persistence, OT adapter behavior, command/write/setpoint payloads in current scope. |

## Edge Runtime

### Owns

- Edge process lifecycle (start, stop, supervise).
- Local telemetry ingestion adapters, initially **mock / file / replay
  only**.
- Local tag-map validation using SDK types.
- Replay frame construction and (later) mock live-read frame
  construction.
- Shadow runtime execution (offline / mock).
- Local advisory contract evaluation against hypothetical proposals.
- Local audit buffering.
- Deployment package download (over read-only API), unpacking, and
  validation.
- Capability gate enforcement (deny-by-default).
- Health, status, and read-only diagnostics reporting.

### Does not own

- dPHM / dPHM-PINN training.
- Model registry storage.
- Operator dashboards or review workflows.
- SDK schema definitions.
- Direct OT binding.
- PLC / PAC / SCADA writers.
- Command / setpoint / control emission of any kind.

### Inputs

- Approved deployment package (manifest + tag map + replay dataset +
  advisory contract + model metadata).
- Mock or file-based telemetry frames.
- SDK contract types.
- Operator-acknowledged safety flags carried by the deployment
  manifest.

### Outputs

- `EdgePackageValidationResult` (SDK type).
- `ShadowRuntimeReport` (SDK type, currently produced by the Phase 1
  shadow runtime).
- `EdgeHealthReport` / `EdgeStatusSnapshot` (SDK types).
- `EdgeAuditEvent` (SDK type).
- Read-only status responses on local edge APIs.

### Allowed dependencies

- Shared Contracts / SDK (Python import).
- Python stdlib only for deterministic serialization where applicable.
- A choice of mock adapter library at Sprint 46 time.

### Communication boundary

- The Edge Runtime communicates with the AI / Optimization Server only
  through **read-only fetches** (`GET /api/v1/deployment-packages/...`)
  and **report uploads** (`POST /api/v1/edge/reports/...`,
  `POST /api/v1/edge/health`, `POST /api/v1/edge/package-validation-results`).
- The Operations Console may call **read-only** edge status / health /
  capability endpoints where approved.
- The Edge Runtime exposes **no** `POST /command`, `POST /setpoint`,
  `POST /control`, `POST /actuate`, or equivalent endpoint.

## AI / Optimization Server

### Owns

- EPANET `.inp` loading and import-quality reporting.
- `Network` topology model construction.
- dPHM forward solve orchestration.
- dPHM-PINN inference and training.
- Calibration loss reports (e.g. `DPLCalibrationLossReport`).
- Optimization workloads.
- Model evaluation and model registry records.
- Advisory proposal generation (audit-only payloads).
- Deployment package generation.
- Edge report ingestion APIs and storage.
- Server APIs consumed by Edge Runtime and Operations Console.
- GB10 compute scheduling and worker services.

### Does not own

- Edge process lifecycle.
- Direct OT binding.
- Operator UI rendering.
- Human approval workflow state machines.
- Shared schema definitions.
- Edge-side safety enforcement (the AI Server can refuse to package
  unsafe artifacts; only the Edge Runtime enforces locally).
- Direct command / setpoint emission to PLC / PAC / SCADA.

### Inputs

- EPANET `.inp` files and JSON topology files.
- Telemetry replay datasets (offline files only in Phase 2).
- Operator notes from the Operations Console.
- Edge reports (`ShadowRuntimeReport`, `EdgeHealthReport`,
  `EdgePackageValidationResult`, `EdgeAuditEvent`).
- SDK contract types.

### Outputs

- `EpanetImportDiagnostics`, `EpanetImportQualityReport`.
- `DPLCalibrationLossReport`.
- `AdvisoryContract` (the typed rule set), `AdvisoryProposal`
  payloads (audit-only).
- `ModelArtifactRecord`, `ModelVersionRecord`, `ModelEvaluationRecord`,
  `ModelCompatibilityReport`.
- `DeploymentPackageManifest` (with safety declaration).
- API responses to Operations Console and Edge Runtime.

### Allowed dependencies

- Shared Contracts / SDK.
- Persistent storage chosen for registry / reports.
- GB10 compute libraries (PyTorch and similar).
- Existing Python codebase in `src/aquaoptima/dphm`, `src/aquaoptima/topology`,
  `src/aquaoptima/models`, `src/aquaoptima/training` (these become
  AI / Optimization Server internals over time).

### Communication boundary

- Exposes `GET /api/v1/models`, `GET /api/v1/deployment-packages/...`,
  `GET /api/v1/reports/shadow-runtime`, `POST /api/v1/edge/reports/...`,
  `POST /api/v1/operator/reviews` and similar.
- Does **not** expose any actuation, command, setpoint, or control
  endpoint.
- May not import Edge Runtime or Operations Console internals.

## Operations Console

### Owns

- Dashboard UI for packages, manifests, shadow reports, calibration
  reports, advisory evaluations, safety flags, edge validation
  results.
- Operator review and approval workflow state and records.
- Deployment package review workflow.
- Advisory review workflow.
- Shadow replay result visualization.
- Model comparison and calibration views.
- Safety boundary visibility (banners, badges, warning panels).
- Audit exploration views.
- User / session workflows for operators.
- Local LLM explanation-only interface and prompt scaffolding.

### Does not own

- Model training or inference internals.
- Optimization algorithms.
- Edge execution.
- OT adapters.
- Contract schema definitions.
- Setpoint or command emission.
- Authoritative safety decision computation (the SDK and Edge Runtime
  remain the source of truth).

### Inputs

- API responses from AI / Optimization Server.
- Read-only API responses from Edge Runtime (where approved).
- SDK contract types.
- Operator interactions (review, acknowledge, approve for
  shadow/review).

### Outputs

- `OperatorReviewRequest`, `OperatorReviewDecision`, `OperatorNote`,
  `DeploymentApprovalRecord`, `ReviewWorkflowEvent` (SDK types).
- UI screens and exported review/audit evidence.
- LLM-generated summaries / explanations labeled non-authoritative.

### Allowed dependencies

- Shared Contracts / SDK.
- AI / Optimization Server public APIs.
- Read-only Edge Runtime status endpoints where approved.
- A chosen local LLM runtime, sandboxed and tool-restricted.

### Communication boundary

- May call **read** AI Server APIs and **submit** operator review
  records.
- May call **read-only** Edge Runtime APIs where approved.
- May **not** call any AI Server "activate / deploy / dispatch"
  endpoint, because **no such endpoint exists in Phase 2**.
- May **not** call Edge Runtime command / setpoint / control
  endpoints, because **no such endpoint exists**.

### Local LLM boundary

The local LLM may:

- summarize manifests, reports, advisory evaluations, calibration
  reports, model comparisons;
- explain rejected packages;
- draft operator notes;
- answer documentation questions backed by repository content.

The local LLM may **not**:

- approve packages, modify manifests, change tag maps;
- call Edge Runtime APIs, AI Server activation APIs, or any mutation
  API;
- generate control commands, setpoints, or actuation payloads;
- suppress safety warnings or bypass capability gates;
- emit output that is treated as authoritative by any other
  component.

## Shared Contracts / SDK

### Owns

- Versioned schemas (telemetry, replay, dPL calibration, advisory,
  operator review, deployment manifest, edge capability, safety,
  model registry).
- Schema metadata envelope (family, name, version, SDK version,
  timestamps, provenance, correlation id).
- Safety flags and capability declarations.
- Deterministic JSON serialization helpers (sorted keys, stable
  numeric rendering, stable ordering of arrays where required).
- Validation helpers (e.g. unknown required capability rejection,
  unsafe-flag rejection).
- Golden fixtures, including Phase 1 shadow-mode artifacts.
- Thin clients for approved public APIs (initially Python).

### Does not own

- Runtime execution of any kind.
- Model inference / training / optimization.
- UI rendering.
- Database persistence policy.
- OT adapter behavior.
- Deployment orchestration.
- Command / write / setpoint payloads (for the current product
  scope).

### Inputs

- Phase 1 fixtures (preserved as golden files).
- Approved schema metadata and safety vocabulary.
- API payload shapes co-designed with AI Server, Edge Runtime, and
  Operations Console teams.

### Outputs

- A Python package (initially in-tree) importable by all three
  deployables.
- Generated JSON Schemas (`aquaoptima_contracts/jsonschema/generated/`).
- Golden fixtures usable as cross-component compatibility seeds.

### Allowed dependencies

- Python stdlib.
- A minimal validation library if and only if it does not introduce
  non-deterministic serialization. The default is to use stdlib
  `json` with a deterministic writer.

### Communication boundary

- The SDK is not a service. It has no HTTP surface.
- It exposes Python types and helpers only.

## Allowed dependency direction

```text
Edge Runtime ───────────────┐
                            │
AI / Optimization Server ───┼──→ Shared Contracts / SDK
                            │
Operations Console ─────────┘
```

Rules:

1. All deployables may depend on Shared Contracts / SDK.
2. No deployable may import another deployable's internals.
3. No shared business logic outside Shared Contracts / SDK.
4. The Edge Runtime may load approved artifacts produced by the AI
   Server but may not import AI Server internals.
5. The AI Server may target Edge package formats but may not import
   Edge Runtime internals.
6. The Operations Console may not import AI or Edge internals.
7. Shared schemas must not be forked into a deployable.
8. Safety flags and capability names must be explicit and centralized
   in the SDK.
9. No live OT adapter is a default dependency.
10. No command / write / setpoint contracts are part of the current
    product boundary.

## Edge / server / console communication boundaries

| From → To | Allowed | Method | Examples |
|---|---|---|---|
| Edge Runtime → AI Server | Yes | HTTPS, JSON payloads typed by SDK. | `POST /api/v1/edge/reports/shadow-runtime`, `POST /api/v1/edge/health`, `POST /api/v1/edge/package-validation-results`, `GET /api/v1/deployment-packages/{id}`. |
| AI Server → Edge Runtime | No direct invocation (no push) | Edge polls / fetches. | None defined. |
| Operations Console → AI Server | Yes | HTTPS, JSON. | `GET /api/v1/models`, `GET /api/v1/reports/shadow-runtime`, `GET /api/v1/deployment-packages`, `POST /api/v1/operator/reviews`. |
| Operations Console → Edge Runtime | Read-only only where approved. | HTTPS, JSON. | `GET /api/v1/edge/status`, `GET /api/v1/edge/health`, `GET /api/v1/edge/capabilities`. |
| AI Server → Operations Console | No direct invocation. | Console polls / fetches. | None defined. |
| Any component → SDK | Yes | In-process Python import. | `from aquaoptima_contracts.safety import SafetyFlagSet`. |
| SDK → Anything runtime | No | N/A. | N/A. |

Disallowed endpoints for the entire approved planning window:

- `POST /command`
- `POST /setpoint`
- `POST /control`
- `POST /actuate`
- `POST /write`
- `POST /dispatch`

These verbs must not appear in any deployable's HTTP surface, SDK
contract, or test code without an explicit, separately approved gate.

## Conformance checklist (Sprint 41+ code review)

A PR touching deployables or contracts must pass each of the following
items before merge:

1. Adds shared types only to the SDK.
2. Does not import another deployable's internals.
3. Includes safety flags on every emitted manifest / package.
4. Does not introduce command / write / setpoint vocabulary.
5. Does not introduce a live OT adapter dependency.
6. Adds a deny-by-default capability gate for any new capability.
7. Adds at least one negative test for unsafe inputs.
8. Updates the contract inventory if new contract types are added.
9. Updates the capability list if new capabilities are added.
10. Updates this matrix if the boundary changes.
