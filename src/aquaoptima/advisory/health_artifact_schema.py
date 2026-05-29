"""Pillar A -- Health / Anomaly detection artifact contract stub.

Describes what a *trained* health-detection artifact must look like to "plug in":

* wrapped in a contracts-SDK :class:`ModelArtifactRecord` with the canonical all-True
  :class:`SafetyFlagSet`, a real checksum, and ``framework="onnx"`` (the AMAX edge
  profile advertises onnx; a CPU-only export keeps the validator green);
* carrying, in its free-form ``summary``, the ordered telemetry axis schema (shared) plus
  the Pillar-A output schema: a scalar health score, per-axis contribution vector, and an
  anomaly flag with the baselines it must beat declared explicitly.

NOTE: this module builds the *record* (audit metadata). It never loads or runs a model.
The acceptance verdict (does the detector beat SPC / persistence on injected faults?) is
produced by the offline evaluation harness, NOT here.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from aquaoptima_contracts import (
    ArtifactReference,
    CapabilityRequirement,
    Checksum,
    ModelArtifactRecord,
    Provenance,
    SDK_VERSION,
)
from aquaoptima_contracts.safety.flags import default_safety_flag_set

from . import ARTIFACT_SCHEMA_VERSION
from .label_schema import (
    active_axes_ordered,
    assert_summary_accelerator_clean,
    telemetry_axis_schema_json,
)

PILLAR = "A_health"
EDGE_FRAMEWORK = "onnx"  # MUST be in the AMAX edge profile's supported_model_frameworks

# Baselines a health detector must beat to earn a PASS (declared in the artifact so the
# eval harness and any reviewer see the bar up front). Persistence has no concept of
# "normal", so the real bar is statistical process control.
HEALTH_BASELINES = ("persistence_last_value", "spc_ewma_3sigma")

# Metrics the offline harness computes against injected synthetic faults on the locked
# March 2026 holdout (no true anomaly labels exist, so faults are injected).
HEALTH_METRICS = (
    "injected_fault_auroc",
    "detection_lead_time_steps",
    "false_alarm_rate_per_day",
    "reconstruction_error_p99",
)


def health_output_schema() -> dict[str, Any]:
    """Pillar-A output contract embedded in ModelArtifactRecord.summary."""
    return {
        "pillar": PILLAR,
        "outputs": [
            {"name": "health_score", "kind": "continuous", "range": "0_1", "higher_is": "healthier"},
            {"name": "anomaly_flag", "kind": "binary", "decode": "threshold_on_health_score"},
            {
                "name": "axis_contribution",
                "kind": "vector",
                "axis_order": active_axes_ordered(),
                "meaning": "per_axis_reconstruction_or_residual_contribution_to_anomaly",
            },
        ],
        "baselines_to_beat": list(HEALTH_BASELINES),
        "evaluation_metrics": list(HEALTH_METRICS),
        "label_regime": "no_true_labels_inject_synthetic_faults_on_holdout",
        "advisory_only": True,
    }


def build_health_summary(
    *,
    architecture: str = "x86_64",
    parameter_count: int = 0,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the ``summary`` mapping for a health ModelArtifactRecord.

    The contracts SDK only allows scalar / flat-list-of-scalar summary values (no nested
    dicts) and scans every string for forbidden vocabulary. So structured payloads are
    embedded as JSON *strings* and flat scalar keys carry the headline facts.

    ``architecture`` defaults to ``"x86_64"`` to match the AMAX CPU profile; passing an
    accelerator-tainted value raises before the SDK ever sees it.
    """
    summary: dict[str, Any] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "pillar": PILLAR,
        "architecture": architecture,
        "parameter_count": int(parameter_count),
        "advisory_only": True,
        "actuates": False,
        "baselines_to_beat": list(HEALTH_BASELINES),
        "evaluation_metrics": list(HEALTH_METRICS),
        "axis_order": active_axes_ordered(),
        "telemetry_axis_schema_json": telemetry_axis_schema_json(),
        "output_schema_json": json.dumps(
            health_output_schema(), sort_keys=True, separators=(",", ":")
        ),
    }
    if extra:
        summary.update(dict(extra))
    assert_summary_accelerator_clean(summary)
    return summary


def build_health_artifact_record(
    *,
    model_id: str,
    model_version: str,
    checksum_hex: str,
    checksum_size_bytes: int,
    checksum_algorithm: str = "sha256",
    producer_component: str = "ai_server",
    producer_version: str = "0.1.0",
    build_id: str = "unset",
    artifact_uri_id: str | None = None,
    parameter_count: int = 0,
    architecture: str = "x86_64",
    summary_extra: Mapping[str, Any] | None = None,
) -> ModelArtifactRecord:
    """Build a conformant Pillar-A :class:`ModelArtifactRecord`.

    Raises ``ContractError`` (from the SDK) if any field violates the contract -- e.g. a
    framework outside the allowed set, a missing checksum, or a non-all-True safety set.
    """
    return ModelArtifactRecord(
        model_id=model_id,
        model_version=model_version,
        framework=EDGE_FRAMEWORK,
        artifact_reference=ArtifactReference(
            kind="model_weights",
            id=artifact_uri_id or model_id,
            version=model_version,
            checksum=Checksum(
                algorithm=checksum_algorithm,
                hex_digest=checksum_hex,
                size_bytes=int(checksum_size_bytes),
            ),
        ),
        provenance=Provenance(
            component=producer_component,
            version=producer_version,
            build_id=build_id,
        ),
        safety_flag_set=default_safety_flag_set(),
        capability_requirement=CapabilityRequirement(
            package_id=f"model-{model_id}",
            required=frozenset({"validate_manifest", "validate_checksums", "validate_safety_flags"}),
            sdk_version=SDK_VERSION,
        ),
        description="offline health/anomaly detector (Pillar A, advisory reference)",
        summary=build_health_summary(
            architecture=architecture,
            parameter_count=parameter_count,
            extra=summary_extra,
        ),
    )


__all__ = [
    "PILLAR",
    "EDGE_FRAMEWORK",
    "HEALTH_BASELINES",
    "HEALTH_METRICS",
    "health_output_schema",
    "build_health_summary",
    "build_health_artifact_record",
]
