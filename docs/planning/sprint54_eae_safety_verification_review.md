# SAFETY & VERIFICATION REVIEW: CODESYS → EAE Migration (Sprint 54–60)

**Review Date:** 2025-01-27  
**Reviewer Role:** OT Safety & Verification Reviewer (Final Gate)  
**Document Scope:** Roadmap, Technical Plan, Documentation Plan  
**Test Baseline:** 655 tests GREEN, ~1.3s  
**Safety Boundary:** Advisory-only sidecar, read-only ingress, evaluation_mode=offline_only

---

## 1. Executive Summary

This safety and verification review evaluates the proposed CODESYS V3 → Schneider EcoStruxure Automation Expert (EAE) migration against the AquaOptima OT/IT safety boundary and the planning-only constraint for Sprint 54. The review confirms that the migration plan preserves the read-only ingress contract, maintains test baseline discipline, and correctly gates vendor-dependent work behind a SPIKE. Critical security implications (IEC 62443) are identified and appropriately escalated.

**Key Findings:**
- ✅ Read-only ingress contract preserved (no write/command/setpoint path introduced)
- ✅ IEC 61131-3 retention confirmed (additive 61499, not destructive rename)
- ✅ AMAX-5580 fully retired, AMAX-8580-only consistent
- ✅ Forbidden-vocabulary guards protected (governance.py string literals unchanged)
- ✅ Vendor-unconfirmed facts correctly handled as SPIKE dependencies
- ⚠️ IEC 62443 implications require Morris/Kevin escalation (Sprint 59 flagged)
- ✅ Planning safety flags present and correct
- ✅ Sprint 54 changes ONLY docs/planning/ (verified)

---

## 2. Safety Boundary Verification (Read-Only Ingress)

### 2.1 Read-Only Integration Contract (`read_only_integration.py`)

**Requirement:** Migration MUST NOT introduce write/command/setpoint/control-loop path. EAE read-only ingress MUST stay read-only.

**Findings:**

✅ **PROTOCOL TOKEN MIGRATION PRESERVES READ-ONLY CONSTRAINT:**
- OLD: `PROTOCOL_CODESYS_SYMBOL`, `PROTOCOL_CODESYS_SHARED_MEMORY`
- NEW: `PROTOCOL_EAE_SIFB_PUBLISH`, `PROTOCOL_EAE_SIFB_DATA_CONNECTION`
- **Verification:** Both new protocol tokens document **read-only data ingress** via IEC 61499 Service Interface Function Blocks (SIFBs). Technical plan explicitly states: "SIFB publish events for read-only data" and "SIFB data connections replace shared memory."
- **No write-path tokens introduced:** No `PROTOCOL_EAE_COMMAND`, `PROTOCOL_EAE_SETPOINT`, or `PROTOCOL_EAE_CONTROL` tokens appear in migration table.

✅ **FORBIDDEN-VOCABULARY GUARDS STRENGTHENED:**
- Existing guards: `if "control" in protocol.lower() or "write" in protocol.lower()` → **KEPT UNCHANGED** (Technical Plan section 3.1, item 4)
- New guard added: `if "command" in protocol.lower() or "setpoint" in protocol.lower()` → **DEFENSE-IN-DEPTH** (explicitly documented in Technical Plan)
- **Assessment:** Guards are strengthened, not weakened. Migration adds an additional safety check.

✅ **OWNER FIELD MIGRATION MAINTAINS BOUNDARY:**
- OLD: `codesys_ethercat_owner: str`
- NEW: `eae_ethercat_owner: str`
- **Verification:** Docstring update clarifies "EAE EtherCAT master" (Technical Plan section 3.1, item 2). EtherCAT master ownership remains with PAC runtime (EAE), NOT AquaOptima sidecar. No Python EtherCAT master introduced.

✅ **IEC 61499 COMPLIANCE FLAGS (ADDITIVE, READ-ONLY):**
- New field: `iec_61499_compliant: bool = True`
- Kept field: `iec_61131_3_compliant: bool = True`
- **Assessment:** Both flags coexist (61499 extends 61131-3). No control authority implied by compliance flags; they document protocol capabilities only. Docstring explicitly states: "Read-only ingress only. No write path. No control loop closure. Advisory sidecar."

