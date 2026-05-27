"""Deployment manifest contract projections (Sprint 42).

The Sprint 42 SDK manifest module owns *shape* and deterministic
JSON for:

* :class:`ShadowDeploymentArtifact` — per-artifact metadata.
* :class:`ShadowDeploymentManifest` — top-level shadow-mode
  packaging manifest projection.
* :class:`ShadowDeploymentPackageDiagnostics` — warnings / errors
  tuples.

The Phase 1 module ``aquaoptima.dphm.shadow_deployment`` continues to
own the full Sprint 39 builder and JSON writer. The SDK projection
here mirrors the public artifact / manifest shape so any deployable
can read a packaged manifest without depending on the Phase 1
runtime. The SDK never writes a setpoint / command / write field;
the manifest is packaging / audit-evidence only.
"""
