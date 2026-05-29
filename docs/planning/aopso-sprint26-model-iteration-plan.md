# AOPSO Sprint 26 — dPHM Model Iteration & Re-Gate

> **Project:** Pump Station Optimizer Lite (Plane: AOPSO). Follows Sprint 25 (offline eval, GATE=FAIL).
> **Status:** Planned (execution-ready). **Blocks:** packaging (now Sprint 27) until this sprint's re-gate PASSes.
> **Safety:** `evaluation_mode=offline_only`, `write_path=none`, `influences_control=false`, `site_integration_allowed=false`. Existing MVP PLC/PAC baseline control preserved.

## Why this sprint exists

Sprint 25 scored the trained dPHM model against the **LOCKED March 2026 benchmark (44,469 rows)** and the acceptance gate returned **FAIL**. The diagnostic dig found that the failure is **three labeling/plumbing defects plus one genuine modeling finding** — not a single problem. This sprint fixes the defects and attacks the genuine finding, then re-runs the Sprint 25 harness to re-gate.

The committed Sprint 25 scorecard (`data/eval/yilan_dphm_v1/march2026_scorecard.json`) is the evidence baseline for this work.

---

## Defect log (root-cause findings from the Sprint 25 dig)

### DEFECT 1 — `node_status` is mislabeled (caused the 0.67 "accuracy") 🔴
- `node_status` is mapped (in `src/aquaoptima/dataio/yilan_axis_map.py`) to **`tb_system_head`**, which is a **continuous** hydraulic head (range ~7.2–24.0 m, 10,102 unique values), **not a binary status**.
- It is force-listed in `BINARY_AXES`, so evaluation de-normalizes the model output back to ~18 m and thresholds at 0.5 → the "true class" is **always 1** → accuracy is meaningless (0.6677).
- **Fix:** reclassify `node_status`↔`tb_system_head` as a **continuous** axis (treat like pressure/level), OR drop it. It is not a real binary signal in this site's data.

### DEFECT 2 — `edge_status`'s 0.988 "pass" is hollow (class imbalance) 🟠
- `P_1531A_status` (the real pump-on/off signal) is **on 99.85%** of the time in March 2026.
- A trivial "always-on" predictor scores **0.9985**; the model's 0.988 is therefore *below* the do-nothing rate. Accuracy is the wrong metric for a 99.85%-imbalanced signal.
- **Fix:** for any genuine binary axis, gate on **balanced accuracy / F1 / MCC** (not raw accuracy), or drop the axis as a target if it carries no learnable signal.

### DEFECT 3 — train/eval decode mismatch on binary axes 🟠
- The model trains binary axes with **`BCEWithLogitsLoss`** (outputs are **logits**).
- `evaluation.py` decodes binary outputs as **z-score-normalized continuous** values (`p·σ+μ`) instead of applying **`sigmoid`**. Wrong inverse transform.
- Masked by Defects 1 & 2, but real.
- **Fix:** decode genuine BCE axes via `sigmoid(logit) ≥ 0.5`. (May become moot if both fake-binary axes are reclassified/dropped.)

### GENUINE MODELING FINDING (the real verdict — not a bug) 🔴
- On the 6 continuous axes, the **MVP persistence baseline beats dPHM by 5–10× MSE on every axis (0/6 won)**.
- Root cause: the model was asked to predict the **absolute next-step value** on 60-second-cadence telemetry, where "next ≈ now". Persistence (last-observed-value) is a brutally strong baseline for that task.
- **A forecaster that cannot beat persistence has no product value** — you would ship the one-line baseline instead.

---

## Sprint 26 scope (execution-ready)

**Component owner:** core model + training + evaluation (`src/aquaoptima/{models,training,dataio}`). No edge, no contracts writes, no ONNX.

