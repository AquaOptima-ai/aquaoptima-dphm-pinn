# AMAX-5580 Pilot Readiness Review / Hardware-in-the-loop Plan (Sprint 51)

Sprint 51 is the final AMAX evidence-ladder sprint. It defines an
**AMAX pilot readiness review / hardware-in-the-loop (HIL) plan**:
a deterministic, audit-only structure that maps the Sprint 46–50
evidence ladder onto a concrete HIL test matrix and a go / no-go gate
that must pass before any real lab or pilot is considered.

Sprint 51 is planning / HIL-readiness only. It does **not** install
software on a site PLC, does **not** connect to a live site, does
**not** open a write surface, does **not** emit setpoints, does
**not** emit commands, and does **not** approve any pilot. The site
PLC retains direct VFD / pump / actuator authority for every Sprint
45+ AMAX deliverable until a future safety gate explicitly approves
a supervised, bounded write surface.

This document is the audit-only companion to
`src/aquaoptima_contracts/edge/pilot_readiness.py` and the canonical
helpers `default_amax_hil_test_matrix()` /
`default_amax_pilot_readiness_review()` /
`evaluate_amax_pilot_readiness_review()`.

## Sprint 46–50 evidence ladder recap

Sprint 51 stands on five contract / evidence sprints. None of them
authorised a live write; together they describe what AquaOptima Edge
*could* run on real AMAX hardware once real evidence replaces the
current surrogate evidence.

| Sprint | Shipped artefact | Audit role |
|--------|------------------|------------|
| 46 | `AMAXSkuProfile`, `AMAXRuntimeOption`, `AMAXFeasibilityDecision` | SKU / OS / runtime feasibility evidence. Surrogate until real AMAX hardware. |
| 47 | `AMAXBenchmarkScenario`, `AMAXBenchmarkMetrics`, `AMAXBenchmarkReport`, `classify_supervisory_cadence()` | CPU dPHM-PINN benchmark / packaging smoke harness. Offline / CPU-only, sized for a real AMAX-5580 run. |
| 48 | `ReadOnlyIntegrationProtocol`, `ReadOnlyTagBinding`, `TelemetryFreshnessPolicy`, `ReadOnlyTelemetrySource`, `ReadOnlyIntegrationContract`, `ReplayToLiveEquivalenceEvidence` | Read-only PLC/SCADA integration contracts. No write path. |
| 49 | `DeploymentReadinessItem`, `AMAXDeploymentReadinessChecklist`, `AMAXOTCertificationEvidence`, `AMAXFailureMode`, `AMAXSiteDeploymentEvidencePackage` | Site deployment readiness / OT certification evidence package. No site install approval by default. |
| 50 | `SupervisoryProposalValue`, `SupervisoryProposalDryRun`, `PLCGatekeeperCondition`, `PLCGatekeeperEvaluation`, `AMAXSupervisoryDryRunContract`, `evaluate_plc_gatekeeper_dry_run()` | Simulated supervisory proposal / PLC gatekeeper dry-run contract. Verdict vocabulary is strictly `not_evaluated` / `blocked` / `simulation_accepted`. |

The non-negotiable safety boundary is reaffirmed at every step:

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- the site PLC retains direct VFD / pump / actuator authority.

## What this sprint ships

- **Sprint 51 ships an AMAX pilot readiness review / HIL plan
  contract, not a live write or control authorisation.** The default
  review is conservative: every blocking evidence item starts in
  `pending`, the review verdict is `not_ready`, and
  `live_control_authorized` is fixed to `False`.
- A canonical HIL test category vocabulary (ten categories — see
  below) for the SDK to validate against.
