# Glossary

Domain and project vocabulary for AquaOptima dPHM-PINN. When two people mean
different things by the same word, subtle bugs follow — keep this current.

## Domain & modelling

- **dPHM** — Differentiable Pressurised Hydraulic Model. The differentiable
  physics core for pressurised clean-water pipe networks (Hazen-Williams, pump
  affinity, incidence, residuals, Newton solver).
- **PINN** — Physics-Informed Neural Network. A model whose training loss
  includes a physics-residual term alongside supervised loss.
- **dPL** — differentiable Pump/Performance Learning; the efficiency-advisory
  modelling under Pillar B.
- **MPC** — Model Predictive Control.
- **MG-PID** — Multi-Gain PID control (context for the OT/IT decoupling work).
- **Hazen-Williams** — empirical head-loss equation for pressurised flow.
- **EPANET / `.inp`** — standard water-distribution modelling format; see
  `docs/examples/` for reference networks.

## Product

- **Pillar A** — health / anomaly detection. **Validated** and shipping (advisory).
- **Pillar B** — efficiency advisory (dPL). **Parked** — Sprint 33 found no
  meaningful energy opportunity at the locked March benchmark site.
- **Advisory** — output intended for human/operator consideration, **never** a
  control command. See [ADR-0001](docs/adr/0001-ot-it-decoupling.md).
- **Dry-run** — execution that produces evidence/output without acting on the
  process.
- **Evidence** — generated artifacts (scorecards, manifests) that justify an
  advisory or a deployment decision.
- **Yilan / March benchmark** — the locked offline benchmark dataset.

## Hardware & OT/IT

- **OT** — Operational Technology: the control system (PAC, HMI, field I/O).
- **IT** — Information Technology: AquaOptima's inference/analytics stack.
- **PAC** — Programmable Automation Controller. The AMAX/CODESYS control box.
- **CODESYS** — IEC 61131-3 control runtime/IDE. The "CODESYS Ready PAC" SKU runs
  Win10 LTSC + CODESYS V3 Pure Control + Visu/HMI.
- **AMAX-8580** — the canonical target edge hardware (CPU-only profile
  `amax8580_cpu`). Supersedes the earlier AMAX-5580 — see
  [ADR-0002](docs/adr/0002-amax8580-cpu-only-edge.md) /
  [ADR-0005](docs/adr/0005-amax-5580-to-8580-reconciliation.md).
- **`amax8580_cpu`** — the edge deployment profile id: CPU-only ONNX/TFLite;
  rejects pytorch/cuda/tensorrt/arm64.
- **EtherCAT** — real-time fieldbus the PAC uses for field I/O.
- **NVRAM** — non-volatile RAM on the PAC (2 MB on the CODESYS Ready PAC).

## Process & tooling

- **ADR** — Architecture Decision Record. See [`docs/adr/`](docs/adr/README.md).
- **Plane** — the project-management ledger (live sprint/issue state).
- **AOPSO** — AquaOptima project/issue prefix (e.g. AOPSO #44).
- **TDD** — Test-Driven Development; this repo is built sprint-by-sprint under it.
- **ONNX / TFLite** — CPU inference runtimes used at the edge.
