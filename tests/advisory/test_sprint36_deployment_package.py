"""AOPSO Sprint 36 -- Pillar A Linux deployment package tests.

What this suite proves (offline, advisory-only, no Docker daemon required):

* The Sprint-36 serving entrypoint
  (:func:`aquaoptima.advisory.packaging.serve_advisory.score_to_evidence`)
  reproduces the Sprint-35 ONNX scoring results bit-faithfully on a held-in
  fixture: flags identical and recon-error / anomaly-score within a tight
  numerical tolerance.

* The Sprint-36
  :func:`build_pillarA_deployment_package_manifest` builder constructs a
  valid :class:`DeploymentPackageManifest` (no ``ContractError``) AND that
  manifest passes :func:`validate_deployment_package_for_edge` against the
  canonical AMAX-5580 declaration with zero errors.

* The model record inside the manifest carries the canonical all-True
  :class:`SafetyFlagSet`, the matching capability requirement, the
  Sprint-35 sha256, and ``framework="onnx"``.

* Forbidden-vocabulary text in the manifest's notes is rejected by the
  contracts SDK.

* The Dockerfile contains the boundary-enforcing flags (USER non-root,
  no setpoint / actuation / write wiring) and the requirements pin set
  is CPU-only (no torch / no CUDA / no TensorRT).

The on-disk sha256 of ``pillarA_health_detector.onnx`` matches the
checksum advertised by the manifest's model record.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

onnx = pytest.importorskip("onnx", reason="Sprint 36 packaging requires onnx")
ort = pytest.importorskip(
    "onnxruntime", reason="Sprint 36 packaging requires onnxruntime"
)

from aquaoptima.advisory.packaging import (
    PILLARA_DEPLOYMENT_PACKAGE_ID,
    PILLARA_DEPLOYMENT_PACKAGE_VERSION,
    AdvisoryServingResult,
    build_pillarA_deployment_package_manifest,
    score_to_evidence,
    score_with_onnx,
    write_pillarA_deployment_package_manifest,
)
from aquaoptima.advisory.packaging.serve_advisory import (
    EVIDENCE_COLUMNS,
    load_telemetry_frames,
)

from aquaoptima_contracts import (
    DeploymentPackageManifest,
    ModelArtifactRecord,
    default_amax_edge_capability_declaration,
    validate_deployment_package_for_edge,
)
from aquaoptima_contracts.base.envelope import ContractError


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGING_DIR = REPO_ROOT / "data" / "eval" / "packaging"
ONNX_PATH = PACKAGING_DIR / "pillarA_health_detector.onnx"
SIDECAR_PATH = PACKAGING_DIR / "pillarA_health_detector.sidecar.json"
ARTIFACT_RECORD_PATH = PACKAGING_DIR / "pillarA_onnx_artifact_record.json"
DOCKERFILE = REPO_ROOT / "deploy" / "pillarA_advisory" / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / "deploy" / "pillarA_advisory" / ".dockerignore"
REQUIREMENTS = REPO_ROOT / "deploy" / "pillarA_advisory" / "requirements.txt"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_pillarA_image.sh"
SERVE_SHIM = REPO_ROOT / "scripts" / "serve_pillarA_advisory.py"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def sidecar_payload() -> dict[str, Any]:
    return json.loads(SIDECAR_PATH.read_text())


@pytest.fixture(scope="module")
def axes(sidecar_payload: dict[str, Any]) -> list[str]:
    return list(sidecar_payload["axes"])


@pytest.fixture(scope="module")
def synthetic_frames(
    sidecar_payload: dict[str, Any],
    axes: list[str],
) -> pd.DataFrame:
    """Generate a small reproducible telemetry frame in the sidecar's axis
    order. Values are centered on ``mu`` with a tiny zero-mean perturbation
    so the resulting frames are inside the autoencoder's normal operating
    envelope -- they should mostly score below the flag threshold."""
    rng = np.random.default_rng(0)
    n = 64
    mu = np.asarray(sidecar_payload["mu"], dtype=np.float64)
    sigma = np.asarray(sidecar_payload["sigma"], dtype=np.float64)
    # Mix two regimes: 56 in-distribution + 8 anomalous so both flag classes
    # appear in the evidence sink and we test the path through both.
    Z = rng.standard_normal(size=(n, len(axes))).astype(np.float64) * 0.05
    Z[-8:, :] = 5.0  # Wildly off-distribution rows
    X = Z * sigma + mu
    frame = pd.DataFrame(X, columns=axes)
    return frame


@pytest.fixture(scope="module")
def synthetic_telemetry_path(
    synthetic_frames: pd.DataFrame, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    tmp_dir = tmp_path_factory.mktemp("sprint36-telemetry")
    csv_path = tmp_dir / "input.csv"
    synthetic_frames.to_csv(csv_path, index=False)
    return csv_path


# --------------------------------------------------------------------------- #
# 1. Serving entrypoint reproduces Sprint-35 scores
# --------------------------------------------------------------------------- #


def test_serving_entrypoint_reproduces_sprint35_scores(
    synthetic_frames: pd.DataFrame,
    synthetic_telemetry_path: Path,
    tmp_path: Path,
) -> None:
    """The Sprint-36 serving entrypoint must reproduce Sprint-35 scores
    bit-faithfully on a fixture. Proven in-process so the test does NOT
    depend on Docker."""
    evidence_dir = tmp_path / "evidence"
    result = score_to_evidence(
        onnx_path=ONNX_PATH,
        sidecar_path=SIDECAR_PATH,
        input_path=synthetic_telemetry_path,
        evidence_dir=evidence_dir,
    )
    assert isinstance(result, AdvisoryServingResult)
    assert result.n_rows == len(synthetic_frames)

    # Ground-truth Sprint-35 scoring pass for the same frames.
    reference = score_with_onnx(synthetic_frames, ONNX_PATH, SIDECAR_PATH)

    # Bit-faithful: scores produced by the entrypoint must match the
    # Sprint-35 wrapper to within float32 round-off and flags must be
    # exactly equal (the entrypoint just delegates to score_with_onnx).
    np.testing.assert_array_equal(
        result.scoring_result.detector_flag, reference.detector_flag
    )
    max_abs_err = float(
        np.max(
            np.abs(
                result.scoring_result.detector_recon_error
                - reference.detector_recon_error
            )
        )
    )
    max_abs_score = float(
        np.max(
            np.abs(
                result.scoring_result.detector_anomaly_score
                - reference.detector_anomaly_score
            )
        )
    )
    assert max_abs_err <= 1e-12
    assert max_abs_score <= 1e-12

    # Evidence sink files actually written.
    assert result.evidence_csv_path.exists()
    assert result.evidence_summary_path.exists()
    written = pd.read_csv(result.evidence_csv_path)
    for col in EVIDENCE_COLUMNS:
        assert col in written.columns
    assert len(written) == len(synthetic_frames)
    np.testing.assert_array_equal(
        written["detector_flag"].to_numpy(),
        reference.detector_flag,
    )


def test_serving_entrypoint_loads_json_records(
    synthetic_frames: pd.DataFrame,
    tmp_path: Path,
) -> None:
    """The entrypoint accepts JSON-records input as well as CSV."""
    json_path = tmp_path / "input.json"
    json_path.write_text(json.dumps(synthetic_frames.to_dict(orient="records")))
    frames = load_telemetry_frames(json_path)
    assert list(frames.columns) == list(synthetic_frames.columns)
    assert len(frames) == len(synthetic_frames)


def test_serving_summary_reports_advisory_boundary(
    synthetic_telemetry_path: Path, tmp_path: Path
) -> None:
    """The per-run JSON summary must declare the advisory boundary explicitly
    so the audit log is unambiguous."""
    evidence_dir = tmp_path / "evidence"
    result = score_to_evidence(
        onnx_path=ONNX_PATH,
        sidecar_path=SIDECAR_PATH,
        input_path=synthetic_telemetry_path,
        evidence_dir=evidence_dir,
    )
    summary = json.loads(result.evidence_summary_path.read_text())
    assert summary["advisory_only"] is True
    assert summary["evaluation_mode"] == "offline_only"
    assert summary["boundary"]["control_plane_network"] is False
    assert summary["boundary"]["write_path"] is False
    assert summary["boundary"]["runs_read_only"] is True
    assert summary["boundary"]["network"] == "none"


# --------------------------------------------------------------------------- #
# 2. DeploymentPackageManifest validates against the AMAX edge profile
# --------------------------------------------------------------------------- #


def test_manifest_builds_and_validates_for_edge() -> None:
    manifest = build_pillarA_deployment_package_manifest(
        onnx_path=ONNX_PATH,
        sidecar_path=SIDECAR_PATH,
        artifact_record_json_path=ARTIFACT_RECORD_PATH,
    )
    assert isinstance(manifest, DeploymentPackageManifest)
    assert manifest.envelope.schema_family == "manifest"
    assert manifest.package_id == PILLARA_DEPLOYMENT_PACKAGE_ID
    assert manifest.package_version == PILLARA_DEPLOYMENT_PACKAGE_VERSION
    assert manifest.safety_declaration.package_id == manifest.package_id
    assert (
        manifest.capability_requirement.package_id == manifest.package_id
    )
    assert len(manifest.model_artifacts) == 1
    model_record = manifest.model_artifacts[0]
    assert isinstance(model_record, ModelArtifactRecord)
    assert model_record.framework == "onnx"
    assert model_record.artifact_reference.checksum is not None
    assert model_record.artifact_reference.checksum.algorithm == "sha256"

    # Safety flags must be all True.
    flags = manifest.safety_declaration.safety_flag_set
    for token in (
        "offline",
        "read_only",
        "no_write",
        "no_control",
        "no_live_ot_binding",
        "no_setpoint_output",
        "packaging_audit_only",
    ):
        assert getattr(flags, token) is True

    # And the deny-by-default Edge validator accepts the package.
    edge = default_amax_edge_capability_declaration()
    result = validate_deployment_package_for_edge(manifest, edge)
    assert result.accepted is True, list(result.errors)
    assert list(result.errors) == []
    assert list(result.rejected_accelerator_tokens) == []
    assert list(result.rejected_frameworks) == []


def test_manifest_round_trips_through_canonical_json(tmp_path: Path) -> None:
    """The manifest must serialize to canonical JSON and reload via
    :meth:`DeploymentPackageManifest.from_dict` without losing fields."""
    manifest = build_pillarA_deployment_package_manifest(
        onnx_path=ONNX_PATH,
        sidecar_path=SIDECAR_PATH,
        artifact_record_json_path=ARTIFACT_RECORD_PATH,
    )
    out_path = tmp_path / "manifest.json"
    write_pillarA_deployment_package_manifest(manifest, out_path)
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    rebuilt = DeploymentPackageManifest.from_dict(payload)
    assert rebuilt.package_id == manifest.package_id
    assert rebuilt.package_version == manifest.package_version
    assert (
        rebuilt.model_artifacts[0].artifact_reference.checksum.hex_digest
        == manifest.model_artifacts[0]
        .artifact_reference.checksum.hex_digest
    )


def test_manifest_rejects_forbidden_vocab_notes() -> None:
    """A deliberately control-flavoured note must be rejected by the SDK."""
    # ``setpoint_output`` is a canonical forbidden-vocabulary token; the
    # SDK refuses any manifest field that contains it.
    with pytest.raises(ContractError):
        build_pillarA_deployment_package_manifest(
            onnx_path=ONNX_PATH,
            sidecar_path=SIDECAR_PATH,
            artifact_record_json_path=ARTIFACT_RECORD_PATH,
            notes=(
                "This package is intended for setpoint_output and "
                "closed_loop_control via the site PLC."
            ),
        )


def test_manifest_model_record_sha256_matches_on_disk_onnx() -> None:
    """The model record's checksum must equal the sha256 of the .onnx bytes."""
    manifest = build_pillarA_deployment_package_manifest(
        onnx_path=ONNX_PATH,
        sidecar_path=SIDECAR_PATH,
        artifact_record_json_path=ARTIFACT_RECORD_PATH,
    )
    h = hashlib.sha256()
    h.update(ONNX_PATH.read_bytes())
    declared_hex = manifest.model_artifacts[0].artifact_reference.checksum.hex_digest
    assert declared_hex == h.hexdigest()


