# AquaOptima Pump Station Optimizer Lite — Health & Efficiency Advisory A+B  
## MoSCoW Features List + User Stories

**Product scope:** Single-site Yilan pump station offline evidence product.  
**Product boundary:** Offline files only; no write path; no actuation; no site integration; March 2026 locked holdout; honest PASS/FAIL evaluation.

---

## 1. Pillar A — Health / Anomaly Detection

### Must Have

- Learn a **normal multivariate operating envelope** from 2025 data only, primarily confirmed `auto == true` records.
- Produce an offline **health score**, e.g. 0–100, for each evaluated timestamp or interval.
- Produce binary or graded **anomaly flags** using thresholds frozen from 2025 validation data before March 2026 scoring.
- Include interpretable baseline detectors:
  - Persistence residual baseline.
  - Univariate SPC / EWMA / robust z-score.
  - Mahalanobis / robust covariance or equivalent multivariate distance.
- Include at least one compact learned or nonlinear detector candidate, e.g. autoencoder or Isolation Forest-style model, if supported by the allowed offline stack.
- Use active Yilan telemetry axes:
  - `edge_flow`
  - `edge_power`
  - `edge_pump_speed`
  - `node_demand`
  - `node_level`
  - `node_pressure`
  - `edge_status`
  - `node_status` interpreted as hydraulic head, not binary status.
- Exclude `edge_valve_position` from modeling because coverage is 0%.
- Engineer health features using past-only transformations:
  - Specific-energy proxy.
  - Power/flow/speed/head consistency.
  - First differences.
  - Rolling 5, 15, and 60 minute past-only statistics.
- Generate event-level anomaly summaries, not just point-level flags.
- Rank contributing variables for every high-severity health event where enough data exists.
- Evaluate on March 2026 only after model, scaler, feature list, and thresholds are frozen.
- Report honest PASS/FAIL against predefined Pillar A gates.

### Should Have

- Mode-aware health scoring that separately reports behavior for auto, manual, and other/unprofiled modes.
- Event debouncing to reduce noisy single-point alerts.
- Physical residual checks, especially “power high for matched flow/head/speed.”
- Injected-fault evaluation for:
  - Power degradation.
  - Flow drift.
  - Pressure drift.
  - Stuck sensor.
  - Spike/dropout.
  - Cross-sensor inconsistency.
- Variable attribution accuracy metric for injected faults.
- Alert reviewability metrics:
  - Event count per day.
  - Percent time in high-severity alarm.
  - Median and maximum event duration.

### Could Have

- Separate normal-envelope models by operating regime if 2025 profiling shows enough clean data.
- Compact temporal convolutional autoencoder if it materially improves injected-fault detection over simpler baselines.
- Proxy-label evaluation using mode transitions, extreme pressure/head/level events, or known control log events.
- Configurable severity bands, e.g. advisory, warning, high severity, while still frozen before March holdout scoring.

### Won’t Have This Version

- Real-time online anomaly detection.
- Predictive maintenance claims based on true fault recall, because confirmed field fault labels are not available.
- Automatic maintenance ticket creation in CMMS.
- Live alarm delivery to HMI, SCADA, PAC, AMAX, EtherCAT, or CODESYS.
- Any write-back, control action, speed command, or automatic pump recommendation for execution.
- Multi-site anomaly models or generalized SaaS benchmarking.

---

## 2. Pillar B — Efficiency Advisory

### Must Have

- Compute offline **specific energy** for valid pumped intervals:

  \[
  SE = \frac{Energy}{Volume}
  \]

  with unit handling explicitly validated before reporting kWh/m³.
- Filter out invalid low-flow, missing, pump-off, or unreliable intervals before SE calculation.
- Aggregate efficiency analysis over stable intervals, e.g. 15 or 30 minutes, not only noisy point-level data.
- Learn a conservative **matched-condition efficiency envelope** from 2025 data only.
- Match comparable historical intervals using:
  - `node_demand`
  - hydraulic head from `node_status`
  - `node_level`
  - `node_pressure`
  - delivered flow/service condition where appropriate.
