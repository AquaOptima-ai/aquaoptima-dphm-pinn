# Phase 2 and Phase 3 3+1 Roadmap

## Recommendation and approval gate

This roadmap reorganizes Phase 2 and Phase 3 around the AquaOptima 3+1 architecture:

- **SDK**: Shared Contracts / SDK
- **EDGE**: Edge Runtime
- **AI**: AI / Optimization Server
- **OPS**: Operations Console

**Do not start Sprint 40 implementation until the user explicitly approves this replan.** Sprint 40 should remain a planning and acceptance sprint. The first development sprint should be Sprint 41, focused on Shared Contracts / SDK safety and capability foundations.

Mandatory safety boundary for every sprint:

- No live OT binding.
- No PLC / PAC / SCADA write.
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated and approved.
- Future edge/PAC work begins mock, offline, simulated, dry-run, read-only, lab-only, and capability-gated.

## Module labels and ownership

| Label | Module | Deployable? | Primary owner | Responsibility boundary |
|---|---|---:|---|---|
| **SDK** | Shared Contracts / SDK | No | Architecture / platform | Versioned schemas, manifests, safety vocabulary, capability gates, API payloads, deterministic serialization, fixtures, thin clients. |
| **EDGE** | Edge Runtime | Yes | Edge / runtime team | Offline/mock/read-only edge execution, package validation, local capability enforcement, shadow replay, advisory evaluation, health/status, audit buffering. |
| **AI** | AI / Optimization Server | Yes | AI / platform team | dPHM/dPHM-PINN inference, optimization, calibration, retraining, model registry, deployment package generation, server APIs, report ingestion. |
| **OPS** | Operations Console | Yes | Product / UI workflow team | Dashboards, operator review, package approval records, audit views, model comparison, safety visibility, local LLM explanation-only workflows. |

Cross-cutting rules:

1. All shared payloads belong to SDK.
2. No deployable imports another deployable's internals.
3. No Phase 2 or Phase 3 sprint introduces write/control/setpoint behavior.
4. Advisory proposals remain audit/review payloads, not commands.
5. GB10 co-location does not imply shared internals.

## Revised Sprint 40-51 Phase 2 sequence

Phase 2 goal: auditable advisory / supervised-review product shape on GB10 + edge runtime, still offline/mock/read-only only.

| Sprint | Primary module | Expected deliverable / API | Safety gate |
|---:|---|---|---|
| **40** | SDK / Architecture | Planning sprint: 3+1 ownership matrix, contract inventory, capability model, Phase 1 API-to-component migration map, safety boundary docs, package validation rules. | No implementation starts until dependency rules, safety boundary, and module ownership are approved by the user. |
| **41** | SDK | `aquaoptima-contracts-sdk` skeleton; schema metadata; `SafetyFlagSet`; `CapabilityDeclaration`; deterministic JSON helpers; golden test harness. | Missing safety flags fail validation; no command/write/setpoint vocabulary allowed. |
| **42** | SDK | First contract set: `TelemetryTagMap`, `ShadowReplayDataset`, `AdvisoryContract`, `AdvisoryProposal`, `ShadowRuntimeReport`, `DeploymentPackageManifest`, `ModelArtifactRecord`. | Golden files prove deterministic serialization and Phase 1 fixture compatibility. |
| **43** | AI | AI Server foundation: topology/import service boundary, calibration report producer, model artifact metadata API: `GET /api/v1/models`, `GET /api/v1/calibration-reports/{id}`. | AI produces reports only; no edge control or OT binding APIs. |
| **44** | AI | Deployment package generation service: `POST /api/v1/deployment-packages`, `GET /api/v1/deployment-packages/{id}/manifest`; package contains manifest, tag map, advisory contract, model metadata. | AI refuses packages requiring write/control/live OT/setpoint capabilities. |
| **45** | EDGE | Edge package validation CLI/service: validate manifest, checksums, schema versions, safety flags, capabilities; produce `EdgePackageValidationResult`. | Unsafe, missing, unknown, or unsupported capabilities are rejected before activation. |
| **46** | EDGE | Offline shadow replay runner: consumes package + replay dataset, evaluates advisory contract, emits `ShadowRuntimeReport`. | Runtime modes limited to `offline_replay`, `mock_live_read`, `advisory_audit_only`; no live adapters. |
| **47** | AI | Edge report ingestion APIs: `POST /api/v1/edge/reports/shadow-runtime`, `POST /api/v1/edge/health`, `POST /api/v1/edge/package-validation-results`. | Server treats reports as audit evidence only; no automatic deployment or actuation. |
| **48** | OPS | Console dashboards for packages, manifests, shadow reports, calibration reports, safety flags, edge validation results. | UI language restricted to review, acknowledge, approve package for shadow deployment; no execute/apply/send command. |
| **49** | OPS | Operator review workflow: `POST /api/v1/operator/reviews`; approval record includes actor, artifact IDs, safety acknowledgement, decision, timestamp. | Approval authorizes package distribution/review only, not actuation. |
| **50** | AI / EDGE / OPS | End-to-end Phase 2 flow: AI builds package -> OPS reviews -> EDGE downloads/validates -> EDGE runs shadow replay -> AI ingests report -> OPS displays evidence. | Contract test proves no deployable imports another's internals; no control endpoints exist. |
| **51** | All | Phase 2 hardening/release candidate: compatibility matrix, negative tests, audit event envelope, docs, deployment runbook, release checklist. | Release gate: no live OT binding, no PLC/PAC/SCADA writes, no setpoints, no command verbs, all unsafe packages rejected. |

