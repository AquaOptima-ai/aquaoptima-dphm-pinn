# AquaOptima 3+1 Product Component Architecture

## Recommendation and approval gate

AquaOptima dPHM-PINN should be organized as **three independently deployable product components plus one non-deployable Shared Contracts / SDK package**:

1. **Edge Runtime**
2. **AI / Optimization Server**
3. **Operations Console**
4. **Shared Contracts / SDK**

**Do not start Sprint 40 implementation until the user explicitly approves this replan.** Sprint 40 should remain a planning and acceptance sprint for confirming component ownership, dependency rules, contract boundaries, deployment topology, and safety gates.

The mandatory safety boundary for this architecture is:

- No live OT binding.
- No PLC / PAC / SCADA write.
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated and approved.
- Future edge/PAC work begins mock, simulated, offline, dry-run, read-only, and capability-gated.

## Context from Phase 1 and forward phase gates

Phase 1 validated a deterministic offline shadow-mode chain:

```text
Telemetry rows
→ TelemetryTagMap
→ ShadowReplayDataset
→ DPLCalibrationLossReport
→ AdvisoryContract
→ ShadowRuntimeReport
→ ShadowDeploymentManifest
```

That chain should be preserved as compatibility evidence and redistributed into explicit product boundaries. The Phase 1 safety guarantees remain required: offline/read-only execution, deterministic manifest rendering, no live OT binding, no setpoint output, no write path, and audit-only advisory behavior.

**Phase 2** should use the 3+1 architecture to build advisory/supervised-control product surfaces while preserving human review and offline or mocked execution gates first. It must not introduce a direct PLC/PAC/SCADA write path. **Phase 3** should use the same component split to qualify a PAC-like edge product with dry-run, mocked, read-only, and eventually explicitly approved supervised-write evidence. The architecture in this document is therefore a phase gate: it organizes Phase 2 and Phase 3 work, but it does not authorize live OT binding, command emission, or setpoint output.

## Component 1: Edge Runtime

### Purpose

The Edge Runtime is the plant-adjacent runtime for offline, mock,
dry-run, and read-only shadow behavior. For Sprint 45+ planning the
primary hardware target is the **Advantech AMAX-8580** class of PAC /
industrial controller: x86_64, CPU-first, CODESYS / industrial-protocol
capable, and deployed as an OT-side supervisory edge asset. It is
designed to coexist with existing site PLCs and pump-station PLCs;
those PLCs remain the direct VFD / pump / actuator authority.

### Owns

- Edge process lifecycle.
- AMAX-8580 / x86_64 PAC-class hardware capability validation.
- Local telemetry ingestion adapters, initially mock/file/replay only.
- Local tag-map validation using Shared Contracts / SDK types.
- Local replay or streaming frame construction.
- Shadow runtime execution.
- Local advisory safety evaluation.
- Local audit buffering.
- Deployment package unpacking and validation.
- Capability gate enforcement.
- Health/status reporting.
- Read-only diagnostics.

### Does not own

- dPHM/dPHM-PINN training.
- Model registry.
- Fleet-wide optimization.
- Operator dashboard or review workflow.
- Contract schema definitions.
- Direct write/control semantics.
- PLC/PAC/SCADA write adapters.
- Direct VFD / pump / actuator control.
- Site PLC interlock, permissive, trip, manual-mode, or emergency-stop
  authority.

### Initial modes

| Mode | Status | Meaning |
|---|---:|---|
| `offline_replay` | Allowed | Reads local fixture/replay files only. |
| `mock_live_read` | Allowed | Reads from a mock adapter shaped like live telemetry. |
| `advisory_audit_only` | Allowed | Evaluates hypothetical proposals for audit/review. |
| `package_validation_only` | Allowed | Validates package manifests and capabilities. |
| `dry_run_read_only` | Future gated | Reads from an approved source without commands or writes. |
| `control_enabled` | Not allowed | Would emit commands or setpoints; excluded from current architecture. |

### Primary Edge hardware target for Sprint 45+

The default Edge target is **AMAX-8580 / x86_64 / CPU-first**. The Edge
package validator must not assume CUDA, TensorRT, Jetson, Orin, ARM64,
or NVIDIA JetPack. CPU PyTorch is the default model runtime; ONNX
Runtime CPU or OpenVINO may be added later if benchmarks justify it.
TensorRT remains only an optional artifact format for a separate Orin
accelerator profile.

The AMAX Edge role is supervisory: package validation, local dPHM-PINN
inference, safety/capability gate checks, read-only telemetry handling,
audit buffering, and later bounded setpoint proposals only after an
explicit safety gate. The site PLC / pump-station PLC remains the
deterministic final authority for VFD and pump control.

## Component 2: AI / Optimization Server

### Purpose

The AI / Optimization Server is the GB10-hosted intelligence backend. It owns model intelligence, optimization, model lifecycle, deployment package generation, and server APIs.

### Owns

- dPHM forward model orchestration.
- dPHM-PINN inference.
- Optimization workloads.
- Model evaluation and calibration.
- Regular dPL/dPHM-PINN retraining workflows.
- Model registry and artifact metadata.
- Deployment package generation.
- Offline/shadow dataset ingestion.
- Import quality reports and calibration loss reports.
- Advisory proposal generation.
- GB10 compute scheduling and worker services.
- APIs for Edge Runtime and Operations Console.

