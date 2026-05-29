# PRD: AquaOptima Pump Station Optimizer Lite — Health & Efficiency Advisory (A+B)

**Product:** AquaOptima Pump Station Optimizer Lite  
**Mode:** Offline-only evidence and advisory product  
**Site:** Single legacy Yilan pump station, Taiwan  
**Pillars:**  
- **Pillar A:** Health / Anomaly Detection Advisory  
- **Pillar B:** Efficiency / Specific-Energy Advisory  
**Safety boundary:** No write path, no actuation, no control influence, no site integration in this version  
**Primary historical data:** `source1_2025.csv` for training/validation; locked `source1_2026.csv` March 2026 for holdout only  
**Control ownership:** AMAX/CODESYS owns control. AquaOptima is a read-only, offline evidence sidecar only.  
**Document status:** Build-ready PRD for offline MVP after Sprint 26 forecasting failure verdicts  

---

## 1. Executive Summary

### 1.1 Vision

AquaOptima Pump Station Optimizer Lite will become a single-site, offline advisory analytics product for the Yilan pump station that helps operators and managers answer two practical questions:

1. **Health:** “Did the pump station operate abnormally or show early signs of degradation compared with its own historical normal operating envelope?”
2. **Efficiency:** “Under similar demand and hydraulic conditions, did the station historically achieve lower energy per cubic meter, and where is the offline opportunity worth investigating?”

The product does **not** control the pump station. It does **not** send speed commands. It does **not** write to AMAX, CODESYS, PAC, HMI, EtherCAT, SCADA, historian, or field I/O. It produces offline reports, scorecards, event tables, plots, and evidence bundles for human review.

The intended business value for a plant manager is straightforward:

- **Earlier fault warning:** identify abnormal power/flow/head/pressure/speed relationships before they become obvious operational problems.
- **Avoided energy cost opportunity:** quantify offline kWh or cost opportunity by comparing actual operation to historically observed lower-specific-energy operation under matched conditions.
- **Operational focus:** reduce noisy data into reviewable health events and prioritized efficiency opportunities.
- **Decision evidence:** provide honest PASS/FAIL scorecards rather than optimistic model claims.

### 1.2 Forecasting-failure backstory

The original product direction was short-horizon telemetry forecasting. That direction was tested twice and failed honestly against the locked March 2026 Yilan holdout. In Sprint 25, a learned dPHM forecasting model attempted 60-second-ahead absolute telemetry prediction and failed to beat a trivial persistence baseline on all 6 continuous axes. In Sprint 26, after fixing known defects, correcting taxonomy, using a residual-over-persistence target, and moving to a 15-minute horizon, the model again failed to beat persistence on all 8 active axes. The core lesson is that minute-cadence pump station telemetry is highly autocorrelated: for many signals, “the next value is the last value” is a very strong baseline. Therefore, AquaOptima should stop trying to win where persistence is structurally advantaged and pivot to advisory tasks where persistence has no operational understanding: multivariate health detection and matched-condition efficiency comparison.

### 1.3 Two-pillar pivot

The MVP now consists of two offline advisory pillars:

| Pillar | User Question | Product Output | Why It Can Add Value |
|---|---|---|---|
| **A — Health / Anomaly Detection** | Is this combination of flow, power, speed, pressure, demand, level, status, and hydraulic head normal for this station? | Health score, anomaly events, severity, contributing variables, detector agreement, offline scorecard | Persistence can follow abnormal values indefinitely. It does not know the normal multivariate operating envelope. |
| **B — Efficiency Advisory** | Under similar hydraulic conditions, did this station historically use less energy per m³? | Specific-energy comparison, historically observed efficient speed ranges, offline kWh opportunity, confidence, caveats | Persistence cannot compare current operation against historically better matched operating points. |

Both pillars are advisory-only and offline-only. Neither pillar can write, actuate, or influence control.

### 1.4 Target KPIs

The MVP must be evaluated honestly. Because true fault labels are scarce or absent, health KPIs must distinguish between synthetic/injected sensitivity, proxy-label analysis, and actual field-verified fault performance. Efficiency KPIs must distinguish offline opportunity from realized savings.

#### Pillar A target KPIs

| KPI | Target / Gate Candidate | Business Interpretation |
|---|---:|---|
| High-severity March anomaly time fraction | ≤ 5% unless evidence justifies broader abnormality | Operators receive reviewable events, not constant alarm noise. |
| High-severity event count per day | Operationally reviewable; target ≤ 10/day for high severity | Events can be reviewed by staff. |
| Injected +10% power degradation detection | Detected within 1–6 hours depending on threshold | Earlier warning of possible efficiency decay or equipment issue. |
| Injected stuck sensor detection | Detected within minutes to tens of minutes | Faster identification of telemetry failure. |
| Injected-fault AUROC | > 0.85 on major injected fault families | Detector is sensitive to defined abnormal patterns. |
| Evidence completeness | ≥ 90% of high-severity events include top contributing variables | Operators understand why an event was flagged. |
| Baseline comparison | Beat or materially improve over SPC/persistence on slow degradation and cross-sensor faults | Model adds value beyond simple charts. |

#### Pillar B target KPIs

| KPI | Target / Gate Candidate | Business Interpretation |
|---|---:|---|
| Advisory coverage | > 30% of valid pumped volume, or lower with clear exclusion explanation | Enough volume is covered to be useful. |
| Comparable historical support | ≥ 30 matched observations or equivalent interval-hours per advisory class | Recommendations are based on history, not extrapolation. |
| Specific-energy opportunity | Positive under conservative 25th-percentile envelope | Opportunity is not a single outlier. |
| Offline kWh/m³ reduction identified | Reported as counterfactual opportunity only | Potential avoided energy cost for review. |
| Unsupported interval rejection | 100% of unsafe/unseen/low-confidence intervals rejected | No unsupported “optimization” claims. |
| MVPv1 comparison coverage | Reported where logs align | Shows whether AquaOptima identifies additional reviewable opportunity. |

### 1.5 Timeline

The plan continues the AOPSO ladder after Sprint 26. The next sprint is Sprint 27 and is the only sprint marked **Planned**. All later sprints remain **Backlog** and are gated by prior evidence.

High-level timeline:

- **Sprint 27:** Data profile, safety guardrails, leakage guard, schema/unit validation.
- **Sprint 28:** Pillar A baselines and health scoring on 2025 validation.
- **Sprint 29:** Pillar A learned detector, injected-fault harness, frozen health gate.
- **Sprint 30:** Pillar A locked March evaluation. Pillar A must earn PASS or explicit FAIL.
- **Sprint 31:** Pillar B specific-energy engine and valid interval aggregation.
- **Sprint 32:** Pillar B matched-condition envelope and MVPv1 log comparison.
- **Sprint 33:** Pillar B locked March evaluation. Pillar B must earn PASS or explicit FAIL.
- **Sprint 34:** Unified A+B report/dashboard/export packaging only if gates pass; no edge packaging, no site integration, no write path.

The product is not eligible for field deployment or control integration in this PRD. Even if both pillars pass, the deliverable remains offline evidence.

---

## 2. Background & Context

### 2.1 Site context

This PRD applies to one legacy pump station in Yilan, Taiwan. It is not a multi-site product, not a fleet benchmark, and not a generalized SaaS optimization service. The product must learn from and evaluate against this single site’s historical telemetry and control logs only.

Available datasets:

| Dataset | Period | Role |
|---|---|---|
| `source1_2025.csv` | January–December 2025 | Training, validation, profiling, threshold tuning, model selection |
| `source1_2026.csv` | March 2026 | Locked holdout benchmark only |
| MVPv1 control logs | Existing offline logs, if supplied | Operational comparator for efficiency advisory |

The product must enforce that March 2026 is never used for training, scaler fitting, threshold tuning, feature selection, model selection, matching tolerance tuning, or quantile selection.

