# AMAX-8580 Site Deployment Readiness / OT Certification Evidence (Sprint 49)

Sprint 49 defines the **site deployment readiness / OT certification
evidence package** required before installing AquaOptima AMAX Edge in
an OT-side environment. It is an evidence / checklist / specification
sprint. Sprint 49 does **not** install software, does **not** connect
to a live site, and does **not** approve writes.

This document is the audit-only companion to
`src/aquaoptima_contracts/edge/deployment_readiness.py` and the
canonical helper `default_amax_site_deployment_evidence_package()`.

## What this sprint ships

- **Sprint 49 ships a site deployment readiness / OT certification
  evidence package, not a site install approval.** The default
  package is conservative: every blocking checklist item starts in
  `pending`, and `site_specific_approval_required` is fixed to
  `True`.
- A canonical readiness vocabulary (twelve categories — see below)
  for the SDK to validate against.
- Frozen, audit-only SDK dataclasses:
  - `DeploymentReadinessItem` — labels-only audit row for one
    readiness item (item id, category, description, evidence
    reference label, owner / approver label, status, blocking flag,
    notes).
  - `AMAXDeploymentReadinessChecklist` — frozen audit bundle of
    readiness items. Helpers: `categories`, `items_for_category()`,
    `unresolved_blocking_items()`, `is_fully_approved()`.
  - `AMAXOTCertificationEvidence` — frozen audit record contrasting
    AMAX hardware certification with AquaOptima system-level
    qualification evidence. `hardware_certifies_system` is fixed to
    `False`.
  - `AMAXFailureMode` — frozen failure mode / effect / detection /
    fallback row.
  - `AMAXSiteDeploymentEvidencePackage` — frozen audit bundle
    combining the checklist, certification evidence, failure-mode
    matrix, Sprint 46 / 47 / 48 evidence references, the next gate,
    and explicit `site_specific_approval_required=True`.
  - `AMAXDeploymentReadinessDiagnostics` — deterministic warnings /
    errors surfaced by
    `diagnose_amax_site_deployment_evidence_package()` for
    unresolved blocking items, missing required categories, missing
    failure-mode coverage, missing referenced evidence, and unsafe
    vocabulary in labels.

## Deployment readiness checklist

The canonical Sprint 49 checklist covers twelve categories. Every
item ships in `pending` status with `blocking=True`; real site
evidence is required to flip each to `approved`.

| Category | What is being approved | Owner label |
|----------|------------------------|-------------|
| `sku` | AMAX-8580 SKU pinned to a Sprint 46 serious-candidate (Core i5-6300U 8 GB / Core i7-6600U 8 GB) per site BOM | `site_hardware_lead` |
| `os_image` | Site OS image (AdvLinuxTU Ubuntu 18 or Windows 10 LTSC 2019) built, signed, stored with provenance in the site image registry | `site_ot_engineering_lead` |
| `codesys_package` | CODESYS Linux Control / Control RTE runtime co-tenant approved, version pinned, signed per site policy | `site_plc_lead` |
| `network_ports` | Network ports allow Sprint 48 read-only inbound flows only; no outbound write / dispatch flows are opened | `site_network_security_lead` |
| `physical_install` | AMAX panel mount, grounding, and clearance follow Advantech DIN-rail / panel installation guidance | `site_electrical_contractor` |
| `power` | 24 VDC supply meets AMAX input range; site UPS sized for orderly shutdown on power loss | `site_electrical_lead` |
| `storage` | Industrial-grade SSD / mSATA storage sized for site log retention; power-loss tolerant | `site_ot_engineering_lead` |
| `environment` | Cabinet temperature, humidity, vibration, ingress protection stay within the AMAX operating envelope | `site_facilities_lead` |
| `rollback` | Rollback runbook written, dry-run signed off, stored alongside the deployment package | `site_operations_lead` |
| `cybersecurity` | Site cybersecurity posture documented and signed (see below) | `site_cybersecurity_lead` |
| `fat_sat` | FAT (factory acceptance test) and SAT (site acceptance test) plans written, reviewed, scheduled | `site_acceptance_lead` |
| `safety_boundary` | Sprint 49 safety boundary reaffirmed before any site install | `aquaoptima_safety_owner` |

