# AOPSO Sprint 32 — Pillar B matched-condition efficiency envelope + MVPv1 alignment

**SPRINT32_STATUS: COMPLETE**
**SPRINT32_GATE: PASS**

OFFLINE, ADVISORY ONLY. Speed ranges in this sprint are EVIDENCE of historically
observed 2025 operating points — they are NOT executable recommendations,
NOT setpoints, NOT control targets, and NOT a deployment-readiness signal. All
artifacts carry `advisory_only=True` and `is_evidence_not_setpoint=True`. No
edge SDK, no actuation, no write path, no live integration. The locked
March-2026 holdout is NOT touched in this sprint.

> Note: this file replaces a prior unrelated **dPHM** "Sprint 32 — Per-edge
> surrogate diagnostics for EPANET import" report that lives on `main` (commit
> `ea23c17`). That report is preserved in git history; the present working-tree
> copy is the **AOPSO Sprint 32** deliverable for branch
> `aopso/sprint32-pillarB-envelope`, per the Sprint 32 brief.

---

## 1. What this sprint built

Four new modules under `src/aquaoptima/advisory/` and one new test module —
**no existing file was modified**:

| File | Purpose |
|---|---|
| `efficiency_gate.py` | FROZEN matching tolerances + SE quantiles + min_support + MVPv1 thresholds. Hash-stable; SHA-256 pre-registration-ready for Sprint 33. |
| `efficiency_envelope.py` | `OperatingConditionQuery`, matched-condition search, p10/p25 envelope, observed efficient speed range, rejection records, batch evaluation. |
| `efficiency_mvpv1_alignment.py` | MVPv1 control-log alignment diagnostic with timestamp-window match + demand-disagreement bound. |
| `sprint32_envelope.py` | Scorecard orchestrator + CLI. Writes `data/eval/pillarB/sprint32_envelope_scorecard.json`. |
| `tests/advisory/test_sprint32_envelope.py` | 21 tests covering all five Sprint 32 gate criteria + leakage guard + hash-stability. |

The contracts SDK, `health_gate.py`, and every Sprint 27–31 file are
untouched (`git status` shows only NEW files were added).

---

## 2. Frozen Pillar B parameters

Declared in source in `efficiency_gate.py` **before** the March-2026 holdout
is touched. Re-tuning requires a new module + GATE_VERSION (audit-trail
preserving), exactly like Pillar A's v1/v2 gate split.

```
gate_version:                          sprint32.envelope.v1
frozen:                                true
march_used_for_tuning:                 false

se_quantiles:                          [0.10, 0.25]
se_quantile_primary (efficient bar):   0.25
se_quantile_aggressive (transparency): 0.10
min_support:                           30
speed_range_se_cutoff_quantile:        0.25

matching_tolerances (absolute):
  mean_demand_m3_per_h:                50.0
  mean_level_m:                        0.25
  mean_pressure_m_head:                0.50
  mean_flow_m3_per_h:                  50.0
matching_channels (canonical order):
  [mean_demand_m3_per_h,
   mean_level_m,
   mean_pressure_m_head,
   mean_flow_m3_per_h]

mvpv1_min_overlap_fraction:                  0.80
mvpv1_max_demand_disagreement_m3_per_h:      100.0
```

**Frozen-params SHA-256** (pre-register this in Sprint 33 and integrity-check
before touching March):

```
f7d6145492787c3c451f7334837536559939a766f4ae905f47aa83968f146e9e
```

---

## 3. Matched-condition search

`matched_search(ops, query)` returns the positional row indices of
OperatingPoints whose four context channels (demand, level, pressure, flow)
each lie within their FROZEN per-channel tolerance of the query. The reported
match-distance metric is the L∞-norm of `|delta| / tolerance` across the four
channels (0 = perfect match, 1 = at tolerance boundary).

The summary block on each query exposes `min`, `mean`, `max` of the per-row
L∞ normalised distance. Any OperatingPoint with NaN in any matching channel
is excluded (we never match a row whose context is unknown).

---

## 4. p25 / p10 SE envelopes per matched bucket

Within each matched bucket, `compute_envelope` returns p10, p25, and median
of `specific_energy_kwh_per_m3` using numpy's deterministic linear
interpolation. The conservative efficient envelope is p25; p10 is reported
alongside for transparency.

Observed efficient speed extraction (`extract_observed_speed_range`):

* Define the efficient sub-bucket as rows whose SE ≤ p25.
* Report `speed_min_hz`, `speed_max_hz`, and the rounded distinct **set** of
  efficient speeds.
