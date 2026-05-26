# MVP v1 `water-pump-opt` baseline integration note

This note records how the existing real-site MVP v1 codebase should be treated by the dPHM-PINN roadmap.

- Source repo: `https://github.com/aquaoptima/water-pump-opt`
- Local review path: `/home/hunter_lin/work/repos/water-pump-opt`
- Reviewed baseline: `main` at `0210c22`
- Quick verification reported for the baseline: `python3 -m compileall -q pump_control/pump_control_v1_1 flow_prediction`

## Executive framing

`water-pump-opt` is the current field-proven Water Pump Optimization MVP v1. It combines Python services, ThingsBoard rule chains, Modbus/MQTT telemetry, pump-curve prediction, and a deterministic pump-control API for multi-pump water systems.

It should be preserved as the **legacy controller / MVP baseline**, not replaced immediately by dPHM-PINN.

dPHM-PINN should initially wrap and observe it:

```text
MVP v1 water-pump-opt
= deterministic/heuristic controller + ThingsBoard integration + field I/O patterns

dPHM-PINN
= sidecar/supervisory validation, digital twin, health-aware optimization,
  shadow-mode inference, evidence logging, and safer bounded proposals
```

## What MVP v1 currently does

The production loop is:

```text
PLC/PAC sensors
→ Python Modbus/MQTT bridge
→ ThingsBoard telemetry/rule engine
→ Flow Prediction API :5000
→ Pump Control API :5001
→ ThingsBoard rule engine writes approved setpoints back to PLC/PAC/VFD
```

Important implementation areas in `water-pump-opt`:

| Area | Role |
|---|---|
| `pump_control/pump_control_v1_1/main_api.py` | Flask Pump Control API, `POST /api/pump-control`, port `5001` |
| `pump_control/pump_control_v1_1/pump_controller.py` | Main deterministic controller state machine |
| `pump_control/pump_control_v1_1/config.py` | Site/pump constants, frequency bounds, tolerances, optimization table |
| `flow_prediction/pump.py` | Classical pump-curve fitting and prediction |
| `flow_prediction/pump_combination_optimizer.py` | Algorithmic pump-combination optimizer seed |
| `autorun/thingsboard-MODBUS-MQTT-Bridge.py` | Production-style Modbus/MQTT telemetry bridge |
| `docs/DEPLOYMENT_GUIDE.md` | Strongest deployment/architecture reference |

## Controller reality: not classical PID

The MVP v1 controller should not be described as a classical PID implementation. A code search for explicit PID concepts did not reveal a proportional/integral/derivative loop.

A more accurate description is:

> MVP v1 is not a classical PID controller. It is a deterministic multi-goal control policy with ramping, hysteresis/confirmation windows, table-driven pump-combination selection, safety/data-quality gates, and efficiency-aware frequency adjustments.

Main control behavior:

1. Demand/head/flow target handling.
2. Manual-mode and missing/extreme-data gates.
3. Table-driven pump-combination selection through `PUMP_OPTIMIZATION_TABLE`.
4. Ramp mode for demand transitions or manual-to-auto transitions.
5. Normal-mode rolling head/flow checks and one-pump frequency adjustments.
6. Efficiency tuning after demand stability.
7. Compromise/fail flags when repeated efficiency adjustments cannot meet goals.

This is useful to dPHM-PINN because it gives a clear legacy behavior to emulate, compare against, and safety-wrap without pretending a formal PID loop exists.

## What dPHM-PINN should not duplicate

dPHM-PINN should not immediately rebuild or replace these MVP v1 responsibilities:

- direct Modbus/MQTT field bridging;
- ThingsBoard device/rule-chain integration;
- live PLC/PAC/VFD write-back paths;
- pump switching as direct control authority;
- static site-specific register/token/device configuration;
- operator-facing ThingsBoard monitoring already used at the site.

For the current dPHM-PINN safety boundary, AquaOptima remains **read-only / shadow-mode / advisory evidence first**: no live OT binding, no PLC/PAC/SCADA write, no command emission, no setpoint output, and no control-loop closure.

## Where dPHM-PINN can add value

Near-term dPHM-PINN value should focus on sidecar evidence rather than direct actuation:

1. **Shadow-mode comparison** — run beside MVP v1, consume the same demand/sensor snapshots, and compare dPHM-PINN advisory outputs against the MVP controller outputs.
2. **Digital-twin residual evidence** — calculate dPHM/dPL consistency, pressure/flow residuals, and quality diagnostics for each operating window.
3. **Health-aware optimization evidence** — quantify whether alternative pump combinations/frequency proposals appear safer or more efficient, without emitting write commands.
4. **Safety violation detection** — flag deltas that violate bounds, missing evidence, stale data, or known unsafe transitions.
5. **Configuration and site-readiness checks** — expose hardcoded MVP assumptions as formal site profile/tag-map/readiness gaps.
6. **Replay dataset generation** — turn MVP telemetry and controller decisions into fixtures for offline shadow replay.
7. **Operator evidence reports** — summarize when dPHM-PINN agreed with MVP v1, disagreed, or lacked sufficient confidence.

## Shadow-mode adapter contract

The first bridge should be an adapter contract, not a controller replacement. It should normalize MVP v1 I/O into dPHM-PINN's existing contract/replay vocabulary.

Minimum input snapshot:

| Contract section | Example content |
|---|---|
| Demand input | target head, flow lower/upper bounds, schedule/demand identifier |
| Sensor snapshot | head, pressure, level, per-pump predicted/measured flow where available |
| Pump state | pump on/off state, frequency, alarm/switch flags, manual/auto mode |
| Site metadata | site id, pump ids, pump category, rated power, register/tag mapping version |
| Controller context | current MVP controller mode, demand-stability/ramp state, rolling-window state if available |

Minimum output/evidence snapshot:

| Contract section | Example content |
|---|---|
| MVP proposed setpoints | pump on/off changes, frequency changes, controller mode, flags/logs |
| dPHM-PINN advisory proposal | bounded advisory-only proposal, if any; no write command |
| Comparison result | agreement/disagreement, delta magnitude, safety-boundary classification |
| Residual/evidence metrics | dPHM/dPL residuals, confidence/readiness flags, estimated efficiency delta |
| Audit metadata | timestamp, source version, schema version, correlation id, replay frame id |

The adapter should be designed so the same contract can be populated from:

- live read-only telemetry later;
- exported ThingsBoard/CSV data;
- MVP v1 simulation JSONs;
- offline replay fixtures.

## Productization risks found in MVP v1

These are not criticisms of the MVP; they are exactly the constraints the dPHM-PINN wrapper should make explicit:

1. **Hardcoded site specifics** — pump names, device ids, tokens, IPs, register addresses, and pump tables appear embedded in code.
2. **Limited multi-site generality** — docs imply variable pump counts, but current controller code is strongly shaped around four pumps.
3. **Monolithic controller** — `pump_controller.py` combines validation, state, switching, ramping, normal adjustment, and efficiency logic in one large module.
4. **No main pytest suite** — simulation inputs exist, but not a formal regression suite around controller behavior.
5. **Security hygiene risk** — source may contain ThingsBoard tokens/default credentials/site details; future ingestion should treat the repo as sensitive.
6. **No formal PID layer** — product language should use "deterministic multi-goal policy" unless a real PID loop is added later.
7. **Optimizer split** — `flow_prediction/pump_combination_optimizer.py` looks more algorithmic than the live static table, but is not clearly integrated into production control.

## Recommended dPHM-PINN backlog items

Keep these as Backlog/Candidate items until execution-ready; do not assign speculative sprint numbers yet.

1. `CAP — MVP v1 baseline adapter contract`
   - Define stdlib-only contract shapes for demand/sensor/pump-state/MVP-output snapshots.
   - Architecture placement: Shared Contracts / SDK.
   - Forbidden: live OT binding, write commands, setpoint emission, ThingsBoard client implementation.

2. `SPIKE — MVP v1 replay fixture extraction`
   - Convert existing MVP v1 simulation JSON / exported telemetry into deterministic shadow replay fixtures.
   - Architecture placement: Server-side training / replay / fine-tuning + Shared Contracts.

3. `CAP — Legacy-controller comparison report`
   - Produce agreement/disagreement, safety-boundary, residual, and estimated efficiency-delta reports comparing MVP v1 and dPHM-PINN.
   - Architecture placement: Server-side replay/report generation; Console UI remains a separate product stream.

4. `SPIKE — MVP v1 secret/config hardening inventory`
   - Inventory hardcoded site-specific values and define how they should map into a future Site Readiness & Configuration Management product unit.

## Decision

Treat MVP v1 as the real-site baseline controller and integration pattern. dPHM-PINN should first become a read-only shadow-mode sidecar that observes the same inputs, compares against MVP v1 decisions, logs evidence, and prepares bounded advisory proposals only after explicit safety qualification.
