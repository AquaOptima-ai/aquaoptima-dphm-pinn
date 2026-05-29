# AOPSO Sprint 29 — Pillar A learned detector + injected-fault harness + frozen health gate

Branch: `aopso/sprint29-pillarA-detector`
Worktree: `/home/hunter_lin/projects/aopso-sprint29-impl`

> NOTE: this file replaces a previous, unrelated EPANET water-quality
> diagnostics report that lived at this path before the AOPSO A+B pivot. The
> active Sprint-29 work is the Pillar A learned health detector documented
> below.

## Sprint goal

Ship the **learned** Pillar A health detector that the Sprint 28 interpretable
baselines (EWMA/SPC + Mahalanobis + physical residual) had pre-registered as
the bar to clear, evaluate it honestly on a FROZEN-seed injected-fault test
set, and decide PASS/FAIL against a pre-registered rule.

This is the first sprint in the A+B pivot where a LEARNED model is asked to
beat a statistical baseline. The prior forecasting objective FAILed exactly
this kind of gate twice (Sprint 25: 0/6 vs persistence; Sprint 26: 0/8 vs
persistence). A FAIL verdict on the model gate is an ACCEPTABLE, VALUABLE
outcome — and is what the script reports below.

## Hard safety boundary (unchanged)
- `evaluation_mode = offline_only`, `write_path = none`,
  `influences_control = False`, `site_integration_allowed = False`.
- No `aquaoptima.edge` / `aquaoptima_contracts.edge` imports. Contracts SDK
  read-only.
- March 2026 (`2026-03`) is a LOCKED holdout. The Sprint-27 leakage guard
  (`advisory.governance.assert_holdout_isolated`) runs before every detector
  fit; March-2026 keys raise `LeakageError` and the report script exits
  non-zero (exit code 2).
- Training data: 2025 auto-mode rows only (the first 30 000 auto-mode rows of
  `source1_2025.csv`, split 50/50 into a fitting frame and the eval pool
  before any fault injection).
- The injected-fault harness operates only on holdout-of-training 2025 rows.
  March 2026 is NEVER touched.

## Files added

| Path | Purpose |
|------|---------|
| `src/aquaoptima/advisory/health_detector.py` | Small CPU MLP autoencoder (`HealthAutoencoder`), deterministic `fit_health_detector`, frozen `FittedHealthDetector` with `.score()` returning `detector_anomaly_score` and `detector_flag`. Standardises inputs with the frozen 2025 stats when available; falls back to input-frame statistics for tests. Sprint-27 leakage guard runs before every fit. |
| `src/aquaoptima/advisory/injected_faults.py` | FROZEN-seed injected-fault harness producing the four documented families (`sensor_drift`, `stuck_flatline`, `spike`, `envelope_violation`), per-row labels, and per-episode onsets. |
| `src/aquaoptima/advisory/health_gate.py` | `evaluate_detector_vs_baseline` (AUROC + lead-time + false-alarm for BOTH detector and baseline) and `health_acceptance_gate` (FROZEN pre-registered rule). Composes with `apply_governance_to_verdict` from Sprint 27. |
| `tests/advisory/test_health_detector.py` | 14 detector tests: determinism, seed sensitivity, leakage guard, normalisation priority, scoring columns. |
| `tests/advisory/test_injected_faults.py` | 16 harness tests: labels/onsets alignment, all four fault families present, determinism, read-only on input, spike-detectability invariant. |
| `tests/advisory/test_health_gate.py` | 12 gate tests: PASS / FAIL by each of the three rule clauses, governance override, AUROC helper edge cases. |
| `scripts/sprint29_detector_eval.py` | Subset-capable CLI: fits both detector + baseline on 2025, builds the FROZEN-seed injected-fault set, evaluates, applies governance, writes the scorecard JSON. |
| `data/eval/pillarA/sprint29_detector_scorecard.json` | The Sprint 29 scorecard: detector vs baseline AUROC / lead-time / false-alarm, verdict, gate rule, safety + governance block. |

No edits to `aquaoptima.edge`, `aquaoptima_contracts`, packaging, or any
existing Sprint 27 / 28 module.

## Detector architecture

Small symmetric MLP autoencoder over the standardised active-axis vector, CPU
only:

```
input (n_axes=8) --Linear--> 16 --Tanh--> Linear --> 8 (latent) --Tanh
                                                                     \
        Linear <-- 16 <--Tanh-- Linear <-- 8 (latent)                /
        |
        v
output (n_axes=8)
```