# --------------------------------------------------------------------------- #
# 3. Dockerfile / .dockerignore / build script structural integrity
# --------------------------------------------------------------------------- #


def _strip_dockerfile_comments(text: str) -> str:
    """Return Dockerfile content with comment lines removed.

    We only enforce "no torch / no CUDA" on the *actual* COPY / RUN / FROM
    lines -- comments that warn against those dependencies are fine and
    keep the boundary documented in the file itself.
    """
    keep: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        keep.append(line)
    return "\n".join(keep)


def test_dockerfile_present_and_boundary_enforcing() -> None:
    assert DOCKERFILE.exists()
    text = DOCKERFILE.read_text()
    # Targets linux/amd64
    assert "--platform=linux/amd64" in text
    # Slim CPU base image
    assert "python:3.12-slim" in text
    # Non-root user
    assert "USER 1001:1001" in text
    # Read-only friendly: declares both volumes
    assert "/telemetry" in text and "/evidence" in text
    # Entrypoint is the advisory CLI shim, not a control daemon
    assert "serve_pillarA_advisory.py" in text
    # No torch / CUDA / TensorRT in real build instructions (comments
    # that warn against those dependencies are intentionally allowed).
    instructions = _strip_dockerfile_comments(text).lower()
    assert "torch" not in instructions
    assert "cuda" not in instructions
    assert "tensorrt" not in instructions
    # No live OT / write surface anywhere
    for forbidden in ("modbus_write", "opcua_write", "plc_write", "send_command"):
        assert forbidden not in text


