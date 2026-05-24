# Capability Model and Safety Gates

This document is the Sprint 40 authoritative capability model and the
ordered set of safety gates that must be satisfied **before** any
future dry-run, read-only live adapter, simulated write, supervised
write, or PAC-like edge work is even designed.

It restates and operationalizes the boundary already declared in
[`safety-boundary.md`](../safety-boundary.md) and
[`component-boundaries-and-qualification-gates.md`](component-boundaries-and-qualification-gates.md),
and gives Sprint 41+ a single capability vocabulary to enforce.

Non-negotiable boundary:

- No live OT binding.
- No PLC/PAC/SCADA write (required exact phrase: no PLC/PAC/SCADA write).
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated
  and approved.
- Future edge / PAC work begins mock, offline, simulated, dry-run,
  read-only, lab-only, and capability-gated.

## Capability model overview

A **capability** is a single, machine-readable, deny-by-default
permission token. Capabilities flow through the system in two
directions:

- **Declared** by the Edge Runtime: what the running Edge instance
  advertises it is allowed to do (`EdgeCapabilityDeclaration`).
- **Required** by a deployment package: what the package needs in
  order to run (`CapabilityRequirement` inside the package's
  `DeploymentPackageManifest`).

A package is allowed to activate at the Edge only if every required
capability is in the Edge's declared set **and** every declared safety
flag is consistent with the current product safety boundary. If any
required capability is unknown, forbidden, or unsupported, the Edge
must reject the package. Rejection produces an
`EdgePackageValidationResult` audit record.

Capability storage and naming rules:

1. Capability tokens live in the Shared Contracts / SDK
   (`aquaoptima_contracts/safety/capability_gates.py`). No deployable
   defines its own capability tokens.
2. Tokens are lowercase snake_case identifiers.
3. Capability sets are immutable once published in a SDK release.
4. Adding a capability requires an SDK MINOR bump.
5. Repurposing a capability requires an SDK MAJOR bump and a
   deprecation window.
6. Removing a capability requires an SDK MAJOR bump.
7. Forbidden tokens (see below) must never appear in any declared,
   required, or fixture capability set.

## Default supported capabilities

These are the capabilities that **may** be declared by an Edge
Runtime in Phase 2. The Sprint 41 SDK ships a canonical token list
and validators; the Phase 1 chain already exercises the
semantics of every token below as offline / read-only behavior.

```text
load_signed_or_hashed_package
validate_manifest
validate_checksums
validate_schema_versions
validate_safety_flags
validate_tag_map
run_shadow_replay
run_mock_read
evaluate_advisory_contract
produce_shadow_runtime_report
upload_health_report
upload_audit_event
serve_read_only_status
```

All thirteen capabilities listed above are deny-by-default in the SDK:
they only become active when a deployment package declares the
requirement **and** the Edge declares the matching capability. Sprint
41 does not implement Edge enforcement code; it only defines the
vocabulary and the validators.

## Default forbidden capabilities

These tokens must **never** appear as a declared capability, as a
required capability, in any contract fixture, or in any SDK or
deployable test. The SDK ships negative tests for each of them.

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

The SDK validator must reject any input containing one of these
tokens, regardless of context.

## Runtime modes

A separate vocabulary, the `EdgeRuntimeMode`, governs the dynamic
posture of an Edge Runtime instance. Runtime modes are deny-by-default
and must be declared explicitly by the deployment package and matched
by the Edge.

| Mode | Status (Sprint 41 / early Phase 2) | Meaning |
|---|---|---|
| `offline_replay` | Allowed | Reads local fixture / replay files only. |
| `mock_live_read` | Allowed | Reads from a mock adapter shaped like live telemetry; no live binding. |
| `advisory_audit_only` | Allowed | Evaluates hypothetical proposals for audit / review. |
| `package_validation_only` | Allowed | Validates package manifests and capabilities; no runtime evaluation. |
| `dry_run_read_only` | **Future, gated.** Requires Gate 0–7 below. | Reads from an approved source without commands or writes. |
| `control_enabled` | **Forbidden** in the current architecture. | Would emit commands or setpoints. Not modeled by the SDK. |
| `closed_loop_control` | **Forbidden** in the current architecture. | Closed-loop write/read interlock. Not modeled by the SDK. |
| `live_write` | **Forbidden** in the current architecture. | Live write to OT. Not modeled by the SDK. |
| `setpoint_output` | **Forbidden** in the current architecture. | Setpoint dispatch. Not modeled by the SDK. |
| `command_dispatch` | **Forbidden** in the current architecture. | Command dispatch. Not modeled by the SDK. |

Sprint 41 implements only the **safety vocabulary** and validators for
these modes. Edge Runtime mode selection logic is Sprint 46 work.

## Safety flag defaults