- Use historically realized lower-specific-energy intervals only; do not extrapolate into unobserved speed/head/flow regions.
- Report observed efficient **pump speed ranges** as advisory evidence, not exact executable setpoints.
- Estimate offline opportunity:

  \[
  Savings_{kWh} = \max(0, SE_{actual} - SE_{envelope}) \times Volume
  \]

- Include confidence indicators based on:
  - Comparable sample count.
  - Match distance.
  - data quality.
  - whether candidate speed ranges were historically observed.
- Compare against relevant baselines:
  - Actual March 2026 operation.
  - 2025 matched historical operation.
  - Median matched-condition operation.
  - MVPv1 control logs where time-aligned.
  - Conservative low-quantile historical SE envelope.
- Report honest PASS/FAIL against predefined Pillar B gates.
- Clearly label all savings as **offline estimated opportunity**, not realized savings.

### Should Have

- Conservative quantile options, e.g. 10th and 25th percentile SE, with 25th percentile used for robustness checks.
- Separate efficiency analysis by auto, manual, and other/unprofiled modes after profiling.
- Coverage reporting:
  - Percent of valid pumped volume covered by confident advisories.
  - Percent excluded due to missing data, low flow, poor match, or unprofiled mode.
- MVPv1 control log alignment quality checks.
- Advisory language that states: “Historically, under similar conditions, the station achieved lower specific energy at observed speed range X–Y.”

### Could Have

- Affinity-law diagnostic features as guardrails:
  - \(Q \propto N\)
  - \(H \propto N^2\)
  - \(P \propto N^3\)
- Confidence-adjusted savings estimates.
- Monthly or shift-level opportunity rollups.
- Sensitivity analysis showing opportunity under multiple match tolerances.

### Won’t Have This Version

- Closed-loop optimization.
- Reinforcement learning control.
- Direct pump-speed optimization for execution.
- Any command to PAC, HMI, AMAX, EtherCAT, CODESYS, or field I/O.
- Claims of guaranteed or realized energy savings.
- Safety-certified setpoint recommendations.
- Advisories outside historically observed operating envelopes.
- Multi-pump sequencing optimization unless already visible and safely represented in the offline historical data.

---

## 3. Data & Ingest — Offline Files

### Must Have

- Ingest historical offline files only:
  - `source1_2025.csv`
  - `source1_2026.csv`
  - MVPv1 control logs, if supplied as offline files.
- Enforce Yilan single-site scope.
- Validate schema for all required active telemetry axes.
- Validate timestamp ordering, cadence, duplicate timestamps, gaps, and missingness.
- Recognize true mode columns:
  - `auto`
  - `manual`
- Treat records that are neither auto nor manual as **other/unprofiled**, not automatically normal.
- Internally rename or document `node_status` as hydraulic head to prevent binary-status misuse.
- Exclude `edge_valve_position` or mark unavailable because coverage is 0%.
- Confirm or require explicit configuration of flow and power units before SE reporting.
- Produce a data-profile artifact before model training or March holdout scoring.
- Prevent March 2026 data from being read by any training, scaler fitting, feature selection, threshold tuning, or model-selection process.

### Should Have

- Mode-profile report for 2025:
  - Distribution of active axes by mode.
  - Missingness by mode.
  - Specific energy by mode.
  - Time-of-day and month distribution by mode.
  - Mode transition durations.
- Low-flow and pump-off interval classification.
- MVPv1 log time-alignment diagnostics.
- File checksum capture for reproducibility.

### Could Have

- Offline data dictionary export.
- Unit conversion helper for known flow-unit variants.
- Gap-filling diagnostics, while preserving original raw values.
- Configurable exclusion rules for maintenance periods if supplied as offline logs.

### Won’t Have This Version

- Live historian connection.
- SCADA, OPC UA, Modbus, MQTT, EtherCAT, PAC, HMI, or CODESYS integration.
- Cloud streaming ingest.
- Automatic site discovery.
- Multi-site ingestion.
- Any write-back to source systems.
- Any ingestion path that can influence control.

