# AquaOptima dPHM-PINN: CODESYS → Schneider EAE Runtime Migration
## Gated Sprint Roadmap (Sprint 54+)

**Document Status:** Grounding & Planning  
**Sprint Numbering:** Sprint 54 onwards (follows Sprint 52: vendor PAC inventory, Sprint 53: site data intake contract)  
**Current Test Baseline:** 655 tests GREEN, ~1.3s (tests/aquaoptima_contracts/)  
**Migration Verification Target:** 655+ tests GREEN, pass count unchanged or increased only by new coverage

---

## 1. Executive Summary

### What Changes (Substrate Evolution)

**Runtime Substrate Migration:**  
The AquaOptima edge integration is migrating from CODESYS V3 to **Schneider EcoStruxure Automation Expert (EAE)** runtime on the PAC side. This migration affects our read-only OT/IT data ingress protocols and deployment readiness contracts.

**IEC Standards Update (ADDITIVE, not replacement):**  
EAE implements **IEC 61499** (event-driven distributed function blocks), which **EXTENDS IEC 61131-3** — it does NOT replace it. Our codebase will:
- **KEEP** all existing IEC 61131-3 references (they remain valid; 61499 reuses 61131-3 logic concepts)
- **ADD** IEC 61499 references for Service Interface Function Blocks (SIFBs), distributed event-driven comms, and EAE-native ingress protocols
- **NEVER** rename `61131` tokens to `61499` — both coexist as layered standards

**Hardware Profile (Confirmed Sales-Ready):**  
- **AMAX-8580 ONLY** (Advantech confirmed sales-ready; AMAX-5580 fully retired)
- Edge profile id token: `amax8580_cpu` (unchanged)
- **Vendor confirmation REOPENED** for EAE-specific integration facts: EAE runtime availability on AMAX-8580 SKU, EtherCAT master under EAE, OS image, licensing/package structure, Python/ONNX sidecar co-tenancy beside EAE real-time runtime → becomes SPIKE work

**Why EAE is Better (IEC 61499 Benefits):**  
- Vendor-independent function block format and first-class Service Interface Function Blocks (SIFBs) for inter-device comms/sync
- Read-only data ingress becomes cleaner and more declarative (less bolt-on OPC UA/Modbus glue, more native protocol surface)
- Expected faster path to **IEC 62443** (industrial cybersecurity) compliance → new security posture requirements for our sidecar (signed evidence, audit logs, network segmentation posture)

**Migration Honesty Caveat:**  
"Compliable with" ≠ "zero-effort lift." IEC 61131-3 → 61499 migration pitfalls are documented in literature. That effort sits in the PAC (their) layer, but our integration contracts must adapt to EAE's protocol surface. We treat this as a **tested code change** with gated verification, not prose-only.

### What Does NOT Change (Safety Boundary — Sacred)

**AquaOptima Role (Unchanged):**  
- Advisory/inference/validation/dry-run proposal/read-only health-status evidence SIDECAR ONLY
- No live OT binding; no PLC/PAC/SCADA write; no command emission; no setpoint output; no control-loop closure; no Python EtherCAT master; no PAC project generator
- EAE (not AquaOptima) owns hard real-time control, field I/O, interlocks, actuator authority, HMI
- AquaOptima integrates AROUND this substrate, read-only

**Planning Safety Flags (Stamp on Every Doc):**  
```yaml
evaluation_mode: offline_only
write_path: none
influences_control: false
site_integration_allowed: false
```

---

## 2. Sprint Table: Gated Roadmap (Sprint 54–60)

| Sprint # | Title | Type | Confirmed / Vendor-Dependent | Go/No-Go Gate | Depends On |
|----------|-------|------|------------------------------|---------------|------------|
| **54** | ADR: CODESYS→EAE Runtime Decision Record | docs | Confirmed (planning-only) | Test baseline GREEN (655) | — |
| **55** | SPIKE: EAE-on-AMAX-8580 Vendor Confirmation (Runtime/EtherCAT/OS/Licensing/Co-Tenancy) | spike | **Vendor-Dependent** | SPIKE report delivered, facts confirmed or blocked | Sprint 54 complete |
| **56** | read_only_integration.py: Migrate CODESYS Protocols → EAE/61499 SIFB Ingress (Add 61499, Keep 61131-3) | code | Depends on Sprint 55 facts | Tests pass (unchanged count), contract schema valid, E2E verify | Sprint 55 unblocked |
| **57** | deployment_readiness.py + vendor_pac_inventory.py: Identifier Migration (CODESYS → EAE, Versioned Schema) | code | Depends on Sprint 55 facts | Tests pass (unchanged count), v2 schema valid | Sprint 56 complete |
| **58** | feasibility.py + supervisory_gatekeeper.py: Identifier Migration + Governance Safety Check | code | Confirmed (internal contracts) | Tests pass, forbidden-vocab regex unbroken | Sprint 57 complete |
| **59** | IEC 62443 Sidecar Security Posture Sprint (Signed Evidence, Audit Log, Network Segmentation Design) | security | Confirmed (new design area) | SECURITY.md drafted, Morris/Kevin escalation recorded | Sprint 58 complete |
| **60** | Docs Sync: Hardware/ADR/PRD/GLOSSARY/ARCHITECTURE Update (GitHub Canonical, Plane Ledger) | docs | Confirmed | Docs consistent, CODESYS→EAE narrative complete, historical records immutable | Sprint 59 complete |