Every deployment manifest produced by the AI / Optimization Server in
Phase 2 must declare the full Sprint 41 safety flag set:

```text
offline                = True
read_only              = True
no_write               = True
no_control             = True
no_live_ot_binding     = True
no_setpoint_output     = True
packaging_audit_only   = True
```

The SDK rejects any package that omits one of these flags, sets one of
them to a value other than `True`, or attempts to introduce a new flag
not in the canonical list.

These defaults are derived from the Phase 1 manifests already produced
by `build_shadow_deployment_manifest` and exercised by
`tests/e2e/test_phase1_shadow_mode_pipeline.py`.

## Forbidden capabilities and modes for Sprint 41 and early Phase 2

For the entire approved planning window (Sprint 41 through at least
Sprint 51), the following are forbidden at every layer (SDK, AI Server,
Edge Runtime, Operations Console):

1. Any capability in the forbidden list above.
2. Any runtime mode in the forbidden list above.
3. Any HTTP verb / endpoint that emits a command, setpoint, write,
   actuation, or control payload.
4. Any code path that converts an `AdvisoryProposal` into a control
   instruction.
5. Any Operations Console action that bypasses Edge package validation.
6. Any LLM tool / function call that mutates Edge or AI Server state.
7. Any direct binding to a live PLC, PAC, SCADA, historian, OPC-UA,
   MQTT broker, or REST OT endpoint.
8. Any storage of a credential or write-grant token in a contract,
   manifest, or fixture.
9. Any Edge configuration that auto-activates a deployment package
   without a recorded operator review.
10. Any merge of a `lab/pac-edge-qualification` branch into `main`
    without independent safety review.

## Gate sequence

The following gates must be satisfied **in order** before the
corresponding step is allowed. Sprint 41 satisfies none of these
gates and does not need to; Sprint 41 only ships the capability /
safety vocabulary and validators. Each gate below is a precondition
for a later sprint's runtime feature.

### Gate A — before any new `EdgeRuntimeMode` ships

Even modes already listed as allowed (`offline_replay`,
`mock_live_read`, `advisory_audit_only`, `package_validation_only`)
require the following before code can use them:

1. SDK contract types are released (Sprint 41 / 42).
2. Capability declaration / requirement validators are merged.
3. Negative tests for forbidden tokens are merged.
4. Phase 1 fixtures pass through the SDK byte-for-byte.

### Gate B — before any `dry_run_read_only` (read-only live adapter)

`dry_run_read_only` is **not** allowed in Sprint 41 and is not
implemented until at least Phase 3 lab work. Before any code path
opens a connection to a live OT source even in read-only mode, the
following must be true:

1. Gate A is satisfied.
2. The target OT source, protocol, version, and site are named in an
   approved scope document.
3. A hazard analysis covers stale telemetry, partial reads, unit
   mismatch, replay/live confusion, and network partition.
4. The Edge advertises `serve_read_only_status` and only that —
   no write or command capability is in the declared set.
5. A read-only adapter contract is added to the SDK with deny-by-
   default capability requirements and a separate set of negative
   tests.
6. The package and the Edge both declare the adapter capability;
   neither side can default it.
7. Operations Console UI text refers to the source as **read-only**
   and the safety flags remain `no_write = no_control =
   no_live_ot_binding = True`. The new flag set adds an explicit
   `read_only_live_source` flag but does not remove existing flags.
8. Independent safety review signs off.

Until Gate B is satisfied, no live OT source is consulted in any
component. Mock adapters and replay datasets are the only data
sources.

### Gate C — before any simulated write

A **simulated write** is a code path that constructs a write-shaped
payload against a mock / simulator endpoint **without** binding to a
real OT system. Even simulated writes are forbidden until:

1. Gates A and B are satisfied.
2. The simulated write code lives on a `lab/pac-edge-qualification`
   branch (or equivalent isolated branch) and is gated by a
   `lab_only` feature flag that fails closed.
3. The SDK introduces explicit lab-only contracts for the simulated
   write, clearly separated from advisory / report types and named so
   they cannot be confused with production payloads.
4. The mock / simulator endpoint refuses connections from any
   non-loopback address by default.
5. A hazard analysis specific to the simulated write is filed.
6. Negative tests prove that the simulated write path is unreachable
   from a Phase 2 main-branch build.
7. The Operations Console does **not** expose any UI surface for
   triggering the simulated write.
8. Independent safety review signs off.

### Gate D — before any supervised write

A **supervised write** is a control-capable operation executed under
an operator's explicit, named approval. It is **not authorized** by
the current product boundary. Before any design work begins:

1. Gates A, B, and C are satisfied.
2. An explicit product approval document changes the safety boundary
   and names the operator authority model.
3. A formal hazard and risk analysis covers incorrect setpoint, stale
   telemetry, wrong tag mapping, unit mismatch, network partition,
   model error, replay/live confusion, and unauthorized operator
   action.