---

## 4. Evaluation & Scorecards

### Must Have

- Generate frozen evaluation configs before March 2026 scoring.
- Enforce March 2026 as locked holdout.
- Produce machine-readable scorecard JSON with:
  - `evaluation_mode = offline_only`
  - `write_path = none`
  - `influences_control = false`
  - `site_integration_allowed = false`
  - train period.
  - validation period.
  - holdout period.
  - feature list.
  - scaler and threshold provenance.
  - leakage check result.
  - Pillar A PASS/FAIL.
  - Pillar B PASS/FAIL.
  - caveats.
- Pillar A scorecard must include:
  - March anomaly time fraction.
  - Event count per day.
  - Event durations.
  - injected-fault AUROC or equivalent sensitivity metrics.
  - detection delay for injected faults.
  - baseline comparisons.
  - evidence completeness.
- Pillar B scorecard must include:
  - valid evaluated volume.
  - coverage rate.
  - actual SE.
  - matched-envelope SE.
  - estimated kWh opportunity.
  - comparable sample counts.
  - MVPv1 comparison where available.
  - unsafe or unsupported advisory rejection count.
- Scorecards must support honest PASS/FAIL; failures must be reported without suppression.

### Should Have

- Human-readable evaluation summary alongside JSON.
- Separate “cannot claim” section to prevent overstatement.
- Baseline comparison tables for each pillar.
- Evaluation reproducibility hash from config, data checksums, and code version.
- Explicit warning if March data was unavailable, modified, duplicated, or accessed prematurely.

### Could Have

- HTML scorecard.
- CSV metric tables for audit.
- Waterfall view of Pillar B exclusions and opportunity.
- Sensitivity analysis appendix.

### Won’t Have This Version

- Silent pass conditions.
- Post-hoc threshold tuning on March 2026.
- Model selection based on March 2026 performance.
- Claims of real-world fault detection accuracy without labels.
- Claims of realized savings without prospective controlled validation.
- Automated promotion to deployment.

---

## 5. Evidence Reporting / Export

### Must Have

- Export offline artifacts only:
  - Scorecard JSON.
  - Health event CSV.
  - Efficiency opportunity CSV.
  - Data-profile report.
  - Plots/images.
  - Human-readable PDF or HTML report, if supported.
- Every exported artifact must prominently state:
  - Offline advisory only.
  - No control action taken.
  - No write path.
  - March 2026 locked holdout evaluation.
  - PASS/FAIL status.
- Health event export must include:
  - Start/end timestamp.
  - Severity.
  - Health score.
  - mode context.
  - detector agreement.
  - top contributing variables.
  - data-quality flags.
- Efficiency export must include:
  - Evaluated interval.
  - actual SE.
  - matched-envelope SE.
  - estimated kWh opportunity.
  - comparable sample count.
  - observed advisory speed range.
  - confidence score.
  - caveats.
- Reports must distinguish:
  - actual measured operation.
  - offline counterfactual opportunity.
  - historically observed comparable intervals.
  - unsupported intervals.

### Should Have

- Evidence links from each summary metric to underlying interval rows.
- Plots for:
  - health score over time.
  - anomaly events.
  - specific energy over time.
  - matched historical comparisons.
  - savings opportunity rollup.
- Report-ready language for plant managers:
  - avoided energy cost estimate if tariff is provided.
  - earlier warning potential.
  - reviewable alert volume.
- Export manifest listing all generated files.

### Could Have

- Configurable tariff input for avoided-energy-cost estimate.
- ZIP bundle of all evidence artifacts.
- Lightweight notebook-style appendix for ML audit.
- Monthly management summary.

### Won’t Have This Version

- Direct export into CMMS, SCADA, HMI, PAC, or control systems.
- Automated email/SMS/pager notifications.
- Operator acknowledgement workflow connected to live operations.
- Editable control recommendations.
- Anything that can be interpreted as an executable control instruction.

