"""Runtime report contract projections (Sprint 42).

The Sprint 42 SDK runtime module owns *shape* and deterministic JSON
for:

* :class:`ShadowRuntimeStepReport` — per-frame projection.
* :class:`ShadowRuntimeReport` — top-level report projection.
* :class:`ShadowRuntimeDiagnostics` — warnings / errors tuples.

The Phase 1 harness driver ``aquaoptima.dphm.shadow_runtime.run_shadow_runtime``
remains the authority for residual / advisory math. The SDK
projection here only models the read-only audit shape. No advisory
emission, no setpoint output, no control surface.
"""
