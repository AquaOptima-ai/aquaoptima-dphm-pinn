# Component Boundaries and Qualification Gates

## Recommendation and approval gate

This document defines the safety and qualification boundaries for the AquaOptima 3+1 architecture: Edge Runtime, AI / Optimization Server, Operations Console, and Shared Contracts / SDK.

**Do not start Sprint 40 implementation until the user explicitly approves the replan.** Sprint 40 should be used to approve the component boundaries, Shared Contracts / SDK ownership, capability gates, roadmap changes, and safety restrictions before any code implementation begins.

The mandatory safety boundary is:

- No live OT binding.
- No PLC / PAC / SCADA write.
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated and approved.
- Any future PAC/edge work starts mock, simulated, offline, dry-run, read-only, lab-only, and capability-gated.

## Phase 2 versus Phase 3

### Phase 2: advisory / supervised-review product

Phase 2 is an operator-supervised advisory and audit product. It can move beyond Phase 1 offline validation into a GB10 + edge + console product shape while preserving the safety boundary.

Allowed Phase 2 capabilities:

- Edge Runtime package validation.
- Edge Runtime offline replay execution.
- Mock live-read style telemetry, without live OT binding.
- Read-only health/status reporting.
- Advisory proposal generation by the AI / Optimization Server.
- Advisory review in the Operations Console.
- Operator review and package approval records.
- Deployment package review and distribution workflow.
- Audit trails for proposal evaluation and package activation.
- Local LLM explanation and summarization with strict restrictions.

In Phase 2, if an advisory proposal is accepted by rules or approved by an operator, the meaning is:

> Accepted for advisory display, audit, or supervised review.

It does not mean:

> Authorized for actuation, command dispatch, PLC/PAC/SCADA write, or setpoint output.

### Phase 3: qualified PAC-like edge preparation

Phase 3 is a different category: qualified PAC-like edge preparation. It is not merely a feature extension of Phase 2 and does not grant write/control authority by default.

Phase 3 should begin with a lab-only qualification path and stronger evidence:

- Formal capability model.
- Qualification plan.
- Hazard analysis.
- Failure mode analysis.
- Runtime mode separation.
- Cybersecurity review.
- Secure package provenance.
- Operator authority model.
- Site acceptance test template.
- Rollback and safe-state behavior.
- Independent safety review.
- Hardware/environment qualification if targeting PAC-like deployment.
- Evidence that unsupported or unsafe capabilities are rejected by default.

Recommended distinction:

| Area | Phase 2 | Phase 3 |
|---|---|---|
| Product class | Advisory / supervised review | Qualified PAC-like edge preparation |
| Control authority | None | Not by default; future authority requires separate approval |
| Edge mode | Mock/replay/read-only/dry-run | Lab-qualified, still gated |
| OT binding | Not live | Lab-only first; live binding requires separate approval |
| Writes | Prohibited | Prohibited until explicit qualification gate is passed |
| Operator role | Review and acknowledge | Review plus qualified operating procedure |
| Evidence level | Product safety evidence | Qualification and site safety evidence |
| Branch strategy | Mainline Phase 2 product hardening | Separate lab branch until qualified |

## Component safety responsibilities

### Shared Contracts / SDK

Owns the shared safety vocabulary and capability model:

- Safety flags.
- Capability declarations.
- Capability requirements.
- Safety boundary acknowledgements.
- Manifest safety declarations.
- Edge validation result payloads.
- Audit event envelopes.

Rules:

- Safety vocabulary is defined once in Shared Contracts / SDK.
- No deployable defines a private meaning for `read_only`, `no_write`, `no_control`, `no_live_ot_binding`, or `no_setpoint_output`.
- Current contracts do not include command/write/setpoint payloads.

### Edge Runtime

Owns local enforcement:

- Reject unsafe deployment packages.
- Reject missing safety flags.
- Reject unsupported schema major versions.
- Reject unknown required capabilities.
- Reject write/control/setpoint/live OT capability requests.
- Produce validation results for every activation attempt.
- Emit health/status/audit reports.

The Edge Runtime must be deny-by-default. Unsupported means rejected, not ignored.

### AI / Optimization Server

Owns server-side generation and intelligence:

- Generate deployment packages.
- Produce model artifacts and registry records.
- Produce calibration reports.
- Generate advisory proposals.
- Ingest edge reports.
- Refuse packages that exceed current approved capability boundaries.

The AI Server must not directly bind to live OT, dispatch commands, or emit setpoints.

### Operations Console

Owns human workflow:

- Display safety boundaries.
- Display package and report evidence.
- Capture operator review records.
- Capture package approval records.
- Show model comparisons and audit history.
- Offer local LLM explanation-only assistance.

The Operations Console must not become a hidden control plane. It must not include execute/apply/send-command behavior in Phase 2.

## Edge Runtime capability model

### Allowed current runtime modes

- `offline_replay`
- `mock_live_read`
- `advisory_audit_only`
- `package_validation_only`
- `dry_run_read_only`, only after explicit approval for a safe read source

### Not allowed current runtime modes

- `control_enabled`
- `closed_loop_control`
- `live_write`
- `setpoint_output`
- `command_dispatch`

### Default supported capabilities

- `load_signed_or_hashed_package`
- `validate_manifest`
- `validate_checksums`
- `validate_schema_versions`
- `validate_safety_flags`
- `validate_tag_map`
- `run_shadow_replay`
- `run_mock_read`
- `evaluate_advisory_contract`
- `produce_shadow_runtime_report`
- `upload_health_report`
- `upload_audit_event`
- `serve_read_only_status`

### Default forbidden capabilities

- `live_ot_bind_write`
- `plc_write`
- `pac_write`
- `scada_write`
- `setpoint_output`
- `command_emit`
- `actuator_control`
- `closed_loop_control`
- `remote_control_api`
- `llm_command_execution`
- `operator_chat_to_control`
- `unreviewed_package_activation`

## Package validation rejection rules

The Edge Runtime must reject a package if:

- Safety flags are missing.
- Safety flags conflict with the current product boundary.
- Required capabilities exceed supported capabilities.
- Package references unknown schema major versions.
- Checksums fail.
- Artifact provenance is missing.
- Advisory contract contains command-like semantics.
- Telemetry tag map contains unsupported axes or unit ambiguity.
- Package attempts to enable write/control behavior.
- Package was not approved through the required workflow.

Every validation attempt, including rejection, should produce an `EdgePackageValidationResult` defined by Shared Contracts / SDK.

## Gates before any future write/control path

No write/control path is allowed in Phase 2. Before any future write/control path is even designed, all gates below must be satisfied.

### Gate 0: explicit product approval

Required evidence:

- Approved scope statement.
- Target environment.
- Controlled variables.
- Forbidden operations.
- Operator authority model.
- Formal statement that the current safety boundary is intentionally changing.

### Gate 1: hazard and risk analysis

Required analysis:

- Incorrect setpoint.
- Stale telemetry.
- Wrong tag mapping.
- Unit mismatch.
- Network partition.
- Model error.
- Replay/live confusion.
- Unauthorized operator action.
- Safe-state definition.
- Rollback and disable procedure.

### Gate 2: deny-by-default capability enforcement

Dangerous capabilities must be absent by default and impossible to activate accidentally. Examples include:

- `live_ot_bind_read`
- `live_ot_bind_write`
- `setpoint_output`
- `command_emit`
- `closed_loop_control`
- `pac_write_adapter`
- `plc_write_adapter`
- `scada_write_adapter`
- `remote_actuation`
- `llm_action_execution`

### Gate 3: contract and schema review

Shared Contracts / SDK must not introduce command/write/setpoint contracts until approved. Advisory payloads and control payloads must remain separate concepts.