---

## 6. Operator Dashboard

### Must Have

- Offline dashboard or static report viewer only.
- Prominent persistent status banner:

  **“Advisory-only offline evidence. Does not monitor live site. Does not control anything. No write path.”**

- Show overall evaluation status:
  - Pillar A PASS/FAIL.
  - Pillar B PASS/FAIL.
  - leakage check PASS/FAIL.
  - holdout period = March 2026.
- Show health timeline with event intervals and severity.
- Show efficiency opportunity timeline and rollup.
- Allow filtering by:
  - date range within loaded offline files.
  - mode: auto/manual/other.
  - severity.
  - confidence.
  - data-quality status.
- Display data-quality warnings where advisory or health scoring is unsupported.
- Clearly distinguish historical observed speed ranges from control commands.

### Should Have

- Plant-manager summary cards:
  - high-severity health events.
  - reviewable event count per day.
  - valid evaluated volume.
  - estimated offline kWh opportunity.
  - optional avoided energy cost if tariff is configured.
- Drilldown from event to evidence:
  - trend plot.
  - contributing variables.
  - detector agreement.
  - comparable historical intervals.
- Caveat panel visible on all efficiency advisory views.

### Could Have

- Side-by-side March actual operation versus matched historical efficient envelope.
- Export button for selected evidence bundle.
- Confidence coloring for advisories.
- Annotated known events if supplied as offline notes.

### Won’t Have This Version

- Live dashboard connected to site telemetry.
- Real-time alerts.
- HMI mimic screen.
- Controls panel.
- Setpoint entry.
- Acknowledge/execute action buttons.
- Any UI element implying the software can command pump speed, valve position, PAC logic, or CODESYS routines.

---

## 7. Safety / Governance Guardrails

### Must Have

- Advisory-only guardrails as first-class product features.
- All runtime and exported scorecards must include:

  ```json
  {
    "evaluation_mode": "offline_only",
    "write_path": "none",
    "influences_control": false,
    "site_integration_allowed": false
  }
  ```

- Prominent “does not control anything” status in dashboard and reports.
- No code path may write to PAC, HMI, SCADA, AMAX, EtherCAT, CODESYS, field I/O, or site historian.
- No `aquaoptima.edge` or `contracts.edge` imports in modeling code.
- Locked-holdout enforcement:
  - March 2026 cannot be used in training.
  - March 2026 cannot be used in scaler fitting.
  - March 2026 cannot be used in threshold tuning.
  - March 2026 cannot be used in feature selection.
  - March 2026 cannot be used in model selection.
- Data-leakage guard must fail closed if March 2026 is accessed before freeze by any training/tuning process.
- Honest PASS/FAIL gate must be mandatory for both pillars.
- Reports must include caveats:
  - no true fault labels.
  - offline estimated savings only.
  - single-site only.
  - unprofiled “other” mode risk.
  - valve position unavailable.
  - no actuation or control validation.

### Should Have

- Automated static check that rejects prohibited imports.
- Manifest of all files read during each pipeline stage.
- Separate user-visible status for:
  - leakage check.
  - safety boundary check.
  - model freeze check.
  - March scoring check.
- Approval checklist before March holdout scoring.
- Explicit “cannot claim” report section.

### Could Have

- Governance audit log signed with config hash.
- Policy-as-code validation for offline-only operation.
- Red-team wording check for advisory reports to detect control-like phrasing.

### Won’t Have This Version

- Any live site integration.
- Any write-enabled connector.
- Any actuation pathway.
- Any “recommended setpoint to execute now” language.
- Any auto-promotion from offline model to edge deployment.
- Any multi-site or fleet claim.
- Any safety certification claim.

---

## 8. Model Lifecycle — Train Offline / Export ONNX; Packaging Out of Scope

### Must Have

- Train models offline using 2025 training/validation data only.
- Freeze:
  - feature list.
  - scalers.
  - imputers.
  - thresholds.
  - model weights.
  - matching tolerances.
  - evaluation gates.
  - scorecard schema.
