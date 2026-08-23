# Kevin Feedback on PO Orientation Brief

Related brief: [`docs/product/po-orientation-brief.md`](po-orientation-brief.md)

## Context

This note captures Kevin's feedback and clarifying questions on the PO orientation brief covering MVP v1, dPHM, and dPHM-PINN. The feedback generally agrees with the brief's observation that AquaOptima can be explained in multiple product/model layers, but asks for a few corrections in emphasis before the product framing is treated as final.

The main correction is that the discussion should not only be framed as **model-site fit**. It also needs to reflect **product packaging strategy**: AquaOptima can keep multiple model/control layers available inside the edge package, while enabling only the layer that is suitable for the customer, project scope, telemetry maturity, and commercial entitlement.

## Questions for the brief author / reviewer

### 1. Was dPL considered in the review?

The brief mentions dPHM and dPHM-PINN, but the review should explicitly account for the **dPL** role as well.

The product plan may use **MVP v1 and dPL together**. dPL can continuously improve the quality of pump-efficiency and pump-performance data in a dynamic way, which makes it useful even before the full dPHM-PINN network-intelligence layer is enabled.

Suggested clarification:

> MVP v1 is not isolated from dPL. MVP v1 can remain the first commercial/control layer while dPL continuously improves pump-efficiency evidence, calibration quality, and maintenance insight. dPL can therefore strengthen MVP v1 and dPHM readiness even when dPHM-PINN is not yet needed.

### 2. Was OT / IT decoupling considered?

The brief should more explicitly discuss **OT and IT decoupling**.

For AquaOptima, the edge side and the server/IT side should not be treated as one monolithic runtime. The product should preserve the distinction between:

- **OT / Edge side**
  - site-adjacent deployment;
  - integration with PLC/PAC/SCADA boundaries;
  - local safety/capability gates;
  - deterministic control-policy or advisory enforcement;
  - package validation;
  - no uncontrolled write path;
  - site PLC remaining final actuator authority.

- **IT / AI / Optimization side**
  - model training/retraining;
  - fleet analytics;
  - package generation;
  - optimization workloads;
  - dashboard and review workflows;
  - non-real-time model lifecycle tasks.

This decoupling matters commercially and technically. It allows the edge package to contain multiple possible model/control layers while enabling only what is approved and paid for at a given site. It also protects OT safety boundaries while still allowing IT-side intelligence to improve over time.

Suggested clarification:

> The three-layer product model should be described together with OT/IT decoupling: the edge can carry validated packages and local capability gates, while the IT/AI side can train, evaluate, and package models without directly becoming the live control authority.

### 3. Was the continued need for Multi-Goal PID considered?

The brief should make clear that **Multi-Goal PID remains necessary even when dPHM or dPHM-PINN is available**.

dPHM and dPHM-PINN can improve hydraulic understanding, feasibility checking, state estimation, forecasting, and network-aware optimization. But the product still needs a deterministic control-policy layer that resolves operational priorities in real time or near-real time.

Multi-Goal PID remains important because it provides:

- deterministic priority handling when pressure, flow, energy, pump wear, and safety goals conflict;
- explainable operator-facing behaviour;
- bounded ramping / switching decisions;
- exception handling and fallback structure;
- compatibility with existing PLC authority and operator override;
- a stable policy layer that can consume evidence from MVP v1, dPL, dPHM, or dPHM-PINN.

Suggested clarification:

> dPHM / dPHM-PINN do not replace Multi-Goal PID. They provide physics and learning evidence that can inform the policy layer. Multi-Goal PID remains the deterministic operating-policy layer that translates goals, constraints, and model evidence into auditable control/advisory behaviour.

## Feedback on the current product framing

### 1. General agreement with the three-layer categorisation

I generally agree with the observation and categorisation of the three layers:

1. **MVP v1** as the immediate commercial wedge and station-level optimization layer.
2. **dPHM** as the physics / calibration / trust layer.
3. **dPHM-PINN** as the network-intelligence scaling layer.

This is broadly aligned with how we planned the product. We understand that **PINN is only needed when WDN involvement or network-level state inference becomes relevant**. It should not be forced into every simple pump-station job on day one.

### 2. Product strategy is broader than model-site fit

One point the brief may understate: the issue is not only whether a model fits a site today. It is also about **product planning and packaging strategy**.

AquaOptima can keep multiple layers available in the edge software package:

- MVP v1 / Multi-Goal PID;
- dPL;
- dPHM;
- dPHM-PINN.