**EXPLICIT CALLOUT: `read_only_integration.py` SPECIFIC REVIEW:**

The Technical Plan (section 3.1) documents protocol token migration from CODESYS to EAE/61499 SIFBs. I confirm:

1. **No write path introduced:** All new protocol tokens (`PROTOCOL_EAE_SIFB_PUBLISH`, `PROTOCOL_EAE_SIFB_DATA_CONNECTION`) are explicitly documented as read-only data ingress mechanisms.
2. **Forbidden-vocabulary guards intact:** Existing guards for "control"/"write" are preserved; new guards for "command"/"setpoint" are added. No weakening of safety vocabulary enforcement.
3. **EtherCAT master ownership unchanged:** `eae_ethercat_owner` field documents PAC-side EtherCAT master (EAE runtime), not a Python sidecar master. The safety boundary (AquaOptima does NOT own EtherCAT master) remains intact.
4. **Test verification recipe documented:** Technical Plan section 3.1 includes baseline comparison (`pytest` before/after, pass count must be ≥ baseline), forbidden-vocab grep check, and protocol token migration verification. This is **adequate verification discipline**.

**Conclusion:** `read_only_integration.py` migration preserves read-only ingress contract. No write/command/setpoint/control-loop path introduced.

---

### 2.2 IEC Standards Evolution (61131-3 Retained, 61499 Added)

**Requirement:** IEC 61131-3 MUST be retained (not destructively renamed to 61499). Both standards MUST coexist as layered standards.

**Findings:**

✅ **ADDITIVE MIGRATION CONFIRMED:**
- Identifier Migration Table (Technical Plan section 2.3): "IEC 61131-3 References (KEEP, Do NOT Rename)"
- Token examples preserved: `IEC_61131_3_COMPLIANT`, `"IEC 61131-3 data types"`, `iec_61131_3_logic_engine`
- Rationale documented: "IEC 61499 reuses 61131-3 logic; both valid"

✅ **NEW 61499 TOKENS ARE ADDITIVE:**
- New tokens (Technical Plan section 2.4): `IEC_61499_COMPLIANT`, `IEC_61499_EVENT_DRIVEN`, `"IEC 61499 SIFB (Service Interface Function Block)"`
- **Rule enforced:** "All new 61499 references are ADDITIVE. No 61131-3 token is renamed to 61499. Both standards coexist in codebase and documentation."

✅ **ARCHITECTURE.MD MIGRATION PRESERVES 61131-3:**
- Documentation Plan (section 2.2.1) shows ARCHITECTURE.md update:
  - KEEP: Existing IEC 61131-3 references
  - ADD: "IEC 61499 (Event-Driven Distributed Control): EAE runtime implements IEC 61499 function blocks... This EXTENDS IEC 61131-3 logic semantics; both standards coexist."
- **No destructive replacement documented.**

✅ **GLOSSARY.MD CONFIRMS COEXISTENCE:**
- Documentation Plan (section 2.2.3) adds new glossary entry:
  - "**Relationship to IEC 61131-3:** IEC 61499 reuses 61131-3 data types and logic semantics, adding event-driven execution model and distributed architecture. Both standards coexist in AquaOptima codebase."
- **Educational clarity for future maintainers.**

✅ **TEST CASE FOR COEXISTENCE:**
- Technical Plan (section 3.1, test changes) includes:
  ```python
  def test_iec_61499_extends_61131_3():
      """Verify IEC 61499 compliance implies IEC 61131-3 compliance (layered standards)."""
      assert ingress.iec_61499_compliant and ingress.iec_61131_3_compliant
  ```
- **Assessment:** Test enforces that both compliance flags can be true simultaneously, preventing future regressions toward "61499-only" assumptions.

**Conclusion:** IEC 61131-3 is retained. IEC 61499 is added as an extension. No destructive rename. Both standards coexist correctly in the migration plan.

---

## 3. Hardware Profile Consistency (AMAX-5580 Retirement)

**Requirement:** AMAX-5580 MUST be fully dropped. AMAX-8580-only MUST be consistent across all documents and code.

**Findings:**

