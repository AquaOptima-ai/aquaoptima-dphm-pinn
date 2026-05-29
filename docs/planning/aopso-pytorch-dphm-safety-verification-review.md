# AOPSO PyTorch dPHM Roadmap — Safety & Verification Review (Sprints 23–27)

> **Project:** Pump Station Optimizer Lite (AOPSO). Offline-only; preserves existing MVP PLC/PAC baseline control (no removal); no new write path.

  **Reviewer:** OT Safety & Verification
  **Product:** AquaOptima dPHM-PINN (aquaoptima-dphm-pinn, main @ 9453b9f)
  **Site:** Yilan 溪南系統 (P_1531A-D)
  **Review Date:** 2026-01-15
  **Documents Reviewed:** Data Profiling Plan
  (`dphm_pytorch_training_profiling_plan.md`), Execution-Ready Sprint Roadmap
  (`dphm_pytorch_sprint_roadmap.md`)
  **Mode under review:** Shadow / advisory-only read-only sidecar (NO
  control-loop closure). MVP v1 retains exclusive control of the PLC/PAC/VFD
  path.

  ---

  ## 1. Safety Boundary Compliance: NON-NEGOTIABLE READ-ONLY VERIFICATION

  ### 1.1 Overall Assessment: COMPLIANT

  **Finding:** All plan elements preserve the non-negotiable safety
  boundary. The dPHM system remains a **shadow-mode / advisory-only
  read-only sidecar** with zero control-loop closure capability. No sprint
  (A–E) introduces live OT binding, PLC/PAC/SCADA write, command emission,
  setpoint output, or control-loop closure.

  **Verification Points:**
  - ✅ **No PLC/PAC/SCADA write capability:** Planning explicitly states "NO
  control-loop closure," "NO command emission," "NO setpoint output."
  - ✅ **No actuation pathway:** Architecture document confirms dPHM
  produces "evidence/advisory, never actuation." Legacy MVP v1 controls the
  PLC/PAC/VFD path; dPHM is isolated.
  - ✅ **Edge runtime contract preserved:** Edge inference runtime
  (`src/aquaoptima/edge/`) imports only from shared contracts; no write
  primitives exposed.
  - ✅ **Training is offline:** All training activities consume CSV files in
  `data/` directory; no live telemetry connection, no OT network I/O.
  - ✅ **Packaging is inert (Sprint 26):** The ONNX artifact +
  `DeploymentPackageManifest` carry all 7 `SafetyFlagSet` flags = True
  (shadow/advisory-only, no OT bind, no write, no command/setpoint, no
  control-loop closure). The artifact is loaded read-only by the edge shadow
  runtime.
  - ✅ **Anomaly evidence is advisory (Sprint 27):** Anomaly records contain
  no `action`/`setpoint`/`command` field; an explicit test
  (`test_anomaly_evidence_advisory_only.py`) enforces this. Outputs inform
  operational guidance only — never automated control handoff.

  ### 1.2 Wording Corrections Required: MINOR

  **Issue 1 (Sprint 23 Safety Boundary statement):**
  Current text: "Read-only operation: No PLC/OT interaction, no model
  inference, no control output."

  **Problem:** The phrase "no model inference" is misleading—Sprint 23 does
  not involve inference, but future sprints will run inference in shadow
  mode. This could create confusion about whether inference itself violates
  the boundary.

  **Corrected phrasing:**
  ```
  Read-only operation: No PLC/OT write capability. Scripts consume static
  CSV files only.
  No SCADA/Modbus/OPC-UA calls, no live telemetry binding, no setpoint
  emission.
  Model inference (future sprints) will operate in shadow mode, producing
  advisory outputs only,
  with no pathway to actuate pumps, valves, or control loops.
  ```

  **Issue 2 (Dataset Construction § 2.2 "Control inputs"):**
  Current text: "Control inputs (role=control_input): edge_pump_speed (VFD
  setpoint), edge_status (on/off command)"

  **Problem:** The words "setpoint" and "command" imply dPHM *issues*
  control signals. In reality, dPHM *observes* these as historical telemetry
  from the legacy controller.

  **Corrected phrasing:**
  ```
  Observed control state (role=observed_control): edge_pump_speed
  (historical VFD setpoint from legacy controller),
  edge_status (historical on/off state). These axes are INPUTS to the dPHM
  model, reflecting past control decisions
  made by the operational PLC. The dPHM model does NOT generate or emit
  control signals.
  ```

  **Issue 3 (Training Plan § 3.5 "External Artifact Contract"):**
  The example was truncated mid-JSON block ("model_file_uri":
  "file:///opt/aquaoptima/models/yilan_dphm").

  **Resolution:** The artifact-contract example has been completed during doc
  assembly (see Training Plan § 3.5 and Sprint 26 of the roadmap). The
  completed record sets `framework="onnx"`, references an external
  checksummed `model.onnx` via `model_file_uri`, and is loaded **read-only**
  by the edge runtime for inference. It NEVER writes inference results back to
  any control interface. ✅ Resolved.

  **Issue 4 (Sprint 26 wording guard):** Ensure Sprint 26 documentation never
  describes the edge runtime as "applying," "actuating," or "sending" model
  outputs. Approved phrasing: the runtime "produces advisory shadow
  predictions/evidence consumed by humans." ✅ Roadmap Sprint 26 Safety
  Boundary already uses advisory-only phrasing.

  ---

  ## 2. Data-Leakage Review: COMPLIANT WITH ADVISORY

  ### 2.1 Temporal Split Boundaries: VERIFIED

  **March 2026 Holdout Protection:**
  - ✅ Training set: 2025-03-01 → 2025-12-31 (auto-mode only)
  - ✅ Validation set: 20% day-stratified sample *within* training temporal
  range
  - ✅ Holdout frozen: `data/*_2026-03-01_..._2026-04-01.csv` (~30k rows)
  explicitly excluded from train/val/manual splits
  - ✅ Extended holdout: Rest of 2026 (149,539 rows) also excluded
  - ✅ **No 2026 data enters training.** The March 2026 benchmark is a FROZEN
  holdout used only by Sprint 25 evaluation and the Sprint 26 parity sample;
  neither path feeds gradients back into the model.

  **Gate:** The split manifest (`data/splits/yilan_2025_split_v1.json`) MUST
  be version-controlled and checksummed. Any modification to split dates
  requires re-verification.

  **Recommended Verification Command (Sprint 23 Acceptance):**
  ```bash
  # Assert no 2026 data in training split
  python -c "
  import json
  with open('data/splits/yilan_2025_split_v1.json') as f:
      splits = json.load(f)
  assert splits['train']['end'] < '2026-01-01', 'Train set leaks into 2026'
  assert splits['val']['end'] < '2026-01-01', 'Val set leaks into 2026'
  assert splits['holdout_march2026']['frozen'] is True, 'Holdout not marked
  frozen'
  print('✓ No 2026 leakage detected')
  "
  ```

  ### 2.2 Auto/Manual Stratification: VERIFIED

  **Finding:** The plan correctly separates auto-mode (training target) from
  manual-mode (robustness slice).

  - ✅ Training uses **only** auto-mode months (Mar, Apr, May, Jun, Jul,
  Oct, Dec 2025).
  - ✅ Manual-mode months (Jan, Feb, Aug, Sep, Nov 2025) carved into
  separate evaluation slice.
  - ✅ No manual-mode data blended into training or validation sets.

  **Leakage Risk:** Cross-regime contamination prevented by explicit mode
  detection logic (`optimizer_enabled`/`auto_mode_active` flags). This
  stratification prevents regime leakage — the model is never shown
  manual-override behavior during training, so the manual slice remains a true
  out-of-regime test.

  **Advisory:** Sprint 27 (Sprint 27 — Manual-Mode Robustness Evaluation) MUST
  verify that manual-slice evaluation does NOT trigger model retraining or
  weight updates. The manual slice is **test-only**; any performance
  degradation on manual-mode data should inform *operational guidance* (e.g.,
  "dPHM advisory unreliable during manual overrides"), not automated control
  handoff. The roadmap's `test_manual_slice_test_only.py` enforces this. ✅

  ### 2.3 Gap Handling: VERIFIED

  **Finding:** 19 temporal gaps (>5 min) flagged and excluded from sequence
  windowing.

  - ✅ Training sequences do NOT span gap boundaries (prevents artificial
  continuity).
  - ✅ Gap intervals serialized to `data/profiling/gap_intervals_2025.json`
  for reproducibility.

  **Gate:** Sprint 23 acceptance MUST confirm gap count = 19. Deviation
  requires root-cause analysis (data corruption, parsing error, or
  legitimate data-quality change).

  ---

  ## 3. PyTorch Packaging Review: OPTION A APPROVED, OPTION B DEFERRED

  ### 3.1 Option A (PyTorch → ONNX Export): APPROVED

  **Rationale:**
  - ✅ **Edge validator compliance:** AMAX-8580 CPU profile already
  advertises `'onnx'` (and `'tflite'`) in `supported_model_frameworks`. No
  edge-profile schema change required.
  - ✅ **Determinism:** ONNX CPU runtime (onnxruntime) is deterministic,
  hardware-agnostic, well-tested.
  - ✅ **Zero contract extension risk:**
  `validate_deployment_package_for_edge` accepts `framework='onnx'` without
  modification. Sprint 26 asserts `validate_deployment_package_for_edge(...)
  .accepted is True` on the **UNCHANGED** default CPU profile.
  - ✅ **Rejection guardrails preserved:** Sprint 26's negative tests confirm
  the same validator still **rejects** `framework='pytorch'` and any
  `cuda`/`tensorrt`/`jetson`/`orin`/`arm64`/`aarch64` accelerator/architecture
  token. Packaging the model does NOT weaken rejection — that is the central
  safety property of Option A.
  - ✅ **No inline weights:** `ModelArtifactRecord` references an external
  checksummed `.onnx` (SHA256 + size); weights are never inlined into the
  manifest.

  **Required Safety Gate (Sprint 26 / Sprint 26):**
  Before packaging for edge deployment, a **numerical parity test** MUST
  pass:
  ```python
  # Parity test pseudocode
  holdout_sample = load_holdout_sample(n=1000)  # March 2026, first 1000 rows
  pytorch_output = tcn_dphm_model(holdout_sample)
  onnx_output = onnx_runtime.run(onnx_model, holdout_sample)
  max_abs_diff = np.abs(pytorch_output - onnx_output).max()
  assert max_abs_diff < 1e-4, f"ONNX parity failure: max diff {max_abs_diff}"
  ```

  **Stop Condition:** If parity test fails (max abs diff ≥ 1e-4), **BLOCK
  packaging**. Investigate ONNX export opset version, quantization
  artifacts, or operator compatibility. Do NOT deploy non-equivalent models.

  **`framework` field requirement:** For Option A, `ModelArtifactRecord
  .framework` MUST be `"onnx"`. A `"pytorch"` value would (correctly) be
  rejected by the default CPU profile and indicates an Option-A configuration
  error.

  ### 3.2 Option B (Native PyTorch/TorchScript Edge Artifact): DEFERRED, CONDITIONAL APPROVAL

  **Status:** Correctly marked as **Backlog** (deferred alternative; not the
  default path).

  **Required Prerequisites for Option B activation (ALL must hold):**
  1. **Edge-profile schema extension:** Add `'pytorch'` to
  `supported_model_frameworks` in the AMAX-8580 hardware profile — its own
  contracts-change PR.
     - **Safety gate:** This schema change MUST go through contracts review
  + edge validator integration test + deployment dry-run.
     - **Verification command:**
       ```bash
       python -m aquaoptima_contracts.edge.package_validator \
         --hardware-profile amax8580_cpu \
         --model-artifact model.pt \
         --framework pytorch
       # Must pass validation OR fail with explicit "pytorch not supported"
       error (not silent acceptance)
       ```

  2. **Libtorch CPU runtime integration:** Add libtorch as edge dependency,
  audit for non-determinism (e.g., TorchScript JIT optimizations, CPU
  threading).
     - **Safety gate:** Determinism test on AMAX-8580 hardware (not just dev
  laptop). Run same input 100 times, assert bitwise-identical outputs.

  3. **Accelerator/architecture rejection preserved:** Confirm that even with
  `'pytorch'` in the profile, the edge validator still **rejects**
  GPU/TPU/FPGA artifacts and `cuda`/`tensorrt`/`jetson`/`orin`/`arm64`/
  `aarch64` tokens if the hardware profile is CPU-only. Adding `'pytorch'`
  must NOT weaken any other rejection.
     - **Anti-regression test:**
       ```bash
       # Attempt to package a CUDA model for CPU-only hardware
       python -m aquaoptima_contracts.edge.package_validator \
         --hardware-profile amax8580_cpu \
         --model-artifact model_cuda.pt \
         --framework pytorch
       # Expected: ERROR "CUDA artifact rejected for CPU-only profile"
       ```

  4. **Dedicated safety review:** Option B requires its **own** safety &
  verification review sign-off before any edge deployment — it does not
  inherit this review's approval.

  **Advisory:** Option B introduces edge-runtime complexity. Unless
  PyTorch-native inference provides measurable latency/accuracy benefits
  over ONNX (quantified in a dedicated Backlog spike), prefer Option A for
  operational simplicity. Until all four prerequisites pass, `framework`
  remains `"onnx"` and Option A is the only approved path.

  ---

  ## 4. Planning-Sprint Gate: EXACT VERIFICATION COMMANDS

  ### 4.1 Current Sprint Deliverables

  **Assertion:** The planning sprint produces **ONLY** markdown files under
  `docs/planning/`. No production code, contracts, schemas, tests, or
  training code modified.

  **Git Verification Commands (run at sprint close):**

  ```bash
  # 1. Assert no changes outside docs/planning/
  git diff main --name-only | grep -v '^docs/planning/' && echo "FAIL:
  Production code touched" || echo "PASS: docs/planning/ only"

  # 2. List all new/modified files
  git diff main --name-status

  # Expected output (planning sprint):
  # A  docs/planning/dphm_pytorch_training_profiling_plan.md
  # A  docs/planning/dphm_pytorch_sprint_roadmap.md
  # A  docs/planning/dphm_pytorch_safety_verification_review.md

  # 3. Assert no changes to contracts
  git diff main --name-only | grep '^src/aquaoptima_contracts/' && echo
  "FAIL: Contracts modified" || echo "PASS: Contracts untouched"

  # 4. Assert no changes to edge runtime
  git diff main --name-only | grep '^src/aquaoptima/edge/' && echo "FAIL:
  Edge runtime modified" || echo "PASS: Edge runtime untouched"

  # 5. Assert no changes to training/model code
  git diff main --name-only | grep -E '^src/aquaoptima/(training|models|dphm|dataio|topology)/' && echo
  "FAIL: Core code modified" || echo "PASS: Core code untouched"
  ```

  **Gate:** If any command above outputs "FAIL," the planning sprint has
  violated its scope. Revert production-code changes and re-review.

  ### 4.2 Planning Artifacts Checklist

  **Required deliverables in `docs/planning/`:**
  - [x] `dphm_pytorch_training_profiling_plan.md` (Dataset construction,
  split strategy, normalization)
  - [x] `dphm_pytorch_sprint_roadmap.md` (Sprint 23–E breakdown, Option A/B
  decision, Plane recommendation)
  - [x] `dphm_pytorch_safety_verification_review.md` (this document)

  ---

  ## 5. Per-Sprint Verification Gates: CONCRETE STOP CONDITIONS REQUIRED

  ### 5.1 Sprint 23 (Sprint 23) Verification Gate: APPROVED

  **E2E Command (from roadmap):**
  ```bash
  python -m aquaoptima.dataio.yilan_profiler --input data/source1_2025.csv --output-dir data/profiling/
  python -m aquaoptima.dataio.split_builder --input data/source1_2025.csv --gaps data/profiling/gap_intervals_2025.json --output data/splits/yilan_2025_split_v1.json
  python -m aquaoptima.training.normalization --split-manifest data/splits/yilan_2025_split_v1.json --split-key train --output data/normalization/yilan_2025_train_stats.json
  pytest -q tests/dataio/test_yilan_split_no_leakage.py tests/dataio/test_yilan_dataset_windowing.py
  ```

  **Expected output verified:** Row counts, gap count, coverage %, test
  passage.

  **Stop Conditions (from roadmap):**
  - ✅ STOP if gap count ≠ 19
  - ✅ STOP if train/val date overlap
  - ✅ STOP if normalization stats contain NaN/inf

  **Additional Required Gate (not in roadmap):**
  ```bash
  # Checksum split manifest for reproducibility
  sha256sum data/splits/yilan_2025_split_v1.json > data/splits/yilan_2025_split_v1.json.sha256
  # Future sprints MUST verify checksum before training
  ```

  ### 5.2 Sprint 24 (Sprint 24) Verification Gate: APPROVED (now complete in roadmap)

  **Finding:** The roadmap now provides complete Sprint 24 detail: acceptance
  criteria, E2E smoke-train command, expected loss-decrease output, stop
  conditions, and a determinism check. Prior truncation resolved.

  **E2E Command (from roadmap):**
  ```bash
  python -m aquaoptima.training.dphm_trainer --config configs/yilan_dphm_v1.yaml \
    --split-manifest data/splits/yilan_2025_split_v1.json \
    --norm-stats data/normalization/yilan_2025_train_stats.json \
    --epochs 2 --subset-rows 5000 --checkpoint-dir data/models/yilan_dphm_v1/
  pytest -q tests/models/test_tcn_dphm_forward.py tests/training/test_dphm_loss.py \
           tests/training/test_train_smoke.py tests/architecture/test_no_edge_imports_in_core.py
  ```

  **Stop Conditions (from roadmap):**
  - ✅ STOP if forward-pass output shape ≠ `[batch, 8]`
  - ✅ STOP if smoke train loss does not decrease
  - ✅ STOP if loss diverges (NaN/inf or monotone increase)
  - ✅ STOP if any `aquaoptima.edge`/`aquaoptima_contracts.edge` import
  appears in core
  - ✅ STOP if two identical-seed CPU runs are not bitwise identical

  ### 5.3 Sprint 25 (Sprint 25) Verification Gate: APPROVED

  **E2E Command (from roadmap):**
  ```bash
  python -m aquaoptima.training.evaluation \
    --checkpoint data/models/yilan_dphm_v1/model_best.pt \
    --split-manifest data/splits/yilan_2025_split_v1.json \
    --norm-stats data/normalization/yilan_2025_train_stats.json \
    --holdout-key holdout_march2026 --baseline mvp_persistence \
    --output data/eval/yilan_dphm_v1/march2026_scorecard.json
  pytest -q tests/training/test_evaluation_harness.py \
           tests/training/test_acceptance_thresholds.py \
           tests/training/test_holdout_isolation.py
  ```

  **Stop Conditions (from roadmap):**
  - ✅ STOP if the March 2026 holdout intersects any train/val split
  (leakage).
  - ✅ STOP if the scorecard does not validate against the
  `ShadowRuntimeReport` shape.
  - ✅ STOP if the acceptance gate returns FAIL → do NOT package (Sprint 26
  blocked).
  - ✅ STOP if dPHM fails to beat the MVP baseline on the required axis count.

  **Safety note:** The `ShadowRuntimeReport` shape is used purely as a
  serialization target; producing one offline does not bind it to any live
  runtime. Acceptance thresholds gate packaging — no model proceeds to Sprint
  D without a PASS.

  ### 5.4 Sprint 26 (Sprint 26) Verification Gate: APPROVED — primary safety gate

  **E2E Command (from roadmap):**
  ```bash
  python -m aquaoptima.training.onnx_export --checkpoint data/models/yilan_dphm_v1/model_best.pt \
    --output data/models/yilan_dphm_v1/model.onnx --opset 17
  python -m aquaoptima.training.onnx_parity --checkpoint data/models/yilan_dphm_v1/model_best.pt \
    --onnx data/models/yilan_dphm_v1/model.onnx --holdout-sample 1000 \
    --report data/packages/yilan_dphm_v1/parity_report.json
  python -m aquaoptima_contracts.edge.package_builder --onnx data/models/yilan_dphm_v1/model.onnx \
    --framework onnx --hardware-profile amax8580_cpu \
    --out data/packages/yilan_dphm_v1/deployment_package_manifest.json
  pytest -q tests/training/test_onnx_parity.py tests/contracts/test_edge_package_accept.py \
           tests/contracts/test_edge_package_reject.py
  ```

  **Stop Conditions (from roadmap):**
  - ✅ STOP / BLOCK if torch-vs-ONNX parity max abs diff ≥ 1e-4.
  - ✅ STOP if `validate_deployment_package_for_edge(...).accepted` is not
  True — fix the manifest, do NOT edit the validator/profile to force
  acceptance.
  - ✅ STOP if any safety flag is not True, `package_id`s mismatch, or
  `schema_family != "manifest"`.
  - ✅ STOP if negative tests stop rejecting `pytorch`/`cuda`/`aarch64` —
  rejection guardrails must never regress.
  - ✅ STOP if packaging requires editing the edge profile to advertise
  `pytorch` — that is Option B, route to Backlog with its own contracts change
  + verification + safety review.

  **Safety note:** This is the most safety-critical sprint. Approval is
  contingent on the validator and AMAX-8580 profile remaining **byte-unchanged**
  (verified via `git diff`) and on the parity gate + rejection negative-tests
  being GREEN.

  ### 5.5 Sprint 27 (Sprint 27) Verification Gate: BACKLOG (not execution-ready)

  **Finding:** Correctly marked **Backlog / Candidate**. Not to be promoted to
  Planned without an explicit product decision after Sprint 26 ships.

  **Stop Conditions (from roadmap):**
  - ✅ STOP (by design) until Sprints C and D are accepted.
  - ✅ STOP if any anomaly-evidence record gains an action/setpoint/command
  field (advisory-only is mandatory).
  - ✅ STOP if manual-slice evaluation mutates model weights (test-only
  violation).

  ### 5.6 Sprint-Chaining Advisory

  **Finding:** Roadmap correctly marks Sprints B–E as Backlog → Candidate,
  contingent on prior-sprint acceptance, with Sprint 23 as the only "Planned
  next."

  **Advisory:** Do NOT chain multiple model/safety sprints unattended. Each
  sprint gate MUST include:
  1. An automated verification command (non-interactive, exit code 0 = pass).
  2. A human review checkpoint (analyst/safety reviewer sign-off).
  3. Explicit STOP conditions (numerical thresholds, error patterns).

  **Recommendation:** After Sprint 23 acceptance, hold a **gate-review
  meeting** before marking Sprint 24 as "Planned." Review: Sprint 23 profiling
  artifacts (coverage %, gap analysis); data-quality red flags (extreme
  missingness, drift); and training hyperparameters informed by profiling
  (batch size, sequence length, axis weighting). Repeat a gate review between
  every subsequent sprint (B→C→D), and require a dedicated product +
  safety decision before promoting Sprint 27 off the Backlog. Specifically, do
  NOT run Sprint 25 (evaluation) and Sprint 26 (packaging) back-to-back without
  a human confirming the Sprint 25 acceptance gate returned PASS, and do NOT
  run any safety-relevant sprint (D especially) unattended.

  ---

  ## Summary of Findings

  | Section | Verdict | Notes |
  |---------|---------|-------|
  | 1. Safety boundary | COMPLIANT | 3 minor wording fixes; Issue 3 resolved. No OT bind / write / command / setpoint / control-loop closure in any sprint. |
  | 2. Data leakage | COMPLIANT | March 2026 frozen; no 2026 data in training; auto/manual stratification prevents regime leakage. |
  | 3. PyTorch packaging | OPTION A APPROVED | torch→ONNX keeps edge validator GREEN, profile UNCHANGED, rejection preserved. Option B deferred (own contracts change + verification + safety review). |
  | 4. Planning-sprint gate | COMPLIANT | Only `docs/planning/` changed; exact git verification commands provided. |
  | 5. Per-sprint gates | APPROVED | Every sprint A–D has a runnable verification command + stop condition; E is Backlog. No unattended safety/model chaining. |

  All identified items are advisories or minor wording corrections; none is a
  blocker. Option A (PyTorch → ONNX export) is approvable as the default
  edge-artifact path.

  VERDICT: APPROVED
