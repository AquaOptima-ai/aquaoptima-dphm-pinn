# AquaOptima Pump Station Optimizer Lite — UX/UI Specification  
## Operator-Facing Offline Dashboard + Exportable Evidence Reports  
### Health & Efficiency Advisory (Pillars A+B) — Yilan Pump Station

**Product mode:** Offline-only evidence and advisory product  
**Site scope:** Single legacy Yilan pump station, Taiwan  
**Primary users:** Plant Operator, Reliability Engineer, Energy / Operations Manager, AquaOptima ML Engineer  
**Safety boundary:** **ADVISORY ONLY — does not control the station**  
**Control ownership:** AMAX/CODESYS owns control. AquaOptima is a read-only offline evidence sidecar.  
**UX mandate:** Every screen, report page, exported artifact, table, chart, and API-fed view must make offline/no-control status unmistakable.

---

## 0. Product UX Summary

AquaOptima Pump Station Optimizer Lite is an offline evidence dashboard and report generator for reviewing historical health anomalies and efficiency opportunities at the Yilan pump station. It is not a live control system, not a SCADA/HMI replacement, not a setpoint optimizer, and not an alarm system. The UI must help operators and engineers understand historical operation calmly and rigorously without ever suggesting that AquaOptima can or should control the pump station.

The dashboard supports two analytical pillars:

1. **Pillar A — Health / Anomaly Detection Advisory**  
   Shows whether historical operating points looked statistically abnormal compared with the station’s learned normal envelope. It provides health score trends, anomaly events, detector agreement, top contributing variables, and evidence plots.

2. **Pillar B — Efficiency / Specific-Energy Advisory**  
   Compares actual historical operation against historically observed lower-specific-energy operating points under similar demand, head, level, pressure, and flow conditions. It reports offline estimated opportunity, not realized savings, and displays historically observed speed ranges, not executable setpoints.

The UI is designed for data-dense industrial review on desktop and tablet. It should feel calm, evidence-first, and operator-safe. It must avoid consumer-dashboard excitement, “optimization magic,” or action-oriented control language. The central product promise is not “we control better”; it is:

> “Here is the offline evidence. Here is what looked abnormal. Here is where energy intensity may have been better historically. Here are the caveats. No control action was taken or enabled.”

---

# 1. Design Principles

## 1.1 Persistent advisory-only boundary

The most important design principle is that every screen must make the safety boundary visible, repeated, and unambiguous.

The global top banner must state:

> **ADVISORY ONLY — does not control the station**  
> Offline historical evidence. No write path. No actuation. AMAX/CODESYS owns control.

This banner must appear:

- On every dashboard route.
- In the report builder.
- On every exported PDF/HTML report page header or footer.
- In CSV/JSON metadata.
- In empty/loading/error states.
- In print views.
- In modal dialogs.
- In chart export images where practical.
- On tablet views after responsive collapse.

No UI may contain buttons such as:

- Execute
- Apply
- Send
- Commit
- Control
- Write
- Dispatch
- Push to PAC
- Push to HMI
- Set speed
- Optimize now
- Acknowledge alarm to station

Permitted action language:

- View evidence
- Compare actual vs advisory
- Export report
- Download CSV
- Open scorecard
- Filter data
- Mark for offline review
- Add to evidence report
- Copy advisory caveat
- Inspect comparable intervals

The user must never be able to confuse AquaOptima with a live HMI or command interface.

---

## 1.2 Calm control-room density

The dashboard should support dense technical information while avoiding alarm fatigue and visual chaos.

Design implications:

- Use muted backgrounds and restrained color.
- Use strong typography hierarchy rather than excessive color blocks.
- Prefer stable layouts and consistent chart scales.
- Avoid flashing, animation, siren red, or live-alarm styling.
- Avoid “real-time” language unless explicitly saying “not real-time.”
- Show event-level summaries first, with drill-down to point-level data.
- Debounce health anomalies into reviewable events rather than flooding tables with every minute.
- Use compact cards and tables, but preserve readable row height for operators in control-room lighting.

The interface should feel like an audit cockpit, not an alarm panel.

---

## 1.3 Uncertainty, baselines, and caveats always visible

Every major analytical output must show its comparator and confidence context.

For Pillar A health:

- Health score must show detector agreement.
- Anomaly detail must show baseline comparisons:
  - SPC/EWMA
  - Mahalanobis / multivariate baseline
  - persistence residual
  - learned detector where available
- Anomaly claims must be phrased as “statistically unusual,” not “confirmed fault,” unless external labels exist.
- Lack of true fault labels must be included in scorecard/report caveats.

For Pillar B efficiency:

- Actual specific energy must be shown next to matched historical envelope.
- Matched sample count and match distance must be visible.
- Efficient speed range must be labeled **historically observed speed range**, not setpoint.
- Estimated kWh must be labeled **offline estimated opportunity**, not savings.
- Unsupported intervals must be clearly marked “No advisory — insufficient support” rather than hidden.

The product earns trust by showing when it does not know enough.

---

## 1.4 Evidence before recommendation

The UX must prioritize evidence traceability over persuasive recommendations.

Every anomaly or efficiency opportunity should answer:

- What time interval?
- What data was used?
- What mode was the station in?
- Which variables contributed?
- Which baselines agreed or disagreed?
- What was the confidence?
- What caveats apply?
- Which artifact/report row can be exported?

Efficiency screens must avoid presenting a single optimal answer. They should instead present:

- Actual operation.
- Comparable historical examples.
- Efficient envelope.
- Historically observed range.
- Estimated opportunity.
- Confidence and limitations.

The user should feel empowered to investigate, not pushed to act.

---

## 1.5 Frozen evaluation and locked holdout transparency

The product exists because prior forecasting honestly failed against locked March 2026 data. The UI should continue that culture of honest evaluation.

Design implications:

- Show train/validation/holdout periods in Data & Holdout Status.
- Show March 2026 as locked holdout and whether leakage checks passed.
- Scorecards must show PASS/FAIL, not vague “good/bad” states.
- FAIL states must be rendered with the same dignity and completeness as PASS states.
- If safety or leakage fails, overall status cannot appear positive.
- Frozen config, checksum, and model version should be visible in governance screens.

