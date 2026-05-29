# AOPSO Sprint 28 — Pillar A interpretable health baselines

Branch: `aopso/sprint28-pillarA-baselines`
Pivot: A+B advisory (Health + Efficiency) — Sprint 28 ships Pillar A FOUNDATION.

This sprint BUILDS the bar that the Sprint 29 learned detector must clear. Nothing
here is learned; the three baselines are transparent, fit/score-separated, pure
statistical methods on 2025 auto-mode normal operation.

> NOTE: this file supersedes an earlier, unrelated EPANET `[EMITTERS]`/`[DEMANDS]`
> diagnostics report that lived at this path before the A+B pivot. The Sprint-28
> work below is the active AOPSO Pillar A foundation.

## Hard boundary (unchanged)
- `evaluation_mode = offline_only`, `write_path = none`,
  `influences_control = False`, `site_integration_allowed = False`.
- No `aquaoptima.edge` / `aquaoptima_contracts.edge` imports. Contracts SDK
  read-only. Governance scan green on the advisory package.
- March 2026 (`2026-03`) is a LOCKED holdout. The Sprint-27 leakage guard
  (`advisory.governance.assert_holdout_isolated`) is invoked before every fit
  in `health_baselines`; March-2026 keys raise `LeakageError` and the report
  script exits non-zero (exit code 2).

## Files added
| Path | Purpose |
|------|---------|
| `src/aquaoptima/advisory/health_baselines.py` | EWMA/SPC, Mahalanobis, physical-residual baselines + `HealthBaselineSuite`. Pure pandas/numpy. |
| `tests/advisory/test_health_baselines.py` | 22 subset/fixture tests covering all three baselines, the suite, determinism, and the leakage guard. |
| `scripts/sprint28_baseline_report.py` | Subset-capable report generator. Exits 2 on leakage; emits the JSON below. |
| `data/eval/pillarA/sprint28_baseline_report.json` | Per-axis SPC limits, Mahalanobis covariance summary, combined-score distribution, false-alarm summary. |

No edge imports, no packaging changes, no neural-net training.

## The three baselines

### 1. EWMA / SPC control chart (`fit_ewma_spc` → `EwmaSpcModel`)
Per continuous active axis we store the in-control mean ``μ``, sample std ``σ``,
the asymptotic EWMA-statistic std ``σ_z = σ · √(λ/(2−λ))`` (λ=0.2 default), and
3-sigma control limits ``μ ± L·σ_z`` (L=3). Scoring recomputes the causal EWMA
``z_t = λ·x_t + (1−λ)·z_{t-1}`` seeded at ``μ`` and emits, per row and per axis,
the EWMA value, an out-of-control flag, and the per-axis |z-score|. A combined
``spc_fraction_axes_out`` summarises the row.

### 2. Multivariate Mahalanobis distance (`fit_mahalanobis` → `MahalanobisModel`)
Standardises the active-axis vector with input ``μ``/``σ``, computes the sample
covariance, ridge-regularises (``Σ + ε(tr(Σ)/k + 1)·I``, ε=1e-6) so the matrix
is reliably invertible at small N, and calibrates the train-time 99.5-percentile
of the Mahalanobis distance as the in-control envelope. Scoring returns both
the raw distance and a [0,1] normalised score (1.0 = at or above calibration).

### 3. Residual vs. physical expectation (`residual_vs_physical` → `PhysicalResidualModel`)
Fits a closed-form OLS for ``edge_power ~ α + β_flow · edge_flow + β_speed ·
edge_pump_speed`` — the documented affinity-law-style linear proxy. Computes
R² and residual σ. If features are missing or R² falls below ``min_r2`` (0.30
default) the model is returned with ``high_confidence=False`` and ``score()``
emits zeros across all rows; we deliberately refuse to fabricate a physical
signal we don't trust. On the real Yilan 2025 auto-mode subset the fit is
strong: **R² = 0.933** → high-confidence path active.