**Gate Discipline:**  
- **Sprint 54 ONLY** moves to **Planned** (planning sprint, docs-only, current sprint)
- **Sprints 55–60** remain **Backlog/Candidate** until prior gate opens
- **Sprint 55 (SPIKE)** is a **blocking gate**: if vendor facts are unavailable, downstream code sprints (56–58) cannot proceed; we document the block and escalate
- No code/contract changes execute until Sprint 55 unblocks or provides fallback guidance

---

## 3. Detailed Sprint Plans (Sprint 54–60)

---

### **Sprint 54: ADR – CODESYS→EAE Runtime Decision Record (Docs-Only)**

**Status:** Planned (Current Sprint)  
**Type:** Documentation  
**Confirmed/Vendor-Dependent:** Confirmed (planning-only, no vendor dependency in this sprint)

#### Goal & Business Value
Document the architectural decision to migrate from CODESYS V3 to Schneider EAE runtime with IEC 61499 support. This ADR establishes the **why** (cleaner read-only ingress, IEC 62443 path, vendor-independent SIFBs), the **what** (EAE/61499 extends 61131-3, AMAX-8580-only), and the **constraints** (safety boundary unchanged, vendor confirmation required). It supersedes prior runtime assumptions without editing immutable ADR-0001/0002.

**Business Value:**  
- Creates a grounded, traceable architectural record for the migration (canonical GitHub, ledger Plane)
- Establishes that IEC 61131-3 and 61499 coexist (prevents identifier-renaming mistakes)
- Documents reopened vendor-confirmation gates (protects against ungrounded assumptions)

#### Concrete Tasks / Plane Issues (5–8)
1. `[PLAN-54.1] Write ADR-000X: CODESYS→EAE Runtime Migration Decision (Superseding Pattern)`
2. `[PLAN-54.2] Document IEC 61499 EXTENDS IEC 61131-3 (both standards coexist, additive)`
3. `[PLAN-54.3] List EAE benefits (SIFB-based ingress, IEC 62443 path) and migration pitfalls (honest caveat)`
4. `[PLAN-54.4] Specify AMAX-8580-ONLY hardware profile, note AMAX-5580 retirement`
5. `[PLAN-54.5] Reopen vendor-confirmation gates (EAE runtime on SKU, EtherCAT, OS, licensing, co-tenancy) → flag as SPIKE (Sprint 55)`
6. `[PLAN-54.6] Reaffirm safety boundary unchanged (advisory-only, no write/control, no PAC project gen)`
7. `[PLAN-54.7] Link to Sprint 55–60 roadmap (this doc) as execution plan`
8. `[PLAN-54.8] Commit ADR-000X + planning roadmap to docs/adr/, docs/planning/`

#### Acceptance Criteria
- [ ] ADR-000X file exists in `docs/adr/000X-codesys-to-eae-runtime-migration.md`
- [ ] ADR includes: Context (why EAE), Decision (EAE/61499, AMAX-8580), Consequences (vendor SPIKE, 62443 posture, identifier migration plan), Status (Proposed)
- [ ] ADR explicitly states: "IEC 61499 EXTENDS IEC 61131-3; both remain valid; never rename 61131 tokens to 61499"
- [ ] ADR lists reopened vendor gates → Sprint 55 SPIKE dependency
- [ ] ADR reaffirms safety boundary (evaluation_mode=offline_only, write_path=none, influences_control=false, site_integration_allowed=false)
- [ ] Planning roadmap (this document) saved to `docs/planning/codesys-eae-migration-roadmap-sprint54-60.md`
- [ ] No production code/contract/test changes in Sprint 54 (docs-only)
- [ ] GitHub commit, Plane issue closed

#### Files Likely Touched
- **New:** `docs/adr/000X-codesys-to-eae-runtime-migration.md` (X = next sequential ADR number; check existing ADRs, likely 0003 or 0004)
- **New:** `docs/planning/codesys-eae-migration-roadmap-sprint54-60.md` (this document)
- **Reference (read-only):** `docs/adr/0001-ot-it-decoupling.md`, `docs/adr/0002-amax8580-cpu-only-edge.md` (immutable; ADR-000X supersedes assumptions, does not edit)

