# PO Orientation Brief: MVP v1, dPHM, and dPHM-PINN

## Purpose

This is the product-owner orientation document for AquaOptima's current pump-station MVP and the dPHM / dPHM-PINN roadmap. It is intentionally written to be read in **5-10 minutes**: comprehensive enough to explain what is being built and why, but not a substitute for engineering design documents.

Use this document as a living Q&A ledger while Product, Kevin, Hunter, and engineering converge on the correct framing. Update it whenever a new product question changes the answer, and keep detailed formulas / API references in the linked engineering docs.

## Product-manager summary

AquaOptima should be explained as a **pump-station optimization product that grows into a lightweight digital twin**.

The business problem is not "build a fancy AI model." The business problem is that water operators must reliably move treated water while managing pressure, flow, energy cost, pump wear, and operational risk. They often do this with incomplete downstream visibility, conservative rules, and aging pump curves. That creates wasted energy, inefficient pump combinations, avoidable wear, and limited confidence in new recommendations.

Quantified external context: the US EPA notes that drinking water and wastewater plants are often among municipal governments' largest energy consumers, drinking-water system energy can be as much as **40% of operating costs**, and energy-efficiency practices can save **15-30%** in some utility contexts. AquaOptima should treat these as market-context ranges, not field-proven product claims until pilot baselines verify them.

The product story is:

1. **MVP v1 solves the immediate business problem**: optimize a large WTP / transmission pump station that usually has one source boundary and one to three outlet trunks. MVP v1 is not only regression + MPC; it also includes the first version of **Multi-Goal PID**, the deterministic multi-objective control layer described in the patent disclosure: data acquisition, pump-combination/demand modelling, real-time control, controller/platform exception handling, and operator monitoring.
2. **dPHM makes MVP v1 more trustworthy when needed**: it is the lightweight hydraulic digital-twin core. It checks whether recommendations are physically plausible, calibrates site-specific pump / pipe behaviour, and explains residuals when telemetry disagrees with the model.
3. **dPHM-PINN expands the product from station optimization to network intelligence**: it uses the hydraulic digital twin plus learning from telemetry to estimate unmeasured states, improve demand forecasting, and support more complex sites with multiple stations, branches, tanks, sparse sensors, or looped zones.

Simple positioning:

> **MVP v1 is the commercial wedge. Multi-Goal PID is the operator-trust/control-policy layer inside MVP v1. dPHM is the optional physics trust layer. dPHM-PINN is the scaling layer.**

This framing keeps the business value clear while avoiding overclaiming that the current pilot already controls or understands the entire downstream distribution network.

## 1. Short answer

AquaOptima's current MVP v1 is best understood as **transmission-side pump-station optimization**:

```text
source tank / WTP clearwell
        |
        v
suction header -> parallel pumps -> discharge header
        |                         |
        |                         v
        +------------------> 1-3 trunk outlets -> supply zone / reservoir / main
```

It is strongest where the site boundary is observable but the full downstream distribution network is not. The first pilot archetype is a **Satellite WTP sending treated water through a main outlet into a supply-zone network** where AquaOptima sees the WTP outlet but not the internal nodes of the zone.

- **MVP v1 = control optimizer for the station boundary.**
- **dPHM = differentiable hydraulic physics core that can be used independently.**
- **dPHM-PINN = network-aware intelligence layer for sparse-sensor, multi-node, multi-station scaling.**

For current target sites, MVP v1 should remain the product control core. dPHM can improve MVP v1 sooner. dPHM-PINN should initially run as a shadow / validation / forecasting layer until topology, telemetry, and safety evidence justify stronger product claims. Current repo phases preserve the safety boundary: **no live OT binding, no PLC/PAC/SCADA write, no command emission, and no control-loop closure** unless a later safety gate explicitly approves it.

## 2. Product questions and current answers

### Q1. What kind of site is MVP v1 best designed for?

**Best fit:** transmission or WTP-outlet pump stations with a small number of hydraulic boundaries.

Typical pattern:

