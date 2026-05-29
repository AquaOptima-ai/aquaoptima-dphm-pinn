# AquaOptima Pump Station Optimizer Lite — Health & Efficiency Advisory  
## Research Report for a Single Legacy Pump Station: Yilan, Taiwan  
### Offline-Only Evidence Product: Pillar A Health Detection + Pillar B Efficiency Advisory

---

## Executive Summary

AquaOptima Pump Station Optimizer Lite should no longer be framed as a short-horizon telemetry forecasting product. That direction was tested twice, independently and honestly, against the locked March 2026 Yilan holdout dataset. It failed both times. In Sprint 25, a learned dPHM forecasting model failed to beat trivial persistence on all 6 continuous axes at a 60-second horizon. In Sprint 26, after defect fixes and a more appropriate residual-over-persistence target at a 15-minute horizon, the model again failed to beat persistence on all 8 axes. The conclusion is not that the implementation was poor; the conclusion is that minute-cadence pump station telemetry is highly autocorrelated, so “the next value is the last value” is an extremely strong baseline.

The correct pivot is therefore to stop competing with persistence where persistence is structurally advantaged. Instead, the product should target two areas where a learned or statistical model can provide value that persistence cannot:

1. **Pillar A — Health / Anomaly Detection**  
   Learn the normal multivariate operating envelope of the pump station across flow, power, speed, pressure, level, demand, pump status, and hydraulic head. Flag abnormal combinations, efficiency decay, sensor drift, incipient equipment problems, and abnormal operating regimes. Persistence has no memory of what “normal” means over seasons, operating modes, or joint sensor relationships.

2. **Pillar B — Efficiency Advisory / Differentiable Pump Learning**  
   Learn or estimate the efficient operating envelope: for a given demand, hydraulic head, tank level, and pressure condition, identify historically realized pump speeds or operating patterns that delivered lower specific energy, measured as energy per volume pumped. This remains advisory-only. It never writes to PAC, HMI, EtherCAT, CODESYS, or AMAX control. It compares suggested setpoints against actual historical operating points and MVPv1 control logs to estimate achievable savings offline.

This report grounds that pivot for the single Yilan legacy site. It explicitly respects the hard safety boundary:

| Safety Rule | Product Interpretation |
|---|---|
| `evaluation_mode = offline_only` | All evaluation is performed on historical CSV/control-log data only. |
| `write_path = none` | Product produces reports, scorecards, and evidence artifacts only. |
| `influences_control = false` | No actuation, no closed-loop optimization, no HMI/PAC command. |
| `site_integration_allowed = false` | No site deployment until a future explicit qualification. |
| No `aquaoptima.edge` / `contracts.edge` imports | Modeling code remains offline; Contracts SDK read-only if used. |
| AMAX/CODESYS owns control | AquaOptima is a sidecar advisory/evidence layer only. |
| March 2026 is locked holdout | Never used in training, scaling fit, threshold tuning, or model selection. |

---

# 1. Problem Framing — Why Forecasting Failed Twice and Why Health + Efficiency Are the Right Pivots

## 1.1 Original forecasting objective

The previous objective was to train a learned model to forecast the next telemetry values, or short-horizon future telemetry values, for a single legacy pump station at 60-second cadence. The available data consisted primarily of 2025 telemetry for development and March 2026 telemetry as a locked benchmark.

The idea was reasonable at first glance: if a model could predict future flow, power, pressure, level, speed, and status better than a baseline, then prediction residuals might become useful for diagnostics or control support. However, the tests showed that the chosen forecasting task is not where this dataset offers model value.

The key reason is simple: at 60-second cadence, many pump station variables are strongly autocorrelated. In a stable hydraulic system, the next minute’s flow, pressure, power, speed, tank level, and demand are usually close to the current minute’s values. A trivial persistence forecast:

\[
\hat{x}_{t+1} = x_t
\]

is therefore extremely difficult to beat. It is not just a naïve baseline; for this single-site telemetry, it is a strong statistical description of the short-term process.

## 1.2 Confirmed failure evidence

The product pivot is based on two honest benchmark failures.

| Sprint | Forecasting Formulation | Holdout | Axes Evaluated | Result vs Persistence | Additional Findings | Decision |
|---|---:|---:|---:|---:|---|---|
| Sprint 25 | Absolute target, horizon = 1 step / 60 seconds | Locked March 2026, 44,469 rows / ~44,400 windows | 6 continuous axes | **0/6 axes beat persistence** | Normalized MSE values were small and passed a ≤0.15 threshold, but persistence MSE was 5–10x smaller. Binary `node_status` accuracy was 0.6677, below trivial always-on/constant behavior. | Forecasting failed as a value proposition. |
| Sprint 26 | Residual-over-persistence target, horizon = 15 minutes; 3 defects fixed; taxonomy corrected; sigmoid decode fixed | Same locked March 2026 benchmark; isolation verified True | 8 active axes | **0/8 axes beat persistence** | Metrics were in physical units. Beats-baseline check was scale-free and unambiguous. Persistence won by 3–10x MSE. | Failure confirmed not an artifact. |

The critical interpretation is that the model did not fail due to a single bug. Sprint 26 fixed known defects, corrected feature taxonomy, and adjusted the target to residual-over-persistence. Even after those corrections, the learned model did not beat persistence on any active axis. Therefore, the failure is a property of the task and data, not merely of the model implementation.

## 1.3 Why persistence is not a useful competitor for the new objectives

Persistence is excellent at answering:

> “What will the sensor value probably be one minute from now?”