#### Tests to Add/Modify
None (docs-only sprint).

#### E2E Verification Command & Expected Output
```bash
# Verify ADR file exists and contains required sections
ls -lh docs/adr/000X-codesys-to-eae-runtime-migration.md
grep -q "IEC 61499 EXTENDS IEC 61131-3" docs/adr/000X-codesys-to-eae-runtime-migration.md && echo "✓ 61499/61131-3 coexistence documented"
grep -q "evaluation_mode.*offline_only" docs/adr/000X-codesys-to-eae-runtime-migration.md && echo "✓ Safety boundary reaffirmed"
grep -q "Sprint 55.*SPIKE.*vendor" docs/adr/000X-codesys-to-eae-runtime-migration.md && echo "✓ SPIKE dependency documented"

# Verify planning roadmap
ls -lh docs/planning/codesys-eae-migration-roadmap-sprint54-60.md
grep -q "Sprint 54.*ADR.*Planned" docs/planning/codesys-eae-migration-roadmap-sprint54-60.md && echo "✓ Roadmap includes Sprint 54"
grep -q "Sprint 55.*SPIKE.*Backlog" docs/planning/codesys-eae-migration-roadmap-sprint54-60.md && echo "✓ Sprint 55+ gated"
```

**Expected Output:**  
All `grep` checks print `✓` confirmations; ADR and roadmap files exist with required content.

#### Stop Conditions
- If ADR-000X cannot establish a clear superseding relationship to prior ADRs without contradicting them → escalate to Morris/Kevin for architectural narrative review
- If planning roadmap attempts to make Sprint 55+ "Planned" (violates gate discipline) → revert to Backlog/Candidate status

#### Safety Boundary Line
```yaml
# Sprint 54 Safety Flags (Planning-Only)
evaluation_mode: offline_only
write_path: none
influences_control: false
site_integration_allowed: false
sprint_type: documentation_only
code_execution: none
vendor_confirmation_required: true  # Sprint 55 SPIKE
```

#### Suggested Commit Message
```
docs: ADR-000X CODESYS→EAE runtime migration decision (Sprint 54)

- Add ADR-000X documenting CODESYS V3 → Schneider EAE migration
- IEC 61499 EXTENDS IEC 61131-3 (both coexist, additive not replacement)
- AMAX-8580-ONLY hardware profile (AMAX-5580 retired)
- Reopen vendor-confirmation gates → Sprint 55 SPIKE
- Reaffirm safety boundary (advisory-only, no write/control)
- Add Sprint 54–60 gated migration roadmap to docs/planning/

Sprint 54 complete. Gate open for Sprint 55 (SPIKE, vendor-dependent).

Related: Sprint 52 (vendor PAC inventory), Sprint 53 (site data intake)
```

---

### **Sprint 55: SPIKE – EAE-on-AMAX-8580 Vendor Confirmation (Runtime/EtherCAT/OS/Licensing/Co-Tenancy)**

**Status:** Backlog (Gate: Sprint 54 complete, test baseline GREEN)  
**Type:** SPIKE (Vendor-Dependent Investigation)  
**Confirmed/Vendor-Dependent:** **Vendor-Dependent** (blocks Sprints 56–58 if unconfirmed)

#### Goal & Business Value
Reopen vendor-confirmation gates for EAE-specific integration facts on AMAX-8580 hardware. The vendor_pac_inventory.py module was built on CODESYS-grounded facts; switching to EAE makes these facts **unconfirmed** until Schneider/Advantech verify. This SPIKE produces a grounded fact report or documents a block.

**Business Value:**  
- Prevents building on ungrounded assumptions (protects 655-test GREEN baseline)
- Establishes concrete integration contracts for EAE runtime (enables Sprint 56–58 code migration)
- Documents vendor blockers early (avoids wasted downstream rework if facts unavailable)

#### Concrete Tasks / Plane Issues (5–8)
1. `[SPIKE-55.1] Confirm EAE runtime availability on AMAX-8580 SKU (Schneider product matrix check)`
2. `[SPIKE-55.2] Confirm EtherCAT master support under EAE runtime (vs. CODESYS built-in EtherCAT)`
3. `[SPIKE-55.3] Confirm OS image/kernel for AMAX-8580 + EAE (Linux RTE? Windows Embedded? Version?)`
4. `[SPIKE-55.4] Confirm EAE licensing model & package structure (vs. CODESYS Control RTE packages)`
5. `[SPIKE-55.5] Confirm Python 3.10+ / ONNX Runtime sidecar co-tenancy beside EAE real-time runtime (resource isolation, CPU affinity, no RT interference)`
6. `[SPIKE-55.6] Document IEC 61499 SIFB protocol surface for read-only ingress (replaces CODESYS symbol subscription / shared memory)`
7. `[SPIKE-55.7] Write SPIKE report (grounded facts → proceed, or blocked → escalate)`
8. `[SPIKE-55.8] If blocked: propose fallback plan (keep CODESYS contracts as abstract base, EAE as future opt-in, or pause migration)`