- Frozen, audit-only, stdlib-only SDK dataclasses:
  - `HILTestCase` — labels-only audit row for one HIL test case
    (id, category, objective, required evidence references, expected
    result, blocking flag, simulation_only flag, notes).
  - `HILTestMatrix` — frozen audit bundle of test cases with a
    matrix id, target hardware profile label, target OS / runtime
    label, bench (or simulated) PLC label, references to Sprint
    46–50 evidence, and audit notes.
  - `PilotReadinessEvidenceItem` — frozen audit row for one
    evidence-ledger entry (id, source sprint / doc, status, owner /
    reviewer label, blocking flag, notes).
  - `PilotReadinessReview` — frozen Sprint 51 audit bundle combining
    the HIL matrix, evidence items, open risks, verdict
    (`not_ready` / `ready_for_lab_simulation` / `blocked`),
    referenced Sprint 46–50 evidence, next gate, and the reaffirmed
    safety boundary. Carries explicit `live_control_authorized=False`.
  - `evaluate_amax_pilot_readiness_review()` — pure helper that
    produces a deterministic, lab / simulation-only review from a
    matrix plus a sequence of evidence items. The SDK refuses to
    produce any verdict outside the lab / simulation vocabulary.
  - `AMAXPilotReadinessDiagnostics` — deterministic warnings /
    errors record surfaced by
    `diagnose_amax_pilot_readiness_review()` when the review is
    missing required HIL categories, missing Sprint 46–50 evidence
    references, attempts to declare live-control authorisation, or
    carries unsafe vocabulary in identifier / label fields.

## HIL lab setup

The Sprint 51 HIL plan assumes the following lab arrangement; no
piece of it requires touching a real site:

- One real **AMAX-5580** lab unit, panel-mounted per the Sprint 49
  install drawing label, powered from the lab UPS, and pinned to one
  of the Sprint 46 serious-candidate SKUs.
- One **bench or simulated PLC** (e.g. a desktop CODESYS soft-PLC,
  or a spare PLC chassis already running site-equivalent logic) the
  AMAX lab unit can read from over the Sprint 48 read-only adapter
  shape. No live site PLC is wired in.
- The frozen **Sprint 42 shadow replay dataset** loaded onto the AMAX
  lab unit so the Sprint 48 replay-to-live equivalence evidence can
  be exercised under controlled inputs.
- The signed **Sprint 44 deployment package** + **Sprint 45 edge
  capability declaration** so the package validator gate can be
  exercised end-to-end.
- The **Sprint 50 PLC gatekeeper dry-run** contract loaded with
  bench evidence labels so the gatekeeper verdict path can be
  exercised against the bench / simulated PLC.

Nothing in this lab setup carries a write surface. The bench /
simulated PLC reads telemetry; the AquaOptima advisory channel
proposes; the bench / simulated PLC retains all control authority.

## HIL test matrix

The canonical Sprint 51 HIL matrix covers ten categories. Every test
case is `simulation_only=True` and is audit-only until real lab
evidence is captured.

| Category | Objective | Sprint evidence | Blocking |
|----------|-----------|-----------------|----------|
| `package_install` | Install the signed Sprint 44 deployment package on the AMAX lab unit using the Sprint 45 capability declaration shape and verify the package validator accepts it. | 45, 46, 49 | yes |
| `cpu_benchmark` | Run the Sprint 47 dPHM-PINN CPU benchmark on the AMAX lab unit and verify p95 latency stays within the supervisory cadence envelope. | 46, 47 | yes |
| `read_only_adapter` | Wire the AMAX lab unit to a bench or simulated PLC using the Sprint 48 read-only integration contract and confirm no write path is exposed. | 48, 49 | yes |
| `telemetry_replay` | Replay the Sprint 48 frozen replay dataset against the AMAX lab unit and confirm replay-to-live equivalence evidence is captured. | 42, 48 | yes |
| `stale_data_failure` | Inject stale telemetry and confirm the Sprint 48 freshness policy + Sprint 50 stale-data gate together block the dry-run from being marked simulation-accepted. | 48, 50 | yes |
| `package_rollback` | Execute the Sprint 49 rollback runbook against a known-bad package and confirm the AMAX lab unit returns to pre-deployment PLC-only operation. | 49 | yes |
| `operator_disable` | Exercise the operator console disable path and confirm the AquaOptima advisory channel is disabled within the documented window without affecting site PLC behaviour. | 49, 50 | yes |
| `network_loss` | Sever the AMAX lab unit's network link and confirm behaviour matches the Sprint 49 network failure mode (advisory pauses; site PLC retains authority). | 48, 49 | yes |
| `plc_gatekeeper_dry_run` | Run the Sprint 50 PLC gatekeeper dry-run against a bench or simulated PLC and confirm the verdict stays in the simulation-only vocabulary. | 49, 50 | yes |
| `deployment_readiness_review` | Walk the Sprint 49 deployment readiness checklist against the AMAX lab unit and confirm every required category has captured evidence. | 49 | yes |

