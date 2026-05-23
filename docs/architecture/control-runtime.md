# Control Runtime Architecture

## Current boundary

No control runtime is active in the shadow-mode MVP. The current system is read-only and offline/read-only telemetry oriented.

## Future runtime components

- Telemetry reader.
- State estimator.
- Advisory engine.
- Safety guard.
- Control writer.
- Watchdog.
- Logger/audit trail.
- Rollback manager.
- Health monitor.

Every write-capable component requires safety, approval, rollback, and OT cybersecurity gates.
