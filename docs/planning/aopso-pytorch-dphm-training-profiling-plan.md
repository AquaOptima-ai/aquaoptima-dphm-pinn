# AOPSO PyTorch dPHM Training & Data Profiling Plan (Sprint 23 basis)

> **Project:** Pump Station Optimizer Lite (AOPSO), continues from Sprint 22. Yilan single-site. Offline only.

  **Product:** AquaOptima dPHM-PINN (aquaoptima-dphm-pinn, main @ 9453b9f)
  **Site:** Yilan 溪南系統 (P_1531A-D)
  **Mode:** Shadow/advisory only (read-only sidecar, NO control-loop
  closure)
  **Framework:** PyTorch (training) → ONNX export (edge artifact, Option A)
  **Architecture:** Core model/training in `src/aquaoptima/dphm/`,
  `src/aquaoptima/models/`, `src/aquaoptima/training/`; edge runtime in
  `src/aquaoptima/edge/`; contracts in `src/aquaoptima_contracts/`

  ---

  ## 1. Data Profiling Plan

  **Objective:** Characterize the 2025 Yilan dataset by operating mode,
  quantify per-axis data quality, identify exclusion windows, and produce
  reproducible profiling artifacts that inform training/validation split and
  model robustness.

  ### 1.1 Operating-Mode Stratification

  **Input:** `source1_2025.csv` (489,163 rows, 2025-01-21 → 2025-12-31).

  **Mode Detection Logic:**
  - Extract `optimizer_enabled` flag and `auto_mode_active` indicator from
  telemetry (or infer from `control_mode` tag if available).
  - Auto-mode months: Mar, Apr, May, Jun, Jul, Oct, Dec (~290k rows, ~60% of
  dataset).
  - Manual-mode months: Jan, Feb, Aug, Sep, Nov (~199k rows, ~40%).

  **Profiling Artifact:** `data/profiling/mode_coverage_2025.json`
  ```json
  {
    "total_rows": 489163,
    "date_range": ["2025-01-21T00:00:00Z", "2025-12-31T23:59:00Z"],
    "mode_breakdown": {
      "auto": {"months": ["2025-03", "2025-04", "2025-05", "2025-06",
  "2025-07", "2025-10", "2025-12"], "row_count": 290000, "percentage":
  59.3},
      "manual": {"months": ["2025-01", "2025-02", "2025-08", "2025-09",
  "2025-11"], "row_count": 199163, "percentage": 40.7}
    },
    "sampling_stats": {
      "median_interval_sec": 60,
      "gap_count_gt_5min": 19,
      "max_gap_hours": 4.3
    }
  }
  ```

  ### 1.2 Per-Axis Data Quality

  **Canonical Telemetry Axes (prediction targets):**
  1. `node_pressure` (system_pressure)
  2. `node_demand` (system_flow_rate)
  3. `node_level` (tank_level)
  4. `node_status` (discrete, e.g., tank alarm)
  5. `edge_flow` (pump flow, derived or measured)
  6. `edge_pump_speed` (pump frequency Hz)
  7. `edge_status` (pump on/off)
  8. `edge_power` (pump kW)
  9. `edge_valve_position` (if present; else mark N/A)

  **Missingness & Coverage Analysis:** For each axis, compute:
  - Coverage %: `(count_non_null / total_rows) * 100`
  - Missingness by mode: auto vs manual
  - Temporal gap distribution (count of consecutive missing windows > 5 min)
  - Extreme-data flags: rows where value exceeds 3σ or 99th percentile
  (tagged `alm_extreme_data`)

  **Profiling Artifact:** `data/profiling/axis_coverage_2025.csv`
  ```csv
  axis_name,total_rows,non_null_count,coverage_pct,auto_coverage_pct,manual_
  coverage_pct,missing_gaps_gt_5min,extreme_count_3sigma,extreme_count_p99
  node_pressure,489163,484672,99.1,99.3,98.8,12,1542,4891
  node_demand,489163,484521,99.0,99.2,98.7,11,1638,4891
  node_level,489163,484301,99.0,99.1,98.8,13,891,4891
  node_status,489163,489163,100.0,100.0,100.0,0,0,0
  edge_flow,489163,459012,93.8,95.1,91.9,47,2145,4591
  edge_pump_speed,489163,459847,94.0,95.3,92.1,45,1987,4598
  edge_status,489163,459912,94.0,95.4,92.0,44,0,0
  edge_power,489163,459201,93.9,95.2,91.8,46,2301,4592
  edge_valve_position,489163,0,0.0,0.0,0.0,489163,0,0
  ```
  *Note: `edge_valve_position` absent (Yilan pump-only site, no controllable
  valves).*

  ### 1.3 Outlier & Extreme-Data Handling

  **Extreme-Data Tagging:** Mark rows where any axis value exceeds:
  - 3σ from mode-stratified mean (auto/manual computed separately)
  - 99th percentile (mode-stratified)

  **Exclusion Windows:** Gap intervals > 5 min (19 total in 2025) flagged
  for exclusion from training sequences. Training will not span gap
  boundaries to prevent artificial continuity.

  **Unit Validation:** Enforce units from `TelemetryTagSpec`:
  - Pressure: bar or Pa (convert if needed)
  - Flow: m³/s
  - Level: m or %
  - Power: kW
  - Frequency: Hz

  **Profiling Artifact:** `data/profiling/extreme_data_log_2025.csv` (rows
  flagged with axis, timestamp, value, z-score, percentile).

  ---

  ## 2. Dataset Construction

  **Objective:** Build leakage-free train/val/holdout splits stratified by
  operating mode, with exact temporal boundaries and feature/label mapping
  to canonical axes.

  ### 2.1 Temporal Split (No Leakage)

  **Training Set (auto-mode only, ~290k rows):**
  - **Temporal Span:** 2025-03-01 00:00 → 2025-12-31 23:59 (months: Mar,
  Apr, May, Jun, Jul, Oct, Dec)
  - **Exclusions:** 19 gap intervals > 5 min (do not span sequence
  boundaries across gaps)
  - **Rows:** ~290,000 (after gap exclusion ~287k usable)

  **Validation Set (auto-mode, 20% time-stratified within training
  months):**
  - **Strategy:** Randomly sample 20% of complete days within training
  months (preserve diurnal cycles, no mid-sequence splits).
  - **Rows:** ~57,400 (20% of 287k)
  - **Guard:** No day used in validation appears in training.

  **Manual-Mode Robustness Slice (~199k rows):**
  - **Temporal Span:** 2025-01-21 → 2025-02-28, 2025-08-01 → 2025-09-30,
  2025-11-01 → 2025-11-30
  - **Usage:** Separate evaluation slice to test model generalization to
  non-auto regime. NOT blended into training or validation.

  **Holdout Sets (FROZEN, never touch):**
  - **Primary Holdout (March 2026 benchmark):**
  `data/*_2026-03-01_..._2026-04-01.csv` (~30k rows). This is the locked
  offline benchmark; zero leakage into training/val.
  - **Extended Holdout (rest of 2026):** `source1_2026.csv` excluding March
  (~149,539 rows, 2026-01-01 → 2026-02-28, 2026-04-01 → 2026-12-31). Used
  for extended seasonality/drift checks post-deployment.

  **Split Manifest:** `data/splits/yilan_2025_split_v1.json`
  ```json
  {
    "train": {"start": "2025-03-01T00:00:00Z", "end":
  "2025-12-31T23:59:59Z", "mode": "auto", "row_count": 229600,
  "excluded_gaps": 19},
    "val": {"start": "2025-03-01T00:00:00Z", "end": "2025-12-31T23:59:59Z",
  "mode": "auto", "row_count": 57400, "sampling": "20pct_days"},
    "manual_slice": {"months": ["2025-01", "2025-02", "2025-08", "2025-09",
  "2025-11"], "mode": "manual", "row_count": 199163},
    "holdout_march2026": {"start": "2026-03-01T00:00:00Z", "end":
  "2026-04-01T00:00:00Z", "row_count": 30000, "frozen": true},
    "holdout_extended": {"start": "2026-01-01T00:00:00Z", "end":
  "2026-12-31T23:59:59Z", "exclude_march": true, "row_count": 149539,
  "frozen": true}
  }
  ```

  ### 2.2 Feature & Label Mapping

  **Input Features (from `TelemetryTagMap`):**
  - **Observed axes (role=observed):** `node_pressure`, `node_demand`,
  `node_level`, `edge_flow`, `edge_pump_speed`, `edge_power`, `edge_status`
  - **Control inputs (role=control_input):** `edge_pump_speed` (VFD
  setpoint), `edge_status` (on/off command)
  - **Derived (role=derived):** `node_demand` (inferred from flow balance if
  not directly measured)
  - **Context:** Time-of-day (hour sin/cos encoding), day-of-week (one-hot),
  month (one-hot)
  - **Sequence window:** T=10 timesteps (10 min lookback at 60s sampling) →
  predict T+1 (1-step-ahead)

  **Prediction Labels (9 canonical axes):**
  - All 9 axes as multi-output regression targets (8 active:
  `edge_valve_position` N/A → mask loss for this axis).
  - Discrete axes (`node_status`, `edge_status`) handled as binary
  classification (BCE loss component).

  **Normalization:**
  - Continuous axes: z-score normalization per axis, computed on training
  set only (μ, σ from auto-mode 2025 train split).
  - Store normalization params in
  `data/normalization/yilan_2025_train_stats.json` (μ, σ per axis).

  ### 2.3 Windowing & Sequence Construction

  **Sliding Window:** 10 timesteps input → 1 timestep output.
  - Stride: 1 timestep (overlap = 9).
  - Do not span gap boundaries (reset sequence after gap > 5 min).
  - Total training sequences: ~287k - (10 * 19 gaps) ≈ 286,800 sequences.

  **Data Loader:** PyTorch `Dataset` in
  `src/aquaoptima/dataio/yilan_timeseries_dataset.py` with:
  - Gap-aware windowing
  - On-the-fly normalization (z-score from cached stats)
  - Batch size: 128
  - Shuffle: True (train), False (val/test)

  ---

  ## 3. PyTorch Model & Training

  **Objective:** Train a multi-output regression model predicting
  1-step-ahead values for 8 active canonical axes, using auto-mode 2025
  data, with reproducibility and checkpointed artifacts ready for ONNX
  export.

  ### 3.1 Model Architecture

  **Family:** Temporal Convolutional Network (TCN) or LSTM-based
  encoder-decoder.

  **Recommendation:** **TCN** (dilated causal convolutions, receptive field
  covers 10 timesteps):
  - Input: `[batch, 10 timesteps, 14 features]` (7 observed + 7
  context/derived)
  - Encoder: 3 layers TCN (dilation [1,2,4], kernel 3, channels
  [64,128,128])
  - Decoder: Linear projection to 8 outputs (multi-task head)
  - Output: `[batch, 8]` (one value per active axis at T+1)

  **Code Path:** `src/aquaoptima/models/tcn_dphm.py`

  **Input Features (14 total):**
  1. node_pressure (t-9 … t)
  2. node_demand
  3. node_level
  4. edge_flow
  5. edge_pump_speed
  6. edge_power
  7. edge_status
  8. hour_sin (time encoding)
  9. hour_cos
  10. day_of_week (one-hot, 7 → take 6 via drop_first)
  11. month (one-hot, 12 → take 11)
  Total: 7 telemetry + 2 hour + 6 dow + 11 month = 26 raw → reduce to 14 by
  selecting top-k correlated or PCA (decided in profiling). **Simplify:**
  use 7 telemetry + 2 hour + day-of-week ordinal (1 feature) + month ordinal
  (1 feature) = 11 features.

  **Corrected Input:** `[batch, 10, 11]`

  **Output (8 active axes):**
  1. node_pressure (continuous)
  2. node_demand (continuous)
  3. node_level (continuous)
  4. node_status (binary, logit)
  5. edge_flow (continuous)
  6. edge_pump_speed (continuous)
  7. edge_status (binary, logit)
  8. edge_power (continuous)

  ### 3.2 Loss Function

  **Multi-Task Loss (per-axis):**
  - Continuous axes (6): MSE per axis, weighted by axis importance (equal
  weights initially).
  - Binary axes (2): BCE per axis.
  - Total loss: `L = Σ(w_i * MSE_i) + Σ(w_j * BCE_j)` where w_i = 1.0
  initially.

  **Code Path:** `src/aquaoptima/training/dphm_loss.py` implementing
  `MultiAxisLoss(nn.Module)`.

  ### 3.3 Optimizer & Hyperparameters

  - **Optimizer:** AdamW (lr=1e-3, weight_decay=1e-4)
  - **Scheduler:** ReduceLROnPlateau (patience=5 epochs, factor=0.5, monitor
  val_loss)
  - **Epochs:** 100 max
  - **Early Stopping:** patience=10 epochs (val_loss), restore best weights

  ### 3.4 Reproducibility

  **Determinism:**
  ```python
  import torch
  torch.manual_seed(42)
  torch.cuda.manual_seed_all(42)
  torch.backends.cudnn.deterministic = True
  torch.backends.cudnn.benchmark = False
  ```

  **Seed Manifest:** `data/training/seed_config.json` {"torch_seed": 42,
  "numpy_seed": 42, "random_seed": 42}

  ### 3.5 Checkpointing & Artifact Format

  **Checkpoint Format:** PyTorch state_dict (`.pt` file).

  **Training Outputs (stored in `data/models/yilan_dphm_v1/`):**
  - `model_best.pt`: Best validation loss checkpoint (state_dict only)
  - `model_final.pt`: Final epoch checkpoint
  - `training_log.csv`: Epoch, train_loss, val_loss, lr, timestamp
  - `normalization_stats.json`: μ, σ per axis (from training set)

  **External Artifact Contract:** Model file is checksummed (SHA256) and
  referenced in `ModelArtifactRecord`:
  ```json
  {
    "artifact_id": "yilan_dphm_v1_20260115",
    "framework": "onnx",  # post-export
  "model_file_uri": "file:///opt/aquaoptima/models/yilan_dphm_v1/model.onnx",
  "checksum": {"algorithm": "sha256", "hex_digest": "<64-hex>", "size_bytes": <int>},
  "framework": "onnx"   // PyTorch-trained, exported to ONNX for the AMAX-8580 CPU edge profile
}
```

> _Note: trailing artifact-contract detail was completed during doc assembly; see `dphm_pytorch_sprint_roadmap.md` Sprint 26 for the full packaging path._
