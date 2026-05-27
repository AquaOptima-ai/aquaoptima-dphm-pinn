# Phase 1 API → Component Ownership Map

This document maps the Phase 1 (Sprints 1–39 plus the Phase 1 shadow-
mode end-to-end validation) public surface to its **future home in the
3+1 architecture**. It is part of the Sprint 40 approval gate and is
intended to make Sprint 41 implementation safe: every reviewer can see
exactly where each Phase 1 surface is supposed to live, who produces
it, who consumes it, and whether its public name moves.

Safety boundary (unchanged):

- No live OT binding.
- No PLC/PAC/SCADA write (required exact phrase: no PLC/PAC/SCADA write).
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated
  and approved.

## How to read this map

Each row identifies:

- **Phase 1 surface** — the existing public symbol, file, or document.
- **SDK schema** — whether the type moves into the Shared Contracts /
  SDK schema layer (yes / no / partial).
- **Producer** — which Phase 2 component generates instances.
- **Consumer** — which Phase 2 components read instances.
- **Sprint 41 action** — what (if anything) happens to this surface in
  Sprint 41.
- **Later sprint action** — when the surface is fully relocated.

Sprint 41 itself does not rename or move any existing `aquaoptima.dphm`
import path. Phase 1 fixtures and APIs continue to work unchanged.
Sprint 41 only adds the SDK skeleton, schema metadata envelope,
`SafetyFlagSet`, `CapabilityDeclaration`, deterministic JSON helpers,
golden fixtures, and negative tests.

## Topology and import surfaces

| Phase 1 surface | SDK schema | Producer | Consumer | Sprint 41 action | Later sprint action |
|---|---|---|---|---|---|
| EPANET `.inp` loading (`load_network_from_inp`, fallback parser, WNTR parser) | No (runtime logic) | AI / Optimization Server | AI (input to network model) | None. | Sprint 43 surfaces as AI Server boundary; no rename. |
| `Network` dataclass (`aquaoptima.dphm.Network`) | No (runtime) | AI / Optimization Server | AI internal | None. | Sprint 43 wraps with an `AI` service boundary; the dataclass stays. |
| `EpanetImportDiagnostics` (Sprints 23–32) | Partial — schema projection in SDK | AI (producer) | Operations Console (viewer), Edge (informational) | None. | Sprint 42 adds an SDK projection (`EpanetImportDiagnosticsRecord`) carrying only fields needed by Console / Edge. |
| `EpanetImportQualityReport` (Sprint 33) | Yes — SDK schema | AI (producer) | Operations Console (viewer) | None. | Sprint 42 adds SDK schema with metadata envelope; AI Server begins emitting through SDK in Sprint 43. |
| Topology JSON loader (Sprint 8) | Partial | AI (producer) | AI internal | None. | Sprint 43 stays as AI Server input adapter. |

## Telemetry and replay surfaces

| Phase 1 surface | SDK schema | Producer | Consumer | Sprint 41 action | Later sprint action |
|---|---|---|---|---|---|
| `SiteTagMap`, `TagDefinition`, `SourceType`, `TagKind` (`aquaoptima.dataio`) | No (runtime metadata layer, pre-Phase 1 wider abstraction) | AI / Edge (configuration) | AI internal | None. | Stays as runtime layer; SDK does **not** absorb it. |
| `TelemetrySeries`, `WindowDataset`, `QualityFlag`, `is_usable` | No | AI internal | AI internal | None. | Stays under AI / Optimization Server (training data plane). |
| `TelemetryTagMap` (Sprint 34, `aquaoptima.dphm.telemetry_tag_map`) | Yes — SDK schema | Operations Console (configuration), AI (validation) | Edge Runtime (validation, consumer at replay time) | None. | Sprint 42 adds `TelemetryTagMap` as an SDK schema with metadata envelope. AI / Edge / Console import through SDK starting Sprint 43–46. |
| `ShadowReplayDataset`, `ShadowReplayFrame`, `ShadowReplayDiagnostics`, `load_shadow_replay_csv` (Sprint 35) | Yes — SDK schema | AI (produces canonical dataset from offline rows), Edge (also can build from local replay rows during Phase 2) | AI (calibration), Edge (shadow runtime), Console (visualization) | None. | Sprint 42 adds `ShadowReplayDataset` as an SDK schema. Sprint 46 has Edge Runtime consume through SDK. |

## dPL / calibration / advisory surfaces

