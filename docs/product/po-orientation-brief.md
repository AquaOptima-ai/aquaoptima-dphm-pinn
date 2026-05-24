# PO Orientation Brief: MVP v1, dPHM, and dPHM-PINN

## Purpose

This is the product-owner orientation document for AquaOptima's current pump-station MVP and the dPHM / dPHM-PINN roadmap. It is intentionally written to be read in **5-10 minutes**: comprehensive enough to explain what is being built and why, but not a substitute for engineering design documents.

Use this document as a living Q&A ledger while Product, Kevin, Hunter, and engineering converge on the correct framing. Update it whenever a new product question changes the answer, and keep detailed formulas / API references in the linked engineering docs.

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
historical station telemetry
        |
        v
learn pump HQ / efficiency behaviour
        |
        v
estimate default demand / target pressure / target volume
        |
        v
operator reviews or adjusts target
        |
        v
MPC chooses feasible pump / VFD schedule
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

### Q3. What kind of site is dPHM-PINN best designed for?

dPHM-PINN is strongest when **network topology matters** and the system has unobserved or sparsely observed hydraulic states.

It fits better as the water network becomes more like this:

```text
reservoir / WTP / tank
        |
        v
station A ---- trunk ---- zone node ---- loop ---- tank
        |                   |             |
        v                   v             v
     branch 1            station B      demand area
        |                                 |
        +----------- sparse sensors ------+
```

Rule of thumb:

| Site shape | dPHM-PINN fit | Why |
|---|---:|---|
| Single station, one outlet, no downstream topology | Low-medium | Full graph model may be overkill; dPHM is enough. |
| Single station, 2-3 outlets, simple known downstream topology | Medium | Can validate branch feasibility and infer limited states. |
| District / pressure zone with tanks, valves, branches, sparse sensors | High | Physics-informed state inference becomes valuable. |
| Multiple interacting stations / reservoirs | Very high | Network interactions are hard for simple station MPC alone. |
| Full looped distribution network with partial observability | Very high | GNN + physics residual has a clear reason to exist. |

### Q4. Does dPHM-PINN fit the sites AquaOptima is targeting now?

**Partially, but not as the first direct-control layer.**

For current transmission / Satellite WTP outlet pilots:

- MVP v1 is the most direct product fit.
- dPHM is useful soon because it can validate hydraulics and improve calibration.
- dPHM-PINN is useful as a shadow intelligence layer, especially for demand forecasting, residual detection, and future network expansion.

Do not overclaim that dPHM-PINN optimizes the full supply-zone network when AquaOptima only sees the WTP outlet. The honest claim is:

> We optimize station operation against measured boundary conditions and aggregate demand. dPHM / dPHM-PINN provide physically grounded validation and a path toward network-aware optimization as topology and telemetry expand.

## 3. MVP v1 vs dPHM vs dPHM-PINN

| Layer | What it is | Inputs | Outputs | Best current use |
|---|---|---|---|---|
| MVP v1 | Station-level optimization product | Station telemetry, pump curves, outlet pressure/flow, operator targets | Pump/VFD schedule or recommendation | Core pilot product for WTP / transmission pump station. |
| dPHM | Differentiable pressurised hydraulic model | Topology, pipe/pump parameters, boundary conditions, candidate flows/heads | Physics residuals, feasibility, predicted hydraulic state, calibration loss | Improve MVP v1 with physics checks and calibration. |
| dPHM-PINN | Physics-informed graph + temporal ML model | Topology, telemetry windows, sparse sensor observations | Forecasts, inferred states, physically regularized predictions | Shadow layer now; network intelligence layer later. |

### Module comparison

| Capability | MVP v1 today | dPHM independently | dPHM-PINN |
|---|---|---|---|
| Pump HQ / efficiency regression | Core module | Can constrain / validate pump head behaviour; efficiency may remain a separate empirical curve | Can learn drift patterns if enough history exists. |
| Demand defaults / forecast | Statistical defaults + operator adjustment | Can check whether assumed demand is hydraulically feasible | Can improve demand forecast using topology + temporal telemetry. |
| MPC optimization | Core module | Can become the differentiable plant model or feasibility checker inside MPC | Can propose forecasts / state estimates for MPC. |
| Physical feasibility | Mostly constraints around station operating bounds | Strong: mass / energy / head-loss residuals | Stronger for sparse network state estimation. |
| Explainability | High | High-medium; physics residuals are explainable | Medium; needs careful UI explanations. |
| Direct control readiness | Highest, with safety gates | Useful as validator before control | Shadow first; do not use for direct control initially. |

## 4. Can dPHM be used independently?

Yes. Kevin's statement is directionally correct: **dPHM is useful without dPHM-PINN**.

dPHM is the differentiable physics core. It does not need the neural network to provide value. For current target sites, the most practical use is to improve MVP v1 in bounded, explainable ways.

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
Add dPHM as validator
  check candidate schedules for pressure / flow / energy feasibility
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

| Stage | Product framing | Technical layer | Customer-facing outcome |
|---|---|---|---|
| MVP v1 | Station optimization | Regression + demand defaults + MPC | Better pressure/flow/volume delivery with higher pump efficiency. |
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

## 11. How to maintain this document

- Keep this as the 5-10 minute PO orientation.
- Add new product Q&A here as decisions emerge.
- Move formulas, API contracts, and detailed sprint reports to engineering docs and link them instead of expanding this document indefinitely.
- Prefer diagrams, tables, and site archetypes over long prose.
- Mark uncertain field assumptions explicitly until verified with site data or utility operators.
