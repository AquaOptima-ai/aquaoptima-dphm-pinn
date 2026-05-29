# Sprint 33 — Pillar B locked-March-2026 OUT-OF-SAMPLE holdout evaluation

`SPRINT33_STATUS: COMPLETE`
`SPRINT33_GATE: FAIL`

> **One-line verdict.** On the locked March-2026 holdout, the Sprint-32-frozen
> Pillar B matched-condition efficiency envelope produces ZERO positive
> opportunity under the conservative (p25) SE quantile. Per the FROZEN,
> PRE-REGISTERED Sprint-33 acceptance rule, this is a HONEST FAIL. The frozen
> efficiency_gate.py was byte-identical before and after evaluation
> (`sha256=f2f6bd91d429a6fe80ed7524766782346e8a4b343258f38ccbf2dcb4755b059d`).

---

## 1. What this sprint does, and what it deliberately does not do

Sprint 33 is the SCIENTIFIC GATE for Pillar B: it scores the FROZEN 2025
matched-condition efficiency envelope against the locked March-2026 OperatingPoints.

The honest contract:

- **The 2025 envelope is FROZEN.** Every knob lives in
  `src/aquaoptima/advisory/efficiency_gate.py` and was declared in Sprint 32
  BEFORE March was touched. The orchestrator
  (`scripts/sprint33_locked_march_eval.py`) records the on-disk SHA-256 of
  that file at the start of the run, asserts it equals the post-run hash
  (`pre_eq_post=true`), and writes both into the scorecard.
- **March 2026 is the HOLDOUT.** It is only scored; it is never used to fit,
  tune, or re-derive any envelope parameter. The leakage guard is bidirectional:
  - the 2025 envelope frame raises on any 2026-03 key (Sprint-32 guard,
    `assert_operating_points_no_march_2026`);
  - the March-2026 input frame raises on any non-2026-03 key
    (Sprint-33 guard, `assert_holdout_inputs_are_march_2026`).
- **Counterfactual offline opportunity only.** The output is a HYPOTHETICAL kWh
  number under the conservative (p25) and aggressive (p10) historical envelope
  quantiles. It is not a guarantee, not a savings claim, not a control
  recommendation, not a setpoint. The "cannot claim" section below is binding.
- **Offline, advisory-only.** No setpoints, no actuation, no live integration,
  no edge SDK imports, no write path of any kind. Every artifact carries
  `advisory_only=True`, `evaluation_mode='offline_only'`, and
  `is_evidence_not_setpoint=True`.
- **A FAIL is a valid outcome.** The Sprint-33 acceptance rule is applied
  honestly to the locked holdout; the orchestrator never re-tunes to pass.

---

## 2. Files changed (and the one file that was NOT changed)

| File | Status | Lines | Purpose |
|---|---|---:|---|
| `src/aquaoptima/advisory/efficiency_gate.py` | **UNCHANGED — frozen pre-registration** | 234 | Sprint-32 frozen knobs; hash recorded + verified |
| `src/aquaoptima/advisory/locked_march_holdout.py` | **NEW** | ~590 | Sprint-33 holdout engine + acceptance gate |
| `tests/advisory/test_sprint33_locked_march.py` | **NEW** | ~480 | 14 TDD tests for the holdout mechanics |
| `scripts/sprint33_locked_march_eval.py` | **NEW** | ~250 | CLI orchestrator (loads March CSV, runs SE engine, writes scorecard) |
| `data/eval/pillarB/sprint33_locked_march_scorecard.json` | **NEW** | — | The honest scorecard |
| `SPRINT33_REPORT.md` | **OVERWRITTEN** | this file | Sprint-33 narrative (the placeholder was for a different Sprint 33 in another roadmap) |

**Frozen-gate integrity probe.** SHA-256 of
`src/aquaoptima/advisory/efficiency_gate.py`:

- before evaluation: `f2f6bd91d429a6fe80ed7524766782346e8a4b343258f38ccbf2dcb4755b059d`
- after evaluation:  `f2f6bd91d429a6fe80ed7524766782346e8a4b343258f38ccbf2dcb4755b059d`
- byte-identical: yes (`scorecard.frozen_gate.pre_eq_post == true`)
- a dedicated test (`test_recorded_frozen_gate_sha_matches_actual_on_disk_hash`)
  reads the on-disk file and asserts the scorecard's recorded SHA equals it.

---

## 3. Out-of-sample protocol