| Phase 1 surface | SDK schema | Producer | Consumer | Sprint 41 action | Later sprint action |
|---|---|---|---|---|---|
| `DPLCalibrationLossReport`, `DPLResidual`, `DPLCalibrationDiagnostics`, `build_dpl_calibration_loss_report` (Sprint 36) | Yes — SDK schema (report only; the builder stays in AI) | AI / Optimization Server | Operations Console (viewer), AI (retraining input) | None. | Sprint 42 adds the report schema in SDK. Sprint 43 has AI Server emit through SDK. The builder remains an AI module. |
| `AdvisoryContract`, `AdvisoryRule`, `AdvisoryProposal`, `AdvisoryDecision`, `evaluate_advisory_proposals`, `build_advisory_contract`, advisory axis tokens (Sprint 37) | Yes — SDK schema | AI / Optimization Server (proposals + contract). Console may also configure / approve contracts. | Edge Runtime (evaluator), Console (workflow). | None. Phase 1 imports preserved. | Sprint 42 adds `AdvisoryContract`, `AdvisoryRule`, `AdvisoryProposal`, `AdvisoryDecision`, `AdvisoryRejectionReason` schemas to SDK. The evaluator (`evaluate_advisory_proposals`) is a candidate to migrate to Edge in Sprint 46; the AI may still run it for offline audit. |
| Advisory axis tokens (`ADVISORY_AXIS_*`) and decision status tokens (`ADVISORY_STATUS_*`) | Yes — SDK vocabulary | SDK (single source) | All components | None. | Sprint 42 moves the canonical strings into the SDK; AI / Edge re-export for backward compatibility. |

## Shadow runtime and packaging surfaces

| Phase 1 surface | SDK schema | Producer | Consumer | Sprint 41 action | Later sprint action |
|---|---|---|---|---|---|
| `ShadowRuntimeReport`, `ShadowRuntimeStepReport`, `ShadowRuntimeDiagnostics`, `run_shadow_runtime` (Sprint 38) | Yes — SDK schema for the report; runtime logic stays in Edge Runtime | Edge Runtime (real producer at Phase 2). AI may also call the runner during offline replay / qualification. | AI Server (report ingestion), Operations Console (viewer). | None. | Sprint 42 adds `ShadowRuntimeReport` schema to SDK. Sprint 46 has Edge Runtime emit through SDK. Sprint 47 has AI ingest. |
| `ShadowDeploymentManifest`, `ShadowDeploymentArtifact`, `ShadowDeploymentPackageDiagnostics`, artifact-kind tokens, `build_shadow_deployment_manifest`, `write_shadow_deployment_manifest_json` (Sprint 39) | Yes — SDK schema and deterministic writer | AI / Optimization Server (package generator) | Edge Runtime (validator), Console (review) | None. | Sprint 42 adds the manifest schema in SDK and a deterministic JSON writer. Sprint 44 has AI Server emit through SDK. Sprint 45 has Edge validate through SDK. |
| `ARTIFACT_KIND_*` constants | Yes — SDK vocabulary | SDK (single source) | All components | None. | Sprint 42 moves to SDK. |
| `SAFETY_BOUNDARY_PHRASES` (any safety flag / phrase constants used in Phase 1 manifests) | Yes — SDK vocabulary | SDK (single source) | All components | None. | Sprint 41 introduces `SafetyFlagSet` and a canonical phrase list. Phase 1 phrases are imported as golden fixtures. |

## Edge / capability surfaces (new in Phase 2)

There are no Phase 1 surfaces here yet. The table below names what
Sprint 41+ will add and ties each new contract to its Phase 1 seed.

| New contract | SDK schema | Producer | Consumer | Seed in Phase 1 |
|---|---|---|---|---|
| `SafetyFlagSet` | Yes — SDK | All deployables declare; SDK validates. | All deployables consume. | Phase 1 manifest `safety_flags` and `SAFETY_BOUNDARY_PHRASES`. |
| `CapabilityDeclaration` | Yes — SDK | Edge Runtime advertises; deployment packages declare requirements. | Edge Runtime enforces; AI refuses unsafe packages. | Phase 1 `AdvisoryContract` deny-list; runtime mode tokens in shadow runtime. |
| `CapabilityRequirement` | Yes — SDK | AI Server (in package manifest) | Edge Runtime (validator) | Phase 1 manifest references. |
| `EdgePackageValidationResult` | Yes — SDK | Edge Runtime | AI Server (audit), Console (visibility) | New in Sprint 45. |
| `EdgeHealthReport`, `EdgeStatusSnapshot`, `EdgeAuditEvent` | Yes — SDK | Edge Runtime | AI / Console | New in Sprint 47 / 53. |
| `ContractEnvelope` (schema metadata wrapper) | Yes — SDK | SDK helper; every emitting component | Every consuming component | Phase 1 manifests carry implicit identifying fields; Sprint 41 makes them explicit. |
| `SchemaVersion` | Yes — SDK | SDK | All components | Implicit in Phase 1 (no version field today); Sprint 41 introduces explicit versioning. |

