# AquaOptima 3+1 Planning Report

## Executive recommendation

AquaOptima dPHM-PINN should be packaged as **three independently deployable product components plus one Shared Contracts / SDK package**:

1. **Edge Runtime** — plant-adjacent, mock/offline/read-only shadow runtime and safety-gated package validator.
2. **AI / Optimization Server** — GB10-hosted dPHM/dPHM-PINN inference, optimization, retraining, model registry, and package generator.
3. **Operations Console** — GB10-hosted dashboards, operator review workflows, audit views, deployment package review, and explanation-only local LLM interface.
4. **Shared Contracts / SDK** — non-deployable schemas, manifests, safety vocabulary, capability gates, API payloads, deterministic serialization, fixtures, and thin clients.

**Do not start Sprint 40 implementation until the user explicitly approves this replan.** Sprint 40 should be a planning and acceptance sprint for architecture boundaries, dependency rules, safety gates, contract inventory, package validation rules, and the revised Sprint 41-70 sequence.

## Non-negotiable safety boundary

The architecture and roadmap preserve the Phase 1 safety posture:

- No live OT binding.
- No PLC / PAC / SCADA write.
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated and approved.
- Future PAC/edge work begins mock, offline, simulated, dry-run, read-only, lab-only, and capability-gated.

Advisory proposals remain audit/review payloads. Operator approval authorizes review or shadow package distribution only; it is not actuation authority.

## Documents created by this planning task

- `docs/architecture/product-components-3-plus-1.md`
- `docs/architecture/shared-contracts-sdk.md`
- `docs/safety/component-boundaries-and-qualification-gates.md`
- `docs/product/phase2-phase3-3plus1-roadmap.md`
- `PLANNING_3PLUS1_REPORT.md`

## Architecture summary

### Edge Runtime

Owns:

- Local package validation.
- Capability enforcement.
- Offline replay and mock read execution.
- Local advisory safety evaluation.
- Shadow runtime reports.
- Health/status/audit reporting.

Does not own:

- Model training.
- Model registry.
- Operator UI.
- Shared schema definitions.
- PLC/PAC/SCADA writes.
- Commands or setpoints.

### AI / Optimization Server

Owns:

- dPHM/dPHM-PINN inference.
- Optimization.
- Model calibration and evaluation.
- dPL/dPHM-PINN retraining.
- Model registry.
- Deployment package generation.
- Edge report ingestion.
- Server APIs.

Does not own:

- Edge process lifecycle.
- Direct OT binding.
- Human UI rendering.
- Edge-side safety enforcement.
- Command emission.

### Operations Console

Owns:

- Dashboards.
- Operator review workflows.
- Deployment package review.
- Advisory review.
- Audit views.
- Model comparison views.
- Safety boundary visibility.
- Explanation-only local LLM assistance.

Does not own:

- Training or inference internals.
- Edge execution.
- OT adapters.
- Contract definitions.
- Setpoint or command emission.

### Shared Contracts / SDK

Owns:

- Versioned schemas.
- Safety flags and capability vocabulary.
- Deployment manifests.
- API payload types.
- Event envelopes.
- Deterministic serialization.
- Validation helpers.
- Golden fixtures.
- Thin clients for public APIs.

Does not own:

- Runtime execution.
- Model inference/training.
- Optimization logic.
- UI rendering.
- Database persistence.
- OT adapter behavior.

## Phase 1 chain preservation

The validated Phase 1 deterministic chain remains the seed for the product architecture:

```text
Telemetry rows
→ TelemetryTagMap
→ ShadowReplayDataset
→ DPLCalibrationLossReport
→ AdvisoryContract
→ ShadowRuntimeReport
→ ShadowDeploymentManifest
```

Mapping:

| Phase 1 asset | New owner / location |
|---|---|
| EPANET `.inp` loading | AI / Optimization Server |
| Network model | AI / Optimization Server |
| `EpanetImportDiagnostics` | Shared Contracts / SDK schema; AI producer; Console viewer |
| `EpanetImportQualityReport` | Shared Contracts / SDK schema; AI producer; Console viewer |
| `TelemetryTagMap` | Shared Contracts / SDK schema; Console configuration; Edge consumer |
| `ShadowReplayDataset` | Shared Contracts / SDK schema; AI and Edge consumer |
| `DPLCalibrationLossReport` | Shared Contracts / SDK schema; AI producer; Console viewer |
| `AdvisoryContract` | Shared Contracts / SDK schema; Console workflow; Edge enforcer |
| `AdvisoryProposal` | Shared Contracts / SDK schema; AI producer; Edge evaluator |
| `ShadowRuntimeReport` | Shared Contracts / SDK schema; Edge producer; AI/Console consumer |
| `ShadowDeploymentManifest` | Shared Contracts / SDK schema; AI producer; Edge validator |
| Safety flags | Shared Contracts / SDK vocabulary; enforced everywhere |

## Dependency rule

Allowed dependency direction:

```text
Edge Runtime ───────────────┐
                            │
AI / Optimization Server ───┼──→ Shared Contracts / SDK
                            │
Operations Console ─────────┘
```

No deployable may import another deployable's internals. GB10 co-location of AI Server and Operations Console is a deployment choice, not a license to share internals or database tables as integration contracts.

## Revised sprint recommendation

### Sprint 40

Planning and approval only:

- 3+1 ownership matrix.
- Contract inventory.
- Capability model.
- Phase 1 API-to-component migration map.
- Safety boundary documentation.
- Package validation rules.
- Dependency enforcement rules.
- Revised Sprint 41-70 roadmap.

### Sprint 41

First implementation sprint after approval:

- Shared Contracts / SDK skeleton.
- Schema metadata.
- `SafetyFlagSet`.
- `CapabilityDeclaration`.
- Deterministic JSON helpers.
- Golden file harness.
- Negative tests for missing safety flags and unsafe vocabulary.

### Sprints 42-51

Phase 2 advisory/supervised-review product:

- SDK first contract set.
- AI Server package generation and report APIs.
- Edge Runtime package validation and offline shadow replay.
- Operations Console dashboards and operator review workflows.
- End-to-end shadow package/replay/report/audit flow.
- No live OT binding, writes, commands, or setpoints.

### Sprints 52-70

Phase 3 PAC-like edge preparation:

- Lab branch only.
- Read-only/mocked PAC-like interfaces.
- Watchdog and safe-state prototypes.
- Model registry, retraining, advisory batch generation.
- Fault injection and qualification evidence.
- LLM explanation-only assistant.
- Safe read-only improvements may later merge; write/control remains prohibited without separate gates.

## Open decisions

- Repository strategy: monorepo with strict packages is recommended initially.
- API protocol: REST/JSON is recommended first; event streaming can wait.
- Edge package format: zip/tar/OCI/signing approach remains to be chosen.
- Artifact trust: hashes versus cryptographic signatures remains open.
- Model execution location: GB10 should own heavy inference initially.
- Console backend boundary: a separate Console backend is recommended for workflow/session/LLM isolation.
- Local LLM selection and audit policy remain open.
- Contract semver and deprecation windows require approval.
- Fleet model: one edge per GB10 versus multiple edges remains open.
- Future OT adapter qualification path must be defined before live binding is designed.

## Main risks

- Boundary erosion between deployables.
- Safety vocabulary duplication.
- Premature live OT integration.
- Console becoming a control plane.
- LLM overreach.
- Weak artifact provenance.
- Edge activation of incompatible packages.
- GB10 co-location hiding coupling.
- Insufficient cross-component contract tests.
- Undefined artifact ownership.

## Final recommendation

Approve the 3+1 architecture before implementation. Keep Sprint 40 as a planning and acceptance sprint. Start development only after the user approves the replan, beginning with Sprint 41 Shared Contracts / SDK safety and capability foundations. Preserve Phase 1 deterministic evidence while moving toward independently deployable Edge, AI, and Operations components governed by Shared Contracts / SDK and explicit safety gates.