Required evidence:

- Naming review.
- Safety semantics review.
- Versioning review.
- Backward compatibility review.
- Negative tests proving older Phase 2 edges reject control-capable payloads.
- No ambiguous reuse of `AdvisoryProposal` as a command.

### Gate 4: operator approval and two-person activation rule

Any future activation of write/control capability should require:

- Named operator approval.
- Safety boundary acknowledgement.
- Site identifier.
- Package identifier.
- Capability list.
- Expiration time.
- Second approver or independent reviewer for hazardous capabilities.
- Immutable audit record.

Approval to deploy a package is not approval to actuate.

### Gate 5: read-back and interlock requirements

Before writes are possible, there must be:

- Read-back verification.
- Command/result correlation.
- Rate limiting.
- Bounds checking.
- Deadband logic.
- Staleness checks.
- Unit validation.
- Tag-map verification.
- Local interlock enforcement.
- Emergency disable.
- Watchdog timeout.
- Safe degradation behavior.

### Gate 6: lab qualification before site exposure

Control-capable behavior, if ever approved, must first be proven in a lab branch using simulators, mock PLC/PAC endpoints, hardware-in-the-loop where appropriate, fault injection, network loss, stale data, corrupt packages, operator cancellation, and audit replay.

### Gate 7: independent safety review

Before merging to main or offering to a site:

- Architecture review.
- Security review.
- Safety review.
- Test evidence review.
- Documentation review.
- Operator procedure review.
- Deployment/rollback review.

Until all gates pass, any write/control code remains out of main or disabled behind non-production lab flags.

## Operations Console and local LLM restrictions

The Console may:

- Display Edge Runtime health.
- Display active package and validation result.
- Display shadow runtime reports.
- Display advisory proposals and evaluations.
- Display model lineage and calibration reports.
- Display safety flags and capability requirements.
- Support operator package review.
- Capture operator notes and safety acknowledgements.
- Provide documentation search.
- Use a local LLM to summarize or explain artifacts.

The Console must not:

- Send setpoints.
- Send commands.
- Dispatch control actions.
- Bypass Edge Runtime package validation.
- Treat operator approval as actuation authority.
- Provide execute/apply/send-command buttons.
- Provide chat-driven action execution.
- Hide safety flags or capability warnings.
- Convert advisory proposals into control payloads.

The local LLM must not approve packages, modify manifests, change tag maps, invoke Edge Runtime APIs, invoke AI Server activation APIs, generate control commands, suppress safety warnings, or bypass capability gates.

## PAC edge lab branch strategy

Phase 3 PAC-like edge work should begin in a dedicated lab branch, such as:

```text
lab/pac-edge-qualification
```

Allowed in the lab branch:

- Mock PAC adapters.
- Simulated PLC/PAC endpoints.
- Read-only adapter interfaces.
- Capability declaration experiments.
- Package validation hardening.
- Edge watchdog prototypes.
- Fault injection tests.
- Qualification documentation.

Not allowed without additional approval:

- Live site connection.
- Real PLC/PAC/SCADA writes.
- Production credentials.
- Production network assumptions.
- Merge of write-capable APIs into main.
- Control endpoints exposed by default.
- LLM-to-edge action tooling.
- Reuse of advisory contracts as command contracts.

## Do-not-cross boundaries for the next 5-8 sprints

1. Do not add live OT writes.
2. Do not add live OT binding by default.
3. Do not let advisory become control.
4. Do not give the Console direct control authority.
5. Do not give the LLM tool authority.
6. Do not merge PAC lab work prematurely.
7. Do not fork safety vocabulary outside Shared Contracts / SDK.
8. Do not skip audit evidence.
9. Do not treat GB10 co-location as shared internals.
10. Do not start Sprint 40 implementation before planning artifacts are approved.

Recommended near-term work is to mature Phase 2 as an auditable advisory and supervised-review product while preparing Phase 3 qualification evidence separately.