## Operator / review surfaces

There are no Phase 1 surfaces here; Phase 1 has no operator workflow.
Sprint 41 does not implement any of these. They appear later:

| New contract | Sprint introduced | Notes |
|---|---:|---|
| `OperatorReviewRequest` | 49 | Authored in SDK, used by Console workflows. |
| `OperatorReviewDecision` | 49 | Records decision (review accepted, rejected, deferred). |
| `OperatorNote` | 49 | Free-text or structured note, audit-only. |
| `DeploymentApprovalRecord` | 49 | Approval authorizes package distribution / review only, never actuation. |
| `ReviewWorkflowEvent` | 49 | Immutable audit envelope around operator actions. |

## Documentation map

Existing Phase 1 docs and their post-Sprint-40 reading order:

| Phase 1 doc | New home / treatment |
|---|---|
| `docs/architecture.md` | Stays as historical AI-internal module map. Cross-link from `docs/architecture/component-ownership-matrix.md`. |
| `docs/telemetry-abstraction.md` | Stays. Belongs to AI / Optimization Server (training data plane). |
| `docs/telemetry-tag-map.md` | Stays. SDK schema for `TelemetryTagMap` will reference this doc. |
| `docs/shadow-replay.md` | Stays. SDK schema for `ShadowReplayDataset` will reference this doc. |
| `docs/dpl-calibration.md` | Stays. SDK schema for the calibration loss report references this. |
| `docs/advisory-contract.md` | Stays. SDK schema for advisory types references this; Edge and Console consume. |
| `docs/shadow-runtime.md` | Stays. Becomes the Edge Runtime offline / mock shadow execution reference. |
| `docs/shadow-deployment.md` | Stays. Becomes the AI Server deployment package generation reference. |
| `docs/epanet-inp-import.md` | Stays. AI / Optimization Server input adapter reference. |
| `docs/topology-json-schema.md` | Stays. AI input format reference. |
| `docs/safety-boundary.md` | Stays. Reaffirmed by `docs/safety/component-boundaries-and-qualification-gates.md` and `docs/safety/capability-model-and-safety-gates.md`. |
| `docs/units-and-sign-conventions.md` | Stays. Cross-cutting; SDK telemetry contracts reference this. |
| `docs/testing-strategy.md` | Stays. SDK adds compatibility / golden-file rules referencing this. |
| `docs/validation/phase1-shadow-mode-e2e.md` | Stays. Becomes the SDK compatibility seed evidence. |
| `docs/sprint-roadmap.md` | Stays as historical record. Superseded forward by `docs/product/phase2-phase3-3plus1-roadmap.md`. |

## Test surface map

| Phase 1 test surface | Stays / moves | Notes |
|---|---|---|
| `tests/dphm/*` | Stays under AI / Optimization Server domain. | No rename in Sprint 41. |
| `tests/models/*` | Stays under AI / Optimization Server domain. | No rename in Sprint 41. |
| `tests/training/*` | Stays under AI / Optimization Server domain. | No rename in Sprint 41. |
| `tests/dataio/*` | Stays under AI / Optimization Server domain (training data plane). | No rename in Sprint 41. |
| `tests/topology/*` | Stays under AI / Optimization Server domain. | No rename in Sprint 41. |
| `tests/e2e/test_phase1_shadow_mode_pipeline.py` | Stays. Becomes the SDK compatibility seed; Sprint 42+ adds an SDK-routed twin that exercises the contracts after the SDK absorbs the shapes. | Must continue to pass for the entire planning window. |
| `tests/fixtures/shadow_phase1/*` | Migrates by **copy** to `aquaoptima_contracts/fixtures/phase1_shadow/` in Sprint 41. Phase 1 fixture location stays for back-compat. | The copy is the SDK golden fixture; both must match byte-for-byte. |

## Naming non-actions in Sprint 41

Sprint 41 is explicitly **not** allowed to:

1. Rename any Phase 1 import path (`aquaoptima.dphm.*`,
   `aquaoptima.dataio.*`).
2. Remove any Phase 1 public symbol.
3. Change any Phase 1 dataclass field order, naming, or default that
   would alter manifest JSON byte equality.
4. Move EPANET `.inp` import or `Network` construction into the SDK.
5. Move runtime evaluators (`evaluate_advisory_proposals`,
   `run_shadow_runtime`) into the SDK. They remain runtime logic; the
   SDK owns the input/output **shapes** only.
6. Introduce write / command / setpoint vocabulary in any Phase 1 or
   new module.

This non-action list is the safety contract for Sprint 41. Any later
sprint that wants to rename a Phase 1 surface must add a deprecation
window, a re-export shim, and a contract-compatibility test that runs
the Phase 1 fixtures through both the old and new paths.
