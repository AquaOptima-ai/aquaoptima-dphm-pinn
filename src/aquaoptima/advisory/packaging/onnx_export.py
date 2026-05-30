"""ONNX exporter + scoring wrapper for the Pillar-A health detector.

The exporter wraps a frozen :class:`FittedHealthDetector` into a portable ONNX
inference artifact for the AMAX CPU-only edge profile:

* The ONNX graph carries the autoencoder's forward pass (n_axes -> hidden ->
  latent -> hidden -> n_axes). Input shape is ``[batch, n_axes]`` with a
  dynamic batch axis; dtype is float32.
* A JSON sidecar carries every constant that lives OUTSIDE the graph but is
  required to reproduce :meth:`FittedHealthDetector.score`:

    - the axis order;
    - per-axis ``mu`` / ``sigma`` (standardisation);
    - the score denominator (``val_error_p995``, fallback
      ``train_error_p995``);
    - the binary flag threshold (``flag_threshold_error``);
    - architecture, parameter count, opset, sha256 of the .onnx bytes for
      audit cross-reference.

``score_with_onnx`` then reproduces ``detector_recon_error /
detector_anomaly_score / detector_flag`` purely via onnxruntime + numpy
(no torch dependency at inference time).

Hard boundary
-------------
* Offline only. No write-capable connector imports.
* The exporter mutates nothing on the input detector and never imports the edge
  SDK or any actuation surface.
* This module returns dataclasses + writes files locally. It does NOT push to a
  registry, hit the network, or interact with site infrastructure.
"""

from __future__ import annotations

import hashlib
import io
import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import numpy as np
import pandas as pd

# torch + FittedHealthDetector are only needed by the exporter side and the
# Sprint-35 sidecar builder. The runtime container scores with onnxruntime
# alone; we keep these imports lazy so the scoring path stays torch-free
# (Sprint-36 Linux image is CPU + onnxruntime only).
if TYPE_CHECKING:  # pragma: no cover - type-checking hint only
    from ..health_detector import FittedHealthDetector

# Opset 17 is widely supported by onnxruntime CPU 1.17+. The torch dynamo
# exporter may auto-upgrade to a newer opset; we record the actual opset in
# the sidecar so the audit trail does not lie.
DEFAULT_OPSET = 17


@dataclass(frozen=True)
class OnnxHealthDetectorSidecar:
    """Sidecar payload the ONNX runtime needs to reproduce ``.score()``.

    Everything outside the autoencoder graph: axis order, standardisation
    constants, the score denominator, the binary flag threshold, plus enough
    audit metadata (architecture, parameter count, requested + effective opset,
    sha256 of the .onnx bytes) for cross-referencing the manifest.
    """

    axes: tuple[str, ...]
    mu: tuple[float, ...]
    sigma: tuple[float, ...]
    val_error_p995: float
    train_error_p995: float
    flag_threshold_error: float
    architecture: Mapping[str, Any]
    parameter_count: int
    opset_version: int
    onnx_sha256: str
    onnx_size_bytes: int
    onnx_filename: str
    dynamic_batch: bool = True
    input_name: str = "x"
    output_name: str = "recon"
    framework: str = "onnx"

    def to_dict(self) -> dict[str, Any]:
        return {
            "axes": list(self.axes),
            "mu": list(self.mu),
            "sigma": list(self.sigma),
            "val_error_p995": float(self.val_error_p995),
            "train_error_p995": float(self.train_error_p995),
            "flag_threshold_error": float(self.flag_threshold_error),
            "architecture": dict(self.architecture),
            "parameter_count": int(self.parameter_count),
            "opset_version": int(self.opset_version),
            "onnx_sha256": str(self.onnx_sha256),
            "onnx_size_bytes": int(self.onnx_size_bytes),
            "onnx_filename": str(self.onnx_filename),
            "dynamic_batch": bool(self.dynamic_batch),
            "input_name": str(self.input_name),
            "output_name": str(self.output_name),
            "framework": str(self.framework),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OnnxHealthDetectorSidecar":
        return cls(
            axes=tuple(str(a) for a in data["axes"]),
            mu=tuple(float(v) for v in data["mu"]),
            sigma=tuple(float(v) for v in data["sigma"]),
            val_error_p995=float(data["val_error_p995"]),
            train_error_p995=float(data["train_error_p995"]),
            flag_threshold_error=float(data["flag_threshold_error"]),
            architecture=dict(data.get("architecture", {})),
            parameter_count=int(data.get("parameter_count", 0)),
            opset_version=int(data.get("opset_version", DEFAULT_OPSET)),
            onnx_sha256=str(data.get("onnx_sha256", "")),
            onnx_size_bytes=int(data.get("onnx_size_bytes", 0)),
            onnx_filename=str(data.get("onnx_filename", "")),
            dynamic_batch=bool(data.get("dynamic_batch", True)),
            input_name=str(data.get("input_name", "x")),
            output_name=str(data.get("output_name", "recon")),
            framework=str(data.get("framework", "onnx")),
        )


@dataclass(frozen=True)
class OnnxScoringResult:
    """Per-row score outputs the ONNX wrapper reproduces from ``.score()``."""

    detector_recon_error: np.ndarray
    detector_anomaly_score: np.ndarray
    detector_flag: np.ndarray

    def to_frame(self, index: pd.Index | None = None) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "detector_recon_error": self.detector_recon_error,
                "detector_anomaly_score": self.detector_anomaly_score,
                "detector_flag": self.detector_flag,
            },
            index=index,
        )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _parameter_count(detector: "FittedHealthDetector") -> int:
    """Compute the autoencoder's total parameter count from the state_dict."""
    total = 0
    for tensor in detector.state_dict.values():
        total += int(tensor.numel())
    return total


