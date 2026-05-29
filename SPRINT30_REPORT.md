# AOPSO Sprint 30 — Pillar A locked-March-2026 out-of-sample evaluation (pre-registered v2)

## TL;DR

The Sprint-29 learned health detector + Sprint-28 interpretable baseline suite
were fit on 2025 auto-mode normal data ONLY, then scored on the LOCKED
March-2026 holdout. The Sprint-29b **pre-registered v2 acceptance gate** was
imported as-is from main (no thresholds touched) and applied to the
out-of-sample numbers.

The detector cleared all four v2 clauses (and the absolute-AUROC floor) on
real, never-before-seen March-2026 normal data. Governance also passed clean.

```
SPRINT30_GATE: PASS
SPRINT30_STATUS: COMPLETE
```

Real numbers (one-liner):
- detector AUROC = **0.9299**, baseline AUROC = **0.8781** (Δ = +0.0518)
- detector FAR (injected set) = **0.0245**, baseline FAR = **0.4262** (**17.4× fewer false alarms**)
- raw-March alarm rate (unsupervised, no labels): detector = **2.37 %**, baseline = **42.67 %**
- detector mean lead-time = **6.93 steps**, baseline = **1.48 steps**

The PASS held both on the labelled "synthetic faults on real March normal"
protocol AND on the unsupervised "raw March alarm rate" cross-check. v2 PASS
was not a tuned outcome — the gate was frozen on main before this run and
re-imported, not redefined.

---

## 1. Honesty rules followed

- **Fitting**: detector + baseline + normalization stats fit on **2025
  auto-mode rows ONLY**. Never on March-2026.
  - The Sprint-27 `assert_holdout_isolated` leakage guard runs inside both
    `fit_health_detector` and `fit_health_baseline_suite`; a `2026-03` key in
    fit input raises `LeakageError` BEFORE the fit (tripwire test:
    `tests/advisory/test_sprint30_holdout.py::test_fit_detector_rejects_march_2026_keys`).
- **Pre-registered gate**: this sprint imports
  `aquaoptima.advisory.health_gate.health_acceptance_gate_v2` exactly as it
  exists on `main` after the Sprint-29b merge (commit `52ac365`). No
  thresholds were re-tuned, no clauses were added or removed, no margins were
  loosened. The script records the four clause parameters as artifacts in
  `frozen_gate_v2` and sets `preregistered_before_evaluation: true,
  tuned_to_outcome: false`.
- **Reporting**: a FAIL would have been written as `SPRINT30_GATE: FAIL`. The
  actual model verdict on the locked holdout is **PASS** — this is the real
  outcome, not a forced result.
- **Safety boundary** (unchanged from Sprints 27–29): `evaluation_mode =
  offline_only`, `write_path = none` (scorecard JSON only),
  `influences_control = False`, `site_integration_allowed = False`. No
  `aquaoptima.edge` / `aquaoptima_contracts.edge` imports (verified by the
  governance import-connector scan: clean, 0 violations).

---

## 2. Protocol (and its honest limitation)

March 2026 has **no ground-truth anomaly labels**. AUROC, lead-time, and
false-alarm rate are all label-conditional metrics. We use a two-track
protocol to extract the most honest signal from an unlabelled holdout:

### Track 1 — Labelled metrics on injected faults over real March normal

1. Fit detector + baseline on a 2025 auto-mode subset (28,931 rows after
   filtering, spanning 2025-03-06 → 2025-03-28 in the auto column).
2. **Inject** the Sprint-29 frozen-seed canonical fault families
   (`sensor_drift`, `stuck_flatline`, `spike`, `envelope_violation`) onto the
   **real March-2026 normal frames** (8 episodes per kind, 32 episodes
   total, frozen seed 29).
3. Run `evaluate_detector_vs_baseline` → AUROC, lead-time, false-alarm rate.
4. Apply the **pre-registered v2 acceptance gate** to the eval dict.
5. Compose Sprint-27 governance (`build_governance_block` +
   `apply_governance_to_verdict`).

**Limitation, stated explicitly in the scorecard's
`out_of_sample_protocol.labeled_eval_limitation` field**: the faults
themselves are synthetic, so this measures how the 2025-fit detector
*responds to canonical faults on top of unseen March-2026 normal data*. It
is NOT a measurement of how the detector would score real, in-the-wild
March-2026 faults (none of which are labelled). What it IS testing — and what
matters — is whether the 2025-fit detector generalises to the real out-of-
sample normal distribution. If it didn't, the false-alarm rate would explode
and the gate's C2 clause would fail loudly.

