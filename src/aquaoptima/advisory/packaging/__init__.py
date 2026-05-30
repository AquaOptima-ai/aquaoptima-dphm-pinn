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
from .serve_advisory import (
    EVIDENCE_COLUMNS,
    AdvisoryServingResult,
    load_telemetry_frames,
    score_to_evidence,
)

# The Sprint-36 deployment manifest builder pulls in `aquaoptima.advisory`
# subpackages that themselves depend on torch (via `dataio.telemetry`).
# The runtime container intentionally does NOT carry torch -- it only
# scores ONNX through onnxruntime. To keep the runtime container's import
# graph torch-free, we expose the manifest builder via lazy attribute
# resolution: `from aquaoptima.advisory.packaging import
# build_pillarA_deployment_package_manifest` still works from a full
# editable install, but importing this package without torch installed
# does not eagerly fail.
_LAZY_EXPORTS: dict[str, str] = {
    "PILLARA_DEPLOYMENT_PACKAGE_ID": "deployment_manifest",
    "PILLARA_DEPLOYMENT_PACKAGE_VERSION": "deployment_manifest",
    "PILLARA_REQUIRED_CAPABILITIES": "deployment_manifest",
    "build_pillarA_deployment_package_manifest": "deployment_manifest",
    "write_pillarA_deployment_package_manifest": "deployment_manifest",
}


def __getattr__(name: str):  # pragma: no cover - simple lazy attr lookup
    if name in _LAZY_EXPORTS:
        from importlib import import_module

        module = import_module(f"{__name__}.{_LAZY_EXPORTS[name]}")
        attr = getattr(module, name)
        globals()[name] = attr
        return attr
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )


__all__ = [
    "DEFAULT_OPSET",
    "EVIDENCE_COLUMNS",
    "AdvisoryServingResult",
    "OnnxHealthDetectorSidecar",
    "OnnxScoringResult",
    "PILLARA_DEPLOYMENT_PACKAGE_ID",
    "PILLARA_DEPLOYMENT_PACKAGE_VERSION",
    "PILLARA_REQUIRED_CAPABILITIES",
    "build_health_detector_sidecar",
    "build_pillarA_deployment_package_manifest",
    "export_health_detector_to_onnx",
    "load_telemetry_frames",
    "score_to_evidence",
    "score_with_onnx",
    "write_pillarA_deployment_package_manifest",
]
