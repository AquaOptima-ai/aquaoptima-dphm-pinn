"""Conformance tests for the A+B advisory artifact contract stubs.

Asserts that a trained Health (Pillar A) or Efficiency (Pillar B) artifact, wrapped via the
stub builders, actually conforms to the real contracts SDK:

* canonical all-True SafetyFlagSet (7 tokens),
* mandatory checksum present,
* framework is one the AMAX edge profile advertises (onnx),
* ordered axis/label schema embedded and deterministic,
* a DeploymentPackageManifest containing the record passes
  validate_deployment_package_for_edge against the default AMAX edge declaration,
* an accelerator-tainted summary is rejected before it can poison the package.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from aquaoptima_contracts import (
    ArtifactManifest,
    ArtifactReference,
    CapabilityRequirement,
    Checksum,
    ContractEnvelope,
    ContractError,
    DeploymentPackageManifest,
    PackageSafetyDeclaration,
    Provenance,
    SDK_VERSION,
    SchemaVersion,
    amax_5580_cpu_profile,
    default_amax_edge_capability_declaration,
    validate_deployment_package_for_edge,
)
from aquaoptima_contracts.safety.flags import default_safety_flag_set

from aquaoptima.advisory import ARTIFACT_SCHEMA_VERSION
from aquaoptima.advisory.label_schema import (
    MASKED_AXIS,
    active_axes_ordered,
    assert_summary_accelerator_clean,
    telemetry_axis_schema,
)
from aquaoptima.advisory.health_artifact_schema import (
    HEALTH_BASELINES,
    build_health_artifact_record,
)
from aquaoptima.advisory.efficiency_artifact_schema import (
    EFFICIENCY_BASELINES,
    build_efficiency_artifact_record,
)

EXPECTED_AXES = [
    "edge_flow",
    "edge_power",
    "edge_pump_speed",
    "edge_status",
    "node_demand",
    "node_level",
    "node_pressure",
    "node_status",
]


def _real_checksum() -> tuple[str, int]:
    payload = b"fake-onnx-artifact-bytes-for-contract-stub-test"
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _health_record():
    hexd, size = _real_checksum()
    return build_health_artifact_record(
        model_id="yilan-health-v1",
        model_version="1.0.0",
        checksum_hex=hexd,
        checksum_size_bytes=size,
        parameter_count=4096,
        build_id="build-test",
    )


def _efficiency_record():
    hexd, size = _real_checksum()
    return build_efficiency_artifact_record(
        model_id="yilan-efficiency-v1",
        model_version="1.0.0",
        checksum_hex=hexd,
        checksum_size_bytes=size,
        parameter_count=2048,
        build_id="build-test",
    )


# --- axis / label schema ---------------------------------------------------

def test_active_axes_ordered_is_canonical_and_excludes_masked():
    axes = active_axes_ordered()
    assert axes == EXPECTED_AXES
    assert MASKED_AXIS not in axes


def test_telemetry_axis_schema_is_index_aligned():
    schema = telemetry_axis_schema()
    assert schema["axis_order"] == EXPECTED_AXES
    for i, entry in enumerate(schema["axes"]):
        assert entry["index"] == i
        assert entry["name"] == EXPECTED_AXES[i]
        assert entry["kind"] in {"continuous", "binary"}
        assert entry["unit"]
    masked = schema["masked"]
    assert masked[0]["name"] == MASKED_AXIS
    assert masked[0]["scored"] is False


# --- safety flags ----------------------------------------------------------

@pytest.mark.parametrize("record_factory", [_health_record, _efficiency_record])
def test_record_has_canonical_all_true_safety_flags(record_factory):
    rec = record_factory()
    flags = rec.safety_flag_set.to_dict()
    assert flags == {
        "offline": True,
        "read_only": True,
        "no_write": True,
        "no_control": True,
        "no_live_ot_binding": True,
        "no_setpoint_output": True,
        "packaging_audit_only": True,
    }
    # The SDK itself rejects a non-all-True set, so the default helper is the contract.
    assert rec.safety_flag_set == default_safety_flag_set()


# --- checksum + framework --------------------------------------------------

@pytest.mark.parametrize("record_factory", [_health_record, _efficiency_record])
def test_record_requires_checksum_and_edge_framework(record_factory):
    rec = record_factory()
    assert rec.artifact_reference.checksum is not None
    assert rec.artifact_reference.checksum.algorithm == "sha256"
    assert len(rec.artifact_reference.checksum.hex_digest) == 64
    assert rec.framework == "onnx"
    # onnx must be advertised by the AMAX CPU profile.
    assert "onnx" in amax_5580_cpu_profile().supported_model_frameworks


def test_framework_outside_allowed_set_is_rejected_by_sdk():
    from aquaoptima_contracts import ModelArtifactRecord

    hexd, size = _real_checksum()
    with pytest.raises(ContractError):
        ModelArtifactRecord(
            model_id="x", model_version="1.0.0", framework="not_a_framework",
            artifact_reference=ArtifactReference(
                kind="model_weights", id="x", version="1.0.0",
                checksum=Checksum(algorithm="sha256", hex_digest=hexd, size_bytes=size)),
            provenance=Provenance(component="ai_server", version="0.1.0", build_id="b"),
            safety_flag_set=default_safety_flag_set(),
            capability_requirement=CapabilityRequirement(
                package_id="model-x", required=frozenset({"validate_manifest"}),
                sdk_version=SDK_VERSION),
        )


# --- summary content -------------------------------------------------------

def test_health_summary_declares_baselines_and_metrics():
    rec = _health_record()
    assert rec.summary["pillar"] == "A_health"
    assert rec.summary["baselines_to_beat"] == list(HEALTH_BASELINES)
    assert rec.summary["advisory_only"] is True
    assert rec.summary["actuates"] is False
    assert rec.summary["artifact_schema_version"] == ARTIFACT_SCHEMA_VERSION
    # structured output schema round-trips from its JSON-string embedding
    out = json.loads(rec.summary["output_schema_json"])
    assert out["pillar"] == "A_health"
    assert out["baselines_to_beat"] == list(HEALTH_BASELINES)
    # axis order embedded both as a flat list and inside the JSON schema
    assert rec.summary["axis_order"] == EXPECTED_AXES
    axis_schema = json.loads(rec.summary["telemetry_axis_schema_json"])
    assert axis_schema["axis_order"] == EXPECTED_AXES


def test_efficiency_summary_is_explicitly_non_actuating():
    rec = _efficiency_record()
    assert rec.summary["pillar"] == "B_efficiency"
    assert rec.summary["actuates"] is False
    assert rec.summary["baselines_to_beat"] == list(EFFICIENCY_BASELINES)
    out = json.loads(rec.summary["output_schema_json"])
    assert out["pillar"] == "B_efficiency"
    assert out["actuates"] is False
    # the advisory operating-point output must self-declare it does not actuate
    op = next(o for o in out["outputs"] if o["name"] == "advisory_operating_point")
    assert op["actuates"] is False


def test_accelerator_tainted_summary_is_rejected():
    with pytest.raises(ValueError):
        assert_summary_accelerator_clean({"architecture": "arm64-jetson"})
    with pytest.raises(ValueError):
        assert_summary_accelerator_clean({"notes": {"deep": ["uses CUDA kernels"]}})


# --- end-to-end: package passes the AMAX edge validator ---------------------

def _envelope() -> ContractEnvelope:
    return ContractEnvelope(
        schema_family="manifest",
        schema_name="deployment_package_manifest",
        schema_version=SchemaVersion.parse("1.0.0"),
        sdk_version=SDK_VERSION,
        created_at="2026-05-29T00:00:00Z",
        created_by_component="ai_server",
    )


def _capability_requirement(package_id: str) -> CapabilityRequirement:
    return CapabilityRequirement(
        package_id=package_id,
        required=frozenset({
            "load_signed_or_hashed_package",
            "validate_manifest",
            "validate_checksums",
            "validate_schema_versions",
            "validate_safety_flags",
        }),
        sdk_version=SDK_VERSION,
    )


@pytest.mark.parametrize("record_factory", [_health_record, _efficiency_record])
def test_artifact_packages_pass_amax_edge_validator(record_factory):
    rec = record_factory()
    package_id = "pkg-aopso-advisory"
    manifest = DeploymentPackageManifest(
        envelope=_envelope(),
        package_id=package_id,
        package_version="1.0.0",
        safety_declaration=PackageSafetyDeclaration(
            package_id=package_id,
            package_version="1.0.0",
            safety_flag_set=default_safety_flag_set(),
            capability_requirement=_capability_requirement(package_id),
            acknowledged_at="2026-05-29T00:00:00Z",
            notes="offline advisory package (no live OT binding)",
        ),
        capability_requirement=_capability_requirement(package_id),
        provenance=Provenance(component="ai_server", version="0.1.0", build_id="b"),
        model_artifacts=(rec,),
        notes="aopso A+B advisory package",
    )
    edge = default_amax_edge_capability_declaration()
    result = validate_deployment_package_for_edge(manifest, edge)
    assert result.accepted, f"edge validation failed: {result.errors}"
    assert result.rejected_frameworks == ()
    assert result.rejected_accelerator_tokens == ()
