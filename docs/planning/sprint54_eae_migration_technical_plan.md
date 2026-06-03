# AquaOptima Edge Contracts: CODESYS → EAE Migration Technical Implementation Plan

**Document Status:** Technical Implementation Plan  
**Sprint Scope:** Sprint 54–60  
**Code Owner:** AquaOptima Edge/Contracts Technical Architect  
**Test Baseline:** 655 tests GREEN, ~1.3s (tests/aquaoptima_contracts/)  
**Migration Target:** 655+ tests GREEN, pass count unchanged or increased only by new coverage  
**Safety Boundary:** Advisory-only sidecar, read-only ingress, no write/control, evaluation_mode=offline_only

---

## 1. Executive Summary

This technical implementation plan translates the Sprint 54–60 roadmap into concrete code changes for migrating AquaOptima edge integration contracts from CODESYS V3 to Schneider EcoStruxure Automation Expert (EAE) runtime with IEC 61499 support.

**Critical Architecture Principle:**  
IEC 61499 **EXTENDS** IEC 61131-3 — it does NOT replace it. Our migration strategy:
- **KEEP** all existing IEC 61131-3 references (valid, reused by 61499)
- **ADD** IEC 61499 references for Service Interface Function Blocks (SIFBs), distributed event-driven comms
- **NEVER** rename `61131` tokens to `61499` — both coexist as layered standards

**Migration Scope:**  
- `src/aquaoptima_contracts/edge/read_only_integration.py`: CODESYS protocol tokens → EAE/61499 SIFB ingress (still read-only)
- `src/aquaoptima_contracts/edge/deployment_readiness.py`: CODESYS readiness/failure categories → EAE equivalents
- `src/aquaoptima_contracts/edge/vendor_pac_inventory.py`: CODESYS runtime entries → EAE runtime, schema v1→v2
- `src/aquaoptima_contracts/edge/feasibility.py`: CODESYS runtime tokens → EAE runtime
- `src/aquaoptima_contracts/edge/supervisory_gatekeeper.py`: CODESYS owner tokens → EAE owner
- All corresponding test files in `tests/aquaoptima_contracts/edge/`

**Safety Verification:**  
Every change anchored to 655-test GREEN baseline. Forbidden-vocabulary guards (string literals) are **NEVER** renamed. Real code identifiers migrate via exact token table below.

---

## 2. Identifier Migration Table

### 2.1 Real Code Identifiers (MUST Migrate)

| Old Token (CODESYS) | New Token (EAE) | File(s) | Type | Notes |
|---------------------|-----------------|---------|------|-------|
| `PROTOCOL_CODESYS_SYMBOL` | `PROTOCOL_EAE_SIFB_PUBLISH` | `read_only_integration.py` | Protocol enum | EAE uses IEC 61499 SIFB publish events for read-only data |
| `PROTOCOL_CODESYS_SHARED_MEMORY` | `PROTOCOL_EAE_SIFB_DATA_CONNECTION` | `read_only_integration.py` | Protocol enum | EAE SIFB data connections replace shared memory |
| `codesys_ethercat_owner` | `eae_ethercat_owner` | `read_only_integration.py` | Variable identifier | EtherCAT master ownership under EAE runtime |
| `READINESS_CATEGORY_CODESYS_PACKAGE` | `READINESS_CATEGORY_EAE_PACKAGE` | `deployment_readiness.py` | Readiness enum | EAE package structure replaces CODESYS Control RTE packages |
| `FAILURE_MODE_CATEGORY_CODESYS` | `FAILURE_MODE_CATEGORY_EAE` | `deployment_readiness.py` | Failure mode enum | EAE-specific failure modes |
| `AMAX_RUNTIME_WINDOWS_CODESYS` | `AMAX_RUNTIME_WINDOWS_EAE` | `vendor_pac_inventory.py` | Runtime id | Windows Embedded + EAE runtime (pending Sprint 55 SPIKE) |
| `AMAX_RUNTIME_LINUX_CODESYS` | `AMAX_RUNTIME_LINUX_EAE` | `vendor_pac_inventory.py` | Runtime id | Linux RTE + EAE runtime (pending Sprint 55 SPIKE) |
| `AMAX_CODESYS_RUNTIMES` | `AMAX_EAE_RUNTIMES` | `vendor_pac_inventory.py` | Runtime list | Collection of EAE runtime options for AMAX-8580 |
| `PRODUCT_CATEGORY_CODESYS_READY_PAC` | `PRODUCT_CATEGORY_EAE_READY_PAC` | `vendor_pac_inventory.py` | Product category | EAE-ready PAC hardware profile |
| `OWNER_AMAX_CODESYS_PAC` | `OWNER_AMAX_EAE_PAC` | `vendor_pac_inventory.py`, `supervisory_gatekeeper.py` | Owner identifier | Ownership record for EAE-based PAC |
| `amax_8580_vendor_pac_inventory_v1` | `amax_8580_vendor_pac_inventory_v2` | `vendor_pac_inventory.py` | Inventory id | Schema versioning for EAE migration |

