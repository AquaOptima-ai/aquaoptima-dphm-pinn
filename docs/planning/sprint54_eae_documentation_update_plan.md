# AquaOptima dPHM-PINN: CODESYS → EAE Migration Documentation Update Plan

**Document Status:** Planning – Documentation Update Strategy  
**Sprint Scope:** Sprint 54–60 (follows code migration roadmap)  
**Documentation Model:** Three-layer (GitHub canonical, Plane ledger, Drive narrative)  
**Core Principle:** ONE FACT ONE HOME  
**Current Sprint:** Sprint 54 (planning-only, docs/planning/ additions)

---

## 1. Executive Summary: Documentation Migration Strategy

This plan governs documentation changes that follow the CODESYS → EAE runtime migration across Sprint 54–60. It implements the three-layer documentation model:

1. **GitHub (Canonical Technical Truth):** In-repo `/docs`, changes via PR, same-PR rule (doc changes land in same PR as code they document), immutable historical records
2. **Plane (Live Operational Ledger):** Links to GitHub anchors, never restates facts, tracks work execution, merge-audit comments reference GitHub docs
3. **Drive/AOPSO (Stakeholder Narrative):** Links down to GitHub/Plane, high-level summaries for non-technical stakeholders

**ONE FACT ONE HOME Rule:**  
- Technical facts (protocols, hardware specs, IEC standards, safety constraints) → GitHub docs ONLY
- Work status, sprint progress, issue lifecycle → Plane ONLY (links to GitHub for technical grounding)
- Stakeholder summaries → Drive ONLY (links to GitHub/Plane, never duplicates technical content)

**Same-PR Rule (GitHub):**  
Every code-modifying sprint (56–58) includes doc updates in the SAME pull request as the code changes. No separate "docs catch-up" PRs. This keeps docs synchronized with code at commit granularity.

**Historical Immutability:**  
- Existing ADRs (ADR-0001, ADR-0002) are NEVER edited; new ADR-000X supersedes their assumptions
- Historical sprint reports (`SPRINTNN_REPORT.md`) stay UNEDITED; new sprint reports document migration progress
- CODESYS references in historical docs remain as comparative/historical context

**Documentation Freshness Discipline:**  
Every sprint includes a doc-freshness verification step: check internal links, verify external references (IEC standards URLs, vendor product pages), update owner/last-reviewed timestamps.

---

## 2. GitHub Documentation Changes (Canonical Technical Truth)

### 2.1 New ADR: ADR-000X CODESYS → EAE Runtime Migration Decision

**Sprint:** 54 (Current Sprint, Planning)  
**Status:** NEW file, not an edit  
**File Path:** `docs/adr/000X-codesys-to-eae-runtime-migration.md` (where X = next sequential ADR number, likely 0003 or 0004; verify existing ADRs first)  
**PR Association:** Sprint 54 planning PR (docs-only)  
**Same-PR Rule:** N/A (no code changes in Sprint 54)

**Content Requirements:**

1. **Title & Metadata:**
   ```markdown
   # ADR-000X: CODESYS V3 → Schneider EAE Runtime Migration
   
   **Status:** Proposed  
   **Date:** 2025-01-XX  
   **Supersedes:** Implicit runtime assumptions in ADR-0001, ADR-0002 (does not edit them)  
   **Context:** Sprint 54–60 migration roadmap  
   **Deciders:** Morris Chen (Tech Lead), Kevin (Safety/Advisory Lead)
   ```

2. **Context Section (Why EAE):**
   - Document business/technical drivers: cleaner read-only ingress via IEC 61499 SIFBs, vendor-independent function blocks, expected faster path to IEC 62443 compliance
   - State hardware constraint: AMAX-8580 ONLY (Advantech confirmed sales-ready; AMAX-5580 retired)
   - Reference Sprint 52 (vendor PAC inventory), Sprint 53 (site data intake contract) as prior grounding work
   - Acknowledge migration honesty caveat: "IEC 61131-3 → 61499 migration pitfalls exist; we treat this as tested code change with gated verification, not prose-only"

3. **Decision Section (What Changes):**
   - **Runtime Substrate:** CODESYS V3 → Schneider EcoStruxure Automation Expert (EAE)
   - **IEC Standards:** IEC 61499 EXTENDS IEC 61131-3 (ADDITIVE, not replacement; both standards coexist in codebase)
   - **Hardware Profile:** AMAX-8580-only edge profile (`amax8580_cpu` token unchanged)
   - **Vendor Confirmation Reopened:** EAE runtime availability on AMAX-8580 SKU, EtherCAT master support, OS image, licensing/package structure, Python/ONNX sidecar co-tenancy → becomes Sprint 55 SPIKE work
   - **Safety Boundary UNCHANGED:** Advisory/inference/validation/dry-run proposal/read-only health-status evidence sidecar ONLY; no live OT binding; no PLC/PAC/SCADA write; no command emission; no setpoint output; no control-loop closure; no Python EtherCAT master; no PAC project generator

