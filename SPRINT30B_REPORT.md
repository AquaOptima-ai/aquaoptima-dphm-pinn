# AOPSO Sprint 30b — Pillar A full-year-2025 confirmatory holdout eval (pre-registered v2)

## TL;DR

Sprint 30 PASSED the locked March-2026 holdout under the pre-registered v2
acceptance gate, but the 30 k-row 2025 fit subset collapsed onto **late-March
2025 only** (the head-of-CSV cap landed in the first contiguous auto-mode
block). That made it a *same-season* March-2025 → March-2026 comparison and
likely flattered generalization.

Sprint 30b removes that confounder. Same locked March-2026 holdout, same
**pre-registered v2 acceptance gate imported as-is from main** (no thresholds
touched), but the detector + baseline are now fit on **150 000 rows
stratified across 8 distinct 2025 auto-mode months** (Mar / Apr / May / Jun /
Jul / Oct / Nov-tiny / Dec) instead of a single late-March slice.

The pre-registered v2 verdict on this broader, multi-season fit is **PASS** —
on every clause — and the detector got materially *better* on most metrics
than under the Sprint-30 narrow fit. Pillar A is robust to seasonal
distribution shift on this site.

```
SPRINT30B_GATE: PASS
SPRINT30B_STATUS: COMPLETE
```

Real numbers (out-of-sample, locked March-2026):
- detector AUROC = **0.9436** (Sprint 30 was 0.9299, **+0.0137**)
- baseline AUROC = **0.9175** (Sprint 30 was 0.8781, **+0.0394**)
- detector FAR on injected set = **0.0128** (Sprint 30 was 0.0245, **−47 %**)
- baseline FAR on injected set = **0.0518** (Sprint 30 was 0.4262, **−88 %**)
- detector mean lead-time = **15.82 steps** (Sprint 30 was 6.93, **+8.89**)
- raw-March alarm rate: detector = **1.23 %** (Sprint 30: 2.37 %), baseline
  = **5.18 %** (Sprint 30: 42.67 %)

The baseline got dramatically quieter once it saw real seasonal variability
(its narrow late-March fit was clearly mis-specified). The detector got
quieter *and* earlier-firing. PASS is not a tuned outcome — the gate was
frozen on `main` and re-imported, never redefined.

---

## 1. The one thing this sprint fixed

Sprint 30 used `load_2025_auto_train` with `subset=30_000`, which read from
the top of the 2025 CSV after a stable timestamp sort. The 2025 auto-mode
rows are non-contiguous (Jan/Feb/Aug/Sep have zero auto rows; Nov has 124),
and the first contiguous auto block starts **2025-03-06**. Result: the
30 k-row cap landed entirely inside `2025-03-06 .. 2025-03-28`.

That collapsed the protocol into March-2025 → March-2026 within-season, which
is the easiest possible distribution-shift. Sprint 30b replaces that fit
with a stratified per-month sample across **every** non-empty 2025 auto-mode
month, recorded auditably in `train_meta.per_month_rows`.

### Fit breadth — the per-month table

| month | rows in fit | of total auto rows in CSV |
|---|---:|---:|
| 2025-03 | 21 411 | (~7.9 %) |
| 2025-04 | 21 411 | (~7.9 %) |
| 2025-05 | 21 411 | (~7.9 %) |
| 2025-06 | 21 411 | (~7.9 %) |
| 2025-07 | 21 411 | (~7.9 %) |
| 2025-10 | 21 411 | (~7.9 %) |
| 2025-11 | **123** | (all available — only 123 auto rows exist) |
| 2025-12 | 21 411 | (~7.9 %) |
| **total** | **150 000** | (of 271 486 auto rows in source1_2025.csv) |
| **distinct months** | **8** | (≥ 5 required by gate) |

