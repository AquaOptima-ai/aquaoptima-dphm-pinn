# Advisory / Supervised Control Product

## Purpose

The advisory/supervised-control phase turns shadow-mode evidence into operator-facing recommendations and, later, limited whitelisted writes under explicit approval and rollback conditions.

## Advisory mode

- Recommendations are generated and logged.
- Operators can accept/reject/comment.
- No automatic writes.

## Supervised write mode

- Only whitelisted setpoints may be written.
- Every candidate passes safety constraints.
- Operator/site approval is required.
- Rollback and audit logs are mandatory.
- Existing PLC/PAC/SCADA interlocks remain authoritative.

## Out of scope

- Unbounded optimization.
- Autonomous control.
- Bypassing local controls or operator authority.