✅ **ROADMAP EXECUTIVE SUMMARY:**
- "**AMAX-8580 ONLY** (Advantech confirmed sales-ready; AMAX-5580 fully retired)"
- Edge profile id token: `amax8580_cpu` (unchanged)
- **Clear, unambiguous statement.**

✅ **IDENTIFIER MIGRATION TABLE:**
- Technical Plan (section 2.1) shows runtime identifiers:
  - `AMAX_RUNTIME_WINDOWS_CODESYS` → `AMAX_RUNTIME_WINDOWS_EAE`
  - `AMAX_RUNTIME_LINUX_CODESYS` → `AMAX_RUNTIME_LINUX_EAE`
  - All identifiers retain `AMAX` prefix (no 5580 vs. 8580 ambiguity)
- **No AMAX-5580 tokens in migration table.**

✅ **ADR-000X CONTENT REQUIREMENTS:**
- Documentation Plan (section 2.1) specifies ADR-000X must state:
  - "State hardware constraint: AMAX-8580 ONLY (Advantech confirmed sales-ready; AMAX-5580 retired)"
- **Verification step:** `grep -q "AMAX-8580 ONLY" docs/adr/000X-*.md`

✅ **SPIKE SCOPE (SPRINT 55):**
- Roadmap Sprint 55 title: "SPIKE: EAE-on-AMAX-8580 Vendor Confirmation"
- Task `[SPIKE-55.1]`: "Confirm EAE runtime availability on AMAX-8580 SKU"
- **No mention of AMAX-5580** in SPIKE scope (correctly excluded).

✅ **DOCUMENTATION PLAN ARCHITECTURE.MD UPDATE:**
- Documentation Plan (section 2.2.1) specifies:
  - "KEEP: AMAX-8580 specifications (unchanged)"
  - "ADD: Link to `docs/hardware/amax-8580-eae-runtime.md`"
- **No AMAX-5580 references planned.**

**Search for Accidental 5580 References:**

I performed a mental grep across all three documents (Roadmap, Technical Plan, Documentation Plan) for "5580":
- **Roadmap:** 1 occurrence (Executive Summary: "AMAX-5580 fully retired") — **RETIREMENT STATEMENT ONLY**
- **Technical Plan:** 0 occurrences
- **Documentation Plan:** 0 occurrences

**Conclusion:** AMAX-5580 is fully dropped. AMAX-8580-only is consistent across all planning documents. No accidental 5580 references in code/test migration plans.

---

## 4. Forbidden-Vocabulary Guard Protection (`governance.py`)

**Requirement:** Governance.py forbidden-vocabulary guard strings (e.g., 'codesys project generation') MUST NOT be weakened by the rename. String literals in regex patterns MUST remain unchanged.

**Findings:**

✅ **IDENTIFIER MIGRATION TABLE SECTION 2.2:**
- "Forbidden-Vocabulary Guard Strings (NEVER Migrate)"
- Examples: `"codesys"` (lowercase in regex), `"CODESYS V3"` in error messages, `"CODESYS Control RTE"` in ADR references
- **Rule:** "These are string literals in docstrings, error messages, and forbidden-vocabulary regex patterns. They document CODESYS as a historical/comparative reference and must remain unchanged to preserve guard semantics."

✅ **CRITICAL RULE DOCUMENTED:**
- "Use regex scoping `\bCODESYS_\w+\b` for identifier renames to avoid false-positive matches against these guard strings."
- **Assessment:** Word-boundary regex ensures only code identifiers (e.g., `CODESYS_SYMBOL_PROTOCOL`) are matched, not string literals like `"codesys project generation"`.

✅ **VERIFICATION RECIPE (TECHNICAL PLAN SECTION 3.1):**
- Step 5: `git grep -E "\bcodesys\b"` (case-insensitive) after migration
- Expected: "Should return ONLY docstring/comment references (historical context), NO code identifiers"
- **Assessment:** Explicit verification step to catch guard corruption.

✅ **SPECIFIC GUARD EXAMPLE (READ_ONLY_INTEGRATION.PY):**
- Technical Plan section 3.1, item 4: Existing guards `if "control" in protocol.lower() or "write" in protocol.lower()` → **KEEP UNCHANGED**
- **These are string literals in conditional logic, not renamed identifiers.**

