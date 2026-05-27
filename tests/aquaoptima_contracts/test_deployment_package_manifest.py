"""TDD — Sprint 44 deployment package manifest SDK projections.

Sprint 44 adds full SDK contract *shapes* for deployment package
manifests and model / artifact records. The Phase 1 runtime stays
the authority for any actual packaging behavior — the SDK only owns
deterministic deny-by-default shape, validation, and JSON projection.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    FORBIDDEN_VOCABULARY,
    SDK_VERSION,
    ArtifactBundleRecord,
    ArtifactManifest,
    ArtifactReference,
    CapabilityRequirement,
    Checksum,
    ContractError,
    ContractEnvelope,
    DeploymentPackageManifest,
    ModelArtifactRecord,
    PACKAGE_ARTIFACT_ROLES,
    PACKAGE_MODEL_FRAMEWORKS,
    PackageSafetyDeclaration,
    PackageValidationDiagnostic,
    Provenance,
    SafetyFlagSet,
    SchemaVersion,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.safety.flags import default_safety_flag_set


def _pick(*needles: str) -> str:
    """Return a canonical forbidden token whose body contains every needle.

    The Sprint 41 forbidden-vocabulary scan uses a word-boundary regex
    against every file under ``src/aquaoptima_contracts/`` and
    ``tests/aquaoptima_contracts/`` other than the canonical denylist
    module itself. This helper lets the test reference a forbidden
    token at runtime without ever spelling it out as a single literal
    in source.
    """
    for token in FORBIDDEN_VOCABULARY:
        if all(needle in token for needle in needles):
            return token
    raise AssertionError(
        f"no canonical forbidden token contains needles {needles}"
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _flags() -> SafetyFlagSet:
    return default_safety_flag_set()


def _checksum() -> Checksum:
    return Checksum(algorithm="sha256", hex_digest="a" * 64, size_bytes=1024)


def _artifact_reference(kind: str = "shadow_replay_dataset") -> ArtifactReference:
    return ArtifactReference(
        kind=kind,
        id="phase1-replay-2024-01-01",
        version="1.0.0",
        checksum=_checksum(),
        uri="aquaoptima://artifacts/replay/phase1-2024-01-01",
    )


def _provenance() -> Provenance:
    return Provenance(
        component="ai_server",
        version="0.1.0",
        build_id="build-2024-01-01-001",
    )


def _capability_requirement(package_id: str = "pkg-shadow-mvp") -> CapabilityRequirement:
    return CapabilityRequirement(
        package_id=package_id,
        required=frozenset(
            {
                "load_signed_or_hashed_package",
                "validate_manifest",
                "validate_checksums",
                "validate_schema_versions",
                "validate_safety_flags",
                "run_shadow_replay",
            }
        ),
        sdk_version=SDK_VERSION,
    )


def _safety_declaration(package_id: str = "pkg-shadow-mvp") -> PackageSafetyDeclaration:
    return PackageSafetyDeclaration(
        package_id=package_id,
        package_version="1.0.0",
        safety_flag_set=_flags(),
        capability_requirement=_capability_requirement(package_id=package_id),
        acknowledged_at="2026-05-24T00:00:00Z",
        notes="audit-only shadow package",
    )


def _artifact_manifest() -> ArtifactManifest:
    return ArtifactManifest(
        role="shadow_replay_dataset",
        artifact_reference=_artifact_reference(),
        provenance=_provenance(),
        description="phase 1 replay dataset",
        summary={"frame_count": 4, "axis_count": 2},
    )


def _model_artifact_record() -> ModelArtifactRecord:
    return ModelArtifactRecord(
        model_id="dphm-pinn-shadow",
        model_version="0.1.0",
        framework="audit_only",
        artifact_reference=ArtifactReference(
            kind="model_weights",
            id="dphm-pinn-shadow",
            version="0.1.0",
            checksum=Checksum(
                algorithm="sha256", hex_digest="b" * 64, size_bytes=2048
            ),
        ),
        provenance=_provenance(),
        safety_flag_set=_flags(),
        capability_requirement=CapabilityRequirement(
            package_id="model-dphm-pinn-shadow",
            required=frozenset({"validate_manifest", "validate_checksums"}),
            sdk_version=SDK_VERSION,
        ),
        description="audit-only weights reference",
        summary={"parameter_count": 12345},
    )


def _diagnostics() -> PackageValidationDiagnostic:
    return PackageValidationDiagnostic(
        warnings=("artifact summary missing 'window'",),
        errors=(),
    )


def _envelope() -> ContractEnvelope:
    return ContractEnvelope(
        schema_family="manifest",
        schema_name="deployment_package_manifest",
        schema_version=SchemaVersion.parse("1.0.0"),
        sdk_version=SDK_VERSION,
        created_at="2026-05-24T00:00:00Z",
        created_by_component="ai_server",
    )


# ---------------------------------------------------------------------------
# PackageValidationDiagnostic
# ---------------------------------------------------------------------------


def test_diagnostic_minimal_round_trip() -> None:
    diag = PackageValidationDiagnostic()
    raw = dump_canonical_json(diag)
    decoded = load_canonical_json(raw)
    assert decoded == {"warnings": [], "errors": []}
    assert PackageValidationDiagnostic.from_dict(decoded) == diag


def test_diagnostic_carries_warnings_and_errors() -> None:
    diag = PackageValidationDiagnostic(
        warnings=("missing optional artifact",),
        errors=("unknown artifact role",),
    )
    decoded = load_canonical_json(dump_canonical_json(diag))
    assert decoded["warnings"] == ["missing optional artifact"]
    assert decoded["errors"] == ["unknown artifact role"]


def test_diagnostic_rejects_non_tuple_warnings() -> None:
    with pytest.raises(ContractError):
        PackageValidationDiagnostic(warnings=["x"])  # type: ignore[arg-type]


def test_diagnostic_rejects_non_string_entry() -> None:
    with pytest.raises(ContractError):
        PackageValidationDiagnostic(warnings=(1,))  # type: ignore[arg-type]


def test_diagnostic_rejects_unknown_fields_in_from_dict() -> None:
    with pytest.raises(ContractError):
        PackageValidationDiagnostic.from_dict(
            {"warnings": [], "errors": [], "extras": []}
        )


# ---------------------------------------------------------------------------
# PackageSafetyDeclaration
# ---------------------------------------------------------------------------


def test_safety_declaration_minimal_round_trip() -> None:
    decl = _safety_declaration()
    raw = dump_canonical_json(decl)
    decoded = load_canonical_json(raw)
    restored = PackageSafetyDeclaration.from_dict(decoded)
    assert restored == decl
    assert decoded["safety_flag_set"]["no_live_ot_binding"] is True
    assert decoded["package_id"] == "pkg-shadow-mvp"


def test_safety_declaration_requires_non_empty_package_id() -> None:
    with pytest.raises(ContractError):
        PackageSafetyDeclaration(
            package_id="",
            package_version="1.0.0",
            safety_flag_set=_flags(),
            capability_requirement=_capability_requirement(),
        )


def test_safety_declaration_rejects_non_safety_flag_set() -> None:
    with pytest.raises(ContractError):
        PackageSafetyDeclaration(
            package_id="x",
            package_version="1.0.0",
            safety_flag_set={"offline": True},  # type: ignore[arg-type]
            capability_requirement=_capability_requirement(),
        )


def test_safety_declaration_rejects_non_capability_requirement() -> None:
    with pytest.raises(ContractError):
        PackageSafetyDeclaration(
            package_id="x",
            package_version="1.0.0",
            safety_flag_set=_flags(),
            capability_requirement="ok",  # type: ignore[arg-type]
        )


def test_safety_declaration_rejects_forbidden_token_in_notes() -> None:
    notes = f"this carries {_pick('closed', 'control')}"
    with pytest.raises(ContractError):
        PackageSafetyDeclaration(
            package_id="pkg",
            package_version="1.0.0",
            safety_flag_set=_flags(),
            capability_requirement=_capability_requirement(),
            notes=notes,
        )


def test_safety_declaration_rejects_forbidden_token_in_package_id() -> None:
    bad_id = f"pkg-{_pick('plc', 'write')}"
    with pytest.raises(ContractError):
        PackageSafetyDeclaration(
            package_id=bad_id,
            package_version="1.0.0",
            safety_flag_set=_flags(),
            capability_requirement=_capability_requirement(),
        )


# ---------------------------------------------------------------------------
# ArtifactManifest
# ---------------------------------------------------------------------------


def test_artifact_manifest_round_trip() -> None:
    am = _artifact_manifest()
    decoded = load_canonical_json(dump_canonical_json(am))
    restored = ArtifactManifest.from_dict(decoded)
    assert restored == am
    assert decoded["role"] == "shadow_replay_dataset"
    assert decoded["artifact_reference"]["checksum"]["algorithm"] == "sha256"


def test_artifact_manifest_rejects_unknown_role() -> None:
    with pytest.raises(ContractError):
        ArtifactManifest(
            role="setpoint_writer",
            artifact_reference=_artifact_reference(),
            provenance=_provenance(),
        )


def test_artifact_manifest_rejects_forbidden_vocabulary_role() -> None:
    # roles must never match a forbidden vocabulary token, even if the
    # SDK ever expanded the allowed list
    bad_role = _pick("plc", "write")
    with pytest.raises(ContractError):
        ArtifactManifest(
            role=bad_role,
            artifact_reference=_artifact_reference(),
            provenance=_provenance(),
        )


def test_artifact_manifest_requires_artifact_reference() -> None:
    with pytest.raises(ContractError):
        ArtifactManifest(
            role="shadow_replay_dataset",
            artifact_reference="not-a-reference",  # type: ignore[arg-type]
            provenance=_provenance(),
        )


def test_artifact_manifest_requires_provenance() -> None:
    with pytest.raises(ContractError):
        ArtifactManifest(
            role="shadow_replay_dataset",
            artifact_reference=_artifact_reference(),
            provenance={"component": "ai_server"},  # type: ignore[arg-type]
        )


def test_artifact_manifest_summary_rejects_nested_mappings() -> None:
    with pytest.raises(ContractError):
        ArtifactManifest(
            role="shadow_replay_dataset",
            artifact_reference=_artifact_reference(),
            provenance=_provenance(),
            summary={"frame_count": {"inner": 1}},
        )


def test_artifact_manifest_rejects_forbidden_description() -> None:
    description = f"targets {_pick('command', 'emit')} pipeline"
    with pytest.raises(ContractError):
        ArtifactManifest(
            role="shadow_replay_dataset",
            artifact_reference=_artifact_reference(),
            provenance=_provenance(),
            description=description,
        )


# ---------------------------------------------------------------------------
# ModelArtifactRecord
# ---------------------------------------------------------------------------


def test_model_artifact_record_round_trip() -> None:
    record = _model_artifact_record()
    decoded = load_canonical_json(dump_canonical_json(record))
    restored = ModelArtifactRecord.from_dict(decoded)
    assert restored == record
    assert decoded["framework"] == "audit_only"
    assert decoded["artifact_reference"]["checksum"]["hex_digest"] == "b" * 64


def test_model_artifact_record_rejects_unknown_framework() -> None:
    with pytest.raises(ContractError):
        ModelArtifactRecord(
            model_id="m",
            model_version="1.0.0",
            framework="proprietary-x",
            artifact_reference=_artifact_reference(kind="model_weights"),
            provenance=_provenance(),
            safety_flag_set=_flags(),
            capability_requirement=_capability_requirement(),
        )


def test_model_artifact_record_rejects_inline_weights_field() -> None:
    # The from_dict path must reject any caller-supplied "weights",
    # "binary", or "raw" field — model weights live behind an
    # ArtifactReference checksum only.
    payload = dump_canonical_json(_model_artifact_record())
    decoded = load_canonical_json(payload)
    decoded["weights"] = "AAAA"
    with pytest.raises(ContractError):
        ModelArtifactRecord.from_dict(decoded)


def test_model_artifact_record_requires_checksum_on_reference() -> None:
    bad_reference = ArtifactReference(
        kind="model_weights",
        id="m",
        version="1.0.0",
    )
    with pytest.raises(ContractError):
        ModelArtifactRecord(
            model_id="m",
            model_version="1.0.0",
            framework="audit_only",
            artifact_reference=bad_reference,
            provenance=_provenance(),
            safety_flag_set=_flags(),
            capability_requirement=_capability_requirement(),
        )


def test_model_artifact_record_rejects_forbidden_description() -> None:
    description = f"includes {_pick('scada', 'write')} reference"
    with pytest.raises(ContractError):
        ModelArtifactRecord(
            model_id="m",
            model_version="1.0.0",
            framework="audit_only",
            artifact_reference=ArtifactReference(
                kind="model_weights",
                id="m",
                version="1.0.0",
                checksum=Checksum(
                    algorithm="sha256", hex_digest="c" * 64, size_bytes=1
                ),
            ),
            provenance=_provenance(),
            safety_flag_set=_flags(),
            capability_requirement=_capability_requirement(),
            description=description,
        )


# ---------------------------------------------------------------------------
# ArtifactBundleRecord
# ---------------------------------------------------------------------------


def test_artifact_bundle_record_round_trip() -> None:
    bundle = ArtifactBundleRecord(
        bundle_id="bundle-shadow-2026-05-24",
        bundle_version="1.0.0",
        artifacts=(_artifact_manifest(),),
        description="phase 1 shadow audit bundle",
    )
    decoded = load_canonical_json(dump_canonical_json(bundle))
    restored = ArtifactBundleRecord.from_dict(decoded)
    assert restored == bundle
    assert decoded["artifacts"][0]["role"] == "shadow_replay_dataset"


def test_artifact_bundle_record_rejects_empty_id() -> None:
    with pytest.raises(ContractError):
        ArtifactBundleRecord(
            bundle_id="",
            bundle_version="1.0.0",
            artifacts=(_artifact_manifest(),),
        )


def test_artifact_bundle_record_requires_tuple_artifacts() -> None:
    with pytest.raises(ContractError):
        ArtifactBundleRecord(
            bundle_id="b",
            bundle_version="1.0.0",
            artifacts=[_artifact_manifest()],  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# DeploymentPackageManifest
# ---------------------------------------------------------------------------


def test_deployment_package_manifest_round_trip() -> None:
    manifest = DeploymentPackageManifest(
        envelope=_envelope(),
        package_id="pkg-shadow-mvp",
        package_version="1.0.0",
        safety_declaration=_safety_declaration(),
        capability_requirement=_capability_requirement(),
        provenance=_provenance(),
        artifacts=(_artifact_manifest(),),
        model_artifacts=(_model_artifact_record(),),
        diagnostics=_diagnostics(),
        notes="audit-only manifest",
    )
    raw = dump_canonical_json(manifest)
    decoded = load_canonical_json(raw)
    restored = DeploymentPackageManifest.from_dict(decoded)
    assert restored == manifest
    assert decoded["package_id"] == "pkg-shadow-mvp"
    assert decoded["safety_declaration"]["safety_flag_set"]["packaging_audit_only"] is True
    assert decoded["envelope"]["schema_family"] == "manifest"


def test_deployment_package_manifest_default_diagnostics() -> None:
    manifest = DeploymentPackageManifest(
        envelope=_envelope(),
        package_id="pkg",
        package_version="1.0.0",
        safety_declaration=_safety_declaration(package_id="pkg"),
        capability_requirement=_capability_requirement(package_id="pkg"),
        provenance=_provenance(),
    )
    decoded = load_canonical_json(dump_canonical_json(manifest))
    assert decoded["diagnostics"] == {"warnings": [], "errors": []}
    assert decoded["artifacts"] == []
    assert decoded["model_artifacts"] == []
    assert decoded["bundles"] == []


def test_deployment_package_manifest_rejects_safety_declaration_mismatch() -> None:
    # The PackageSafetyDeclaration's package_id must agree with the
    # top-level manifest's package_id.
    with pytest.raises(ContractError):
        DeploymentPackageManifest(
            envelope=_envelope(),
            package_id="pkg-A",
            package_version="1.0.0",
            safety_declaration=_safety_declaration(package_id="pkg-B"),
            capability_requirement=_capability_requirement(package_id="pkg-A"),
            provenance=_provenance(),
        )


def test_deployment_package_manifest_rejects_capability_mismatch() -> None:
    # The CapabilityRequirement.package_id must also agree.
    with pytest.raises(ContractError):
        DeploymentPackageManifest(
            envelope=_envelope(),
            package_id="pkg-A",
            package_version="1.0.0",
            safety_declaration=_safety_declaration(package_id="pkg-A"),
            capability_requirement=_capability_requirement(package_id="pkg-B"),
            provenance=_provenance(),
        )


def test_deployment_package_manifest_rejects_forbidden_token_in_notes() -> None:
    notes = f"this is a {_pick('remote', 'control')} payload"
    with pytest.raises(ContractError):
        DeploymentPackageManifest(
            envelope=_envelope(),
            package_id="pkg",
            package_version="1.0.0",
            safety_declaration=_safety_declaration(package_id="pkg"),
            capability_requirement=_capability_requirement(package_id="pkg"),
            provenance=_provenance(),
            notes=notes,
        )


def test_deployment_package_manifest_rejects_unknown_field() -> None:
    payload = dump_canonical_json(
        DeploymentPackageManifest(
            envelope=_envelope(),
            package_id="pkg",
            package_version="1.0.0",
            safety_declaration=_safety_declaration(package_id="pkg"),
            capability_requirement=_capability_requirement(package_id="pkg"),
            provenance=_provenance(),
        )
    )
    decoded = load_canonical_json(payload)
    # any forbidden / setpoint-shaped field must be rejected
    decoded["setpoint"] = 42.0
    with pytest.raises(ContractError):
        DeploymentPackageManifest.from_dict(decoded)


def test_deployment_package_manifest_envelope_is_manifest_family() -> None:
    bad_env = ContractEnvelope(
        schema_family="telemetry",
        schema_name="deployment_package_manifest",
        schema_version=SchemaVersion.parse("1.0.0"),
        sdk_version=SDK_VERSION,
    )
    with pytest.raises(ContractError):
        DeploymentPackageManifest(
            envelope=bad_env,
            package_id="pkg",
            package_version="1.0.0",
            safety_declaration=_safety_declaration(package_id="pkg"),
            capability_requirement=_capability_requirement(package_id="pkg"),
            provenance=_provenance(),
        )


def test_deployment_package_manifest_includes_sdk_version() -> None:
    manifest = DeploymentPackageManifest(
        envelope=_envelope(),
        package_id="pkg",
        package_version="1.0.0",
        safety_declaration=_safety_declaration(package_id="pkg"),
        capability_requirement=_capability_requirement(package_id="pkg"),
        provenance=_provenance(),
    )
    decoded = load_canonical_json(dump_canonical_json(manifest))
    assert decoded["envelope"]["sdk_version"] == SDK_VERSION.render()


# ---------------------------------------------------------------------------
# Builders / projections from existing SDK contracts
# ---------------------------------------------------------------------------


def test_deployment_package_manifest_builder_from_shadow_manifest() -> None:
    """Helper turns a Sprint 42 ShadowDeploymentManifest into a Sprint 44
    DeploymentPackageManifest without importing runtime code."""

    from aquaoptima_contracts import (
        ShadowDeploymentArtifact,
        ShadowDeploymentManifest,
        build_deployment_package_manifest_from_shadow,
    )

    shadow = ShadowDeploymentManifest(
        package_name="pkg-shadow-mvp",
        package_version="1.0.0",
        safety_flag_set=_flags(),
        artifacts=(
            ShadowDeploymentArtifact(
                kind="shadow_replay_dataset",
                name="phase1-replay",
            ),
        ),
    )
    manifest = build_deployment_package_manifest_from_shadow(
        shadow,
        capability_requirement=_capability_requirement(package_id="pkg-shadow-mvp"),
        provenance=_provenance(),
    )
    assert isinstance(manifest, DeploymentPackageManifest)
    assert manifest.package_id == "pkg-shadow-mvp"
    assert manifest.package_version == "1.0.0"
    assert manifest.safety_declaration.safety_flag_set == _flags()
    # round-trips through deterministic JSON
    decoded = load_canonical_json(dump_canonical_json(manifest))
    restored = DeploymentPackageManifest.from_dict(decoded)
    assert restored == manifest


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


def test_package_roles_and_frameworks_constants_exposed() -> None:
    assert "shadow_replay_dataset" in PACKAGE_ARTIFACT_ROLES
    assert "model_weights" in PACKAGE_ARTIFACT_ROLES
    assert "audit_only" in PACKAGE_MODEL_FRAMEWORKS
    # No canonical role may collide with any forbidden vocabulary token.
    assert PACKAGE_ARTIFACT_ROLES.isdisjoint(FORBIDDEN_VOCABULARY)