#### Acceptance Criteria
- [ ] SPIKE report document created: `docs/spikes/sprint55-eae-amax8580-vendor-confirmation.md`
- [ ] Report records, per question, one of: `confirmed_by_vendor` (with source/citation), `vendor_confirmation_required` (still open), or `blocked` (with reason)
- [ ] Each open/blocked item maps to a `vendor_confirmation_status` value to be set in `vendor_pac_inventory.py` (Sprint 57), not asserted as fact
- [ ] A go/no-go recommendation for Sprints 56–58 is stated explicitly (proceed / proceed-partial / pause)
- [ ] If blocked: fallback plan documented (keep CODESYS contracts as abstract base + EAE as opt-in, or pause migration) and escalated to Morris/Kevin
- [ ] No production code/contract/test changes (research/docs only)

#### Files Likely Touched
- `docs/spikes/sprint55-eae-amax8580-vendor-confirmation.md` (new)
- (read-only reference) `docs/hardware/amax-8580-vendor-pac-software-inventory.md`

#### Verification Command + Expected Output
```bash
test -f docs/spikes/sprint55-eae-amax8580-vendor-confirmation.md && echo "SPIKE report present"
grep -qE "go/no-go|recommendation" docs/spikes/sprint55-eae-amax8580-vendor-confirmation.md && echo "decision recorded"
git diff --name-only | grep -vqE '^docs/' && echo "FAIL: non-doc change" || echo "docs-only OK"
```

#### Stop Conditions
- HARD STOP if any vendor fact cannot be confirmed AND no defensible fallback exists → escalate, do not proceed to Sprint 56.

#### Safety Boundary
`evaluation_mode=offline_only`, `write_path=none`, `influences_control=false`, `site_integration_allowed=false`. Research only; no code, no contract change.

#### Suggested Commit Message
`docs(spike): Sprint 55 — EAE-on-AMAX-8580 vendor confirmation report + go/no-go`

---

### Sprints 56–60 (summary — full detail in the sprint table, section 2)

Sprints 56–60 are **Backlog/Candidate**, each gated on the prior sprint's verification:

- **Sprint 56 — `read_only_integration.py`:** migrate `PROTOCOL_CODESYS_SYMBOL` / `PROTOCOL_CODESYS_SHARED_MEMORY` ingress to EAE/61499 SIFB-based read-only ingress; ADD 61499, KEEP 61131-3; tests pass with **unchanged count (655)**; still no write path. Depends on Sprint 55 facts.
- **Sprint 57 — `deployment_readiness.py` + `vendor_pac_inventory.py`:** identifier migration (`AMAX_RUNTIME_*_CODESYS`, `READINESS_CATEGORY_CODESYS_PACKAGE`, `PRODUCT_CATEGORY_CODESYS_READY_PAC`, `OWNER_AMAX_CODESYS_PAC`); bump inventory id `_v1 → _v2`; set EAE rows to `vendor_confirmation_required` until SPIKE confirms.
- **Sprint 58 — `feasibility.py` + `supervisory_gatekeeper.py`:** identifier migration + explicit governance forbidden-vocab regex integrity check (guard strings unchanged).
- **Sprint 59 — IEC 62443 sidecar SECURITY posture:** `SECURITY.md` draft (signed evidence, audit log, network segmentation posture); **Morris/Kevin escalation recorded**. Confirm real security target before pulling to Planned.
- **Sprint 60 — Docs sync:** ARCHITECTURE / PRD / GLOSSARY / hardware docs reconciled to EAE narrative; ADRs 0001/0002 superseded (not edited); historical `SPRINTNN_REPORT.md` untouched.

---

## 4. Sprint Status / Chaining Rule

- **Sprint 54 (this planning sprint): `Planned`** — docs-only.
- **Sprints 55–60: `Backlog` / `Candidate`** — each pulled to `Planned` only after the previous sprint's verification gate passes.
- We do **not** pre-chain multiple code/safety sprints as `Planned`. Sprint 55 (SPIKE) is the immediate next gate; everything downstream depends on its outcome. This preserves the "isolate the first empirical/vendor-dependent gate as its own checkpointed launch" discipline.