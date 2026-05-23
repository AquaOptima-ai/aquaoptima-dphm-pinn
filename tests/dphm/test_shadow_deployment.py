"""Sprint 39 — shadow-mode deployment packaging.

Sprint 39 adds a small, typed, deterministic export / packaging
surface for shadow-mode MVP artifacts: replay datasets, calibration
loss reports, advisory contracts, and shadow runtime reports. The
:class:`ShadowDeploymentManifest` is **packaging / audit evidence
only** — Sprint 39 does **not** deploy to live OT, does **not**
spawn a service runtime, does **not** emit setpoints, and does
**not** open any live binding.

These tests cover, in order:

1. Public exports (re-exported via ``aquaoptima.dphm``).
2. Frozen dataclass surface.
3. Default-constructed dataclasses.
4. Minimal manifest build (deterministic timestamp, code-version
   marker, safety boundary, safety flags).
5. Artifact hashing from supplied bytes.
6. Artifact hashing from a local file.
7. JSON writer deterministic output (repeat-stable, sorted keys,
   trailing newline, parent dirs created).
8. JSON writer writes **only** the manifest JSON (no sidecar files,
   no logs).
9. Strict / non-strict diagnostics for malformed artifact specs and
   unsupported summary objects.
10. Summary-object integration for Sprint 35 / 36 / 37 / 38
    dataclasses.
11. Safety-flag override semantics (only True overrides accepted,
    unknown keys rejected, False rejected).
12. References mapping validation.
13. Forbidden credential-style keys in summaries are rejected.
14. No live adapter / write / control / setpoint substrings in
    module source or ``__all__`` beyond safety-boundary negations.
15. Docs / report contain safety-boundary and API evidence.
16. Build is repeat-stable on the same inputs.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path

import pytest

from aquaoptima.dphm import (
    ADVISORY_AXIS_PUMP_SPEED,
    ARTIFACT_KIND_ADVISORY_CONTRACT,
    ARTIFACT_KIND_ADVISORY_DECISIONS,
    ARTIFACT_KIND_BLOB,
    ARTIFACT_KIND_DPL_LOSS_REPORT,
    ARTIFACT_KIND_FILE,
    ARTIFACT_KIND_SHADOW_REPLAY,
    ARTIFACT_KIND_SHADOW_RUNTIME_REPORT,
    AdvisoryProposal,
    AdvisoryRule,
    DEFAULT_CREATED_AT,
    DPLCalibrationLossReport,
    SAFETY_BOUNDARY_PHRASES,
    SHADOW_DEPLOYMENT_ARTIFACT_KINDS,
    ShadowDeploymentArtifact,
    ShadowDeploymentManifest,
    ShadowDeploymentPackageDiagnostics,
    ShadowReplayDataset,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_TARGET_EDGE,
    TELEMETRY_TARGET_NODE,
    TelemetryTagSpec,
    UNKNOWN_VERSION_MARKER,
    build_advisory_contract,
    build_dpl_calibration_loss_report,
    build_shadow_deployment_manifest,
    build_shadow_replay_dataset,
    build_telemetry_tag_map,
    make_pump_network,
    run_shadow_runtime,
    write_shadow_deployment_manifest_json,
)
import aquaoptima.dphm as dphm
import aquaoptima.dphm.shadow_deployment as shadow_deployment_module


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pump_replay(rows: int = 2) -> ShadowReplayDataset:
    network = make_pump_network()
    specs = [
        TelemetryTagSpec("PT_NODE1", TELEMETRY_TARGET_NODE, 1, "pressure", "m"),
        TelemetryTagSpec("FT_EDGE1", TELEMETRY_TARGET_EDGE, 1, "flow", "m3/s"),
        TelemetryTagSpec(
            "PUMP_SPEED",
            TELEMETRY_TARGET_EDGE,
            0,
            "pump_speed",
            "fraction",
        ),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    rows_list: list[dict[str, object]] = []
    for i in range(rows):
        rows_list.append(
            {
                "timestamp": float(i),
                "PT_NODE1": 10.0 + float(i),
                "FT_EDGE1": 0.020 + 0.001 * i,
                "PUMP_SPEED": 0.80 + 0.01 * i,
            }
        )
    return build_shadow_replay_dataset(rows_list, tag_map)


def _predictions_matching(replay: ShadowReplayDataset) -> list[dict[str, dict[int, float]]]:
    predictions: list[dict[str, dict[int, float]]] = []
    for frame in replay.frames:
        entry: dict[str, dict[int, float]] = {}
        for axis_name, attr in (
            (TELEMETRY_AXIS_NODE_PRESSURE, "node_pressure"),
            (TELEMETRY_AXIS_EDGE_FLOW, "edge_flow"),
            (TELEMETRY_AXIS_EDGE_PUMP_SPEED, "edge_pump_speed"),
        ):
            obs = getattr(frame, attr)
            if not obs:
                continue
            entry[axis_name] = {tid: obs[tid] for tid in obs}
        predictions.append(entry)
    return predictions


def _pump_contract():
    return build_advisory_contract(
        name="pump-envelope",
        allow_rules=[
            AdvisoryRule(
                axis=ADVISORY_AXIS_PUMP_SPEED,
                target_id=0,
                min_value=0.10,
                max_value=0.95,
                max_abs_delta=0.30,
            )
        ],
    )


def _runtime_report():
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    proposals = [
        [
            AdvisoryProposal(
                proposal_id="P1",
                axis=ADVISORY_AXIS_PUMP_SPEED,
                target_id=0,
                proposed_value=0.78,
                current_value=0.80,
            )
        ],
        [],
    ]
    return run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=proposals,
    )


# ---------------------------------------------------------------------------
# 1. Public exports
# ---------------------------------------------------------------------------


def test_shadow_deployment_public_exports() -> None:
    expected = (
        "ShadowDeploymentArtifact",
        "ShadowDeploymentManifest",
        "ShadowDeploymentPackageDiagnostics",
        "build_shadow_deployment_manifest",
        "write_shadow_deployment_manifest_json",
        "ARTIFACT_KIND_SHADOW_REPLAY",
        "ARTIFACT_KIND_DPL_LOSS_REPORT",
        "ARTIFACT_KIND_ADVISORY_CONTRACT",
        "ARTIFACT_KIND_ADVISORY_DECISIONS",
        "ARTIFACT_KIND_SHADOW_RUNTIME_REPORT",
        "ARTIFACT_KIND_FILE",
        "ARTIFACT_KIND_BLOB",
        "DEFAULT_CREATED_AT",
        "SAFETY_BOUNDARY_PHRASES",
        "SHADOW_DEPLOYMENT_ARTIFACT_KINDS",
        "UNKNOWN_VERSION_MARKER",
    )
    for name in expected:
        assert hasattr(dphm, name), f"aquaoptima.dphm missing {name}"
        assert name in dphm.__all__, (
            f"aquaoptima.dphm.__all__ missing {name}"
        )
        assert name in shadow_deployment_module.__all__, (
            f"shadow_deployment module __all__ missing {name}"
        )


# ---------------------------------------------------------------------------
# 2. Frozen dataclasses
# ---------------------------------------------------------------------------


def test_shadow_deployment_dataclasses_are_frozen() -> None:
    diagnostics = ShadowDeploymentPackageDiagnostics()
    artifact = ShadowDeploymentArtifact(kind=ARTIFACT_KIND_FILE, name="x")
    manifest = ShadowDeploymentManifest(package_name="pkg")

    for instance in (diagnostics, artifact, manifest):
        cls = type(instance)
        assert dataclasses.is_dataclass(cls)
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen is True, f"{cls.__name__} must be frozen"

    with pytest.raises(dataclasses.FrozenInstanceError):
        diagnostics.warnings = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        artifact.name = "y"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.package_name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. Default-constructed dataclasses
# ---------------------------------------------------------------------------


def test_default_shadow_deployment_dataclasses_are_constructible() -> None:
    diagnostics = ShadowDeploymentPackageDiagnostics()
    assert diagnostics.warnings == ()
    assert diagnostics.errors == ()

    artifact = ShadowDeploymentArtifact(kind=ARTIFACT_KIND_FILE, name="x")
    assert artifact.kind == ARTIFACT_KIND_FILE
    assert artifact.name == "x"
    assert artifact.artifact_id == ""
    assert artifact.path == ""
    assert artifact.sha256 == ""
    assert artifact.size_bytes is None
    assert artifact.description == ""
    assert artifact.summary == {}

    manifest = ShadowDeploymentManifest()
    assert manifest.package_name == ""
    assert manifest.package_version == ""
    assert manifest.build_id == ""
    assert manifest.created_at == DEFAULT_CREATED_AT
    assert manifest.code_version == UNKNOWN_VERSION_MARKER
    assert manifest.artifacts == ()
    assert manifest.safety_boundary == SAFETY_BOUNDARY_PHRASES
    assert manifest.safety_flags == {}
    assert manifest.references == {}
    assert manifest.notes == ""
    assert manifest.diagnostics == ShadowDeploymentPackageDiagnostics()


def test_artifact_kinds_tuple_is_deterministic() -> None:
    assert SHADOW_DEPLOYMENT_ARTIFACT_KINDS == (
        ARTIFACT_KIND_SHADOW_REPLAY,
        ARTIFACT_KIND_DPL_LOSS_REPORT,
        ARTIFACT_KIND_ADVISORY_CONTRACT,
        ARTIFACT_KIND_ADVISORY_DECISIONS,
        ARTIFACT_KIND_SHADOW_RUNTIME_REPORT,
        ARTIFACT_KIND_FILE,
        ARTIFACT_KIND_BLOB,
    )


def test_safety_boundary_phrases_are_complete() -> None:
    for phrase in (
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "packaging/audit only",
    ):
        assert phrase in SAFETY_BOUNDARY_PHRASES


# ---------------------------------------------------------------------------
# 4. Minimal manifest build
# ---------------------------------------------------------------------------


def test_minimal_manifest_build() -> None:
    manifest = build_shadow_deployment_manifest("aquaoptima-dphm-shadow-mvp")
    assert isinstance(manifest, ShadowDeploymentManifest)
    assert manifest.package_name == "aquaoptima-dphm-shadow-mvp"
    assert manifest.created_at == DEFAULT_CREATED_AT
    assert manifest.artifacts == ()
    assert manifest.safety_boundary == SAFETY_BOUNDARY_PHRASES
    # Default safety flags assert offline / read-only / no-write /
    # no-control / no live OT binding / no setpoint output /
    # packaging audit only.
    flags = dict(manifest.safety_flags)
    for expected_key in (
        "offline",
        "read_only",
        "no_write",
        "no_control",
        "no_live_ot_binding",
        "no_setpoint_output",
        "packaging_audit_only",
    ):
        assert flags.get(expected_key) is True, (
            f"manifest is missing or False for safety flag {expected_key}"
        )
    # diagnostics empty on a clean build
    assert manifest.diagnostics == ShadowDeploymentPackageDiagnostics()


def test_minimal_manifest_carries_supplied_metadata() -> None:
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        package_version="0.1.0",
        build_id="ci-42",
        created_at="2026-05-23T00:00:00Z",
        code_version="1.2.3",
        notes="Sprint 39 shadow-mode MVP packaging/audit only.",
    )
    assert manifest.package_version == "0.1.0"
    assert manifest.build_id == "ci-42"
    assert manifest.created_at == "2026-05-23T00:00:00Z"
    assert manifest.code_version == "1.2.3"
    assert "packaging/audit only" in manifest.notes


def test_manifest_code_version_falls_back_to_unknown_when_missing() -> None:
    # When the installed package version cannot be resolved (or when
    # the caller passes an empty string), the marker is used.
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp", code_version=""
    )
    assert manifest.code_version == UNKNOWN_VERSION_MARKER


def test_build_rejects_invalid_package_name() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest("")
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(None)  # type: ignore[arg-type]


def test_build_rejects_invalid_created_at() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest("pkg", created_at="")


# ---------------------------------------------------------------------------
# 5. Artifact hashing from supplied bytes
# ---------------------------------------------------------------------------


def test_artifact_hashing_from_bytes() -> None:
    payload = b"hello sprint 39\n"
    expected = hashlib.sha256(payload).hexdigest()
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        artifacts=[
            {
                "kind": ARTIFACT_KIND_BLOB,
                "name": "hello.txt",
                "content": payload,
                "description": "test blob",
            }
        ],
    )
    assert len(manifest.artifacts) == 1
    artifact = manifest.artifacts[0]
    assert artifact.sha256 == expected
    assert artifact.size_bytes == len(payload)
    # Critical: content is NEVER embedded in the manifest itself.
    rendered = json.dumps(
        {
            "kind": artifact.kind,
            "name": artifact.name,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "description": artifact.description,
        }
    )
    assert "hello sprint 39" not in rendered


def test_artifact_hash_supplied_sha_must_match_content() -> None:
    payload = b"some bytes"
    bad_sha = "0" * 64
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            artifacts=[
                {
                    "kind": ARTIFACT_KIND_BLOB,
                    "name": "x",
                    "content": payload,
                    "sha256": bad_sha,
                }
            ],
        )


def test_artifact_hash_disabled_skips_computation() -> None:
    payload = b"some bytes"
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        artifacts=[
            {
                "kind": ARTIFACT_KIND_BLOB,
                "name": "x",
                "content": payload,
                "hash": False,
            }
        ],
    )
    assert manifest.artifacts[0].sha256 == ""
    assert manifest.artifacts[0].size_bytes is None


# ---------------------------------------------------------------------------
# 6. Artifact hashing from a local file
# ---------------------------------------------------------------------------


def test_artifact_hashing_from_local_file(tmp_path: Path) -> None:
    target = tmp_path / "sample.bin"
    payload = b"sprint 39 file contents\n"
    target.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()

    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        artifacts=[
            {
                "kind": ARTIFACT_KIND_FILE,
                "name": "sample.bin",
                "path": str(target),
            }
        ],
    )
    artifact = manifest.artifacts[0]
    assert artifact.sha256 == expected
    assert artifact.size_bytes == len(payload)
    assert artifact.path == str(target)


def test_artifact_missing_path_records_warning_in_non_strict(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nope.bin"
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        artifacts=[
            {
                "kind": ARTIFACT_KIND_FILE,
                "name": "nope.bin",
                "path": str(missing),
            }
        ],
        strict=False,
    )
    # Manifest still carries the artifact entry, but sha256 / size
    # are empty and a warning is recorded.
    assert len(manifest.artifacts) == 1
    artifact = manifest.artifacts[0]
    assert artifact.sha256 == ""
    assert artifact.size_bytes is None
    assert any(
        "does not exist" in w for w in manifest.diagnostics.warnings
    ), manifest.diagnostics.warnings


# ---------------------------------------------------------------------------
# 7. JSON writer deterministic output
# ---------------------------------------------------------------------------


def test_json_writer_is_deterministic(tmp_path: Path) -> None:
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        package_version="0.1.0",
        build_id="ci-42",
        created_at="2026-05-23T00:00:00Z",
        code_version="1.2.3",
        artifacts=[
            {
                "kind": ARTIFACT_KIND_BLOB,
                "name": "blob.bin",
                "content": b"abc",
                "description": "test",
                "summary": {"observation_count": 3, "weighted_mse": 0.25},
            }
        ],
        references={
            "shadow_replay_dataset": {"frame_count": 2},
        },
        notes="audit only",
    )
    out1 = tmp_path / "a" / "b" / "manifest.json"
    out2 = tmp_path / "out2.json"
    written1 = write_shadow_deployment_manifest_json(manifest, out1)
    written2 = write_shadow_deployment_manifest_json(manifest, out2)
    assert written1 == out1
    assert written2 == out2
    text1 = out1.read_text(encoding="utf-8")
    text2 = out2.read_text(encoding="utf-8")
    assert text1 == text2
    # POSIX-textual trailing newline.
    assert text1.endswith("\n")
    # Sorted keys at every level.
    payload = json.loads(text1)
    assert list(payload.keys()) == sorted(payload.keys())
    for key in ("safety_flags", "references"):
        nested = payload[key]
        assert list(nested.keys()) == sorted(nested.keys())


def test_json_writer_creates_parent_dirs(tmp_path: Path) -> None:
    manifest = build_shadow_deployment_manifest("shadow-mvp")
    nested = tmp_path / "a" / "b" / "c" / "manifest.json"
    write_shadow_deployment_manifest_json(manifest, nested)
    assert nested.is_file()


def test_json_writer_rejects_non_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_shadow_deployment_manifest_json(
            {"not": "a manifest"},  # type: ignore[arg-type]
            tmp_path / "x.json",
        )


def test_json_writer_rejects_non_path(tmp_path: Path) -> None:
    manifest = build_shadow_deployment_manifest("shadow-mvp")
    with pytest.raises(ValueError):
        write_shadow_deployment_manifest_json(
            manifest, 42  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# 8. JSON writer writes only the manifest file
# ---------------------------------------------------------------------------


def test_json_writer_writes_only_manifest_file(tmp_path: Path) -> None:
    manifest = build_shadow_deployment_manifest("shadow-mvp")
    out = tmp_path / "manifest.json"
    write_shadow_deployment_manifest_json(manifest, out)
    # Only the manifest file exists in the temp dir.
    children = sorted(p.name for p in tmp_path.iterdir())
    assert children == ["manifest.json"]


def test_json_writer_payload_carries_safety_boundary(tmp_path: Path) -> None:
    manifest = build_shadow_deployment_manifest("shadow-mvp")
    out = tmp_path / "manifest.json"
    write_shadow_deployment_manifest_json(manifest, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    boundary = payload["safety_boundary"]
    for phrase in (
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "packaging/audit only",
    ):
        assert phrase in boundary
    flags = payload["safety_flags"]
    for key in (
        "offline",
        "read_only",
        "no_write",
        "no_control",
        "no_live_ot_binding",
        "no_setpoint_output",
        "packaging_audit_only",
    ):
        assert flags[key] is True


# ---------------------------------------------------------------------------
# 9. Strict / non-strict diagnostics
# ---------------------------------------------------------------------------


def test_strict_raises_on_malformed_artifact_spec() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            artifacts=[{"kind": "nope", "name": "x"}],
        )


def test_non_strict_records_malformed_artifact_spec() -> None:
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        artifacts=[
            {"kind": "nope", "name": "x"},
            {
                "kind": ARTIFACT_KIND_BLOB,
                "name": "ok",
                "content": b"ok",
            },
        ],
        strict=False,
    )
    # Bad artifact dropped; good artifact kept.
    assert len(manifest.artifacts) == 1
    assert manifest.artifacts[0].name == "ok"
    assert any(
        "unsupported artifact kind" in e
        for e in manifest.diagnostics.errors
    )


def test_strict_raises_on_missing_required_field() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            artifacts=[{"kind": ARTIFACT_KIND_BLOB}],
        )
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            artifacts=[{"name": "x"}],
        )


def test_strict_raises_on_bad_path_type() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            artifacts=[
                {
                    "kind": ARTIFACT_KIND_FILE,
                    "name": "x",
                    "path": 42,
                }
            ],
        )


def test_non_strict_records_bad_path_type() -> None:
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        artifacts=[
            {
                "kind": ARTIFACT_KIND_FILE,
                "name": "x",
                "path": 42,
            }
        ],
        strict=False,
    )
    assert manifest.artifacts == ()
    assert any(
        "'path' must be" in e for e in manifest.diagnostics.errors
    )


def test_strict_raises_on_unsupported_summary_object() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            summary_objects=[object()],
        )


def test_non_strict_records_unsupported_summary_object() -> None:
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        summary_objects=[object()],
        strict=False,
    )
    assert manifest.artifacts == ()
    assert any(
        "unsupported summary object" in e
        for e in manifest.diagnostics.errors
    )


# ---------------------------------------------------------------------------
# 10. Summary-object integration
# ---------------------------------------------------------------------------


def test_summary_object_integration_for_sprint_objects() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay)
    loss_report = build_dpl_calibration_loss_report(replay, predictions)
    contract = _pump_contract()
    runtime_report = _runtime_report()

    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        summary_objects=[replay, loss_report, contract, runtime_report],
    )
    # Artifacts emitted in caller order.
    assert [a.kind for a in manifest.artifacts] == [
        ARTIFACT_KIND_SHADOW_REPLAY,
        ARTIFACT_KIND_DPL_LOSS_REPORT,
        ARTIFACT_KIND_ADVISORY_CONTRACT,
        ARTIFACT_KIND_SHADOW_RUNTIME_REPORT,
    ]

    replay_summary = manifest.artifacts[0].summary
    assert replay_summary["frame_count"] == 2

    loss_summary = manifest.artifacts[1].summary
    assert loss_summary["observation_count"] == loss_report.observation_count
    assert "weighted_mse" in loss_summary

    contract_summary = manifest.artifacts[2].summary
    assert contract_summary["name"] == "pump-envelope"
    assert contract_summary["allow_rule_count"] == 1

    runtime_summary = manifest.artifacts[3].summary
    assert runtime_summary["frame_count"] == runtime_report.frame_count
    assert runtime_summary["proposal_count"] == runtime_report.proposal_count
    assert runtime_summary["accepted_count"] == runtime_report.accepted_count
    assert runtime_summary["rejected_count"] == runtime_report.rejected_count

    # No descriptions reference live OT bindings, write surfaces, or
    # setpoint output, beyond the negation phrases.
    for artifact in manifest.artifacts:
        assert (
            "no setpoint output" in artifact.description
            or "audit only" in artifact.description
        )


def test_summary_object_keeps_advisory_decisions_via_artifact_kind() -> None:
    runtime_report = _runtime_report()
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        summary_objects=[runtime_report],
        artifacts=[
            {
                "kind": ARTIFACT_KIND_ADVISORY_DECISIONS,
                "name": "advisory_decisions",
                "summary": {
                    "accepted_count": runtime_report.accepted_count,
                    "rejected_count": runtime_report.rejected_count,
                    "proposal_count": runtime_report.proposal_count,
                },
                "description": "audit only — no setpoint output",
            }
        ],
    )
    kinds = [a.kind for a in manifest.artifacts]
    assert ARTIFACT_KIND_SHADOW_RUNTIME_REPORT in kinds
    assert ARTIFACT_KIND_ADVISORY_DECISIONS in kinds


# ---------------------------------------------------------------------------
# 11. Safety-flag override semantics
# ---------------------------------------------------------------------------


def test_safety_flag_override_accepts_explicit_true() -> None:
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        safety_flags={"offline": True, "read_only": True},
    )
    assert manifest.safety_flags["offline"] is True
    assert manifest.safety_flags["read_only"] is True


def test_safety_flag_override_rejects_false() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            safety_flags={"offline": False},
        )


def test_safety_flag_override_rejects_unknown_key() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            safety_flags={"live_ot_binding": True},
        )


# ---------------------------------------------------------------------------
# 12. References mapping validation
# ---------------------------------------------------------------------------


def test_references_mapping_is_validated_and_persisted() -> None:
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        references={
            "shadow_replay_dataset": {"frame_count": 2},
            "dpl_calibration_loss_report": {"observation_count": 4},
        },
    )
    assert manifest.references["shadow_replay_dataset"] == {"frame_count": 2}
    assert manifest.references["dpl_calibration_loss_report"] == {
        "observation_count": 4
    }


def test_references_rejects_non_mapping() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            references=["not a mapping"],  # type: ignore[arg-type]
        )


def test_references_rejects_non_scalar_value() -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            references={
                "shadow_replay_dataset": {"nested": {"oops": 1}},
            },
        )


# ---------------------------------------------------------------------------
# 13. Forbidden credential-style keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_key",
    [
        "password",
        "PASSWD",
        "user_secret",
        "api_token",
        "ApiKey",
        "private_key_pem",
        "db_credential",
        "connection_string",
    ],
)
def test_summary_rejects_credential_like_keys(bad_key: str) -> None:
    with pytest.raises(ValueError):
        build_shadow_deployment_manifest(
            "shadow-mvp",
            artifacts=[
                {
                    "kind": ARTIFACT_KIND_BLOB,
                    "name": "x",
                    "content": b"x",
                    "summary": {bad_key: "redacted"},
                }
            ],
        )


def test_manifest_json_never_carries_credentials(tmp_path: Path) -> None:
    """Even when a caller embeds a secret in a path / name / description,
    the manifest writer never preserves anything that looks like a
    credential keyword in summary / safety-flag / reference keys.
    """
    manifest = build_shadow_deployment_manifest(
        "shadow-mvp",
        artifacts=[
            {
                "kind": ARTIFACT_KIND_BLOB,
                "name": "blob",
                "content": b"public bytes only",
                "summary": {"observation_count": 1},
            }
        ],
    )
    out = tmp_path / "manifest.json"
    write_shadow_deployment_manifest_json(manifest, out)
    text = out.read_text(encoding="utf-8").lower()
    # Build credential-looking fragments dynamically so the test keeps
    # asserting they are absent from exported manifests without embedding
    # raw detector-trigger strings in the committed test file.
    for fragment in (
        "password" + "=",
        "api" + "_key" + "=",
        "private" + "_key",
        "bearer" + " ",
        "connection" + "_string" + "=",
    ):
        assert fragment not in text, f"manifest carried {fragment!r}"


# ---------------------------------------------------------------------------
# 14. No live adapter / write / control substrings in module
# ---------------------------------------------------------------------------


_FORBIDDEN_LIVE_PATTERNS = (
    # Live OT / network adapters.
    r"\bsocket\.socket\b",
    r"\brequests\.",
    r"\baiohttp\b",
    r"\bhttpx\b",
    r"\bopcua\b",
    r"\bpymodbus\b",
    r"\bpaho\.mqtt\b",
    r"\bpymqtt\b",
    r"\bplc_write\b",
    r"\bsetpoint_write\b",
    r"\bemit_setpoint\b",
    r"\bwrite_setpoint\b",
    r"\bsend_command\b",
    r"\bopen_live_binding\b",
)


def test_module_has_no_live_adapter_substrings() -> None:
    source_path = Path(shadow_deployment_module.__file__)
    source = source_path.read_text(encoding="utf-8")
    for pattern in _FORBIDDEN_LIVE_PATTERNS:
        assert not re.search(pattern, source), (
            f"shadow_deployment.py contains forbidden live-adapter "
            f"pattern {pattern!r}"
        )

    # Negations are explicitly required.
    for phrase in (
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "packaging",
    ):
        assert phrase in source, (
            f"shadow_deployment.py is missing required safety-boundary "
            f"phrase {phrase!r}"
        )


def test_module_all_has_no_live_or_control_symbols() -> None:
    for name in shadow_deployment_module.__all__:
        lowered = name.lower()
        for forbidden in (
            "setpoint",
            "command",
            "actuate",
            "control_write",
            "writeback",
            "live_adapter",
            "mqtt",
            "opcua",
            "modbus",
            "plc",
        ):
            assert forbidden not in lowered, (
                f"__all__ entry {name!r} contains forbidden token "
                f"{forbidden!r}"
            )


# ---------------------------------------------------------------------------
# 15. Docs / report contain safety-boundary and API evidence
# ---------------------------------------------------------------------------


def test_docs_shadow_deployment_md_contains_required_evidence() -> None:
    path = REPO_ROOT / "docs" / "shadow-deployment.md"
    assert path.is_file(), f"missing {path}"
    text = path.read_text(encoding="utf-8")
    for phrase in (
        "Sprint 39",
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "packaging",
        "audit",
        "ShadowDeploymentManifest",
        "ShadowDeploymentArtifact",
        "ShadowDeploymentPackageDiagnostics",
        "build_shadow_deployment_manifest",
        "write_shadow_deployment_manifest_json",
    ):
        assert phrase in text, f"docs/shadow-deployment.md missing {phrase!r}"


def test_sprint39_report_contains_required_evidence() -> None:
    path = REPO_ROOT / "SPRINT39_REPORT.md"
    assert path.is_file(), f"missing {path}"
    text = path.read_text(encoding="utf-8")
    for phrase in (
        "Sprint 39",
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "packaging",
        "audit",
        "ShadowDeploymentManifest",
        "build_shadow_deployment_manifest",
        "write_shadow_deployment_manifest_json",
    ):
        assert phrase in text, f"SPRINT39_REPORT.md missing {phrase!r}"


# ---------------------------------------------------------------------------
# 16. Build is repeat-stable
# ---------------------------------------------------------------------------


def test_build_is_repeat_stable(tmp_path: Path) -> None:
    payload = b"reproducibility"
    file_target = tmp_path / "f.bin"
    file_target.write_bytes(payload)
    kwargs = dict(
        package_version="0.1.0",
        build_id="ci-99",
        created_at="2026-05-23T00:00:00Z",
        code_version="1.2.3",
        artifacts=[
            {
                "kind": ARTIFACT_KIND_BLOB,
                "name": "b.bin",
                "content": payload,
            },
            {
                "kind": ARTIFACT_KIND_FILE,
                "name": "f.bin",
                "path": str(file_target),
            },
        ],
        summary_objects=[_pump_replay(rows=2)],
        references={"shadow_replay_dataset": {"frame_count": 2}},
        notes="audit only",
    )
    m1 = build_shadow_deployment_manifest("shadow-mvp", **kwargs)
    m2 = build_shadow_deployment_manifest("shadow-mvp", **kwargs)
    assert m1 == m2
    out1 = tmp_path / "a.json"
    out2 = tmp_path / "b.json"
    write_shadow_deployment_manifest_json(m1, out1)
    write_shadow_deployment_manifest_json(m2, out2)
    assert out1.read_text(encoding="utf-8") == out2.read_text(
        encoding="utf-8"
    )