- one source boundary: treated-water tank, reservoir, WTP clearwell, or suction header;
- one pump station with 1-N pumps, preferably with pump speed / status / power telemetry;
- one primary discharge trunk, sometimes two or three;
- downstream demand is visible mostly as aggregate outlet flow / pressure, not as individual customer or distribution-network nodes;
- operator goals are expressed as pressure, flow, volume, schedule, or energy-efficiency targets.

Rule of thumb:

| Site shape | MVP v1 fit | Why |
|---|---:|---|
| 1 inlet -> pump station -> 1 outlet trunk | Very high | Boundary control problem is clear and explainable. |
| 1 inlet -> pump station -> 2-3 trunk outlets | High | Still manageable with station-level MPC and outlet constraints. |
| Multiple stations feeding one pressure zone | Medium | Interactions grow; dPHM/dPHM-PINN becomes more useful. |
| Full looped distribution zone with many nodes | Lower as standalone | Needs network topology and more state estimation. |

### Q2. What operating process is MVP v1 improving?

The current process is a pump-operation decision loop:

```text
100 Data acquisition: live pressure / flow / power / pump state
        |
        v
200 Pump-combination & demand modelling:
    HQ/efficiency regression, BEP table, demand targets
        |
        v
700 Operator target / override input
        |
        v
500 Nominal control:
    MPC searches pump combinations and VFD schedules
        |
        v
Multi-Goal PID priority cascade resolves tradeoffs
        |
        v
400/600 Exception handling:
    hold, latch, alarm, or resume safely
        |
        v
station meets pressure + flow goals with better total efficiency
```

Control goals:

1. meet target discharge pressure;
2. meet target flow or delivered volume;
3. keep each pump near an efficient operating region, e.g. around BEP where feasible;
4. maximize total station efficiency;
5. avoid unsafe or undesirable operating states;
6. preserve operator override and existing PLC authority.

Multi-Goal PID is the first-version policy layer that makes these goals operational. It should be deterministic, versioned, and auditable: when goals conflict, the product should be able to explain which goal won and why.

### Q3. What kind of site needs MVP v1, dPHM-only, or dPHM-PINN, and why?

Do not force every site into dPHM-PINN. The right product layer depends on site complexity, trust needs, and data maturity.

```text
Simple / current pilot              Medium complexity                 Network-scale
1 source -> pumps -> 1 outlet        1 source -> pumps -> 2-3 outlets   multi-station / looped zone
        |                                      |                                  |
        v                                      v                                  v
     MVP v1                             MVP v1 + dPHM                       dPHM-PINN
commercial wedge                         trust layer                         scaling layer
```

The practical decision rule:

- If the site is a simple WTP / transmission station and MVP v1 already gives physically realistic, trusted recommendations, **do not add dPHM just because it exists**.
- Add **dPHM-only** when the business needs stronger trust, calibration, diagnostics, repeatability across new sites, or long-term maintenance evidence.
- Add **dPHM-PINN** when the business problem becomes network intelligence: sparse sensors, multiple stations, branches, tanks, or unmeasured nodes.

Most new sites will start with some uncertainty. That does **not** automatically mean full dPHM-PINN from day one. The default path should be: start with MVP v1 + good onboarding checks; add dPHM-only as a standard validation/calibration option when uncertainty affects trust, safety, or repeatability; reserve dPHM-PINN for sites where network inference or forecasting materially changes the business outcome.

Why this matters to the customer:

| Site / maturity | Operator pain | Best-fit layer | Why | Business outcome |
|---|---|---|---|---|
| One station, one outlet, good telemetry, MVP v1 trusted | Need efficient pump schedule | MVP v1 | Boundary control is enough; avoid unnecessary model complexity | Fastest ROI and simplest operator adoption. |
| Existing site where MVP v1 is already trusted | Maintain performance over time | MVP v1 first; dPHM only if drift or diagnostics matter | dPHM may not be needed immediately if trust is already solved | Keep product simple; add physics later for maintenance evidence. |
| New site with limited trust in pump curves / units / meters | Need confidence before recommending schedules | MVP v1 + dPHM | dPHM validates physical plausibility and catches bad assumptions | Faster commissioning, fewer false savings claims. |
| One station, 2-3 outlets or branch uncertainty | Unsure how outlet branches affect pressure / flow | MVP v1 + dPHM; PINN only if enough telemetry/topology exists | Physics tests branch feasibility; learning may help later | Fewer unsafe or inefficient recommendations. |
| District / pressure zone with tanks and branches | Some pressures / demands are unknown | dPHM-PINN | Learns temporal demand patterns and infers virtual states using topology | Better service confidence and pressure management. |
| Multiple interacting stations / reservoirs | One station's action affects another | dPHM-PINN | Captures interactions that station-only MPC may miss | Better system-level energy and reliability decisions. |
| Looped network with sparse sensors | Cannot observe every node | dPHM-PINN | Uses physics residuals to constrain predictions at unmeasured locations | Lower instrumentation burden; stronger scalable deployment story. |