Activations: `Tanh` everywhere. Per-axis standardisation uses the frozen
`data/normalization/yilan_2025_train_stats.json` mu/sigma when present (the
production path); tests fall back to input-frame statistics. Deterministic
parameter init is sampled from a local `torch.Generator` so the init does
not depend on global torch state.

Training: Adam (lr 1e-3, weight decay 1e-5), MSE reconstruction loss, seeded
mini-batch order from `np.random.default_rng(seed)`, 40 epochs at batch
size 256 on the Yilan subset. Held-in normal val split (20%) is used to
calibrate the reconstruction-error 99.5 percentile (for the [0,1] anomaly
score) and the 99-percentile flag threshold.

Per-row scoring outputs:

- `detector_recon_error`: per-row MSE over the standardised axes.
- `detector_anomaly_score`: `clip(err / val_error_p995, 0, 1)` — the
  comparable [0,1] score used for AUROC against the baseline's
  `combined_deviation`.
- `detector_flag`: 1 iff `err >= flag_threshold_error` (val 99-percentile).

## Injected-fault harness (FROZEN seed)

`inject_faults(normal_frames, seed=29, …)` operates on a copy of the input
frame and returns a faulted frame plus per-row 0/1 labels and per-episode
`(kind, axis, onset_index, end_index)` records.

Four fault families (all knobs FROZEN; no tuning against the detector):

| Kind | Default knobs | Mechanism |
|------|---------------|-----------|
| `sensor_drift` | 4 episodes, window=120 rows, end magnitude = 4·σ_axis | Linear ramp `0 → 4σ` added to one randomly-chosen axis over the window. Models slow sensor or pump-degradation drift. |
| `stuck_flatline` | 4 episodes, window=80 rows | Window replaced with the pre-onset axis mean. Models a frozen sensor or stuck-output failure. |
| `spike` | 4 episodes, single step + 5-row decaying tail, magnitude = 6·σ_axis | Multi-sigma additive spike with exponential decay tail. Models transient instrumentation glitches. |
| `envelope_violation` | 4 episodes, window=60 rows, magnitude = 4·σ_power | `edge_power` is pushed by ±4σ while `edge_flow` and `edge_pump_speed` remain coherent. Models a multivariate break of the physical relationship that the Sprint 28 residual model expects. |

All onsets, lengths, axis selections, and signs are sampled from a single
seeded `np.random.default_rng(29)`. Same seed + same input ⇒ bit-identical
output. Episodes never overlap; minimum gap is 5 rows so labels do not
contaminate one another.

## Frozen acceptance rule (pre-registered before evaluation)

```
detector_auroc >= baseline_auroc + 0.02
AND detector_false_alarm_rate <= baseline_false_alarm_rate
AND detector_auroc >= 0.70
```

Each clause is evaluated as its own named criterion (the same shape as the
existing scorecard acceptance gate) so the failure mode is explicit in the
artifact. Defaults are fixed module-level constants
(`FROZEN_AUROC_MARGIN = 0.02`, `FROZEN_DETECTOR_MIN_AUROC = 0.70`). On
governance FAIL, `apply_governance_to_verdict` forces the gate verdict to
FAIL regardless of metrics (the Sprint-27 contract). The rule is NOT adjusted
based on the empirical outcome.

## REAL evaluation numbers (subset run: 30 000 auto-mode 2025 rows)

| Metric | Detector | Baseline | Delta |
|---|---|---|---|
| AUROC on injected faults | **0.8158** | **0.8072** | **+0.0085** |
| False-alarm rate (normal rows) | **0.76 %** | **16.18 %** | **−15.42 pp** |
| Mean detection lead-time (steps) | **9.56** | **6.76** | +2.80 |
| Episodes detected | 27 / 32 | 29 / 32 | −2 |

Per-kind detection lead time (detector / baseline):

| Kind | Detector mean | Baseline mean | Detector misses |
|---|---|---|---|
| sensor_drift | 29.13 | 19.00 | 1 |
| stuck_flatline | 8.33 | 8.80 | 2 |
| spike | 0.00 | 0.00 | 0 |
| envelope_violation | 0.00 | 0.00 | 2 |

Frozen gate clauses:

| Clause | Required | Observed | Passed |
|---|---|---|---|
| R1: detector AUROC beats baseline by ≥ 0.02 | Δ ≥ 0.02 | Δ = 0.0085 | **FAIL** |
| R2: detector false-alarm rate ≤ baseline | 0.0076 ≤ 0.1618 | true | PASS |
| R3: detector AUROC ≥ 0.70 | 0.8158 ≥ 0.70 | true | PASS |

Governance (`safety.governance_status`): **PASS**. The four Sprint-27
guards (holdout isolation, modeling-source import/connector scan, axis
taxonomy, normalisation coverage) are all green.