The product can then enable the suitable layer based on:

- project scope;
- telemetry maturity;
- topology availability;
- commercial entitlement;
- customer budget;
- safety approval;
- whether the client has paid for the advanced layer.

This means a site can start simple without closing the door to future expansion. We do not need to position the layers as mutually exclusive products. They can be packaged together and selectively enabled.

Suggested product framing:

> AquaOptima should be packaged as a layered edge product. The edge may contain MVP v1, dPL, dPHM, and dPHM-PINN capabilities, but the active capability is enabled according to site maturity, budget, safety approval, and client entitlement.

### 3. MVP v1 and dPL may be useful together

MVP v1 and dPL should not be seen as separate alternatives.

dPL can support MVP v1 by continuously improving the data quality around pump efficiency and pump behaviour. This matters because pump efficiency is not static in the field. It can drift with aging, maintenance condition, operating region, instrumentation quality, and changes in operating practice.

Therefore:

- MVP v1 can provide immediate station optimization and operator-facing control policy.
- dPL can provide continuous dynamic calibration of pump-efficiency evidence.
- dPHM can provide hydraulic plausibility and residual evidence.
- dPHM-PINN can become useful when network-level inference is needed.

Suggested clarification:

> MVP v1 + dPL is a meaningful package. dPL can continuously improve the pump-efficiency evidence that MVP v1 depends on, while dPHM/dPHM-PINN can be enabled when the site requires physics or network intelligence.

### 4. “Simple site” should not be interpreted as permanently isolated

For our target audience, a water supply site or WTP with pumps is rarely truly alone or disconnected. It is usually attached to a WDN, reservoir, dam, transmission main, pressure zone, or another pump station.

When we call a site “simple,” it often means the **initial project scope and budget** are simple, not that the hydraulic context is permanently simple.

A site may grow in complexity over time when:

- the client installs more WDN sensors;
- nearby pump stations begin coordinating;
- the customer obtains or cleans up EPANET data;
- budget becomes available for wider district optimization;
- operational collaboration expands from one station to a pressure zone or district;
- the initial WTP/pump-station project becomes the wedge for broader network management.

Therefore, starting with MVP v1 is totally fine and likely correct, but the product strategy should make clear that this is a **growth path**, not a hard boundary.

Suggested clarification:

> MVP v1 is the right starting point for many projects because it matches initial scope and budget. But many “simple” WTP/pump-station sites are connected to a wider WDN or district context. As telemetry, topology, EPANET data, and budget improve, it is natural for the product to grow toward dPHM and dPHM-PINN.

## Suggested revised product narrative

A concise revised framing could be:

> AquaOptima should be positioned as a layered pump and network optimization product. MVP v1 with Multi-Goal PID is the first commercial and operator-trust layer for station-level optimization. dPL can continuously improve pump-efficiency and pump-performance evidence. dPHM provides hydraulic physics validation, calibration, and diagnostics when trust or repeatability requires it. dPHM-PINN becomes valuable when the project expands into WDN-aware or district-level intelligence with sparse sensors, multiple stations, tanks, reservoirs, or EPANET/topology data. These layers can be packaged together at the edge and selectively enabled according to project scope, client entitlement, telemetry maturity, and safety approval. The OT edge remains decoupled from the IT/model lifecycle side, and the site PLC remains the final actuator authority.

## Proposed action items for the orientation brief

1. Add a short section explaining the role of **dPL** and how it can work with MVP v1.
2. Add an explicit **OT/IT decoupling** section.
3. Clarify that **Multi-Goal PID remains necessary** even when dPHM or dPHM-PINN is used.
4. Reframe “simple sites” as **simple initial scope**, not permanently disconnected hydraulic systems.
5. Add a product-packaging note: all layers may exist in the edge package, but are enabled by site fit, customer entitlement, safety gate, and budget.
6. Clarify that PINN is mainly needed when WDN/network-level intelligence is involved, but many WTP/pump-station projects can naturally grow toward that need over time.

## Bottom line

I generally agree with the brief's observations, but I would adjust the emphasis:

- The product is not only choosing one model per site; it is packaging a layered capability stack.
- MVP v1 remains the commercial wedge.
- dPL can strengthen MVP v1 through dynamic pump-efficiency evidence.
- dPHM improves physics trust and repeatability.
- dPHM-PINN supports the natural growth path toward WDN/district intelligence.
- Multi-Goal PID remains the deterministic control-policy layer.
- OT/IT decoupling and site PLC authority should be explicit in the product story.