### 2.2 Forbidden-Vocabulary Guard Strings (NEVER Migrate)

These are **string literals** in docstrings, error messages, and forbidden-vocabulary regex patterns. They document CODESYS as a historical/comparative reference and must remain unchanged to preserve guard semantics.

| Guard String | Location | Why NOT Migrated |
|--------------|----------|------------------|
| `"codesys"` (lowercase in forbidden-vocab regex) | Multiple test files, docstrings | Historical reference, comparative documentation |
| `"CODESYS V3"` in error messages | Test assertions | Documents legacy integration for comparison |
| `"CODESYS Control RTE"` in ADR references | ADR-000X, docstrings | Immutable historical record |
| `"IEC 61131-3 (CODESYS implementation)"` | Architecture docs | Accurate historical context |

**Critical Rule:** Use regex scoping `\bCODESYS_\w+\b` for identifier renames to avoid false-positive matches against these guard strings. Verify with `git grep -E "\bcodesys\b"` (case-insensitive) after migration to confirm no guard strings were corrupted.

### 2.3 IEC 61131-3 References (KEEP, Do NOT Rename)

| Token/Reference | Location | Why KEPT |
|----------------|----------|----------|
| `IEC_61131_3_COMPLIANT` | `feasibility.py`, `deployment_readiness.py` | IEC 61499 reuses 61131-3 logic; both valid |
| `"IEC 61131-3 data types"` | Docstrings, ADRs | Technical accuracy; 61499 extends 61131-3 |
| `iec_61131_3_logic_engine` | Module references | Valid under EAE (61499 runtime includes 61131-3) |

### 2.4 IEC 61499 References (ADD, New Tokens)

| New Token (61499) | Location | Purpose |
|-------------------|----------|---------|
| `IEC_61499_COMPLIANT` | `feasibility.py`, `deployment_readiness.py` | Flag EAE runtime as 61499-compliant |
| `"IEC 61499 SIFB (Service Interface Function Block)"` | Docstrings, ADRs | Document EAE ingress protocol |
| `IEC_61499_EVENT_DRIVEN` | `read_only_integration.py` | Flag event-driven data ingress vs. polling |
| `"IEC 61499 distributed function blocks"` | Architecture docs | Technical capability description |

**Rule:** All new 61499 references are **ADDITIVE**. No 61131-3 token is renamed to 61499. Both standards coexist in codebase and documentation.

---

## 3. Per-File Migration Plans

### 3.1 `src/aquaoptima_contracts/edge/read_only_integration.py`

**Current State:**  
- Defines `ReadOnlyOTIngress` dataclass with `protocol: str` field
- Protocol tokens: `PROTOCOL_CODESYS_SYMBOL`, `PROTOCOL_CODESYS_SHARED_MEMORY`
- Owner field: `codesys_ethercat_owner: str` (documents EtherCAT master ownership)
- Docstrings reference CODESYS-specific integration patterns

**Migration Goal:**  
Replace CODESYS protocol tokens with EAE/61499 SIFB-based ingress. Maintain read-only constraint (no write path, no control loop closure).

**Changes:**

1. **Protocol Token Migration:**
   ```python
   # OLD (CODESYS)
   PROTOCOL_CODESYS_SYMBOL = "codesys_symbol_subscription"
   PROTOCOL_CODESYS_SHARED_MEMORY = "codesys_shared_memory"
   
   # NEW (EAE/61499)
   PROTOCOL_EAE_SIFB_PUBLISH = "eae_sifb_publish_event"  # IEC 61499 SIFB publish
   PROTOCOL_EAE_SIFB_DATA_CONNECTION = "eae_sifb_data_connection"  # IEC 61499 SIFB data connection
   ```

2. **Owner Field Migration:**
   ```python
   # OLD
   codesys_ethercat_owner: str  # Field name
   
   # NEW
   eae_ethercat_owner: str  # Field name updated, docstring clarifies EAE EtherCAT master
   ```

3. **Docstring Updates:**
   - Add: "EAE implements IEC 61499 Service Interface Function Blocks (SIFBs) for read-only data ingress."
   - Keep: "IEC 61131-3 compliant logic (reused by IEC 61499 runtime)."
   - Add: "SIFB publish events replace CODESYS symbol subscriptions; SIFB data connections replace shared memory."
   - Preserve: "Read-only ingress only. No write path. No control loop closure. Advisory sidecar."