Operators may not need all ML details, but engineers and auditors must be able to trace results.

---

## 1.6 Tablet-first inspection, desktop-first analysis

The dashboard must work on tablets for shift review and on desktop for engineering analysis.

Tablet use cases:

- Review health overview during shift handover.
- Open a single anomaly detail.
- Review top efficiency opportunities.
- Show report summary in a meeting.

Desktop use cases:

- Compare multiple charts.
- Inspect scatter plots and comparable intervals.
- Build evidence reports.
- Review data quality and model lifecycle.

Responsive design should preserve the safety banner, critical status cards, and filter context before secondary charts.

---

# 2. User Flows

## Flow 1 — Review station health for a shift

**Primary persona:** Plant Operator  
**Goal:** Determine whether historical operation during a shift contained reviewable health events.

### Entry point

Route: `/health/overview`  
User selects a time range such as March 8, 00:00–08:00.

### Steps

1. User sees persistent advisory banner.
2. User checks the station summary strip:
   - Site: Yilan
   - Evaluation mode: Offline only
   - Holdout: March 2026
   - High-severity event count
   - Percent time high severity
   - Worst health score
3. User reviews health timeline with severity bands.
4. User filters to:
   - Mode: auto only / manual / other / mixed
   - Severity: warning and high
   - Data quality: include or exclude gaps
5. User opens the event list.
6. User selects a high-severity event.
7. Event preview drawer shows:
   - Event start/end
   - Duration
   - Top contributors
   - Detector agreement
   - Caveat: “Statistical anomaly, not confirmed fault.”
8. User either:
   - Opens Anomaly Detail, or
   - Adds event to an evidence report.

### Success state

User can explain:

- How many reviewable health events occurred.
- Which intervals were most abnormal.
- Which variables contributed.
- That AquaOptima did not issue live alarms or control actions.

### Safety UI requirements

- Page header contains advisory-only banner.
- Health events are called “offline health events,” not alarms.
- Event actions are limited to “View evidence” and “Add to report.”

---

## Flow 2 — Investigate an anomaly with evidence

**Primary persona:** Reliability Engineer  
**Goal:** Determine why a health event was flagged and whether it is worth offline review.

### Entry point

Route: `/health/events/:eventId`

### Steps

1. User opens event detail from overview or report builder.
2. Header shows:
   - Event ID
   - Time interval
   - Severity band
   - Mode context
   - Advisory-only status
3. User reviews the evidence tabs:
   - Summary
   - Variable contributions
   - Baseline comparison
   - Raw telemetry
   - Data quality
   - Export evidence
4. In Summary, user sees:
   - Worst health score
   - Detector agreement matrix
   - Top 5 contributors
   - Caveats
5. In Baseline Comparison, user sees:
   - Learned detector score
   - SPC score
   - Mahalanobis score
   - Persistence residual score
   - Thresholds frozen from 2025 validation
6. In Raw Telemetry, user overlays:
   - edge_power
   - edge_flow
   - edge_pump_speed
   - node_pressure
   - hydraulic head from `node_status`
7. User clicks “Add event to report.”
8. Evidence panel records the event, chart images, and caveats.

### Success state

User can judge whether the anomaly has coherent evidence, whether it may be data quality, mode transition, or true abnormal operation.

### Safety UI requirements

- No “acknowledge alarm” workflow.
- No “create maintenance ticket automatically.”
- Every tab footer states: “Offline evidence only — no station control.”

---

## Flow 3 — Review an efficiency-advisory opportunity vs actual operation

**Primary persona:** Energy / Operations Manager  
**Goal:** Understand whether an interval had lower-specific-energy historical comparables.

### Entry point

Route: `/efficiency/advisory-vs-actual`

### Steps

1. User selects March holdout or a 2025 evaluation interval.
2. Summary cards show:
   - Valid evaluated volume
   - Advisory coverage
   - Actual SE
   - Envelope SE p25
   - Offline estimated kWh opportunity
   - Confidence distribution
3. User opens opportunity table sorted by estimated kWh opportunity.
4. User selects an interval.
5. Detail pane shows:
   - Actual specific energy.
   - Matched historical p25 and p10 envelopes.
   - Comparable sample count.
   - Match distance.
   - Observed efficient speed range.
   - Actual average speed.
   - Exclusion/caveat flags.
6. User clicks “View comparable intervals.”
7. Scatter plot opens with:
   - Actual point highlighted.
   - Historical comparable points.
   - Efficient envelope overlay.
   - Unsupported or low-confidence points faded.
8. User adds opportunity to report.

### Success state

User understands:

- Whether opportunity is robust.
- How much volume is covered.
- Whether historical support is sufficient.
- That the observed speed range is not an executable recommendation.

### Safety UI requirements

- Use label: “Historically observed speed range.”
- Do not label as “recommended setpoint.”
- Estimated opportunity card must say: “Counterfactual offline estimate — not realized savings.”

---

## Flow 4 — Run/read an offline evaluation scorecard

**Primary persona:** ML Engineer, Reliability Engineer, Manager  
**Goal:** Review whether Pillar A and Pillar B passed frozen evaluation gates.

### Entry point

Route: `/evaluation/scorecard`

### Steps

1. User opens scorecard after offline run.
2. Top status rail shows:
   - Safety check PASS/FAIL
   - Leakage check PASS/FAIL
   - Pillar A PASS/FAIL
   - Pillar B PASS/FAIL
   - Overall PASS/FAIL
3. If safety or leakage fails, overall status is locked to FAIL.
4. User expands Pillar A:
   - March anomaly fraction
   - Event count/day
   - Injected-fault AUROC
   - Evidence completeness
   - Baseline comparisons
5. User expands Pillar B:
   - Coverage
   - Valid evaluated volume
   - Estimated opportunity
   - Robustness under p25/p10
   - Unsupported interval rejection