4. **Consequences Section:**
   - **Code Migration (Sprints 56–58):** Identifier migration (CODESYS tokens → EAE tokens) in `read_only_integration.py`, `deployment_readiness.py`, `vendor_pac_inventory.py`, `feasibility.py`, `supervisory_gatekeeper.py`
   - **New Security Posture (Sprint 59):** IEC 62443 compliance requirements for sidecar (signed evidence, audit logs, network segmentation design) → new SECURITY.md
   - **Vendor SPIKE Dependency (Sprint 55):** BLOCKING gate; if vendor facts unavailable, Sprints 56–58 cannot proceed; document block and escalate
   - **Documentation Sync (Sprint 60):** Hardware docs, PRD, GLOSSARY, ARCHITECTURE, INTERFACES, DEPLOYMENT updates to reflect EAE/61499
   - **Test Baseline Protection:** 655 tests GREEN, ~1.3s; migration must maintain or increase pass count (no regressions)

5. **Status Justification:**
   - **Proposed:** Migration roadmap documented (Sprint 54); awaits Sprint 55 SPIKE completion for vendor confirmation
   - **Acceptance Criteria for "Accepted" Status:** Sprint 55 SPIKE delivers grounded vendor facts (EAE runtime on AMAX-8580 confirmed), Sprint 56–58 code migrations complete with tests GREEN, Sprint 59 security posture documented, Sprint 60 docs synced
   - **Rejection Criteria:** Sprint 55 SPIKE finds vendor blockers (EAE unavailable on AMAX-8580, EtherCAT unsupported, co-tenancy prohibited) → fallback to CODESYS or pause migration

6. **Cross-References:**
   - Links to: Sprint 54–60 roadmap (`docs/planning/codesys-eae-migration-roadmap-sprint54-60.md`), ADR-0001 (OT/IT decoupling), ADR-0002 (AMAX-8580 CPU-only edge), future Sprint 55 SPIKE report (`docs/spikes/sprint55-eae-amax8580-vendor-confirmation.md`)
   - External links: IEC 61499 standard overview (iec.ch or IEEE Xplore), Schneider EAE product page (se.com), IEC 62443 industrial cybersecurity standard

**Verification (Sprint 54 acceptance):**
```bash
# Check ADR file exists and contains required sections
ls -lh docs/adr/000X-codesys-to-eae-runtime-migration.md
grep -q "IEC 61499 EXTENDS IEC 61131-3" docs/adr/000X-*.md && echo "✓ Standards coexistence documented"
grep -q "evaluation_mode.*offline_only" docs/adr/000X-*.md && echo "✓ Safety boundary reaffirmed"
grep -q "Sprint 55.*SPIKE.*vendor" docs/adr/000X-*.md && echo "✓ SPIKE dependency flagged"
grep -q "Status.*Proposed" docs/adr/000X-*.md && echo "✓ Status = Proposed (pre-SPIKE)"
```

---

### 2.2 Affected Existing Docs: Keep / Link / Supersede / Migrate-Content Decisions

For each existing doc, we specify the change pattern and WHICH sprint PR it lands in (same-PR rule).

#### 2.2.1 `ARCHITECTURE.md` (Root-Level)

**Change Pattern:** MIGRATE-CONTENT + ADD (not replace)  
**Sprint PR:** Sprint 56 (first code sprint, `read_only_integration.py` migration)  
**Rationale:** Architecture doc must reflect new EAE/61499 runtime substrate alongside existing 61131-3 references

**Changes:**

1. **Section: "Edge Runtime Substrate"**
   - OLD: "CODESYS V3 Control RTE provides IEC 61131-3 compliant logic execution on AMAX-8580 PAC."
   - NEW: "Schneider EcoStruxure Automation Expert (EAE) runtime provides IEC 61499 distributed function blocks (extending IEC 61131-3) on AMAX-8580 PAC. EAE implements Service Interface Function Blocks (SIFBs) for vendor-independent inter-device communication and read-only data ingress to the AquaOptima sidecar."
   - ADD: "**Historical Note:** Prior to Sprint 56, edge integration assumed CODESYS V3 runtime. Migration rationale documented in ADR-000X."

