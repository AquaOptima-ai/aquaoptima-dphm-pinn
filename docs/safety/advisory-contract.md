# Advisory Safety Contract

## Purpose

The advisory safety contract defines what recommendations may be shown, rejected, or escalated before any control path exists.

## Candidate checks

- Minimum/maximum pressure.
- Flow bounds.
- Pump speed bounds.
- Rate-of-change bounds.
- Tank/level bounds where available.
- Confidence thresholds.
- Operator-defined no-go rules.

## Output

Every recommendation should include a pass/fail decision, reason, expected margin, and audit context.