It is poor at answering:

> “Is this combination of flow, power, speed, pressure, level, demand, and hydraulic head normal?”  
> “Is the station using more energy than historically necessary for this operating condition?”  
> “Are we drifting into an inefficient or unhealthy regime even if all individual values change slowly?”

Persistence has no concept of a normal multivariate operating envelope. If a pump gradually degrades and consumes more power for the same flow and head, persistence will happily predict that elevated power minute after minute. It will not call it abnormal. Likewise, if the station historically used a lower specific-energy operating point under similar hydraulic demand, persistence cannot identify that opportunity.

This is the reason the product should pivot from “forecast the next point” to “interpret the current and historical operating point.”

## 1.4 The unified product: Health + Efficiency Advisory

The product should become a single offline advisory product with two mutually reinforcing pillars:

| Product Pillar | Core Question | Why It Can Beat Trivial Baselines | Output |
|---|---|---|---|
| Pillar A — Health / Anomaly Detection | “Is this operating point normal for this station?” | Uses joint multivariate relationships and learned normal envelopes; persistence and univariate SPC miss many cross-sensor anomalies. | Health score, anomaly evidence, ranked contributing variables, event intervals. |
| Pillar B — Efficiency Advisory / dPL | “For this demand/head/level condition, did the site have historically lower-energy choices?” | Compares actual operating points to historically realized lower-specific-energy points under matched hydraulic conditions. | Advisory setpoint envelope, offline savings estimate, evidence from comparable historical cases. |

This is not a multi-site SaaS claim. It is a single-site, evidence-first advisory layer for Yilan. It should not actuate. It should not integrate into control. It should produce scorecards and reports that support operational decision-making and future qualification.

---

# 2. Pillar A Landscape — Health and Anomaly Detection for Single-Site Multivariate 60s Telemetry

## 2.1 Objective

Pillar A should detect abnormal or degraded behavior in the Yilan pump station by learning the normal operating envelope from 2025 auto-mode telemetry and evaluating on locked March 2026 data. The system should produce:

- A continuous **health score**, for example 0–100.
- A binary or graded **anomaly flag**, based on thresholds fixed before March evaluation.
- **Ranked evidence** showing which variables or relationships contributed most.
- **Event summaries**, not just point-level flags.
- Offline evaluation artifacts only: JSON scorecards, CSV event tables, plots, and reports.

The March 2026 holdout has no confirmed fault labels. Therefore, evaluation must use a combination of unsupervised metrics, proxy labels, injected-fault tests, and operational plausibility checks. The evaluation must be honest: without labels, it cannot claim real-world fault detection accuracy. It can claim sensitivity to defined fault injections, stability under normal-like data, and ability to identify statistically unusual operating regions.

## 2.2 Suitable methods

The following methods are appropriate for single-site, multivariate, 60-second telemetry. None should be treated as magic. The product should use a small ensemble of interpretable baselines and one learned model, not a complex research-only architecture that cannot be maintained.

### Pillar A method comparison

| Method | Data Needs | What It Learns | Baseline It Must Beat | Strengths | Failure Modes | Offline Evaluation Without Labels |
|---|---|---|---|---|---|---|
| Reconstruction-error autoencoder | Cleaned 2025 auto-mode windows; normalized 8 active axes; optional lag features | Nonlinear normal manifold of multivariate operating points | Persistence residual score and SPC/EWMA | Captures nonlinear cross-sensor relationships; can rank reconstruction residuals by variable | Learns bad behavior if training data includes unprofiled abnormal “other” mode; threshold instability; poor interpretability if too large | Holdout reconstruction error distribution; injected sensor drift/stuck/spike faults; event rate stability; compare with SPC false alarms |
| One-class SVM | Moderate-sized sampled training set; standardized features | Boundary around normal data | SPC and Mahalanobis | Strong for compact normal regions; well-known one-class method | Poor scaling on large 489K-row data unless sampled; sensitive to kernel and nu; hard to interpret | AUROC on injected faults; false-alarm rate on validation; compare event intervals |
| Isolation Forest | Tabular point or window features; can handle larger samples | Anomaly as easy-to-isolate points | SPC, random/rule thresholds | Fast, CPU-friendly, no neural training | May flag rare but legitimate operating regimes; weak temporal context unless features engineered | Injected faults; rare-regime analysis; stability across months |
| Density / Mahalanobis model | Standardized normal data; preferably mode-stratified | Elliptical or mixture normal distribution | Univariate 3-sigma/EWMA | Interpretable; good baseline; cheap CPU | Linear/Gaussian assumption; poor for multimodal pump regimes | Negative log-likelihood/Mahalanobis distance; threshold by 2025 validation quantile; injected cross-correlation faults |
| Residual vs physical expectation | Flow, power, speed, head/pressure, level; engineered hydraulic features | Expected power/flow/head relationship | Persistence and simple power-per-flow thresholds | Physically meaningful; directly tied to degradation/efficiency | Requires careful unit handling; confounded by operating mode and hydraulic conditions | Residual stability; injected degradation such as +5–20% power at same flow/head; compare with specific-energy anomalies |
| SPC / EWMA / 3-sigma | Per-variable historical baselines, possibly stratified by mode | Univariate or simple process control limits | Must serve as baseline, not final differentiator | Simple, trusted, explainable | Misses multivariate anomalies; many false alarms during regime shifts | False alarm rate, run-length, detection delay on injected faults |
| Multivariate control chart, e.g. Hotelling T² | Normal-mode standardized features; covariance estimate | Joint linear deviations from mean/covariance | Univariate SPC | Interpretable multivariate baseline | Sensitive to covariance drift and multimodality | T² exceedance rates; injected multivariate faults |