### Track 2 — Unsupervised raw-March alarm rate

No labels needed: just run the detector + baseline on raw, un-faulted
March-2026 frames and record the per-row alarm/flag rate. This is the most
honest single number — the detector's real-world false-positive rate on
genuinely unseen data. It is reported as `raw_march_flag_rates` in the
scorecard and discussed in §4 below.

### Holdout-isolation proof (positive)

The scorecard's `holdout_window` block records:

| field | value |
| --- | --- |
| `csv_path` | `…/yearlong_drive/source1_2026.csv` |
| `first_timestamp` | `2026-03-01 00:00:53` |
| `last_timestamp` | `2026-03-31 23:59:19` |
| `n_rows` | `42,674` (all March 2026 rows after dropna on the 8 active axes) |
| `n_march_rows_total_before_cap` | `42,674` |
| `row_cap_applied` | `false` (the default 50,000 cap was not hit — full March used) |
| `all_in_2026_03` | `true` |

Positive proof: every row falls inside `2026-03`. Negative proof: the
Sprint-27 leakage guards on the fit inputs would have raised `LeakageError`
if any March-2026 key had reached them — and they did not.

The training-set side:
- `train_meta.csv_path`: `source1_2025.csv` (2025-only file, no 2026
  timestamps possible).
- `train_meta.n_rows_after_auto_filter`: `28,931`.
- `train_meta.timestamp_min / timestamp_max`: `2025-03-06 09:59:37 /
  2025-03-28 13:44:23` (entirely 2025).

---

## 3. Real numbers (out of sample, locked March-2026)

### Aggregate

| metric | detector | baseline | delta |
|---|---:|---:|---:|
| AUROC (injected on March-normal) | 0.9299 | 0.8781 | +0.0518 |
| false-alarm rate (injected set) | 0.0245 | 0.4262 | −0.4017 |
| mean lead-time (steps to first alarm post-onset) | 6.93 | 1.48 | +5.45 |
| raw-March flag rate (un-faulted, unsupervised) | 0.0237 | 0.4267 | −0.4030 |

### Injected-set composition

- 42,674 evaluation rows.
- 32 fault episodes (8 each of the four canonical kinds).
- 2,128 positive-label rows (≈ 4.99 % of the eval set).

### Detection per fault kind (detector)

| kind | episodes | detected | misses | mean lead-time (steps) |
|---|---:|---:|---:|---:|
| sensor_drift | 8 | 8 | 0 | 26.0 |
| stuck_flatline | 8 | 6 | 2 | 0.0 |
| spike | 8 | 8 | 0 | 0.0 |
| envelope_violation | 8 | 8 | 0 | 0.0 |
| **total** | **32** | **30** | **2** | **6.93** |

### Detection per fault kind (baseline)

| kind | episodes | detected | misses | mean lead-time (steps) |
|---|---:|---:|---:|---:|
| sensor_drift | 8 | 8 | 0 | 5.875 |
| stuck_flatline | 8 | 8 | 0 | 0.0 |
| spike | 8 | 8 | 0 | 0.0 |
| envelope_violation | 8 | 7 | 1 | 0.0 |
| **total** | **32** | **31** | **1** | **1.48** |