### 2.2 Two prior FAIL verdicts

The pivot is driven by two clear forecasting failures:

| Sprint | Formulation | Holdout | Result | Verdict |
|---|---|---|---|---|
| Sprint 25 | 60-second absolute telemetry forecasting | Locked March 2026 | 0/6 continuous axes beat persistence | FAIL |
| Sprint 26 | 15-minute residual-over-persistence forecasting after defect fixes | Locked March 2026 | 0/8 active axes beat persistence | FAIL |

These are not hidden failures. They are part of the product story and must be reflected in the report’s “why this product exists” section. The honest conclusion is that short-horizon forecasting is not the correct first value proposition for this dataset.

### 2.3 Advisory-only OT boundary

The OT safety boundary is absolute:

```json
{
  "evaluation_mode": "offline_only",
  "write_path": "none",
  "influences_control": false,
  "site_integration_allowed": false
}
```

Product implications:

- No live connection to the plant.
- No SCADA, HMI, AMAX, PAC, EtherCAT, CODESYS, OPC UA, Modbus, MQTT, historian, or field I/O write path.
- No live alarms.
- No setpoint execution.
- No command queue.
- No automatic operator acknowledgment workflow connected to operations.
- No auto-generated maintenance tickets into CMMS.
- No edge deployment package in this version.
- No `aquaoptima.edge` or `contracts.edge` imports in modeling code.
- No control claims.

Every report, dashboard page, scorecard, API response, and exported evidence bundle must prominently state that this is offline advisory evidence only.

### 2.4 AMAX/CODESYS ownership split

AMAX/CODESYS owns station control. AquaOptima does not own control logic. AquaOptima is a sidecar analytics product that reads offline files and produces evidence.

This ownership split must be encoded in product behavior:

| Domain | Owner | AquaOptima Behavior |
|---|---|---|
| Pump speed command | AMAX/CODESYS | No command, no write, no suggested executable setpoint |
| PAC logic | AMAX/CODESYS | No integration |
| HMI operator control | Site / AMAX/CODESYS | No HMI control element |
| Field I/O | AMAX/CODESYS / site OT | No connection |
| Offline analytics | AquaOptima | Health and efficiency evidence only |
| Scorecards and reports | AquaOptima | Offline PASS/FAIL with caveats |

### 2.5 Data caveats

Important known data caveats:

- `node_status` is not a binary node status. It is a continuous hydraulic head-like signal, approximately 7.2–24.0 m. Internally, it should be renamed or documented as `hydraulic_head_m`.
- `edge_status` is pump on/off, but pump is on approximately 99.85% of the time, so it has limited classification value.
- `edge_valve_position` has 0% coverage and must be excluded.
- Real mode columns are `auto` and `manual`.
- 2025 mode mix includes approximately:
  - 56.7% auto
  - 11.7% manual
  - 31.6% other/unprofiled
- The 31.6% other bucket is a major risk and cannot be assumed normal.
- True fault labels are not confirmed, so Pillar A cannot claim real-world fault recall unless future labels are supplied.
- Offline efficiency opportunity is not realized savings.

---

## 3. User Personas

All personas interact with offline evidence only. None can use the product to write to or control the pump station.

### 3.1 Plant Operator

**Primary job:** Keep the pump station operating safely and reliably during shifts.

**Needs:**

- Quickly understand whether historical operation looked abnormal.
- Review health events without being overwhelmed by point-level noise.
- See why an event was flagged.
- Understand efficiency advisories without mistaking them for commands.
- Filter unsupported or unprofiled modes.

**Pain points:**

- Raw telemetry is too dense to inspect manually.
- Simple alarms may miss slow changes.
- Too many false alarms reduce trust.
- Advisory analytics can be dangerous if phrased like control instructions.

**Success measures:**

- Can review high-severity health events in minutes.
- Sees clear contributing variables.
- Sees prominent offline/no-control banner on every screen.
- Never sees a button or endpoint that implies execution.

**Safety requirement for persona:** The Plant Operator must never be presented with an “execute,” “apply setpoint,” “send to controller,” or “acknowledge to control” action.

### 3.2 Reliability Engineer

**Primary job:** Investigate equipment and sensor health issues, plan maintenance, and interpret abnormal operating behavior.

**Needs:**

- Event-level anomaly evidence.
- Detector agreement across SPC, multivariate distance, physical residuals, and learned detector.
- Injected-fault sensitivity metrics.
- Variable attribution.
- Honest caveats about lack of field fault labels.

**Pain points:**

- Statistical anomalies are not always faults.
- Without labels, model claims can be overstated.
- Maintenance decisions require evidence, not black-box scores.

**Success measures:**

- Can export health events with start/end time, severity, mode, top contributors, and plots.
- Can see whether the detector beats SPC/persistence on defined synthetic tests.
- Can distinguish “statistically unusual” from “confirmed fault.”

**Safety requirement for persona:** The product can support offline investigation but cannot create maintenance tickets or trigger operational actions automatically.

### 3.3 Energy / Operations Manager

**Primary job:** Reduce operating costs while preserving service reliability and safety.

**Needs:**

- Specific energy in kWh/m³.
- Offline opportunity in kWh and optional avoided cost.
- Coverage and exclusions.
- Conservative confidence scoring.
- Comparison to MVPv1 control logs where valid.

**Pain points:**

- Energy savings claims are often overstated.
- Historical data may be confounded by unobserved conditions.
- Setpoint recommendations can be unsafe if not qualified.

**Success measures:**

- Can see actual SE versus matched historical efficient-envelope SE.
- Can see estimated offline kWh opportunity and optional cost.
- Can see caveats: not realized savings, no actuation, single-site only.
- Can see how much volume is covered by confident advisories.

**Safety requirement for persona:** The product may report “offline estimated opportunity,” but must not claim guaranteed or realized savings and must not recommend executable control changes.

### 3.4 AquaOptima ML Engineer

**Primary job:** Build, evaluate, and audit the offline analytics pipeline.

**Needs:**

- Clear schema validation.
- Leakage guard for March 2026.
- Deterministic training and scoring.
- Frozen configs, thresholds, scalers, and gates.
- Structured scorecards and manifests.
- Prohibited import and write-path checks.

**Pain points:**

- Prior forecasting failed because the task was structurally poor.
- March leakage would invalidate the benchmark.
- Offline advisory boundaries must be enforced in code, not just documentation.
- Model results may fail, and failure must be reportable.

**Success measures:**

- Can run CLI stages reproducibly.
- Can prove March was not used before frozen scoring.
- Can generate scorecards with PASS/FAIL.
- Can audit every file, config, seed, and artifact.

**Safety requirement for persona:** The ML Engineer must be blocked from importing edge/control packages or opening any live/write-capable connector.

---

## 4. Information Architecture

### 4.1 Offline data flow

The product uses a staged offline pipeline. No stage connects to live OT systems or writes to source systems.

```text
Offline CSV / control logs
        |
        v
[Ingest + Schema Validation]
        |
        v
[Data Profile + Mode Profile + Unit Checks]
        |
        v
[2025 Chronological Split]
        |
        +--> [Pillar A Feature Engineering]
        |        |
        |        v
        |   [Pillar A Baselines + Candidate Model Training]
        |        |
        |        v
        |   [Threshold Freeze + Injected-Fault Harness]
        |
        +--> [Pillar B Valid Interval Aggregation]
                 |
                 v
            [Specific Energy Calculation]
                 |
                 v
            [Matched-Condition Efficiency Envelope]
                 |
                 v
            [MVPv1 Log Alignment, if supplied]

After freeze:
        |
        v
[Locked March 2026 Offline Scoring]
        |
        v
[Scorecards + Evidence Reports + Static Dashboard]
```

Safety boundary in this architecture:

- Inputs are offline files only.
- Outputs are offline files only.
- There is no runtime connection to AMAX/CODESYS or any control system.
- There is no write-back path to source data or site systems.

### 4.2 Data partitions

| Partition | Use | Allowed Operations |
|---|---|---|
| 2025 training | Model fitting, scaler fitting, feature engineering design | Allowed before freeze |
| 2025 validation | Threshold selection, model selection, gate calibration | Allowed before freeze |
| March 2026 holdout | Final locked evaluation only | Allowed only after freeze |
| MVPv1 logs | Offline comparison for Pillar B | Allowed if time-aligned and not used to leak March tuning |

The product must produce a leakage manifest showing which files were read by each stage.

### 4.3 Modules

#### 4.3.1 Ingest module

Responsibilities:

- Read offline CSV and log file paths.
- Validate required columns.
- Validate timestamps, cadence, duplicates, gaps.
- Validate row counts and date ranges.
- Validate mode columns `auto` and `manual`.
- Rename or map `node_status` to hydraulic head internally.
- Exclude `edge_valve_position`.
- Compute checksums.
- Reject live connectors.

Safety requirement: Ingest accepts local file paths only and cannot connect to live endpoints.

#### 4.3.2 Data profile module

Responsibilities:

- Missingness by column and mode.
- Mode mix.
- Distribution of telemetry axes.
- Low-flow and pump-off intervals.
- Unit configuration report.
- Other/unprofiled mode report.
- Data quality warnings.

Safety requirement: Profiling is read-only and writes only local artifacts.

#### 4.3.3 Feature module

Responsibilities:

- Build past-only rolling features.
- Specific-energy proxy for health.
- Power/flow/speed/head consistency features.
- First differences.
- Mode context.
- Valid interval flags.

Safety requirement: Feature generation cannot use future windows and cannot use March for training/tuning.

#### 4.3.4 Pillar A health module

Responsibilities:

- Fit baselines: persistence residual, SPC/EWMA/robust z-score, Mahalanobis/robust covariance.
- Train compact learned detector if used.
- Calibrate health scores.
- Freeze thresholds.
- Generate anomaly events.
- Rank contributing variables.
- Run injected-fault evaluation.
- Produce health scorecard.

Safety requirement: Health output is an offline advisory score, not a live alarm or control command.

#### 4.3.5 Pillar B efficiency module

Responsibilities:

- Compute interval energy, volume, and specific energy.
- Filter invalid intervals.
- Build matched-condition historical envelope.
- Compare March actual operation against envelope.
- Align MVPv1 control logs where available.
- Estimate offline kWh opportunity.
- Reject unsupported advisories.
- Produce efficiency scorecard.

Safety requirement: Efficiency output is a historical comparison, not an executable setpoint recommendation.

#### 4.3.6 Evaluation harness module

Responsibilities:

- Freeze configs before March scoring.
- Enforce leakage guard.
- Run locked holdout scoring.
- Compute PASS/FAIL.
- Generate JSON scorecards.
- Generate evidence reports and plots.

Safety requirement: The harness must fail closed if leakage or governance checks fail.

#### 4.3.7 Dashboard/report module

Responsibilities:

- Display offline health timeline.
- Display efficiency opportunity timeline.
- Display scorecards.
- Support filters.
- Export artifacts.

Safety requirement: Dashboard is static or local read-only only. No control widgets.

### 4.4 Evidence artifact locations

Recommended artifact tree:

```text
artifacts/
  runs/
    {run_id}/
      manifest.json
      safety_guard.json
      leakage_guard.json
      config_frozen.yaml
      data_profile/
        schema_report.json
        mode_profile.csv
        missingness_report.csv
        unit_report.json
        plots/
      models/
        pillar_A/
          scaler.pkl
          thresholds.json
          baseline_params.json
          autoencoder.pt
          model_card.md
        pillar_B/
          envelope_index.parquet
          matching_config.json
          unit_config.json
      evaluation/
        scorecard.json
        pillar_A_scorecard.json
        pillar_B_scorecard.json
        injected_fault_results.csv
      evidence/
        health_events.csv
        health_scores.parquet
        efficiency_advisories.csv
        operating_points.parquet
        mvpv1_alignment_report.csv
      reports/
        executive_report.html
        operator_dashboard.html
        evidence_report.pdf
      logs/
        pipeline.jsonl
        stage_timings.json
```

Every artifact must include or link to the safety fields:

```json
{
  "evaluation_mode": "offline_only",
  "write_path": "none",
  "influences_control": false,
  "site_integration_allowed": false
}
```

---

## 5. Feature Specifications — Must-Have

This section defines build-ready requirements for the MVP. Each feature must preserve the offline/no-write/no-actuation boundary.

### 5.1 Common ingest and validation

#### Inputs

- `source1_2025.csv`
- `source1_2026.csv` March 2026 locked holdout
- Optional MVPv1 control logs as offline files
- Configuration file with:
  - site ID = Yilan
  - timestamp column
  - units for flow and power
  - train/validation split dates
  - holdout period
  - mode handling rules
  - safety guard fields

#### Required columns

- `edge_flow`
- `edge_power`
- `edge_pump_speed`
- `node_demand`
- `node_level`
- `node_pressure`
- `edge_status`
- `node_status`
- `auto`
- `manual`

#### Excluded column

- `edge_valve_position` due to 0% coverage.

#### Acceptance criteria

1. The ingest stage rejects any run missing required columns.
2. The ingest stage identifies `node_status` as hydraulic head and prevents binary-status use.
3. The ingest stage produces row counts, date ranges, missingness, mode mix, and checksums.
4. The ingest stage rejects any live connector or URL-like operational endpoint.
5. The ingest stage writes only local artifacts.
6. The ingest stage includes safety metadata in its output.

#### Edge cases

- Duplicate timestamps: reported and either deduplicated by configured rule or fail if ambiguous.
- Missing timestamps: reported as gaps.
- Irregular cadence: reported; rolling features use timestamp-aware windows where possible.
- Missing mode columns: fail.
- Records neither auto nor manual: classified as `other_unprofiled`.
- Flow/power unit missing: Pillar B must fail unit gate and cannot report kWh/m³.

---

### 5.2 Pillar A — Health scoring specification

#### 5.2.1 Inputs

Pillar A uses the 8 active axes and derived features:

Raw axes:

- `edge_flow`
- `edge_power`
- `edge_pump_speed`
- `node_demand`
- `node_level`
- `node_pressure`
- `edge_status`
- `node_status` as hydraulic head

Derived health features:

- Past-only first differences.
- Past-only rolling mean/median/std over 5, 15, and 60 minutes.
- Specific-energy proxy with low-flow guards.
- Power-to-flow relationship.
- Power-to-speed relationship.
- Flow-to-speed relationship.
- Pressure/head consistency.
- Mode context.
- Missingness indicators where needed.

Training data:

- First-pass model uses confirmed 2025 `auto == true` data only.
- Manual and other/unprofiled modes may be scored but not assumed normal.

Holdout:

- March 2026 only after freeze.

#### 5.2.2 Model approach

Pillar A must include interpretable baselines and may include a compact learned detector.

Required baseline detectors:

1. **Persistence residual baseline**
   - Measures absolute change from prior valid timestamp.
   - Used to show that the health detector detects slow/cross-sensor anomalies beyond abrupt change.

2. **Univariate SPC/EWMA/robust z-score**
   - Per-variable and derived-feature control limits.
   - Thresholds fitted on 2025 validation only.

3. **Mahalanobis or robust covariance detector**
   - Multivariate distance on standardized feature vector.
   - Covariance and center fitted on 2025 training/validation only.
   - May be mode-stratified if sufficient data.

Required candidate detector:

4. **Compact learned or nonlinear detector**
   - Preferred: small PyTorch autoencoder.
   - Alternative if stack permits: Isolation Forest-style model.
   - Must be CPU-friendly and deterministic with seed.
   - Must not require edge runtime.

Recommended autoencoder:

- Input: fixed past window of 15–60 minutes.
- Architecture: small dense or 1D temporal autoencoder.
- Loss: masked MSE.
- Early stopping on 2025 validation.
- Thresholds: frozen validation quantiles.
- Attribution: normalized reconstruction error by variable.

#### 5.2.3 Health score

Each detector produces a raw anomaly score. Raw scores are converted to calibrated percentiles or exceedance scores using 2025 validation.

Example fused severity:

```text
severity_t = weighted_percentile_fusion(
  spc_score_t,
  mahalanobis_score_t,
  physical_residual_score_t,
  learned_detector_score_t
)
```

Example health score:

```text
health_score_t = round(100 * (1 - clipped_severity_t), 1)
```

Where:

- 100 = normal/healthy relative to learned envelope.
- 0 = highly abnormal.
- Thresholds are frozen before March scoring.

Severity bands:

| Band | Health Score | Meaning |
|---|---:|---|
| Normal | 80–100 | Within expected envelope |
| Advisory | 60–79 | Mild unusual behavior |
| Warning | 40–59 | Reviewable abnormality |
| High severity | 0–39 | Strong anomaly evidence |

Final band cutoffs must be frozen from 2025 validation and documented in the scorecard.

#### 5.2.4 Outputs

Pillar A outputs:

- `health_scores.parquet` or CSV:
  - timestamp
  - health score
  - severity
  - detector scores
  - mode
  - data quality flags
- `health_events.csv`:
  - event ID
  - start timestamp
  - end timestamp
  - duration
  - min health score
  - max severity
  - mode context
  - detector agreement
  - top contributing variables
  - caveats
- Plots:
  - health score timeline
  - event overlays
  - top variable contributions
- Pillar A scorecard JSON:
  - PASS/FAIL
  - baseline comparisons
  - injected-fault results
  - March anomaly fraction
  - event count/day
  - evidence completeness
  - caveats

#### 5.2.5 Baselines to beat

Pillar A must compare against:

- Persistence residual.
- SPC/EWMA/robust z-score.
- Mahalanobis/Hotelling-style multivariate detector.
- Optional Isolation Forest or equivalent tabular baseline.

#### 5.2.6 Acceptance criteria

1. Pillar A training uses only 2025 training/validation data.
2. March 2026 cannot be read until feature list, scalers, thresholds, model weights, and gates are frozen.
3. The scorecard reports whether Pillar A PASS/FAIL gates were met.
4. A FAIL is preserved and not reworded as success.
5. Every high-severity event includes top contributing variables unless data is insufficient; insufficiency must be flagged.
6. High-severity event generation includes debounce logic to avoid isolated one-point noise.
7. The detector reports event count/day and high-severity time fraction.
8. Injected-fault evaluation includes power degradation, drift, stuck sensor, spike/dropout, and cross-sensor inconsistency.
9. Reports state that statistical anomaly is not confirmed fault diagnosis.
10. No health event can trigger a live alarm, control output, or maintenance workflow.

#### 5.2.7 Edge cases

- Manual mode: score separately or mark context; do not train normal auto envelope on manual unless explicitly configured.
- Other/unprofiled mode: score and label cautiously; do not assume normal.
- Missing values: use masked features and data-quality flags; severe missingness may suppress scoring.
- Low flow: avoid unstable specific-energy proxy.
- Pump-off intervals: treat separately; do not compare to pump-on normal.
- Mode transitions: may cause transient anomalies; mark as transition context.
- Sensor flatline: distinguish real constant operation from stuck sensor using cross-sensor behavior.
- March distribution shift: report as generalization issue, not automatically as equipment fault.

---

### 5.3 Pillar B — Efficiency advisory specification

#### 5.3.1 Inputs

Pillar B uses:

- Telemetry axes:
  - `edge_flow`
  - `edge_power`
  - `edge_pump_speed`
  - `node_demand`
  - `node_level`
  - `node_pressure`
  - `node_status` as hydraulic head
  - `edge_status`
- Mode columns:
  - `auto`
  - `manual`
- Optional MVPv1 logs.
- Unit configuration:
  - power unit, expected kW
  - flow unit, must be convertible to m³/h or equivalent
  - tariff, optional for avoided cost

Training/envelope data:

- 2025 valid intervals only.

Evaluation data:

- March 2026 locked holdout only after freeze.

#### 5.3.2 Specific-energy calculation

Pillar B computes interval-level specific energy:

```text
Energy_kWh = sum(power_kW * delta_hours)
Volume_m3 = sum(flow_m3_per_hour * delta_hours)
SE_kWh_per_m3 = Energy_kWh / Volume_m3
```

Point-level SE may be computed for diagnostics but not used alone for business claims.

Valid interval criteria:

- Pump on, using `edge_status`.
- Flow above configured minimum.
- Power non-missing and physically plausible.
- Flow unit confirmed.
- Interval duration sufficient, e.g. 15 or 30 minutes.
- Missingness below threshold.
- Mode known or explicitly marked.

#### 5.3.3 Model approach

Pillar B uses a conservative matched-condition historical envelope.

For each evaluated interval:

1. Compute actual demand/head/level/pressure/service condition.
2. Search 2025 valid intervals for comparable historical intervals.
3. Match on:
   - `node_demand`
   - hydraulic head from `node_status`
   - `node_level`
   - `node_pressure`
   - delivered flow or service condition
4. Require minimum comparable count.
5. Compute efficient-envelope SE as conservative low quantile:
   - Primary: 25th percentile for robust opportunity.
   - Secondary: 10th percentile for sensitivity.
   - Never use single absolute minimum for primary claim.
6. Identify historically observed pump speed range among efficient comparable intervals.
7. Estimate offline opportunity:

```text
opportunity_kWh = max(0, actual_SE - envelope_SE) * volume_m3
```

8. Compute confidence using:
   - comparable sample count
   - match distance
   - missingness
   - mode quality
   - whether speed/head/flow are within historical observed range

#### 5.3.4 Outputs

Pillar B outputs:

- `operating_points.parquet`:
  - interval start/end
  - actual energy
  - actual volume
  - actual SE
  - demand/head/level/pressure
  - mode
  - validity flags
- `efficiency_advisories.csv`:
  - interval ID
  - actual SE
  - envelope SE
  - SE gap
  - volume
  - estimated kWh opportunity
  - optional avoided cost
  - comparable sample count
  - match distance
  - observed efficient speed range
  - confidence
  - caveats
- `mvpv1_alignment_report.csv`, if logs supplied.
- Pillar B scorecard:
  - coverage
  - valid evaluated volume
  - opportunity
  - exclusions
  - MVPv1 comparison
  - PASS/FAIL

#### 5.3.5 Baselines

Pillar B must compare against:

- Actual March 2026 operation.
- Median matched-condition historical operation.
- 25th-percentile matched historical envelope.
- 10th-percentile sensitivity envelope.
- MVPv1 control logs where time-aligned.
- No-advisory baseline for unsupported intervals.

#### 5.3.6 Acceptance criteria

1. Pillar B refuses to report kWh/m³ if flow/power units are not confirmed.
2. Pillar B computes SE using interval-level energy and volume.
3. Pillar B excludes low-flow, pump-off, missing, invalid, and unsupported intervals.
4. Pillar B builds its historical envelope using 2025 data only.
5. March 2026 cannot tune matching tolerances, quantiles, confidence thresholds, or exclusion rules.
6. Each advisory includes comparable sample count and confidence.
7. Each advisory reports an observed speed range, not an executable setpoint.
8. Advisories outside historically observed speed/head/flow ranges are rejected.
9. Savings are labeled “offline estimated opportunity,” not realized savings.
10. No efficiency advisory can be written to control systems or shown as a command.