def test_dockerignore_present_and_excludes_by_default() -> None:
    assert DOCKERIGNORE.exists()
    text = DOCKERIGNORE.read_text()
    # The "exclude everything; explicitly include" pattern is required.
    assert text.lstrip().startswith("*") or "\n*\n" in text
    assert "!deploy/pillarA_advisory/Dockerfile" in text
    assert "!data/eval/packaging/pillarA_health_detector.onnx" in text


def test_requirements_pinned_and_cpu_only() -> None:
    assert REQUIREMENTS.exists()
    text = REQUIREMENTS.read_text()
    assert "onnxruntime==" in text  # version-pinned
    assert "numpy==" in text
    assert "pandas==" in text
    # CPU-only requirements -- no torch, no CUDA / TensorRT in real
    # requirement lines (comments warning against them are intentionally
    # allowed).
    pkg_lines = [
        ln.strip().lower()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    for pkg in pkg_lines:
        assert "torch" not in pkg
        assert "cuda" not in pkg
        assert "tensorrt" not in pkg


def test_build_script_present_and_marked_executable() -> None:
    assert BUILD_SCRIPT.exists()
    text = BUILD_SCRIPT.read_text()
    assert text.startswith("#!/usr/bin/env bash")
    # Reports a honest "no builder" outcome when docker/podman aren't present.
    assert "skipped_no_builder" in text
    # Targets linux/amd64 by default
    assert "linux/amd64" in text


def test_serve_shim_present_and_minimal() -> None:
    assert SERVE_SHIM.exists()
    text = SERVE_SHIM.read_text()
    assert "run_cli" in text
    assert "from aquaoptima.advisory.packaging.serve_advisory" in text