* Verify that every reported speed appears in the FULL 2025 observed speed
  multiset (`all_speeds_historically_observed`). The Sprint-32 gate **fails**
  the scorecard if this check ever returns False — there is a test that
  monkey-patches a synthetic unobserved speed into the pipeline and confirms
  the gate FAILs.

---

## 5. Envelope examples on the real 2025 OperatingPoints

Inputs: `data/eval/pillarB/operating_points_30min_2025.csv` (9 414 rows; eight
2025 months: 2025-03, 04, 05, 06, 07, 10, 11, 12 — March-2026 is **not**
present).

Default example queries derive from the data's own (p25, p50, p75) of the
matching channels, plus one far-OOD demand query that should be REJECTED.

| Query label | Comparable count | SE p10 | SE p25 | Observed efficient speed range (Hz) | n efficient |
|---|---:|---:|---:|---|---:|
| `data_quantile_p25` | 14 | — | — | REJECTED (insufficient_support, < 30) | — |
| `data_quantile_p50` | 329 | 0.0941 | 0.0963 | 41.00 – 58.00 | 83 |
| `data_quantile_p75` | 108 | 0.0908 | 0.0920 | 43.97 – 46.00 | 27 |
| `far_ood_demand`    |   0 | —      | —      | REJECTED (insufficient_support, 0)   | — |

Every speed in every reported range is, by construction AND verified by the
post-hoc check, a historically observed 2025 pump-speed value.

---

## 6. Unsupported-interval rejection

Rejection counts on the real-2025 scorecard run:

```
n_rejected: 2
reasons:
  insufficient_support: 2     (data_quantile_p25 and far_ood_demand)
```

`insufficient_support` triggers whenever `comparable_count < min_support`
(30). A second reason, `no_observed_efficient_speeds`, is emitted if the
matched bucket has support ≥ 30 but no efficient sub-bucket sample carries a
finite observed speed — this branch is exercised by the unit suite.

Every rejection record carries the query, the comparable_count, the reason,
and a detail block with the FROZEN `required_min_support`. No advisory in
this sprint relies on extrapolation; every advisory's speeds are
subset-of-observed-2025 by structural construction + post-hoc verification.

---

## 7. MVPv1 control-log alignment

The PRD Q5 risk (misaligned logs → false advisory-vs-control conclusions) is
addressed by `efficiency_mvpv1_alignment.diagnose_mvpv1_alignment`. A log row
is ALIGNED iff:

1. Its timestamp falls inside some OperatingPoint's
   `[window_start, window_end)` window.
2. `|mvpv1_demand − op.mean_demand_m3_per_h| ≤ MVPV1_MAX_DEMAND_DISAGREEMENT`
   (100 m³/h).

The diagnostic PASSES iff `coverage = n_aligned / n_log_rows ≥ 0.80` AND the
median demand disagreement on aligned rows is within the bound. Otherwise the
report is REJECTED with reason `alignment_below_threshold`. Edge cases
(`None`, empty, missing required columns) each emit a distinct rejection
reason and never produce a misaligned comparison.

**Coverage on this sprint's real-data run:** No MVPv1 log was supplied to the
scorecard CLI, so the report records `n_log_rows = 0`, `coverage = 0.0`, and
`rejection_reason = no_mvpv1_log_provided`. The Sprint-32 gate criterion C4
("MVPv1 comparison produced ONLY where alignment is valid") **passes**
because no comparison was produced — the invariant holds vacuously. Sprint 33
must supply a real log to convert this vacuous pass into substantive evidence.

---

## 8. Acceptance gate verdict

Gate identity: `sprint32.envelope.v1`. PASS iff all five criteria hold.

| # | Criterion | Outcome on real-data run |
|---|---|---|
| C1 | Advisories require minimum historical support (frozen `min_support = 30` enforced) | **PASS** — all produced advisories have comparable_count ≥ 30 (min = 108). |
| C2 | All reported speed ranges are historically observed (no extrapolation) | **PASS** — every reported efficient speed value is a member of the 2025 observed-speed multiset. |
| C3 | Unsupported intervals are rejected with reasons | **PASS** — 2 rejections, both with reason `insufficient_support` and a detail block. |
| C4 | MVPv1 comparison produced ONLY where alignment is valid | **PASS (vacuous)** — no log was supplied, so no comparison was produced; invariant holds. |
| C5 | Matching tolerances + SE quantiles FROZEN before March | **PASS** — `efficiency_gate.MARCH_USED_FOR_TUNING = False`; scorecard `march_used_for_tuning = False`; SHA-256 of `frozen_params` recorded for Sprint 33 pre-registration. |