6. User opens “Cannot Claim” section:
   - Cannot claim field fault recall without labels.
   - Cannot claim realized savings.
   - Cannot claim safe executable setpoints.
   - Cannot claim multi-site generalization.
7. User exports scorecard JSON/PDF.

### Success state

User can communicate honest PASS/FAIL results and limitations.

### Safety UI requirements

- Scorecard header contains the safety JSON values:
  - `evaluation_mode = offline_only`
  - `write_path = none`
  - `influences_control = false`
  - `site_integration_allowed = false`

---

## Flow 5 — Export an evidence report

**Primary persona:** Operator, Reliability Engineer, Manager  
**Goal:** Create a PDF/HTML/CSV/JSON report bundle for offline review.

### Entry point

Route: `/reports/builder`

### Steps

1. User opens Report Builder.
2. Builder shows persistent safety banner and report metadata.
3. User selects report type:
   - Shift health report
   - Anomaly evidence report
   - Efficiency opportunity report
   - Unified A+B evaluation report
   - ML audit appendix
4. User selects sections:
   - Executive summary
   - Advisory-only boundary
   - Scorecard
   - Health events
   - Anomaly evidence
   - Efficiency opportunities
   - Data and holdout status
   - Model lifecycle
   - Caveats and cannot-claim statements
5. User previews report.
6. Preview shows page header/footer with advisory-only text.
7. User exports:
   - PDF
   - HTML
   - CSV tables
   - JSON scorecard
   - Artifact manifest
8. Export success state shows file paths and checksums.

### Success state

User receives a complete evidence bundle suitable for offline review and audit.

### Safety UI requirements

- Export button label: “Export evidence report,” not “publish to station.”
- Report includes no control instructions.
- CSV/JSON include safety metadata.

---

# 3. Information Architecture and Read-Only Route Structure

The dashboard is a local or static read-only interface. All routes are GET/read-only. No control or write endpoints exist.

## 3.1 Global navigation

Primary sections:

1. Overview
2. Health
3. Efficiency
4. Evaluation
5. Reports
6. Data & Holdout
7. Model Lifecycle
8. Settings & Governance

Global utility:

- Run selector
- Time range selector
- Site selector locked to Yilan
- Export shortcut
- Help/caveats
- Advisory-only status indicator

## 3.2 Route structure

```text
/
  Redirects to /overview

/overview
  Unified A+B summary dashboard

/health/overview
  Health score timeline and event summary

/health/events
  Health event table

/health/events/:eventId
  Anomaly detail + evidence

/health/baselines
  Baseline-vs-model comparison

/efficiency/explorer
  Operating-point efficiency explorer

/efficiency/advisory-vs-actual
  Actual operation vs matched historical advisory envelope

/efficiency/opportunities/:opportunityId
  Efficiency opportunity detail

/evaluation/scorecard
  Unified PASS/FAIL scorecard

/evaluation/injections
  Injected-fault evaluation details

/reports/builder
  Evidence report builder

/reports/exports
  Export history and artifact downloads

/data/status
  Data profile, mode profile, unit status, holdout status

/data/holdout
  March 2026 locked holdout and leakage guard

/model/lifecycle
  Offline model lifecycle, frozen configs, thresholds

/settings/governance
  Safety guard, prohibited imports, read-only settings

/settings/display
  Theme, density, accessibility preferences

/help/caveats
  Product limitations, cannot-claim statements
```

## 3.3 Read-only interaction model

Allowed interactions:

- Filter
- Sort
- Search
- Inspect
- Compare
- Export local artifact
- Add item to report draft
- Download CSV/JSON/PDF/HTML
- Change visual theme
- Toggle units if configured

Disallowed interactions:

- Any command to station.
- Any write to PAC/HMI/SCADA/historian.
- Any live connector configuration.
- Any setpoint execution.
- Any “send report to controller.”
- Any auto-ticket creation to operational systems.

---

# 4. Global Layout System

## 4.1 Page shell

Every screen uses a consistent shell:

1. **Advisory-only banner**  
   Full-width, persistent, non-dismissible.

2. **Top app bar**  
   Product name, run ID, site, holdout status, export shortcut, help.

3. **Left navigation**  
   Collapsible on tablet. Icons plus labels.

4. **Context bar**  
   Time range, mode filter, dataset partition, severity filter, data-quality filter.

5. **Main content area**  
   Cards, charts, evidence panels, tables.

6. **Right evidence drawer**  
   Optional drawer for selected event/opportunity/report contents.

7. **Footer strip**  
   Offline/no-control statement and artifact/run ID.

## 4.2 Persistent advisory banner spec

Text:

> **ADVISORY ONLY — does not control the station**  
> Offline historical evidence. No write path. No actuation. AMAX/CODESYS owns control.

Behavior:

- Always visible at top.
- Sticky during scroll.
- Non-dismissible.
- Appears in high contrast in both light and dark mode.
- On tablet, wraps to two lines but remains visible.
- Includes “Details” link to governance page.
- Does not use alarming red as primary color; use safety amber/blue combination.

Recommended style:

- Background: dark navy in light mode, near-black blue in dark mode.
- Left icon: shield/info icon.
- Accent stripe: amber.
- Text color: white.
- Secondary metadata: light blue-gray.

---

# 5. Screen Specifications

The following screen specs include purpose, layout, key components, states, and safety requirements. Each screen must include the persistent advisory-only banner.

---

## Screen 1 — Unified Overview

**Route:** `/overview`  
**Purpose:** Provide a calm executive/operator summary of A+B evidence for the selected run and period.

### Primary users

- Plant Operator
- Energy Manager
- Reliability Engineer

### Layout

Top:

- Advisory-only banner.
- Page title: “Yilan Offline Health + Efficiency Overview.”
- Run selector and time range.

Status row:

- Safety check
- Leakage check
- Pillar A status
- Pillar B status
- Overall evaluation status

Main cards:

1. Health summary
   - Average health score
   - Worst health score
   - High-severity event count
   - High-severity time fraction

2. Efficiency summary
   - Valid evaluated volume
   - Advisory coverage
   - Actual SE
   - Offline estimated opportunity