def _sha256_of(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _standardise(
    X: np.ndarray, mu: np.ndarray, sigma: np.ndarray
) -> np.ndarray:
    """Mirror of ``health_detector._standardise`` so the wrapper has no torch dep."""
    sigma_safe = np.where(sigma > 0, sigma, 1.0)
    return (X - mu) / sigma_safe


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
def export_health_detector_to_onnx(
    detector: "FittedHealthDetector",
    onnx_path: Path | str,
    *,
    sidecar_path: Path | str | None = None,
    opset_version: int = DEFAULT_OPSET,
) -> OnnxHealthDetectorSidecar:
    """Export ``detector``'s autoencoder forward pass to ONNX + write a sidecar.

    Parameters
    ----------
    detector
        A frozen :class:`FittedHealthDetector` whose ``state_dict`` will be
        loaded into a fresh :class:`HealthAutoencoder` for export. The
        autoencoder is built from the detector's own ``axes``, ``hidden_dim``,
        ``latent_dim``, and ``seed``.
    onnx_path
        Destination path for the ``.onnx`` file. Parent directories are
        created on demand.
    sidecar_path
        Optional explicit path for the sidecar JSON. Defaults to the
        ``.onnx`` path with the suffix swapped to ``.sidecar.json``.
    opset_version
        Requested ONNX opset. The torch exporter may auto-upgrade to a newer
        opset for compatibility; the sidecar records the effective opset.

    Returns
    -------
    OnnxHealthDetectorSidecar
        The sidecar payload that was just written to disk.
    """

    # Lazy-import torch so the scoring-only runtime image does not need it.
    import torch  # noqa: F401

    onnx_path = Path(onnx_path)
    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    if sidecar_path is None:
        sidecar_path = onnx_path.with_suffix(".sidecar.json")
    else:
        sidecar_path = Path(sidecar_path)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)

    model = detector._build_model()
    model.eval()
    n_axes = len(detector.axes)
    example = torch.zeros(1, n_axes, dtype=torch.float32)

    buf = io.BytesIO()
    # Silence the dynamo / version-conversion / deprecation chatter. Whatever
    # opset the exporter actually emits is captured below and recorded in the
    # sidecar so the audit trail does not lie.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        torch.onnx.export(
            model,
            (example,),
            buf,
            input_names=["x"],
            output_names=["recon"],
            dynamic_axes={"x": {0: "batch"}, "recon": {0: "batch"}},
            opset_version=int(opset_version),
        )
    onnx_bytes = buf.getvalue()
    onnx_path.write_bytes(onnx_bytes)

    effective_opset = _infer_opset_from_bytes(onnx_bytes, fallback=opset_version)

    architecture = {
        "n_axes": n_axes,
        "hidden_dim": int(detector.hidden_dim),
        "latent_dim": int(detector.latent_dim),
        "activation": "tanh",
        "layout": "n_axes -> hidden -> latent -> hidden -> n_axes",
    }

    sidecar = OnnxHealthDetectorSidecar(
        axes=tuple(detector.axes),
        mu=tuple(float(v) for v in detector.mu),
        sigma=tuple(float(v) for v in detector.sigma),
        val_error_p995=float(detector.val_error_p995),
        train_error_p995=float(detector.train_error_p995),
        flag_threshold_error=float(detector.flag_threshold_error),
        architecture=architecture,
        parameter_count=_parameter_count(detector),
        opset_version=int(effective_opset),
        onnx_sha256=_sha256_of(onnx_bytes),
        onnx_size_bytes=len(onnx_bytes),
        onnx_filename=onnx_path.name,
        dynamic_batch=True,
        input_name="x",
        output_name="recon",
        framework="onnx",
    )
    sidecar_path.write_text(
        json.dumps(sidecar.to_dict(), sort_keys=True, indent=2)
    )
    return sidecar