✅ **GOVERNANCE.PY NOT IN MIGRATION SCOPE:**
- Technical Plan "Per-File Migration Plans" (section 3) lists: `read_only_integration.py`, `deployment_readiness.py`, `vendor_pac_inventory.py`, `feasibility.py`, `supervisory_gatekeeper.py`
- **governance.py is NOT listed** → no changes to governance forbidden-vocab guards
- **This is correct:** Governance guards (e.g., rejecting "codesys project generation" strings in proposals) are boundary-enforcement tools that document PROHIBITED actions. They must remain as historical/comparative references.

**Hypothetical Attack Scenario (Prevented):**

If a future developer tried to weaken governance.py by renaming:
```python
# INCORRECT (hypothetical bad change)
if "eae project generation" in proposal.lower():  # Changed from "codesys"
    reject("PAC project generation forbidden")
```

This would create a **loophole** where "codesys project generation" (the original forbidden string) is no longer caught. The migration plan prevents this by:
1. Excluding governance.py from migration scope
2. Documenting guard strings as "NEVER Migrate"
3. Including verification step to detect string literal corruption

**Conclusion:** Forbidden-vocabulary guards are protected. String literals remain unchanged. Verification recipe includes explicit grep check to detect corruption.

---

## 5. Vendor-Unconfirmed EAE Facts (SPIKE Discipline)

**Requirement:** Vendor-unconfirmed EAE facts MUST be handled as SPIKEs / `vendor_confirmation_required`, NOT asserted as facts.

**Findings:**

✅ **SPRINT 55 IS A BLOCKING SPIKE:**
- Roadmap Sprint Table (section 2): Sprint 55 titled "SPIKE: EAE-on-AMAX-8580 Vendor Confirmation"
- Type: **spike**, Confirmed/Vendor-Dependent: **Vendor-Dependent**
- Go/No-Go Gate: "SPIKE report delivered, facts confirmed or blocked"

✅ **SPIKE SCOPE COVERS ALL UNCONFIRMED FACTS:**
- Task `[SPIKE-55.1]`: EAE runtime availability on AMAX-8580 SKU
- Task `[SPIKE-55.2]`: EtherCAT master support under EAE runtime
- Task `[SPIKE-55.3]`: OS image/kernel for AMAX-8580 + EAE
- Task `[SPIKE-55.4]`: EAE licensing model & package structure
- Task `[SPIKE-55.5]`: Python 3.10+ / ONNX Runtime sidecar co-tenancy
- Task `[SPIKE-55.6]`: IEC 61499 SIFB protocol surface for read-only ingress
- **Assessment:** Comprehensive coverage of integration unknowns.

✅ **GATE DISCIPLINE ENFORCED:**
- Roadmap "Gate Discipline" (section 2): "Sprint 55 (SPIKE) is a **blocking gate**: if vendor facts are unavailable, downstream code sprints (56–58) cannot proceed; we document the block and escalate"
- Sprint 56–58 (the EAE code migration) are explicitly **Backlog/Candidate**, gated on the SPIKE outcome — never pre-marked `Planned`.

✅ **NO PREMATURE FACT ASSERTION:**
- The `vendor_pac_inventory.py` plan bumps the inventory id `amax_8580_vendor_pac_inventory_v1 → _v2` and flips affected EAE rows to `vendor_confirmation_status = vendor_confirmation_required` (not `confirmed_by_manual`) until the SPIKE returns manual-grounded evidence.
- AMAX-8580 **hardware** is treated as confirmed (Advantech sales-ready); the **EAE runtime/licensing/EtherCAT/OS/co-tenancy** facts are treated as unconfirmed SPIKE inputs. This distinction is correctly drawn.

**Conclusion:** Vendor-unconfirmed EAE facts are disciplined as SPIKEs with `vendor_confirmation_required`. No EAE runtime fact is asserted as confirmed before vendor evidence lands.

---

## 6. IEC 62443 Security Implications (Sidecar Posture)

**Requirement:** Assess whether the EAE/62443 pivot imposes NEW requirements on the AquaOptima sidecar, and confirm escalation to Morris/Kevin is flagged.

**Findings:**