## 2.3 Recommended Pillar A architecture

For the first product version, the recommended approach is not one model alone. It should be a calibrated offline ensemble:

1. **Data filters and segmentation**
   - Use only 2025 training data for fitting scalers, thresholds, and models.
   - Prefer `auto == true` or confirmed auto-mode records for normal-envelope training.
   - Exclude `manual == true` from normal training unless explicitly modeling manual as a separate regime.
   - Treat the 31.6% “other” bucket as unprofiled. Do not blindly label it normal.
   - Exclude `edge_valve_position` because coverage is 0%.
   - Treat `edge_status` carefully because pump is on 99.85% of the time; it carries little anomaly signal except rare off transitions.
   - Treat `node_status` as continuous hydraulic head, not binary status.

2. **Feature engineering**
   - Raw active axes: `edge_flow`, `edge_power`, `edge_pump_speed`, `node_demand`, `node_level`, `node_pressure`, `edge_status`, `node_status`.
   - Derived features:
     - Specific energy proxy: power divided by flow, with safe handling of low-flow periods.
     - Power-to-speed relationships.
     - Flow-to-speed relationship.
     - Pressure/head consistency terms.
     - First differences and rolling changes over 5, 15, and 60 minutes.
     - Rolling median/standard deviation where appropriate.
   - All transformations must be fitted on 2025 training only.

3. **Model components**
   - **Baseline 1:** univariate SPC/EWMA on key variables and derived features.
   - **Baseline 2:** Mahalanobis or robust covariance model, possibly by operating regime.
   - **Candidate learned model:** small autoencoder trained on normalized auto-mode windows.
   - **Auxiliary tabular detector:** Isolation Forest on engineered point/window features.

4. **Score fusion**
   - Convert each detector score into a percentile or calibrated exceedance score based on 2025 validation data.
   - Health score example:

\[
Health_t = 100 - 100 \times \min(1, S_t)
\]

where \( S_t \) is a calibrated anomaly severity score, not fitted on March 2026.

5. **Evidence ranking**
   - For autoencoder: rank variables by normalized reconstruction error.
   - For Mahalanobis: rank variables by contribution to squared distance.
   - For SPC: show violated control limits.
   - For physical residuals: show “power higher than expected for matched flow/head/speed.”

## 2.4 Offline evaluation without true labels

Because March 2026 has no confirmed fault labels, the evaluation must avoid overstated claims. The following tests are legitimate:

| Evaluation Type | Description | What Can Be Claimed | What Cannot Be Claimed |
|---|---|---|---|
| Holdout score distribution | Apply frozen 2025-trained detector to March 2026. Measure anomaly rate, severity distribution, event durations. | Model generalizes or fails to generalize statistically to March. | Cannot claim true fault detection accuracy. |
| Injected sensor drift | Add gradual bias to one or more channels, e.g. +1%, +5%, +10%, +20% over hours/days. | Sensitivity to defined drift faults; detection delay. | Does not prove real sensor drift detection in the field. |
| Injected stuck sensor | Freeze a variable while others continue changing. | Ability to detect physically inconsistent flatlining. | Does not prove all sensor failures are detectable. |
| Injected spike/dropout | Insert short spikes, missing values, or dropouts. | Robustness and detection of transient telemetry faults. | Does not prove mechanical fault detection. |
| Injected efficiency degradation | Increase power by +5%, +10%, +20% at same flow/head/speed. | Sensitivity to energy degradation patterns. | Does not prove pump wear unless validated by maintenance records. |
| Proxy labels from rules | Use extreme pressure/head/level/power conditions or mode transitions as weak labels. | Detector aligns with known unusual conditions. | Proxy labels may be incomplete or biased. |
| Lead-time around known events | If MVPv1 logs or operator notes identify events, measure earlier score rise. | Potential early warning for documented events. | Only valid where event records are real and time-aligned. |

The evaluation should report false-alarm rate as events per day and percentage of time in alarm. A useful advisory detector should not produce constant alarms. For a single legacy site, a practical target might be:

| Metric | Candidate Gate |
|---|---:|
| March anomaly time fraction | ≤ 1–5% for high-severity alerts, unless evidence supports broader abnormality |
| High-severity event count | Operationally reviewable, e.g. not hundreds per day |
| Injected +10% power degradation detection | Detect within a defined window, e.g. under 1–6 hours depending on threshold |
| Injected stuck sensor detection | Detect within minutes to tens of minutes |
| False alarm on clean 2025 validation | Calibrated to threshold, e.g. 1% high-severity point exceedance |
| Evidence completeness | ≥ 90% of alerts include top contributing variables |

These gates should be finalized before March evaluation. The important principle is that the scorecard can say PASS or FAIL. A FAIL is a valid deliverable.

---

# 3. Pillar B Landscape — Pump Efficiency / Specific-Energy Advisory

## 3.1 Objective

Pillar B estimates whether the station historically had lower-energy operating choices for comparable demand and hydraulic conditions. It does not actuate. It does not command pump speed, pump combination, valves, PAC, HMI, or field I/O. It produces advisory evidence:

- Current or historical operating condition.
- Actual pump speed / power / flow / pressure / head / level.
- Specific energy under actual operation.
- Comparable historical operating points.
- Lower-specific-energy setpoint envelope observed in history.
- Estimated offline energy savings if the site had operated like the better matched historical cases.
- Caveats and confidence score.