**Overall verdict: PASS.**

Scorecard written to `data/eval/pillarB/sprint32_envelope_scorecard.json`.

---

## 9. Tests

```
tests/advisory/test_sprint32_envelope.py ..................... 21 passed
full repo suite:                                              2577 passed, 1 skipped
```

The 21 Sprint-32 tests cover:

- **G-class.** `efficiency_gate` constants are importable, frozen, and the
  canonical JSON + SHA-256 are deterministic across calls.
- **C1.** `produce_advisory` returns an `EnvelopeRejection` with reason
  `insufficient_support` when the matched bucket has fewer than `MIN_SUPPORT`
  rows; an `EnvelopeAdvisory` when it has at least `MIN_SUPPORT`.
- **Matched search.** Returns exactly the in-tolerance neighbours on a
  fixture; rejects NaN-context rows; OOD queries get zero matches.
- **Envelope math.** p10, p25, and median match closed-form values on a
  `range(0, 100)` SE fixture; empty bucket → all NaN.
- **C2.** Reported efficient speeds are always in the 2025 observed-speed
  multiset; the efficient sub-bucket's SE never exceeds the bucket's p25; the
  scorecard FAILs when an unobserved speed is monkey-patched into the
  pipeline.
- **C3.** Every rejection record carries a recognised reason; the scorecard's
  rejection block lists count + per-reason buckets.
- **C4.** Clean MVPv1 fixture → diagnostic PASS; misaligned (shifted +10
  days) fixture → REJECTED with `alignment_below_threshold`; demand
  disagreement → REJECTED; `None`/empty/missing-columns → distinct rejection
  reasons.
- **C5.** A 2026-03 window-start in the OperatingPoints raises `ValueError`
  before any compute (via the Sprint-27 leakage guard); a pure-2025 fixture
  passes. The scorecard reports `march_used_for_tuning = False` and the
  frozen-params SHA-256.

---

## 10. Cannot claim

Even though Sprint 32 verdict is PASS, the following claims are **NOT**
supported by this sprint's evidence:

- **No "AquaOptima will save X%."** We have not run a holdout. We have only
  shown the offline shape of historically realized efficient operating
  points at matched conditions, and the rejection logic for queries we
  cannot serve.
- **No "Run the pump at speed Y."** Every reported speed range is OFFLINE
  EVIDENCE — historically observed in 2025 — and is explicitly labelled
  `is_evidence_not_setpoint=True`. There is no setpoint output, no control
  endpoint, no live integration, and no write path anywhere in this sprint.
- **No "The advisory outperforms MVPv1."** No MVPv1 control log was supplied
  to this sprint's scorecard run. The C4 PASS is **vacuous** — we did not
  produce a misaligned comparison, but we have also not produced a valid
  one. Sprint 33 must supply a real log to make this substantive.
- **No "March-2026 results."** The locked holdout is **untouched**. This
  sprint freezes the matching tolerances + SE quantiles + min_support +
  alignment thresholds BEFORE March is ever evaluated. Sprint 33 is the
  honest holdout evaluation.
- **No "Edge / site deployment readiness."** The PRD packaging unblock
  policy remains in force: even after both pillars produce explicit
  verdicts, site integration and control endpoints stay BLOCKED in this
  version.
- **No coverage claim across all operating conditions.** The example
  queries in the scorecard are example-driven evidence (data quantiles plus
  one far-OOD query). Full-distribution coverage is a Sprint 33 question
  against the locked March-2026 holdout.

The frozen `efficiency_gate` SHA-256 above is the binding artefact for
Sprint 33 — pre-register it, integrity-check it, then unlock the holdout.

---

## 11. Files added (none modified)

```
src/aquaoptima/advisory/efficiency_gate.py
src/aquaoptima/advisory/efficiency_envelope.py
src/aquaoptima/advisory/efficiency_mvpv1_alignment.py
src/aquaoptima/advisory/sprint32_envelope.py
tests/advisory/test_sprint32_envelope.py
data/eval/pillarB/sprint32_envelope_scorecard.json
SPRINT32_REPORT.md  (replaces the prior dPHM Sprint 32 report from commit ea23c17;
                     preserved in git history on main)
```

No commits made, no pushes made, no history rewritten.