## Revised Sprint 52-70 Phase 3 / PAC-edge sequence

Phase 3 goal: qualified PAC-like edge preparation through lab-only, read-only, capability-gated work. This is not permission to implement control.

| Sprint | Primary module | Expected deliverable / API | Safety gate |
|---:|---|---|---|
| **52** | EDGE / Safety | Create `lab/pac-edge-qualification` branch; qualification plan, hazard checklist, read-only lab scope, merge policy. | PAC work isolated from main; no live site connection or write adapter. |
| **53** | SDK | Extended edge contracts: `EdgeHealthReport`, `EdgeStatusSnapshot`, `EdgeCapabilityDeclaration`, `EdgeAuditEvent`, fault/audit event envelope. | Dangerous capabilities remain forbidden by default and machine-readable. |
| **54** | EDGE | Edge watchdog and safe-state prototype in lab: process health, stale-data detection, package rollback marker, audit events. | Watchdog cannot trigger commands; only reports, disables local shadow run, or rejects package. |
| **55** | EDGE | Mock PAC/read-only adapter interface using simulated data; `GET /status`, `GET /health`, `GET /capabilities`, `GET /active-package`. | Adapter is mock/read-only only; no `POST /command`, `/setpoint`, `/control`, or equivalent. |
| **56** | EDGE / SDK | Package validation hardening: provenance fields, checksum coverage, optional signature hook, corrupt package tests. | Edge rejects unknown major schemas, bad checksums, missing provenance, unsafe capability declarations. |
| **57** | AI | Model registry lifecycle: model version records, evaluation records, compatibility report API: `GET /api/v1/models/{id}/compatibility`. | Registry metadata does not imply deployment approval or edge activation. |
| **58** | AI | Retraining pipeline design and job records: dataset refs, training config refs, output model artifact refs, evaluation refs. | Retraining runs offline/GB10 only; cannot push directly to edge. |
| **59** | AI | dPL/dPHM-PINN retraining job implementation for offline datasets: `POST /api/v1/retraining-jobs`, `GET /api/v1/retraining-jobs/{id}`. | New model must pass evaluation and package safety gates before becoming deployable. |
| **60** | OPS | Model comparison and retraining review views: lineage, metrics, calibration loss, compatibility, operator notes. | Console may approve model/package review only; no model can be executed from UI. |
| **61** | AI | Batch optimization/advisory proposal generation API: `POST /api/v1/advisory-proposal-batches`; outputs audit-only `AdvisoryProposal` records. | Advisory proposals are explicitly non-command payloads and cannot be routed to actuation. |
| **62** | EDGE | Advisory evaluation determinism/performance tests on lab edge; replay benchmark; rejection reason coverage. | Accepted advisory means accepted for audit/review, not execution. |
| **63** | EDGE | Lab simulator and fault-injection harness: stale telemetry, unit mismatch, wrong tag map, network loss, corrupt package, replay/live confusion. | Faults fail closed: reject package, skip evaluation, or report violation. |
| **64** | AI / SDK | Package provenance/signing integration; artifact hash registry; package build reproducibility checks. | Edge activates only packages with valid integrity evidence and approved safety flags. |
| **65** | EDGE | Read-only edge status API hardening and endpoint scan tests. | Automated test fails build if command/write/setpoint endpoint or token appears. |
| **66** | OPS | Local LLM assistant MVP for explanation-only summaries of manifests, reports, model comparisons, and rejected packages. | LLM has no tool access to activation, mutation, edge APIs, or control-like functions; outputs labeled non-authoritative. |
| **67** | AI / OPS | Multi-edge/fleet read-only metadata: edge registry, package compatibility by edge capability, status aggregation. | Fleet management cannot remotely command edge; only package eligibility and report visibility. |
| **68** | EDGE / Safety | Site acceptance test template and qualification evidence pack: hazard traceability, rollback, audit replay, failure-mode evidence. | Documented as lab/read-only qualification evidence, not live deployment approval. |
| **69** | All | Integrated PAC-edge lab rehearsal: package build, review, validation, mock read-only run, report upload, console audit, retraining comparison. | Independent safety review confirms no write/control path and no PAC lab code merged unsafely. |
| **70** | All | Phase 3 readiness decision: promote safe read-only improvements to main, keep unsafe/lab-only work isolated, define next qualification scope. | Merge only read-only, tested, capability-gated code; control/write remains prohibited without separate approval gates. |

