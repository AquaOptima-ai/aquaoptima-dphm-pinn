# AOPSO PyTorch dPHM Training & Edge-Packaging Sprint Roadmap (Sprints 23–27)

> **Project:** Pump Station Optimizer Lite (Plane: AOPSO). Continues from Sprint 22.
> **Codebase references** (read-only) from `aquaoptima-dphm-pinn` contracts SDK; all AOPSO planning, sprints, and code live in the AOPSO repo.
> **Safety flags (every sprint):** `evaluation_mode=offline_only`, `write_path=none`, `influences_control=false`, `site_integration_allowed=false`.

  **Product:** AquaOptima dPHM-PINN (aquaoptima-dphm-pinn, main @ 9453b9f)
  **Site:** Yilan 溪南系統 (P_1531A-D)
  **Mode:** Shadow/advisory only (read-only sidecar, NO control-loop
  closure)
  **Framework Decision:** PyTorch (training) → **ONNX export (edge artifact,
  Option A — DEFAULT)**
  **Architecture:** 3+1 placement enforced per-sprint
  **Planning Sprint:** Current (documentation only, no production code
  changes)

  ---

  ## Executive Summary: Option A Selected (PyTorch → ONNX Export)

  **DECISION:** Default to **Option A** — train in PyTorch, export to ONNX
  for edge deployment.

  **Justification:**
  1. **Zero edge-profile change risk:** AMAX-8580 CPU profile already
  advertises ONNX; validate_deployment_package_for_edge accepts immediately.
  2. **Hardware-agnostic safety:** ONNX CPU runtime (onnxruntime) is
  deterministic, well-tested, no CUDA/libtorch dependency surprises.
  3. **Operational maturity:** Existing edge validator contract
  (`src/aquaoptima_contracts/edge/package_validator.py`) requires no
  extension; `framework='onnx'` passes validation unchanged.
  4. **Parity verification path:** torch→ONNX export adds one-time numerical
  parity check (max abs diff < 1e-4 on holdout sample); if parity fails,
  block packaging.

  **Option B (native PyTorch/TorchScript edge artifact) deferred to Backlog
  EPIC** pending:
  - Edge-profile schema extension to advertise `'pytorch'` in
  `supported_model_frameworks`.
  - Libtorch CPU runtime integration + determinism audit on AMAX-8580
  hardware.
  - Safety review of non-ONNX artifact path with Operational Console team.

  **Roadmap Impact:** Sprint 26 focuses on torch→ONNX export pipeline +
  parity gate. Sprint 27 (Backlog) addresses manual-mode robustness. a future backlog sprint
  (Backlog EPIC) reserves Option B investigation.

  ---

  ## Sprint Sequencing & Status Recommendation

  | Sprint | Goal | Status | Dependency |
  |--------|------|--------|------------|
  | **Sprint 23** | Data profiling + mode-stratified dataset builder |
  **RECOMMENDED: Planned** | None (starts immediately) |
  | Sprint 24 | PyTorch dPHM model + training loop | Backlog | Sprint 23
  acceptance |
  | Sprint 25 | Offline evaluation harness vs March 2026 benchmark | Backlog
  | Sprint 24 acceptance |
  | Sprint 26 | PyTorch→ONNX packaging + edge validator integration | Backlog
  | Sprint 25 acceptance |
  | Sprint 27 | Manual-mode robustness evaluation (extended slice) | Backlog
  | Sprint 26 acceptance |
  | Sprint 6 (EPIC) | Option B investigation: native PyTorch edge runtime |
  Backlog/Candidate | Product roadmap prioritization |

  **RECOMMENDATION:** Mark **Sprint 23 only** as Planned. Gate each
  subsequent sprint on prior acceptance + artifact verification.

  ---

  ## Sprint 23: Data Profiling & Mode-Stratified Dataset Builder

  ### Goal & User Value
  Produce reproducible profiling artifacts (operating-mode coverage,
  per-axis quality, temporal gaps) and leakage-free train/val/manual/holdout
  splits. Deliverables enable data-informed training in Sprint 24 and
  establish ground truth for evaluation metrics. **User value:**
  Transparency into data quality; reproducible dataset construction
  eliminates manual/Excel-based splits; mode stratification ensures
  auto-mode focus with explicit manual-mode carve-out for robustness
  testing.

  ### Architecture Placement
  **Component Owner:** Core data ingestion + training utilities
  **Code Paths:**
  - `src/aquaoptima/dataio/yilan_profiler.py` (NEW: mode detection, axis
  coverage, gap analysis)
  - `src/aquaoptima/dataio/yilan_timeseries_dataset.py` (NEW: PyTorch
  Dataset with gap-aware windowing)
  - `src/aquaoptima/dataio/split_builder.py` (NEW: temporal split logic, no
  leakage)
  - `src/aquaoptima/training/normalization.py` (NEW: z-score stats caching)

  **Forbidden:** NO imports from `src/aquaoptima/edge/` or runtime
  contracts; NO model training; NO writes to `src/aquaoptima_contracts/`
  (contracts are read-only stdlib). Data profiling uses only
  pandas/numpy/stdlib.

  ### Tasks (Plane Issue Titles)
  1. **Implement operating-mode detection and stratification profiler**
     Parse `source1_2025.csv`, extract
  `optimizer_enabled`/`auto_mode_active`, generate
  `data/profiling/mode_coverage_2025.json` per spec.

  2. **Build per-axis data quality profiler with missingness & extreme-data
  tagging**
     Compute coverage %, 3σ outliers, p99 thresholds per axis per mode;
  output `data/profiling/axis_coverage_2025.csv` and
  `data/profiling/extreme_data_log_2025.csv`.

  3. **Identify and log temporal gap intervals > 5 min**
     Scan timestamp diffs, flag 19 expected gaps, serialize to
  `data/profiling/gap_intervals_2025.json` with start/end timestamps.

  4. **Implement leakage-free temporal split builder
  (train/val/manual/holdout)**
     Generate `data/splits/yilan_2025_split_v1.json` with exact date ranges;
  validate no day overlap between train/val; exclude March 2026 from all
  2025 splits.

  5. **Create PyTorch Dataset with gap-aware sliding window**
     10-timestep input, 1-step output, stride=1, reset sequence at gap
  boundaries; load normalization stats from
  `data/normalization/yilan_2025_train_stats.json` (compute on-the-fly from
  train split).

  6. **Compute and cache z-score normalization stats (μ, σ per axis) from
  training set**
     Auto-mode 2025 train split only; serialize to
  `data/normalization/yilan_2025_train_stats.json` with units from
  TelemetryTagSpec.

  7. **Write integration test: load splits, assert no leakage, verify
  sequence count**
     Test that train/val date ranges don't overlap, gap count = 19, sequence
  count ≈ 286,800 (train), ≈ 57,400 (val).

  8. **Document dataset construction README under
  docs/planning/dataset_construction.md**
     Human-readable summary of split rationale, mode breakdown, gap
  handling, normalization approach.

  ### Acceptance Criteria
  - [ ] `data/profiling/mode_coverage_2025.json` exists, auto=59.3%,
  manual=40.7%, total=489,163 rows.
  - [ ] `data/profiling/axis_coverage_2025.csv` lists 9 axes,
  `edge_valve_position` coverage=0%, others >93%.
  - [ ] `data/profiling/gap_intervals_2025.json` contains 19 gap entries
  with timestamps.
  - [ ] `data/splits/yilan_2025_split_v1.json` defines train (229,600), val
  (57,400), manual_slice (199,163), holdout_march2026 (30,000).
  - [ ] `data/normalization/yilan_2025_train_stats.json` contains μ/σ for 8
  active axes (not valve_position).
  - [ ] `YilanTimeSeriesDataset` loads without error, `len(train_dataset)` ≈
  286,800, `len(val_dataset)` ≈ 57,400.
  - [ ] Test `tests/dataio/test_yilan_split_no_leakage.py` passes: no date
  overlap, holdout exclusion verified.
  - [ ] README `docs/planning/dataset_construction.md` reviewed and approved
  by analyst.

  ### Files Likely Touched
  **New:**
  - `src/aquaoptima/dataio/yilan_profiler.py`
  - `src/aquaoptima/dataio/yilan_timeseries_dataset.py`
  - `src/aquaoptima/dataio/split_builder.py`
  - `src/aquaoptima/training/normalization.py`
  - `data/profiling/mode_coverage_2025.json`
  - `data/profiling/axis_coverage_2025.csv`
  - `data/profiling/extreme_data_log_2025.csv`
  - `data/profiling/gap_intervals_2025.json`
  - `data/splits/yilan_2025_split_v1.json`
  - `data/normalization/yilan_2025_train_stats.json`
  - `docs/planning/dataset_construction.md`
  - `tests/dataio/test_yilan_split_no_leakage.py`
  - `tests/dataio/test_yilan_dataset_windowing.py`

  **Modified:** None (planning sprint; all code is new scaffolding)

  ### Tests to Create
  1. `tests/dataio/test_yilan_split_no_leakage.py`: Assert train/val date
  ranges disjoint, holdout excluded, gap count = 19.
  2. `tests/dataio/test_yilan_dataset_windowing.py`: Assert sequence count ≈
  expected, no sequences span gap boundaries, window shape [10, 11].
  3. `tests/training/test_normalization_stats.py`: Load cached μ/σ, apply to
  sample, verify z-score mean≈0, std≈1.

  ### E2E Command & Expected Output
  ```bash
  # Step 1: Run profiler
  python -m aquaoptima.dataio.yilan_profiler \
    --input data/source1_2025.csv \
    --output-dir data/profiling/

  # Expected output (stdout):
  # Mode coverage: auto=59.3% (290,000 rows), manual=40.7% (199,163 rows)
  # Gaps detected: 19 intervals > 5 min
  # Per-axis coverage written to data/profiling/axis_coverage_2025.csv

  # Step 2: Build splits
  python -m aquaoptima.dataio.split_builder \
    --input data/source1_2025.csv \
    --gaps data/profiling/gap_intervals_2025.json \
    --output data/splits/yilan_2025_split_v1.json

  # Expected output:
  # Train: 229,600 rows (2025-03-01 to 2025-12-31, auto-mode)
  # Val: 57,400 rows (20% day-stratified sample)
  # Manual slice: 199,163 rows
  # Holdout March 2026: 30,000 rows (frozen)

  # Step 3: Compute normalization stats
  python -m aquaoptima.training.normalization \
    --split-manifest data/splits/yilan_2025_split_v1.json \
    --split-key train \
    --output data/normalization/yilan_2025_train_stats.json

  # Expected output:
  # Computed μ/σ for 8 axes (edge_valve_position skipped, N/A)

  # Step 4: Test dataset loader
  pytest -q tests/dataio/test_yilan_split_no_leakage.py
  tests/dataio/test_yilan_dataset_windowing.py

  # Expected output:
  # .... 4 passed in 2.1s
  ```

  ### Stop Conditions
  - **STOP if:** Gap count ≠ 19, or total rows ≠ 489,163, or mode
  percentages deviate >2% from analyst plan → investigate CSV corruption or
  parsing logic.
  - **STOP if:** Train/val date overlap detected → fix split_builder logic
  before proceeding.
  - **STOP if:** Normalization stats contain NaN or inf → trace to axis with
  zero variance or all-missing data.

  ### Safety Boundary
  **Read-only operation:** No PLC/OT interaction, no model inference, no
  control output. Scripts read CSV files only. No network I/O, no
  SCADA/Modbus/OPC-UA calls. Pure offline data manipulation. Compliance:
  TRIVIAL (air-gapped profiling).

  ### Suggested Commit Message
  ```
  feat(dataio): add Yilan 2025 data profiling and mode-stratified dataset
  builder

  - Implement operating-mode detection (auto/manual) and gap-aware temporal
  split
  - Compute per-axis coverage, extreme-data tagging, and normalization stats
  - Create PyTorch Dataset with sliding-window + gap boundary handling
  - Produce reproducible artifacts: mode_coverage, axis_coverage, split
  manifest, normalization μ/σ
  - Add tests for leakage prevention and sequence windowing

  Deliverables:
    - data/profiling/mode_coverage_2025.json (auto=59.3%, manual=40.7%)
    - data/profiling/axis_coverage_2025.csv (9 axes, valve N/A)
    - data/splits/yilan_2025_split_v1.json (train=229k, val=57k,
  manual=199k, holdout=30k)
    - data/normalization/yilan_2025_train_stats.json (μ/σ for 8 axes)
    - src/aquaoptima/dataio/{yilan_profiler, yilan_timeseries_dataset,
  split_builder}.py
    - src/aquaoptima/training/normalization.py
    - tests/dataio/test_yilan_split_no_leakage.py,
  test_yilan_dataset_windowing.py

  Component: Core dataio + training
  Safety: Read-only CSV profiling, no OT interaction
  Ref: Sprint 23, dPHM PyTorch roadmap
  ```

  ---

  ## Sprint 24: PyTorch dPHM Model + Training Loop (Backlog)

  ### Goal & User Value
  Implement TCN-based multi-output regression model, train on auto-mode 2025
  split, checkpoint best/final weights, log training curves. **User value:**
  Executable model ready for evaluation; reproducible training with
  deterministic seeding; checkpointed artifacts (`.pt` files) ready for ONNX
  export in Sprint 26.

  ### Architecture Placement
  **Component Owner:** Core model + training orchestration
  **Code Paths:**
  - `src/aquaoptima/models/tcn_dphm.py` (NEW: TCN encoder-decoder)
  - `src/aquaoptima/training/dphm_trainer.py` (NEW: training loop,
  checkpointing, early stopping)
  - `src/aquaoptima/training/dphm_loss.py` (NEW: MultiAxisLoss with MSE +
  BCE)
  - `data/models/yilan_dphm_v1/` (output dir for checkpoints)

  **Forbidden:** NO edge runtime imports; NO inference/advisory logic; NO
  ONNX export yet (Sprint 26). Model stays in PyTorch `.pt` format. NO writes
  to `src/aquaoptima_contracts/`.

  ### Tasks (Plane Issue Titles)
  1. **Implement TCN-based multi-output dPHM model (11 input features → 8
  output axes)**
  2. **Implement MultiAxisLoss with per-axis MSE (6 continuous) + BCE (2
  binary)**
  3. **Build training loop with AdamW optimizer, ReduceLROnPlateau, early
  stopping**
  4. **Add deterministic seeding (torch.manual_seed=42,
  cudnn.deterministic=True)**
  5. **Implement checkpointing: save best (val_loss), final,
  training_log.csv**
  6. **Write training script with CLI args: --epochs, --batch-size, --lr,
  --checkpoint-dir**
  7. **Add unit test: forward pass shape check [batch, 10, 11] → [batch,
  8]**
  8. **Add integration test: train 2 epochs on subset, assert loss
  decreases**

  ### Acceptance Criteria
  - [ ] `src/aquaoptima/models/tcn_dphm.py` defines `TCN_DPHM(nn.Module)`
  with 3-layer TCN + linear projection.
  - [ ] Forward pass: input `[128, 10, 11]` → output `[128, 8]` (batch,
  axes).
  - [ ] `src/aquaoptima/training/dphm_loss.py` computes combined MSE+BCE,
  per-axis weights=1.0.

  - [ ] Training loop runs 2 epochs on a 5k-row subset without error; train
  loss strictly decreases epoch-1 → epoch-2.
  - [ ] Deterministic seeding wired (`torch.manual_seed(42)`,
  `cudnn.deterministic=True`, `cudnn.benchmark=False`); two identical runs
  produce bitwise-identical `model_final.pt` on CPU.
  - [ ] Checkpointing writes `data/models/yilan_dphm_v1/model_best.pt`,
  `model_final.pt`, `training_log.csv` (epoch, train_loss, val_loss, lr,
  timestamp), and a copy of `normalization_stats.json`.
  - [ ] Early stopping (patience=10 on val_loss) and ReduceLROnPlateau
  (patience=5, factor=0.5) verified active in `training_log.csv`.
  - [ ] No import of `src/aquaoptima/edge/*` or
  `src/aquaoptima_contracts/edge/*` anywhere under `models/` or `training/`
  (enforced by import-linter test).
  - [ ] Model stays in `.pt` (state_dict) format only; NO ONNX export in this
  sprint (deferred to Sprint 26 / Sprint 26).
  - [ ] Unit + integration tests pass under `pytest -q tests/training
  tests/models`.

  ### Files Likely Touched
  **New:**
  - `src/aquaoptima/models/tcn_dphm.py`
  - `src/aquaoptima/training/dphm_trainer.py`
  - `src/aquaoptima/training/dphm_loss.py`
  - `src/aquaoptima/training/seed.py`
  - `configs/yilan_dphm_v1.yaml`
  - `data/training/seed_config.json`
  - `data/models/yilan_dphm_v1/` (output: model_best.pt, model_final.pt,
  training_log.csv, normalization_stats.json)
  - `tests/models/test_tcn_dphm_forward.py`
  - `tests/training/test_dphm_loss.py`
  - `tests/training/test_train_smoke.py`
  - `tests/architecture/test_no_edge_imports_in_core.py`

  **Modified:** None outside core `models/` + `training/` (no contracts, no
  edge, no dataio changes beyond Sprint 23 outputs).

  ### Tests to Create
  1. `tests/models/test_tcn_dphm_forward.py`: assert forward `[128,10,11] →
  [128,8]`; assert parameter count > 0; assert no NaN on random input.
  2. `tests/training/test_dphm_loss.py`: assert `MultiAxisLoss` returns scalar
  ≥ 0; assert binary axes (`node_status`, `edge_status`) routed to BCE,
  continuous axes to MSE; assert masked axis (`edge_valve_position`)
  contributes 0.
  3. `tests/training/test_train_smoke.py`: train 2 epochs on a 5k subset;
  assert `train_loss[1] < train_loss[0]`; assert `model_best.pt` written.
  4. `tests/architecture/test_no_edge_imports_in_core.py`: static check that
  `models/` and `training/` never import `aquaoptima.edge` or
  `aquaoptima_contracts.edge`.

  ### E2E Command & Expected Output
  ```bash
  # Smoke train (CI-fast) on a subset
  python -m aquaoptima.training.dphm_trainer \
    --config configs/yilan_dphm_v1.yaml \
    --split-manifest data/splits/yilan_2025_split_v1.json \
    --norm-stats data/normalization/yilan_2025_train_stats.json \
    --epochs 2 --subset-rows 5000 \
    --checkpoint-dir data/models/yilan_dphm_v1/

  # Expected output (stdout):
  # epoch 1 | train_loss 0.842 | val_loss 0.871 | lr 1.0e-03
  # epoch 2 | train_loss 0.613 | val_loss 0.659 | lr 1.0e-03
  # saved best checkpoint -> data/models/yilan_dphm_v1/model_best.pt

  # Tests
  pytest -q tests/models/test_tcn_dphm_forward.py \
           tests/training/test_dphm_loss.py \
           tests/training/test_train_smoke.py \
           tests/architecture/test_no_edge_imports_in_core.py
  # Expected output:
  # ....                                                   [100%]
  # 4 passed in 6.4s
  ```

  ### Stop Conditions
  - **STOP if:** forward-pass output shape ≠ `[batch, 8]` → fix head
  projection before training.
  - **STOP if:** smoke train loss does NOT decrease (`train_loss[1] ≥
  train_loss[0]`) → investigate lr, normalization, or label alignment.
  - **STOP if:** loss diverges (NaN/inf, or monotone increase after epoch 10
  on a full run) → halt, do not checkpoint a divergent model.
  - **STOP if:** any `aquaoptima.edge` / `aquaoptima_contracts.edge` import
  appears in core → architecture violation, revert.
  - **STOP if:** two identical-seed CPU runs are not bitwise identical →
  determinism broken; fix before relying on reproducibility downstream.

  ### Safety Boundary
  **Offline training only.** No PLC/PAC/SCADA/OT interaction, no live
  telemetry binding, no Modbus/OPC-UA, no network egress to control systems.
  Training consumes static CSV-derived splits and writes only model
  checkpoints under `data/models/`. The trained `.pt` produces NO advisory or
  control output in this sprint — it is an inert artifact until evaluated
  (Sprint 25) and packaged (Sprint 26). No control-loop closure, no command
  emission, no setpoint output.

  ### Suggested Commit Message
  ```
  feat(models,training): add TCN dPHM model and reproducible PyTorch training loop

  - Implement TCN_DPHM (3-layer dilated TCN + multi-task linear head): [B,10,11]->[B,8]
  - Add MultiAxisLoss (per-axis MSE for 6 continuous + BCE for 2 binary; valve axis masked)
  - Build training loop: AdamW, ReduceLROnPlateau, early stopping, deterministic seeding
  - Checkpoint best/final state_dicts + training_log.csv + normalization snapshot
  - Add forward/loss/smoke tests and an architecture test forbidding edge imports in core

  Component: Core models + training (no edge, no contracts changes)
  Safety: Offline training only; .pt artifact is inert (no advisory/control output)
  Ref: Sprint 24 (Sprint 24), dPHM PyTorch roadmap
  ```

  ---

  ## Sprint 25: Offline Evaluation Harness vs LOCKED March 2026 Benchmark (Backlog)

  ### Goal & User Value
  Build a reproducible **offline** evaluation harness that scores the trained
  model against the LOCKED March 2026 frozen holdout and the extended 2026
  holdout, emitting per-axis MSE/MAE aligned to the `ShadowRuntimeReport`
  contract shape, plus a baseline comparison versus current MVP v1 behavior.
  Define explicit acceptance thresholds that decide whether the model is
  "good enough to package" in Sprint 26. **User value:** an objective,
  contract-shaped, reproducible scorecard that gates packaging — no model
  ships to edge without passing the locked benchmark, and operators get an
  apples-to-apples comparison against the incumbent MVP.

  ### Architecture Placement
  **Component Owner:** Core evaluation (lives with model/training utilities);
  consumes the SHARED `ShadowRuntimeReport` contract for output shape only.
  **Code Paths:**
  - `src/aquaoptima/training/evaluation.py` (NEW: per-axis MSE/MAE, metric
  aggregation, holdout loop)
  - `src/aquaoptima/training/baseline_mvp.py` (NEW: persistence / last-value
  and MVP-behavior baseline predictor for comparison)
  - `src/aquaoptima/training/eval_report.py` (NEW: assemble metrics into a
  `ShadowRuntimeReport`-shaped dict for serialization)
  - `data/eval/yilan_dphm_v1/` (output dir: scorecards, JSON reports)
  - reads (import allowed, never writes): the `ShadowRuntimeReport`
  dataclass/schema from `src/aquaoptima_contracts/` (shared contracts)

  **Forbidden cross-component imports:**
  - NO import of `src/aquaoptima/edge/*` (edge runtime) — evaluation is an
  offline core activity, not an edge activity.
  - NO import of `src/aquaoptima_contracts/edge/*` (that is Sprint 26's
  packaging concern).
  - NO WRITES to `src/aquaoptima_contracts/*` — contracts are read-only; the
  harness only *imports* the `ShadowRuntimeReport` shape to align its output.
  - NO ONNX export and NO edge packaging here (Sprint 26).

  ### Tasks (Plane Issue Titles)
  1. **Implement offline evaluator that loads `model_best.pt` and scores the
  March 2026 frozen holdout (per-axis MSE/MAE)**
  2. **Add extended-2026-holdout scoring path (seasonality/drift checks,
  reported separately from the locked benchmark)**
  3. **Align evaluation output to the `ShadowRuntimeReport` contract shape (no
  contract edits; consume the existing schema)**
  4. **Implement MVP v1 baseline predictor (persistence / last-observed-value
  proxy for incumbent behavior) and score it on the same holdout**
  5. **Compute relative improvement (dPHM vs baseline) per axis and emit a
  scorecard `data/eval/yilan_dphm_v1/march2026_scorecard.json`**
  6. **Define and encode acceptance thresholds ("good enough to package") as a
  machine-checkable gate**
  7. **Write a deterministic eval E2E test that runs on a fixture holdout and
  asserts the scorecard schema + threshold-gate logic**
  8. **Document the evaluation methodology and thresholds in
  `docs/planning/evaluation_methodology.md`**

  ### Acceptance Criteria
  - [ ] `python -m aquaoptima.training.evaluation` scores the **frozen March
  2026 holdout** (≈30k rows) and writes
  `data/eval/yilan_dphm_v1/march2026_scorecard.json`.
  - [ ] Scorecard reports **per-axis MSE and MAE** for all 8 active axes
  (`edge_valve_position` reported as N/A/masked).
  - [ ] Scorecard payload conforms to the `ShadowRuntimeReport` contract shape
  (field names/types validated against the imported schema — NOT a forked
  copy).
  - [ ] MVP v1 **baseline** scored on the identical holdout; per-axis
  dPHM-vs-baseline delta reported.
  - [ ] Acceptance thresholds encoded and evaluated, e.g.: continuous-axis
  **normalized MSE ≤ 0.15** AND **MAE ≤ 0.30** per active continuous axis;
  binary-axis (`node_status`, `edge_status`) **accuracy ≥ 0.95**; dPHM **beats
  baseline** (lower MSE) on ≥ 5 of 6 continuous axes. Gate returns
  PASS/FAIL.
  - [ ] Extended-2026-holdout scored and reported **separately** (informational
  drift check, NOT part of the packaging gate).
  - [ ] March 2026 holdout is read-only; harness contains an assertion that it
  never appears in any training/val split (re-checks the split manifest).
  - [ ] Eval E2E test passes under `pytest -q tests/training/test_evaluation_harness.py`.

  ### Files Likely Touched
  **New:**
  - `src/aquaoptima/training/evaluation.py`
  - `src/aquaoptima/training/baseline_mvp.py`
  - `src/aquaoptima/training/eval_report.py`
  - `data/eval/yilan_dphm_v1/march2026_scorecard.json` (output)
  - `data/eval/yilan_dphm_v1/extended2026_scorecard.json` (output)
  - `docs/planning/evaluation_methodology.md`
  - `tests/training/test_evaluation_harness.py`
  - `tests/training/test_acceptance_thresholds.py`

  **Modified:** None in contracts/edge. Possibly extend
  `configs/yilan_dphm_v1.yaml` with an `eval:` block (thresholds).

  ### Tests to Create
  1. `tests/training/test_evaluation_harness.py`: run evaluator on a small
  fixture holdout; assert scorecard JSON validates against the
  `ShadowRuntimeReport` shape; assert per-axis MSE/MAE keys present for 8
  axes.
  2. `tests/training/test_acceptance_thresholds.py`: feed synthetic
  metrics above/below thresholds; assert gate returns FAIL/PASS correctly;
  assert baseline-comparison logic (dPHM must beat baseline on ≥5/6
  continuous axes).
  3. `tests/training/test_holdout_isolation.py`: assert the March 2026
  holdout window does not intersect any train/val split window.

  ### E2E Command & Expected Output
  ```bash
  python -m aquaoptima.training.evaluation \
    --checkpoint data/models/yilan_dphm_v1/model_best.pt \
    --split-manifest data/splits/yilan_2025_split_v1.json \
    --norm-stats data/normalization/yilan_2025_train_stats.json \
    --holdout-key holdout_march2026 \
    --baseline mvp_persistence \
    --output data/eval/yilan_dphm_v1/march2026_scorecard.json

  # Expected output (stdout):
  # === March 2026 LOCKED holdout (30,000 rows) ===
  # axis                 MSE(norm)  MAE(norm)   baseline_MSE   beats_baseline
  # node_pressure          0.071      0.198        0.142            yes
  # node_demand            0.089      0.221        0.160            yes
  # node_level             0.064      0.181        0.151            yes
  # edge_flow              0.112      0.268        0.171            yes
  # edge_pump_speed        0.098      0.241        0.155            yes
  # edge_power             0.131      0.289        0.149            yes
  # node_status (acc)      0.971        -            0.940          yes
  # edge_status (acc)      0.983        -            0.951          yes
  # edge_valve_position    N/A         N/A          N/A             N/A
  # GATE: PASS (good enough to package)  -> Sprint 26 unblocked
  # scorecard -> data/eval/yilan_dphm_v1/march2026_scorecard.json

  pytest -q tests/training/test_evaluation_harness.py \
           tests/training/test_acceptance_thresholds.py \
           tests/training/test_holdout_isolation.py
  # Expected output:
  # ...                                                    [100%]
  # 3 passed in 4.8s
  ```

  ### Stop Conditions
  - **STOP if:** the March 2026 holdout window intersects any train/val split
  → data-leakage; abort evaluation, fix splits.
  - **STOP if:** the scorecard does not validate against the
  `ShadowRuntimeReport` shape → fix `eval_report.py` mapping (do NOT edit the
  contract).
  - **STOP if:** acceptance gate returns FAIL → DO NOT proceed to Sprint 26
  packaging; iterate on Sprint 24 training instead.
  - **STOP if:** dPHM fails to beat the MVP baseline on the required number of
  axes → packaging is not justified; escalate to a model/feature review.

  ### Safety Boundary
  **Offline scoring only.** No edge runtime, no OT/PLC/SCADA interaction, no
  command/setpoint output. Outputs are evidence/advisory scorecards consumed
  by humans to decide packaging — they NEVER drive actuation or close any
  control loop. The `ShadowRuntimeReport` shape is used purely as a
  serialization target; producing one here does not bind it to any live
  runtime. March 2026 + extended 2026 holdouts remain read-only.

  ### Suggested Commit Message
  ```
  feat(training): add offline evaluation harness vs LOCKED March 2026 benchmark

  - Score model_best.pt on frozen March 2026 holdout + extended 2026 holdout (per-axis MSE/MAE)
  - Emit ShadowRuntimeReport-shaped scorecards (consume contract shape, no contract edits)
  - Add MVP v1 persistence baseline and per-axis dPHM-vs-baseline comparison
  - Encode "good enough to package" acceptance thresholds as a PASS/FAIL gate
  - Add evaluation, threshold, and holdout-isolation tests

  Component: Core training/evaluation (no edge, no contracts changes)
  Safety: Offline scoring only; advisory scorecards, no actuation
  Ref: Sprint 25 (Sprint 25), dPHM PyTorch roadmap
  ```

  ---

  ## Sprint 26: PyTorch → Edge-Artifact Packaging Path — Option A (torch→ONNX) [MOST IMPORTANT] (Backlog)

  ### Goal & User Value
  Convert the validated PyTorch model into a **deployable edge artifact** via
  the LOCKED default path — **Option A: train in PyTorch, export to ONNX** —
  with a torch-vs-ONNX **numerical parity gate**, then build a
  `ModelArtifactRecord` + `DeploymentPackageManifest` and prove that
  `validate_deployment_package_for_edge(...)` accepts the package **UNCHANGED**
  on the AMAX-8580 default CPU edge profile (advertises `onnx`/`tflite`;
  rejects `pytorch`/`cuda`/`tensorrt`/`jetson`/`orin`/`arm64`/`aarch64`).
  **User value:** a checksummed, contract-valid, CPU-deployable shadow-mode
  artifact that the existing edge validator passes with **zero contract or
  edge-profile changes** — de-risking deployment entirely.

  ### Architecture Placement
  **Component Owner:** SHARED contracts boundary + a thin core export utility.
  Packaging/validation logic belongs to the shared-contracts layer
  (`src/aquaoptima_contracts/`); ONNX export is a core-model utility.
  **Code Paths:**
  - `src/aquaoptima/training/onnx_export.py` (NEW core util: torch→ONNX export
  + opset pinning)
  - `src/aquaoptima/training/onnx_parity.py` (NEW core util: torch-vs-onnxruntime
  parity check on a holdout sample)
  - `src/aquaoptima_contracts/edge/package_builder.py` (NEW shared:
  `build_model_artifact_record(...)` and
  `build_deployment_package_manifest(...)`)
  - reads/uses existing `src/aquaoptima_contracts/edge/package_validator.py`
  (`validate_deployment_package_for_edge`) — **no modification**
  - `data/models/yilan_dphm_v1/model.onnx` (output artifact)
  - `data/packages/yilan_dphm_v1/deployment_package_manifest.json` (output)

  **Forbidden cross-component imports:**
  - The `package_builder` in `src/aquaoptima_contracts/edge/` must NOT import
  from `src/aquaoptima/*` (contracts never depend on the model layer).
  - The core export utils (`src/aquaoptima/training/onnx_*.py`) may import the
  shared contract dataclasses (`ModelArtifactRecord`,
  `DeploymentPackageManifest`, `SafetyFlagSet`) but must NOT reach into
  `src/aquaoptima/edge/*` runtime internals.
  - **No edge-profile schema change.** The AMAX-8580 default CPU profile must
  remain UNCHANGED; if a change is needed, that is Option B (see Backlog).
  - `framework` field in `ModelArtifactRecord` **MUST be `"onnx"`** for Option
  A.

  ### Tasks (Plane Issue Titles)
  1. **Implement deterministic torch→ONNX export (pinned opset, fixed input
  signature `[1,10,11]`, dynamic batch axis) producing `model.onnx`**
  2. **Implement torch-vs-ONNX numerical parity check (max abs diff < 1e-4 on
  a March-2026 holdout sample of 1000 rows); BLOCK on failure**
  3. **Compute SHA256 checksum + size of `model.onnx` and build a
  `ModelArtifactRecord` with `framework="onnx"` (external checksummed
  reference, never inline weights)**
  4. **Build a `DeploymentPackageManifest` with all 7 `SafetyFlagSet` flags =
  True, matching `package_id`s, `schema_family="manifest"`, label contract =
  9 canonical axes / `TelemetryTagMap` roles**
  5. **Write a test asserting
  `validate_deployment_package_for_edge(manifest, amax8580_cpu_profile).accepted
  is True` (artifact accepted UNCHANGED)**
  6. **Add negative tests: a `framework="pytorch"` artifact and a
  `cuda`/`tensorrt`/`aarch64`-tagged artifact are REJECTED by the same
  validator (proves rejection still works)**
  7. **Document the packaging path + Option A/B decision in
  `docs/planning/edge_packaging_path.md` (Option B explicitly deferred to
  Backlog)**

  ### Acceptance Criteria
  - [ ] `model.onnx` exported deterministically; re-export from the same `.pt`
  is byte-stable (or parity-stable) on CPU.
  - [ ] Torch-vs-ONNX parity: **max abs diff < 1e-4** on a 1000-row March-2026
  holdout sample; parity result logged to
  `data/packages/yilan_dphm_v1/parity_report.json`. Packaging is **BLOCKED**
  if parity fails.
  - [ ] `ModelArtifactRecord` built with **`framework="onnx"`**, a real SHA256
  `checksum` + `size_bytes`, and `model_file_uri` pointing at the external
  `.onnx` (NO inline weights).
  - [ ] `DeploymentPackageManifest` has all **7 `SafetyFlagSet` flags True**,
  matching `package_id`s across record↔manifest, `schema_family="manifest"`,
  and prediction labels = the 9 canonical telemetry axes /
  `TelemetryTagMap` input roles.
  - [ ] **`validate_deployment_package_for_edge(manifest,
  amax8580_cpu_profile).accepted is True`** — accepted UNCHANGED on the
  default CPU edge profile, with NO edge-profile or contract modification.
  - [ ] Negative tests pass: `framework="pytorch"` → `accepted is False`;
  `cuda`/`tensorrt`/`jetson`/`orin`/`arm64`/`aarch64` accelerator/architecture
  tokens → `accepted is False`.
  - [ ] `git diff` shows **no change** under
  `src/aquaoptima_contracts/edge/package_validator.py` or the AMAX-8580
  profile definition (validator/profile untouched).
  - [ ] `pytest -q tests/contracts/test_edge_package_accept.py` is GREEN.

  ### Files Likely Touched
  **New:**
  - `src/aquaoptima/training/onnx_export.py`
  - `src/aquaoptima/training/onnx_parity.py`
  - `src/aquaoptima_contracts/edge/package_builder.py`
  - `data/models/yilan_dphm_v1/model.onnx` (output)
  - `data/packages/yilan_dphm_v1/deployment_package_manifest.json` (output)
  - `data/packages/yilan_dphm_v1/model_artifact_record.json` (output)
  - `data/packages/yilan_dphm_v1/parity_report.json` (output)
  - `docs/planning/edge_packaging_path.md`
  - `tests/contracts/test_edge_package_accept.py`
  - `tests/contracts/test_edge_package_reject.py`
  - `tests/training/test_onnx_parity.py`

  **Modified:** NONE in
  `src/aquaoptima_contracts/edge/package_validator.py` and NONE in the
  AMAX-8580 profile — that is the whole point of Option A.

  ### Tests to Create
  1. `tests/training/test_onnx_parity.py`: export a tiny model, run torch +
  onnxruntime on the same input, assert `max_abs_diff < 1e-4`; assert the
  parity gate raises/blocks when diff ≥ 1e-4.
  2. `tests/contracts/test_edge_package_accept.py`: build manifest via
  `package_builder` with `framework="onnx"`, 7 safety flags True; assert
  `validate_deployment_package_for_edge(...).accepted is True`.
  3. `tests/contracts/test_edge_package_reject.py`: assert
  `framework="pytorch"` rejected; assert `cuda`/`tensorrt`/`aarch64` tokens
  rejected; assert a safety flag set False → rejected; assert mismatched
  `package_id` → rejected.

  ### E2E Command & Expected Output
  ```bash
  # 1. Export + parity gate
  python -m aquaoptima.training.onnx_export \
    --checkpoint data/models/yilan_dphm_v1/model_best.pt \
    --output data/models/yilan_dphm_v1/model.onnx --opset 17

  python -m aquaoptima.training.onnx_parity \
    --checkpoint data/models/yilan_dphm_v1/model_best.pt \
    --onnx data/models/yilan_dphm_v1/model.onnx \
    --holdout-sample 1000 \
    --report data/packages/yilan_dphm_v1/parity_report.json
  # Expected: parity OK | max_abs_diff=3.1e-05 (< 1e-4) -> PASS

  # 2. Build package + validate against AMAX-8580 CPU profile
  python -m aquaoptima_contracts.edge.package_builder \
    --onnx data/models/yilan_dphm_v1/model.onnx \
    --framework onnx \
    --hardware-profile amax8580_cpu \
    --out data/packages/yilan_dphm_v1/deployment_package_manifest.json
  # Expected:
  # ModelArtifactRecord.framework = onnx
  # SafetyFlagSet: 7/7 True
  # validate_deployment_package_for_edge(...).accepted = True
  # package -> data/packages/yilan_dphm_v1/deployment_package_manifest.json

  # 3. Tests
  pytest -q tests/training/test_onnx_parity.py \
           tests/contracts/test_edge_package_accept.py \
           tests/contracts/test_edge_package_reject.py
  # Expected output:
  # .....                                                  [100%]
  # 5 passed in 5.7s
  ```

  ### Stop Conditions
  - **STOP if:** torch-vs-ONNX parity max abs diff ≥ 1e-4 → **BLOCK
  packaging**; investigate opset/operator/quantization mismatch. Do NOT ship a
  non-equivalent model.
  - **STOP if:** `validate_deployment_package_for_edge(...).accepted` is not
  True on the default CPU profile → do NOT modify the validator/profile to
  force acceptance; fix the manifest (framework, flags, ids) instead.
  - **STOP if:** any safety flag is not True, or `package_id`s mismatch, or
  `schema_family != "manifest"` → reject; fix the builder.
  - **STOP if:** the negative tests stop rejecting `pytorch`/`cuda`/`aarch64`
  → the rejection logic regressed; halt — accelerator/architecture rejection
  must never weaken.
  - **STOP if:** packaging requires editing the edge profile to advertise
  `pytorch` → that is **Option B**, out of scope; route to Backlog with its
  own contracts change + verification + safety review.

  ### Safety Boundary
  **Packaging produces an inert, checksummed, read-only artifact.** The ONNX
  model + manifest carry NO actuation pathway: all 7 `SafetyFlagSet` flags
  affirm shadow/advisory-only, no OT binding, no PLC/PAC/SCADA write, no
  command/setpoint emission, no control-loop closure. Option A specifically
  preserves the edge validator's existing rejection of unsupported
  frameworks, accelerator tokens, and architecture mismatches — packaging
  does NOT weaken any guardrail. The artifact is loaded read-only by the edge
  shadow runtime and emits advisory evidence only.

  ### Option B (DEFERRED — Backlog Alternative)
  **Option B = native TorchScript edge artifact + extend the edge profile to
  advertise `pytorch` (libtorch CPU).** This is explicitly **NOT** the default
  and is deferred to Backlog. Activating Option B requires ALL of:
  1. A dedicated **contracts change** adding `"pytorch"` to the AMAX-8580
  profile's `supported_model_frameworks` (its own PR + contracts review).
  2. Independent **verification**: libtorch CPU determinism audit on
  AMAX-8580 hardware (100× identical-input → bitwise-identical output) and a
  TorchScript-vs-PyTorch parity check.
  3. A separate **safety review** confirming the profile extension does NOT
  weaken accelerator/architecture rejection (cuda/tensorrt/jetson/orin/
  arm64/aarch64 must still be rejected).
  Until all three pass, `framework` remains `"onnx"` and Option A is the only
  approved path.

  ### Suggested Commit Message
  ```
  feat(contracts,training): package PyTorch model as ONNX edge artifact (Option A)

  - Add deterministic torch->ONNX export (pinned opset, dynamic batch axis)
  - Add torch-vs-ONNX numerical parity gate (max abs diff < 1e-4); BLOCK on failure
  - Build ModelArtifactRecord(framework="onnx", sha256 checksum, external uri) — no inline weights
  - Build DeploymentPackageManifest (7/7 SafetyFlagSet True, matching package_ids, schema_family=manifest)
  - Assert validate_deployment_package_for_edge(...).accepted is True on AMAX-8580 CPU profile (UNCHANGED)
  - Add negative tests: pytorch/cuda/tensorrt/aarch64 still rejected; Option B deferred to Backlog

  Component: Shared contracts (package builder) + core export util (no edge runtime, no validator/profile edits)
  Safety: Inert checksummed artifact, shadow-only flags; rejection guardrails preserved
  Ref: Sprint 26 (Sprint 26), dPHM PyTorch roadmap
  ```

  ---

  ## Sprint 27: Broader Offline Robustness on Manual-Mode 2025 Slice + Anomaly Evidence (BACKLOG — NOT execution-ready)

  ### Goal & User Value
  Extend offline evaluation to the **manual-mode 2025 robustness slice**
  (~199k rows) and produce **anomaly evidence** (where shadow predictions
  diverge from observed telemetry under manual overrides), characterizing how
  the auto-mode-trained model generalizes to the manual regime. **User
  value:** operational guidance — e.g., "dPHM advisory is unreliable during
  manual overrides" — surfaced as evidence, never as automated handoff. This
  sprint is **Backlog / Candidate only**; it is NOT execution-ready and must
  not be marked Planned.

  ### Architecture Placement
  **Component Owner:** Core evaluation (extends Sprint 25 harness); reuses the
  `ShadowRuntimeReport` shape from shared contracts.
  **Code Paths:**
  - `src/aquaoptima/training/robustness_eval.py` (NEW: manual-slice scoring +
  regime-shift metrics)
  - `src/aquaoptima/training/anomaly_evidence.py` (NEW: per-axis residual /
  divergence flags → advisory evidence records)
  - `data/eval/yilan_dphm_v1/manual_slice_report.json` (output)
  - reads the `ShadowRuntimeReport` shape from `src/aquaoptima_contracts/`

  **Forbidden cross-component imports:**
  - NO `src/aquaoptima/edge/*` and NO `src/aquaoptima_contracts/edge/*`
  imports.
  - NO WRITES to `src/aquaoptima_contracts/*`.
  - Anomaly evidence is advisory only — it MUST NOT feed any retraining
  trigger, control handoff, or edge runtime.

  ### Tasks (Plane Issue Titles)
  1. **Score the manual-mode 2025 slice (test-only) and report per-axis
  MSE/MAE vs the auto-mode benchmark**
  2. **Quantify regime-shift degradation (manual vs auto per-axis metric
  delta)**
  3. **Implement anomaly-evidence generator (residual thresholding → advisory
  flags, NOT actions)**
  4. **Produce an operational-guidance summary ("advisory reliability by
  regime")**
  5. **Add tests asserting the manual slice is test-only (never triggers
  weight updates / retraining)**
  6. **Document robustness findings in
  `docs/planning/robustness_anomaly_backlog.md` (Backlog status)**

  ### Acceptance Criteria (Backlog — to be ratified if/when promoted)
  - [ ] Manual-slice scorecard `data/eval/yilan_dphm_v1/manual_slice_report.json`
  produced (per-axis MSE/MAE, regime-shift deltas).
  - [ ] Anomaly evidence emitted as **advisory records only** (no action
  field, no setpoint, no command).
  - [ ] A test asserts the manual slice NEVER triggers retraining or weight
  updates (test-only guarantee).
  - [ ] Operational-guidance summary documents advisory reliability by regime.
  - [ ] Sprint remains labeled **Backlog**; NOT marked Planned.

  ### Files Likely Touched
  **New:**
  - `src/aquaoptima/training/robustness_eval.py`
  - `src/aquaoptima/training/anomaly_evidence.py`
  - `data/eval/yilan_dphm_v1/manual_slice_report.json` (output)
  - `docs/planning/robustness_anomaly_backlog.md`
  - `tests/training/test_manual_slice_test_only.py`
  - `tests/training/test_anomaly_evidence_advisory_only.py`

  **Modified:** None in contracts/edge.

  ### Tests to Create
  1. `tests/training/test_manual_slice_test_only.py`: assert evaluating the
  manual slice never invokes an optimizer step / does not mutate the
  checkpoint.
  2. `tests/training/test_anomaly_evidence_advisory_only.py`: assert anomaly
  records contain no `action`/`setpoint`/`command` field — advisory evidence
  only.

  ### E2E Command & Expected Output
  ```bash
  python -m aquaoptima.training.robustness_eval \
    --checkpoint data/models/yilan_dphm_v1/model_best.pt \
    --split-manifest data/splits/yilan_2025_split_v1.json \
    --slice manual_slice \
    --output data/eval/yilan_dphm_v1/manual_slice_report.json
  # Expected output (stdout):
  # === Manual-mode 2025 slice (199,163 rows, TEST-ONLY) ===
  # mean per-axis MSE delta vs auto benchmark: +0.18 (degraded, as expected)
  # anomaly evidence records: 1,204 (advisory only; NO actions emitted)
  # guidance: dPHM advisory reliability LOWER during manual overrides
  # report -> data/eval/yilan_dphm_v1/manual_slice_report.json

  pytest -q tests/training/test_manual_slice_test_only.py \
           tests/training/test_anomaly_evidence_advisory_only.py
  # Expected output:
  # ..                                                     [100%]
  # 2 passed in 3.2s
  ```

  ### Stop Conditions
  - **STOP (by design):** This sprint is Backlog — do NOT begin until Sprints
  C and D are accepted and a product decision promotes it.
  - **STOP if:** any anomaly-evidence record gains an action/setpoint/command
  field → safety violation; advisory-only is mandatory.
  - **STOP if:** manual-slice evaluation mutates model weights → leakage /
  test-only violation.

  ### Safety Boundary
  **Offline, test-only, advisory-only.** No retraining on manual data, no OT
  interaction, no command/setpoint/control-loop output. Anomaly evidence is
  consumed by humans as operational guidance, never as automated control
  handoff. Manual slice is read-only and never blended into training.

  ### Suggested Commit Message
  ```
  feat(training): add manual-mode robustness eval + advisory anomaly evidence (Backlog)

  - Score manual-mode 2025 slice (test-only) and report regime-shift degradation
  - Generate advisory anomaly evidence (residual flags; NO actions/setpoints/commands)
  - Add operational-guidance summary (advisory reliability by regime)
  - Tests: manual slice is test-only (no retraining); anomaly evidence is advisory-only

  Component: Core training/evaluation (no edge, no contracts changes)
  Safety: Offline, test-only, advisory-only; no control handoff
  Status: BACKLOG / Candidate — not execution-ready
  Ref: Sprint 27 (Sprint 27), dPHM PyTorch roadmap
  ```

  ---

  ## Plane Recommendation

  Mark **only Sprint 23 ( Data Profiling & Mode-Stratified Dataset
  Builder)** as **Planned next**; it has no upstream dependency, is read-only,
  and unblocks everything downstream. Keep **Sprints B, C, and D** as
  **Backlog → Candidate**, each promoted to Planned only after the prior
  sprint's verification gate passes (B after A's leakage/windowing tests; C
  after B's smoke-train + determinism gate; D after C's acceptance-threshold
  gate returns PASS). Keep **Sprint 27** as **Backlog** — it is not
  execution-ready and should be promoted only by an explicit product decision
  after D ships. Do NOT chain multiple model/safety sprints unattended: hold a
  gate-review checkpoint between each sprint.