### Tasks
1. **Reframe the prediction target to residual-over-persistence** (`Δ = value[t+h] − value[t]`). The model predicts the *change*; final prediction = `last_value + Δ̂`. This forces the model to beat persistence by construction (persistence ≡ predicting Δ=0). Add an inverse-transform in eval so the scorecard still reports absolute-value MSE/MAE comparable to Sprint 25.
2. **Fix the axis taxonomy** (`yilan_axis_map.py`): reclassify `node_status`(`tb_system_head`) as **continuous**; either drop `edge_status` as a target or keep it with an imbalance-aware metric. Update `BINARY_AXES`/`CONTINUOUS_AXES` accordingly and regenerate normalization stats if axis set changes.
3. **Fix binary decode** in `evaluation.py` (sigmoid for true BCE axes) and **switch binary gating to balanced-accuracy/F1**.
4. **Add a multi-step-ahead eval option** (e.g. h = 1, 5, 15, 30 min) reported alongside h=1 — persistence decays as horizon grows, so this is where a model legitimately wins. Decide the product-relevant horizon with the user.
5. **Retrain** on the full auto-mode 2025 split with the residual target; **re-run the Sprint 25 harness** against the LOCKED March 2026 benchmark.
6. **Update the scorecard + gate**; record the new verdict honestly (PASS or FAIL).

### Acceptance criteria
- [ ] `node_status` no longer treated as binary (reclassified continuous or removed); no axis thresholds a continuous head value.
- [ ] Binary gating (if any binary axis remains) uses balanced-accuracy/F1, not raw accuracy.
- [ ] Residual-over-persistence target implemented; eval reports absolute-value metrics comparable to Sprint 25 **and** explicit dPHM-vs-persistence deltas.
- [ ] Multi-horizon eval (≥1 horizon beyond h=1) reported.
- [ ] Re-gate run against the LOCKED March 2026 holdout (still read-only, isolation re-asserted); scorecard committed.
- [ ] Harness/unit tests pass; no edge/contracts/ONNX changes; offline-only.

### Stop conditions
- STOP if residual-target model **still loses to persistence on the product-relevant horizon** → escalate: the value proposition is likely **anomaly/health + efficiency advisory**, not next-step forecasting (pivot the modeling objective, not just the target).
- STOP if reclassifying axes changes the active-axis set in a way that invalidates Sprint 23 normalization → regenerate stats first.

### Re-gate decision
- **PASS** → unblock packaging (Sprint 27).
- **FAIL** → do not package; escalate to objective pivot (anomaly/efficiency) before any further forecasting work.

---

## Tooling note (numpy / graphify / gitnexus for this iteration)

- **numpy / pandas — YES, core.** The entire fix is numerical: residual-target construction (`Δ = x[t+h]−x[t]`), inverse transform, persistence baseline, per-axis MSE/MAE/balanced-accuracy, normalization regen. This is exactly numpy/pandas (+ torch) work. No new tool needed.
- **graphify — NO (for the modeling).** Graphify builds *knowledge graphs from documents/code*. It does not help time-series forecasting skill. ⚠️ Do not confuse it with the **water-network topology graph** (nodes/pipes/pumps) that a GNN encoder uses — that graph is real and relevant to dPHM, but it comes from the EPANET/site topology, **not** from graphify. The repo already has `src/aquaoptima/models/graph_encoder.py` for that.
- **gitnexus — NO (for the modeling).** It's a *code* graph for navigating the codebase. Useful for a developer orienting in the repo; irrelevant to whether the model beats persistence.

**Bottom line:** the model-iteration work is numpy/pandas/torch. Graphify and gitnexus are dev-orientation tools, not modeling tools, and add nothing to the forecasting-skill problem.

> _Roadmap renumbering note: the original `aopso-sprints-23-27` roadmap listed Sprint 26 = packaging and Sprint 27 = robustness. This model-iteration sprint is inserted as the new Sprint 26 (it must precede packaging); packaging shifts to Sprint 27 and manual-mode robustness to Sprint 28._
