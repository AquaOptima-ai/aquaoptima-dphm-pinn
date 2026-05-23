# Telemetry Pipeline Architecture

## Current scope

Sprint 34 and 35 define offline telemetry schema and replay surfaces:

- `TelemetryTagMap` maps operator-facing tags to canonical dPHM axes.
- `ShadowReplayDataset` turns offline rows into replay frames.

## Future scope

Live adapters may include historian exports, CSV drops, MQTT mirrors, OPC-UA read-only endpoints, or REST APIs. These must remain read-only until the supervised-control phase.