The key phrase is **historically realized**. The product should not claim that an untested setpoint is physically safe or achievable unless the same or very similar operating point was observed in the historical data or supported by conservative hydraulic constraints.

## 3.2 Specific energy

Specific energy is the central metric:

\[
SE = \frac{\text{Energy consumed}}{\text{Volume pumped}}
\]

For minute-level telemetry, if `edge_power` is in kW and `edge_flow` is in m³/h, then:

\[
SE_{t} = \frac{kW}{m^3/h} = kWh/m^3
\]

If flow uses different units, the calculation must convert units before reporting. The product must not silently assume units. Low-flow intervals require special handling because division by near-zero flow creates unstable values. For pump-on, valid-flow intervals only:

\[
SE_t = \frac{P_t}{Q_t}
\]

with \( Q_t \) expressed in m³/h if using the above formula. For total interval savings:

\[
Energy_{actual} = \sum_t P_t \Delta t
\]

\[
Volume = \sum_t Q_t \Delta t
\]

\[
SE_{interval} = \frac{\sum_t P_t \Delta t}{\sum_t Q_t \Delta t}
\]

Interval-level specific energy is often more stable than point-level specific energy.

## 3.3 Affinity laws and pump physics

Pump affinity laws provide a physical guide for speed-controlled pumps:

| Relationship | Approximate Law | Meaning |
|---|---|---|
| Flow vs speed | \( Q \propto N \) | Flow changes roughly linearly with rotational speed. |
| Head vs speed | \( H \propto N^2 \) | Head changes roughly with speed squared. |
| Power vs speed | \( P \propto N^3 \) | Power changes roughly with speed cubed. |

These laws are approximate. Real stations include static head, system curves, pump efficiency curves, valves, tank levels, multiple pumps, controls, and constraints. Therefore, the product should use affinity laws as guardrails and features, not as a sole optimizer.

Important physical features for Pillar B include:

- Demand or required flow: `node_demand`.
- Actual flow: `edge_flow`.
- Hydraulic head: `node_status` as continuous 7.2–24.0 m.
- Pressure: `node_pressure`.
- Tank or node level: `node_level`.
- Pump speed: `edge_pump_speed`.
- Power: `edge_power`.
- Pump on/off status: `edge_status`.

## 3.4 Learning an efficient setpoint envelope

The product should learn a conditional efficiency envelope:

> Given similar demand, hydraulic head, level, and pressure, what pump speeds or operating patterns historically achieved lower specific energy while delivering comparable flow/service?

A practical single-site method:

1. **Define valid comparison intervals**
   - Use 2025 auto-mode data.
   - Optionally include MVPv1 control log periods as a separate baseline category.
   - Exclude invalid flow/power records, missing data, manual mode unless specifically analyzing manual behavior.
   - Exclude transient startup/shutdown periods unless they are part of the advisory scope.
   - Respect March 2026 as locked evaluation only.

2. **Create operating-condition bins or nearest-neighbor neighborhoods**
   - Match on `node_demand`, `node_status`/head, `node_level`, `node_pressure`, and possibly time-of-day/season if operationally meaningful.
   - Use tolerances such as demand within a percentile band, head within a fixed meter band, level within a fixed range, and pressure within a fixed range.
   - Require a minimum number of comparable historical points before making an advisory.

3. **Compute actual specific energy**
   - For each evaluated interval, compute actual SE over a stable time window, e.g. 15, 30, or 60 minutes.
   - Avoid point-level noisy claims where flow fluctuates.

4. **Estimate efficient envelope**
   - Within matched comparable historical points, compute a low-specific-energy quantile, such as the 10th or 25th percentile SE, not the absolute minimum.
   - The absolute minimum is often noise or an outlier.
   - Identify corresponding pump speed ranges and conditions that achieved that quantile.

5. **Estimate offline savings**
   - For each interval:

\[
Savings_{kWh} = \max(0, SE_{actual} - SE_{efficient\_envelope}) \times Volume
\]

   - Report both gross opportunity and confidence-adjusted opportunity.

6. **Generate advisory evidence**
   - “At similar demand/head/level, historical operations achieved 0.XXX kWh/m³ at pump speed range Y–Z, compared with actual 0.XXX kWh/m³.”
   - “This is an offline advisory only. No control action was taken or recommended for direct execution.”

## 3.5 Comparison against MVPv1 control logs and 2025 auto-mode

The baselines to beat are not theoretical curves. They are the site’s own historical operating points:

| Baseline | Role in Evaluation |
|---|---|
| 2025 auto-mode telemetry | Main source for observed operating envelope and efficient historical examples. |
| MVPv1 control logs | Operational baseline for what the previous control/advisory process actually did. |
| Actual March 2026 operation | Locked holdout for offline replay evaluation. |
| Simple rule baseline | Example: choose median historical speed for demand/head bin. |
| Best historical quantile baseline | Conservative envelope based on low SE quantile under matched conditions. |

The product should not claim:

- “We will save X% on site” without actuation and prospective validation.
- “The setpoint is safe” unless safety constraints are externally qualified.
- “The pump should run at this exact speed now” as an operational command.
- “The model outperforms control” unless control logs are time-aligned and comparison is valid.

It may claim, if supported:

- “In offline historical replay, for matched operating conditions, the advisory identified historically realized lower-specific-energy operating points.”
- “The estimated offline opportunity is X kWh or Y% over evaluated intervals, before implementation losses and safety qualification.”
- “The evidence is based on N comparable historical intervals with similar demand/head/level.”
- “No actuation occurred.”

