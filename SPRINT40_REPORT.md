# Sprint 40 Report — 3+1 Architecture Approval Gate

**Branch:** `sprint40`
**Base:** 3+1 planning commit `6b99877627a5a5f6f1279aaef3c3772855ef7de7`
**Type:** Planning / approval sprint only. No new runtime source code.

Sprint 40 produces the implementation-ready approval gate for the
3+1 product architecture replan landed in the prior planning commit.
It does **not** start Sprint 41 (Shared Contracts / SDK MVP) and
explicitly preserves the Phase 1 safety boundary.

## Safety boundary

The non-negotiable boundary is unchanged and reaffirmed in every
Sprint 40 document:

- No live OT binding.
- No PLC / PAC / SCADA write.
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated
  and approved.
- Future edge / PAC work begins mock, offline, simulated, dry-run,
  read-only, lab-only, and capability-gated.

## Planning outputs

| Path | Purpose |
| --- | --- |
| `docs/product/sprint40-3plus1-approval-gate.md` | Decision summary; what Sprint 40 approves; what Sprint 40 explicitly does not approve; required user approval before Sprint 41 implementation; open decisions and blockers. |
| `docs/architecture/component-ownership-matrix.md` | Detailed ownership matrix for Edge Runtime, AI / Optimization Server, Operations Console, and Shared Contracts / SDK — owns / does-not-own / inputs / outputs / allowed dependencies and edge/server/console communication boundaries. |
| `docs/architecture/phase1-api-to-component-map.md` | Mapping of Phase 1 surfaces (`TelemetryTagMap`, `ShadowReplayDataset`, `DPLCalibrationLossReport`, `AdvisoryContract`, `AdvisoryProposal`, `ShadowRuntimeReport`, `ShadowDeploymentManifest`, `EpanetImportDiagnostics`, `EpanetImportQualityReport`, etc.) to future component ownership; identifies SDK schema, AI producer, Edge / Console consumer for each. |
| `docs/architecture/contracts-inventory.md` | First contract inventory for the Shared Contracts / SDK package; categorizes by safety, envelope, telemetry, dPL/calibration, advisory, operator review, deployment manifest, edge capability, model registry, runtime report, topology projection; marks Sprint 41 MVP vs Sprint 42 first-batch vs Phase 2 vs Phase 3; documents schema-versioning expectations. |
| `docs/safety/capability-model-and-safety-gates.md` | Capability flags + defaults; allowed and forbidden runtime modes; forbidden capabilities for Sprint 41 and early Phase 2; ordered gates (A–E) before any new runtime mode, dry-run / read-only live adapter, simulated write, supervised write, or PAC-like edge merge to main; explicit local-LLM / Operations Console safety restrictions. |
| `docs/product/sprint41-shared-contracts-sdk-plan.md` | Implementation-ready Sprint 41 plan: candidate public APIs and types (`SafetyFlagSet`, `CapabilityDeclaration`, `CapabilityRequirement`, `ContractEnvelope`, `SchemaVersion`, deterministic JSON helpers, golden fixtures); TDD acceptance criteria; files to create / modify; verification commands; explicit non-goals. |
| `SPRINT40_REPORT.md` | This report. |

No `src/` change was made — Phase 1 product surface is unchanged.

## Verification commands run

All commands below were executed against the worktree at
`/home/hunter_lin/projects/aquaoptima-dphm-pinn-sprint40` on the
`sprint40` branch.

### Expected documents exist

```bash
test -f docs/product/sprint40-3plus1-approval-gate.md            # OK
test -f docs/architecture/component-ownership-matrix.md          # OK
test -f docs/architecture/phase1-api-to-component-map.md         # OK
test -f docs/architecture/contracts-inventory.md                 # OK
test -f docs/safety/capability-model-and-safety-gates.md         # OK
test -f docs/product/sprint41-shared-contracts-sdk-plan.md       # OK
test -f SPRINT40_REPORT.md                                       # OK
```

### Vocabulary audit (per-file mention counts)

Each of the six planning documents references the 3+1 component
vocabulary, sprint phasing, and the safety boundary. Per-file
mention counts for required phrases:

| Document | Shared Contracts / SDK | Edge Runtime | AI / Optimization Server | Operations Console | Sprint 41 | Phase 2 | Phase 3 | no live OT binding |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `sprint40-3plus1-approval-gate.md` | 7 | 4 | 3 | 6 | 15 | 2 | 3 | 2 |
| `component-ownership-matrix.md` | 12 | 24 | 10 | 16 | 2 | 2 | 0 | 1 |
| `phase1-api-to-component-map.md` | 0¹ | 10 | 13 | 5 | 23 | 5 | 0 | 1 |
| `contracts-inventory.md` | 1 | 1 | 0² | 0² | 11 | 34 | 10 | 1 |
| `capability-model-and-safety-gates.md` | 1 | 5 | 1 | 9 | 15 | 6 | 1 | 1 |
| `sprint41-shared-contracts-sdk-plan.md` | 2 | 3 | 2 | 3 | 25 | 2 | 2 | 1 |

¹ `phase1-api-to-component-map.md` uses the short form "SDK" (table
column "SDK schema") throughout. The full phrase appears in cross-
references.

² `contracts-inventory.md` uses "AI" and "Console" for the producer
and consumer columns to keep tables narrow. The full names appear in
the cross-referenced ownership matrix.

Per-file mention counts for forbidden-action phrasing (`no PLC/PAC/SCADA write`,
`no command emission`, `no setpoint output`):

| Document | Forbidden-action mentions |
|---|---:|
| `sprint40-3plus1-approval-gate.md` | 6 |
| `component-ownership-matrix.md` | 4 |
| `phase1-api-to-component-map.md` | 3 |
| `contracts-inventory.md` | 3 |
| `capability-model-and-safety-gates.md` | 3 |
| `sprint41-shared-contracts-sdk-plan.md` | 3 |

### Python / test suite

```bash
python -m compileall src tests
# exit 0 — bytecode compile passes across src/ and tests/

python -m pytest tests/e2e/test_phase1_shadow_mode_pipeline.py -q
# 2 passed in 2.41s

python -m pytest tests/dphm tests/models -q
# 1495 passed, 1 skipped (WNTR optional import), 3 warnings in 22.12s

python -m pytest -q
# 1633 passed, 1 skipped (WNTR optional import), 3 warnings in 99.22s
```

### Git hygiene

```bash
git diff --check
# exit 0 — no whitespace or merge-marker issues

git status --short
# ?? docs/architecture/component-ownership-matrix.md
# ?? docs/architecture/contracts-inventory.md
# ?? docs/architecture/phase1-api-to-component-map.md
# ?? docs/product/sprint40-3plus1-approval-gate.md
# ?? docs/product/sprint41-shared-contracts-sdk-plan.md
# ?? docs/safety/capability-model-and-safety-gates.md
# (SPRINT40_REPORT.md added at the end of this sprint)
```

### Secret scan over changed files

Pattern scan covered the six new docs and this report. The scan
checked for common credential / token / signing-key markers (private
key headers, common provider-specific token prefixes, and embedded
credential-assignment examples such as password, API-key, secret, or bearer forms). No
hits were returned.

## Boundary preservation evidence

- Phase 1 shadow-mode end-to-end pipeline test passes
  (`tests/e2e/test_phase1_shadow_mode_pipeline.py` — 2 cases).
- Full pytest suite passes (1633 passed, 1 optional-skip).
- No new runtime / `src/` source files were added.
- No new HTTP, network, OT, or messaging code was added.
- No command / write / setpoint / control / actuation vocabulary was
  introduced in any new document or fixture.
- Every new document restates the non-negotiable safety boundary.

## Recommended next action

1. **Review the planning outputs**, starting with
   [`docs/product/sprint40-3plus1-approval-gate.md`](docs/product/sprint40-3plus1-approval-gate.md).
2. **Record approval, deferral, or change requests** in a PR comment
   or commit message that names that approval-gate document by path.
3. On approval, **start Sprint 41** as specified in
   [`docs/product/sprint41-shared-contracts-sdk-plan.md`](docs/product/sprint41-shared-contracts-sdk-plan.md):
   ship the `aquaoptima_contracts` SDK MVP (envelope, schema version,
   `SafetyFlagSet`, capability declaration / requirement,
   deterministic JSON helpers, golden fixtures, negative tests).
4. **Do not begin AI / Edge / Operations Console runtime work** until
   the Sprint 41 SDK is merged and the contract inventory for
   Sprint 42 is unblocked.
5. **Keep the existing Phase 1 chain importable from
   `aquaoptima.dphm`** for the entire approved planning window;
   Sprint 41 ships SDK projections, not renames.

Hermes will independently verify, commit, push, and update Plane.
This sprint does not commit or push.