- Use chronological 2025 split for training and validation.
- Use past-only rolling features.
- Save model metadata:
  - train period.
  - validation period.
  - excluded periods.
  - mode filters.
  - feature definitions.
  - threshold values.
  - random seeds.
  - code version.
- Support optional ONNX export for trained health model artifacts where feasible.
- Treat ONNX export as an offline artifact only.
- Explicitly mark edge packaging and deployment as out of scope.

### Should Have

- Reproducible training command with config file.
- Deterministic seeds where supported.
- Model comparison table on 2025 validation only.
- Feature importance or attribution artifact for health detector.
- Saved efficiency-envelope index with provenance.
- Versioned frozen evaluation package for March scoring.

### Could Have

- Multiple candidate models trained offline and selected using 2025 validation only.
- Lightweight model registry folder for local artifacts.
- Model card for each frozen artifact.
- CPU runtime benchmark on offline files.

### Won’t Have This Version

- Edge deployment package.
- Dockerized edge runtime for AMAX.
- CODESYS integration.
- PAC/HMI connector.
- Real-time inference service.
- Continuous learning from March holdout.
- Automatic retraining from live site data.
- Packaging that implies field readiness.

---

## 9. Observability

### Must Have

- Offline pipeline logs for:
  - ingest.
  - profiling.
  - feature generation.
  - model training.
  - threshold freeze.
  - March scoring.
  - report export.
- Capture file paths, checksums, row counts, date ranges, and mode counts.
- Capture leakage-guard result.
- Capture safety-guard result.
- Capture excluded rows and reasons:
  - missing data.
  - low flow.
  - pump off.
  - unprofiled mode.
  - invalid units.
  - insufficient comparable history.
- Capture model/runtime warnings.
- Capture PASS/FAIL decisions and gate values.
- Observability artifacts must be offline files only.

### Should Have

- Structured logs in JSONL.
- Pipeline stage duration metrics.
- Data-quality trend summaries.
- Count of health events by severity and detector.
- Count of efficiency advisories by confidence band.
- Reproducibility manifest that links logs, scorecards, reports, configs, and model artifacts.

### Could Have

- Local-only run comparison utility.
- Human-readable audit timeline.
- Metric diff between frozen evaluation runs.
- Exported diagnostics for failed gates.

### Won’t Have This Version

- Live telemetry observability.
- Cloud monitoring.
- Remote logging from site.
- Runtime alerting service.
- Automatic incident creation.
- Any observability hook connected to operational control systems.

---

# User Stories

## Plant Operator

### **US-001**: Offline advisory status visibility

As a **Plant Operator**, I want to immediately see whether AquaOptima is offline advisory-only so that I do not mistake the product for a live control or alarm system.

AC:  
1. The dashboard and every report display a persistent banner stating: **“Offline advisory only. Does not monitor live site. Does not control anything. No write path.”**  
2. The scorecard contains `evaluation_mode = offline_only`, `write_path = none`, `influences_control = false`, and `site_integration_allowed = false`.  
3. No screen contains execute, acknowledge-to-control, setpoint-write, PAC, HMI, EtherCAT, AMAX, or CODESYS action controls.

---

### **US-002**: Review health events

As a **Plant Operator**, I want to review offline health events by time and severity so that I can understand when the station appeared to operate abnormally.

AC:  
1. The offline dashboard shows March 2026 health score timeline, anomaly intervals, severity, and event duration using the frozen Pillar A model.  
2. Events are generated from historical files only and do not require or create any live site connection or write path.  
3. The event view displays Pillar A PASS/FAIL status and indicates that March 2026 was a locked holdout, not used for training or tuning.

---

### **US-003**: Understand why an anomaly was flagged

As a **Plant Operator**, I want to see the top contributing variables for each health event so that I can decide whether the event is operationally plausible.

