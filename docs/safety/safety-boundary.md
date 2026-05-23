# Safety Boundary

## Current boundary

The current dPHM-PINN implementation is read-only. It may parse, diagnose, model, replay, calibrate, and report. It must not write to PLC/PAC/SCADA or change pump/valve/setpoint state.

## Prohibited until later phases

- Pump speed writes.
- Valve open/close writes.
- Pressure setpoint writes.
- Alarm acknowledgement.
- Control-mode changes.
- Bypassing operator or local interlocks.

## Required before supervised writes

- Safety contract.
- Validation matrix.
- Operator approval workflow.
- Rollback plan.
- Audit logs.
- OT cybersecurity review.
- Site acceptance test.