```
2025 source CSV ──► Sprint-31 SE engine ──► 2025 OperatingPoints (n=9,414)
                                                   │
                                                   ▼
                                            FROZEN Sprint-32
                                            matched-condition envelope
                                            (tolerances, p25/p10 SE quantiles,
                                             min_support=30, gate_version=
                                             sprint32.envelope.v1)
                                                   │
locked March-2026 ──► Sprint-31 SE engine ──► March OperatingPoints (n=58)
source CSV          (SAME engine, March-only       │
                     filter; auto-mode only)       ▼
                                            produce_advisory()
                                                   │
                                                   ▼
                                    coverage waterfall + kWh opportunity
                                       (p25 + p10) + MVPv1 alignment +
                                       acceptance gate
                                                   │
                                                   ▼
                                       sprint33_locked_march_scorecard.json
```

**Hard contracts during the holdout:**

1. The 2025 envelope frame is loaded from the Sprint-31 cached export
   (`data/eval/pillarB/operating_points_30min_2025.csv`); it is asserted to
   contain ZERO 2026-03 keys (`assert_operating_points_no_march_2026`).
2. The March-2026 frame is loaded from the locked source CSV
   (`/home/hunter_lin/projects/yilan-site-model-testing/yearlong_drive/source1_2026.csv`),
   filtered to `2026-03` at three layers (the loader, the OperatingPoint
   `window_start` check, and the `assert_holdout_inputs_are_march_2026` guard),
   then passed through the SAME Sprint-31 SE engine with default `EngineConfig`.
3. For every March OperatingPoint, `produce_advisory()` queries the FROZEN
   2025 envelope. The MIN_SUPPORT=30 floor and the matching tolerances are
   pulled directly from `efficiency_gate`; the gate file's hash is the
   pre-registration probe.

---

## 4. Holdout window

```
csv_path:         /home/hunter_lin/projects/yilan-site-model-testing/yearlong_drive/source1_2026.csv
first_timestamp:  2026-03-01 00:00:53
last_timestamp:   2026-03-31 23:59:19
all_in_2026_03:   true
n_rows:           44,469
n_operating_points (30-min): 58
window_minutes:   30
```

---

## 5. Coverage and exclusion waterfall

```
Raw March-2026 rows                                  44,469
SE-engine intervals (44,469 - 1)                     44,468
  ├── kept (auto-mode + finite + within gap)          1,689   ( 3.8%)
  ├── excluded "unprofiled_mode_other"               42,624   (95.8%) -- MANUAL mode
  ├── excluded "pump_off"                               130
  ├── excluded "nan_input"                               22
  └── excluded "gap_too_long"                             3

30-min OperatingPoints aggregated                        58
  ├── supported (>= MIN_SUPPORT historical neighbours)   21   (36.2%)
  └── unsupported (insufficient_support, n<30)           37   (63.8%)
       └── all 37 rejected with reason "insufficient_support";
           zero savings claimed on any of them (verified by
           "no_unsupported_interval_produces_savings": passed)
```

**Coverage interpretation.** The MOST IMPORTANT finding of this sprint is in
the waterfall, not the verdict: in March 2026, the pump operated in MANUAL
mode for 95.8% of the time. The Sprint-31 SE engine -- by frozen design --
excludes manual-mode intervals from the auto-mode efficiency envelope (Q1 in
PRD §10.1; default `EngineConfig.excluded_modes = {manual, other}`). That
leaves only 1,689 auto-mode intervals across all of March, which aggregate
into 58 30-min OperatingPoints. Of those, 21 have enough 2025 neighbours
under the FROZEN matching tolerances to receive an envelope advisory.

This is itself an honest limitation worth surfacing: **a frozen 2025 auto-mode
envelope cannot make any claim about the 95.8% of March that ran in manual
mode.** Any future Pillar B that wants to score manual-mode efficiency would
need a SEPARATE manual-mode envelope, declared and frozen BEFORE March.

---

## 6. Estimated offline kWh opportunity (counterfactual, conservative)

```
n_supported_intervals:                       21
march_observed_energy_kwh (supported):  498.654 kWh
march_volume_m3        (supported):    7,140.6  m^3

kwh_p25 (conservative, primary):          0.000 kWh   <-- ZERO opportunity
kwh_p10 (aggressive,  reported):          1.310 kWh   <-- 0.26% of observed
                                                          energy on supported
                                                          intervals; not robust
robust_under_conservative:                false

avoided_cost:                              null
tariff_source:                             null  (no tariff supplied; we do
                                                  not invent one per PRD §10.1 Q6)
```

**What this means.** On the 21 March operating points where the frozen 2025
envelope has enough historical support to produce an advisory, March's
observed SE is ALREADY AT OR BELOW the conservative (p25) SE quantile of
matched 2025 conditions. Concretely, three supported windows
(`samples.supported_head`):

| March window (UTC) | observed SE (kWh/m³) | 2025 envelope p25 SE | opp p25 (kWh) | opp p10 (kWh) |
|---|---:|---:|---:|---:|
| 2026-03-03 01:30 | 0.0690 | 0.0725 | 0.000 | 0.000 |
| 2026-03-04 01:30 | 0.0700 | 0.0723 | 0.000 | 0.000 |
| 2026-03-05 01:30 | 0.0688 | 0.0725 | 0.000 | 0.000 |