AC:  
1. Each high-severity event includes top contributing variables when data is sufficient, such as `edge_power`, `edge_flow`, `edge_pump_speed`, `node_pressure`, or hydraulic head.  
2. The evidence panel distinguishes detector output from confirmed fault diagnosis and states that true fault labels are not available unless supplied separately.  
3. Evidence is exported or displayed offline only and cannot trigger any live alarm, command, or control action.

---

### **US-004**: Review efficiency advisories without treating them as commands

As a **Plant Operator**, I want to view efficiency advisories as historical comparisons so that I understand possible operating improvements without treating them as executable setpoints.

AC:  
1. Each advisory states: “Historically, under similar conditions, lower specific energy was observed at speed range X–Y,” and does not phrase the result as a command.  
2. The dashboard labels speed ranges as historically observed advisory evidence, not live setpoints, and provides no mechanism to write them to any controller.  
3. The advisory includes March 2026 actual SE, matched-envelope SE, comparable sample count, confidence, and Pillar B PASS/FAIL status.

---

### **US-005**: Filter by operating mode and data quality

As a **Plant Operator**, I want to filter health and efficiency results by auto, manual, and other/unprofiled modes so that I do not confuse unsupported data with normal operation.

AC:  
1. The dashboard provides filters for auto, manual, and other/unprofiled modes based on offline file columns `auto` and `manual`.  
2. Other/unprofiled records are clearly marked and are not automatically treated as normal or efficient training examples.  
3. Filtering affects only offline display and export; it does not connect to or influence live site operation.

---

### **US-006**: See unsupported intervals

As a **Plant Operator**, I want unsupported intervals to be clearly marked so that I know when AquaOptima is not making a reliable advisory.

AC:  
1. The dashboard marks intervals excluded due to missing data, low flow, pump-off status, invalid units, unprofiled mode, or insufficient comparable history.  
2. Unsupported intervals do not produce efficiency savings claims or speed advisory ranges.  
3. The exclusion logic is applied to historical files only and cannot alter source data or write to any operational system.

---

## Reliability / Maintenance Engineer

### **US-007**: Investigate health-event evidence

As a **Reliability/Maintenance Engineer**, I want event-level anomaly evidence with contributing variables and detector agreement so that I can prioritize offline investigation.

AC:  
1. The health event CSV includes start/end timestamp, severity, health score, mode context, detector agreement, top variables, and data-quality flags.  
2. The report distinguishes statistical abnormality from confirmed equipment fault and includes no claim of field fault recall without labels.  
3. Event evidence is generated from frozen offline evaluation and cannot create maintenance tickets or control actions automatically.

---

### **US-008**: Compare health detector against simple baselines

As a **Reliability/Maintenance Engineer**, I want the anomaly model compared against persistence residuals and SPC so that I can trust that it adds value beyond simple monitoring.

AC:  
1. The Pillar A scorecard reports performance against persistence residual, SPC/EWMA, and multivariate baseline detectors.  
2. The scorecard includes honest PASS/FAIL using predefined 2025-frozen gates, with March 2026 used only for holdout scoring.  
3. If the detector fails to beat baselines on required gates, the report shows FAIL and does not suppress or reword the result as a success.

---

### **US-009**: Validate sensitivity using injected faults

As a **Reliability/Maintenance Engineer**, I want injected-fault tests so that I can understand what types of degradation the health model is sensitive to.

AC:  
1. The evaluation includes offline injected tests for power degradation, sensor drift, stuck sensor, spike/dropout, and cross-sensor inconsistency.  
2. Metrics include detection sensitivity, detection delay, and whether the injected variable appears in top contributors.  
3. Injected-fault results are reported as sensitivity to defined synthetic faults, not proof of real-world field fault detection.

---

### **US-010**: Detect slow power degradation

As a **Reliability/Maintenance Engineer**, I want the system to flag power rising relative to flow/head/speed so that I can get earlier warning of possible efficiency decay or equipment issues.

AC:  
1. Pillar A includes a physical residual or equivalent feature that compares power against matched flow, speed, and hydraulic head context.  
2. The scorecard reports whether +10% injected power degradation is detected materially earlier than a persistence-residual baseline.  
3. Any warning is labeled as offline advisory evidence and does not command maintenance, shutdown, pump-speed change, or control action.