def _infer_opset_from_bytes(onnx_bytes: bytes, *, fallback: int) -> int:
    """Read the model's actual opset_import[0].version for audit accuracy."""
    try:
        import onnx  # local import keeps the module importable without onnx

        proto = onnx.load_model_from_string(onnx_bytes)
        for imp in proto.opset_import:
            if not imp.domain or imp.domain == "ai.onnx":
                return int(imp.version)
    except Exception:
        pass
    return int(fallback)


def build_health_detector_sidecar(
    detector: "FittedHealthDetector",
    *,
    onnx_sha256: str,
    onnx_size_bytes: int,
    onnx_filename: str,
    opset_version: int = DEFAULT_OPSET,
) -> OnnxHealthDetectorSidecar:
    """Pure-data sidecar builder for callers that already have ``.onnx`` bytes."""
    architecture = {
        "n_axes": len(detector.axes),
        "hidden_dim": int(detector.hidden_dim),
        "latent_dim": int(detector.latent_dim),
        "activation": "tanh",
        "layout": "n_axes -> hidden -> latent -> hidden -> n_axes",
    }
    return OnnxHealthDetectorSidecar(
        axes=tuple(detector.axes),
        mu=tuple(float(v) for v in detector.mu),
        sigma=tuple(float(v) for v in detector.sigma),
        val_error_p995=float(detector.val_error_p995),
        train_error_p995=float(detector.train_error_p995),
        flag_threshold_error=float(detector.flag_threshold_error),
        architecture=architecture,
        parameter_count=_parameter_count(detector),
        opset_version=int(opset_version),
        onnx_sha256=str(onnx_sha256),
        onnx_size_bytes=int(onnx_size_bytes),
        onnx_filename=str(onnx_filename),
    )


# --------------------------------------------------------------------------- #
# scoring (torch-free at inference time)
# --------------------------------------------------------------------------- #
def _load_session(onnx_path: Path | str):
    import onnxruntime as ort  # local import keeps module import cheap

    sess_options = ort.SessionOptions()
    sess_options.intra_op_num_threads = 1
    sess_options.inter_op_num_threads = 1
    return ort.InferenceSession(
        str(onnx_path),
        sess_options=sess_options,
        providers=["CPUExecutionProvider"],
    )


def _load_sidecar(sidecar_path: Path | str) -> OnnxHealthDetectorSidecar:
    payload = json.loads(Path(sidecar_path).read_text())
    return OnnxHealthDetectorSidecar.from_dict(payload)