Rule of thumb:

| Site shape | MVP v1 fit | dPHM-only fit | dPHM-PINN fit | Product reason |
|---|---:|---:|---:|---|
| Single station, one outlet, no downstream topology | Very high | Optional | Low-medium | Start simple; dPHM is for validation/calibration, not mandatory. |
| Single station, 2-3 outlets, simple known downstream topology | High | Medium-high | Medium | Branch tradeoffs may justify a physics trust layer. |
| Existing site with strong MVP trust and stable curves | High | Low-medium | Low | Defer dPHM until maintenance, drift, or new-site replication needs appear. |
| New site with uncertain curves/meters/units | Medium-high | High | Low-medium | dPHM reduces commissioning and false-confidence risk. |
| District / pressure zone with tanks, valves, branches, sparse sensors | Medium | Medium | High | Helps manage service risk without instrumenting every node. |
| Multiple interacting stations / reservoirs | Medium | Medium | Very high | Moves AquaOptima from local station savings to system-level optimization. |
| Full looped distribution network with partial observability | Low-medium | Medium | Very high | Strongest case for a physics-informed network model. |

### Q4. Does dPHM-PINN fit the sites AquaOptima is targeting now?

**Partially, but not as the first direct-control layer.**

For current transmission / Satellite WTP outlet pilots:

- MVP v1 is the most direct product fit.
- If MVP v1 is already trusted and physically realistic at an existing site, dPHM is **not mandatory** for immediate value.
- dPHM becomes useful for long-term maintenance, curve drift detection, onboarding new sites, validating questionable telemetry, and defending recommendations with physics evidence. Multi-Goal PID already supplies deterministic control trust; dPHM supplies hydraulic-physics trust when the site needs it.
- dPHM-PINN is useful as a shadow intelligence layer, especially for demand forecasting, residual detection, and future network expansion.

Do not overclaim that dPHM-PINN optimizes the full supply-zone network when AquaOptima only sees the WTP outlet. The honest claim is:

> We optimize station operation against measured boundary conditions and aggregate demand. dPHM / dPHM-PINN provide physically grounded validation and a path toward network-aware optimization as topology and telemetry expand.

## 3. MVP v1 vs dPHM vs dPHM-PINN

| Layer | Product-manager description | Inputs | Outputs | Business outcome | Best current use |
|---|---|---|---|---|---|
| MVP v1 | Station optimization product with Multi-Goal PID | Station telemetry, pump curves, outlet pressure/flow, operator targets | Pump/VFD schedule or recommendation with goal-priority explanation | Fastest path to energy savings, pressure/flow reliability, and operator adoption at the first pilot | Core pilot product for WTP / transmission pump station. |
| dPHM-only | Lightweight hydraulic digital-twin core | Topology, pipe/pump parameters, boundary conditions, candidate flows/heads | Physics residuals, feasibility, predicted hydraulic state, calibration loss | Higher trust where needed: fewer unrealistic recommendations, better calibration, clearer explanations when telemetry looks wrong | Add when MVP v1 needs physics evidence, maintenance diagnostics, or new-site repeatability. |
| dPHM-PINN | Learning layer on top of the hydraulic digital twin | Topology, telemetry windows, sparse sensor observations | Forecasts, inferred states, physically regularized predictions | Scaling story: better forecasts and network insight without needing sensors at every node | Shadow layer now; network intelligence layer later. |

### Module features by solution level