### Does not own

- Edge process lifecycle.
- Direct OT binding.
- Operator UI rendering.
- Human approval workflow state.
- Shared schema definitions.
- Edge-side enforcement of safety gates.
- Direct command emission to PLC/PAC/SCADA.

## Component 3: Operations Console

### Purpose

The Operations Console is the GB10-hosted human interface. It owns operator review, dashboard, audit, deployment review, and explanation workflows. It is not the intelligence engine and not the edge runtime.

### Owns

- Dashboard UI.
- Operator review and approval records.
- Deployment package review workflow.
- Advisory review workflow.
- Shadow replay result visualization.
- Model comparison and calibration views.
- Safety boundary visibility.
- Audit exploration.
- User/session workflows.
- Local LLM explanation-only interface.

### Does not own

- Model training or inference internals.
- Optimization algorithms.
- Edge execution.
- OT adapters.
- Contract schema definitions.
- Setpoint or command emission.
- Safety decision computation as source of truth.

### Local LLM boundary

The local LLM may summarize reports, explain manifests, compare model evidence, draft operator notes, and answer documentation questions. It must not approve packages, modify manifests, call edge APIs, generate commands, generate setpoints for execution, suppress safety warnings, or bypass capability gates.

## Component 4: Shared Contracts / SDK

### Purpose

The Shared Contracts / SDK is a non-deployable package used by all three deployables. It is the sole owner of shared data shapes, safety vocabulary, manifests, API payloads, deterministic serialization helpers, versioning metadata, and thin clients.

### Owns

- Versioned schemas.
- Safety flags and capability gate vocabulary.
- Deployment and artifact manifests.
- API request/response payload types.
- Event envelope types.
- Serialization/deserialization helpers.
- Validation helpers.
- Contract fixtures and golden files.
- Thin clients for approved public APIs.

### Does not own

- Runtime execution.
- Model inference or training.
- Optimization logic.
- UI rendering.
- Database persistence policy.
- OT adapter behavior.
- Deployment orchestration.

## Deployment topology

```text
+---------------------------------------------------------------+
|                         GB10 Server                           |
|                                                               |
|  +-----------------------------+    +----------------------+  |
|  | AI / Optimization Server    |    | Operations Console   |  |
|  | - inference/optimization    |    | - dashboards         |  |
|  | - retraining                |    | - review workflows   |  |
|  | - model registry            |    | - audit views        |  |
|  | - package generation        |    | - local LLM assist   |  |
|  +-------------+---------------+    +----------+-----------+  |
|                |                               |              |
|                +-------------+-----------------+              |
|                              |                                |
|                    Shared Contracts / SDK                     |
+------------------------------|--------------------------------+
                               |
                               | packages, reports, health,
                               | read-only APIs, manifests
                               |
+------------------------------|--------------------------------+
|         Edge / AMAX-8580 Industrial Controller                 |
|                                                               |
|  +---------------------------------------------------------+  |
|  | Edge Runtime                                             |  |
|  | - mock/offline telemetry ingestion                      |  |
|  | - tag-map validation                                    |  |
|  | - shadow runtime                                        |  |
|  | - advisory safety evaluation                            |  |
|  | - package validation                                    |  |
|  | - capability gates                                      |  |
|  +---------------------------------------------------------+  |
|                                                               |
|  No live OT binding by default. No writes. No commands.       |
|  No setpoints.                                                |
+------------------------------|--------------------------------+
                               |
                               | read-only telemetry initially;
                               | bounded proposals only after
                               | explicit safety approval
                               |
+------------------------------|--------------------------------+
|              Site PLC / Pump Station PLC                      |
|  - VFD / pump / actuator control                              |
|  - interlocks, permissives, trips, fallback/manual mode        |
|  - final deterministic actuator authority                     |
+---------------------------------------------------------------+
```

## Dependency rules

Allowed dependency direction:

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
4. Edge may load approved artifacts but must not import AI Server internals.
5. AI Server may target edge package formats but must not import Edge Runtime implementation.
6. Operations Console must not import AI or Edge internals.
7. Shared schemas must not be forked.
8. Safety flags and capability names must be explicit and centralized.
9. No live OT adapter is a default dependency.
10. No command/write/setpoint contracts are part of the current product boundary.

## Phase 1 asset migration map

| Phase 1 asset | New owner / location |
|---|---|
| EPANET `.inp` loading | AI / Optimization Server |
| Network model | AI / Optimization Server, with contract projections as needed |
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

## Sprint 40 acceptance scope

Sprint 40 should produce and obtain approval for:

- 3+1 ownership matrix.
- Contract inventory.
- Capability model.
- Phase 1 API-to-component migration map.
- Initial package validation rules.
- Safety boundary documents.
- Dependency enforcement rules.
- Roadmap update for Sprints 41-70.

**Recommendation: do not start Sprint 40 implementation until the user approves this replan.** After approval, the first development sprint should be Sprint 41, focused on Shared Contracts / SDK safety and capability foundations.