def score_with_onnx(
    frames: pd.DataFrame,
    onnx_path: Path | str,
    sidecar_path: Path | str,
) -> OnnxScoringResult:
    """Reproduce ``FittedHealthDetector.score`` purely with onnxruntime + numpy.

    Pipeline:
    1. Pull the standardised axis vector from ``frames`` in the sidecar's order.
    2. Standardise with ``(mu, sigma)`` from the sidecar (NaN/inf rows raise).
    3. Run the ONNX graph on CPU to get the reconstruction.
    4. Per-row MSE over the standardised axes -> ``detector_recon_error``.
    5. Normalise by ``val_error_p995`` (fallback ``train_error_p995``) clipped
       to ``[0, 1]`` -> ``detector_anomaly_score``.
    6. Binary flag = ``(err >= flag_threshold_error)``.
    """
    sidecar = _load_sidecar(sidecar_path)
    axes = list(sidecar.axes)
    missing = [a for a in axes if a not in frames.columns]
    if missing:
        raise KeyError(f"frames missing required axes: {missing}")

    X = frames[axes].to_numpy(dtype=np.float64)
    mu = np.asarray(sidecar.mu, dtype=np.float64)
    sigma = np.asarray(sidecar.sigma, dtype=np.float64)
    Z = _standardise(X, mu, sigma).astype(np.float32)

    sess = _load_session(onnx_path)
    out = sess.run([sidecar.output_name], {sidecar.input_name: Z})[0]
    err = np.mean((Z - out) ** 2, axis=1).astype(np.float64)

    denom = sidecar.val_error_p995 if sidecar.val_error_p995 > 0 else sidecar.train_error_p995
    denom = denom if denom > 0 else 1.0
    norm = np.clip(err / denom, 0.0, 1.0)
    flag = (err >= sidecar.flag_threshold_error).astype(int)
    return OnnxScoringResult(
        detector_recon_error=err,
        detector_anomaly_score=norm,
        detector_flag=flag,
    )


def score_axes_with_onnx(
    Z_standardised: np.ndarray,
    onnx_path: Path | str,
    sidecar_path: Path | str,
) -> OnnxScoringResult:
    """Variant of :func:`score_with_onnx` that takes a pre-standardised matrix.

    Useful for latency timing / unit tests that want to skip pandas. ``Z`` must
    be ``[n_rows, n_axes]`` float32 in the sidecar's axis order.
    """
    sidecar = _load_sidecar(sidecar_path)
    if Z_standardised.ndim != 2 or Z_standardised.shape[1] != len(sidecar.axes):
        raise ValueError(
            f"Z_standardised must be [n_rows, {len(sidecar.axes)}]; got "
            f"{Z_standardised.shape}"
        )
    sess = _load_session(onnx_path)
    Z = Z_standardised.astype(np.float32, copy=False)
    out = sess.run([sidecar.output_name], {sidecar.input_name: Z})[0]
    err = np.mean((Z - out) ** 2, axis=1).astype(np.float64)
    denom = sidecar.val_error_p995 if sidecar.val_error_p995 > 0 else sidecar.train_error_p995
    denom = denom if denom > 0 else 1.0
    norm = np.clip(err / denom, 0.0, 1.0)
    flag = (err >= sidecar.flag_threshold_error).astype(int)
    return OnnxScoringResult(
        detector_recon_error=err,
        detector_anomaly_score=norm,
        detector_flag=flag,
    )


def standardise_frames(
    frames: pd.DataFrame, sidecar: OnnxHealthDetectorSidecar
) -> np.ndarray:
    """Public helper: produce the float32 standardised matrix the ONNX graph wants."""
    axes = list(sidecar.axes)
    missing = [a for a in axes if a not in frames.columns]
    if missing:
        raise KeyError(f"frames missing required axes: {missing}")
    X = frames[axes].to_numpy(dtype=np.float64)
    mu = np.asarray(sidecar.mu, dtype=np.float64)
    sigma = np.asarray(sidecar.sigma, dtype=np.float64)
    Z = _standardise(X, mu, sigma).astype(np.float32)
    return Z


__all__ = [
    "DEFAULT_OPSET",
    "OnnxHealthDetectorSidecar",
    "OnnxScoringResult",
    "build_health_detector_sidecar",
    "export_health_detector_to_onnx",
    "score_axes_with_onnx",
    "score_with_onnx",
    "standardise_frames",
]