---

### **US-011**: Export evidence for offline review

As a **Reliability/Maintenance Engineer**, I want to export event evidence so that I can review it with operations and maintenance teams outside the product.

AC:  
1. The product exports health event CSV and report artifacts with timestamps, variables, plots, and caveats.  
2. Every exported artifact includes offline-only, no-write, no-actuation, March-holdout, and PASS/FAIL status statements.  
3. Exports are files only and do not integrate with CMMS, SCADA, HMI, PAC, or any live operational workflow.

---

## Energy / Operations Manager

### **US-012**: Quantify offline energy opportunity

As an **Energy/Operations Manager**, I want estimated kWh opportunity from matched historical efficiency envelopes so that I can judge whether the advisory is worth further operational review.

AC:  
1. Pillar B reports actual SE, matched-envelope SE, evaluated volume, estimated kWh opportunity, and percent SE reduction for valid intervals.  
2. The report labels the result as offline estimated opportunity, not realized or guaranteed savings.  
3. The calculation uses March 2026 as locked holdout and does not use March data to tune matching tolerances, quantiles, or model selection.

---

### **US-013**: Convert energy opportunity to business value

As an **Energy/Operations Manager**, I want optional avoided-energy-cost estimates so that I can communicate the opportunity in plant-manager business terms.

AC:  
1. If a tariff is provided offline, the report converts estimated kWh opportunity into avoided energy cost.  
2. The report states that avoided cost is counterfactual and requires future qualified operational validation before being called realized savings.  
3. Tariff input and cost calculations are offline report features only and do not influence live site operation or control.

---

### **US-014**: Compare against MVPv1 control logs

As an **Energy/Operations Manager**, I want AquaOptima’s offline advisory compared with MVPv1 control logs so that I can understand whether the new advisory identifies additional opportunity.

AC:  
1. The product aligns MVPv1 logs with telemetry using offline files and reports alignment quality before comparison.  
2. The comparison reports actual logged behavior versus matched historical efficient envelopes only where time alignment and data quality are sufficient.  
3. The report does not claim control outperformance unless the comparison is valid and does not use MVPv1 logs to leak March outcomes into model tuning.

---

### **US-015**: Understand advisory coverage and exclusions

As an **Energy/Operations Manager**, I want to see what portion of pumped volume receives confident advisories so that I can judge whether the opportunity is meaningful.

AC:  
1. The Pillar B scorecard reports valid evaluated volume, advisory coverage rate, and excluded volume by reason.  
2. Intervals with insufficient comparable history or outside historically observed speed/head/flow ranges produce no advisory and no savings claim.  
3. Coverage and exclusions are calculated from offline historical files only and cannot trigger live monitoring or control actions.

---

### **US-016**: Review conservative savings caveats

As an **Energy/Operations Manager**, I want savings caveats to be explicit so that I do not overstate offline opportunity as guaranteed savings.

AC:  
1. The report includes caveats for historical confounding, missing valve position, mode ambiguity, unit assumptions, no actuation, and single-site scope.  
2. The report includes both gross and conservative opportunity views where supported, such as 10th versus 25th percentile matched-envelope SE.  
3. The report prominently states that realized savings require future safety qualification and prospective validation outside this version.

---

## AquaOptima ML Engineer

### **US-017**: Enforce offline ingest and schema validation

As an **AquaOptima ML Engineer**, I want the pipeline to ingest only offline CSV/control-log files and validate schema so that modeling starts from auditable historical data.

AC:  
1. The ingest stage accepts offline file paths only and rejects live connectors, site integrations, or streaming endpoints.  
2. The schema validator checks required active axes, mode columns, timestamp quality, missingness, and the special interpretation of `node_status` as hydraulic head.  
3. The ingest run writes a data-profile artifact and safety metadata showing `evaluation_mode = offline_only` and `write_path = none`.

---