In other words: when the pump WAS running in auto mode in March, it was
operating efficiently relative to the 2025 envelope. There is no
conservative-quantile opportunity to claim.

The aggressive-quantile (p10) opportunity exists but is tiny (1.310 kWh
across 21 intervals, ~0.26% of observed supported energy). The frozen
acceptance rule requires robustness under the CONSERVATIVE quantile, so this
is FAIL.

---

## 7. MVPv1 comparison

No MVPv1 March control log was supplied to the orchestrator. Per the FROZEN
Sprint-32 contract (C4 in `efficiency_gate.MVPV1_MIN_OVERLAP_FRACTION = 0.80`),
the comparison is REJECTED with reason `no_mvpv1_log_provided` and no
comparison is produced. The criterion
`mvpv1_comparison_valid_where_reported` passes vacuously (we honour the
"valid where reported, otherwise honestly unavailable" invariant by
construction).

```
mvpv1_comparison: {
  available:           false,
  valid:               false,
  comparison_produced: false,
  rejection_reason:    "no_mvpv1_log_provided"
}
```

---

## 8. Leakage and safety checks

```
march_only_input:                  true
isolation_assert_passed:           true
holdout_prefix:                    "2026-03"
n_2025_ops_in_envelope:            9,414
n_march_ops_scored:                58
frozen_gate_file_sha256_at_eval:   f2f6bd91d429a6fe80ed7524766782346e8a4b343258f38ccbf2dcb4755b059d
frozen_gate_file_sha256_post_eval: f2f6bd91d429a6fe80ed7524766782346e8a4b343258f38ccbf2dcb4755b059d
pre_eq_post:                       true
march_used_for_tuning:             false

safety:
  advisory_only:           true
  evaluation_mode:         "offline_only"
  write_path:              "scorecard_json_only"
  influences_control:      false
  site_integration_allowed:false
  is_evidence_not_setpoint:true
  scorecard_role:          "advisory_evidence_only"
```

C5 ("leakage_and_safety_checks_pass") PASSES.

---

## 9. Acceptance gate — applied honestly

The five frozen PASS criteria, evaluated on the locked March-2026 holdout:

| # | Criterion | passed |
|---|---|:---:|
| C1 | `coverage_meaningful_or_limitations_explained` | **PASS** |
| C2 | `positive_opportunity_robust_under_conservative_quantile` | **FAIL** |
| C3 | `no_unsupported_interval_produces_savings` | **PASS** |
| C4 | `mvpv1_comparison_valid_where_reported` | **PASS** |
| C5 | `leakage_and_safety_checks_pass` | **PASS** |
| —  | **OVERALL** | **FAIL** |

PASS rule:

> Sprint 33 PASS iff: coverage_meaningful_or_limitations_explained AND
> positive_opportunity_robust_under_conservative_quantile AND
> no_unsupported_interval_produces_savings AND
> mvpv1_comparison_valid_where_reported AND
> leakage_and_safety_checks_pass.

Since C2 fails, the OVERALL verdict is **FAIL**, recorded honestly. No tuning,
no re-fitting, no re-thresholding was done to chase a PASS.

---

## 10. Cannot claim (per PRD §10.3)

This sprint MUST NOT and DOES NOT say any of the following:

- AquaOptima saved X kWh in March 2026.
- AquaOptima will save X% if deployed.
- The pump should run at speed Y.
- The setpoint is safe.
- The advisory outperforms MVPv1 control.
- Savings are guaranteed.

What is ALLOWED (and is what this scorecard reports):

- "In offline historical replay on the locked March-2026 holdout, the
  Pillar B matched-condition envelope identified an estimated COUNTERFACTUAL
  OPPORTUNITY of 0.000 kWh under the conservative p25 quantile and 1.310 kWh
  under the aggressive p10 quantile, summed over 21 supported intervals."
- "Under similar historical demand/level/pressure/flow conditions, observed
  March SE was at or below the 2025 p25 SE envelope."
- "This is a counterfactual offline estimate requiring future operational
  validation."
- "No control action was taken."

**Honest limitations** (also recorded verbatim in
`scorecard.out_of_sample_protocol.honest_limitations`):

1. March 2026 has NO ground-truth efficiency labels. We compare observed
   March SE to a 2025-derived envelope; we cannot claim what would have
   happened in production.
2. The counterfactual energy assumes the pump COULD have operated at the
   bucket's p25/p10 SE under the same demand/level/pressure/flow context.
   Realising any such opportunity would require future operational
   validation under the same hydraulic constraints.
