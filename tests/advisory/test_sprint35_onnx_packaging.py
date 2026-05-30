"""AOPSO Sprint 35 -- Pillar A ONNX packaging tests.

What we prove here (offline, advisory-only, no live wiring):

* the ONNX exporter round-trips through onnxruntime CPU;
* the ONNX wrapper reproduces ``FittedHealthDetector.score`` within a tight
  tolerance (recon-error max-abs-diff <= 1e-5 AND flags identical);
* the sidecar's ``sha256`` matches the bytes actually on disk;
* the ``ModelArtifactRecord`` built via :func:`build_health_artifact_record`
  validates with ``framework="onnx"`` and the canonical all-True
  :class:`SafetyFlagSet`;
* swapping in a bad framework / dropping the checksum / corrupting the safety
  flag set each raise ``ContractError``;
* the governance scanner finds no forbidden edge / write-capable token
  anywhere in the packaging subpackage.

Tests skip cleanly (with an honest reason) if ``onnx`` / ``onnxruntime`` are
not importable, but the Sprint 35 acceptance gate REQUIRES them present.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

onnx = pytest.importorskip("onnx", reason="Sprint 35 packaging requires onnx")
ort = pytest.importorskip(
    "onnxruntime", reason="Sprint 35 packaging requires onnxruntime"
)

from aquaoptima.advisory.governance import (
    scan_modeling_source_for_governance_violations,
)
from aquaoptima.advisory.health_artifact_schema import (
    build_health_artifact_record,
)
from aquaoptima.advisory.health_detector import (
    DEFAULT_HIDDEN_DIM,
    DEFAULT_LATENT_DIM,
    fit_health_detector,
)
from aquaoptima.advisory.packaging import (
    DEFAULT_OPSET,
    OnnxHealthDetectorSidecar,
    export_health_detector_to_onnx,
    score_with_onnx,
)
from aquaoptima.advisory.packaging.onnx_export import (
    standardise_frames,
    score_axes_with_onnx,
)

# The contracts SDK validation raises ContractError on bad input -- we use it
# to prove the safety wrapper is real, not for any control behaviour.
from aquaoptima_contracts import (
    ArtifactReference,
    CapabilityRequirement,
    Checksum,
    ModelArtifactRecord,
    Provenance,
    SDK_VERSION,
)
from aquaoptima_contracts.base.envelope import ContractError
from aquaoptima_contracts.safety.flags import (
    SafetyFlagError,
    SafetyFlagSet,
    default_safety_flag_set,
)


TEST_AXES = ("edge_flow", "edge_power", "edge_pump_speed", "node_pressure")


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _synthetic_2025_normal(n_rows: int = 600, seed: int = 17) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    flow = rng.normal(loc=1500.0, scale=80.0, size=n_rows)
    speed = rng.normal(loc=42.0, scale=1.5, size=n_rows)
    power = 0.05 * flow + 1.5 * speed + rng.normal(0.0, 2.0, size=n_rows)
    pressure = rng.normal(loc=18.0, scale=0.5, size=n_rows)
    ts = pd.date_range(
        "2025-07-01 00:00:00", periods=n_rows, freq="1min"
    ).strftime("%Y-%m-%d %H:%M:%S")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "edge_flow": flow,
            "edge_power": power,
            "edge_pump_speed": speed,
            "node_pressure": pressure,
        }
    )


@pytest.fixture(scope="module")
def normal_frames() -> pd.DataFrame:
    return _synthetic_2025_normal()


@pytest.fixture(scope="module")
def fitted_detector(normal_frames):
    return fit_health_detector(
        normal_frames,
        axes=list(TEST_AXES),
        seed=0,
        epochs=20,
        batch_size=128,
        hidden_dim=DEFAULT_HIDDEN_DIM,
        latent_dim=DEFAULT_LATENT_DIM,
    )


@pytest.fixture()
def exported(tmp_path, fitted_detector):
    onnx_path = tmp_path / "pillarA_health_detector.onnx"
    sidecar_path = tmp_path / "pillarA_health_detector.sidecar.json"
    sidecar = export_health_detector_to_onnx(
        fitted_detector, onnx_path, sidecar_path=sidecar_path
    )
    return {
        "onnx_path": onnx_path,
        "sidecar_path": sidecar_path,
        "sidecar": sidecar,
        "detector": fitted_detector,
    }


# --------------------------------------------------------------------------- #
# export round-trip
# --------------------------------------------------------------------------- #
def test_export_writes_onnx_and_sidecar(exported):
    onnx_path = exported["onnx_path"]
    sidecar_path = exported["sidecar_path"]
    assert onnx_path.exists() and onnx_path.stat().st_size > 0
    assert sidecar_path.exists() and sidecar_path.stat().st_size > 0
    proto = onnx.load(str(onnx_path))
    # Effective opset should be >= what we requested. The torch exporter is
    # allowed to upgrade to a newer opset for compatibility.
    declared = max(
        imp.version for imp in proto.opset_import if not imp.domain or imp.domain == "ai.onnx"
    )
    assert declared >= DEFAULT_OPSET


def test_sidecar_sha256_matches_onnx_bytes(exported):
    import hashlib

    onnx_path = exported["onnx_path"]
    sidecar = exported["sidecar"]
    h = hashlib.sha256()
    h.update(onnx_path.read_bytes())
    assert sidecar.onnx_sha256 == h.hexdigest()
    assert sidecar.onnx_size_bytes == onnx_path.stat().st_size


def test_sidecar_roundtrip_via_json(exported):
    raw = json.loads(exported["sidecar_path"].read_text())
    reloaded = OnnxHealthDetectorSidecar.from_dict(raw)
    sidecar = exported["sidecar"]
    assert reloaded.axes == sidecar.axes
    assert reloaded.mu == sidecar.mu
    assert reloaded.sigma == sidecar.sigma
    assert reloaded.val_error_p995 == pytest.approx(sidecar.val_error_p995)
    assert reloaded.flag_threshold_error == pytest.approx(
        sidecar.flag_threshold_error
    )
    assert reloaded.framework == "onnx"
    assert reloaded.dynamic_batch is True


def test_dynamic_batch_axis_works(exported):
    # Onnxruntime should accept multiple batch sizes for the same session.
    sess = ort.InferenceSession(
        str(exported["onnx_path"]),
        providers=["CPUExecutionProvider"],
    )
    for n in (1, 3, 19):
        x = np.random.RandomState(n).randn(n, len(TEST_AXES)).astype(np.float32)
        out = sess.run(None, {"x": x})[0]
        assert out.shape == (n, len(TEST_AXES))


# --------------------------------------------------------------------------- #
# parity
# --------------------------------------------------------------------------- #
def test_onnx_parity_matches_score_within_tolerance(
    exported, normal_frames, fitted_detector
):
    torch_scored = fitted_detector.score(normal_frames)
    onnx_scored = score_with_onnx(
        normal_frames, exported["onnx_path"], exported["sidecar_path"]
    )
    max_abs_recon_diff = float(
        np.max(
            np.abs(
                torch_scored["detector_recon_error"].to_numpy()
                - onnx_scored.detector_recon_error
            )
        )
    )
    assert max_abs_recon_diff <= 1e-5, (
        f"ONNX/Torch recon error parity exceeded 1e-5 tolerance: "
        f"max_abs_diff={max_abs_recon_diff:.3e}"
    )
    np.testing.assert_array_equal(
        torch_scored["detector_flag"].to_numpy(),
        onnx_scored.detector_flag,
    )
    score_diff = float(
        np.max(
            np.abs(
                torch_scored["detector_anomaly_score"].to_numpy()
                - onnx_scored.detector_anomaly_score
            )
        )
    )
    assert score_diff <= 1e-5


def test_score_axes_variant_matches_dataframe(
    exported, normal_frames, fitted_detector
):
    """Both ``score_with_onnx`` entry points should agree bit-equally."""
    Z = standardise_frames(normal_frames, exported["sidecar"])
    via_axes = score_axes_with_onnx(
        Z, exported["onnx_path"], exported["sidecar_path"]
    )
    via_frame = score_with_onnx(
        normal_frames, exported["onnx_path"], exported["sidecar_path"]
    )
    np.testing.assert_array_equal(
        via_axes.detector_recon_error, via_frame.detector_recon_error
    )
    np.testing.assert_array_equal(
        via_axes.detector_flag, via_frame.detector_flag
    )


# --------------------------------------------------------------------------- #
# ModelArtifactRecord validation
# --------------------------------------------------------------------------- #
def test_artifact_record_validates_with_onnx_framework(exported):
    sidecar = exported["sidecar"]
    record = build_health_artifact_record(
        model_id="pillarA-onnx-test",
        model_version="0.0.0-test",
        checksum_hex=sidecar.onnx_sha256,
        checksum_size_bytes=sidecar.onnx_size_bytes,
        parameter_count=sidecar.parameter_count,
        architecture="x86_64",
        summary_extra={
            "onnx_filename": sidecar.onnx_filename,
            "onnx_opset_version": int(sidecar.opset_version),
        },
    )
    assert record.framework == "onnx"
    assert record.safety_flag_set == default_safety_flag_set()
    # All-True safety flag set guarantee.
    flag_dict = record.safety_flag_set.to_dict()
    for k, v in flag_dict.items():
        if isinstance(v, bool):
            assert v is True, f"safety flag {k} not True"


def test_artifact_record_rejects_bad_framework(exported):
    sidecar = exported["sidecar"]
    checksum = Checksum(
        algorithm="sha256",
        hex_digest=sidecar.onnx_sha256,
        size_bytes=sidecar.onnx_size_bytes,
    )
    with pytest.raises(ContractError):
        ModelArtifactRecord(
            model_id="bad",
            model_version="0.0.0",
            framework="tensorflow",  # NOT in PACKAGE_MODEL_FRAMEWORKS
            artifact_reference=ArtifactReference(
                kind="model_weights",
                id="bad",
                version="0.0.0",
                checksum=checksum,
            ),
            provenance=Provenance(
                component="ai_server", version="0.1.0", build_id="unset"
            ),
            safety_flag_set=default_safety_flag_set(),
            capability_requirement=CapabilityRequirement(
                package_id="model-bad",
                required=frozenset(
                    {
                        "validate_manifest",
                        "validate_checksums",
                        "validate_safety_flags",
                    }
                ),
                sdk_version=SDK_VERSION,
            ),
            description="bad framework",
            summary={},
        )


def test_artifact_record_rejects_missing_checksum(exported):
    with pytest.raises(ContractError):
        ModelArtifactRecord(
            model_id="missing-checksum",
            model_version="0.0.0",
            framework="onnx",
            artifact_reference=ArtifactReference(
                kind="model_weights",
                id="missing-checksum",
                version="0.0.0",
                checksum=None,
            ),
            provenance=Provenance(
                component="ai_server", version="0.1.0", build_id="unset"
            ),
            safety_flag_set=default_safety_flag_set(),
            capability_requirement=CapabilityRequirement(
                package_id="model-missing",
                required=frozenset(
                    {
                        "validate_manifest",
                        "validate_checksums",
                        "validate_safety_flags",
                    }
                ),
                sdk_version=SDK_VERSION,
            ),
        )


def test_artifact_record_rejects_non_default_safety_flag_set(exported):
    # The contracts SDK refuses to construct a SafetyFlagSet that is not the
    # canonical all-True bundle. Flipping any single flag off must raise.
    with pytest.raises(SafetyFlagError):
        SafetyFlagSet(
            offline=True,
            read_only=True,
            no_write=False,
            no_control=True,
            no_live_ot_binding=True,
            no_setpoint_output=True,
            packaging_audit_only=True,
        )


# --------------------------------------------------------------------------- #
# governance: packaging code must not introduce forbidden imports/tokens
# --------------------------------------------------------------------------- #
def test_packaging_module_clean_of_forbidden_tokens():
    pkg_dir = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "aquaoptima"
        / "advisory"
        / "packaging"
    )
    assert pkg_dir.exists(), pkg_dir
    result = scan_modeling_source_for_governance_violations([pkg_dir])
    assert result.clean, f"governance violations: {result.violations}"
    assert result.files_scanned >= 2