### **US-018**: Prevent March 2026 leakage

As an **AquaOptima ML Engineer**, I want a leakage guard around March 2026 so that the locked holdout remains a valid benchmark.

AC:  
1. Training, scaler fitting, feature selection, threshold tuning, model selection, and matching-tolerance selection fail if they attempt to read March 2026 data.  
2. March 2026 can only be read by the frozen scoring stage after config, features, scalers, thresholds, models, and gates are frozen.  
3. The scorecard includes a leakage-check PASS/FAIL result, and any failure blocks PASS status for both pillars.

---

### **US-019**: Train and freeze Pillar A models offline

As an **AquaOptima ML Engineer**, I want to train Pillar A baselines and candidate models on 2025 data only so that the health detector can be evaluated honestly on March 2026.

AC:  
1. The training command uses 2025 chronological train/validation splits and confirmed auto-mode data for the first normal-envelope model.  
2. The pipeline freezes feature definitions, scalers, model weights, thresholds, and Pillar A PASS/FAIL gates before March scoring.  
3. The trained artifacts are offline files only and include no edge imports, no write path, and no control integration.

---

### **US-020**: Build the Pillar B matched-efficiency envelope offline**

As an **AquaOptima ML Engineer**, I want to build a matched-condition efficiency-envelope engine so that March operation can be compared against historically realized lower-specific-energy cases.

AC:  
1. The envelope is built from 2025 valid intervals only, using unit-confirmed SE and matching variables for demand, hydraulic head, level, pressure, and delivered service.  
2. The engine rejects advisories where comparable sample count is below threshold or candidate speed/head/flow ranges are outside historical observations.  
3. March 2026 is used only for frozen offline replay evaluation and cannot tune match tolerances, quantiles, or confidence thresholds.

---

### **US-021**: Generate honest PASS/FAIL scorecards

As an **AquaOptima ML Engineer**, I want the pipeline to generate mandatory PASS/FAIL scorecards so that failed results are visible and auditable.

AC:  
1. The scorecard JSON includes safety fields, train/validation/holdout periods, feature list, leakage result, Pillar A metrics, Pillar B metrics, and caveats.  
2. PASS/FAIL is computed from predefined gates, and a FAIL is preserved in reports without manual override.  
3. Scorecard generation is offline only and does not promote models to deployment, integration, or live control.

---

### **US-022**: Export model artifacts without packaging for edge deployment

As an **AquaOptima ML Engineer**, I want to export trained model artifacts, including optional ONNX, so that offline evaluation is reproducible while edge packaging remains out of scope.

AC:  
1. The pipeline saves model metadata, frozen config, scalers, thresholds, and optional ONNX files as offline artifacts.  
2. Exported artifacts are marked “not for site deployment” and include `site_integration_allowed = false`.  
3. No AMAX package, CODESYS integration, PAC connector, HMI connector, EtherCAT interface, or edge runtime is produced.

---

### **US-023**: Audit pipeline observability

As an **AquaOptima ML Engineer**, I want structured offline logs and manifests so that every result can be traced back to data, config, and code.

AC:  
1. Each pipeline stage writes structured logs with file checksums, row counts, date ranges, mode counts, exclusions, warnings, and stage duration.  
2. The run manifest links data profile, frozen config, model artifacts, scorecards, reports, and export files.  
3. Observability artifacts are offline files only and include no cloud monitoring, live telemetry, remote logging, or control-system hooks.

---

### **US-024**: Block prohibited imports and write paths

As an **AquaOptima ML Engineer**, I want automated governance checks for prohibited imports and write paths so that the offline/no-actuation boundary is enforced by the product.

AC:  
1. The governance check fails if modeling code imports `aquaoptima.edge`, `contracts.edge`, or any configured live-control/site-integration package.  
2. The governance check fails if any pipeline stage attempts to open a write-capable connector to PAC, HMI, SCADA, AMAX, EtherCAT, CODESYS, or site historian.  
3. A failed governance check forces the final scorecard safety status to FAIL, regardless of model metrics.