Strategy: equal per-month quota (`target_rows / n_months = 18 750`), each
month then padded up to its share of the requested 150 000 via a round-robin
of remaining capacity; sampled without replacement, seeded. No single month
carries > 14.3 % of the fit set (vs Sprint 30's **100 %** in March-2025).

Audit fields written to the scorecard's `train_meta`:
- `fit_strategy: "full_year_stratified_auto_mode_2025"`
- `distinct_months: 8` (the Hermes verifier hard-stops the merge if < 5)
- `n_auto_rows_total_in_csv: 271 486`
- `n_rows_after_auto_filter: 150 000`
- `timestamp_min / timestamp_max: 2025-03-06 .. 2025-12-31`
- `per_month_rows: {...}` (the table above)
- `min_distinct_months_required: 5`
- `seed: 0`

### Loader correctness

The Sprint-30 loader used pandas' default timestamp parsing, which the
underscore `%Y-%m-%d_%H:%M:%S` format trips up on some pandas versions.
Sprint 30b parses with the explicit `TIMESTAMP_FORMAT = "%Y-%m-%d_%H:%M:%S"`
constant from `aquaoptima.dataio.yilan_axis_map`. A unit test
(`test_underscore_timestamp_format_parses`) round-trips the format on a
synthetic CSV and asserts `parsed.notna().all()`.

---

## 2. Honesty rules followed (unchanged from Sprint 30)

- **Fitting**: detector + baseline fit on **2025 auto-mode rows ONLY**, now
  stratified across 8 distinct months. Never on March-2026.
  - The Sprint-27 `assert_holdout_isolated` leakage guard fires inside both
    `fit_health_detector` and `fit_health_baseline_suite`; a 2026-03 key in
    fit input raises `LeakageError` before any fit work happens
    (tripwire test:
    `tests/advisory/test_sprint30b_fullyear.py::test_fit_detector_rejects_march_2026_keys_from_builder_output`).
  - A second guard inside `build_stratified_2025_auto_fit` raises
    `LeakageError` if the 2025 CSV unexpectedly contains 2026 timestamps.
- **Pre-registered gate**: this sprint imports
  `aquaoptima.advisory.health_gate.health_acceptance_gate_v2` exactly as it
  exists on `main` after the Sprint-29b merge (commit `52ac365`). **No
  thresholds re-tuned, no clauses added or removed, no margins loosened.**
  The script records the four clause parameters as artifacts in
  `frozen_gate_v2` with `preregistered_before_evaluation: true,
  tuned_to_outcome: false`.
- **Reporting**: a FAIL would have been written as `SPRINT30B_GATE: FAIL`.
  The actual model verdict on the broad-fit locked holdout is **PASS** —
  the real outcome, not a forced result.
- **Safety boundary**: `evaluation_mode = offline_only`, `write_path = none`
  (scorecard JSON only), `influences_control = False`,
  `site_integration_allowed = False`. No `aquaoptima.edge` /
  `aquaoptima_contracts.edge` imports (verified by the governance
  import-connector scan: clean, 0 violations across 39 files scanned).

---

## 3. Protocol (unchanged from Sprint 30 except for the fit frame)

March 2026 still has no ground-truth anomaly labels. AUROC, lead-time, and
false-alarm rate are all label-conditional metrics. We use the same
two-track protocol as Sprint 30 to extract the most honest signal from an
unlabelled holdout:

### Track 1 — Labelled metrics on injected faults over real March normal

1. Build the **stratified 8-month 2025 auto-mode fit frame** (§1).
2. Fit detector + baseline on it.
3. **Inject** the Sprint-29 frozen-seed canonical fault families
   (`sensor_drift`, `stuck_flatline`, `spike`, `envelope_violation`) onto the
   **real March-2026 normal frames** (8 episodes per kind, 32 episodes
   total, frozen seed 29).
4. Run `evaluate_detector_vs_baseline` → AUROC, lead-time, false-alarm rate.
5. Apply the **pre-registered v2 acceptance gate** to the eval dict.
6. Compose Sprint-27 governance and force-FAIL on any guardrail violation.

### Track 2 — Unsupervised raw-March alarm rate

Run detector + baseline on raw, un-faulted March-2026 frames and record the
per-row alarm/flag rate. The most honest single number on truly unseen data.

### Holdout-isolation proof (positive)

`holdout_window` block:

| field | value |
| --- | --- |
| `csv_path` | `…/yearlong_drive/source1_2026.csv` |
| `first_timestamp` | `2026-03-01 00:00:53` |
| `last_timestamp` | `2026-03-31 23:59:19` |
| `n_rows` | `42 674` (all March 2026 rows after dropna on the 8 active axes) |
| `n_march_rows_total_before_cap` | `42 674` |
| `row_cap_applied` | `false` (default 50 000 cap was not hit — full March used) |
| `all_in_2026_03` | `true` |

Negative proof: the Sprint-27 leakage guards on the fit inputs would have
raised `LeakageError` if any March-2026 key had reached them — and they did
not.

---

## 4. Real numbers (out of sample, locked March-2026)

### Aggregate

| metric | detector | baseline | delta |
|---|---:|---:|---:|
| AUROC (injected on March-normal) | **0.9436** | **0.9175** | +0.0261 |
| false-alarm rate (injected set) | **0.0128** | **0.0518** | −0.0390 |
| mean lead-time (steps to first alarm post-onset) | **15.82** | **4.84** | +10.98 |
| raw-March flag rate (un-faulted, unsupervised) | **1.23 %** | **5.18 %** | −3.95 % |

### Injected-set composition

- 42 674 evaluation rows.
- 32 fault episodes (8 each of 4 kinds).
- 2 128 positive-label rows (≈ 4.99 % of the eval set).
- Identical to Sprint 30 by construction (same frozen seed 29 on the same
  locked March frames).

### Detection per fault kind (detector)

| kind | episodes | detected | misses | per-kind mean lead-time (steps) |
|---|---:|---:|---:|---:|
| sensor_drift | 8 | 8 | 0 | 55.375 |
| stuck_flatline | 8 | 4 | **4** | 0.0 |
| spike | 8 | 8 | 0 | 0.0 |
| envelope_violation | 8 | 8 | 0 | 0.0 |
| **total** | **32** | **28** | **4** | **15.82** |

### Detection per fault kind (baseline)

| kind | episodes | detected | misses | per-kind mean lead-time (steps) |
|---|---:|---:|---:|---:|
| sensor_drift | 8 | 8 | 0 | 13.5 |
| stuck_flatline | 8 | 7 | 1 | 6.0 |
| spike | 8 | 8 | 0 | 0.0 |
| envelope_violation | 8 | 8 | 0 | 0.0 |
| **total** | **32** | **31** | **1** | **4.84** |

Read: the baseline still catches slightly more `stuck_flatline` episodes
(7/8 vs detector 4/8 — flatlines on a quiet axis are an interpretable-rule
sweet spot). But the detector buys back **a 4.1× larger mean lead-time on
drift-style faults** (55 steps vs 14) and **runs at 4.0× lower false-alarm
rate** on the injected set. That trade — slightly fewer late catches in
exchange for a far earlier-firing and quieter monitor — is exactly the
alarm-fatigue trade the v2 gate was designed to credit, and it holds up
across the broader fit.

### Raw-March (un-faulted, unsupervised)

| | detector | baseline |
|---|---:|---:|
| flag rate (per row) | **1.23 %** | **5.18 %** |
| mean score / deviation | 0.0156 | 0.354 |

On real, unseen, un-faulted March-2026 operating data the broad-fit
detector cries wolf on **1.23 %** of rows (Sprint 30: 2.37 %) and the
broad-fit baseline cries wolf on **5.18 %** of rows (Sprint 30: **42.67 %**).
The Sprint-30 baseline's 42.7 % rate was the largest hint that something
was off with the fit frame — the broad fit drops it by an order of
magnitude.

---

## 5. Pre-registered gate v2 — clause-by-clause result

The gate is `health_acceptance_gate_v2` exactly as frozen on `main`
(commit `52ac365`, Sprint-29b). The four clauses (each must hold for PASS):

```
detector_auroc >= baseline_auroc - 0.01                              (C1)
AND detector_false_alarm_rate <= baseline_false_alarm_rate / 2       (C2)
AND detector_auroc >= 0.70                                           (C3)
AND detector_mean_lead_time >= baseline_mean_lead_time - 1.0         (C4)
```

| clause | parameter | actual | required | verdict |
|---|---|---:|---|:---:|
| C1 — AUROC non-inferior | tol = 0.01 | 0.9436 | ≥ 0.9175 − 0.01 = 0.9075 | **PASS** |
| C2 — FAR materially better | ≥ 2× improvement | 0.0128 | ≤ 0.0518 / 2 = 0.0259 | **PASS** (actual factor 4.05×) |
| C3 — AUROC absolute floor | min = 0.70 | 0.9436 | ≥ 0.70 | **PASS** |
| C4 — lead-time non-inferior | tol = 1 step | 15.82 | ≥ 4.84 − 1.0 = 3.84 | **PASS** |

All four clauses PASS. Composed with Sprint-27 governance
(`governance_status: PASS`) → final **verdict: PASS**.

```
SPRINT30B_GATE: PASS
```

---

## 6. Direct comparison: Sprint 30 (narrow March-2025 fit) vs Sprint 30b (full-year fit)

| metric | Sprint 30 | Sprint 30b | direction |
|---|---:|---:|:---:|
| fit set size | 28 931 rows | 150 000 rows | broader |
| fit set distinct 2025 months | **1** (March 06–28) | **8** (Mar–Jul, Oct, Nov-tiny, Dec) | broader |
| detector AUROC | 0.9299 | **0.9436** | better |
| baseline AUROC | 0.8781 | **0.9175** | better |
| detector FAR (injected) | 0.0245 | **0.0128** | better |
| baseline FAR (injected) | 0.4262 | **0.0518** | much better |
| detector mean lead-time (steps) | 6.93 | **15.82** | better |
| baseline mean lead-time (steps) | 1.48 | **4.84** | better |
| detector raw-March flag rate | 2.37 % | **1.23 %** | better |
| baseline raw-March flag rate | 42.67 % | **5.18 %** | much better |
| pre-registered v2 verdict | PASS | **PASS** | held |

Key observations:
- The detector got materially better on every single metric under the
  broader fit. The "good Sprint-30 number" was not a Sprint-30 artifact.
- The baseline improved even more dramatically — its narrow late-March fit
  was clearly mis-specified (42 % raw-March alarm rate is alarm-fatigue
  territory). Once it sees seasonal variation, it stabilises.
- The C2 improvement-factor margin tightened (17.4× → 4.05×) because the
  baseline FAR dropped so much, but it still beats the required 2.0×.
- C1 AUROC delta stayed positive (+0.026 vs +0.052) — the detector still
  beats a much stronger baseline.

Plain English: the detector's edge is not an artifact of a single
favourable season in the fit data. Pillar A's signal is real on this site.

---

## 7. Governance result (Sprint-27 guardrails)

`safety.governance` block:

| guard | result |
| --- | :--- |
| holdout-isolation (split manifest train/val keys vs `2026-03` window) | **PASS** (0 leaked keys, 213 train/val keys checked) |
| import / connector scan (`src/aquaoptima/{advisory,training,models,dataio}`) | **PASS** (0 violations across 39 files scanned, 0 `aquaoptima.edge` imports) |
| axis taxonomy (8 expected active axes, all backed, masked axis maps to None) | **PASS** |
| normalization coverage (8 axes × finite μ / σ > 0) | **PASS** |

`governance_status: PASS` → no override applied to the model verdict.

---

## 8. Verification gate (Sprint-30b IMPLEMENTATION pass)

| step | command | result |
| --- | --- | --- |
| 1 | `python -m pytest tests/advisory -q` | **122 passed** in 5.98 s |
| 2 | `python -m pytest tests -q` | **2 542 passed, 1 skipped** in 2 m 11 s (no regressions) |
| 3 | `python scripts/sprint30b_fullyear_holdout_eval.py` | wrote `data/eval/pillarA/sprint30b_fullyear_holdout_scorecard.json` with `verdict: PASS` and `train_meta.distinct_months: 8` (≥ 5 required) |

```
SPRINT30B_STATUS: COMPLETE
```

The five new tests (`tests/advisory/test_sprint30b_fullyear.py`):

1. underscore timestamp format `%Y-%m-%d_%H:%M:%S` parses every fixture row.
2. stratified fit-builder, on a tiny 5-month synthetic fixture, returns a
   set spanning all 5 expected months with roughly balanced counts (no
   single month > 50 %).
3. fit-builder raises `RuntimeError` when fewer than 5 distinct 2025 months
   are present (the Hermes verifier's contract is enforced at the source).
4. leakage tripwire: a 2026-03 timestamp injected into the fit-builder's
   output causes `fit_health_detector` to raise `LeakageError`.
5. end-to-end eval pipeline on tiny multi-month fixtures emits a real
   `gate_version='v2'` verdict dict (shape only; PASS/FAIL deliberately
   NOT asserted on synthetic data).

All five tests pass deterministically.

---

## 9. Files changed / written

- `scripts/sprint30b_fullyear_holdout_eval.py` (new) —
  stratified-full-year-2025 fit / score-on-March / v2-gate / governance /
  raw-March cross-check. CLI flags: `--fit-rows`, `--per-month-floor`,
  `--min-distinct-months`. Env knobs: `SPRINT30B_FIT_ROWS`,
  `SPRINT30B_FULL=1` (use every auto row + every March row),
  `SPRINT30B_MARCH_NROWS`.
- `tests/advisory/test_sprint30b_fullyear.py` (new) — 5 deterministic
  fixture-based tests; no full-CSV reads; total runtime 4 s.
- `data/eval/pillarA/sprint30b_fullyear_holdout_scorecard.json` (new) — the
  broad-fit out-of-sample scorecard with verdict, all metrics, holdout-
  isolation proof, **per-month fit breakdown**, governance block, and the
  safety boundary.
- `SPRINT30B_REPORT.md` (this file).

**Explicitly unchanged**:
- `aquaoptima_contracts/**` (contracts SDK is read-only).
- `src/aquaoptima/advisory/health_gate.py` — gate v2 imported unmodified.
  Pre-registration integrity preserved.
- All other modeling source, including `scripts/sprint30_holdout_eval.py`.
  Sprint 30b reuses Sprint 30's `rename_backing_to_canonical`,
  `load_march_canonical`, and `DEFAULT_*` constants via direct import.

---

## 10. What this PASS does and does not mean

It DOES mean:
- The Sprint-29 detector + Sprint-28 baseline, fit on a broad cross-section
  of 2025 normal operation, generalise to the genuinely unseen March-2026
  normal distribution: raw-March alarm rate is **1.23 %** (detector) and
  **5.18 %** (baseline).
- Against canonical injected faults on top of that real March-normal
  signal, the detector cleared the pre-registered v2 bar on every clause
  with margin: AUROC delta +0.026, FAR improvement 4.05× (vs required 2×),
  AUROC absolute 0.94 (vs floor 0.70), lead-time +11 steps (vs required
  non-inferiority).
- The Sprint-30 PASS was not an artifact of the narrow March-2025 fit
  flattering the same-season comparison. Pillar A's signal is robust to
  seasonal distribution shift on this site.
- Governance is clean: no leakage, no forbidden edge imports, no
  write-actuation tokens, valid axis taxonomy, valid normalization coverage.

It DOES NOT mean:
- The detector would pass on REAL March-2026 anomalies — those don't exist
  as labels in this dataset; we substituted injected canonical faults on
  real March-normal data. That limitation is recorded verbatim in the
  scorecard's `out_of_sample_protocol.labeled_eval_limitation` field and
  should be carried forward into any downstream packaging or pilot
  decision.
- The detector is approved for site integration: the safety block is still
  `site_integration_allowed = False` and the artifact is advisory-only.
- The fit covers every operating regime. January / February / August /
  September have **zero** auto-mode rows in source1_2025.csv — those
  seasons are uncovered no matter how the cap is set, and an extreme
  August manual-mode signal would still be out-of-distribution for the
  detector.

---

## 11. Final lines (required)

```
SPRINT30B_GATE: PASS
SPRINT30B_STATUS: COMPLETE
```
