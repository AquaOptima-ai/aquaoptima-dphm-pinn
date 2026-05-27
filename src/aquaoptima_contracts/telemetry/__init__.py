"""Telemetry contract projections (Sprint 42).

The Sprint 42 SDK telemetry module owns *shape* and deterministic
JSON for:

* :class:`TelemetryAxis` — canonical axis token vocabulary.
* :class:`UnitSpec` — name + canonical dimension.
* :class:`TelemetryTagSpec` — single tag entry.
* :class:`TelemetryTagMap` — tuple of tag specs plus diagnostics.
* :class:`TelemetryTagMapDiagnostics` — warnings / errors tuples.
* :class:`ShadowReplayFrame`, :class:`ShadowReplayDataset`,
  :class:`ShadowReplayDiagnostics` — shadow replay value projections.

The SDK never absorbs the Phase 1 ``aquaoptima.dphm.telemetry_tag_map``
network-dimension validator or unit-conversion tables. Those live in
the runtime module and continue to be the authority for runtime
behavior. The projection helpers in :mod:`.adapters` translate the
Phase 1 fixture JSON into the SDK shapes for downstream consumers
(Edge Runtime, AI Server, Operations Console).
"""
