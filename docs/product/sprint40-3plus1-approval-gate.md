# Sprint 40 — 3+1 Architecture Approval Gate

Sprint 40 is a **planning and approval sprint only**. It produces the
final approval gate for the 3+1 product architecture replan delivered in
the prior planning commits, so that Sprint 41 implementation can begin
without scope drift, safety regressions, or contract surprises.

This document is the single decision document a reviewer should read to
either approve, defer, or reject Sprint 41 implementation. It cross-
references the more detailed planning docs in `docs/architecture/`,
`docs/safety/`, and `docs/product/`.

## Decision summary

AquaOptima dPHM-PINN is recommended to be packaged as
**three independently deployable product components plus one
non-deployable Shared Contracts / SDK package**:

1. **Edge Runtime** — plant-adjacent, mock/offline/read-only shadow
   runtime, package validator, capability enforcer.
2. **AI / Optimization Server** — GB10-hosted dPHM/dPHM-PINN inference,
   optimization, calibration, retraining, model registry, deployment
   package generator.
3. **Operations Console** — GB10-hosted dashboards, operator review
   workflows, audit views, deployment package review, and
   explanation-only local LLM interface.
4. **Shared Contracts / SDK** — non-deployable schemas, manifests,
   safety vocabulary, capability gates, API payloads, deterministic
   serialization, fixtures, thin clients.

Sprint 40 does not introduce runtime code for any of those components.
It only delivers the planning artifacts required to start Sprint 41
safely.

## What Sprint 40 approves

Approving Sprint 40 means the reviewer has accepted, for the next
8–12 sprints:

1. **The 3+1 component split.** Edge Runtime, AI / Optimization Server,
   Operations Console, and Shared Contracts / SDK are the four product
   boundaries. See
   [`docs/architecture/component-ownership-matrix.md`](../architecture/component-ownership-matrix.md).
2. **The Shared Contracts / SDK package** as the sole owner of shared
   data shapes, safety vocabulary, capability gates, manifests, and
   deterministic serialization. See
   [`docs/architecture/shared-contracts-sdk.md`](../architecture/shared-contracts-sdk.md).
3. **The contract inventory and Sprint 41 MVP cut.** See
   [`docs/architecture/contracts-inventory.md`](../architecture/contracts-inventory.md).
4. **The Phase 1 API → component map.** Existing Phase 1 surfaces
   (`TelemetryTagMap`, `ShadowReplayDataset`, `DPLCalibrationLossReport`,
   `AdvisoryContract`, `AdvisoryProposal`, `ShadowRuntimeReport`,
   `ShadowDeploymentManifest`, `EpanetImportDiagnostics`,
   `EpanetImportQualityReport`) get a single, named future home. See
   [`docs/architecture/phase1-api-to-component-map.md`](../architecture/phase1-api-to-component-map.md).
5. **The capability and safety-gate model.** Allowed and forbidden
   capabilities, gates before any dry-run / read-only adapter /
   simulated write / supervised write / PAC-like edge work, and local
   LLM / Operations Console safety restrictions. See
   [`docs/safety/capability-model-and-safety-gates.md`](../safety/capability-model-and-safety-gates.md).
6. **The Sprint 41 Shared Contracts / SDK plan.** Candidate public APIs
   and types, TDD acceptance criteria, files to create or modify,
   verification commands, and explicit non-goals. See
   [`docs/product/sprint41-shared-contracts-sdk-plan.md`](sprint41-shared-contracts-sdk-plan.md).
7. **The Phase 2 / Phase 3 sprint sequence** described in
   [`docs/product/phase2-phase3-3plus1-roadmap.md`](phase2-phase3-3plus1-roadmap.md).
8. **The non-negotiable safety boundary** below.

## What Sprint 40 explicitly does NOT approve

Sprint 40 does **not** authorize, schedule, or pre-approve any of the
following. Each requires a separate, named, explicit approval gate.

1. No live OT binding.
2. No PLC/PAC/SCADA write (required exact phrase: no PLC/PAC/SCADA write).
3. No command emission.
4. No setpoint output.
5. No control-loop closure.
6. No setpoint or command output unless later explicitly safety-gated
   and approved.
7. No automatic activation of an AI-generated deployment package at the
   edge.
8. No Operations Console "execute / apply / send command" UI surface.
9. No local LLM tool-use that touches Edge Runtime APIs, AI Server
   activation APIs, manifest mutation, or any capability gate.
10. No reuse of `AdvisoryProposal` as a command payload.
11. No merge of Phase 3 PAC-like edge work into `main` without separate
    qualification approval.
12. No Sprint 41 implementation before this approval gate is signed.

The Edge Runtime, AI / Optimization Server, and Operations Console
remain bound, for the entire approved planning window, by:

- offline, mock, dry-run, read-only execution only;
- explicit deny-by-default capability gates;
- no command / write / setpoint vocabulary in any contract;
- advisory proposals are audit / review payloads, not commands;
- operator approval authorizes review or shadow-package distribution
  only — never actuation.

