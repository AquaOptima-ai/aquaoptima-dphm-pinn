# Shadow Replay Validation

## Purpose

Validate offline telemetry replay before live monitoring or advisory workflows.

## Current sources

- `TelemetryTagMap`.
- `ShadowReplayDataset`.
- CSV/offline row loaders.

## Validation goals

- Deterministic frame ordering.
- Correct canonical unit conversion.
- Missing/invalid/stale sample diagnostics.
- Read-only/no-live-binding safety boundary.