## Retraining placement

Regular dPL / dPHM-PINN retraining belongs in the **AI / Optimization Server** module, beginning as design work in Sprint 58 and implementation work in Sprint 59 after model registry and package compatibility foundations exist.

Reasons:

1. Retraining is GB10/server-side compute, not edge runtime behavior.
2. Training datasets, model versions, calibration loss reports, evaluation records, and registry metadata are AI responsibilities.
3. A newly trained model must not become active at the edge automatically.
4. Retraining jobs need dataset references, config references, artifact checksums, metrics, provenance, and reviewer evidence.
5. Edge Runtime consumes approved deployment packages only; it does not train, select, or promote models.
6. Operations Console displays retraining results and review workflows but does not run training.
7. SDK defines retraining payloads and model metadata but contains no training logic.

## First development sprint after approval

Recommended first development sprint: **Sprint 41 — Shared Contracts / SDK safety and capability foundation**.

Sprint 41 scope:

- Create `aquaoptima-contracts-sdk` package.
- Implement schema metadata base class/envelope.
- Implement `SafetyFlagSet`.
- Implement `CapabilityDeclaration`.
- Implement deterministic JSON serialization.
- Add golden file tests.
- Add negative tests for missing safety flags, unsupported capabilities, and command/write/setpoint vocabulary.
- Import Phase 1 fixtures as compatibility seeds.

Sprint 41 acceptance gate:

> SDK can represent the Phase 1 safety boundary deterministically, and every deployable can depend on it without importing another deployable's internals.

## Plane update plan

Change in active roadmap:

1. Replace monolithic Phase 2/3 planning with SDK, EDGE, AI, and OPS labels.
2. Add module owner, deployable boundary, expected API/contract, and safety gate to every sprint record.
3. Mark Sprint 40 as planning/architecture acceptance, not feature implementation.
4. Sequence SDK contracts before AI package generation, Edge validation, and Console workflows.
5. Move model intelligence, registry, optimization, and retraining under AI.
6. Move package validation, shadow replay, local advisory evaluation, status, and capability enforcement under EDGE.
7. Move dashboards, review records, approval records, audit views, and LLM explanation workflows under OPS.
8. Move schemas, manifests, safety flags, capability declarations, and API payload types under SDK.
9. Add explicit no-live-OT/no-write/no-control/no-setpoint safety gates to every sprint.
10. Split Phase 3 PAC-edge work into a lab qualification path with merge restrictions.

Preserve as historical records:

- Phase 1 deterministic chain.
- Phase 1 fixtures as SDK golden files and cross-component contract tests.
- Historical sprint plans as superseded baselines.
- Prior architecture decisions with accepted/superseded/deferred/rejected labels.
- Safety decisions and rationale.
- Existing calibration reports, manifests, diagnostics, and shadow runtime reports.
- Test evidence proving deterministic manifest rendering and offline/read-only behavior.
- Old API names in migration notes mapped to new owning modules.
- PAC-edge exploratory records as lab evidence, not production commitments.