## 3.6 Caveats for savings claims

Offline savings are not the same as realized savings. The report must include caveats:

| Caveat | Why It Matters |
|---|---|
| Historical comparability may be imperfect | Demand/head/level bins may not fully capture hydraulic state. |
| Lower SE may reflect unobserved factors | Weather, tank operations, valve states, maintenance condition, or sensor bias may influence results. |
| `edge_valve_position` unavailable | Valve state cannot be used to confirm hydraulic configuration. |
| Manual/other modes complicate interpretation | The 31.6% “other” bucket is unprofiled. |
| No actuation | Savings are counterfactual estimates, not measured outcomes. |
| Safety constraints external to data | Equipment limits and AMAX/CODESYS control logic are not overridden or inferred. |
| Single-site data | No generalization claim to other pump stations. |

---

# 4. Data Assessment

## 4.1 Available data

The product is built around a single legacy site:

| Dataset | Period | Approximate Size | Role |
|---|---:|---:|---|
| `source1_2025.csv` | Jan–Dec 2025 | ~489K rows, 60-second cadence | Training, validation, model selection, threshold tuning. |
| `source1_2026.csv` | March 2026 | ~44,469 rows, 60-second cadence | Locked holdout benchmark only. |
| MVPv1 control logs | Existing operational logs | Size not specified | Operational baseline for Pillar B comparison. |

March 2026 must never be used for training, scaler fitting, threshold selection, feature selection, or model selection. It is evaluation only.

## 4.2 Active telemetry axes

The active signal axes are:

| Axis | Interpretation | Product Use | Cautions |
|---|---|---|---|
| `edge_flow` | Pump station flow | Health, efficiency, specific energy denominator | Unit must be confirmed before kWh/m³ reporting. Low-flow intervals require filtering. |
| `edge_power` | Electrical power | Health, efficiency, degradation proxy | Power anomalies may reflect demand or hydraulic changes, not only equipment issues. |
| `edge_pump_speed` | Pump speed | Health, efficiency setpoint envelope | Advisory must not command speed. Only compare historically realized speed ranges. |
| `node_demand` | Demand signal | Matching variable for efficiency; context for health | Demand may be forecast, measured, or derived; semantics should be confirmed. |
| `node_level` | Tank/node level | Hydraulic context and constraint proxy | Important for matching; may have operational thresholds. |
| `node_pressure` | Pressure | Hydraulic health and matching | Should be checked against head relationship. |
| `edge_status` | Pump on/off | Filtering and state context | Pump is on 99.85% of time, so little class balance for status modeling. |
| `node_status` | Actually hydraulic head, continuous 7.2–24.0 m | Critical matching and health variable | Must not be treated as binary node status. |

Excluded:

| Axis | Reason |
|---|---|
| `edge_valve_position` | 0% coverage; excluded or masked. |

## 4.3 Mode mix risk

The real mode columns are `auto` and `manual`, not `optimizer_enabled` or `auto_mode_active`.

| Mode Category | 2025 Share | Product Interpretation |
|---|---:|---|
| Auto | 56.7% | Primary training source for normal envelope and efficiency envelope. |
| Manual | 11.7% | Exclude from normal auto-mode training or model separately. |
| Other/unprofiled | 31.6% | Major data-quality risk; must be profiled before inclusion. |

The 31.6% “other” bucket is a serious risk. It may include communications gaps, transitional states, unknown mode encodings, maintenance, fallback logic, or data-quality artifacts. If it is mixed into “normal” training without profiling, Pillar A may learn abnormal behavior as normal, and Pillar B may infer false efficiency opportunities.

Recommended treatment:

1. Build a mode-profile report for 2025:
   - Distribution of all 8 axes by mode.
   - Missingness by mode.
   - Specific energy by mode.
   - Time-of-day/month distribution by mode.
   - Event durations and transitions.

2. Train first-pass Pillar A on confirmed auto-mode only.

3. Evaluate how Pillar A scores manual and other modes, but do not automatically call them faults.

4. For Pillar B, compute efficiency envelopes separately for auto, manual, and other only after profiling.

## 4.4 Labels

Available labels are limited.

| Label Type | Exists? | Use |
|---|---|---|
| True fault labels | Not specified / likely absent | Cannot compute true field fault recall without them. |
| Mode labels `auto` / `manual` | Yes | Filtering, stratification, proxy evaluation. |
| Pump on/off `edge_status` | Yes, but 99.85% on | State filtering; not useful as balanced classification. |
| Hydraulic head `node_status` | Yes, continuous | Feature/matching variable, not binary label. |
| MVPv1 control actions/logs | Yes | Pillar B baseline comparison. |
| Engineered anomaly labels | Must be created | Injected-fault tests and proxy labels. |
| Engineered efficiency labels | Must be created | Specific-energy envelope and matched-condition comparisons. |

## 4.5 Leakage rules

Leakage controls are mandatory:

| Rule | Implementation |
|---|---|
| March 2026 locked holdout | Never read during training, scaling, feature selection, threshold tuning, or model selection. |
| 2025-only scalers | Fit normalization, imputation, PCA/covariance, and thresholds on 2025 training/validation only. |
| Time-aware split | Use chronological splits within 2025, e.g. train on earlier months, validate on later months. |
| No future features | Rolling features must use past-only windows. |
| MVPv1 logs alignment | Logs can be used for offline comparison, but must not leak March outcomes into model tuning. |
| Report reproducibility | Save config, feature list, split definitions, and threshold values before March scoring. |

---

# 5. Evaluation Strategy