4. A deny-by-default capability gate is added; the new capability
   must be explicitly required and explicitly declared, and the
   default fixture set must keep it absent.
5. SDK contracts for supervised-write payloads are introduced as a
   new contract family — never reusing `AdvisoryProposal` or any
   advisory type.
6. Edge read-back verification, command/result correlation, rate
   limiting, bounds checking, deadband logic, staleness checks, unit
   validation, tag-map verification, local interlock enforcement,
   emergency disable, and watchdog timeout are all implemented.
7. Two-person activation rule: every supervised-write activation
   carries a named approver, a named second approver or independent
   reviewer, a site identifier, a package identifier, a capability
   list, and an expiration time.
8. Lab qualification runs in `lab/pac-edge-qualification` with
   simulators, mock PLC/PAC endpoints, hardware-in-the-loop where
   appropriate, fault injection, network loss, stale data, corrupt
   packages, operator cancellation, and audit replay.
9. Independent architecture, security, safety, test, documentation,
   operator procedure, and deployment/rollback review pass.
10. Approval is explicit and time-bounded; default revokes after the
    expiration time without manual renewal.

### Gate E — before any PAC-like edge work merges to `main`

PAC-like edge work belongs on a dedicated lab branch (e.g.
`lab/pac-edge-qualification`). Code from that branch may merge to
`main` only when:

1. Gates A through D (as applicable) are satisfied.
2. The merge contains **no** write / command / setpoint code path
   reachable from a Phase 2 main-branch build.
3. The merge adds qualification evidence (hazard traceability,
   rollback, audit replay, failure-mode evidence).
4. Independent safety review confirms the merge does not weaken
   existing deny-by-default behavior.
5. The merge includes negative tests proving that the forbidden
   vocabulary remains rejected.

## Local LLM / Operations Console safety restrictions

The local LLM in the Operations Console is **explanation-only**.

The local LLM **may**:

- summarize manifests, reports, advisory evaluations, calibration
  reports, model comparisons;
- explain rejected packages and rule violations;
- draft operator notes (saved as `OperatorNote` records pending
  human submission);
- answer documentation questions grounded in repository content;
- generate human-readable rationales for review decisions that the
  operator still has to make.

The local LLM **must not**:

- approve packages, modify manifests, change tag maps, or otherwise
  mutate any contract;
- call Edge Runtime APIs, AI Server activation APIs, deployment APIs,
  retraining APIs, or any mutation endpoint;
- generate control commands, setpoints, or actuation payloads in any
  form;
- suppress safety warnings, capability warnings, or rejection
  reasons;
- emit output treated as authoritative by any other component;
- be granted tool access to runtime services, even in read mode,
  without a separate approval gate;
- be exposed to free-form operator commands like "apply the
  recommended setpoint" that could be interpreted as actuation
  intent.

Operations Console UI restrictions:

1. No `execute`, `apply`, `send command`, `dispatch`, `actuate`,
   `write`, `setpoint`, or equivalent action.
2. Operator approval text reads "Approve for shadow / review
   distribution" or "Approve for audit," never "Apply" or "Execute."
3. Safety flags and forbidden / unsupported capability rejections are
   always visible; the UI cannot hide them.
4. The local LLM panel renders an explicit non-authoritative banner
   adjacent to every generated paragraph.
5. The Console's only mutation endpoints toward the AI Server are
   operator-review submissions and operator notes — never
   activation / write / control endpoints, because no such endpoints
   exist.

## Audit and evidence requirements

For each capability change, runtime-mode change, or contract change
that touches safety:

1. Edge produces an `EdgeAuditEvent` per validation attempt and per
   rejection.
2. AI Server records package generation events and refusals.
3. Operations Console records operator review decisions and any LLM
   summarization tied to a review.
4. The SDK ships a release changelog entry naming every safety flag,
   capability, or runtime mode added / changed.
5. Negative tests are added for every newly forbidden vocabulary.

## Sprint 41 enforcement scope

Sprint 41 satisfies these enforcement obligations at the SDK layer
only:

1. Canonical token lists (safety flags, allowed capabilities,
   forbidden capabilities, allowed runtime modes, forbidden runtime
   modes).
2. Validators that reject unknown / forbidden tokens.
3. Validators that reject missing safety flags.
4. Validators that reject `CapabilityRequirement` declarations
   referencing unknown or forbidden capabilities.
5. Negative tests for each rejection path.
6. Golden fixtures derived from the Phase 1 chain that pass all
   validators.

Sprint 41 does **not** implement Edge enforcement code, AI Server
package generation, Operations Console UI restrictions, or LLM
sandboxing. Those obligations apply in their respective sprints
(45–66) and must reuse the SDK token lists and validators introduced
in Sprint 41 without forking them.
