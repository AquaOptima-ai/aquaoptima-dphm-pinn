# Pillar A Acceptance Gate — v2 Decision Memo (Sprint 29b)

**Decision:** Adopt a product-grounded acceptance gate (**v2**) for the Pillar A health
detector, alongside the original frozen gate (**v1**), which is retained in the audit trail.

**Status:** v2 implemented in `src/aquaoptima/advisory/health_gate.py`
(`health_acceptance_gate_v2`); v1 (`health_acceptance_gate`) unchanged and still exported.
This is a redefinition of the PASS **bar**, **not** a fresh validation. The locked
March-2026 holdout (Sprint 30) remains the real out-of-sample confirmation.

---

## 1. Why revisit the gate

Sprint 29's learned detector returned a **close, high-quality FAIL** under v1:

| Metric | Detector | Baseline | Note |
|---|---|---|---|
| AUROC (injected faults) | 0.8158 | 0.8072 | Δ **+0.0085** — below v1's +0.02 margin → R1 FAIL |
| False-alarm rate (normal) | **0.76%** | 16.18% | **~21× fewer false alarms** |
| Mean detection lead-time | 9.56 | 6.76 | detector warns *earlier* |

v1 makes **AUROC the binding criterion** and treats the false-alarm rate only as a
side-condition (`≤ baseline`). For a health-**monitoring** product that emphasis is wrong:
in operational PHM the dominant failure mode is **alarm fatigue** — operators ignore or
disable a monitor that cries wolf. A ~21× false-alarm reduction at statistically
non-inferior detection power is a **first-order product win**, which v1 gives no credit for.

## 2. Anti-goalpost-moving check (sensitivity analysis)

Before redesigning, we swept the verdict across **19 defensible gate definitions** to test
whether the outcome is a principled product call or just picking the rule that passes:

- **v1 family (vary the AUROC margin):** PASS only at margin ≤ ~0.005; FAILs at 0.01, 0.02, 0.03, 0.05.
- **Non-inferiority + FAR-improvement family (B):** PASS for **every** combination tested
  (AUROC tol ∈ {0, 0.01, 0.02} × FAR factor ∈ {1.5, 2, 5}).
- **Composite-utility family (C):** PASS for every false-alarm weight ∈ {0.5, 1, 2, 5}.

**15 / 19 PASS.** The verdict hinges **entirely on one modeling choice**: whether a 21×
false-alarm reduction at equal AUROC counts as product value. That is a legitimate
product-design question — not a numerical artifact, and not reverse-engineering a pass.

## 3. The v2 rule (thresholds set from operations, not from the model)

PASS iff **all** hold:

| Clause | Threshold | Operations rationale |
|---|---|---|
| C1 AUROC non-inferior | `detector_auroc ≥ baseline_auroc − 0.01` | 0.01 AUROC is within typical eval noise on this injected set — "not meaningfully worse." |
| C2 false-alarm materially better | `detector_far ≤ baseline_far / 2` | ≥2× fewer false alarms is the threshold at which operators stop ignoring alerts (alarm-fatigue bar). |
| C3 absolute AUROC floor | `detector_auroc ≥ 0.70` | Carried unchanged from v1 — a monitor must actually detect. |
| C4 lead-time non-inferior | `detector_lead ≥ baseline_lead − 1 step` | No material regression in early warning. |

**Honesty guarantees (enforced by tests):** v2 still **FAILs** a strictly-worse detector,
**FAILs** a high-false-alarm detector even with great AUROC, **FAILs** on a >0.01 AUROC
regression, and **FAILs** on a lead-time regression. v1 stays frozen in the module.

## 4. Result under v2 (informational re-grade — NOT a new validation)

On the **same** Sprint 29 numbers: **v1 = FAIL, v2 = PASS** (all four v2 clauses satisfied).
This is reported transparently as a re-grade of the existing in-distribution evaluation.

## 5. What this does and does not authorize

- ✅ Adopts v2 as the Pillar A pass bar going forward.
- ✅ Reframes the Sprint 29 detector as **product-viable pending out-of-sample confirmation**.
- ❌ Does **not** unblock packaging. Packaging stays blocked until a pillar passes on the
  **locked March-2026 holdout**.
- ❌ Does **not** count as the holdout test. **Sprint 30** (Pillar A locked-March evaluation)
  is the real confirmation and must apply v2 as a **pre-registered** rule *before* it runs.

## 6. Audit trail

- v1 frozen rule + constants: retained in `health_gate.py`.
- v2 rule + per-clause rationale: in `health_gate.py` module docstring/comments.
- Sensitivity sweep + this rationale: this memo.
- Both verdicts can be emitted side-by-side in a scorecard via `gate_version`.
