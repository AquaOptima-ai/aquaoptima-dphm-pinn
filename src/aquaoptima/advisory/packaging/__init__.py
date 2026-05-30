"""AOPSO Sprint 35 -- Pillar A offline packaging surface.

The packaging surface produces a PORTABLE INFERENCE ARTIFACT (an ONNX export of
the validated Pillar-A health detector + a JSON sidecar carrying the
standardisation and calibration constants needed to reproduce
:meth:`FittedHealthDetector.score`). It is OFFLINE artifact packaging only and
is **not** a deployment path:

* no setpoints, no actuation, no control language, no live OT binding;
* no write-capable connector imports (governance scan tested);
* the resulting :class:`ModelArtifactRecord` carries the canonical all-True
  :class:`SafetyFlagSet` so the contracts validator stays happy;
* ``framework`` is ``"onnx"`` (in the AMAX edge profile's supported set);
* March 2026 is a frozen holdout -- packaging fits / loads on 2025 data only.

The acceptance verdict (parity + manifest validation + governance scan) is
produced by the Sprint 35 pipeline, NOT here. This subpackage only holds the
pure exporter + scoring wrapper + sidecar shape.
"""

from __future__ import annotations

from .onnx_export import (
    DEFAULT_OPSET,
    OnnxHealthDetectorSidecar,
    OnnxScoringResult,
    build_health_detector_sidecar,
    export_health_detector_to_onnx,
    score_with_onnx,
)

__all__ = [
    "DEFAULT_OPSET",
    "OnnxHealthDetectorSidecar",
    "OnnxScoringResult",
    "build_health_detector_sidecar",
    "export_health_detector_to_onnx",
    "score_with_onnx",
]