This table lists the product modules without turning the brief into a technical spec.

| Module feature | MVP v1 | dPHM-only adds | dPHM-PINN adds |
|---|---|---|---|
| Pump performance model | HQ curve + efficiency curve regression | Physics-constrained pump head validation / calibration | Learns pump-performance drift patterns if enough history exists |
| Demand handling | Statistical demand defaults; operator-adjustable targets | Feasibility check for assumed demand against hydraulic boundaries | Temporal/spatial demand forecast using topology + telemetry windows |
| Optimizer | MPC searches pump/VFD schedules | dPHM can act as feasibility checker or plant-model component | Uses forecasts / inferred states to improve optimization context |
| Multi-Goal PID / policy layer | Dynamic multi-objective controller: priority cascade, pump switching, bounded ramping, exception ladder, operator audit | dPHM evidence can inform whether a candidate violates physics or telemetry is inconsistent | dPHM-PINN evidence can inform future network-aware priorities |
| Safety / operator trust | Familiar targets, operator override, existing PLC remains authority | Physics residuals explain why a recommendation is plausible or suspicious | Shadow first; explanations must be simplified because ML is harder to trust |
| Diagnostics | Telemetry validity, demand validity, switch timeout, fail/compromise flags, alarms and dashboard logs | Sensor/unit/curve drift, hydraulic inconsistency, anomaly residuals | Virtual-node / forecast disagreement and network-level anomaly clues |
| Best business role | First-pilot ROI and adoption | Trust, maintainability, new-site repeatability | Scale from station product to network intelligence |

### Multi-Goal PID: where it fits

Multi-Goal PID is part of MVP v1, not a replacement for MPC, dPHM, or dPHM-PINN. In the uploaded patent disclosure, it is broader than a simple PID loop: it is a **dynamic multi-objective multi-pump control architecture** with modelling, switching, exception handling, and operator supervision.

Product interpretation:

> MVP v1 decides how to run the station. MPC searches for feasible pump combinations and VFD schedules. Multi-Goal PID is the deterministic real-time control and policy layer that resolves goal conflicts, ramps safely, handles exceptions, and keeps recommendations operator-safe and explainable.

Patent-disclosure module map:

| Patent block | Product meaning | PO interpretation |
|---|---|---|
| 100 Data Acquisition & Processing | Cleans, validates, aligns, normalizes, and archives telemetry | Makes control decisions depend on usable data, not raw noisy tags. |
| 200 Pump Combination & Demand Modelling | Builds pump performance/BEP tables, demand targets, and feasible combination matrices | Converts history + pump knowledge into lookup/reference intelligence for control. |
| 300 Real-time Control | Tracks state, setpoints, counters, alarms, operator input, and health every cycle | The real-time brain that decides whether control can proceed. |
| 400 Controller Exception Handling | Prioritized alarm/warning ladder with latching and confirmation dwell | Prevents unsafe automation during manual override, bad demand, bad sensors, extreme data, or switching failures. |
| 500 Nominal Control Operation | Selects better pump combination, switches/ramp pumps over multiple cycles, adjusts head/flow/efficiency | The main optimization loop for pressure, flow, BEP/efficiency, and smooth transitions. |
| 600 Platform Exception Handling | Aggregates hardware/network/telemetry/model/controller faults | Keeps platform-level faults visible and prevents hidden dependency failures. |
| 700 Operator Monitoring & Interface | Dashboard, manual intervention, alarm acknowledgement, audit trail | Makes the product supervisable and acceptable for conservative plant operations. |

The first version should focus on explicit, auditable goals:

| Goal family | Why the operator cares | Example metric / constraint |
|---|---|---|
| Pressure / head minimum | Avoid service failure | measured head >= target minimum |
| Pressure / head maximum | Avoid bursts/leakage/excess stress | measured head <= site maximum |
| Flow / volume delivery | Meet WTP / zone supply mission | delivered volume vs target schedule; flow within allowed band |
| Energy efficiency | Reduce kWh/m3 and inefficient pump combinations | total station efficiency, BEP-band runtime, predicted energy per candidate combination |
| Pump combination switching | Avoid disruptive start/stop behavior | multi-cycle start/confirm/stop/ramp sequence; switch timeout alarm |
| Pump wear protection | Avoid unnecessary starts, bad speed ranges, excessive cycling | max starts/hour, runtime balancing, maintenance flags, min/max frequency |
| Smoothness / surge avoidance | Avoid rapid changes that operators distrust or that stress assets | pressure/speed rate-of-change limit; bounded Hz-per-cycle ramps |
| Manual override / safety | Preserve existing operating authority | manual override suspends optimization; existing PLC authority remains protected |
| Exception/fault recovery | Maintain safe operation under bad data or equipment faults | latching, confirmation dwell, fail flag, compromise flag, alarm escalation |

Business value:

- It makes MVP v1 more sellable to conservative operators because recommendations are deterministic and auditable, not a black box.
- It creates a clear conflict-resolution story: default priority can be head -> flow -> efficiency, but the priority cascade can be reconfigured for site requirements.
- It supports scalable pump inventory: adding/removing pumps should update performance tables and the combination matrix rather than require controller code changes.
- It reduces operational risk through multi-cycle switching, bounded frequency ramps, latching alarms, dwell confirmation, and operator dashboards.
- It creates patentable product differentiation separate from dPHM-PINN: the neural model is not required for the Multi-Goal PID value proposition.

Relationship to dPHM / dPHM-PINN:

- **Without dPHM:** Multi-Goal PID can still use measured pressure/flow/power, regression models, BEP tables, demand targets, and configured limits.
- **With dPHM:** PID decisions can include physics-feasibility evidence, residual warnings, and better confidence in pump/pipe assumptions.
- **With dPHM-PINN:** future PID/advisory logic can include forecasted demand, inferred network-state risk, and sparse-sensor network context after shadow validation.

### Requirement level comparison

These are planning ranges, not hard product gates. They should be refined after pilot data inventory.

| Requirement | MVP v1 | dPHM-only | dPHM-PINN |
|---|---|---|---|
| Site topology | Station schematic, pump list, inlet/outlet points | Station + simple hydraulic topology: tanks/reservoirs, pipes/headers, pumps, 1-3 outlets if relevant | Network graph with nodes/edges; EPANET/GIS/P&ID strongly preferred |
| Telemetry minimum | Discharge pressure, outlet flow, pump status/speed; power preferred; operator target/override logs, alarms, confirmation counters, switch events for Multi-Goal PID tuning | Same as MVP v1 plus enough boundary data to validate residuals | Multi-axis telemetry over time: pressure/flow/pump states, preferably across multiple nodes/edges |
| Historical data to start | 2-4 weeks can support first defaults; 8-12+ weeks better for daily/weekly patterns | Same or less for feasibility; 4-8+ weeks better for calibration/drift | 8-12+ weeks minimum for useful learning; 3-12 months better for seasonality and robust forecasting |
| Server / compute | Ordinary industrial PC or small server for optimization; edge can be CPU-first | CPU-first is usually enough for steady-state solves and calibration reports | Training/retraining wants GPU or stronger server; edge inference should remain bounded/read-only first |
| Site complexity justified | 1 source, 1-3 outlets, station boundary control | MVP sites needing validation, diagnostics, commissioning, or maintenance drift evidence | District/zone, sparse sensors, multiple stations, tanks/branches/loops |
| Product maturity | Pilot-ready fastest | v1.5 trust/diagnostic layer | v2+ shadow/network intelligence layer |

### Quantified outcome framing

Do not treat these as AquaOptima-proven claims until field baselines validate them.

| Metric | Why it matters | How to measure in pilot | External / planning range |
|---|---|---|---|
| kWh per m3 delivered | Main energy ROI metric | Compare baseline vs optimized periods normalized by volume/head | EPA context: energy can be up to ~40% of drinking-water operating cost; efficiency practices can save 15-30% in some utilities. |
| Pump BEP adherence | Indicates less inefficient operation and potentially less wear | % runtime within target BEP band, e.g. around 90% BEP where feasible | Product target should be site-specific; do not promise until curves are validated. |
| Pressure target compliance | Protects service quality | % intervals within operator pressure band | Target band set by operator/site constraints. |
| Flow / volume target compliance | Ensures operational mission is met | Delivered volume vs target schedule | Target set by WTP/utility. |
| Recommendation rejection rate | Measures trust and practicality | Operator rejects / overrides per week and reason codes | Should fall as calibration and explanations improve. |
| Residual/anomaly count | Measures model-data disagreement | dPHM residual alerts by axis/source | Useful for diagnostics, not a savings claim by itself. |

