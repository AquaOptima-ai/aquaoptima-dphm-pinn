# Control Write Contract

## Purpose

Define future supervised write behavior before implementing any real write adapter.

## Requirements

- Whitelisted asset/setpoint only.
- Min/max and rate limits.
- Approval and lockout semantics.
- Read-after-write confirmation.
- Timeout and rollback conditions.
- Audit log entry for every proposed/committed/rolled-back write.

No real write path should be enabled before this contract is implemented and approved.