3. Data/holdout summary
   - Train period
   - Validation period
   - Holdout period
   - Unit status

4. Cannot-claim card
   - No control
   - No realized savings
   - No confirmed fault recall unless labels exist

Main charts:

- Health timeline sparkline.
- Efficiency actual vs envelope sparkline.
- Event/opportunity priority list.

### Empty state

If no run is selected:

> No offline evaluation run selected. Choose a local run artifact to view evidence. AquaOptima remains advisory-only and does not connect to the station.

CTA: “Select run artifact.”

### Loading state

Skeleton cards with banner visible. Text:

> Loading local evidence artifacts. No station connection is used.

### Error state

If artifact load fails:

> Unable to load offline evidence artifacts. No station data was modified. Check local file path and manifest.

---

## Screen 2 — Health Overview

**Route:** `/health/overview`  
**Purpose:** Review health score trend and anomaly event volume.

### Layout

Header:

- Page title: “Health Overview — Offline Anomaly Advisory.”
- Status chips:
  - Offline only
  - Holdout March 2026
  - No control path
  - Thresholds frozen

Controls:

- Time range
- Severity band
- Mode filter
- Detector filter
- Data quality flags

Cards:

- Current selected-period health summary
- High-severity event count
- Event count/day
- Evidence completeness
- Manual/other mode share

Charts:

1. Health gauge card.
2. Anomaly timeline with severity bands.
3. Detector agreement stacked strip.
4. Mode context timeline.
5. Top contributing variables bar chart.

Table:

- Event list:
  - Event ID
  - Start/end
  - Duration
  - Worst health
  - Severity
  - Mode
  - Top contributors
  - Detector agreement
  - Data quality flags
  - Actions: View evidence, Add to report

### Empty state

If no health events:

> No health events met the selected severity threshold for this period. This does not prove absence of faults; it means the offline detector did not flag reviewable anomalies under frozen thresholds.

### Loading state

Charts show skeleton axes. Banner remains visible.

### Error state

If health score artifact missing:

> Health scores are unavailable for this run. Pillar A may not have been evaluated or the artifact is incomplete.

---

## Screen 3 — Health Events Table

**Route:** `/health/events`  
**Purpose:** Provide a sortable, filterable event register.

### Layout

- Event table full-width.
- Advanced filters drawer:
  - Severity
  - Duration
  - Detector agreement
  - Contributor variable
  - Mode
  - Data quality
- Bulk export selection.

Columns:

- Event ID
- Start
- End
- Duration
- Severity
- Min health score
- Top contributors
- Detector agreement
- Mode
- Caveats
- Report inclusion

### Empty state

> No events match current filters. Try widening severity, mode, or date filters. No control action exists from this page.

### Loading state

Table skeleton rows.

### Error state

> Event table could not be loaded from local artifact. Check `health_events.csv`.

---

## Screen 4 — Anomaly Detail + Evidence

**Route:** `/health/events/:eventId`  
**Purpose:** Deep evidence review for a selected anomaly.

### Layout

Header:

- Event ID
- Severity
- Time interval
- Mode context
- Advisory-only badge

Left column:

- Health event summary card
- Top contributors
- Data quality flags
- Caveats

Main area tabs:

1. Summary
2. Telemetry overlay
3. Baseline vs model
4. Contributions
5. Data quality
6. Export evidence

Charts:

- Health score over event window plus context before/after.
- Raw telemetry multi-axis chart.
- Baseline-vs-model chart.
- Contribution waterfall.

Evidence text panel:

- “Why flagged”
- “What baselines agreed”
- “What to be careful about”
- “Cannot claim”

Actions:

- Add to report
- Download event CSV
- Copy evidence summary

### Empty state

If event ID not found:

> Event not found in this offline run. It may belong to another run or filtered artifact.

### Loading state

Event shell loads before charts.

### Error state

If chart data missing:

> Event metadata loaded, but telemetry evidence is incomplete. Report will mark this event as partially supported.

---

## Screen 5 — Baseline vs Model Health Comparison

**Route:** `/health/baselines`  
**Purpose:** Show how health detector compares against simple baselines.

### Layout

Cards:

- Persistence residual comparison
- SPC/EWMA comparison
- Mahalanobis comparison
- Learned detector comparison
- Ensemble fusion status

Charts:

- Score distribution: 2025 validation vs March holdout.
- Threshold lines.
- Injected fault detection delay.
- AUROC by injected fault family.
- Attribution accuracy.

Table:

- Metric
- Baseline value
- Candidate model value
- PASS/FAIL
- Notes

### Empty state

> Baseline comparison has not been generated. Run offline health evaluation before reviewing this page.

### Error state

> Baseline artifacts are incomplete. Scorecard cannot support Pillar A PASS without required baselines.

---

## Screen 6 — Operating-Point Efficiency Explorer

**Route:** `/efficiency/explorer`  
**Purpose:** Explore specific energy across operating conditions.

### Layout

Header:

- “Operating-Point Efficiency Explorer.”
- Unit status chip: kWh/m³ confirmed / unit gate failed.
- Advisory-only banner.

Controls:

- Date range
- Mode
- Demand range
- Head range
- Level range
- Pressure range
- Minimum comparable count
- Confidence threshold

Main chart:

- Specific-energy scatter:
  - X-axis: flow, demand, head, or speed selectable.
  - Y-axis: kWh/m³.
  - Color: confidence or mode.
  - Shape: actual vs historical comparable.
  - Overlay: efficient envelope p25/p10.

Side panel:

- Selected point details:
  - Energy
  - Volume
  - Actual SE
  - Head
  - Level
  - Pressure
  - Mode
  - Validity flags

### Empty state

If unit gate fails:

> Efficiency explorer is unavailable because flow/power units are not confirmed. AquaOptima will not report kWh/m³ without unit validation.

### Loading state

Scatter skeleton with unit chip visible.

### Error state

> Operating points could not be loaded. Check interval aggregation artifact.

---

## Screen 7 — Efficiency Advisory vs Actual