### Module comparison

| Capability | MVP v1 today | dPHM independently | dPHM-PINN |
|---|---|---|---|
| Pump HQ / efficiency regression | Core module | Can constrain / validate pump head behaviour; efficiency may remain a separate empirical curve | Can learn drift patterns if enough history exists. |
| Demand defaults / forecast | Statistical defaults + operator adjustment | Can check whether assumed demand is hydraulically feasible | Can improve demand forecast using topology + temporal telemetry. |
| MPC optimization | Core module | Can become the differentiable plant model or feasibility checker inside MPC | Can propose forecasts / state estimates for MPC. |
| Multi-Goal PID | Core v1 policy layer for resolving conflicting goals and explaining tradeoffs | Can consume dPHM feasibility/residual evidence | Can later consume forecast / inferred-state risk after shadow validation. |
| Physical feasibility | Mostly constraints around station operating bounds | Strong: mass / energy / head-loss residuals | Stronger for sparse network state estimation. |
| Explainability | High | High-medium; physics residuals are explainable | Medium; needs careful UI explanations. |
| Direct control readiness | Highest, with safety gates | Useful as validator before control | Shadow first; do not use for direct control initially. |

### Business outcome comparison

| Business question | MVP v1 answer | dPHM-only answer | dPHM-PINN answer |
|---|---|---|---|
| How do we win the first pilot? | Show lower kWh/m3 or higher efficiency while meeting pressure/flow targets. | Add only if it increases confidence in the recommendation or catches bad assumptions. | Run in shadow to show future upside without increasing control risk. |
| Why would an operator trust it? | Targets remain familiar: pressure, flow, volume, pump efficiency, override. | Residuals and feasibility checks explain *why* a recommendation is plausible or suspicious. | Provides richer insight, but needs careful UI because ML is harder to trust. |
| What creates measurable ROI? | Reduced kWh/m3, less runtime far from BEP, fewer inefficient pump combinations. | Avoids ROI leakage from wrong curves, bad sensors, or physically impossible schedules. | Expands ROI to district / multi-station optimization when topology and telemetry mature. |
| What quantified targets should we track? | kWh/m3, pressure compliance %, flow/volume compliance %, BEP-band runtime %. | residual error, calibration drift, anomaly count, schedule-feasibility pass/fail. | forecast error, inferred-state error where sensors exist, network-level energy/service KPIs. |
| What reduces deployment friction? | Works with limited station-boundary telemetry. | Helps commission new sites where curves/meters/units are uncertain. | Can reduce long-term need to instrument every node, but needs more setup and validation. |
| What is the risk? | May be too station-local for complex networks. | May be unnecessary on stable existing sites where MVP v1 is already trusted. | Can be over-complex or hard to explain if introduced before customer trust is established. |

## 4. Can dPHM be used independently?

Yes. Kevin's statement is directionally correct: **dPHM is useful without dPHM-PINN**.

dPHM is the differentiable physics core. It does not need the neural network to provide value. However, if MVP v1 already produces trusted, physically realistic recommendations at a stable existing site, dPHM may be a **later add-on**, not an immediate requirement. Its strongest near-term value is in bounded, explainable cases: new-site onboarding, curve/telemetry uncertainty, maintenance drift, anomaly diagnostics, and audit evidence.

### dPHM modules that can improve MVP v1 directly