Every row in the matrix is blocking by default. Site engineering may
mark a row `not_applicable` only with auditable rationale captured in
the Sprint 51 review.

## Evidence ledger

The Sprint 51 default review carries six blocking evidence items
that map directly onto the Sprint 46–50 ladder plus the HIL lab unit:

| Evidence id | Source sprint / doc | Default status | Owner label |
|-------------|---------------------|----------------|-------------|
| `evidence_sprint_46_feasibility_decision` | `sprint_46_amax_feasibility_decision` | `pending` | `aquaoptima_amax_feasibility_owner` |
| `evidence_sprint_47_benchmark_report` | `sprint_47_amax_benchmark_report` | `pending` | `aquaoptima_amax_benchmark_owner` |
| `evidence_sprint_48_read_only_integration_contract` | `sprint_48_amax_read_only_integration_contract` | `pending` | `aquaoptima_amax_integration_owner` |
| `evidence_sprint_49_site_deployment_evidence_package` | `sprint_49_amax_site_deployment_evidence_package` | `pending` | `aquaoptima_amax_deployment_owner` |
| `evidence_sprint_50_supervisory_dry_run_contract` | `sprint_50_amax_supervisory_dry_run_contract` | `pending` | `aquaoptima_amax_supervisory_owner` |
| `evidence_hil_lab_unit_inventoried` | `docs/hardware/amax-5580-pilot-readiness-hil-plan.md` | `pending` | `aquaoptima_amax_hil_lab_owner` |

Status semantics:

- `pending` — the cited evidence has not been replaced by real lab
  evidence yet (the default).
- `available` — the evidence is on file, current, and signed off by
  the named owner / reviewer.
- `blocked` — the evidence has been actively flagged as unsatisfied
  and must be resolved before any verdict can move forward.

## Go / no-go verdicts

`PilotReadinessReview` carries a `verdict` field. The vocabulary is
strictly lab / simulation; no live control / write verdict can be
produced:

- `not_ready` — at least one blocking evidence item is `pending`.
  This is the conservative default for Sprint 51.
- `ready_for_lab_simulation` — every blocking evidence item is
  `available`. The lab simulation may proceed. **A
  `ready_for_lab_simulation` verdict does not approve a real pilot,
  a site install, or any write surface; it only authorises the HIL
  exercise itself.**
- `blocked` — at least one blocking evidence item has status
  `blocked`. No lab simulation may proceed.

`evaluate_amax_pilot_readiness_review()` computes the verdict
deterministically:

```
if any blocking evidence has status == blocked:
    verdict = blocked
elif any blocking evidence has status == pending:
    verdict = not_ready
else:
    verdict = ready_for_lab_simulation
```

The helper sets `live_control_authorized=False` unconditionally; the
contract refuses to record this flag as `True`.

## Required evidence before any real pilot

Sprint 51 lists the evidence that must exist — and be signed off —
before a future safety gate can even consider opening a supervised
write surface. None of it is shipped by Sprint 51 itself. The list
includes, at minimum:

- Real AMAX hardware procured, inventoried, and panel-mounted.
- Real (not surrogate) Sprint 46 SKU / OS / runtime feasibility
  evidence captured against the lab unit.
- Real (not surrogate) Sprint 47 CPU benchmark numbers within the
  supervisory cadence envelope.
- Bench-PLC Sprint 48 read-only adapter wiring verified end-to-end.
- Bench-PLC Sprint 48 replay-to-live equivalence evidence captured
  under controlled inputs.
- Sprint 49 rollback runbook dry-run signed off.
- Sprint 49 FAT / SAT plan authored, reviewed, and scheduled.
- Sprint 49 site cybersecurity posture review signed off.
- Sprint 49 failure-mode walkthrough completed.
- Sprint 50 PLC gatekeeper dry-run exercised against a bench /
  simulated PLC with every gate transitioning at least once.