4. **Forbidden-Vocabulary Guards:**
   - Existing guards: `if "control" in protocol.lower() or "write" in protocol.lower()` → **KEEP UNCHANGED**
   - Add new guard: `if "command" in protocol.lower() or "setpoint" in protocol.lower()` (defense-in-depth)

5. **Add IEC 61499 Compliance Flag:**
   ```python
   @dataclass(frozen=True)
   class ReadOnlyOTIngress:
       protocol: str
       eae_ethercat_owner: str
       iec_61499_compliant: bool = True  # NEW: flag EAE/61499 support
       iec_61131_3_compliant: bool = True  # KEEP: 61499 extends 61131-3
       # ... other fields
   ```

**Test Changes (`tests/aquaoptima_contracts/edge/test_read_only_integration.py`):**

1. **Update Protocol Test Cases:**
   ```python
   # OLD test
   def test_codesys_symbol_protocol():
       ingress = ReadOnlyOTIngress(protocol=PROTOCOL_CODESYS_SYMBOL, ...)
       assert ingress.protocol == "codesys_symbol_subscription"
   
   # NEW test
   def test_eae_sifb_publish_protocol():
       ingress = ReadOnlyOTIngress(protocol=PROTOCOL_EAE_SIFB_PUBLISH, ...)
       assert ingress.protocol == "eae_sifb_publish_event"
       assert ingress.iec_61499_compliant is True
       assert ingress.iec_61131_3_compliant is True  # Both true
   ```

2. **Add Test for 61499/61131-3 Coexistence:**
   ```python
   def test_iec_61499_extends_61131_3():
       """Verify IEC 61499 compliance implies IEC 61131-3 compliance (layered standards)."""
       ingress = ReadOnlyOTIngress(
           protocol=PROTOCOL_EAE_SIFB_PUBLISH,
           eae_ethercat_owner="eae_runtime",
           iec_61499_compliant=True,
           iec_61131_3_compliant=True
       )
       # Both flags true; 61499 extends 61131-3
       assert ingress.iec_61499_compliant and ingress.iec_61131_3_compliant
   ```

3. **Preserve Forbidden-Vocabulary Tests:**
   - Existing tests that verify "control"/"write" rejection → **KEEP UNCHANGED**
   - Add test for "command"/"setpoint" rejection (new guard)

**Verification Recipe:**
```bash
# 1. Baseline: Record current test pass count
pytest tests/aquaoptima_contracts/edge/test_read_only_integration.py -v --tb=short | tee baseline.txt
# Expected: N tests pass (e.g., 45 tests)

# 2. Apply migration changes to read_only_integration.py and test file

# 3. Rerun tests
pytest tests/aquaoptima_contracts/edge/test_read_only_integration.py -v --tb=short | tee migrated.txt

# 4. Compare pass counts
# migrated.txt pass count MUST be >= baseline.txt pass count
# New tests (61499/61131-3 coexistence) may increase count by 2–3

# 5. Verify no forbidden-vocab guard corruption
git grep -i "codesys" src/aquaoptima_contracts/edge/read_only_integration.py
# Should return ONLY docstring/comment references (historical context), NO code identifiers

# 6. Verify protocol tokens migrated
git grep "PROTOCOL_CODESYS" src/aquaoptima_contracts/edge/read_only_integration.py
# Should return ZERO matches (all migrated to PROTOCOL_EAE)
```

---

### 3.2 `src/aquaoptima_contracts/edge/deployment_readiness.py`

**Current State:**  
- Defines `DeploymentReadiness` dataclass with readiness/failure categories
- Readiness token: `READINESS_CATEGORY_CODESYS_PACKAGE`
- Failure token: `FAILURE_MODE_CATEGORY_CODESYS`
- Docstrings reference CODESYS Control RTE package structure

**Migration Goal:**  
Migrate CODESYS-specific readiness/failure categories to EAE equivalents. Preserve deployment gating logic (still blocks deployment on package failures).

**Changes:**

1. **Readiness Category Migration:**
   ```python
   # OLD
   READINESS_CATEGORY_CODESYS_PACKAGE = "codesys_rte_package_availability"
   
   # NEW
   READINESS_CATEGORY_EAE_PACKAGE = "eae_runtime_package_availability"
   ```

2. **Failure Mode Migration:**
   ```python
   # OLD
   FAILURE_MODE_CATEGORY_CODESYS = "codesys_runtime_failure"
   
   # NEW
   FAILURE_MODE_CATEGORY_EAE = "eae_runtime_failure"
   ```

3. **Docstring Updates:**
   - Replace: "CODESYS Control RTE package" → "EAE runtime package (IEC 61499 compliant)"
   - Add: "EAE package structure includes IEC 61499 function block libraries and IEC 61131-3 logic engine."
   - Keep: "Deployment gating: blocks site integration on package unavailability or runtime failure."