#### 5.3.7 Edge cases

- Low flow: suppress SE claim.
- Pump off: suppress efficiency advisory.
- Missing unit configuration: Pillar B FAIL.
- Insufficient historical matches: no advisory.
- Other/unprofiled mode: mark lower confidence or suppress depending on configuration.
- Missing valve position: include caveat.
- Confounded low SE: report confidence and caveat; do not overclaim.
- Extreme March condition not seen in 2025: reject advisory rather than extrapolate.
- MVPv1 logs not aligned: skip comparison and report reason.

---

### 5.4 Offline evaluation harness and scorecard specification

#### Inputs

- Frozen config.
- Data checksums.
- Feature list.
- Scalers.
- Thresholds.
- Pillar A model artifacts.
- Pillar B envelope artifacts.
- March 2026 file.
- Optional MVPv1 logs.
- PASS/FAIL gate definitions.

#### Required scorecard fields

```json
{
  "product": "AquaOptima Pump Station Optimizer Lite",
  "site": "Yilan",
  "evaluation_mode": "offline_only",
  "write_path": "none",
  "influences_control": false,
  "site_integration_allowed": false,
  "train_period": "...",
  "validation_period": "...",
  "holdout_period": "March 2026",
  "data_checksums": {},
  "feature_list": [],
  "leakage_check": "PASS|FAIL",
  "safety_check": "PASS|FAIL",
  "pillar_A_status": "PASS|FAIL",
  "pillar_B_status": "PASS|FAIL",
  "overall_status": "PASS|FAIL",
  "cannot_claim": [],
  "caveats": []
}
```

#### Acceptance criteria

1. Scorecard generation fails if frozen config is missing.
2. Scorecard generation fails if March was accessed by training/tuning stages.
3. Safety check fails if prohibited imports or write connectors are detected.
4. Overall status cannot PASS if leakage or safety fails.
5. Pillar A and B PASS/FAIL are computed from predefined gates.
6. The scorecard includes “cannot claim” statements.
7. The evaluation harness writes local artifacts only.
8. No scorecard result can trigger deployment or control integration.

---

## 6. Data Model

The product data model supports offline evaluation, evidence traceability, and dashboard/report consumption. It does not include control commands, setpoint writes, device outputs, or actuation entities.

### 6.1 Entity overview

| Entity | Purpose |
|---|---|
| `TelemetryWindow` | Time-bounded slice of telemetry used for features and scoring |
| `HealthScore` | Per-timestamp or per-window health score and detector details |
| `AnomalyEvent` | Debounced event interval derived from health scores |
| `OperatingPoint` | Aggregated interval used for efficiency analysis |
| `EfficiencyAdvisory` | Offline matched-condition efficiency opportunity |
| `Scorecard` | PASS/FAIL evaluation summary |
| `EvidenceReport` | Human-readable bundle of scorecards, plots, tables, caveats |

### 6.2 TelemetryWindow

Represents a fixed window of telemetry.

Fields:

| Field | Type | Description |
|---|---|---|
| `window_id` | string | Unique ID |
| `site_id` | string | Must be Yilan for MVP |
| `start_ts` | datetime | Window start |
| `end_ts` | datetime | Window end |
| `source_dataset` | enum | `train_2025`, `validation_2025`, `holdout_2026_march` |
| `mode` | enum | `auto`, `manual`, `other_unprofiled`, `mixed` |
| `raw_values_ref` | string | Pointer to local artifact |
| `feature_vector_ref` | string | Pointer to feature artifact |
| `data_quality_flags` | array | Missing, low-flow, gap, duplicate, etc. |
| `safety_context` | object | Offline/no-write metadata |

Relationships:

- One `TelemetryWindow` may have zero or one `HealthScore`.
- One `TelemetryWindow` may contribute to one `OperatingPoint`.
- Many `TelemetryWindow` records can be grouped into an `AnomalyEvent`.

### 6.3 HealthScore

Fields:

| Field | Type | Description |
|---|---|---|
| `health_score_id` | string | Unique ID |
| `window_id` | string | FK to `TelemetryWindow` |
| `timestamp` | datetime | Score timestamp |
| `health_score` | float | 0–100 |
| `severity_band` | enum | normal/advisory/warning/high |
| `spc_score` | float | Baseline score |
| `mahalanobis_score` | float | Multivariate score |
| `persistence_residual_score` | float | Persistence baseline score |
| `physical_residual_score` | float | Power/flow/head/speed residual |
| `learned_detector_score` | float | AE or nonlinear detector score |
| `top_contributors` | array | Ranked variables |
| `threshold_version` | string | Frozen threshold ID |
| `model_version` | string | Frozen model ID |
| `advisory_only` | boolean | Always true |

Relationships:

- Many `HealthScore` records can form one `AnomalyEvent`.

### 6.4 AnomalyEvent

Fields:

| Field | Type | Description |
|---|---|---|
| `event_id` | string | Unique ID |
| `site_id` | string | Yilan |
| `start_ts` | datetime | Event start |
| `end_ts` | datetime | Event end |
| `duration_minutes` | float | Duration |
| `min_health_score` | float | Worst score |
| `max_severity_band` | enum | Highest severity |
| `mode_context` | enum | auto/manual/other/mixed |
| `detector_agreement` | object | Detectors contributing |
| `top_contributors` | array | Variables |
| `data_quality_flags` | array | Caveats |
| `confirmed_fault` | nullable boolean | Null unless external label supplied |
| `control_action_taken` | boolean | Always false |

### 6.5 OperatingPoint

Fields:

| Field | Type | Description |
|---|---|---|
| `operating_point_id` | string | Unique ID |
| `site_id` | string | Yilan |
| `start_ts` | datetime | Interval start |
| `end_ts` | datetime | Interval end |
| `mode` | enum | auto/manual/other/mixed |
| `energy_kwh` | float | Interval energy |
| `volume_m3` | float | Interval volume |
| `specific_energy_kwh_per_m3` | float | Energy/volume |
| `avg_flow` | float | Average flow |
| `avg_power` | float | Average power |
| `avg_speed` | float | Average pump speed |
| `avg_demand` | float | Average demand |
| `avg_head_m` | float | From `node_status` |
| `avg_level` | float | Node level |
| `avg_pressure` | float | Node pressure |
| `valid_for_efficiency` | boolean | Eligibility |
| `exclusion_reasons` | array | If invalid |

Relationships:

- One `OperatingPoint` may have zero or one `EfficiencyAdvisory`.
- Many historical `OperatingPoint` records support one advisory.

### 6.6 EfficiencyAdvisory

Fields:

| Field | Type | Description |
|---|---|---|
| `advisory_id` | string | Unique ID |
| `operating_point_id` | string | FK to evaluated point |
| `actual_se` | float | Actual kWh/m³ |
| `envelope_se_p25` | float | Conservative envelope |
| `envelope_se_p10` | float | Sensitivity envelope |
| `se_gap` | float | Actual minus envelope |
| `estimated_kwh_opportunity` | float | Offline opportunity |
| `estimated_cost_opportunity` | nullable float | If tariff supplied |
| `comparable_count` | int | Historical support |
| `match_distance` | float | Similarity distance |
| `observed_speed_range_min` | float | Historical efficient range |
| `observed_speed_range_max` | float | Historical efficient range |
| `confidence_score` | float | 0–1 |
| `unsupported` | boolean | True if no advisory |
| `rejection_reasons` | array | If unsupported |
| `advisory_only` | boolean | Always true |
| `control_endpoint` | null | Always null |

### 6.7 Scorecard

Fields:

| Field | Type |
|---|---|
| `scorecard_id` | string |
| `run_id` | string |
| `site_id` | string |
| `evaluation_mode` | string, must be `offline_only` |
| `write_path` | string, must be `none` |
| `influences_control` | boolean, must be false |
| `site_integration_allowed` | boolean, must be false |
| `leakage_check` | enum |
| `safety_check` | enum |
| `pillar_A_status` | enum |
| `pillar_B_status` | enum |
| `overall_status` | enum |
| `metrics` | object |
| `caveats` | array |
| `cannot_claim` | array |

### 6.8 EvidenceReport

Fields:

| Field | Type |
|---|---|
| `report_id` | string |
| `run_id` | string |
| `scorecard_id` | string |
| `artifact_paths` | array |
| `summary_text` | string |
| `plant_manager_summary` | object |
| `operator_summary` | object |
| `ml_audit_summary` | object |
| `safety_banner` | string |
| `generated_at` | datetime |

Safety note: There is intentionally no `ControlCommand`, `SetpointWrite`, `ActuationRequest`, or `DeviceOutput` entity in the data model.

---

## 7. API / Interface Design

The primary interface is an offline CLI. An optional local read-only API may serve a static dashboard. There are no control endpoints.

### 7.1 Offline CLI

#### Command: profile data

```bash
aopso-lite profile \
  --site yilan \
  --telemetry-2025 data/source1_2025.csv \
  --telemetry-2026 data/source1_2026.csv \
  --config configs/yilan_units.yaml \
  --out artifacts/runs/{run_id}/data_profile
```

Purpose:

- Validate schema.
- Compute mode profile.
- Validate units.
- Capture checksums.
- Produce safety and leakage precheck.

Acceptance criteria:

- Rejects missing required columns.
- Rejects live endpoints.
- Writes local artifacts only.

#### Command: train Pillar A

```bash
aopso-lite train-health \
  --site yilan \
  --telemetry-2025 data/source1_2025.csv \
  --config configs/health_train.yaml \
  --out artifacts/runs/{run_id}/models/pillar_A
```

Purpose:

- Train baselines and candidate detector on 2025 only.
- Freeze thresholds.
- Run 2025 validation evaluation.

Acceptance criteria:

- Fails if March 2026 file is provided or read.
- Saves frozen model, scalers, thresholds, gates.
- Includes no edge/control imports.

#### Command: evaluate injected faults

```bash
aopso-lite eval-health-injections \
  --site yilan \
  --health-artifacts artifacts/runs/{run_id}/models/pillar_A \
  --telemetry-2025 data/source1_2025.csv \
  --config configs/injections.yaml \
  --out artifacts/runs/{run_id}/evaluation/injected_fault_results.csv
```

Purpose:

- Evaluate sensitivity to synthetic faults.

Acceptance criteria:

- Reports AUROC, delay, attribution metrics.
- Labels results as synthetic sensitivity only.

#### Command: build efficiency envelope

```bash
aopso-lite build-efficiency-envelope \
  --site yilan \
  --telemetry-2025 data/source1_2025.csv \
  --config configs/efficiency_envelope.yaml \
  --out artifacts/runs/{run_id}/models/pillar_B
```

Purpose:

- Compute valid intervals.
- Build matched-condition envelope.

Acceptance criteria:

- Fails without confirmed units.
- Fails if March data is read.
- Rejects unsupported/unobserved operating regions.

#### Command: freeze evaluation

```bash
aopso-lite freeze \
  --site yilan \
  --health-artifacts artifacts/runs/{run_id}/models/pillar_A \
  --efficiency-artifacts artifacts/runs/{run_id}/models/pillar_B \
  --gates configs/gates.yaml \
  --out artifacts/runs/{run_id}/config_frozen.yaml
```

Purpose:

- Create immutable evaluation package.

Acceptance criteria:

- Saves feature list, scalers, thresholds, gates, matching rules, checksums.
- Writes safety metadata.
- Blocks changes before March scoring.

#### Command: score locked March

```bash
aopso-lite score-holdout \
  --site yilan \
  --frozen-config artifacts/runs/{run_id}/config_frozen.yaml \
  --telemetry-2026 data/source1_2026.csv \
  --mvpv1-logs data/mvpv1_logs.csv \
  --out artifacts/runs/{run_id}/evaluation
```

Purpose:

- Score locked March 2026.

Acceptance criteria:

- Fails if frozen config missing.
- Fails if leakage guard fails.
- Produces scorecards and evidence tables.
- Does not tune anything.

#### Command: export report

```bash
aopso-lite export-report \
  --site yilan \
  --run artifacts/runs/{run_id} \
  --format html,pdf,csv,json \
  --out artifacts/runs/{run_id}/reports
```

Purpose:

- Generate human-readable and machine-readable offline evidence.

Acceptance criteria:

- Every report includes safety banner.
- No output includes executable control instruction.

### 7.2 Optional local read-only API

If a dashboard needs local interactive views, it may use a local API bound to localhost only.

Example endpoints:

```http
GET /api/v1/scorecard
GET /api/v1/health/scores
GET /api/v1/health/events
GET /api/v1/efficiency/operating-points
GET /api/v1/efficiency/advisories
GET /api/v1/reports/{report_id}
GET /api/v1/artifacts/manifest
```

Response safety fields must be included:

```json
{
  "evaluation_mode": "offline_only",
  "write_path": "none",
  "influences_control": false,
  "site_integration_allowed": false,
  "data": {}
}
```

### 7.3 Explicitly prohibited endpoints

The product must not implement:

```http
POST /setpoint
POST /control
POST /execute
POST /actuate
POST /hmi
POST /pac
POST /codesys
POST /amax
POST /ethercat
POST /scada
POST /historian/write
PUT /api/v1/control/*
PATCH /api/v1/control/*
DELETE /api/v1/control/*
```

No API endpoint may write to operational systems. No API endpoint may imply live monitoring or control. Any future proposal for control integration requires a separate safety qualification outside this PRD.

---

## 8. Non-Functional Requirements

All non-functional requirements preserve the offline/no-write/no-actuation boundary.

### 8.1 Performance

Target environment:

- CPU-only execution.
- Single-site dataset scale:
  - 2025: ~489K rows
  - March 2026: ~44K rows
- No GPU requirement.

Performance targets:

| Stage | Target |
|---|---:|
| Data profile | < 10 minutes CPU |
| Pillar A baseline training | < 20 minutes CPU |
| Pillar A compact autoencoder training | < 60 minutes CPU |
| Pillar B envelope build | < 30 minutes CPU |
| March scoring | < 15 minutes CPU |
| Report export | < 10 minutes CPU |

If targets are exceeded, the run may still be valid but must report timing in logs.

### 8.2 Determinism and reproducibility

Requirements:

1. All random seeds must be configurable and saved.
2. Chronological splits must be explicit.
3. Config hashes must be saved.
4. Input file checksums must be saved.
5. Model weights, thresholds, scalers, and matching tolerances must be versioned.
6. Re-running the same frozen config on same data should reproduce scorecards within deterministic tolerance.
7. Scorecards must include code version or commit hash where available.

### 8.3 Data leakage guard

Requirements:

1. March 2026 file path may not be read by training/tuning stages.
2. Any attempt to read March during training/tuning fails closed.
3. File access manifests must record all files read by each stage.
4. Holdout scoring requires a frozen config.
5. No post-hoc threshold tuning on March.
6. No model selection based on March metrics.
7. Leakage failure forces overall scorecard FAIL regardless of model metrics.

### 8.4 Security and governance

Requirements:

1. Local file operation only.
2. No live connector support.
3. No write-capable OT package imports.
4. Prohibited import scan must include:
   - `aquaoptima.edge`
   - `contracts.edge`
   - configured AMAX/CODESYS/PAC/HMI/control connector packages
5. Reports must include offline advisory caveats.
6. Artifacts must not contain credentials.
7. Optional local API must bind to localhost unless explicitly configured for offline local network review; even then, read-only only.
8. No cloud upload unless separately approved outside this PRD.

