# AOPSO Sprint 25 — Offline Evaluation Methodology & Acceptance Thresholds

**Component:** Core training/evaluation (offline). **Safety:** offline scoring
only; advisory scorecards; no edge runtime, no ONNX, no OT/PLC/SCADA, no
actuation, no control-loop closure. The March 2026 benchmark and any 2026 data
are **read-only**.

---

## 1. Goal

Score the trained dPHM checkpoint (`model_best.pt`) against the **LOCKED March
2026 benchmark** and decide, via a machine-checkable PASS/FAIL gate, whether the
model is "good enough to package" in Sprint 26. The scorecard is shaped to the
shared `ShadowRuntimeReport` contract (consumed, never forked) so downstream
consumers (Operations Console, audit harnesses) can read it directly.

The harness reports **whatever the model actually scores**. There are no
illustrative or hardcoded metric values anywhere in the code. A **FAIL is a
valid, valuable outcome**: it means *do not package; iterate on Sprint 24
training*.

---

## 2. The March 2026 benchmark (holdout)

- Source: `$YILAN_2026_CSV` (default
  `/home/hunter_lin/projects/yilan-site-model-testing/yearlong_drive/source1_2026.csv`),
  **same schema** as `source1_2025.csv`. Overridable via the `--march-csv` CLI
  flag.
- The harness reads that CSV, parses the `timestamp` column
  (`%Y-%m-%d_%H:%M:%S`), and **filters to calendar month March (year 2026,
  month 3)**.
- **Actual March 2026 row count: 44,469 rows** (calendar window
  `2026-03-01 00:00:53 .. 2026-03-31 23:59:19`). This is the real number; the
  roadmap's "≈30k rows" was a guess and is *not* used anywhere.
- The same canonical axis map (`yilan_axis_map.CANONICAL_AXIS_TO_COLUMN`) and the
  **training** normalization stats (`yilan_2025_train_stats.json`, computed on
  the 2025 train split only) are applied. 2026 data never fits normalization or
  the model.
- Windowing is identical to training: gap-aware sliding windows
  (`window`/`horizon`/`stride` from `configs/yilan_dphm_v1.yaml`; gaps > 5 min
  break a window), z-scored per active axis.

### Axes scored

| Group | Axes | Metric |
|-------|------|--------|
| Continuous (6) | `edge_flow`, `edge_power`, `edge_pump_speed`, `node_demand`, `node_level`, `node_pressure` | normalized **MSE** + **MAE** |
| Binary (2) | `node_status`, `edge_status` | **accuracy** (de-normalize → threshold at 0.5 → compare 0/1 class) |
| Masked (1) | `edge_valve_position` | **N/A** — no backing telemetry column at the Yilan site (0% coverage) |

All metrics are computed on the **normalized** scale (the scale the model is
trained on), which is why the MSE/MAE thresholds are unitless and comparable
across axes.

---

## 3. Holdout isolation (leakage guard)

Before scoring, `assert_holdout_isolated()` re-checks the split manifest and
**hard-STOPs** if the March 2026 window (2026-03) intersects any `train` or
`val` split day or date-range bound. The committed manifest's train/val days are
all 2025 dates and the holdout is reference-only (`row_count: 0`,
`2026-03-01..2026-03-31`), so the check passes; any future split edit that
leaked a 2026-03 day would abort evaluation with a `ValueError`. The 2026 CSV is
opened read-only and never written.

---

## 4. MVP v1 baseline

The incumbent "MVP v1" behaviour is modelled as a **persistence /
last-observed-value** predictor: the next-step prediction is the last value of
the input window (`baseline_mvp.persistence_predict`). It is scored on the
**identical** holdout windows (same windowing, normalization, axis order), so the
dPHM-vs-baseline comparison is apples-to-apples. The dPHM model must beat this
naive baseline to justify packaging.

---

## 5. Acceptance gate ("good enough to package")