4. **Add IEC 61499/61131-3 Flags:**
   ```python
   @dataclass(frozen=True)
   class DeploymentReadiness:
       readiness_category: str
       failure_mode_category: str
       iec_61499_runtime_available: bool  # NEW: EAE runtime check
       iec_61131_3_logic_available: bool = True  # KEEP: 61131-3 logic stays valid under 61499
   ```
   Rationale: 61499 EXTENDS 61131-3 — the readiness record advertises BOTH (61499 runtime present AND 61131-3 logic engine present), never replaces the 61131-3 flag with a 61499 one. Default `True` for the 61131-3 flag preserves backward-compatible construction of existing records.

---

## 5. Versioning & ADR

- **`vendor_pac_inventory.py`:** bump `AMAX_VENDOR_PAC_INVENTORY_ID` `amax_8580_vendor_pac_inventory_v1 → amax_8580_vendor_pac_inventory_v2`. The `_v2` schema adds EAE product/runtime rows and sets their `vendor_confirmation_status = vendor_confirmation_required` until the Sprint 55 SPIKE confirms. Keep the `_v1` record readable for historical comparison (from_dict accepts both ids).
- **New ADR:** next number after the existing `0005` → **`docs/adr/0006-codesys-to-eae-runtime-migration.md`**, Status: **Proposed**. It supersedes the *runtime* assumptions in ADR-0001 (OT/IT decoupling) and ADR-0002 (AMAX CPU edge) by reference — those ADRs are **immutable** and are NOT edited; the new ADR records the decision, consequences, and the reopened vendor gates.

---

## 6. Verification Recipe (per code sprint)

```bash
# 1. Establish GREEN baseline BEFORE any change
python -m pytest tests/aquaoptima_contracts/ -q   # expect: 655 passed

# 2. Apply the scoped identifier migration (word-boundary regex; NEVER touch guard strings)
#    e.g. \bCODESYS\b inside identifiers only; leave string literals in governance.py alone

# 3. Re-run the suite AFTER the change
python -m pytest tests/aquaoptima_contracts/ -q   # expect: 655 passed (UNCHANGED count)

# 4. Confirm guard integrity — codesys should survive ONLY in historical/comparative strings
git grep -inE "\bcodesys\b" src/aquaoptima/advisory/governance.py   # forbidden-vocab guards intact

# 5. Confirm no new write/control path
git grep -inE "write|setpoint|command|control_loop|actuator" src/aquaoptima_contracts/edge/read_only_integration.py | grep -vi "forbid\|reject\|no_\|not "

# 6. File renames use git-mv (preserve history); historical SPRINTNN_REPORT.md untouched
```

A sprint is accepted only if: pass count unchanged, guard strings intact, no new write/control path, and the planning/diff gate is clean.

---

## 7. Architecture Placement

| Item | Value |
|---|---|
| **Component owner** | Edge inference / advisory runtime → **Shared Contracts / SDK** (`src/aquaoptima_contracts/edge/`) |
| **Code paths** | `read_only_integration.py`, `deployment_readiness.py`, `feasibility.py`, `vendor_pac_inventory.py`, `supervisory_gatekeeper.py` (+ matching `tests/aquaoptima_contracts/`) |
| **Forbidden imports** | no training/model internals, no Operations Console, no network clients, no OT adapters, no torch, no runtime execution |
| **Cross-component deps** | contracts stay stdlib-only, frozen, deterministic; consumed read-only by edge runtime |
| **No-write/no-control checks** | step 5 above; `influences_control=False` asserted in records; ingress declared read-only |

---

## 8. Risks & Pitfalls

1. **61131-3 → 61499 migration is not zero-effort** — literature documents real pitfalls. The PAC-side effort is Schneider's; our risk is mapping our ingress contract onto EAE's actual SIFB protocol surface, which is a **Sprint 55 SPIKE unknown**. Do not code Sprint 56 until that surface is confirmed.
2. **Forbidden-vocabulary guard trap** — `governance.py` holds `codesys` inside guard/regex string literals (e.g. "codesys project generation"). A naive global rename would weaken a safety guard. Use word-boundary identifier-only scoping; `governance.py` is **out of migration scope**.
3. **Immutable records** — ADRs 0001/0002 superseded not edited; historical `SPRINTNN_REPORT.md` left untouched.
4. **Vendor over-assertion** — never set EAE rows to `confirmed_by_manual` before the SPIKE delivers manual-grounded evidence.
5. **Pass-count drift** — any change in the 655 test count (up or down) without an explicit, reviewed reason is a stop condition.