2. **Section: "IEC Standards Compliance"**
   - KEEP: Existing IEC 61131-3 references (valid; reused by 61499)
   - ADD: "**IEC 61499 (Event-Driven Distributed Control):** EAE runtime implements IEC 61499 function blocks with event-driven execution model. SIFBs provide standardized service interfaces for read-only data publish/subscribe. This EXTENDS IEC 61131-3 logic semantics; both standards coexist."
   - ADD: Cross-reference to GLOSSARY.md entries for IEC 61499, SIFB

3. **Section: "OT/IT Safety Boundary" (Diagrams)**
   - UPDATE diagram labels: Replace "CODESYS Runtime" box with "EAE Runtime (IEC 61499/61131-3)"
   - KEEP boundary arrows and "read-only ingress" annotations (unchanged safety posture)
   - ADD caption: "EAE runtime owns hard real-time control, field I/O, interlocks, actuator authority. AquaOptima sidecar remains advisory-only (no write path)."

4. **Section: "Hardware Profile"**
   - KEEP: AMAX-8580 specifications (unchanged)
   - UPDATE: "Runtime: Schneider EAE (IEC 61499/61131-3 compliant) + Python 3.10 sidecar (co-tenant, CPU-affinity isolated)"
   - ADD: Link to `docs/hardware/amax-8580-eae-runtime.md` (new doc, created in Sprint 56)

**Link Pattern:**
```markdown
For detailed EAE runtime integration, see [AMAX-8580 EAE Runtime Profile](docs/hardware/amax-8580-eae-runtime.md).  
For migration decision rationale, see [ADR-000X: CODESYS→EAE Migration](docs/adr/000X-codesys-to-eae-runtime-migration.md).  
For IEC 61499 terminology, see [GLOSSARY.md#iec-61499](GLOSSARY.md#iec-61499).
```

**Verification (Sprint 56 PR):**
```bash
# Verify EAE references added, CODESYS references moved to historical notes
git diff origin/main ARCHITECTURE.md | grep -E "\+.*EAE|61499"
# Should show new EAE/61499 content

git grep -i "codesys" ARCHITECTURE.md
# Should return ONLY historical notes, NOT current architecture statements
```

---

#### 2.2.2 `PRD.md` (Product Requirements)

**Change Pattern:** MIGRATE-CONTENT (runtime assumptions) + ADD (62443 security posture)  
**Sprint PR:** Sprint 59 (security posture sprint, when IEC 62443 requirements are defined)  
**Rationale:** PRD defines product capabilities and constraints; EAE migration changes runtime assumptions but not product scope (still advisory-only)

**Changes:**

1. **Section: "Edge Integration Requirements"**
   - UPDATE: "The edge subsystem SHALL integrate with Schneider EAE runtime via IEC 61499 Service Interface Function Blocks (SIFBs) for read-only process data ingress."
   - KEEP: "The edge subsystem SHALL NOT execute control commands, modify setpoints, or close control loops." (unchanged constraint)
   - ADD: "Historical: Prior edge integration (pre-Sprint 56) assumed CODESYS V3 runtime. See ADR-000X for migration rationale."

2. **Section: "IEC Standards Compliance"**
   - KEEP: Existing IEC 61131-3 requirement ("SHALL respect IEC 61131-3 data type semantics")
   - ADD: "The edge subsystem SHALL leverage IEC 61499 SIFB event-driven data ingress where supported by the PAC runtime (EAE). Fallback to IEC 61131-3 polling SHALL be available if 61499 SIFBs unavailable."

3. **NEW Section: "Security & Audit Requirements (IEC 62443 Posture)"** (Added in Sprint 59)
   - "The AquaOptima sidecar SHALL produce cryptographically signed evidence logs for all inference executions, timestamped and bound to site/plant/unit identifiers."
   - "The sidecar SHALL maintain an append-only audit log (tamper-evident) for all OT data ingress events, retained for [X days, per site SLA]."
   - "The sidecar SHALL enforce network segmentation posture per IEC 62443 zone/conduit model: sidecar resides in DMZ/monitoring zone, no direct access to safety-critical control zone."
   - "For detailed security architecture, see [SECURITY.md](SECURITY.md)."

**Verification (Sprint 59 PR):**
```bash
# Verify EAE/61499 requirements added
grep -q "IEC 61499 SIFB" PRD.md && echo "✓ 61499 requirement added"

# Verify IEC 62443 security section added
grep -q "IEC 62443" PRD.md && echo "✓ Security posture requirements added"

# Verify historical note present
grep -q "Historical.*CODESYS.*ADR-000X" PRD.md && echo "✓ Migration history documented"
```

