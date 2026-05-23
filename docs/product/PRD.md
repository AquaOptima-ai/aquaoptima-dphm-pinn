# AquaOptima dPHM-PINN Product Requirements Document

## Purpose

AquaOptima dPHM-PINN is a physics-informed hydraulic modelling and optimization platform for water and pumping systems. The product combines a differentiable physical hydraulic model (dPHM), a physics-informed neural model (dPHM-PINN), EPANET/WNTR import visibility, offline telemetry replay, and eventually advisory/supervised-control workflows.

## Product principle

The product advances through safety-gated phases:

1. read-only modelling and import diagnostics;
2. shadow-mode replay and evaluation;
3. advisory / supervised control with explicit approval and rollback;
4. qualified PAC-like edge runtime with industrial safety evidence.

No phase may bypass the safety boundary of the previous phase.

## Users

- Water utility engineers and operators.
- Pumping-station operations teams.
- Hydraulic modelling specialists.
- Energy optimization engineers.
- OT / controls engineers.
- Product and safety reviewers.

## Core jobs to be done

- Import and inspect network topology from EPANET/WNTR sources.
- Make unsupported or approximated semantics visible before modelling decisions.
- Map site telemetry tags to canonical dPHM node/edge quantities.
- Replay historical telemetry offline to evaluate model fit and safety.
- Quantify calibration residuals and shadow-mode performance.
- Produce operator-reviewable advisory outputs only after safety contracts exist.
- Provide evidence for future supervised control and PAC-like edge qualification.

## In scope for current shadow-mode MVP

- EPANET import diagnostics and import-quality reporting.
- Read-only telemetry tag-map schema.
- Offline shadow replay dataset builder.
- dPL calibration-loss prototype.
- Advisory safety contract.
- Shadow runtime harness.
- Export/deployment packaging for read-only operation.

## Out of scope until later phases

- Live PLC/PAC/SCADA write path.
- Autonomous control.
- Production savings claims.
- Qualified PAC certification claims.
- Field deployment without operator approval, rollback, audit logs, and OT cybersecurity review.

## Success metrics

- Import-quality reports clearly identify unsupported sections and edge surrogates.
- Shadow replay accepts offline telemetry and produces deterministic diagnostics.
- Calibration loss reports are reproducible and tied to canonical axes.
- Safety contract rejects unsafe recommendations deterministically.
- Every sprint is traceable from Plane issue to Git branch/commit/PR and repo docs.