Read: the baseline gives slightly broader coverage (31/32 vs 30/32 — it
detects two `stuck_flatline` episodes the detector missed). But the detector
- buys back a 4.7× larger mean lead-time on drift-style faults (it surfaces
  sensor_drift on average 26 steps earlier than the baseline's 5.9), AND
- runs at ~17× lower false-alarm rate.

That trade — slightly fewer late catches in exchange for a far quieter and
earlier-firing monitor — is the alarm-fatigue trade the v2 gate was
designed to credit.

### Raw-March (un-faulted, unsupervised)

| | detector | baseline |
|---|---:|---:|
| flag rate (per row) | **2.37 %** | **42.67 %** |
| mean score / deviation | 0.066 | 0.504 |

On real, unseen, un-faulted March operating data the detector cries wolf on
2.37 % of rows; the baseline cries wolf on 42.67 % of rows. A monitor that
flags 4 out of 10 normal rows in production would be ignored or
silenced within a week — the detector's 2.4 % rate is in operationally
useable territory.

---

## 4. Pre-registered gate v2 — clause-by-clause result

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
| C1 — AUROC non-inferior | tol = 0.01 | 0.9299 | ≥ 0.8781 − 0.01 = 0.8681 | **PASS** |
| C2 — FAR materially better | ≥ 2× improvement | 0.0245 | ≤ 0.4262 / 2 = 0.2131 | **PASS** (actual factor 17.4×) |
| C3 — AUROC absolute floor | min = 0.70 | 0.9299 | ≥ 0.70 | **PASS** |
| C4 — lead-time non-inferior | tol = 1 step | 6.93 | ≥ 1.48 − 1.0 = 0.48 | **PASS** |

All four clauses PASS. Composed with Sprint-27 governance
(`governance_status: PASS`) → final **verdict: PASS**.

```
SPRINT30_GATE: PASS
```

---

## 5. Governance result (Sprint-27 guardrails)

`safety.governance` block:

| guard | result |
| --- | :--- |
| holdout-isolation (split manifest train/val keys vs `2026-03` window) | **PASS** (0 leaked keys, 379 train/val keys checked) |
| import / connector scan (`src/aquaoptima/{advisory,training,models,dataio}`) | **PASS** (0 violations across 23 files scanned, 0 `aquaoptima.edge` imports, 0 write-actuation tokens) |
| axis taxonomy (8 expected active axes, all backed, masked axis maps to None) | **PASS** |
| normalization coverage (8 axes × finite μ / σ > 0) | **PASS** |

`governance_status: PASS` → no override applied to the model verdict.

---

## 6. Verification gate (Sprint-30 IMPLEMENTATION pass)

| step | command | result |
| --- | --- | --- |
| 1 | `python -m pytest tests/advisory -q` | **117 passed** in 8.6 s |
| 2 | `python -m pytest tests -q` | **2537 passed, 1 skipped** in 2 m 21 s (no regressions) |
| 3 | `python scripts/sprint30_holdout_eval.py` | wrote `data/eval/pillarA/sprint30_holdout_scorecard.json` with `verdict: PASS` |

```
SPRINT30_STATUS: COMPLETE
```

The five new tests (`tests/advisory/test_sprint30_holdout.py`):

1. backing→canonical rename maps the 8 active axes.
2. partial-column rename: only present backing columns are renamed; absent
   canonical axes stay absent (no fabrication).
3. end-to-end eval pipeline on a tiny synthetic March-shaped frame yields a
   real `gate_version: 'v2'` verdict dict — shape is asserted, but PASS/FAIL
   is deliberately NOT asserted on a synthetic fixture.
4. leakage tripwire: feeding a `2026-03` key into `fit_health_detector`
   raises `LeakageError` before any fit work happens.
5. governance FAIL → forced verdict FAIL → `governance_guardrails` criterion
   appended.

---

## 7. Files changed / written

- `scripts/sprint30_holdout_eval.py` (new) — fit-on-2025 / score-on-March
  / v2-gate / governance / raw-March cross-check, with a `--march-nrows`
  cap and `SPRINT30_FULL=1` env to keep every March row (the default 50 000
  cap was not hit on the real run — the full 42 674 March rows were used).
- `tests/advisory/test_sprint30_holdout.py` (new) — 5 deterministic
  fixture-based tests; no full-CSV reads.
- `data/eval/pillarA/sprint30_holdout_scorecard.json` (new) — the real
  out-of-sample scorecard with verdict, all metrics, holdout-isolation
  proof, governance block, and the safety boundary.
- `SPRINT30_REPORT.md` (this file).

Unchanged: `aquaoptima_contracts/**`, `src/aquaoptima/advisory/health_gate.py`
(gate v2 imported unmodified), all other modeling source. Pre-registration
integrity preserved.

---

## 8. What this PASS does and does not mean

It DOES mean:
- The Sprint-29 detector + Sprint-28 baseline, fit on 2025 only, generalise
  to the genuinely unseen March-2026 normal distribution: the raw-March
  alarm rate is 2.4 % (detector) and 42.7 % (baseline).
- Against canonical injected faults on top of that real March-normal
  signal, the detector cleared the pre-registered v2 bar on every clause:
  non-inferior AUROC, ≥ 2× false-alarm reduction (actual 17×), absolute
  AUROC floor, and non-inferior lead-time.
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

---

## 9. Final lines (required)

```
SPRINT30_GATE: PASS
SPRINT30_STATUS: COMPLETE
```
