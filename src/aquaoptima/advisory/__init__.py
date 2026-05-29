"""AquaOptima offline advisory product (A+B pivot).

This package holds the *contract stubs* and shared label/axis schema for the two
pillars introduced after the Sprint 26 forecasting FAIL (0/8 vs persistence):

* Pillar A -- anomaly / health detection  (:mod:`aquaoptima.advisory.health_artifact_schema`)
* Pillar B -- efficiency advisory / dPL   (:mod:`aquaoptima.advisory.efficiency_artifact_schema`)

Nothing in this package trains, loads, writes, actuates, or emits a setpoint. It only
describes *what a conformant artifact must look like* so that:

1. a trained artifact can be wrapped in a contracts-SDK ``ModelArtifactRecord`` whose
   ``safety_flag_set`` is the canonical all-True set and whose ``framework`` is one the
   AMAX edge profile advertises (``onnx``); and
2. the offline evaluation harness knows the exact ordered axis vector / label schema to
   score against.

Hard boundary (asserted by the conformance tests): offline-only, read-only, no-write,
no-control, no-live-OT-binding, no-setpoint-output, packaging-audit-only.
"""

from __future__ import annotations

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
]

# Bump when the label/axis schema or summary contract changes in a breaking way.
ARTIFACT_SCHEMA_VERSION = "1.0.0"