- Site engineering, site operations, and site safety stakeholders
  all named and signed.

Until that evidence exists, the Sprint 51 review remains
`not_ready` or `blocked`.

## Go / no-go gates before any supervised write pilot

Sprint 51 does not authorise a supervised write pilot. The closest
the SDK can produce is `ready_for_lab_simulation`, which only
approves the HIL lab exercise itself. A future supervised-write
pilot must clear, at minimum, *all* of the following gates *in
addition* to a green Sprint 51 review:

1. **Phase checkpoint / replanning gate.** Sprints 52–60 are not
   yet well-planned and must be replanned before any implementation
   work begins. This document does not pre-empt that planning.
2. **Site safety review.** Site safety, site operations, site
   engineering, and AquaOptima safety leads must all sign a real
   pilot scope document.
3. **Independent OT cyber review.** External cybersecurity review
   of the AquaOptima Edge + AMAX deployment plus the bench / pilot
   integration paths.
4. **Site PLC interlock / permissive review.** A bench / simulated
   PLC walkthrough is not a site PLC walkthrough. The site PLC
   retains direct VFD / pump / actuator authority.
5. **Operator console disable + E-stop + manual override evidence
   captured against the *real* pilot site**, not just the lab.
6. **Documented rollback and PLC-only operation drill at the pilot
   site.**

None of these gates are wired into Sprint 51 source code. They are
audit text in this document and in the SDK `safety_notes`. The
authority for opening or closing each gate sits with the named site
roles, not with AquaOptima Edge or this repository.

## Explicit boundary statements

- Sprint 51 remains planning-only / HIL-readiness-only. It does not
  output setpoints or commands.
- Real site testing needs separate approval and a future sprint.
- The site PLC remains final actuator authority.
- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop;
- no live OPC UA / Modbus / CODESYS / SCADA / PLC / MQTT / HTTP /
  database / message-broker client (the SDK module is stdlib-only);
- no Edge Runtime daemon / service implementation;
- no AI / Optimization Server runtime, no Operations Console
  runtime;
- no model artifact loading from disk, no inline model weights;
- no credentials, passwords, tokens, API keys, or connection secrets
  in docs / tests / source;
- no site install approval by default;
- no supervised writes, no proposal-to-PLC path, no live write or
  control authorisation verdict.

## What Sprint 51 explicitly does **not** ship

- No real-hardware probe. Sprint 51 ships a *plan* and a contract;
  it does not run on AMAX hardware.
- No Edge Runtime daemon, no AI / Optimization Server runtime, no
  Operations Console runtime, no FastAPI process, no MQTT process.
- No movement of `evaluate_advisory_proposals`, `run_shadow_runtime`,
  the EPANET `.inp` import, or `Network` into the SDK. The Phase 1
  runtime modules remain authoritative under `src/aquaoptima/`.
- No removal or renaming of the Phase 1 `aquaoptima.*` import path.
- No site install approval. No supervised writes. No proposal-to-PLC
  routing. No live write or control authorisation verdict.

## Next gate

After Sprint 51, **Sprint 52+** is not yet well-planned. The
recommended next step is a **phase checkpoint / Sprint 52–60
replanning gate**, not an automatic live-control implementation.
That checkpoint should re-examine:

- whether the AMAX evidence ladder is sufficient to authorise a
  supervised-write pilot at all;
- which Phase 2 deployable (Edge Runtime, AI / Optimization Server,
  Operations Console) should be advanced first;
- whether to expand the read-only adapter family (e.g. an actual
  Modbus or OPC UA shim) before any write-surface conversation;
- the staffing, safety, and customer-engagement context that has
  to exist before a real pilot can be scheduled.

Sprint 51 reaffirms the non-negotiable safety boundary: **no live
OT binding**, **no PLC/PAC/SCADA write**, **no command emission**,
**no setpoint output**, no control-loop closure, no supervised
writes, no proposal-to-PLC path, no live write or control
authorisation verdict. The site PLC retains direct VFD / pump /
actuator authority.