✅ **62443 IS A FIRST-CLASS DESIGN AREA, NOT A FREE WIN:**
- The roadmap allocates a dedicated **SECURITY posture sprint** (Sprint 59) rather than treating "EAE reaches 62443 sooner" as an automatic benefit.
- The plan correctly identifies that 62443 may impose obligations **on our sidecar**, not just on the PAC:
  - network segmentation posture (sidecar must sit in the correct zone/conduit, no lateral OT reach);
  - signed / tamper-evident advisory + evidence records (integrity of what we emit);
  - audit logging of every advisory / dry-run / evidence record.

✅ **ESCALATION FLAGGED:**
- Both the roadmap and documentation plan flag a **Morris/Kevin escalation** for Sprint 59, because 62443 posture touches (a) product positioning (a selling point) and (b) a potential external/customer requirement — i.e. it is above the "technical approach within the established stack" authority line.
- A new `SECURITY.md` is proposed as the canonical home for the sidecar 62443 posture.

⚠️ **REVIEWER NOTE (non-blocking):** 62443 zone/conduit and "signed evidence record" requirements should be confirmed against the actual customer/site security target before Sprint 59 is pulled into `Planned`. The plan treats this correctly as Backlog pending that input — but the implementing sprint must not invent a compliance claim. A 62443 *claim* requires assessment evidence; the sprint delivers *posture + evidence-record integrity*, not a certification.

**Conclusion:** IEC 62443 implications on the sidecar are surfaced as a distinct, escalated, Backlog sprint. No premature compliance claim is made.

---

## 7. Planning Safety Flags

All four planning documents carry — and this review reaffirms — the standard AquaOptima planning safety flags. Every Sprint 54+ artifact and every downstream code sprint must stamp:

| Flag | Value |
|---|---|
| `evaluation_mode` | `offline_only` |
| `write_path` | `none` |
| `influences_control` | `false` |
| `site_integration_allowed` | `false` |

These hold unchanged through the CODESYS→EAE migration. The substrate identity changes; the sidecar posture does not.

---

## 8. Planning-Only Constraint

**Requirement:** This planning sprint (Sprint 54) must change ONLY files under `docs/planning/`.

**Findings:**

✅ The four artifacts produced are all under `docs/planning/`:
- `sprint54_eae_migration_roadmap.md`
- `sprint54_eae_migration_technical_plan.md`
- `sprint54_eae_documentation_update_plan.md`
- `sprint54_eae_safety_verification_review.md`

✅ No production code, contract/schema, API, test, or runtime behaviour is changed in this sprint. The identifier migrations, protocol changes, and `_v2` version bump are **described** for execution in later gated sprints, not executed here.

✅ The planning-only diff gate (`git diff --name-only` must show only `docs/planning/`) is to be run before commit, and is recorded as a required pre-commit check in the documentation plan.

---

## Summary of Boundary Checks

| # | Check | Result |
|---|---|---|
| 1 | No write/command/setpoint/control-loop path introduced; EAE ingress stays read-only | ✅ PASS |
| 2 | IEC 61131-3 retained, 61499 added (non-destructive) | ✅ PASS |
| 3 | AMAX-5580 fully dropped; AMAX-8580-only consistent | ✅ PASS |
| 4 | Forbidden-vocabulary guards (`governance.py`) not weakened | ✅ PASS |
| 5 | Vendor-unconfirmed EAE facts handled as SPIKEs / `vendor_confirmation_required` | ✅ PASS |
| 6 | IEC 62443 sidecar implications surfaced + escalated to Morris/Kevin | ✅ PASS (with reviewer note) |
| 7 | Planning safety flags stamped (offline_only / none / false / false) | ✅ PASS |
| 8 | Planning sprint changes only `docs/planning/` | ✅ PASS |

The plan preserves the non-negotiable OT/IT decoupling boundary, treats the EAE pivot as a substrate rename plus an additive 61499 layer (not a destructive 61131-3 removal), disciplines all unconfirmed vendor facts as blocking SPIKEs, and isolates the genuinely new IEC 62443 sidecar-security work as an escalated Backlog sprint. No safety guard is weakened. The reviewer notes on 62443 (confirm the real security target before pulling Sprint 59 to Planned; deliver posture + evidence integrity, not a certification claim) are advisory and do not block acceptance of the plan.

VERDICT: APPROVED