**Route:** `/efficiency/advisory-vs-actual`  
**Purpose:** Compare actual operation against matched historical efficient envelope.

### Layout

Top cards:

- Evaluated volume
- Advisory coverage
- Actual average SE
- Envelope SE p25
- Offline estimated opportunity
- Unsupported interval count

Main chart:

- Time series:
  - Actual SE
  - Envelope SE p25
  - Envelope SE p10
  - Confidence shading
  - Unsupported intervals hatched

Opportunity table:

- Interval
- Actual SE
- Envelope SE
- SE gap
- Volume
- Estimated kWh opportunity
- Comparable count
- Observed speed range
- Confidence
- Caveats

Detail drawer:

- Actual vs envelope summary
- Comparable interval histogram
- Speed range evidence
- Add to report

### Empty state

If no supported advisories:

> No efficiency advisories were produced for the selected filters. Intervals may be unsupported due to low flow, insufficient historical matches, unconfirmed units, or unseen operating regimes.

### Error state

> Efficiency advisory artifact is missing or invalid. Pillar B cannot claim opportunity for this run.

---

## Screen 8 — Efficiency Opportunity Detail

**Route:** `/efficiency/opportunities/:opportunityId`  
**Purpose:** Inspect one opportunity and its comparable historical support.

### Layout

Header:

- Opportunity ID
- Interval
- Confidence
- Offline estimated opportunity
- Advisory-only badge

Sections:

1. Actual operation
   - Energy
   - Volume
   - Actual SE
   - Actual speed
   - Demand/head/level/pressure

2. Matched historical envelope
   - Comparable count
   - Match distance
   - p25 SE
   - p10 SE
   - observed speed range

3. Scatter evidence
   - Actual point
   - Historical comparables
   - Efficient envelope

4. Caveats
   - Missing valve position
   - Historical comparability
   - Not realized savings
   - Not executable setpoint

Actions:

- Add opportunity to report
- Download comparable intervals CSV
- Copy advisory text

### Empty state

If opportunity unsupported:

> This interval has no advisory because historical support was insufficient. No setpoint or savings claim is produced.

### Error state

> Comparable interval evidence is unavailable. The report will mark this opportunity as incomplete.

---

## Screen 9 — Scorecard / Evaluation Results

**Route:** `/evaluation/scorecard`  
**Purpose:** Show honest PASS/FAIL evaluation for safety, leakage, Pillar A, Pillar B, and overall.

### Layout

Top status rail:

- Safety check
- Leakage check
- Pillar A status
- Pillar B status
- Overall status

Each card uses accessible PASS/FAIL styling with icon and text.

Sections:

1. Safety boundary
   - `evaluation_mode = offline_only`
   - `write_path = none`
   - `influences_control = false`
   - `site_integration_allowed = false`

2. Leakage guard
   - March access status
   - Frozen config timestamp
   - File checksums

3. Pillar A
   - Health metrics
   - Baseline comparison
   - Injected fault sensitivity
   - Event reviewability

4. Pillar B
   - Coverage
   - SE opportunity
   - Robustness
   - Unsupported interval rejection

5. Cannot claim
   - Field fault recall without labels
   - Realized savings
   - Safe executable setpoints
   - Multi-site generalization

### Empty state

> No scorecard is available. Run offline evaluation with a frozen config before viewing results.

### Error state

> Scorecard failed validation. Overall status is treated as FAIL until safety and leakage checks pass.

---

## Screen 10 — Injected-Fault Evaluation

**Route:** `/evaluation/injections`  
**Purpose:** Show synthetic fault sensitivity for Pillar A.

### Layout

Cards:

- Power degradation detection
- Flow drift detection
- Pressure drift detection
- Stuck sensor detection
- Spike/dropout detection
- Cross-sensor inconsistency detection

Charts:

- AUROC by injected fault family
- Detection delay distribution
- Attribution accuracy
- Detector comparison

Caveat block:

> Injected faults test sensitivity to defined synthetic scenarios. They do not prove real-world field fault recall.

### Empty state

> No injected-fault evaluation artifact found.

### Error state

> Injected-fault results are incomplete. Pillar A scorecard should mark this gate unavailable or FAIL according to frozen rules.

---

## Screen 11 — Evidence Report Builder / Export

**Route:** `/reports/builder`  
**Purpose:** Build exportable evidence packages.

### Layout

Left panel:

- Report type selector
- Section checklist
- Selected events
- Selected efficiency opportunities
- Include appendix toggles

Main panel:

- Live report preview
- Page thumbnails
- Missing evidence warnings

Right panel:

- Export settings
  - PDF
  - HTML
  - CSV
  - JSON
  - Include manifest
  - Include checksums
  - Include charts

Footer:

- Export evidence report button

### Required report sections

- Advisory-only boundary
- Executive summary
- Scorecard
- Health events
- Efficiency opportunities
- Data status
- Model lifecycle
- Caveats/cannot-claim
- Artifact manifest

### Empty state

> Start by selecting a report type or adding health events and efficiency opportunities.

### Loading state

Preview skeleton.

### Error state

> Report export failed. No station systems were contacted or modified. Check local write permissions.

---

## Screen 12 — Export History and Artifacts

**Route:** `/reports/exports`  
**Purpose:** List generated reports and downloadable artifacts.

### Layout

Table:

- Export ID
- Generated time
- Report type
- Formats
- Run ID
- File path
- Checksum
- Status

Actions:

- Open local file
- Download artifact
- Copy checksum
- View manifest

### Empty state

> No reports have been exported for this run.

### Error state

> Export manifest could not be loaded.

---

## Screen 13 — Data & Holdout Status

**Route:** `/data/status` and `/data/holdout`  
**Purpose:** Show schema, unit, mode, missingness, and leakage status.

### Layout

Cards:

- Schema validation
- Unit validation
- Mode mix
- Missingness
- Cadence/gaps
- Holdout lock status

Charts:

- Mode mix donut/bar:
  - Auto
  - Manual
  - Other/unprofiled
- Missingness heatmap.
- Data availability timeline.
- Low-flow/pump-off intervals.

Holdout panel:

- March 2026 locked holdout.
- Not used for training/tuning.
- Leakage guard result.
- Files read by stage.

### Empty state

> Data profile has not been generated.

### Error state

> Data validation failed. Modeling and scorecards should not proceed until required schema and unit issues are resolved.

---

## Screen 14 — Model Lifecycle Offline

**Route:** `/model/lifecycle`  
**Purpose:** Audit offline model artifacts, thresholds, frozen configs, and versions.

### Layout

Timeline:

- Data profile
- Pillar A baseline training
- Pillar A detector training
- Pillar B envelope build
- Freeze
- March scoring
- Report export

Cards:

- Health model version
- Threshold version
- Efficiency envelope version
- Frozen config hash
- Code version
- Seed
- Artifact paths

Tables:

- Feature list
- Thresholds
- Matching rules
- Excluded features
- Prohibited import scan

### Empty state

> No lifecycle metadata found for this run.

### Error state

> Lifecycle metadata is incomplete. Audit confidence is reduced.

---

## Screen 15 — Settings & Governance

**Route:** `/settings/governance`  
**Purpose:** Show read-only governance, safety guard, and display settings.

### Layout

Safety boundary card:

- Offline only
- No write path
- Does not influence control
- Site integration not allowed

Prohibited capabilities list:

- No control endpoints
- No AMAX/CODESYS integration
- No SCADA writes
- No HMI commands
- No edge deployment package

Read-only settings:

- Theme
- Density
- Time zone
- Units display
- Report branding
- Accessibility preferences

### Empty state

Not applicable; governance always renders.

### Error state

If governance metadata missing:

> Safety metadata is missing. The dashboard must treat this run as invalid until governance metadata is restored.

---

# 6. Component Library

## Component 1 — Advisory-Only Status Banner

**Purpose:** Persistent safety boundary.

### Variants

- Global banner
- Compact tablet banner
- Report header/footer banner
- Inline safety chip

### Content

Primary:

> ADVISORY ONLY — does not control the station

Secondary:

> Offline historical evidence. No write path. No actuation. AMAX/CODESYS owns control.

### Accessibility

- Role: `status` or landmark region.
- High contrast.
- Not color-only; includes shield icon and text.
- Keyboard focusable “Details” link.

---

## Component 2 — Health Gauge

**Purpose:** Show health score 0–100 with severity.

### Visual

- Semicircular or horizontal gauge.
- Prefer horizontal bar for density.
- Score number large.
- Severity text always shown.

### Bands

- 80–100 Normal
- 60–79 Advisory
- 40–59 Warning
- 0–39 High severity

### Rules

- Never use green alone for “safe.”
- High severity uses red/orange plus icon and label.
- Include “Offline score” caption.

---

## Component 3 — Anomaly Timeline

**Purpose:** Display health scores and events over time.

### Features

- Time-series line for health.
- Shaded event regions.
- Severity band background.
- Mode timeline below.
- Data-quality markers.
- Hover/click event details.

### Safety copy

Tooltip footer:

> Offline health event — not a live alarm and not connected to station control.

---

## Component 4 — Baseline-vs-Model Chart

**Purpose:** Compare detector scores and thresholds.

### Visual

- Multi-line chart:
  - learned detector
  - SPC
  - Mahalanobis
  - persistence residual
- Frozen threshold line.
- Event interval highlight.

### Requirements

- Threshold label includes source: “Frozen from 2025 validation.”
- Chart legend accessible.
- Supports log scale only with clear label.

---

## Component 5 — Specific-Energy Scatter with Efficient Envelope Overlay

**Purpose:** Explore actual vs historical efficient operation.

### Visual

- X-axis selectable: demand, head, speed, flow.
- Y-axis: kWh/m³.
- Historical comparable points in muted blue/gray.
- Actual selected point in high-contrast outline.
- p25 envelope line or band.
- p10 sensitivity line dashed.

### Tooltip

- Actual SE
- Envelope SE
- Comparable count
- Match distance
- Confidence
- Advisory-only footer

---

## Component 6 — PASS/FAIL Scorecard Card

**Purpose:** Display honest evaluation status.

### Variants

- PASS
- FAIL
- NOT RUN
- INCOMPLETE
- BLOCKED

### Design

- PASS: blue-green with check icon and text.
- FAIL: red-orange with X icon and text.
- BLOCKED: amber with lock icon.
- NOT RUN: neutral gray.

### Rules

- Safety/leakage FAIL forces overall FAIL.
- Never hide FAIL metrics.
- Include “View evidence” link.

---

## Component 7 — Evidence / Export Panel

**Purpose:** Collect selected events/opportunities for report.

### Features

- Selected items list.
- Evidence completeness status.
- Missing artifact warnings.
- Section toggles.
- Export formats.
- Checksum display after export.

### Copy

Button:

> Export evidence report

Not allowed:

> Publish
> Send to station
> Push

---

## Component 8 — Locked-Holdout Badge

**Purpose:** Show March 2026 holdout protection.

### Variants

- Locked
- Scored after freeze
- Leakage PASS
- Leakage FAIL

### Visual

- Lock icon.
- Text label.
- Tooltip with freeze timestamp and checksum.

### Example

> Locked holdout: March 2026 — scoring only after frozen config.

---

## Component 9 — Confidence and Support Meter

**Purpose:** Show advisory confidence without overclaiming.

### Inputs

- Comparable sample count
- Match distance
- Missingness
- Mode quality
- Historical range support

### Output

- High / Medium / Low / Unsupported
- Numeric 0–1 optional

### Rules

- Unsupported intervals display “No advisory.”
- Low confidence cannot show estimated opportunity as primary metric.

---

## Component 10 — Caveat / Cannot-Claim Block

**Purpose:** Make limitations visible.

### Variants

- Inline caveat
- Report caveat section
- Scorecard cannot-claim list
- Modal explanation

### Standard claims

- Statistical anomaly is not confirmed fault.
- Offline opportunity is not realized savings.
- Observed speed range is not executable setpoint.
- Single-site Yilan only.
- No control integration.

---

# 7. Visual Design Direction