### Honest interpretation

The learned autoencoder matches the interpretable baseline's separating
power (Δ AUROC ≈ +0.0085) but does NOT clear the pre-registered margin of
+0.02. It does, however, deliver a dramatically lower false-alarm rate on
normal rows (0.76 % vs the EWMA chart's ~16 %), and it detects sensor drifts
earlier (mean lead-time 29 vs 19 steps). The reverse pattern is that the
EWMA chart catches two more episodes overall and is competitive on
stuck-flatline lead-time.

That is exactly the *kind* of evidence that justifies a FAIL verdict on the
frozen rule: the detector is meaningfully better in some dimensions but
fails the clause we pre-registered as the gating one. We are NOT relaxing
the rule. The detector goes back for iteration; the rule stays.

```
SPRINT29_GATE: FAIL
```

## Verification gate (Sprint 29 *implementation* gate — distinct from model gate)

1. `python -m pytest tests/advisory -q`
   ```
   103 passed in 5.66s
   ```

2. `python -m pytest tests -q`
   ```
   2523 passed, 1 skipped, 3 warnings in 143.71s (0:02:23)
   ```

3. `python scripts/sprint29_detector_eval.py --subset 30000 --epochs 40 --episodes-per-kind 8`
   ```
   [sprint29] wrote data/eval/pillarA/sprint29_detector_scorecard.json
   [sprint29] detector_auroc=0.8158 baseline_auroc=0.8072 verdict=FAIL
   ```
   Exits 0 (a model-gate FAIL is a valid run — only true errors, leakage, or
   missing data cause non-zero exits).

```
SPRINT29_STATUS: COMPLETE
SPRINT29_GATE: FAIL
```

`STATUS=COMPLETE` means the code, tests, and report ship cleanly per the
verification gate above. `GATE=FAIL` reflects the honest empirical verdict
under the pre-registered rule. The two are intentionally separate.

## Test coverage (subset / fixture only)

| File | Tests | Highlights |
|------|-------|-----------|
| `test_health_detector.py` | 14 | Same-seed → bit-identical state-dict and scores; different seed → different scores; March-2026 key → `LeakageError`; explicit norm-stats and JSON-path priority over input-frame fallback; missing-axis raise on score; summary dict is JSON-safe. |
| `test_injected_faults.py` | 16 | Labels alignment to episode windows; all four fault families present; episodes never overlap; spike alters target axis at the onset index (≥ 3σ deviation invariant); stuck window is constant; envelope_violation only edits `edge_power`; harness is read-only on the input frame; empty/missing-axes input raises. |
| `test_health_gate.py` | 12 | PASS on a synthetic eval where detector clearly beats baseline; explicit FAIL on each of the three rule clauses (margin, FAR, absolute minimum); governance FAIL forces verdict FAIL even on passing metrics; end-to-end pipeline runs and produces a verdict in `{PASS, FAIL}`; AUROC helper returns 0.5 on all-positive / all-negative labels (no fabricated pass). |

Subset-only / fixture-based throughout. No test loads the full ~489 000-row
CSV. No test asserts a specific real-data outcome of the model gate.

## What this sprint did NOT do

* It did NOT train or score against any March-2026 data.
* It did NOT tune the detector hyperparameters against the injected-fault
  set after seeing the AUROC numbers.
* It did NOT relax the pre-registered acceptance rule.
* It did NOT package, sign, or write an artifact contract.
* It did NOT add any edge / OT / write-capable connector.

## Recommended next-sprint focus (Sprint 30)

The honest verdict here is "the autoencoder ties the baseline on AUROC and
beats it on false-alarm". Two reasonable directions for Sprint 30:

1. **Architecture / capacity**: a temporally-aware encoder (small TCN /
   1-D conv over a short window, or a multi-step reconstruction target)
   would give the detector access to the autocorrelation structure that
   the EWMA chart is implicitly exploiting. The current per-row MLP throws
   that away.

2. **Loss / calibration**: train with a Mahalanobis-aware reconstruction
   loss (whiten the residual against the train covariance) so the detector
   does not waste capacity on the per-axis variance that the EWMA term
   already covers; calibrate the flag threshold against the baseline's
   false-alarm rate target so the gate's R2 clause has explicit headroom.

Both are clean improvements that respect the FROZEN rule unchanged. Whichever
is chosen, the empirical gate stays at AUROC + 0.02 / FAR ≤ baseline / AUROC
≥ 0.70 — those numbers were pre-registered before Sprint 29's run and remain
pre-registered for the next attempt.