| dPHM capability | How it improves MVP v1 | Example for WTP outlet / transmission station |
|---|---|---|
| Pump head-gain model | Adds physically consistent pump behaviour to curve regression | Rejects a fitted pump curve that implies impossible head at a given speed. |
| Head-loss model | Estimates pipe/header/trunk losses from flow | Helps separate pump inefficiency from downstream hydraulic resistance. |
| Mass balance residual | Checks if measured flows / demands are internally consistent | Flags meter mismatch when inlet/outlet/branch totals do not balance. |
| Energy residual | Checks whether pressure + flow + pump head are plausible together | Detects bad pressure sensor, wrong unit, stale pump curve, or abnormal operation. |
| Feasibility solver | Tests candidate MPC actions before recommending them | Filters schedules that meet target flow mathematically but violate hydraulic feasibility. |
| Calibration loss | Provides objective function for tuning pump/pipe parameters from history | Learns site-specific correction factors before relying on optimization. |
| Autograd / differentiability | Enables gradient-based calibration and sensitivity analysis | Shows which parameter or target most affects pressure/energy outcome. |

### Practical integration path

```text
MVP v1 baseline
  pump regression + statistical demand + MPC
        |
        v
Add dPHM only when needed
  validate candidate schedules, calibrate new sites, or detect drift
        |
        v
Add dPHM calibration
  tune pump / pipe / loss parameters from historical telemetry
        |
        v
Add differentiable MPC or gradient-assisted optimization
  use sensitivities to search faster / more robustly
        |
        v
Add dPHM-PINN shadow layer
  improve demand forecast + infer missing network states when topology exists
```

## 5. Could differentiable algorithm concepts help MVP v1?

Yes, but the best near-term use is **not** to replace MPC with a neural network. The better use is to make parts of MVP v1 more calibrated, testable, and explainable.

Potential improvements:

1. **Differentiable pump-curve fitting**
   - Fit pump parameters by minimizing pressure / flow / power residuals.
   - Add physical bounds so regression does not produce unrealistic curves.

2. **Differentiable site calibration**
   - Learn station-specific loss coefficients, roughness surrogates, or correction factors from historical telemetry.
   - Useful when datasheets are stale or field conditions differ from design assumptions.

3. **Gradient-assisted MPC**
   - Use dPHM sensitivities to understand how pump speed changes affect discharge pressure, flow, and efficiency.
   - Could reduce brute-force search or improve optimizer stability.

4. **Scenario / target sensitivity**
   - Show operator-facing tradeoffs: "If pressure target rises by 2 m, energy cost increases by X and pump 2 leaves efficient range."
   - This is product-useful even before direct control.

5. **Residual-based anomaly detection**
   - If observed pressure/flow/power disagrees with dPHM beyond tolerance, flag likely sensor error, curve drift, valve state mismatch, leakage, blockage, or abnormal operating condition.

Near-term principle:

> Use differentiability first for calibration, feasibility, sensitivity, and explainability. Only later use it for closed-loop optimization once safety evidence exists.

## 6. Visual examples

### Example A — current MVP v1 sweet spot

```text
[Satellite WTP]
      |
      v
[clearwell / treated-water tank]
      |
      v
+------------------ Pump Station ------------------+
| Pump 1   Pump 2   Pump 3                          |
| HQ + efficiency regression                         |
| MPC chooses speed / combination                    |
+-------------------------+------------------------+
                          |
                          v
                [main outlet meter]
                pressure + flow observed
                          |
                          v
                 [main supply zone]
                 internal nodes not observed
```

Best product claim:

> Optimize the WTP outlet pump station to meet operator pressure / flow / volume targets efficiently.

Avoid claiming:

> Optimize every node in the supply-zone network.

### Example B — where dPHM starts adding value

```text
source tank -> pumps -> outlet trunk -> branch A
                                |
                                +-> branch B
                                |
                                +-> branch C
```

If outlets are 1-3 trunks, MVP v1 can still work. dPHM helps by checking whether the branch flows, pressure targets, and pump head are hydraulically consistent.

### Example C — where dPHM-PINN becomes strategic

```text
          tank
           |
station A--+---- node 1 ---- node 2 ---- station B
           |       |           |             |
        sensor   demand     no sensor      sensor
           |       |           |             |
           +------- looped pressure zone ---+
```

Here dPHM-PINN has a stronger reason to exist because the product needs to infer unmeasured states and learn temporal demand patterns across topology.

## 7. Product roadmap framing