## Cybersecurity posture

The cybersecurity category covers — at minimum — the following
audit evidence. None of these are runtime configuration; they are
references / labels the site must capture before any pilot.

- **Segmentation labels.** Sprint 48 already records OT-zone /
  IT-zone segmentation labels for read-only telemetry sources. The
  site cybersecurity review must reaffirm the segmentation in the
  context of the AMAX device's network ports and any IT-zone bridge
  it touches.
- **Credential references.** All credentials are labels pointing at
  the site secret-management system. **No secrets, no passwords, no
  tokens, no API keys, and no connection strings are stored in any
  AquaOptima SDK artifact, doc, test, or fixture.**
- **No stored secrets.** The SDK contract package is byte-stable;
  any deployment package built from these SDK contracts therefore
  carries no embedded secrets either.
- **Software signing and provenance.** OS image, AquaOptima
  deployment package, and CODESYS runtime are signed per site policy.
  Provenance (hashes, signing key references) is captured in the
  Sprint 44 / Sprint 45 deployment manifests; site policy must
  approve the signing key references.
- **Audit logs.** Edge audit logs must be retained per site policy.
  Sprint 49 records the retention expectation as a readiness
  reference; the runtime path that produces those logs stays in
  Phase 1 `aquaoptima.*` runtime modules, not the SDK.
- **Patching / update stance.** Updates to the OS image, CODESYS
  runtime, or AquaOptima deployment package must follow the rollback
  runbook (above) and the FAT / SAT plans (below). No silent in-place
  patching of OT-side software is permitted.

## Certification / evidence map

AMAX-8580 hardware ships with industry certifications (CE marking,
FCC Part 15, UL industrial-control, EN 61131-2, IEC 61010-1, Class 1
Div 2 where applicable, etc.). Those certifications are necessary
for OT installation but **necessary but not sufficient** for
AquaOptima system deployment.

The Sprint 49 evidence map (`AMAXOTCertificationEvidence`) makes
this explicit:

- `hardware_certifications` — list of AMAX hardware certification
  labels (CE / FCC / UL / EN 61131-2 / IEC 61010-1 / Class 1 Div 2
  where applicable). Labels are references to the certification
  documentation; the SDK does not embed certificate content.
- `system_qualifications_required` — list of AquaOptima
  system-level qualifications still required: FAT evidence, SAT
  evidence, site cybersecurity review, rollback dry-run, failure-mode
  walkthrough, and replay-to-live equivalence sign-off (Sprint 48).
- `hardware_certifies_system` — fixed to `False`. The Sprint 49
  package and the SDK contract refuse to record this as `True`.

## FAT / SAT outline

The Sprint 49 FAT (factory acceptance test) and SAT (site acceptance
test) plans are required before any pilot. The plans themselves live
in site documentation; the SDK contract holds the *readiness
references* only. Sprint 49 expects the plans to cover at minimum:

- **FAT (factory acceptance test).** Run on bench AMAX hardware
  with simulated / replay telemetry. Confirms Sprint 45 deployment
  package validation, Sprint 46 SKU pinning, Sprint 47 CPU benchmark
  cadence on the target SKU, Sprint 48 read-only integration shapes
  (axis / role / unit / target id alignment, freshness thresholds,
  quality-flag mapping, replay-to-live equivalence not-evaluated /
  surrogate status), rollback runbook dry run, operator disable
  walkthrough.
- **SAT (site acceptance test).** Run on the actual AMAX hardware
  in the site cabinet, against **frozen / replayed** telemetry only.
  No live writes. Repeats the FAT checks with the site network
  segmentation, site credential references, and site environment.
  SAT sign-off requires the cybersecurity, rollback, and failure-mode
  evidence to be approved.

Neither FAT nor SAT closes a control loop. Both stop at the
audit-only output of the Edge advisory; the site PLC retains direct
VFD / pump / actuator authority throughout.

## Failure-mode matrix

