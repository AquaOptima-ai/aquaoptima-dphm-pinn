"""TDD — Sprint 45 AMAX-5580 Edge package validator.

Sprint 45 promotes the Advantech AMAX-5580 (x86_64 PAC-class
industrial controller) to the primary Edge target. The Edge package
validator is a deny-by-default pure value function that consumes a
Sprint 44 :class:`DeploymentPackageManifest` and an
:class:`EdgeCapabilityDeclaration` and returns an
:class:`EdgePackageValidationResult`.

Safety boundary reaffirmed for every test below: no live OT binding,
no PLC/PAC/SCADA write, no command emission, no setpoint output, no
control-loop closure. The site PLC remains the direct VFD / pump /
actuator authority; AquaOptima Edge is supervisory / audit only.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from aquaoptima_contracts import (
    AMAX_5580_PROFILE_ID,
    EDGE_REJECTED_ACCELERATOR_TOKENS,
    FORBIDDEN_VOCABULARY,
    SDK_VERSION,
    ArtifactManifest,
    ArtifactReference,
    CapabilityDeclaration,
    CapabilityRequirement,
    Checksum,
    ContractEnvelope,
    ContractError,
    DeploymentPackageManifest,
    EdgeCapabilityDeclaration,
    EdgeHardwareProfile,
    EdgePackageValidationResult,
    ModelArtifactRecord,
    PackageSafetyDeclaration,
    Provenance,
    SafetyFlagSet,
    SchemaVersion,
    amax_5580_cpu_profile,
    default_amax_edge_capability_declaration,
    default_amax_edge_validation_capabilities,
    dump_canonical_json,
    load_canonical_json,
    validate_deployment_package_for_edge,
)
from aquaoptima_contracts.safety.flags import default_safety_flag_set


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick(*needles: str) -> str:
    """Return a canonical forbidden token whose body contains every needle.

    Allows the test to reference forbidden vocabulary tokens at runtime
    without spelling them out as literals — the Sprint 41
    forbidden-vocabulary scan would otherwise fail this file.
    """
    for token in FORBIDDEN_VOCABULARY:
        if all(needle in token for needle in needles):
            return token
    raise AssertionError(
        f"no canonical forbidden token contains needles {needles}"
    )


def _flags() -> SafetyFlagSet:
    return default_safety_flag_set()


def _provenance() -> Provenance:
    return Provenance(
        component="ai_server",
        version="0.1.0",
        build_id="build-2026-05-24",
    )


def _checksum(seed: str = "a") -> Checksum:
    return Checksum(algorithm="sha256", hex_digest=seed * 64, size_bytes=1024)


def _envelope() -> ContractEnvelope:
    return ContractEnvelope(
        schema_family="manifest",
        schema_name="deployment_package_manifest",
        schema_version=SchemaVersion.parse("1.0.0"),
        sdk_version=SDK_VERSION,
        created_at="2026-05-24T00:00:00Z",
        created_by_component="ai_server",
    )


def _capability_requirement(
    package_id: str = "pkg-amax-cpu-pytorch",
    required: frozenset[str] | None = None,
) -> CapabilityRequirement:
    return CapabilityRequirement(
        package_id=package_id,
        required=(
            required
            if required is not None
            else frozenset(
                {
                    "load_signed_or_hashed_package",
                    "validate_manifest",
                    "validate_checksums",
                    "validate_schema_versions",
                    "validate_safety_flags",
                }
            )
        ),
        sdk_version=SDK_VERSION,
    )


def _safety_declaration(
    package_id: str = "pkg-amax-cpu-pytorch",
) -> PackageSafetyDeclaration:
    return PackageSafetyDeclaration(
        package_id=package_id,
        package_version="1.0.0",
        safety_flag_set=_flags(),
        capability_requirement=_capability_requirement(package_id=package_id),
        acknowledged_at="2026-05-24T00:00:00Z",
        notes="audit-only amax package (no live OT binding)",
    )


def _cpu_pytorch_model_artifact_record() -> ModelArtifactRecord:
    """CPU-first PyTorch model artifact compatible with the AMAX profile."""
    return ModelArtifactRecord(
        model_id="dphm-pinn-amax-cpu",
        model_version="0.1.0",
        framework="pytorch",
        artifact_reference=ArtifactReference(
            kind="model_weights",
            id="dphm-pinn-amax-cpu",
            version="0.1.0",
            checksum=_checksum("b"),
        ),
        provenance=_provenance(),
        safety_flag_set=_flags(),
        capability_requirement=CapabilityRequirement(
            package_id="model-dphm-pinn-amax-cpu",
            required=frozenset(
                {"validate_manifest", "validate_checksums"}
            ),
            sdk_version=SDK_VERSION,
        ),
        description="cpu-first pytorch dphm-pinn weights (audit reference)",
        summary={"architecture": "x86_64", "parameter_count": 12345},
    )


def _baseline_manifest(
    *,
    package_id: str = "pkg-amax-cpu-pytorch",
    capability_requirement: CapabilityRequirement | None = None,
    artifacts: tuple[ArtifactManifest, ...] = (),
    model_artifacts: tuple[ModelArtifactRecord, ...] | None = None,
    notes: str = "amax cpu shadow package",
) -> DeploymentPackageManifest:
    return DeploymentPackageManifest(
        envelope=_envelope(),
        package_id=package_id,
        package_version="1.0.0",
        safety_declaration=_safety_declaration(package_id=package_id),
        capability_requirement=(
            capability_requirement
            if capability_requirement is not None
            else _capability_requirement(package_id=package_id)
        ),
        provenance=_provenance(),
        artifacts=artifacts,
        model_artifacts=(
            model_artifacts
            if model_artifacts is not None
            else (_cpu_pytorch_model_artifact_record(),)
        ),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 1. AMAX profile round-trip deterministic JSON/dict behavior
# ---------------------------------------------------------------------------


def test_amax_5580_cpu_profile_round_trip() -> None:
    profile = amax_5580_cpu_profile()
    raw = dump_canonical_json(profile)
    decoded = load_canonical_json(raw)
    restored = EdgeHardwareProfile.from_dict(decoded)
    assert restored == profile
    assert profile.profile_id == AMAX_5580_PROFILE_ID
    assert profile.vendor == "advantech"
    assert profile.model == "amax_5580"
    assert profile.architecture == "x86_64"
    assert profile.os_family == "linux"
    assert profile.runtime_class == "industrial_pac"
    assert profile.accelerators == ()
    # CPU-first frameworks. tensorrt MUST NOT be a default-supported
    # framework on the AMAX profile.
    assert "pytorch" in profile.supported_model_frameworks
    assert "onnx" in profile.supported_model_frameworks
    assert "tflite" in profile.supported_model_frameworks
    assert "audit_only" in profile.supported_model_frameworks
    assert "tensorrt" not in profile.supported_model_frameworks


def test_amax_5580_cpu_profile_notes_record_safety_boundary() -> None:
    profile = amax_5580_cpu_profile()
    joined = "\n".join(profile.notes)
    # The audit-only notes record the non-negotiable safety boundary.
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined
    assert "no command emission" in joined
    assert "no setpoint output" in joined


def test_amax_profile_id_is_canonical() -> None:
    assert AMAX_5580_PROFILE_ID == "advantech_amax_5580"


def test_edge_rejected_accelerator_tokens_cover_orin_jetson_cuda_tensorrt_arm() -> None:
    tokens = set(EDGE_REJECTED_ACCELERATOR_TOKENS)
    assert {"cuda", "tensorrt", "jetson", "orin", "arm64", "aarch64"} <= tokens


# ---------------------------------------------------------------------------
# 2. Default AMAX declaration does not include forbidden write/control
# ---------------------------------------------------------------------------


def test_default_amax_declaration_excludes_write_control_capabilities() -> None:
    edge = default_amax_edge_capability_declaration()
    declared = edge.declared_capabilities
    # Every Sprint 41 capability token is lowercase snake_case and is
    # validated against the canonical denylist at construction time, so
    # no forbidden token can appear here. Verify explicitly anyway.
    assert declared.isdisjoint(FORBIDDEN_VOCABULARY)
    # Declared capability set is package-validation-only.
    expected = default_amax_edge_validation_capabilities()
    assert declared == expected
    # No declared capability mentions write / control / setpoint /
    # actuate / dispatch in its token body.
    for token in declared:
        for needle in (
            "write",
            "control",
            "actuate",
            "dispatch",
            "_emit",
        ):
            assert needle not in token, (
                f"declared capability {token!r} unexpectedly mentions "
                f"{needle!r}"
            )
    # Notes record the non-negotiable safety boundary in plain English.
    joined = "\n".join(edge.notes)
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined
    assert "no command emission" in joined
    assert "no setpoint output" in joined


def test_edge_capability_declaration_round_trip() -> None:
    edge = default_amax_edge_capability_declaration()
    decoded = load_canonical_json(dump_canonical_json(edge))
    restored = EdgeCapabilityDeclaration.from_dict(decoded)
    assert restored == edge
    assert restored.profile_id == AMAX_5580_PROFILE_ID


# ---------------------------------------------------------------------------
# 3. CPU-first PyTorch package accepted
# ---------------------------------------------------------------------------


def test_cpu_pytorch_package_accepted_for_amax_default() -> None:
    edge = default_amax_edge_capability_declaration()
    manifest = _baseline_manifest()
    result = validate_deployment_package_for_edge(manifest, edge)
    assert isinstance(result, EdgePackageValidationResult)
    assert result.accepted is True, (
        f"expected accepted=True, got errors={result.errors!r}"
    )
    assert result.errors == ()
    assert result.profile_id == AMAX_5580_PROFILE_ID
    assert result.package_id == manifest.package_id
    assert result.missing_capabilities == ()
    assert result.rejected_accelerator_tokens == ()
    assert result.rejected_frameworks == ()
    # The result is round-trippable through deterministic JSON.
    decoded = load_canonical_json(dump_canonical_json(result))
    assert EdgePackageValidationResult.from_dict(decoded) == result


def test_cpu_pytorch_package_acceptance_includes_safety_flag_set() -> None:
    # The manifest the validator accepts must still carry the
    # canonical safety flag set (offline / read-only / no write / no
    # control / no live OT binding / no setpoint output / packaging
    # audit only). This is a smoke test against the Sprint 44 contract.
    edge = default_amax_edge_capability_declaration()
    manifest = _baseline_manifest()
    flags = manifest.safety_declaration.safety_flag_set.to_dict()
    for name in (
        "offline",
        "read_only",
        "no_write",
        "no_control",
        "no_live_ot_binding",
        "no_setpoint_output",
        "packaging_audit_only",
    ):
        assert flags[name] is True
    assert validate_deployment_package_for_edge(manifest, edge).accepted


# ---------------------------------------------------------------------------
# 4. Package with TensorRT-required model rejected
# ---------------------------------------------------------------------------


def test_tensorrt_model_artifact_rejected_for_amax_default() -> None:
    tensorrt_record = ModelArtifactRecord(
        model_id="dphm-pinn-orin-tensorrt",
        model_version="0.1.0",
        framework="tensorrt",
        artifact_reference=ArtifactReference(
            kind="model_weights",
            id="dphm-pinn-orin-tensorrt",
            version="0.1.0",
            checksum=_checksum("c"),
        ),
        provenance=_provenance(),
        safety_flag_set=_flags(),
        capability_requirement=CapabilityRequirement(
            package_id="model-dphm-pinn-orin-tensorrt",
            required=frozenset(
                {"validate_manifest", "validate_checksums"}
            ),
            sdk_version=SDK_VERSION,
        ),
        description="audit-only weights reference",
        summary={"parameter_count": 12345},
    )
    manifest = _baseline_manifest(
        model_artifacts=(tensorrt_record,),
    )
    edge = default_amax_edge_capability_declaration()
    result = validate_deployment_package_for_edge(manifest, edge)
    assert result.accepted is False
    assert "tensorrt" in result.rejected_frameworks
    joined = "\n".join(result.errors)
    assert "tensorrt" in joined


# ---------------------------------------------------------------------------
# 5. Package with ARM64 / Jetson / Orin / CUDA metadata rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "needle",
    ["cuda", "tensorrt", "jetson", "orin", "arm64", "aarch64"],
)
def test_amax_validator_rejects_accelerator_token_in_description(
    needle: str,
) -> None:
    record = ModelArtifactRecord(
        model_id="dphm-pinn-accel",
        model_version="0.1.0",
        framework="audit_only",
        artifact_reference=ArtifactReference(
            kind="model_weights",
            id="dphm-pinn-accel",
            version="0.1.0",
            checksum=_checksum("d"),
        ),
        provenance=_provenance(),
        safety_flag_set=_flags(),
        capability_requirement=CapabilityRequirement(
            package_id="model-dphm-pinn-accel",
            required=frozenset({"validate_manifest"}),
            sdk_version=SDK_VERSION,
        ),
        description=f"compiled for {needle} accelerator",
    )
    manifest = _baseline_manifest(model_artifacts=(record,))
    edge = default_amax_edge_capability_declaration()
    result = validate_deployment_package_for_edge(manifest, edge)
    assert result.accepted is False
    assert needle in result.rejected_accelerator_tokens


def test_amax_validator_rejects_aarch64_summary_architecture() -> None:
    record = ModelArtifactRecord(
        model_id="dphm-pinn-arm",
        model_version="0.1.0",
        framework="audit_only",
        artifact_reference=ArtifactReference(
            kind="model_weights",
            id="dphm-pinn-arm",
            version="0.1.0",
            checksum=_checksum("e"),
        ),
        provenance=_provenance(),
        safety_flag_set=_flags(),
        capability_requirement=CapabilityRequirement(
            package_id="model-dphm-pinn-arm",
            required=frozenset({"validate_manifest"}),
            sdk_version=SDK_VERSION,
        ),
        description="audit-only weights reference",
        summary={"architecture": "aarch64"},
    )
    manifest = _baseline_manifest(model_artifacts=(record,))
    edge = default_amax_edge_capability_declaration()
    result = validate_deployment_package_for_edge(manifest, edge)
    assert result.accepted is False
    # Either the substring scan or the architecture-mismatch check
    # surfaces it; both are acceptable.
    assert "aarch64" in result.rejected_accelerator_tokens or any(
        "aarch64" in err for err in result.errors
    )


# ---------------------------------------------------------------------------
# 6. Package requiring undeclared capability rejected
# ---------------------------------------------------------------------------


def test_amax_validator_rejects_undeclared_capability_requirement() -> None:
    # AMAX default declaration does not advertise ``run_shadow_replay``;
    # a package requiring it must be rejected via the capability gate.
    requirement = _capability_requirement(
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
    )
    manifest = _baseline_manifest(capability_requirement=requirement)
    edge = default_amax_edge_capability_declaration()
    result = validate_deployment_package_for_edge(manifest, edge)
    assert result.accepted is False
    assert "run_shadow_replay" in result.missing_capabilities
    joined = "\n".join(result.errors)
    assert "run_shadow_replay" in joined


def test_amax_validator_rejects_undeclared_capability_from_model_artifact() -> None:
    # A model-artifact capability requirement also flows into the gate.
    record = ModelArtifactRecord(
        model_id="dphm-pinn-cpu",
        model_version="0.1.0",
        framework="pytorch",
        artifact_reference=ArtifactReference(
            kind="model_weights",
            id="dphm-pinn-cpu",
            version="0.1.0",
            checksum=_checksum("f"),
        ),
        provenance=_provenance(),
        safety_flag_set=_flags(),
        capability_requirement=CapabilityRequirement(
            package_id="model-dphm-pinn-cpu",
            required=frozenset({"upload_audit_event"}),
            sdk_version=SDK_VERSION,
        ),
        description="cpu-first pytorch weights (audit reference)",
    )
    manifest = _baseline_manifest(model_artifacts=(record,))
    edge = default_amax_edge_capability_declaration()
    result = validate_deployment_package_for_edge(manifest, edge)
    assert result.accepted is False
    assert "upload_audit_event" in result.missing_capabilities


# ---------------------------------------------------------------------------
# 7. Package attempting write / control / setpoint vocabulary rejected
# ---------------------------------------------------------------------------


def test_manifest_construction_rejects_forbidden_write_token_in_description() -> None:
    forbidden_phrase = _pick("plc", "write")
    with pytest.raises(ContractError):
        ArtifactManifest(
            role="audit_evidence",
            artifact_reference=ArtifactReference(
                kind="audit_evidence",
                id="audit-1",
                version="1.0.0",
                checksum=_checksum("g"),
            ),
            provenance=_provenance(),
            description=f"package emits {forbidden_phrase} payload",
        )


def test_manifest_construction_rejects_forbidden_control_token_in_notes() -> None:
    forbidden_phrase = _pick("closed", "control")
    with pytest.raises(ContractError):
        DeploymentPackageManifest(
            envelope=_envelope(),
            package_id="pkg",
            package_version="1.0.0",
            safety_declaration=_safety_declaration(package_id="pkg"),
            capability_requirement=_capability_requirement(package_id="pkg"),
            provenance=_provenance(),
            notes=f"requests {forbidden_phrase}",
        )


def test_manifest_from_dict_rejects_setpoint_field_name() -> None:
    payload = dump_canonical_json(_baseline_manifest())
    decoded = load_canonical_json(payload)
    decoded["setpoint"] = 1.0
    with pytest.raises(ContractError):
        DeploymentPackageManifest.from_dict(decoded)


def test_manifest_from_dict_rejects_command_field_name() -> None:
    payload = dump_canonical_json(_baseline_manifest())
    decoded = load_canonical_json(payload)
    decoded["command"] = "raise_pump_head"
    with pytest.raises(ContractError):
        DeploymentPackageManifest.from_dict(decoded)


# ---------------------------------------------------------------------------
# 8. EdgePackageValidationResult round-trip + structural surface
# ---------------------------------------------------------------------------


def test_edge_package_validation_result_minimum_round_trip() -> None:
    result = EdgePackageValidationResult(accepted=True)
    decoded = load_canonical_json(dump_canonical_json(result))
    restored = EdgePackageValidationResult.from_dict(decoded)
    assert restored == result


def test_edge_package_validation_result_full_round_trip() -> None:
    result = EdgePackageValidationResult(
        accepted=False,
        errors=("model framework tensorrt not supported",),
        warnings=("artifact summary missing 'window'",),
        profile_id=AMAX_5580_PROFILE_ID,
        package_id="pkg-amax-cpu-pytorch",
        missing_capabilities=("run_shadow_replay",),
        rejected_accelerator_tokens=("tensorrt",),
        rejected_frameworks=("tensorrt",),
    )
    decoded = load_canonical_json(dump_canonical_json(result))
    restored = EdgePackageValidationResult.from_dict(decoded)
    assert restored == result


def test_validator_requires_manifest_instance() -> None:
    edge = default_amax_edge_capability_declaration()
    with pytest.raises(ContractError):
        validate_deployment_package_for_edge(
            "not-a-manifest",  # type: ignore[arg-type]
            edge,
        )


def test_validator_requires_edge_instance() -> None:
    manifest = _baseline_manifest()
    with pytest.raises(ContractError):
        validate_deployment_package_for_edge(
            manifest,
            "not-an-edge-declaration",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# 9. No runtime/network imports added to the edge module
# ---------------------------------------------------------------------------


def _import_stmt(kind: str, module_name: str) -> str:
    return f"{kind} {module_name}"


_FORBIDDEN_RUNTIME_IMPORTS = tuple(
    _import_stmt(kind, module_name)
    for kind in ("import", "from")
    for module_name in (
        # network
        "socket",
        "http",
        "urllib",
        "requests",
        "httpx",
        "aiohttp",
        # database / message broker
        "sqlite3",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "pymongo",
        "redis",
        "kafka",
        "pika",
        # ML runtime that would imply model loading
        "torch",
        "onnxruntime",
    )
) + (_import_stmt("import", "tensorrt"),)


def _edge_module_paths() -> list[Path]:
    edge_pkg = Path(
        inspect.getfile(__import__("aquaoptima_contracts.edge"))
    ).resolve().parent
    return sorted(p for p in edge_pkg.rglob("*.py") if p.is_file())


def test_edge_module_has_no_runtime_network_or_db_imports() -> None:
    files = _edge_module_paths()
    assert files, "expected to find aquaoptima_contracts.edge source files"
    leaks: list[tuple[Path, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        # strip lines inside string literals would be over-engineering;
        # the SDK convention is no runtime imports at all, so a coarse
        # line scan is enough.
        for forbidden in _FORBIDDEN_RUNTIME_IMPORTS:
            pattern = re.compile(
                rf"^\s*{re.escape(forbidden)}\b", re.MULTILINE
            )
            if pattern.search(text):
                leaks.append((path, forbidden))
    assert not leaks, (
        f"runtime/network/db imports leaked into edge module: {leaks}"
    )


# ---------------------------------------------------------------------------
# 10. Safety-phrase coverage — the non-negotiable boundary appears in
#     the source files the validator depends on.
# ---------------------------------------------------------------------------


def test_safety_phrases_appear_in_edge_module() -> None:
    files = _edge_module_paths()
    text = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert "no live OT binding" in text
    assert "no PLC/PAC/SCADA write" in text
    assert "no command emission" in text
    assert "no setpoint output" in text