### 8.5 Accessibility and usability

Requirements:

1. Dashboard/report must use clear language for non-ML users.
2. Color severity must include text labels, not color alone.
3. Efficiency advisories must say “historically observed range,” not “setpoint.”
4. PASS/FAIL must be visible.
5. Caveats must be visible on summary pages.
6. Tables must be exportable to CSV.
7. Plant-manager summary must include:
   - high-severity event count
   - reviewable alert volume
   - estimated offline kWh opportunity
   - optional avoided cost if tariff supplied
   - confidence and caveats

### 8.6 Reliability

Requirements:

1. Pipeline failures must be explicit.
2. Partial outputs must be marked incomplete.
3. Invalid unit configuration must block Pillar B.
4. Missing labels must block fault-recall claims.
5. Unsupported intervals must not produce advisories.
6. Safety or leakage failure must block PASS.

### 8.7 Single-site scale

This product is scoped to Yilan only.

Requirements:

1. Site ID must be explicit.
2. Multi-site ingestion is out of scope.
3. No fleet benchmark claims.
4. Models and thresholds are site-specific.
5. Reports must state single-site limitation.

### 8.8 Honest evaluation

Requirements:

1. FAIL is an acceptable product outcome.
2. The product must never suppress failed metrics.
3. Scorecards must include “cannot claim” statements:
   - Cannot claim true field fault recall without labels.
   - Cannot claim realized energy savings without prospective validation.
   - Cannot claim safe executable setpoints.
   - Cannot claim multi-site generalization.
   - Cannot claim control improvement unless MVPv1 comparison is valid.

---

## 9. Sprint Plan — AOPSO Ladder After Sprint 26

Only Sprint 27 is **Planned**. All later sprints are **Backlog** and remain gated by evidence from the previous sprint. Edge deployment, site integration, and control packaging are not part of this plan.

### Sprint 27 — Planned  
**Title:** Data profile, safety guardrails, leakage guard, and unit validation

**Goal:** Establish trustworthy offline foundation before modeling.

**Deliverables:**

- Offline ingest CLI.
- Schema validator.
- Mode profile for 2025.
- Data quality report for 2025 and March 2026.
- Unit configuration gate for flow/power.
- Leakage guard implementation.
- Safety guard implementation.
- Prohibited import scan.
- Artifact manifest and run logs.

**Verification gate:**

PASS if:

1. Required telemetry columns are validated.
2. `node_status` is mapped as hydraulic head.
3. `edge_valve_position` is excluded.
4. Mode mix is reported, including other/unprofiled bucket.
5. March 2026 is protected from training/tuning stages.
6. Safety metadata is present.
7. No prohibited imports or write paths are detected.

FAIL if any safety, schema, or leakage check fails.

**Safety boundary:** Offline files only; no live connectors; no write path.

---

### Sprint 28 — Backlog, pending Sprint 27 PASS  
**Title:** Pillar A interpretable health baselines

**Goal:** Build health baselines before learned models.

**Deliverables:**

- Persistence residual baseline.
- SPC/EWMA/robust z-score baseline.
- Mahalanobis/robust covariance baseline.
- Past-only health feature pipeline.
- 2025 validation score distributions.
- Initial health score formula.
- Event debounce logic.
- Baseline health scorecard on 2025 validation only.

**Verification gate:**

PASS if:

1. All baselines run on 2025 only.
2. Thresholds are selected from 2025 validation only.
3. Event outputs include severity and contributors where possible.
4. Baseline metrics are reproducible.
5. March is not read.

FAIL if thresholds or features depend on March.

**Safety boundary:** Health events are offline evidence only and cannot trigger alarms or control actions.

---

### Sprint 29 — Backlog, pending Sprint 28 PASS  
**Title:** Pillar A compact detector and injected-fault harness

**Goal:** Add learned/nonlinear detector and prove sensitivity on defined faults.

**Deliverables:**

- Compact autoencoder or approved nonlinear detector.
- Training on 2025 auto-mode only.
- Frozen model artifacts.
- Injected-fault generator:
  - power degradation
  - flow drift
  - pressure drift
  - stuck sensor
  - spike/dropout
  - cross-sensor inconsistency
- Attribution metrics.
- Pillar A candidate gates frozen.

**Verification gate:**

PASS if:

1. Learned detector improves on at least one important multivariate/injected fault class without unacceptable false alarm increase.
2. +10% power degradation is detected materially earlier than persistence residual.
3. Top-contributor attribution includes injected variable in target share of injected cases.
4. Gates are frozen before March scoring.
5. No March access.

FAIL if learned detector adds no value and ensemble cannot justify PASS; the product may continue with baselines only if gates are updated before holdout and documented.

**Safety boundary:** Detector output remains offline advisory evidence only.

---

### Sprint 30 — Backlog, pending Sprint 29 PASS  
**Title:** Pillar A locked March evaluation

**Goal:** Run honest Pillar A holdout evaluation.

**Deliverables:**

- Frozen Pillar A scoring on March 2026.
- Pillar A scorecard.
- Health event table.
- Health timeline plots.
- PASS/FAIL verdict.
- Caveats and cannot-claim section.

**Verification gate:**

PASS if Pillar A meets predefined gates for reviewability, injected-fault sensitivity, evidence completeness, baseline comparison, and leakage/safety.

FAIL if gates are not met. FAIL must be reported honestly.

**Safety boundary:** March scoring reads offline holdout only and produces files only.

---

### Sprint 31 — Backlog, pending Sprint 30 completed with explicit PASS/FAIL  
**Title:** Pillar B specific-energy engine

**Goal:** Build correct energy/volume accounting and valid interval aggregation.

**Deliverables:**

- Unit-confirmed SE calculation.
- Valid interval filters.
- 15/30-minute aggregation.
- Low-flow/pump-off exclusion.
- OperatingPoint entity export.
- Pillar B unit and validity scorecard.

**Verification gate:**

PASS if:

1. Units are confirmed.
2. SE is calculated from interval energy and volume.
3. Invalid intervals are excluded with reasons.
4. 2025-only aggregation works reproducibly.
5. March is not used for tuning.

FAIL if unit ambiguity remains.

**Safety boundary:** No setpoints, no control language, no live integration.

---

### Sprint 32 — Backlog, pending Sprint 31 PASS  
**Title:** Pillar B matched-condition efficiency envelope and MVPv1 alignment

**Goal:** Build conservative historical efficiency advisory engine.

**Deliverables:**

- Matched-condition search.
- 25th and 10th percentile SE envelopes.
- Comparable sample count and match distance.
- Observed efficient speed range extraction.
- Unsupported interval rejection.
- MVPv1 log alignment report.
- Pillar B gates frozen.

**Verification gate:**

PASS if:

1. Advisories require minimum historical support.
2. All speed ranges are historically observed.
3. Unsupported intervals are rejected.
4. MVPv1 comparison is only produced where aligned.
5. Matching tolerances and quantiles are frozen before March.

FAIL if advisories rely on extrapolation or unconfirmed data.

**Safety boundary:** Speed ranges are evidence, not executable recommendations.

---

### Sprint 33 — Backlog, pending Sprint 32 PASS  
**Title:** Pillar B locked March evaluation

**Goal:** Run honest Pillar B holdout evaluation.

**Deliverables:**

- March 2026 efficiency advisories.
- Coverage and exclusion waterfall.
- Estimated offline kWh opportunity.
- Optional avoided cost if tariff provided.
- MVPv1 comparison where valid.
- Pillar B scorecard.
- PASS/FAIL verdict.

**Verification gate:**

PASS if:

1. Coverage is meaningful or limitations are clearly explained.
2. Positive opportunity is robust under conservative quantile.
3. No unsupported intervals produce savings claims.
4. MVPv1 comparison is valid where reported.
5. Leakage and safety checks pass.