Thresholds are encoded in `configs/yilan_dphm_v1.yaml` (`eval:` block) and in
`acceptance.AcceptanceThresholds` (defaults below). The gate
(`acceptance.evaluate_gate`) returns PASS/FAIL with per-criterion detail.

| # | Criterion | Bar |
|---|-----------|-----|
| 1 | Continuous-axis normalized **MSE** | `<= 0.15` for **every** active continuous axis |
| 2 | Continuous-axis normalized **MAE** | `<= 0.30` for **every** active continuous axis |
| 3 | Binary-axis **accuracy** | `>= 0.95` for `node_status` AND `edge_status` |
| 4 | **Beats baseline** (lower MSE) | on `>= 5` of the 6 continuous axes |

**Gate = PASS iff all four criteria pass.** Boundaries are inclusive
(`<=` / `>=`). If no baseline metrics are supplied, criterion 4 fails (packaging
cannot be justified without a baseline comparison).

### Thresholds rationale

- **MSE ≤ 0.15 (normalized):** a normalized MSE of 0.15 corresponds to a
  per-axis RMSE of ≈0.39 σ — materially better than a unit-variance naive guess
  (MSE ≈ 1.0) and tight enough that residual-based advisories are meaningful.
- **MAE ≤ 0.30 (normalized):** a complementary, outlier-robust bar (≈0.30 σ mean
  absolute error). Pairing MSE *and* MAE rejects models that look good on
  average squared error but have heavy-tailed misses.
- **Binary accuracy ≥ 0.95:** status axes are near-constant (mostly "on") in the
  Yilan data; the model must clear a high bar to add value over trivially
  predicting the majority class.
- **Beats baseline on ≥ 5/6 axes:** allows one axis where persistence is hard to
  beat (e.g. a very smooth, slowly-varying signal) while still requiring a clear,
  broad improvement over the incumbent.

These are the **packaging bar**, not observed results. They are deliberately
strict; a model that fails should be iterated on, not shipped.

---

## 6. Output: contract-shaped scorecard

`evaluation.evaluate()` assembles a scorecard dict written to
`data/eval/yilan_dphm_v1/march2026_scorecard.json`. It contains:

- the per-axis dPHM metrics, baseline metrics, and per-axis dPHM-vs-baseline
  deltas;
- the acceptance-gate verdict and per-criterion detail;
- the **`shadow_report`** payload, which is built via the real
  `ShadowRuntimeReport`/`ShadowRuntimeStepReport` contract classes and
  **round-trip-validated** (`ShadowRuntimeReport.from_dict`). If the payload
  fails contract validation, the harness **STOPs** (the scorecard must not
  ship). Continuous-axis MSE/MAE populate the contract step's `mse_by_axis` /
  `mae_by_axis`; binary accuracy is reported alongside (advisory) and not forced
  into the contract.
- the real March-2026 **row count and window count actually scored** and the
  holdout date range.

The harness process exit code mirrors the gate (`0` = PASS, `1` = FAIL) so CI
can branch on packaging readiness.

---

## 7. Advisory-only / packaging gate statement

**Scorecards produced by this harness are advisory evidence only.** They are
consumed by humans (and CI) to *decide* whether to package a model. They never
drive actuation, never close a control loop, and never bind to any live runtime
— producing a `ShadowRuntimeReport`-shaped object here is purely a serialization
choice.

**A FAIL verdict blocks Sprint 26 packaging.** No model ships to edge without a
PASS against the LOCKED March 2026 benchmark. On FAIL, the correct action is to
return to Sprint 24 and iterate training (features, capacity, epochs), then
re-score — not to relax the gate or hand-edit numbers.

---

## 8. STOP conditions

The harness halts (raises) rather than producing a misleading scorecard if:

- the March 2026 holdout window intersects any train/val split (data leakage);
- the scorecard payload fails `ShadowRuntimeReport` contract validation;
- March 2026 data cannot be loaded (0 rows after the month filter) or yields 0
  scorable windows;
- (build-time) any edge import or ONNX export is introduced — forbidden in this
  sprint.
