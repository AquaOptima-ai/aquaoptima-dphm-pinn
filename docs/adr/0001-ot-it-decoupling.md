# ADR-0001: OT/IT decoupling — AquaOptima is an advisory sidecar

- **Status:** Accepted
- **Date:** 2026-05-31
- **Owner:** Tech lead

## Context

AquaOptima is deployed alongside a legacy pump-station site whose control is
owned by a vendor PAC stack (AMAX / CODESYS). The control layer owns the
process: PAC/control logic, HMI/Visu, and EtherCAT field I/O. AquaOptima
provides physics-informed health and (eventually) efficiency intelligence.

The blast radius of an unsafe write to a live PLC controlling a drinking-water
distribution network is a **real-world health and safety incident**, not a
software bug (see [`safety-boundary.md`](../safety-boundary.md)). Operational
Technology (OT — the control system) and Information Technology (IT — our
inference/analytics stack) have fundamentally different risk profiles,
certification regimes, and change cadences. Coupling them tightly would put our
fast-moving ML code inside a safety-critical control loop.

## Decision

**We will run AquaOptima as an IT-side advisory sidecar that is decoupled from
the OT control loop.**

- **OT side (AMAX / CODESYS) owns:** PAC/control logic, HMI/Visu, and EtherCAT
  field I/O. This is the system of record for control.
- **IT side (AquaOptima) provides:** inference, advisory ranking, evidence
  generation, and dry-run only.
- AquaOptima **does not write to control.** No code path connects advisory
  output to a controller write. Any future write capability requires explicit
  **safety qualification** and is gated behind named safety gates
  (see [`safety/capability-model-and-safety-gates.md`](../safety/capability-model-and-safety-gates.md)).
- `TagDefinition.writable` defaults to `False`; write is per-tag opt-in only.

## Consequences

- **Easier:** AquaOptima can iterate at IT speed without endangering the process.
  The boundary is auditable and the failure mode is "no advice," never "bad write."
- **Harder:** Acting on advice requires a human or a separately qualified path.
  Closed-loop optimisation is explicitly deferred behind safety qualification.
- Crossing this boundary accidentally is the **highest-severity mistake** in the
  product. Every developer must internalise it before touching the read or
  (future) write path.

## Alternatives considered

- **Closed-loop control now:** rejected — unacceptable safety risk without
  qualification, and outside our certification scope for the legacy site.
- **Embedding inference inside the PAC:** rejected — couples ML change cadence
  to safety-critical control software and the vendor's release process.