## 7.1 Tone

The visual tone should be:

- Industrial
- Calm
- Technical
- Trustworthy
- Evidence-first
- Non-alarming

Avoid:

- Bright marketing gradients.
- Excessive red.
- Animated alerts.
- “AI magic” motifs.
- Control-room alarm styling.

## 7.2 Color palette

### Light mode

| Token | Color | Use |
|---|---:|---|
| `bg.page` | #F5F7FA | Main background |
| `bg.surface` | #FFFFFF | Cards |
| `bg.surface-muted` | #EEF2F6 | Secondary panels |
| `text.primary` | #142033 | Primary text |
| `text.secondary` | #536173 | Secondary text |
| `border.default` | #D6DEE8 | Borders |
| `brand.navy` | #183A59 | Header/banner |
| `brand.blue` | #2F6FA3 | Links, selected states |
| `safety.amber` | #D89500 | Advisory accent |
| `success.teal` | #13866F | PASS/normal support |
| `warning.orange` | #C96A1B | Warning |
| `danger.red` | #B83A32 | FAIL/high severity |
| `neutral.gray` | #7A8696 | Unknown/not run |

### Dark mode

Dark mode is required for control-room lighting.

| Token | Color | Use |
|---|---:|---|
| `bg.page` | #0B1118 | Main background |
| `bg.surface` | #111A24 | Cards |
| `bg.surface-muted` | #172230 | Secondary panels |
| `text.primary` | #E7EEF7 | Primary text |
| `text.secondary` | #AAB7C6 | Secondary text |
| `border.default` | #2A394A | Borders |
| `brand.navy` | #071522 | Banner |
| `brand.blue` | #6FA8DC | Links |
| `safety.amber` | #F2B84B | Advisory accent |
| `success.teal` | #44BBA4 | PASS |
| `warning.orange` | #F09A45 | Warning |
| `danger.red` | #F06A61 | FAIL/high severity |
| `neutral.gray` | #93A0AE | Unknown |

## 7.3 Severity color coding

Severity must never rely on color alone.

| Severity | Color | Icon | Text |
|---|---|---|---|
| Normal | Teal/blue-green | Check circle | Normal |
| Advisory | Blue/amber | Info | Advisory |
| Warning | Orange | Triangle | Warning |
| High severity | Red-orange | Octagon/exclamation | High severity |

For color-blind accessibility:

- Use icons.
- Use text labels.
- Use patterns/hatching for critical chart regions.
- Maintain 3:1 contrast for graphical objects and 4.5:1 for text.

## 7.4 PASS/FAIL color coding

| Status | Color | Icon | Text |
|---|---|---|---|
| PASS | Teal | Check | PASS |
| FAIL | Red-orange | X | FAIL |
| BLOCKED | Amber | Lock | BLOCKED |
| NOT RUN | Gray | Minus | NOT RUN |
| INCOMPLETE | Amber/gray | Alert | INCOMPLETE |

Do not use green/red only. Use labels in every card and table cell.

## 7.5 Typography

Recommended typefaces:

- Primary UI: Inter, Source Sans 3, or IBM Plex Sans.
- Numeric/table: IBM Plex Sans or tabular-nums enabled.
- Monospace for hashes/config: IBM Plex Mono.

Scale:

| Token | Size | Use |
|---|---:|---|
| Display | 28–32px | Page title/dashboard summary |
| H1 | 24px | Screen title |
| H2 | 20px | Section |
| H3 | 16–18px | Card title |
| Body | 14px | Standard UI |
| Dense table | 13px | Data-dense rows |
| Caption | 12px | Chart notes/caveats |

Use tabular numbers for:

- Health score
- kWh
- kWh/m³
- timestamps
- PASS/FAIL metrics

## 7.6 Spacing and density

Base spacing unit: 4px.

Recommended:

- Card padding desktop: 16–20px.
- Card padding tablet: 12–16px.
- Table row height:
  - Comfortable: 44px.
  - Dense: 36px.
  - Minimum: 32px only for expert desktop mode.
- Chart height:
  - Overview sparkline: 120–160px.
  - Main chart: 280–420px.
  - Tablet chart: 220–320px.

Density toggle:

- Comfortable
- Compact
- Control-room high contrast

Density changes should never hide safety banner or caveat labels.

---

# 8. Responsive Design

## 8.1 Desktop layout

Target widths:

- 1366px minimum preferred.
- Optimized for 1440–1920px.

Desktop behavior:

- Left nav visible.
- Right evidence drawer available.
- Charts and tables side-by-side.
- Multi-chart comparison enabled.
- Report builder uses 3-column layout.

## 8.2 Tablet layout

Target:

- 768–1024px width.
- Landscape preferred but portrait supported.

Tablet behavior:

- Advisory banner remains top sticky.
- Left nav collapses to icon rail or hamburger.
- Context filters collapse into filter drawer.
- Tables become horizontally scrollable with frozen first column.
- Detail screens become stacked sections.
- Evidence drawer becomes bottom sheet.
- Report builder becomes stepper:
  1. Choose report type
  2. Select sections
  3. Review evidence
  4. Export

## 8.3 Small tablet / portrait behavior

- Summary cards stack 1 column.
- Charts use simplified legends.
- Tables show priority columns:
  - Event ID
  - Severity
  - Start
  - Duration
  - Top contributor
  - Action
- Secondary metrics move into row expansion.
- No chart tooltip should require hover only; tap opens details.

---

# 9. Accessibility — WCAG 2.1 AA

## 9.1 Contrast

- Body text contrast at least 4.5:1.
- Large text contrast at least 3:1.
- Chart lines and important graphical objects at least 3:1.
- Focus indicators at least 3:1 against adjacent colors.

Dark mode must be tested in control-room lighting and should avoid pure black/white glare.

## 9.2 Keyboard navigation

All interactive elements must be keyboard accessible:

- Navigation
- Filters
- Date range selectors
- Table sorting
- Row expansion
- Chart data table fallback
- Report builder
- Export controls

Focus order should follow visual order.

## 9.3 Screen reader support