## 5.1 Evaluation philosophy

The evaluation should be designed to answer:

- Does Pillar A detect abnormal multivariate behavior better than simple baselines?
- Does Pillar B identify historically realized lower-specific-energy opportunities under comparable conditions?
- Are results stable, interpretable, and operationally reviewable?
- Does the product respect the advisory-only boundary?

A PASS is valuable. A FAIL is also valuable. The forecasting work already demonstrated the importance of honest negative results. The same discipline should apply here.

## 5.2 Baselines each pillar must beat

| Pillar | Baseline | Why It Matters |
|---|---|---|
| A Health | Persistence residual | Tests whether anomaly score adds value beyond “changed from last value.” |
| A Health | Univariate SPC / EWMA / 3-sigma | Simple and trusted process monitoring baseline. |
| A Health | Mahalanobis / multivariate control chart | Strong interpretable multivariate baseline. |
| A Health | Isolation Forest baseline | CPU-friendly nonlinear-ish tabular baseline. |
| B Efficiency | Site’s own actual historical operation | The advisory must identify better choices than what was done. |
| B Efficiency | MVPv1 control logs | Operational comparator for prior control/advisory behavior. |
| B Efficiency | Median matched-condition operation | Simple benchmark: use typical historical behavior. |
| B Efficiency | Low-quantile historical SE envelope | Conservative best-observed comparator. |

Persistence should remain in the scorecard, but not as the main competitor for all tasks. For Pillar A, persistence residual detects abrupt changes but misses slow degradation. For Pillar B, persistence is largely irrelevant; the baseline is actual site operation under comparable conditions.

## 5.3 Pillar A metrics

Because true labels are absent, metrics should be split into unsupervised holdout metrics, injected-fault metrics, and proxy-label metrics.

### Pillar A metric table

| Metric | Definition | Purpose |
|---|---|---|
| Point anomaly rate | Percentage of March points above threshold | Checks alarm volume. |
| Event count per day | Contiguous anomaly intervals after debounce | Operational reviewability. |
| Median / max event duration | Duration of alert intervals | Distinguishes noise from sustained issues. |
| Reconstruction error percentile | March score relative to 2025 validation distribution | Generalization check. |
| False alarm proxy | Exceedance on presumed normal 2025 validation | Threshold calibration. |
| AUROC on injected faults | Separate clean vs injected sequences | Sensitivity to defined faults. |
| Detection delay / lead time | Time from injection start to threshold crossing | Practical early warning measure. |
| Variable attribution accuracy | Whether injected channel appears in top contributors | Evidence quality. |
| SPC comparison | Relative AUROC/delay/alarm rate vs SPC | Must beat simple control charts. |
| Persistence residual comparison | Detection of slow drift vs last-value residual | Demonstrates pivot value. |

Recommended injected faults:

| Injected Fault | Example Magnitudes | Expected Detector Behavior |
|---|---:|---|
| Power degradation | +5%, +10%, +20% power at same flow/head/speed | Physical residual and autoencoder should flag. |
| Flow sensor drift | +1%, +5%, +10% gradual bias | Multivariate detectors should detect inconsistency. |
| Pressure drift | +5%, +10% gradual bias | Pressure/head consistency should flag. |
| Stuck speed sensor | Freeze speed for 30–180 minutes while power/flow change | Temporal features should flag. |
| Spike/dropout | 1–10 minute spikes or missing values | SPC and robust detector should flag. |
| Cross-sensor inconsistency | Increase flow without corresponding speed/power/head change | Multivariate methods should outperform univariate. |

A candidate PASS for Pillar A should require more than one favorable metric. Example PASS gate:

| Gate | Candidate Requirement |
|---|---|
| March reviewability | High-severity alerts ≤ 5% of time and event count operationally reviewable. |
| Injected fault sensitivity | AUROC > 0.85 on at least major injected fault families. |
| Slow degradation advantage | Detect +10% power degradation materially earlier than persistence residual. |
| Evidence quality | Top-3 contributing variables include injected variable in ≥ 70–80% of injected events. |
| Baseline comparison | Autoencoder/ensemble improves over SPC on multivariate/cross-sensor injected faults without unacceptable false alarms. |

These thresholds are suggestions. Final gates must be frozen before holdout scoring.

## 5.4 Pillar B metrics

Pillar B evaluation should focus on matched-condition specific-energy improvement.

### Pillar B metric table

| Metric | Definition | Purpose |
|---|---|---|
| Valid evaluated volume | Total volume in intervals passing data-quality and comparability filters | Ensures coverage. |
| Coverage rate | Fraction of March or 2025 intervals where advisory can make a confident comparison | Avoids universal but unsupported recommendations. |
| Actual SE | Actual kWh/m³ for evaluated interval | Baseline energy intensity. |
| Matched-envelope SE | Low-quantile SE among comparable historical intervals | Advisory target proxy. |
| SE reduction | \( SE_{actual} - SE_{envelope} \) | Opportunity size. |
| Percent SE reduction | Reduction divided by actual SE | Normalized opportunity. |
| Estimated kWh opportunity | SE reduction × volume | Business value proxy. |
| Comparable sample count | Number of historical intervals in neighborhood | Confidence. |
| Speed recommendation range | Observed speed range associated with efficient envelope | Advisory evidence, not command. |
| MVPv1 comparison | Actual logs vs advisory envelope under same conditions | Tests against operational baseline. |
| Constraint violation proxy | Whether recommended envelope lies outside observed safe ranges | Filters unsafe/unseen suggestions. |

Recommended PASS gate:

| Gate | Candidate Requirement |
|---|---|
| Minimum coverage | Advisory covers a meaningful share of valid auto-mode pumped volume, e.g. >30%, or clearly explains lower coverage. |
| Historical support | Each advisory interval has minimum comparable observations, e.g. N ≥ 30 matched points or sufficient interval-hours. |
| Positive opportunity | Matched-envelope SE is lower than actual by a practically meaningful margin after guardrails. |
| Robustness | Savings estimate remains positive under conservative quantile choice, e.g. 25th percentile rather than minimum. |
| MVPv1 relevance | Advisory identifies opportunities relative to MVPv1 logged behavior where logs overlap. |
| No unsafe extrapolation | Recommendations are within historically observed speed/head/flow ranges. |

## 5.5 Offline scorecard structure

The final product artifact should be a scorecard JSON and report, not a deployment package.

Example scorecard fields:

| Field | Description |
|---|---|
| `evaluation_mode` | Must equal `offline_only`. |
| `write_path` | Must equal `none`. |
| `influences_control` | Must equal `false`. |
| `site_integration_allowed` | Must equal `false`. |
| `train_period` | 2025 ranges used. |
| `holdout_period` | March 2026. |
| `features` | Exact feature list. |
| `leakage_check` | Confirmation of no March use in training/tuning. |
| `pillar_A_status` | PASS/FAIL with metrics. |
| `pillar_B_status` | PASS/FAIL with metrics. |
| `alerts` | Offline event summaries. |
| `efficiency_opportunities` | Offline advisory opportunities. |
| `caveats` | Data and interpretation limitations. |

---

# 6. Technical Recommendation

## 6.1 Overall recommendation

Build AquaOptima Pump Station Optimizer Lite as an **offline, advisory-only evidence product** with two pillars:

1. **Pillar A Health Detection**
   - Start with interpretable baselines and a compact autoencoder ensemble.
   - Evaluate against SPC, Mahalanobis, Isolation Forest, and persistence residual.
   - Use injected-fault and proxy-label testing because true labels are absent.

2. **Pillar B Efficiency Advisory**
   - Build a matched-condition specific-energy envelope.
   - Compare actual operation and MVPv1 logs against historically realized lower-SE operating points.
   - Report counterfactual offline savings with conservative caveats.

No site integration or edge packaging should proceed until at least one pillar earns an honest PASS under frozen evaluation rules.

## 6.2 Pillar A concrete modeling approach

### Recommended first implementation

| Component | Recommendation |
|---|---|
| Language/stack | Python, pandas, numpy, PyTorch. |
| Training data | 2025 confirmed auto-mode data only for first normal model. |
| Holdout | March 2026 only after freeze. |
| Features | 8 active axes + derived physical/rolling features. |
| Baselines | SPC/EWMA, Mahalanobis/Hotelling T², Isolation Forest if available in allowed stack; if not, implement robust alternatives or use sklearn only if permitted by environment. |
| Learned model | Small dense or temporal autoencoder. |
| Window length | Candidate 15–60 minutes of 60-second samples; freeze based on 2025 validation. |
| Threshold | 2025 validation quantile, e.g. 99th percentile for high severity. |
| Output | Health score, event table, top contributing variables. |
| Deployment | None. Offline reports only. |

If staying strictly within PyTorch/pandas/numpy and avoiding scikit-learn, the minimum viable set is:

- EWMA/SPC implemented in numpy.
- Robust z-score and covariance/Mahalanobis implemented in numpy.
- PyTorch autoencoder.
- Optional simple density model or PCA reconstruction implemented manually.

### Autoencoder design

A suitable architecture should be small enough for CPU:

- Input: normalized window of shape `[window_length, feature_count]`, flattened or encoded by a small 1D temporal architecture.
- Model option A: dense autoencoder on flattened windows.
- Model option B: small temporal convolution autoencoder.
- Latent dimension: small, for example 4–16 depending on feature count.
- Loss: masked MSE, possibly weighted by feature reliability.
- Training: early stopping on 2025 validation.
- Thresholds: fixed from 2025 validation score distribution.

The autoencoder should not be sold as “predictive maintenance” by itself. It is a normal-envelope detector. Maintenance interpretation requires corroborating evidence, logs, or field inspection.

### Health evidence

Every alert should include:

| Evidence Field | Example |
|---|---|
| Alert start/end | Timestamp interval. |
| Severity | Health score or percentile. |
| Dominant variables | `edge_power`, `edge_flow`, `node_pressure`, etc. |
| Detector agreement | AE + Mahalanobis + SPC, or only one detector. |
| Physical residual | “Power high for matched flow/head/speed.” |
| Mode context | Auto/manual/other. |
| Data-quality flags | Missingness, low-flow, mode ambiguity. |

## 6.3 Pillar B concrete modeling approach

### Recommended first implementation

Use a conservative matched-neighborhood efficiency envelope rather than a free-form optimizer.

| Step | Recommendation |
|---|---|
| Filter | Valid auto-mode pump-on intervals with reliable flow and power. |
| Aggregate | Use 15-minute or 30-minute intervals to reduce noise. |
| Compute SE | kWh/m³ after confirming flow units. |
| Match variables | Demand, hydraulic head, level, pressure, and possibly flow/service delivered. |
| Envelope | Use 10th or 25th percentile SE among comparable historical intervals. |
| Advisory | Report historically observed efficient speed range, not an exact command. |
| Savings | Estimate offline kWh opportunity = SE gap × volume. |
| Confidence | Based on sample count, match distance, data quality, and whether speed range was historically observed. |

