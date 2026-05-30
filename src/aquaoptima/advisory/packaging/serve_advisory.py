"""AOPSO Sprint 36 -- read-only, offline serving entrypoint for the Pillar-A
ONNX health detector.

This module is the *logic* that the Linux container image runs. It is a
batch-style scorer: read a telemetry frame (CSV or JSON-records) off disk,
score it through the Sprint-35 ONNX artifact + sidecar via
:func:`aquaoptima.advisory.packaging.score_with_onnx`, and write the resulting
health-flag evidence (CSV + JSON summary) to a configured evidence sink path.

Boundary -- non-negotiable
--------------------------
* Read-only. No mutation of model, sidecar, manifest, or input.
* Offline. No network, no HTTP client, no message broker, no historian
  client, no PLC / PAC / SCADA touchpoint. Nothing under
  :mod:`aquaoptima.edge` or :mod:`aquaoptima_contracts.edge` is imported.
* Advisory. The output is a per-row flag + score table; it is NOT a
  setpoint, command, dispatch, or actuation surface. The output schema
  is health evidence only.
* The container is designed to run with ``--read-only --network=none
  --user <non-root>``. Nothing here writes outside the evidence sink path
  the caller hands in.

The serving entrypoint is exercised in-process by the Sprint-36 test
suite to prove bit-faithful parity with the Sprint-35 ONNX scoring
wrapper -- so correctness is provable without a Docker daemon.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .onnx_export import (
    OnnxHealthDetectorSidecar,
    OnnxScoringResult,
    score_with_onnx,
)


# Output column order for evidence sinks. Deterministic so the audit
# trail is reproducible.
EVIDENCE_COLUMNS: tuple[str, ...] = (
    "detector_recon_error",
    "detector_anomaly_score",
    "detector_flag",
)


@dataclass(frozen=True)
class AdvisoryServingResult:
    """Outcome of a single read-only scoring run.

    Attributes
    ----------
    n_rows
        Number of telemetry rows scored.
    evidence_csv_path
        Where the per-row evidence CSV was written (always written).
    evidence_summary_path
        Where the per-run JSON summary was written (always written).
    sidecar
        The sidecar object loaded for the run. Kept here so callers can
        cross-reference axes / sha256 without re-reading the file.
    scoring_result
        The :class:`OnnxScoringResult` produced by :func:`score_with_onnx`.
        Kept for in-process parity checks in tests.
    """

    n_rows: int
    evidence_csv_path: Path
    evidence_summary_path: Path
    sidecar: OnnxHealthDetectorSidecar
    scoring_result: OnnxScoringResult


# --------------------------------------------------------------------------- #
# input loading
# --------------------------------------------------------------------------- #
def load_telemetry_frames(input_path: Path | str) -> pd.DataFrame:
    """Read a telemetry frame from disk in CSV or JSON-records form.

    The format is inferred from the suffix: ``.csv`` -> ``pd.read_csv``,
    ``.json`` / ``.jsonl`` / ``.ndjson`` -> JSON records (one row per
    object). Anything else raises ``ValueError``. No remote URI, no
    stdin, no network -- the path must be a local filesystem path.
    """
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"telemetry input not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in (".json", ".jsonl", ".ndjson"):
        if suffix == ".json":
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if not isinstance(payload, list):
                raise ValueError(
                    f"telemetry JSON at {path} must be a list of records"
                )
            return pd.DataFrame.from_records(payload)
        # jsonl / ndjson: one record per line
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                obj = json.loads(raw)
                if not isinstance(obj, dict):
                    raise ValueError(
                        f"telemetry record at {path}:{line_no} must be an object"
                    )
                records.append(obj)
        return pd.DataFrame.from_records(records)
    raise ValueError(
        f"unsupported telemetry input suffix {suffix!r} at {path}; "
        f"expected .csv / .json / .jsonl / .ndjson"
    )


# --------------------------------------------------------------------------- #
# evidence sink writing
# --------------------------------------------------------------------------- #
def _write_evidence_csv(
    evidence_dir: Path,
    frames: pd.DataFrame,
    result: OnnxScoringResult,
) -> Path:
    out = pd.DataFrame(
        {
            "row_index": np.arange(len(frames), dtype=np.int64),
            "detector_recon_error": result.detector_recon_error,
            "detector_anomaly_score": result.detector_anomaly_score,
            "detector_flag": result.detector_flag.astype(np.int64),
        }
    )
    csv_path = evidence_dir / "pillarA_advisory_evidence.csv"
    out.to_csv(csv_path, index=False)
    return csv_path


def _write_evidence_summary(
    evidence_dir: Path,
    sidecar: OnnxHealthDetectorSidecar,
    result: OnnxScoringResult,
    input_path: Path,
    onnx_path: Path,
    sidecar_path: Path,
) -> Path:
    flags = result.detector_flag.astype(np.int64)
    err = result.detector_recon_error
    score = result.detector_anomaly_score
    summary: dict[str, Any] = {
        "sprint": "36",
        "pillar": "A",
        "advisory_only": True,
        "evaluation_mode": "offline_only",
        "boundary": {
            "control_plane_network": False,
            "write_path": False,
            "runs_read_only": True,
            "network": "none",
        },
        "inputs": {
            "telemetry_path": str(input_path),
            "onnx_path": str(onnx_path),
            "sidecar_path": str(sidecar_path),
            "onnx_sha256": sidecar.onnx_sha256,
            "axes": list(sidecar.axes),
            "n_axes": len(sidecar.axes),
        },
        "scoring": {
            "n_rows": int(len(err)),
            "flag_threshold_error": float(sidecar.flag_threshold_error),
            "flag_positive_count": int(flags.sum()),
            "flag_positive_fraction": (
                float(flags.mean()) if len(flags) else 0.0
            ),
            "recon_error_min": float(err.min()) if len(err) else 0.0,
            "recon_error_mean": float(err.mean()) if len(err) else 0.0,
            "recon_error_max": float(err.max()) if len(err) else 0.0,
            "anomaly_score_min": float(score.min()) if len(score) else 0.0,
            "anomaly_score_mean": float(score.mean()) if len(score) else 0.0,
            "anomaly_score_max": float(score.max()) if len(score) else 0.0,
        },
        "output_columns": list(EVIDENCE_COLUMNS),
    }
    summary_path = evidence_dir / "pillarA_advisory_evidence_summary.json"
    summary_path.write_text(
        json.dumps(summary, sort_keys=True, indent=2)
    )
    return summary_path


# --------------------------------------------------------------------------- #
# the public scoring entrypoint
# --------------------------------------------------------------------------- #
def score_to_evidence(
    *,
    onnx_path: Path | str,
    sidecar_path: Path | str,
    input_path: Path | str,
    evidence_dir: Path | str,
) -> AdvisoryServingResult:
    """Read telemetry, score through ONNX, write evidence. Pure I/O at the
    boundaries; nothing in this function emits a setpoint, dispatch, or
    actuation payload.

    Parameters
    ----------
    onnx_path
        Path to the Sprint-35 ``pillarA_health_detector.onnx`` artifact.
    sidecar_path
        Path to the Sprint-35 ``pillarA_health_detector.sidecar.json``.
    input_path
        Telemetry input file (CSV or JSON records). Must carry every
        axis the sidecar declares; any missing axis raises ``KeyError``
        via :func:`score_with_onnx`.
    evidence_dir
        Destination directory for the evidence sink. Created if missing.
        Only files explicitly named by this function are written there.
    """
    onnx_path = Path(onnx_path)
    sidecar_path = Path(sidecar_path)
    input_path = Path(input_path)
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    sidecar = OnnxHealthDetectorSidecar.from_dict(
        json.loads(sidecar_path.read_text())
    )
    frames = load_telemetry_frames(input_path)
    result = score_with_onnx(frames, onnx_path, sidecar_path)

    csv_path = _write_evidence_csv(evidence_dir, frames, result)
    summary_path = _write_evidence_summary(
        evidence_dir,
        sidecar,
        result,
        input_path=input_path,
        onnx_path=onnx_path,
        sidecar_path=sidecar_path,
    )
    return AdvisoryServingResult(
        n_rows=int(len(frames)),
        evidence_csv_path=csv_path,
        evidence_summary_path=summary_path,
        sidecar=sidecar,
        scoring_result=result,
    )


# --------------------------------------------------------------------------- #
# CLI -- the container entrypoint hook
# --------------------------------------------------------------------------- #
def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serve_pillarA_advisory",
        description=(
            "AOPSO Pillar-A read-only offline health-evidence scorer. "
            "No network, no PLC / PAC / SCADA touchpoint, no setpoint output."
        ),
    )
    parser.add_argument(
        "--onnx",
        required=True,
        help="path to pillarA_health_detector.onnx",
    )
    parser.add_argument(
        "--sidecar",
        required=True,
        help="path to pillarA_health_detector.sidecar.json",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="telemetry CSV or JSON-records file (read-only)",
    )
    parser.add_argument(
        "--evidence-dir",
        required=True,
        help="directory to write health-evidence sink files into",
    )
    return parser


def run_cli(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    result = score_to_evidence(
        onnx_path=args.onnx,
        sidecar_path=args.sidecar,
        input_path=args.input,
        evidence_dir=args.evidence_dir,
    )
    print(
        json.dumps(
            {
                "n_rows": result.n_rows,
                "evidence_csv_path": str(result.evidence_csv_path),
                "evidence_summary_path": str(result.evidence_summary_path),
                "advisory_only": True,
                "evaluation_mode": "offline_only",
            },
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "EVIDENCE_COLUMNS",
    "AdvisoryServingResult",
    "build_cli_parser",
    "load_telemetry_frames",
    "run_cli",
    "score_to_evidence",
]


if __name__ == "__main__":  # pragma: no cover - exercised by the container
    raise SystemExit(run_cli())
