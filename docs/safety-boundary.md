# Safety Boundary — Reading vs. Writing the Process

AquaOptima models drinking-water distribution networks. The blast
radius of an unsafe write to a live PLC is a real-world health and
safety incident, not a software bug. This file is the explicit policy
for *every* sprint that touches the read path or the (future) write
path.

## Current state (Sprint 4.5)

**No write path exists in this code base.** There is no PLC client, no
Modbus writer, no OPC-UA `WriteValue`, no MQTT publisher to a control
topic. Sprint 4.5 ships only:

- A *metadata* model (`SiteTagMap`, `TagDefinition`) that *describes*
  whether a tag could in principle be written.
- The synthetic telemetry generator (no real I/O of any kind).

`TagDefinition.writable` defaults to **`False`**. The default has to
be opt-in: a future bug in adapter code that accidentally widens the
writable set must not silently turn into actual writes.

## Rules that hold across all sprints

1. **Read-only first.** Every new source adapter ships in read-only
   mode. Write capability is a separate, named follow-up.
2. **`writable=True` is a per-tag opt-in.** Setting it at the site
   level wholesale is not a supported configuration. Each tag must be
   reviewed individually.
3. **No advisory output is wired to a writer.** `SetpointAdvisoryHead`
   currently outputs a per-node setpoint advisory. It is **not** a
   command. There is no code path from advisory tensors to controller
   writes today, and there must not be until Sprint 10 ships the
   safety-gated write path with explicit policy and tests.
4. **Network feasibility checks are advisory, not enforcement.**
   `FeasibilityResult` reports bound violations on model output. It
   does *not* prevent any downstream system from misusing those
   values. A future write path must run feasibility on the *command*
   before issuing it, and reject the command on any violation.
5. **Defence in depth.** Even when Sprint 10 lands, command issuance
   must require *three* independent allow signals:
   - `TagDefinition.writable=True` for the target tag.
   - A site-level policy switch that enables writes on this site.
   - A per-command feasibility check passing on the value being sent.

## Audit hooks the code is already ready for

- Every `SolveResult` carries a `SolveFailureReason`; any future write
  path can refuse to issue commands derived from a failed solve.
- Every `TagDefinition` is frozen — no in-place mutation can flip
  `writable` after construction. Re-construction is the only way to
  change permissions, and a future adapter can log every
  reconstruction event.
- `QualityFlag` includes `MANUAL_OVERRIDE` so AquaOptima will never
  treat an operator-forced value as a training signal *or* as a basis
  for issuing further commands.

## What is *not* in scope here

- Authentication, authorisation, audit logging of operator actions
  in the SCADA frontend itself. AquaOptima trusts the upstream
  control system's identity model.
- Network-level security (segmentation, firewalling). That is an
  infrastructure concern documented in the deployment guide once the
  first live adapter ships.

This file should be re-read and updated **every time** a new sprint
touches the source-adapter layer, the model output heads, or anything
in `training/`. If a sprint changes the policy, the change goes in
this file before the code lands.