3. 95.8% of March ran in MANUAL mode and is excluded from the auto-mode
   envelope by design. The Sprint-33 scorecard makes ZERO claim about
   manual-mode efficiency.
4. 37 of 58 (63.8%) auto-mode March OperatingPoints were REJECTED for
   insufficient historical support (< 30 neighbours under the frozen
   tolerances). These intervals carry ZERO claim.
5. MVPv1 control-log comparison is produced ONLY where the frozen alignment
   diagnostic passes; otherwise the comparison is marked unavailable, never
   approximated.
6. Offline only. No setpoints, no actuation, no live integration, no site
   write path of any kind.

---

## 11. Validation

```bash
# Full advisory test suite (171 tests, 0 fail).
python -m pytest tests/advisory/ -q
# .........................................................................[100%]
# 171 passed in 6.82s

# Full repo test suite (2,591 tests, 0 fail, 1 pre-existing skip).
python -m pytest tests/ -q --timeout=120
# 2591 passed, 1 skipped in 120.27s

# Run the honest locked-March holdout end-to-end.
python scripts/sprint33_locked_march_eval.py
# [sprint33] frozen gate sha256 (pre-eval) : f2f6bd91d429...
# [sprint33] 2025 envelope ops: 9414; march-2026 ops: 58 (rows=44469)
# [sprint33] scorecard written to data/eval/pillarB/sprint33_locked_march_scorecard.json
# [sprint33] verdict: FAIL
# [sprint33] coverage: total=58, supported=21, unsupported=37
# [sprint33] opportunity: p25=0.000 kWh, p10=1.310 kWh, robust_under_conservative=False

# Frozen-gate integrity probe (must equal the value recorded in the scorecard).
sha256sum src/aquaoptima/advisory/efficiency_gate.py
# f2f6bd91d429a6fe80ed7524766782346e8a4b343258f38ccbf2dcb4755b059d  src/aquaoptima/advisory/efficiency_gate.py
```

---

## 12. What the Sprint 33 FAIL tells us

A FAIL on the locked holdout is a VALID, VALUABLE outcome. The Sprint-33
honest verdict says, evidence-first:

1. **The 2025 auto-mode efficient envelope did not transfer to a positive
   conservative-quantile opportunity in March 2026** because the auto-mode
   operation in March was already at or below the 2025 p25 SE quantile under
   matched conditions. The pump was being operated efficiently within the
   regime the envelope describes.
2. **March 2026 was overwhelmingly MANUAL mode (95.8%).** Any future Pillar B
   that wants to score manual-mode efficiency must build a DISTINCT manual-mode
   envelope, declared and frozen BEFORE the holdout is touched. The current
   frozen envelope intentionally has nothing to say about manual operation.
3. **The frozen Sprint-32 envelope is functioning as designed.** It refuses to
   extrapolate (37/58 = 63.8% of valid March operating points have <30
   neighbours under the frozen tolerances and are REJECTED), and it refuses
   to manufacture savings when March's observed SE is already below the p25
   envelope (every supported interval has 0 kWh opportunity at p25).

For the unified A+B package (Sprint 34), Pillar B's documented verdict is:
**FAIL on the locked March-2026 holdout, with the above honest scope
limitations.** No setpoint claims; no avoided-cost claims; no deployment
language.

---

## 13. Frozen-gate non-modification audit

Per the Sprint-33 brief: any byte-level change to
`src/aquaoptima/advisory/efficiency_gate.py` between Sprint 32 ship and
Sprint 33 evaluation is pre-registration tampering and a HARD STOP.

```
$ git log --oneline -- src/aquaoptima/advisory/efficiency_gate.py
9ce5a9f feat(advisory): AOPSO Sprint 32 - Pillar B matched-condition efficiency envelope + ... + frozen efficiency_gate.py

$ git diff HEAD -- src/aquaoptima/advisory/efficiency_gate.py
(no output -- file is identical to the Sprint-32 ship commit)

$ sha256sum src/aquaoptima/advisory/efficiency_gate.py
f2f6bd91d429a6fe80ed7524766782346e8a4b343258f38ccbf2dcb4755b059d  src/aquaoptima/advisory/efficiency_gate.py
```

The scorecard's `frozen_gate.gate_file_sha256_at_eval` and
`leakage_check.frozen_gate_file_sha256_at_eval` both record this hash, and
the dedicated test
`test_recorded_frozen_gate_sha_matches_actual_on_disk_hash` verifies it
matches the live on-disk file. The orchestrator also records
`gate_file_sha256_post_eval` and `pre_eq_post=true` after the run, with a
hard exit code (`EXIT_FROZEN_GATE_TAMPERED=5`) if the post-eval hash differs.

---

## 14. Status lines (required by Sprint 33 brief)

```
SPRINT33_STATUS: COMPLETE
SPRINT33_GATE: FAIL
```