### Suite — combined per-row health score and anomaly flag
``HealthBaselineSuite`` combines the three normalised component scores into a
per-row deviation in [0, 1] (mean of the components used; the residual term is
dropped when ``low_confidence``), and emits

  - ``health_score = 1 − combined_deviation`` in [0, 1] (higher = healthier),
  - ``anomaly_flag = (health_score < health_threshold)`` (threshold 0.5),
  - the three component norm scores for interpretability,
  - ``components_used`` (2 or 3) for downstream audit.

A ``false_alarm_summary(frames)`` reports the alarm-rate behaviour on the input
data — that is the Sprint-28 gate artifact.

## Held-in normal-data false-alarm behaviour (Sprint 28 gate artifact)

Source data: real 2025 Yilan CSV, **28,931 auto-mode rows** (subset cap
30k specified to the report script; the auto-mode prefix in the source yields
≈29k rows after dropping NaN axes). Axes used: all 8 active continuous axes
from the canonical taxonomy (`edge_flow`, `edge_power`, `edge_pump_speed`,
`edge_status`, `node_demand`, `node_level`, `node_pressure`, `node_status`).

| Metric | Value | Notes |
|---|---|---|
| Combined anomaly-flag rate | **15.69%** | Health < 0.5 threshold |
| EWMA/SPC any-axis-out rate | **67.47%** | EWMA-statistic 3-σ limits are tight relative to real pump-station autocorrelation/drift |
| Mahalanobis alarm rate | **0.50%** | Calibrated by construction (99.5-pct envelope on train) |
| Physical-residual R² | **0.933** | High-confidence; residual term contributes |
| Health-score mean | **0.677** | |
| Health-score p05 | **0.404** | |

These numbers are reproducible: re-running the report script on the same CSV
yields a bit-identical JSON (no RNG; all statistics deterministic).

**Interpretation.** The EWMA 3-σ chart is the tightest of the three baselines on
this site's autocorrelated telemetry, and produces the high any-axis-out rate —
exactly the kind of behaviour the Sprint-29 learned detector needs to improve
on (raise detection on injected faults while staying at or below this
characteristic false-alarm rate). Mahalanobis sits at its calibration target
(~0.5%) by design. The physical residual contributes the third leg only when
the fit clears 0.30 R²; here it does.

## Tests

`tests/advisory/test_health_baselines.py` — 22 new tests covering:

- EWMA/SPC: low false-alarm rate on a pure-normal synthetic frame; an injected
  large step deviation is flagged in ≥ 90% of post-step rows; rejects
  out-of-range λ.
- Mahalanobis: invertible covariance; an out-of-envelope point scores high
  (norm = 1.0) and at or above the train calibration distance; an in-envelope
  point scores near zero; refuses to fit on too few rows.
- Residual: high-confidence path on a strong synthetic linear relationship;
  flags a 20-σ deviation; drops to low-confidence (zero score) when features
  are missing or the relationship is pure noise.
- Determinism: identical seed/data → bit-identical fitted params and scored
  DataFrames for both individual models and the suite.
- Leakage guard: every fit entry point (`fit_ewma_spc`, `fit_mahalanobis`,
  `residual_vs_physical`, `fit_health_baseline_suite`) raises `LeakageError`
  on input containing a `2026-03` key (timestamp column AND index fallback).
- Suite: score columns and health-range invariants; held-in normal false-alarm
  summary stays low on the synthetic fixture; ``to_summary_dict`` is JSON-safe.

### Verification gate results
- `python -m pytest tests/advisory -q` → **43 passed** in 0.51s (21 prior
  Sprint-27 conformance/governance tests + 22 new Sprint-28 baseline tests).
- `python -m pytest tests -q` → **2463 passed, 1 skipped** in 134s
  (Sprint-26/27 regressions absent; the only skip is the unconditional WNTR
  optional-import skip, unchanged from main).
- Report script reproducibility verified: two consecutive runs produce
  identical false-alarm rates (15.6891%, byte-identical JSON).

## What is NOT in this sprint (by design)
- The learned detector (TCN reconstruction / autoencoder) — that is Sprint 29.
- A "beat the baseline" claim — Sprint 28 only BUILDS the bar.
- Any packaging, ONNX export, or contracts artifact wrap — Sprint 30+.
- Any read/write/actuation against the OT side. (None imported, none invoked.)

SPRINT28_STATUS: COMPLETE