FAIL if opportunity is not robust or relies on unsafe extrapolation.

**Safety boundary:** Output remains counterfactual offline opportunity only.

---

### Sprint 34 — Backlog, pending Pillar A and Pillar B explicit verdicts  
**Title:** Unified A+B offline evidence package

**Goal:** Package the product as a unified advisory evidence bundle only after both pillars have honest verdicts.

**Deliverables:**

- Unified scorecard.
- Static dashboard or local read-only dashboard.
- Executive report.
- Health event export.
- Efficiency advisory export.
- Artifact manifest.
- Plant-manager summary.
- ML audit appendix.

**Verification gate:**

PASS if:

1. Unified report includes Pillar A and Pillar B PASS/FAIL.
2. Safety banner appears everywhere.
3. No control endpoints or UI controls exist.
4. Leakage and safety checks pass.
5. Reports include cannot-claim statements.
6. Edge/site/control packaging remains blocked.

FAIL if packaging implies deployment readiness, actuation, or control influence.

**Safety boundary:** Even after successful packaging, site integration is not allowed in this version.

### Packaging unblock policy

No packaging beyond offline evidence export is allowed unless:

1. Pillar A has explicit PASS or documented FAIL with scope decision.
2. Pillar B has explicit PASS or documented FAIL with scope decision.
3. Safety and leakage checks PASS.
4. A future separate qualification authorizes any deployment discussion.

This PRD does **not** unblock edge deployment or control integration.

---

## 10. Open Questions & Risks

All risks must be managed without crossing the offline/no-write/no-actuation boundary.

### 10.1 Open questions

#### Q1. What exactly is in the 31.6% other/unprofiled mode bucket?

Risk: The other bucket may include communications gaps, fallback operation, maintenance, transition states, or bad encodings. If treated as normal, it can corrupt Pillar A. If treated as efficient, it can corrupt Pillar B.

Required next step:

- Sprint 27 mode profile must characterize this bucket before any inclusion in training.
- Default behavior: exclude from normal training and mark as unprofiled.

#### Q2. Are flow and power units confirmed?

Risk: Incorrect units invalidate kWh/m³ and savings claims.

Required next step:

- Unit config must be explicit.
- Pillar B must FAIL if units are not confirmed.

#### Q3. Are true fault labels available?

Risk: Without true fault labels, Pillar A cannot claim real-world fault recall or predictive maintenance accuracy.

Required next step:

- Use injected faults and proxy labels.
- If operator notes or maintenance logs exist, ingest them offline only and treat them as optional labels.

#### Q4. What is the semantic source of `node_demand`?

Risk: Demand could be measured, forecast, derived, or control target. Its meaning affects matching.

Required next step:

- Data dictionary confirmation.
- Sensitivity analysis if semantics remain uncertain.

#### Q5. How reliable are MVPv1 control logs?

Risk: Misaligned logs could create false conclusions about advisory value versus prior operation.

Required next step:

- Build alignment diagnostics.
- Report comparison only where quality is sufficient.

#### Q6. What tariff should be used for avoided cost?

Risk: Wrong tariff overstates business value.

Required next step:

- Tariff is optional offline input.
- If absent, report kWh only.

### 10.2 Key risks and mitigations

| Risk | Severity | Impact | Mitigation |
|---|---:|---|---|
| March leakage | High | Invalid benchmark | File access manifest, frozen config, fail-closed leakage guard |
| Safety boundary breach | High | OT risk and product disqualification | Prohibited imports, no connectors, no control endpoints, safety checks |
| Other mode contamination | High | Bad normal/efficiency envelope | Profile separately; exclude by default |
| Label scarcity for anomalies | High | Cannot prove field fault recall | Use injected faults, proxy labels, honest caveats |
| Overclaiming savings | High | Loss of trust; bad business decisions | Phrase as offline opportunity only; conservative quantiles; caveats |
| Flow unit uncertainty | High | Wrong SE | Unit gate; fail if unknown |
| Low-flow SE instability | High | False savings | Minimum flow threshold; interval aggregation |
| Missing valve position | Medium/High | Unobserved hydraulic confounding | Caveat; conservative matching; reject low confidence |
| MVPv1 alignment errors | Medium | Invalid comparator | Alignment report; compare only valid overlaps |
| Over-alerting | Medium | Operator fatigue | Debounce; severity bands; event/day gate |
| Under-alerting | Medium | Missed abnormality | Injected sensitivity tests; baseline comparison |
| Model overfitting | Medium | Poor holdout behavior | Chronological validation; simple baselines; locked March |
| Unseen March operating regimes | Medium | Unsupported advisories | Reject rather than extrapolate |
| Users interpret advisory as command | High | Unsafe operation | Persistent banners; no setpoint wording; no write path |
| Both pillars fail | High | Product may not have value | Honest stop/pivot contingency |

### 10.3 Honesty risk: overclaiming savings

This is one of the largest product risks. Pillar B must not say:

- “AquaOptima will save X%.”
- “Run the pump at speed Y.”
- “The setpoint is safe.”
- “The advisory outperforms control.”
- “Savings are guaranteed.”

Allowed language:

- “In offline historical replay, AquaOptima identified an estimated opportunity of X kWh over evaluated intervals.”
- “Under similar historical demand/head/level/pressure conditions, lower specific energy was observed at speed range X–Y.”
- “This is a counterfactual offline estimate requiring future operational validation.”
- “No control action was taken.”

Acceptance criterion: Reports must include a “cannot claim” section and must use offline opportunity language.

### 10.4 Label scarcity risk for anomalies

Because true fault labels are absent or limited, Pillar A must be positioned as health/anomaly advisory, not proven predictive maintenance.

Allowed claims:

- Sensitivity to injected power degradation.
- Sensitivity to sensor drift/stuck/spike scenarios.
- Reviewable anomaly event rate.
- Cross-sensor abnormality detection relative to baselines.
- Potential earlier warning for documented offline events, if logs exist.

Not allowed:

- Field fault recall.
- Mean time to failure prediction.
- Maintenance diagnosis.
- Safety-certified alarming.

Acceptance criterion: Pillar A report must clearly distinguish statistical anomaly from confirmed equipment fault.

### 10.5 The “both pillars fail” contingency

If Pillar A and Pillar B both fail their gates, the correct response is not to repackage the result as success.

Contingency plan:

1. Publish the unified scorecard with both FAIL verdicts.
2. Preserve all evidence artifacts.
3. Identify whether failure was due to:
   - data quality
   - missing labels
   - insufficient mode clarity
   - lack of efficiency variation
   - sensor/unit uncertainty
   - true absence of advisory signal
4. Recommend one of three paths:
   - **Data remediation path:** obtain better labels, units, valve state, maintenance logs, or mode definitions.
   - **Scope reduction path:** keep only data profiling and reporting as a paid diagnostic.
   - **Stop/pause path:** do not continue productization for this site until better evidence exists.
5. Do not deploy, integrate, or imply value.

Acceptance criterion: A dual-FAIL result blocks Sprint 34 packaging except for an honest failure report bundle.

### 10.6 Final risk position

AquaOptima Pump Station Optimizer Lite should proceed only as an offline advisory evidence product. The product’s credibility depends on three disciplines:

1. **Respect the OT boundary:** no write path, no actuation, no control influence.
2. **Respect the holdout:** March 2026 remains locked until freeze.
3. **Respect negative evidence:** PASS and FAIL are both valid outcomes.

If Pillar A passes, the site gets reviewable earlier-warning evidence. If Pillar B passes, the site gets quantified offline energy opportunity. If both pass, the plant manager gets a credible offline decision package: where the station looked unhealthy, where energy intensity looked improvable, how much opportunity may exist, and what must be validated before operational change.

The product must never cross from advisory evidence into control.