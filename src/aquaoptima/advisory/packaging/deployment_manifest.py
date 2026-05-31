"""AOPSO Sprint 36 -- ``DeploymentPackageManifest`` builder for the Pillar-A
Linux deployment package.

This module composes a contracts-SDK :class:`DeploymentPackageManifest`
that wraps the Sprint-35 ONNX :class:`ModelArtifactRecord`. The manifest:

* uses :class:`ContractEnvelope` with ``schema_family="manifest"``;
* sets the canonical all-True :class:`SafetyFlagSet` on the
  :class:`PackageSafetyDeclaration`;
* keeps ``package_id`` consistent across the manifest, its safety
  declaration, and its top-level capability requirement (the SDK rejects
  any mismatch);
* embeds the existing Sprint-35 :class:`ModelArtifactRecord` in the
  ``model_artifacts`` tuple verbatim;
* MUST pass :func:`validate_deployment_package_for_edge` against the
  canonical AMAX-8580 CPU profile -- the package is the input to the
  Edge package validator described in the contracts inventory.

Boundary -- non-negotiable
--------------------------
The manifest carries audit evidence only. No field describes a write,
dispatch, actuation, setpoint, or control surface. All free-form strings
(package_id, notes, descriptions, summary) avoid forbidden vocabulary so
the contracts SDK's ``contains_forbidden_token`` check stays clean.

The on-disk evidence lands at
``data/eval/packaging/pillarA_deployment_package_manifest.json``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aquaoptima_contracts import (
    ArtifactReference,
    CapabilityRequirement,
    Checksum,
    ContractEnvelope,
    DeploymentPackageManifest,
    ModelArtifactRecord,
    PackageSafetyDeclaration,
    PackageValidationDiagnostic,
    Provenance,
    SDK_VERSION,
    SchemaVersion,
)
from aquaoptima_contracts.package.package_manifest import ArtifactManifest

from ..health_artifact_schema import build_health_artifact_record


# Canonical package identity for the Sprint-36 Linux package. Stays clear
# of the forbidden-vocabulary substrings the contracts SDK refuses.
PILLARA_DEPLOYMENT_PACKAGE_ID: str = "aopso-pillarA-linux-advisory-package"
PILLARA_DEPLOYMENT_PACKAGE_VERSION: str = "sprint36-r0"

# The validation capability bundle required to load and audit this
# package on an AMAX-8580 Edge target. Mirrors the canonical AMAX
# package-validation-only token set so the Edge validator's capability
# gate accepts the manifest against
# ``default_amax_edge_capability_declaration``.
PILLARA_REQUIRED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "validate_manifest",
        "validate_checksums",
        "validate_safety_flags",
        "load_signed_or_hashed_package",
    }
)


def _sha256_of_path(path: Path) -> tuple[str, int]:
    import hashlib

    data = Path(path).read_bytes()
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest(), len(data)


def _build_model_record_from_artifact_record_json(
    artifact_record_json_path: Path,
    *,
    onnx_path: Path,
) -> ModelArtifactRecord:
    """Reconstruct the Sprint-35 :class:`ModelArtifactRecord` from disk and
    re-verify the on-disk ONNX sha256 matches.

    The Sprint-35 artifact record JSON is the canonical audit-evidence
    snapshot of the packaged detector. We rebuild the dataclass via
    :func:`build_health_artifact_record` using values pulled from that
    JSON so the Sprint-36 manifest binds to the same identity, the same
    checksum, and the same summary -- preserving the Sprint-35 chain of
    custody end-to-end.
    """
    record_payload = json.loads(artifact_record_json_path.read_text())
    artifact_ref = record_payload["artifact_reference"]
    checksum = artifact_ref["checksum"]
    summary_payload = dict(record_payload.get("summary", {}))

    # Re-verify the ONNX sha256 matches what the artifact record claims.
    on_disk_hex, on_disk_size = _sha256_of_path(onnx_path)
    declared_hex = str(checksum["hex_digest"])
    declared_size = int(checksum["size_bytes"])
    if on_disk_hex != declared_hex:
        raise ValueError(
            "ONNX on-disk sha256 does not match Sprint-35 artifact record: "
            f"on_disk={on_disk_hex} declared={declared_hex}"
        )
    if on_disk_size != declared_size:
        raise ValueError(
            "ONNX on-disk size_bytes does not match Sprint-35 artifact record: "
            f"on_disk={on_disk_size} declared={declared_size}"
        )

    # The Sprint-35 summary keys are already SDK-clean. Drop the keys
    # ``build_health_summary`` will re-emit (it would otherwise complain
    # about an unrelated duplicate). The remaining sprint-35 audit
    # facts (axis_order, telemetry_axis_schema_json, output_schema_json,
    # baselines, evaluation_metrics, advisory_only, actuates,
    # parameter_count, pillar, architecture) are passed through as
    # ``summary_extra``.
    drop_keys = {
        "artifact_schema_version",
        "pillar",
        "architecture",
        "parameter_count",
        "advisory_only",
        "actuates",
        "baselines_to_beat",
        "evaluation_metrics",
        "axis_order",
        "telemetry_axis_schema_json",
        "output_schema_json",
    }
    summary_extra = {
        k: v for k, v in summary_payload.items() if k not in drop_keys
    }
    return build_health_artifact_record(
        model_id=str(record_payload["model_id"]),
        model_version=str(record_payload["model_version"]),
        checksum_hex=declared_hex,
        checksum_size_bytes=declared_size,
        checksum_algorithm=str(checksum.get("algorithm", "sha256")),
        producer_component=str(
            record_payload["provenance"].get("component", "ai_server")
        ),
        producer_version=str(
            record_payload["provenance"].get("version", "0.1.0")
        ),
        build_id=str(
            record_payload["provenance"].get(
                "build_id", "aopso-sprint36-pillarA-linux-package"
            )
        ),
        artifact_uri_id=str(artifact_ref.get("id")),
        parameter_count=int(summary_payload.get("parameter_count", 0)),
        architecture=str(summary_payload.get("architecture", "x86_64")),
        summary_extra=summary_extra,
    )


def _build_envelope(*, created_at: str | None) -> ContractEnvelope:
    return ContractEnvelope(
        schema_family="manifest",
        schema_name="deployment_package_manifest",
        schema_version=SchemaVersion.parse("1.0.0"),
        sdk_version=SDK_VERSION,
        created_at=created_at,
        created_by_component="ai_server",
        artifact_id=PILLARA_DEPLOYMENT_PACKAGE_ID,
    )


def _build_capability_requirement(package_id: str) -> CapabilityRequirement:
    return CapabilityRequirement(
        package_id=package_id,
        required=PILLARA_REQUIRED_CAPABILITIES,
        sdk_version=SDK_VERSION,
    )


def _build_safety_declaration(
    *,
    package_id: str,
    package_version: str,
    capability_requirement: CapabilityRequirement,
    acknowledged_at: str,
) -> PackageSafetyDeclaration:
    from aquaoptima_contracts.safety.flags import default_safety_flag_set

    return PackageSafetyDeclaration(
        package_id=package_id,
        package_version=package_version,
        safety_flag_set=default_safety_flag_set(),
        capability_requirement=capability_requirement,
        acknowledged_at=acknowledged_at,
        notes=(
            "offline audit-evidence package for the Pillar-A health detector; "
            "shadow / offline use only; not authorized to influence the site"
        ),
    )


def _build_sidecar_artifact(
    sidecar_path: Path,
) -> ArtifactManifest:
    """Sidecar JSON is registered as an ``audit_evidence`` artifact."""
    hex_digest, size_bytes = _sha256_of_path(sidecar_path)
    return ArtifactManifest(
        role="audit_evidence",
        artifact_reference=ArtifactReference(
            kind="audit_evidence",
            id="aopso-pillarA-onnx-sidecar",
            version=PILLARA_DEPLOYMENT_PACKAGE_VERSION,
            checksum=Checksum(
                algorithm="sha256",
                hex_digest=hex_digest,
                size_bytes=size_bytes,
            ),
        ),
        provenance=Provenance(
            component="ai_server",
            version="0.1.0",
            build_id="aopso-sprint36-pillarA-linux-package",
        ),
        description=(
            "Sprint-35 ONNX sidecar JSON: axis order, standardisation "
            "constants, and the binary flag threshold needed to reproduce the "
            "offline health-evidence pipeline"
        ),
        summary={
            "kind": "sidecar_json",
            "advisory_only": True,
            "evaluation_mode": "offline_only",
        },
    )


def build_pillarA_deployment_package_manifest(
    *,
    onnx_path: Path | str,
    sidecar_path: Path | str,
    artifact_record_json_path: Path | str,
    created_at: str | None = None,
    notes: str | None = None,
) -> DeploymentPackageManifest:
    """Build the Sprint-36 :class:`DeploymentPackageManifest`.

    Parameters
    ----------
    onnx_path
        On-disk path to ``pillarA_health_detector.onnx``. Used to
        re-verify the Sprint-35 sha256.
    sidecar_path
        On-disk path to ``pillarA_health_detector.sidecar.json``. Used
        to register the sidecar as an audit-evidence artifact.
    artifact_record_json_path
        On-disk path to ``pillarA_onnx_artifact_record.json``. The
        Sprint-35 record is rebuilt from this file to preserve the
        chain of custody.
    created_at
        Optional ISO-8601 envelope timestamp. Defaults to the current
        UTC moment.
    notes
        Optional override for the manifest-level notes. Defaults to a
        neutral advisory string; whatever the caller passes is checked
        for forbidden vocabulary by the contracts SDK.
    """
    onnx_path = Path(onnx_path)
    sidecar_path = Path(sidecar_path)
    artifact_record_json_path = Path(artifact_record_json_path)
    if created_at is None:
        created_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    capability_requirement = _build_capability_requirement(
        PILLARA_DEPLOYMENT_PACKAGE_ID
    )
    safety_declaration = _build_safety_declaration(
        package_id=PILLARA_DEPLOYMENT_PACKAGE_ID,
        package_version=PILLARA_DEPLOYMENT_PACKAGE_VERSION,
        capability_requirement=capability_requirement,
        acknowledged_at=created_at,
    )
    model_record = _build_model_record_from_artifact_record_json(
        artifact_record_json_path, onnx_path=onnx_path
    )
    sidecar_artifact = _build_sidecar_artifact(sidecar_path)
    envelope = _build_envelope(created_at=created_at)
    provenance = Provenance(
        component="ai_server",
        version="0.1.0",
        build_id="aopso-sprint36-pillarA-linux-package",
    )
    default_notes = (
        "AOPSO Sprint 36 Pillar-A Linux audit-evidence package for the "
        "AMAX-8580 x86_64 CPU profile. Offline / shadow use only; the "
        "container image runs read-only with no network and a non-root "
        "user. The site PLC retains direct VFD / pump / actuator authority."
    )
    return DeploymentPackageManifest(
        envelope=envelope,
        package_id=PILLARA_DEPLOYMENT_PACKAGE_ID,
        package_version=PILLARA_DEPLOYMENT_PACKAGE_VERSION,
        safety_declaration=safety_declaration,
        capability_requirement=capability_requirement,
        provenance=provenance,
        artifacts=(sidecar_artifact,),
        model_artifacts=(model_record,),
        bundles=(),
        diagnostics=PackageValidationDiagnostic(),
        notes=(notes if notes is not None else default_notes),
    )


def write_pillarA_deployment_package_manifest(
    manifest: DeploymentPackageManifest, out_path: Path | str
) -> Path:
    """Serialize ``manifest`` to canonical JSON at ``out_path``."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest.to_dict(), sort_keys=True, indent=2)
    )
    return out_path


__all__ = [
    "PILLARA_DEPLOYMENT_PACKAGE_ID",
    "PILLARA_DEPLOYMENT_PACKAGE_VERSION",
    "PILLARA_REQUIRED_CAPABILITIES",
    "build_pillarA_deployment_package_manifest",
    "write_pillarA_deployment_package_manifest",
]