---

#### 2.2.3 `GLOSSARY.md`

**Change Pattern:** ADD (new terms: IEC 61499, EAE, SIFB, IEC 62443) + KEEP (existing IEC 61131-3 entries)  
**Sprint PR:** Sprint 56 (first code sprint, when new terms appear in code)  
**Rationale:** Glossary is append-only; new terms added as migration introduces them

**New Entries to ADD (Sprint 56):**

```markdown
### EAE (EcoStruxure Automation Expert)
Schneider Electric's industrial automation platform implementing IEC 61499 distributed control with vendor-independent function blocks. Supersedes CODESYS V3 as AquaOptima edge runtime substrate (Sprint 56+). See [ADR-000X](docs/adr/000X-codesys-to-eae-runtime-migration.md).

### IEC 61499
International standard for distributed control systems using event-driven function blocks. **EXTENDS** IEC 61131-3 (does not replace). EAE runtime implements 61499 with Service Interface Function Blocks (SIFBs) for inter-device communication. AquaOptima leverages 61499 SIFBs for read-only OT data ingress.

**Relationship to IEC 61131-3:** IEC 61499 reuses 61131-3 data types and logic semantics, adding event-driven execution model and distributed architecture. Both standards coexist in AquaOptima codebase.

### SIFB (Service Interface Function Block)
IEC 61499 concept: function block that provides the interface between an application and external services (communication, process I/O, hardware). In AquaOptima's EAE integration, SIFBs are the declarative mechanism by which the sidecar consumes **read-only** OT telemetry — replacing the bolt-on CODESYS symbol-subscription / shared-memory ingress glue. SIFBs do not grant write/command capability to the sidecar; ingress remains read-only.
```

---

## 3. Plane Ledger Updates (live operational state — links to GitHub, never restates)

Plane project: **DPHM** (`dPHM-PINN`, workspace `aquaoptima`). Issue numbering convention applies; verify the latest `sequence_id` before creating.

| Action | Issue | State |
|---|---|---|
| Complete | `Sprint 54 — Planning: CODESYS→EAE migration roadmap + ADR + doc plan` | Completed |
| Create | `Sprint 55 — SPIKE: EAE-on-AMAX-8580 vendor confirmation` | **Planned** (immediate next) |
| Create | `Sprint 56 — read_only_integration.py: CODESYS→EAE/61499 SIFB ingress` | Backlog |
| Create | `Sprint 57 — deployment_readiness + vendor_pac_inventory identifier migration (v2)` | Backlog |
| Create | `Sprint 58 — feasibility + supervisory_gatekeeper migration + governance guard check` | Backlog |
| Create | `Sprint 59 — IEC 62443 sidecar security posture (escalate Morris/Kevin)` | Backlog |
| Create | `Sprint 60 — Docs sync: ARCHITECTURE/PRD/GLOSSARY/hardware/ADR reconciliation` | Backlog |

**Modules to link** (`ModuleIssue.get_or_create`): `Edge Integration Contracts`, `Deployment / Site Readiness`, `Safety / Advisory Contract`, `Security`.

**Merge-audit comment pattern:** on each merge, attach an `IssueComment` (Description-object pattern) that **links to the relevant `docs/` anchors** (ADR, technical plan, hardware doc) and records the test pass-count delta (must be unchanged). The comment never restates the doc content — it points to it. Only the immediate next sprint is `Planned`; the rest stay `Backlog` until their gate opens.

---

## 4. Doc Freshness, Ownership & Link-Check

- Every new/edited doc carries front-matter `owner:` and `last_reviewed: YYYY-MM-DD`.
- The new ADR is owned by Nova (Development Lead); `SECURITY.md` owner is flagged for Morris/Kevin sign-off.
- Before each doc PR merges, run the `os.path.exists` link-check loop over every internal link (resolved relative to each file's own directory — nested `docs/planning/` and `docs/adr/` links need correct `../` depth) and the existing repo link checker.
- ADRs 0001/0002 are **immutable** — superseded by the new ADR, never edited.

---

## 5. Planning-Sprint Scope Confirmation

This planning sprint (Sprint 54) adds **only** files under `docs/planning/`:
`sprint54_eae_migration_roadmap.md`, `sprint54_eae_migration_technical_plan.md`, `sprint54_eae_documentation_update_plan.md`, `sprint54_eae_safety_verification_review.md`. No ADR, code, contract, test, or other doc is modified in this sprint — those changes are **planned here** and **executed in the gated Sprints 55–60** under the same-PR rule.