The canonical Sprint 49 failure-mode matrix
(`canonical_amax_failure_modes()`) covers eight failure modes. Every
fallback narrates a fall-through to site PLC authority.

| Mode id (suffix) | Category | Effect | Detection | Fallback |
|------------------|----------|--------|-----------|----------|
| `stale_telemetry` | telemetry | Edge cannot produce a current advisory; outputs are audit-only | Sprint 48 freshness policy & quality-flag mapping | Hold last good audit window; fall through to site PLC authority |
| `package_install_failure` | package | Edge runtime not promoted | Sprint 45 deny-by-default validator | Stay on previously validated package; otherwise PLC-only |
| `cpu_benchmark_failure` | benchmark | Supervisory cadence downgrade or package rejection | Sprint 47 `AMAXBenchmarkReport` and cadence classifier | Slower cadence audit-only mode or PLC-only |
| `network_loss` | network | Sprint 48 sources stop delivering telemetry | Sprint 48 missing-data behavior tokens | Audit-only fallback; site PLC retains direct VFD / pump / actuator authority |
| `power_loss` | power | Edge unavailable for outage duration | Site UPS telemetry & AMAX power-fail signalling | Site continues PLC-only; orderly shutdown preserves audit logs |
| `rollback_failure` | rollback | Cannot safely promote new package | Rollback runbook checklist & FAT / SAT gates | Hold at the prior validated state; escalate before further promotion |
| `operator_disable_unavailable` | operator | Operators cannot suspend Edge advisory outputs | FAT / SAT operator-disable walkthrough | Site PLC interlocks remain authoritative; escalate per operations runbook |
| `codesys_co_tenancy_unresolved` | codesys | CPU / memory contention risk | Sprint 47 packaging smoke harness & FAT headroom checks | Move ML sidecar outside CODESYS via Sprint 46 service-sidecar option |

Each row is captured as a frozen `AMAXFailureMode` record. The
fallback text is **audit expectation**, not an instruction the SDK
executes; the SDK has no actuators, no command path, and no setpoint
output.

## Non-negotiable safety boundary

Sprint 49 reaffirms — in source docstrings, canonical record notes,
this document, and tests — the boundary that Sprint 45+ AMAX work
must never cross:

- no live OT binding
- no PLC/PAC/SCADA write
- no command emission
- no setpoint output
- no control-loop closure
- no direct VFD / pump / actuator control from AquaOptima Edge
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop
- no Edge Runtime daemon / service implementation
- no AI / Optimization Server runtime, no Operations Console runtime
- no live OPC UA / Modbus / CODESYS / SCADA / PLC / MQTT / HTTP /
  database / message-broker client in this module
- no model artifact loading from disk, no inline model weights
- no credentials, passwords, tokens, API keys, or connection secrets
  in docs / tests / source
- no site install approval by default
- no supervised writes or proposal-to-PLC path

The site PLC / pump-station PLC retains direct VFD / pump / actuator
authority for every Sprint 45+ AMAX deliverable.

## What Sprint 49 explicitly does not do

- **Sprint 49 does not install software.** It defines the readiness
  evidence that must be in hand before any installation.
- **Sprint 49 does not connect to a live site.** All Sprint 48
  read-only integration shapes remain audit-only; replay-to-live
  equivalence stays `not_evaluated` until a real source verification
  is signed off.
- **Sprint 49 does not approve writes.** AMAX hardware certification
  is *necessary but not sufficient* for AquaOptima system
  deployment; FAT, SAT, cybersecurity, rollback, and failure-mode
  evidence are required before any pilot.

## Sprint 50 — next gate

After Sprint 49 passes, **Sprint 50 should remain a simulated
supervisory proposal / PLC gatekeeper contract sprint**, not a live
write / control sprint. Sprint 50 must not introduce live OT binding,
PLC/PAC/SCADA write, command emission, setpoint output, control-loop
closure, or any Edge Runtime daemon implementation. The site PLC
retains direct VFD / pump / actuator authority for every Sprint 45+
AMAX deliverable until a future safety gate explicitly approves a
supervised, bounded write surface.