### Why not start with reinforcement learning or direct control optimization?

Because this product is explicitly advisory-only and single-site. A reinforcement learning or direct optimizer framing would imply control influence and would be difficult to validate safely without actuation. It would also risk extrapolating beyond historical operation. The correct first product is evidence-based:

> “Here is what the station historically achieved under similar conditions, and here is how current/historical operation compares.”

That is useful, auditable, and compatible with the safety boundary.

## 6.4 Integration boundary

Even though edge hardware is AMAX-8580 and model export PyTorch → ONNX is known, packaging is out of scope for this product version. The current deliverables are:

- Offline model training scripts.
- Frozen evaluation configs.
- Scorecard JSON.
- Report artifacts.
- Plots and event tables.
- Efficiency opportunity tables.
- Leakage and safety compliance checks.

The product must not include:

- PAC write path.
- HMI command path.
- EtherCAT field I/O influence.
- CODESYS integration.
- Edge deployment package.
- `aquaoptima.edge` or `contracts.edge` imports in model code.
- Any closed-loop setpoint execution.

## 6.5 Risk register

| Risk | Pillar | Severity | Why It Matters | Mitigation |
|---|---|---:|---|---|
| March leakage | A/B | High | Invalidates benchmark. | Strict split enforcement; save frozen configs before holdout; audit file access. |
| “Other” mode contamination | A/B | High | 31.6% unprofiled data may corrupt normal/efficient envelopes. | Profile separately; train first on confirmed auto only. |
| No true fault labels | A | High | Cannot claim real fault recall. | Use injected faults, proxy labels, event review; state limitations. |
| Edge status imbalance | A | Medium | 99.85% on makes status classification meaningless. | Use as filter/context, not target. |
| Misinterpreting `node_status` | A/B | High | It is hydraulic head, not binary status. | Rename internally as `hydraulic_head_m` or similar. |
| Flow unit uncertainty | B | High | Incorrect kWh/m³ calculation would invalidate savings. | Confirm units; include unit conversion tests. |
| Low-flow division instability | B | High | Inflates specific energy. | Minimum flow thresholds; interval aggregation. |
| Valve position unavailable | B | Medium/High | Missing hydraulic configuration variable. | Conservative matching; caveat; avoid overclaiming. |
| Historical confounding | B | High | Lower SE may be due to unobserved conditions. | Use matched neighborhoods, confidence scoring, conservative quantiles. |
| Over-alerting | A | Medium | Operators ignore noisy health scores. | Event debounce; severity thresholds; report event/day. |
| Overfitting single site | A/B | Medium | Model may learn quirks not causal physics. | Single-site claim only; validate on March; avoid SaaS generalization. |
| Unsafe advisory interpretation | B | High | Users may treat advisory as command. | Every screen/report/API states advisory-only; no write path. |
| Model complexity | A | Medium | Hard to maintain on CPU/offline stack. | Compact models; baselines first; simple features. |
| Savings overclaim | B | High | Offline estimate not realized savings. | Phrase as “offline opportunity”; require future controlled trial for realized savings. |
| MVPv1 log alignment errors | B | Medium | Invalid comparison to control logs. | Time synchronization checks; missing-log handling. |

## 6.6 Recommended milestone plan

| Milestone | Deliverable | PASS/FAIL Decision |
|---|---|---|
| M1 — Data profile | 2025/2026 schema, missingness, mode profile, unit checks | PASS if data quality sufficient for offline modeling. |
| M2 — Pillar A baselines | SPC, EWMA, Mahalanobis, persistence residual scorecard on 2025 validation | Establish baseline thresholds before March. |
| M3 — Pillar A learned model | Autoencoder trained on 2025 auto-mode; injected-fault evaluation | PASS if it improves on baselines for multivariate/injected faults. |
| M4 — Pillar B SE engine | Valid interval aggregation, unit-confirmed SE, matched-condition search | PASS if SE estimates are stable and comparable. |
| M5 — MVPv1 comparison | Align control logs with telemetry; compare actual operation to envelope | PASS if log alignment supports fair comparison. |
| M6 — Locked March evaluation | Apply frozen A+B pipeline to March 2026 | Report honest PASS/FAIL. |
| M7 — Product report | Offline scorecard, evidence tables, caveats, recommendation | No integration unless future qualification. |

## 6.7 Final recommendation

Proceed with AquaOptima Pump Station Optimizer Lite as a two-pillar offline advisory product:

- **Pillar A should be built as a normal-envelope health detector**, combining SPC/EWMA, multivariate distance, physical residuals, and a compact autoencoder. It should be evaluated using March holdout distributions, injected faults, proxy labels, and operational reviewability metrics. It must beat simple SPC and persistence-residual baselines on defined anomaly tasks, especially slow degradation and cross-sensor inconsistency.

- **Pillar B should be built as a conservative efficiency advisory engine**, based on specific energy and matched historical operating conditions. It should compare actual operation and MVPv1 logs against historically realized lower-specific-energy envelopes. It may report offline opportunity, not guaranteed savings.

The product should explicitly preserve the safety boundary: offline only, no write path, no control influence, no site integration. The deliverable is evidence: scorecards, reports, event tables, and efficiency opportunity analysis.

The forecasting failure is not a setback to hide; it is the evidence that justifies this pivot. The single-site Yilan data does not reward learned short-horizon forecasting over persistence. It may, however, reward models that understand normal multivariate behavior and historical energy efficiency. That is where AquaOptima Pump Station Optimizer Lite should focus.