Requirements:

- Banner announced as advisory status.
- PASS/FAIL cards include text status.
- Charts have accessible summaries and linked data tables.
- Icons have labels or are decorative as appropriate.
- Tabs use ARIA tab patterns.
- Tables use proper headers.
- Error messages are announced.

Example chart summary:

> Health score timeline for March 8, 2026. Three high-severity offline health events detected. Worst score 31. Top contributors: edge_power and node_pressure. This is not a live alarm.

## 9.4 Non-color encoding

Severity and status must use:

- Text label
- Icon
- Shape or pattern where useful
- Tooltip/caption

Efficiency scatter should use shape differences in addition to color:

- Actual point: outlined diamond.
- Historical comparable: circle.
- Efficient envelope: solid/dashed line.
- Unsupported: hollow gray marker.

## 9.5 Motion and flashing

- No flashing alerts.
- No auto-refresh implied as live monitoring.
- Use subtle transitions only.
- Respect reduced motion settings.

## 9.6 Touch targets

Tablet touch targets:

- Minimum 44×44px for primary controls.
- Table row actions should open detail drawer rather than rely on tiny icons.
- Filter chips should be tappable.

---

# 10. Evidence Report Specification

## 10.1 Report types

1. Shift Health Report
2. Anomaly Evidence Report
3. Efficiency Opportunity Report
4. Unified A+B Evaluation Report
5. ML Audit Appendix

## 10.2 Required header/footer

Every page must include:

Header:

> AquaOptima Pump Station Optimizer Lite — Offline Evidence Report

Safety line:

> **ADVISORY ONLY — does not control the station. No write path. No actuation. AMAX/CODESYS owns control.**

Footer:

- Site: Yilan
- Run ID
- Generated timestamp
- Page number
- `evaluation_mode=offline_only`
- `write_path=none`

## 10.3 Executive summary

Must include:

- Pillar A PASS/FAIL.
- Pillar B PASS/FAIL.
- Safety PASS/FAIL.
- Leakage PASS/FAIL.
- Health event summary.
- Efficiency opportunity summary.
- Cannot-claim list.

## 10.4 Health event report section

For each selected event:

- Event ID
- Start/end
- Duration
- Severity
- Min health score
- Top contributors
- Detector agreement
- Charts
- Data quality flags
- Caveat: statistical anomaly, not confirmed fault
- No control action taken

## 10.5 Efficiency report section

For each selected opportunity:

- Interval
- Actual SE
- Envelope SE p25/p10
- Volume
- Estimated kWh opportunity
- Comparable count
- Match distance
- Observed speed range
- Confidence
- Caveats:
  - Not realized savings
  - Not executable setpoint
  - Historical comparability limitations
  - Valve position unavailable if applicable

## 10.6 Audit appendix

Include:

- Input file checksums.
- Frozen config hash.
- Feature list.
- Thresholds.
- Matching rules.
- Holdout leakage manifest.
- Prohibited import scan.
- Model versions.
- Artifact manifest.

---

# 11. Content and Terminology Guidelines

## 11.1 Preferred language

Use:

- Offline evidence
- Offline health event
- Statistical anomaly
- Advisory
- Historically observed speed range
- Estimated offline opportunity
- Matched historical envelope
- Comparable intervals
- Frozen threshold
- Locked holdout
- No control action taken

Avoid:

- Alarm
- Fault detected, unless externally confirmed
- Guaranteed savings
- Recommended setpoint
- Apply
- Execute
- Optimize station
- Live monitoring
- Control action
- Command

## 11.2 Standard caveat copy

### Health

> This event indicates statistically unusual operation relative to the frozen offline model and baselines. It is not a confirmed equipment fault unless validated by external maintenance or operator records.

### Efficiency

> This is a counterfactual offline estimate based on historically observed comparable intervals. It is not realized savings and is not an executable setpoint recommendation.

### Safety

> AquaOptima does not control the station. It has no write path, no actuation path, and no site integration in this version. AMAX/CODESYS owns control.

---

# 12. Empty, Loading, and Error State Pattern

Every state must preserve safety context.

## Empty state formula

1. Clear reason.
2. What user can do next.
3. Safety reminder.

Example:

> No supported efficiency advisories found for this period. Try widening filters or review exclusion reasons. AquaOptima has produced no setpoint and does not control the station.

## Loading state formula

1. Skeleton UI.
2. Local artifact language.
3. Safety reminder.

Example:

> Loading offline artifacts. No live station connection is used.

## Error state formula

1. What failed.
2. Operational impact.
3. No station modification.
4. Next step.

Example:

> Scorecard could not be validated because safety metadata is missing. Overall status is treated as FAIL. No station systems were contacted or modified.

---

# 13. Final UX Acceptance Criteria

The dashboard and report package is acceptable only if:

1. The advisory-only banner appears on every screen and report page.
2. No UI element implies control, execution, write-back, live alarm, or setpoint command.
3. Health anomalies are presented as offline evidence, not confirmed faults.
4. Efficiency opportunities are presented as offline estimates, not realized savings.
5. Observed speed ranges are never labeled as executable setpoints.
6. PASS/FAIL scorecards are visible, honest, and exportable.
7. Safety and leakage failures force overall FAIL.
8. Empty/loading/error states preserve safety language.
9. Color is never the sole carrier of meaning.
10. Desktop and tablet layouts remain usable with the banner visible.
11. Reports include safety metadata, caveats, and cannot-claim statements.
12. Users can trace every major claim back to artifacts, baselines, and frozen configuration.
13. The product remains strictly offline, read-only, and evidence-focused.

---

# 14. North Star Experience

A successful operator experience should sound like this:

> “I can see that AquaOptima is not controlling anything. For this shift, there were two high-severity offline health events. I can see which variables contributed and which baselines agreed. For efficiency, I can see that some intervals had historically lower specific energy under similar conditions, but the report clearly says this is only an offline opportunity and not a setpoint. I can export the evidence for review without any risk of sending commands to the station.”

That is the intended UX: calm, dense, auditable, honest, and unmistakably advisory-only.