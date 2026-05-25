# AMAX-5580 Supervisory Proposal Dry-run / PLC Gatekeeper Contract (Sprint 50)

Sprint 50 defines a **simulated supervisory proposal / PLC gatekeeper
contract** that names the *structure* of future autonomy work without
enabling any of it. Sprint 50 is a contracts / dry-run / simulation
sprint. It does **not** install software, does **not** connect to a
live site, does **not** open a write surface, and does **not** approve
any pilot.

This document is the audit-only companion to
`src/aquaoptima_contracts/edge/supervisory_gatekeeper.py` and the
canonical helper `default_amax_supervisory_dry_run_contract()`.

## What this sprint ships

- **Sprint 50 ships a simulated supervisory proposal / PLC gatekeeper
  contract, not a live write or control authorisation.** The default
  contract is conservative: every gatekeeper condition starts in
  `not_evaluated`, the evaluation verdict is `not_evaluated`, and
  `live_write_authorized` is fixed to `False`.
- A canonical gatekeeper category vocabulary (eight categories — see
  below) for the SDK to validate against.
- Frozen, audit-only, stdlib-only SDK dataclasses:
  - `SupervisoryProposalValue` — labels-only audit row for one
    simulated proposal value (axis label, target id, proposed value,
    unit, lower / upper envelope, confidence, validity window
    seconds, rollback / fallback reference, notes).
  - `SupervisoryProposalDryRun` — frozen audit bundle of proposal
    values with proposal id, source evidence references, created-by
    label, validity window, expiration label, `simulation_only=True`,
    `dry_run=True`, and safety notes.
  - `PLCGatekeeperCondition` — frozen audit row for one gate (id,
    category, required state, observed-evidence label, status,
    blocking flag, notes).
  - `PLCGatekeeperEvaluation` — frozen audit bundle combining a
    proposal with a tuple of gatekeeper conditions and a
    deterministic verdict (`not_evaluated`, `blocked`, or
    `simulation_accepted`). Always carries `simulation_only=True`.
  - `evaluate_plc_gatekeeper_dry_run()` — pure helper that produces
    a deterministic evaluation from a proposal plus a sequence of
    conditions. Simulation only.
  - `AMAXSupervisoryDryRunContract` — frozen Sprint 50 audit bundle
    combining the proposal, the gatekeeper evaluation, Sprint 49
    referenced evidence ids / docs, warnings / errors, and the next
    gate. Carries explicit `live_write_authorized=False`.
  - `AMAXSupervisoryDryRunDiagnostics` — deterministic warnings /
    errors record surfaced by
    `diagnose_amax_supervisory_dry_run_contract()` when the contract
    is missing gatekeeper categories, missing Sprint 49 referenced
    evidence, missing next-gate language, attempts to declare live
    write authorisation, or carries unsafe vocabulary in labels.

## Proposal semantics

A `SupervisoryProposalValue` describes a single simulated proposed
value, not a write. Every field is audit-only:

| Field | Audit-only meaning |
|-------|--------------------|
| `axis_label` | Label naming the proposed variable / axis (e.g. `pump_speed_proposed_fraction`). |
| `target_id` | Label naming the target the advisory is *about* (e.g. `station_a_pump_1`). The site PLC retains direct VFD / pump / actuator authority. |
| `proposed_value` | Numeric value the advisor would *suggest*; the site PLC may consider or ignore it at its sole discretion. |
| `unit` | Engineering unit label (e.g. `fraction_of_rated_speed`, `metres_water_column`). |
| `lower_envelope` / `upper_envelope` | Safety envelope bounds; the SDK enforces `lower_envelope <= proposed_value <= upper_envelope`. |
| `confidence` | Confidence score in `[0.0, 1.0]`; rejected outside that range. |
| `validity_window_seconds` | Positive duration during which the advisory is meant to be considered. |
| `rollback_reference` | Label pointing at the Sprint 49 rollback / fallback evidence. No callable handle is stored. |
| `notes` | Audit notes. |

A `SupervisoryProposalDryRun` bundles one or more values under a
proposal id with `simulation_only=True` and `dry_run=True`. The SDK
refuses to record either flag as `False`. No proposal carries a
write register, command topic, dispatch topic, or actuator address.

## PLC gatekeeper expectations

A real, future autonomy path must pass through *every* gate the site
PLC enforces — not the AquaOptima advisory channel. The Sprint 50
contract names those gates so that future evidence work has a
structured surface to fill in. The site PLC owns the gates; AquaOptima
only records the *expectation*.

The canonical Sprint 50 gatekeeper categories are:

| Category | What the site PLC must report before any dry-run is `simulation_accepted` |
|----------|----------------------------------------------------------------------------|
| `operator_enable` | Site operator has explicitly enabled the AquaOptima supervisory advisory channel at the operator console. |
| `mode_enabled` | Site PLC reports the supervisory advisory mode as enabled and not in manual / maintenance / e-stop. |
| `interlocks_healthy` | Site PLC reports all relevant interlocks as healthy for the proposal window. |
| `permissives_healthy` | Site PLC reports all relevant permissives as healthy for the proposal window. |
| `stale_data_rejection` | Sprint 48 freshness policy holds — telemetry windows feeding the proposal are within their freshness thresholds. |
| `bounds_rate_limits` | Proposal value lies within the lower / upper envelope and within site rate-of-change limits documented in the site SAT evidence. |
| `fallback_manual_priority` | Site PLC fallback / manual operation always takes priority over any AquaOptima advisory output. |
| `e_stop_manual_override` | E-stop and manual override paths remain authoritative and unaffected by the AquaOptima advisory channel. |

Every gate is captured as a frozen `PLCGatekeeperCondition` record.
Default conditions start in `not_evaluated`; real site evidence is
required to mark any condition `passed`. `failed` is reserved for a
discovered gap that must be resolved before further evidence is
accepted.

## Verdicts (simulation only)

`PLCGatekeeperEvaluation.verdict` is one of three audit labels:

- `not_evaluated` — at least one condition is still `not_evaluated`.
  This is the safe default the canonical helper returns.
- `blocked` — every condition has been evaluated, but at least one
  blocking condition is not `passed`. A `blocked` verdict ends the
  dry-run: no further evidence is accepted until the failing gates
  are resolved.
- `simulation_accepted` — every blocking condition is `passed`. This
  is a *simulation-only* label that says "the structural gates lined
  up for this dry-run". It is **not** a live-write authorisation, it
  is **not** a pilot sign-off, and it does **not** trigger any side
  effect.

The SDK refuses to construct an evaluation with any verdict outside
this set. There is no `live_write_authorized` verdict; the contract's
top-level `live_write_authorized` boolean is fixed to `False`.

## Relationship to Sprint 49

Sprint 50 is a strict downstream of Sprint 49. Every Sprint 50
contract is expected to cite the Sprint 49 site deployment readiness
evidence package:

- The default contract's `referenced_evidence` cites
  `sprint_49_amax_site_deployment_evidence_package` plus the Sprint 46
  feasibility decision, Sprint 47 benchmark report, Sprint 48
  read-only integration contract, and the relevant docs under
  `docs/hardware/`.
- The `rollback_reference` on each proposal value cites
  `sprint_49_rollback_runbook_label`. Sprint 49 defines what
  "rollback" means; Sprint 50 only references it.
- The Sprint 50 gatekeeper diagnostics surface a warning when the
  contract does not mention Sprint 49 in its referenced evidence and
  an error when no referenced evidence is supplied at all.
- The Sprint 49 readiness checklist (operator disable path, site
  cybersecurity posture, rollback runbook, FAT / SAT plans,
  failure-mode walkthrough) remains the upstream evidence; Sprint 50
  does not duplicate those checks, it references them.

Sprint 50 does **not** override or relax any Sprint 49 expectation.
If the Sprint 49 evidence package is not signed off for a site, the
Sprint 50 dry-run cannot reach `simulation_accepted` for that site —
the gatekeeper categories above will not have evidence to back them.

## Non-negotiable safety boundary

Sprint 50 reaffirms — in source docstrings, canonical record notes,
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
- no live OPC UA / Modbus / CODESYS / SCADA / PLC / MQTT / HTTP /
  database / message-broker client in this module
- no Edge Runtime daemon / service implementation
- no AI / Optimization Server runtime, no Operations Console runtime
- no model artifact loading from disk, no inline model weights
- no credentials, passwords, tokens, API keys, or connection secrets
  in docs / tests / source
- no site install approval by default
- no supervised writes, no proposal-to-PLC path, no live write
  authorisation verdict

The site PLC / pump-station PLC retains direct VFD / pump / actuator
authority for every Sprint 45+ AMAX deliverable. The Sprint 50
contract makes the *structure* of a future supervised path
auditable; it does not bring that path any closer to live
operation.

## What Sprint 50 explicitly does not do

- **Sprint 50 does not install software.** It defines the contract
  shapes a future supervisory advisory channel would have to honour.
- **Sprint 50 does not connect to a live site.** All Sprint 48
  read-only integration shapes remain audit-only; replay-to-live
  equivalence stays `not_evaluated` until real source verification
  is signed off by Sprint 49 evidence and beyond.
- **Sprint 50 does not output setpoints, commands, writes, or close
  a control loop.** The contract is a simulation-only structural
  record; no Sprint 50 dataclass field can authorise a live write.
- **Sprint 50 does not approve any pilot.** A `simulation_accepted`
  verdict is a structural audit label only.

## Sprint 51 — next gate

After Sprint 50 passes, **Sprint 51 should be an AMAX pilot
readiness review / hardware-in-the-loop plan**, still no live
control. Sprint 51 must not introduce live OT binding, PLC/PAC/SCADA
write, command emission, setpoint output, control-loop closure, or
any Edge Runtime daemon implementation. The site PLC retains direct
VFD / pump / actuator authority until a future safety gate
explicitly approves a supervised, bounded write surface.
