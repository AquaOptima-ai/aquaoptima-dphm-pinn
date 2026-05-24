"""TDD — shadow deployment manifest SDK projections (Sprint 42).

Acceptance: SDK ``ShadowDeploymentArtifact`` / ``ShadowDeploymentManifest``
/ ``ShadowDeploymentPackageDiagnostics`` types capture the *shape*
of the Phase 1 Sprint 39 manifest. Full package generation and
deployment manifest production remain in
``aquaoptima.dphm.shadow_deployment``.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    ContractError,
    SDK_VERSION,
    SafetyFlagSet,
    ShadowDeploymentArtifact,
    ShadowDeploymentManifest,
    ShadowDeploymentPackageDiagnostics,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.safety.flags import default_safety_flag_set


def _flags() -> SafetyFlagSet:
    return default_safety_flag_set()


def test_minimal_artifact_round_trip() -> None:
    artifact = ShadowDeploymentArtifact(
        kind="shadow_replay_dataset",
        name="phase1-replay",
    )
    raw = dump_canonical_json(artifact)
    decoded = load_canonical_json(raw)
    assert decoded["kind"] == "shadow_replay_dataset"
    assert decoded["name"] == "phase1-replay"
    restored = ShadowDeploymentArtifact.from_dict(decoded)
    assert restored == artifact


def test_artifact_with_summary_and_size() -> None:
    artifact = ShadowDeploymentArtifact(
        kind="file",
        name="telemetry.csv",
        artifact_id="art-1",
        path="fixtures/telemetry.csv",
        size_bytes=128,
        description="phase 1 replay csv",
        summary={"frame_count": 3, "name": "telemetry"},
    )
    decoded = load_canonical_json(dump_canonical_json(artifact))
    assert decoded["summary"] == {"frame_count": 3, "name": "telemetry"}
    assert decoded["size_bytes"] == 128


def test_artifact_rejects_unknown_kind() -> None:
    with pytest.raises(ContractError):
        ShadowDeploymentArtifact(kind="control_loop_setpoint", name="x")


def test_artifact_rejects_empty_name() -> None:
    with pytest.raises(ContractError):
        ShadowDeploymentArtifact(kind="file", name="")


def test_artifact_rejects_negative_size() -> None:
    with pytest.raises(ContractError):
        ShadowDeploymentArtifact(kind="file", name="x", size_bytes=-1)


def test_manifest_minimal_round_trip() -> None:
    manifest = ShadowDeploymentManifest(
        package_name="aquaoptima-dphm-shadow-mvp",
        safety_flag_set=_flags(),
    )
    raw = dump_canonical_json(manifest)
    decoded = load_canonical_json(raw)
    assert decoded["package_name"] == "aquaoptima-dphm-shadow-mvp"
    assert decoded["safety_flag_set"]["no_live_ot_binding"] is True
    restored = ShadowDeploymentManifest.from_dict(decoded)
    assert restored == manifest


def test_manifest_rejects_unknown_safety_flag_payload() -> None:
    with pytest.raises(ContractError):
        ShadowDeploymentManifest(package_name="x", safety_flag_set="all_good")  # type: ignore[arg-type]


def test_manifest_with_artifacts_and_diagnostics() -> None:
    manifest = ShadowDeploymentManifest(
        package_name="bundle",
        safety_flag_set=_flags(),
        artifacts=(
            ShadowDeploymentArtifact(kind="file", name="telemetry.csv"),
        ),
        diagnostics=ShadowDeploymentPackageDiagnostics(
            warnings=("noted",),
            errors=(),
        ),
    )
    raw = dump_canonical_json(manifest)
    decoded = load_canonical_json(raw)
    assert decoded["artifacts"][0]["name"] == "telemetry.csv"
    assert decoded["diagnostics"]["warnings"] == ["noted"]


def test_manifest_rejects_empty_package_name() -> None:
    with pytest.raises(ContractError):
        ShadowDeploymentManifest(package_name="", safety_flag_set=_flags())


def test_manifest_rejects_non_tuple_artifacts() -> None:
    with pytest.raises(ContractError):
        ShadowDeploymentManifest(
            package_name="x",
            safety_flag_set=_flags(),
            artifacts=[ShadowDeploymentArtifact(kind="file", name="x")],  # type: ignore[arg-type]
        )


def test_manifest_includes_sdk_version_field() -> None:
    manifest = ShadowDeploymentManifest(
        package_name="x", safety_flag_set=_flags()
    )
    decoded = load_canonical_json(dump_canonical_json(manifest))
    assert decoded["sdk_version"] == SDK_VERSION.render()