From a product strategy perspective, AquaOptima should not sell every layer at once. Start with a narrow wedge that creates measurable value, then add trust and network intelligence as the customer and data maturity increase.

| Stage | Product framing | Technical layer | Customer-facing outcome |
|---|---|---|---|
| MVP v1 | Station optimization | Regression + demand defaults + MPC + Multi-Goal PID v1 | Better pressure/flow/volume delivery with higher pump efficiency and explainable tradeoffs. |
| v1.5 | Physics-validated station optimization | MVP v1 + independent dPHM | More trustworthy schedules, better calibration, anomaly flags. |
| v2 | Shadow network intelligence | dPHM + dPHM-PINN | Better forecasts, virtual-state inference, evidence for advisory mode. |
| v3 | Advisory / supervised control | dPHM-PINN + optimizer + safety contract | Operator-reviewed recommendations with audit trail. |
| v4 | Qualified edge / bounded proposals | Edge runtime + safety gates | Site-approved supervisory proposals; PLC remains final authority. |

## 8. What is built in the current repo, in PO language

The repo is currently strongest in the foundation required for dPHM / dPHM-PINN rather than a finished operator product. In PO terms, it contains:

- differentiable hydraulic physics primitives for pressurised clean-water networks;
- topology representation and EPANET-style import / diagnostic surfaces;
- telemetry tag mapping and offline replay surfaces;
- calibration-loss reporting for future dPL loops;
- shadow/advisory safety contracts and deployment-package manifests;
- a dPHM-PINN model skeleton / training path for physics-informed learning;
- safety boundaries that intentionally prevent live PLC / PAC / SCADA writes in current phases.

The repo does **not** yet prove field savings at the Satellite WTP pilot, does not directly control pumps, and does not have access to unobserved downstream supply-zone nodes unless a site topology / telemetry package provides them.

## 9. Fact-check notes for water-industry context

- A pressurised water network can be represented as links and nodes: pipes, pumps, and valves connect junctions, tanks, and reservoirs. This is the same basic abstraction used by EPANET-style modelling.
- A Satellite WTP outlet into a supply zone can be treated as a station-boundary optimization problem when internal supply-zone nodes are unavailable.
- Transmission pump stations are often larger and more energy-relevant than small distribution boosters, but exact design varies by utility and geography.
- If downstream topology and telemetry are unavailable, claims should be framed around station boundary performance, not whole-network optimization.
- Hazen-Williams / steady-state hydraulic assumptions are appropriate for many 5-minute operational optimization cycles, but not for transient surge / water-hammer certification.

## 10. Open questions to keep updating

1. What exactly are the first pilot's available tags: suction pressure, tank level, discharge pressure, outlet flow, pump speed, pump power, pump status?
2. Are there 1, 2, or 3 meaningful outlets from the WTP / station boundary?
3. Are operator targets pressure-based, volume-based, schedule-based, energy-cost-based, or a mix?
4. Does the site have pump datasheets and historical maintenance / curve-test data?
5. Is there an EPANET model, GIS topology, P&ID, hydraulic profile, or only station SCADA?
6. Which outputs are acceptable in the pilot: dashboard-only insight, recommendation, operator-approved setpoint, or no setpoint at all?
7. What evidence would make the customer trust a dPHM residual warning or MPC recommendation?
8. What baseline will be used to prove value: existing rule-based control, operator manual strategy, or historical energy per volume delivered?
9. Is MVP v1 already trusted enough at the existing site, or is dPHM needed to explain / defend recommendations?
10. What is the minimum quantified pilot target: kWh/m3 reduction, BEP-band runtime improvement, pressure compliance, or operator acceptance?
11. What compute and deployment environment is acceptable for each layer: station PC, AMAX-class edge, GB10/server, cloud, or offline analysis only?

## 11. How to maintain this document

- Keep this as the 5-10 minute PO orientation.
- Add new product Q&A here as decisions emerge.
- Move formulas, API contracts, and detailed sprint reports to engineering docs and link them instead of expanding this document indefinitely.
- Prefer diagrams, tables, and site archetypes over long prose.
- Mark uncertain field assumptions explicitly until verified with site data or utility operators.
