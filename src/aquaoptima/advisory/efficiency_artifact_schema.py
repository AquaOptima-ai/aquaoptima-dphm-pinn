"""Pillar B -- Efficiency Advisory / dPL artifact contract stub.

Describes what a *trained* efficiency-advisory artifact must look like to "plug in".
Same record/contract discipline as Pillar A, but the ``summary`` output schema describes
an efficient-setpoint envelope (specific energy, kWh/m3) keyed by operating point.

CRITICAL SAFETY NOTE: the "setpoint" here is an OFFLINE ADVISORY OPPORTUNITY, never a
command. The canonical SafetyFlagSet asserts ``no_setpoint_output`` and ``no_control`` --
the artifact emits an *analysis of historically realized efficient operating points*, not
a control target. The output field is deliberately named ``advisory_operating_point`` and
flagged ``actuates=False`` so no downstream consumer can mistake it for a command.
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

PILLAR = "B_efficiency"
EDGE_FRAMEWORK = "onnx"

# Operating-point conditioning axes: at a given demand / head / level, what pump speed
# minimizes specific energy? These are INPUTS to the envelope, not predicted outputs.
OPERATING_POINT_AXES = ("node_demand", "node_pressure", "node_level")

# Baselines a Pillar-B advisory must beat: the site's OWN historically realized operating
# points at matched conditions (and the MVPv1 control log). No actuation involved.
EFFICIENCY_BASELINES = ("site_historical_matched_condition", "mvpv1_control_log")

EFFICIENCY_METRICS = (
    "specific_energy_kwh_per_m3",
    "matched_condition_energy_reduction_pct",
    "coverage_of_valid_intervals_pct",
    "opportunity_realizability_flag",
)


def efficiency_output_schema() -> dict[str, Any]:
    """Pillar-B output contract embedded in ModelArtifactRecord.summary."""
    return {
        "pillar": PILLAR,
        "operating_point_axes": list(OPERATING_POINT_AXES),
        "outputs": [
            {
                "name": "advisory_operating_point",
                "kind": "vector",
                "fields": ["edge_pump_speed", "expected_specific_energy_kwh_per_m3"],
                "actuates": False,
                "meaning": "offline_efficient_envelope_point_at_matched_conditions",
            },
            {
                "name": "opportunity_estimate",
                "kind": "continuous",
                "unit": "kwh_per_m3",
                "meaning": "offline_specific_energy_gap_vs_realized_baseline",
            },
        ],
        "baselines_to_beat": list(EFFICIENCY_BASELINES),
        "evaluation_metrics": list(EFFICIENCY_METRICS),
        "claim_discipline": "report_offline_opportunity_only_never_guaranteed_savings",
        "advisory_only": True,
        "actuates": False,
    }


def build_efficiency_summary(
    *,
    architecture: str = "x86_64",
    parameter_count: int = 0,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "pillar": PILLAR,
        "architecture": architecture,
        "parameter_count": int(parameter_count),
        "advisory_only": True,
        "actuates": False,
        "operating_point_axes": list(OPERATING_POINT_AXES),
        "baselines_to_beat": list(EFFICIENCY_BASELINES),
        "evaluation_metrics": list(EFFICIENCY_METRICS),
        "axis_order": active_axes_ordered(),
        "telemetry_axis_schema_json": telemetry_axis_schema_json(),
        "output_schema_json": json.dumps(
            efficiency_output_schema(), sort_keys=True, separators=(",", ":")
        ),
    }
    if extra:
        summary.update(dict(extra))
    assert_summary_accelerator_clean(summary)
    return summary


def build_efficiency_artifact_record(
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
        description="offline efficiency advisory / dPL envelope (Pillar B, advisory reference)",
        summary=build_efficiency_summary(
            architecture=architecture,
            parameter_count=parameter_count,
            extra=summary_extra,
        ),
    )


__all__ = [
    "PILLAR",
    "EDGE_FRAMEWORK",
    "OPERATING_POINT_AXES",
    "EFFICIENCY_BASELINES",
    "EFFICIENCY_METRICS",
    "efficiency_output_schema",
    "build_efficiency_summary",
    "build_efficiency_artifact_record",
]