## Required user approval before Sprint 41 implementation

Sprint 41 implementation is gated on explicit user approval of, at
minimum:

1. The 3+1 component split.
2. The Shared Contracts / SDK package boundary and ownership.
3. The Sprint 41 SDK MVP scope (envelopes, `SafetyFlagSet`,
   `CapabilityDeclaration`, deterministic JSON helpers, golden
   fixtures, negative tests).
4. The capability and safety-gate model in
   `docs/safety/capability-model-and-safety-gates.md`.
5. The forbidden-capability list and the gates before any future
   dry-run / read-only adapter / simulated write / supervised write /
   PAC-like edge work.
6. The Phase 1 API → component mapping (no API renames in Sprint 41;
   Phase 1 surfaces remain importable from `aquaoptima.dphm`).
7. The non-goals list in
   [`docs/product/sprint41-shared-contracts-sdk-plan.md`](sprint41-shared-contracts-sdk-plan.md).
8. The branch/merge policy: PAC-like or write-capable code stays on a
   `lab/pac-edge-qualification` branch and may not merge to `main`
   without an independent safety review.

Approval should be recorded as a commit or PR comment that names this
document by path. Sprint 41 should not start until that approval is on
the record.

## Open decisions and blockers

The following items remain open. None of them block Sprint 41 SDK
foundation work; they must be closed before later sprints depending on
them.

| # | Decision | Owner | Blocks |
|---:|---|---|---|
| 1 | Repository strategy (monorepo with strict packages vs polyrepo). Recommended: monorepo first. | Architecture | Sprint 41 package layout (SDK lives inside this repo initially). |
| 2 | API protocol baseline (REST/JSON first vs event streaming). Recommended: REST/JSON first. | Architecture | Sprints 43–47 AI Server and Edge APIs. |
| 3 | Edge deployment package format (zip vs tar vs OCI; signing approach). | Edge / Security | Sprints 44–45 package generation and validation. |
| 4 | Artifact trust model (hashes-only vs cryptographic signatures vs in-toto-style provenance). | Security | Sprints 44, 56, 64 package provenance. |
| 5 | Model execution location for Phase 2 (GB10-only vs split edge inference). Recommended: GB10 owns heavy inference initially. | AI / Edge | Sprint 43 onward AI Server inference scope. |
| 6 | Console backend boundary (separate Console backend service vs embedded in AI Server). Recommended: separate Console backend for workflow / session / LLM isolation. | Product / UI | Sprints 48–49 Console workflows. |
| 7 | Local LLM model selection and audit policy. | Product / Security | Sprint 66 LLM assistant MVP. |
| 8 | Contract semver windows and deprecation policy (e.g. minimum two-major-version overlap). | SDK | Sprint 42 first contract set. |
| 9 | Fleet model (one edge per GB10 vs multiple edges per GB10). | Product / Edge | Sprint 67 fleet metadata. |
| 10 | Future OT adapter qualification path (lab simulator → HIL → site acceptance). | Safety | Phase 3 (Sprints 52–70). |
| 11 | Persistent storage choice for AI Server (model registry / report ingestion). | AI | Sprints 43–47. |
| 12 | Audit event sink (file / DB / external system) and retention policy. | Security / Ops | Sprints 47, 53. |

Open decisions 1–8 should be closed during Sprints 41–43 so that
Sprints 44+ have a stable execution plan. Items 9–12 may close later
but should be tracked on the roadmap.

## Non-negotiable safety boundary (restated)

For the next 8–12 sprints, every component, contract, sprint plan,
and merge is bound by the following invariants:

- No live OT binding.
- No PLC/PAC/SCADA write (required exact phrase: no PLC/PAC/SCADA write).
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated
  and approved.
- Future edge / PAC work begins mock, offline, simulated, dry-run,
  read-only, lab-only, and capability-gated.

These invariants are encoded in:

- the safety vocabulary in
  [`docs/safety/capability-model-and-safety-gates.md`](../safety/capability-model-and-safety-gates.md);
- the contract design rules in
  [`docs/architecture/shared-contracts-sdk.md`](../architecture/shared-contracts-sdk.md);
- the boundary rules in
  [`docs/safety/component-boundaries-and-qualification-gates.md`](../safety/component-boundaries-and-qualification-gates.md);
- the existing Phase 1 evidence in
  [`docs/validation/phase1-shadow-mode-e2e.md`](../validation/phase1-shadow-mode-e2e.md).

## Recommended next action

1. Review this document and its referenced planning artifacts.
2. Record approval (or specific rejections / change requests) in a PR
   comment or commit message that names this document.
3. On approval, start **Sprint 41 — Shared Contracts / SDK safety and
   capability foundations** as specified in
   [`docs/product/sprint41-shared-contracts-sdk-plan.md`](sprint41-shared-contracts-sdk-plan.md).
4. Do not begin AI / Edge / Operations Console runtime work until the
   SDK MVP from Sprint 41 is in place.
