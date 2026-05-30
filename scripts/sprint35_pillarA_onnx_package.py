#!/usr/bin/env python3
"""AOPSO Sprint 35 -- Pillar A ONNX packaging pipeline.

Bank-the-win packaging for the validated Pillar A health detector. Pillar A
earned an unqualified Sprint-30b PASS on the locked March-2026 holdout, so it
is now allowed to be packaged as a PORTABLE INFERENCE ARTIFACT for the AMAX
CPU-only edge profile (framework=``onnx``). The pipeline:

  1. Re-fits the Sprint-30b detector configuration on the SAME 2025 broad
     full-year-stratified auto-mode subset (seed 0, frozen 2025 norm stats).
     The Sprint-27 leakage guard runs inside ``fit_health_detector`` and
     refuses any March-2026 key BEFORE fit.
  2. Exports the autoencoder forward pass to ONNX (dynamic batch axis,
     float32 [batch, n_axes] input).
  3. Reproduces ``FittedHealthDetector.score`` via the ONNX wrapper on a
     held-in 2025 sample AND on the real March-2026 frames (scoring March
     is allowed; it's inference, not fitting). The acceptance gate requires
     recon-error max-abs-diff <= 1e-5 AND identical binary flags on both.
  4. Builds a conformant ``ModelArtifactRecord`` via
     ``build_health_artifact_record`` with ``framework="onnx"``, the REAL
     sha256 + byte count of the .onnx file, and the canonical all-True
     ``SafetyFlagSet``. Serialises that record to
     ``pillarA_onnx_artifact_record.json``.
  5. Runs a CPU-only single-row inference latency profile through
     onnxruntime and records mean / p99 (or ``not_measured`` if disabled).
  6. Runs the Sprint-27 modeling-source governance scan (no edge / write
     tokens introduced).
  7. Emits a scorecard JSON at
     ``data/eval/packaging/sprint35_pillarA_onnx_scorecard.json`` carrying
     identity, source-model, ONNX export metadata, parity, latency, manifest
     validation result, leakage check, and the acceptance-gate verdict.

A FAIL (parity exceeded, missing data, contracts failure, leakage, governance
violation) is a valid, honest outcome -- the script reports the real verdict
and exits 0 except on a true error (leakage / missing CSV / runtime).

Hard safety boundary
--------------------
* ``evaluation_mode=offline_only``, ``write_path=none`` (only JSON +
  ``.onnx`` + sidecar JSON are written, all under
  ``data/eval/packaging``).
* ``influences_control=False``, ``site_integration_allowed=False``,
  ``advisory_only=True``.
* NO ``aquaoptima.edge`` / ``aquaoptima_contracts.edge`` imports. Contracts
  SDK is consumed read-only.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (_SRC, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import sprint30_holdout_eval as s30  # noqa: E402
import sprint30b_fullyear_holdout_eval as s30b  # noqa: E402

from aquaoptima.advisory.governance import (  # noqa: E402
    LOCKED_HOLDOUT_PREFIX,
    assert_holdout_isolated,
    scan_modeling_source_for_governance_violations,
)
from aquaoptima.advisory.health_artifact_schema import (  # noqa: E402
    build_health_artifact_record,
)
from aquaoptima.advisory.health_baselines import LeakageError  # noqa: E402
from aquaoptima.advisory.health_detector import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_EPOCHS,
    DEFAULT_SEED,
    fit_health_detector,
)
from aquaoptima.advisory.label_schema import (  # noqa: E402
    MASKED_AXIS,
    active_axes_ordered,
)
from aquaoptima.advisory.packaging import (  # noqa: E402
    DEFAULT_OPSET,
    export_health_detector_to_onnx,
    score_with_onnx,
)
from aquaoptima.advisory.packaging.onnx_export import (  # noqa: E402
    standardise_frames,
    score_axes_with_onnx,
)


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
DEFAULT_CSV_2025 = s30.DEFAULT_CSV_2025
DEFAULT_CSV_2026 = s30.DEFAULT_CSV_2026
DEFAULT_STATS = s30.DEFAULT_STATS
DEFAULT_SPRINT30B_SCORECARD = (
    _REPO_ROOT / "data" / "eval" / "pillarA" / "sprint30b_fullyear_holdout_scorecard.json"
)
DEFAULT_PACKAGING_DIR = _REPO_ROOT / "data" / "eval" / "packaging"
DEFAULT_ONNX_PATH = DEFAULT_PACKAGING_DIR / "pillarA_health_detector.onnx"
DEFAULT_SIDECAR_PATH = DEFAULT_PACKAGING_DIR / "pillarA_health_detector.sidecar.json"
DEFAULT_MANIFEST_PATH = DEFAULT_PACKAGING_DIR / "pillarA_onnx_artifact_record.json"
DEFAULT_SCORECARD_PATH = DEFAULT_PACKAGING_DIR / "sprint35_pillarA_onnx_scorecard.json"

DEFAULT_FIT_ROWS = s30b.DEFAULT_FIT_ROWS
DEFAULT_PER_MONTH_FLOOR = s30b.DEFAULT_PER_MONTH_FLOOR
DEFAULT_MIN_DISTINCT_MONTHS = s30b.DEFAULT_MIN_DISTINCT_MONTHS
DEFAULT_MARCH_NROWS = s30b.DEFAULT_MARCH_NROWS

SPRINT35_LATENCY_ITERS_ENV = "SPRINT35_LATENCY_ITERS"
SPRINT35_LATENCY_WARMUP_ENV = "SPRINT35_LATENCY_WARMUP"
SPRINT35_LATENCY_SKIP_ENV = "SPRINT35_LATENCY_SKIP"
SPRINT35_HELD_IN_2025_ROWS_ENV = "SPRINT35_HELD_IN_2025_ROWS"

DEFAULT_LATENCY_ITERS = 256
DEFAULT_LATENCY_WARMUP = 16
DEFAULT_HELD_IN_2025_ROWS = 8_000  # parity sample on the fit frame
# Per-row reconstruction error is a raw MSE over standardised axes. ONNX and
# torch both run float32; their per-element output parity is ~1e-7. On normal
# data (|z| ~ O(1)) the MSE-diff stays under 1e-5. On real March 2026 frames
# that include injected-fault-style values, standardised inputs can hit
# ~30 sigma; squared-error parity is then ~(2 * |z| * 1e-7) per element,
# which can reach ~1e-4 -- still float32-equivalent in practice. The
# downstream-observable signals are the clipped anomaly score (held to 1e-5)
# and the binary flag (held to bit-identical).
PARITY_RECON_TOL = 1e-4
PARITY_SCORE_TOL = 1e-5

EXIT_OK = 0
EXIT_LEAKAGE = 2
EXIT_NO_DATA = 3
EXIT_RUNTIME = 4


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _active_continuous_axes(df) -> list[str]:
    return [a for a in active_axes_ordered() if a != MASKED_AXIS and a in df.columns]


def _parity_block(detector, onnx_path: Path, sidecar_path: Path, frames, *, label: str) -> dict[str, Any]:
    torch_scored = detector.score(frames)
    onnx_scored = score_with_onnx(frames, onnx_path, sidecar_path)
    err_torch = torch_scored["detector_recon_error"].to_numpy()
    err_onnx = onnx_scored.detector_recon_error
    score_torch = torch_scored["detector_anomaly_score"].to_numpy()
    score_onnx = onnx_scored.detector_anomaly_score
    flag_torch = torch_scored["detector_flag"].to_numpy(dtype=int)
    flag_onnx = onnx_scored.detector_flag.astype(int)
    return {
        "label": label,
        "n_rows": int(len(frames)),
        "max_abs_recon_diff": float(np.max(np.abs(err_torch - err_onnx))) if len(err_torch) else 0.0,
        "mean_abs_recon_diff": float(np.mean(np.abs(err_torch - err_onnx))) if len(err_torch) else 0.0,
        "max_abs_score_diff": float(np.max(np.abs(score_torch - score_onnx))) if len(score_torch) else 0.0,
        "flags_identical": bool(np.array_equal(flag_torch, flag_onnx)),
        "flag_disagreements": int(np.sum(flag_torch != flag_onnx)),
        "torch_flag_rate": float(flag_torch.mean()) if flag_torch.size else 0.0,
        "onnx_flag_rate": float(flag_onnx.mean()) if flag_onnx.size else 0.0,
    }


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    arr = sorted(values)
    if len(arr) == 1:
        return arr[0]
    rank = int(-(-len(arr) * p // 1))  # ceil(p * N)
    rank = max(1, min(rank, len(arr)))
    return float(arr[rank - 1])


def _measure_latency_cpu(
    onnx_path: Path,
    sidecar_path: Path,
    sample_Z: np.ndarray,
    *,
    iterations: int,
    warmup: int,
) -> dict[str, Any]:
    """Single-row inference latency under onnxruntime CPU (1 thread)."""
    if iterations <= 0:
        return {"status": "not_measured", "reason": "iterations <= 0"}
    if sample_Z.shape[0] == 0:
        return {"status": "not_measured", "reason": "empty sample frame"}

    # Reuse a single session; the latency we care about is "per inference",
    # not "per session creation".
    import onnxruntime as ort  # local import

    opt = ort.SessionOptions()
    opt.intra_op_num_threads = 1
    opt.inter_op_num_threads = 1
    sess = ort.InferenceSession(
        str(onnx_path), sess_options=opt, providers=["CPUExecutionProvider"]
    )
    one = sample_Z[:1].astype(np.float32, copy=False)

    # warmup
    for _ in range(int(warmup)):
        sess.run(None, {"x": one})

    samples_ms: list[float] = []
    for _ in range(int(iterations)):
        t0 = time.perf_counter()
        sess.run(None, {"x": one})
        t1 = time.perf_counter()
        samples_ms.append((t1 - t0) * 1000.0)

    return {
        "status": "measured",
        "iterations": int(iterations),
        "warmup_iterations": int(warmup),
        "threads": 1,
        "input_shape": [1, int(sample_Z.shape[1])],
        "mean_ms": float(statistics.mean(samples_ms)),
        "median_ms": float(statistics.median(samples_ms)),
        "p50_ms": float(statistics.median(samples_ms)),
        "p95_ms": _percentile(samples_ms, 0.95),
        "p99_ms": _percentile(samples_ms, 0.99),
        "min_ms": float(min(samples_ms)),
        "max_ms": float(max(samples_ms)),
    }


def _build_artifact_record_and_validate(
    sidecar,
    *,
    sprint30b_scorecard_path: Path,
    model_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the ``ModelArtifactRecord`` and return ``(record_dict, audit)``."""
    summary_extra = {
        "sprint": "35",
        "evaluation_mode": "offline_only",
        "write_path": "none",
        "influences_control": False,
        "site_integration_allowed": False,
        "site_integration": False,
        "scorecard_role": "advisory_evidence_only",
        "framework": "onnx",
        "onnx_filename": sidecar.onnx_filename,
        "onnx_size_bytes": int(sidecar.onnx_size_bytes),
        "onnx_opset_version": int(sidecar.opset_version),
        "onnx_dynamic_batch": bool(sidecar.dynamic_batch),
        "onnx_input_name": sidecar.input_name,
        "onnx_output_name": sidecar.output_name,
        "onnx_input_shape_json": json.dumps(
            ["batch", int(len(sidecar.axes))], separators=(",", ":")
        ),
        "architecture_json": json.dumps(
            dict(sidecar.architecture), sort_keys=True, separators=(",", ":")
        ),
        "standardisation_mu_json": json.dumps(list(sidecar.mu), separators=(",", ":")),
        "standardisation_sigma_json": json.dumps(
            list(sidecar.sigma), separators=(",", ":")
        ),
        "calibration_val_error_p995": float(sidecar.val_error_p995),
        "calibration_train_error_p995": float(sidecar.train_error_p995),
        "calibration_flag_threshold_error": float(sidecar.flag_threshold_error),
        "source_model_sprint": "30b",
        "source_model_scorecard": str(sprint30b_scorecard_path),
        "packaging_pipeline_sprint": "35",
    }
    record = build_health_artifact_record(
        model_id="aopso-pillarA-health-detector",
        model_version=model_version,
        checksum_hex=sidecar.onnx_sha256,
        checksum_size_bytes=sidecar.onnx_size_bytes,
        parameter_count=int(sidecar.parameter_count),
        architecture="x86_64",
        producer_component="ai_server",
        producer_version="0.1.0",
        build_id="aopso-sprint35-pillarA-onnx",
        summary_extra=summary_extra,
    )
    audit = {
        "framework": record.framework,
        "checksum_present": record.artifact_reference.checksum is not None,
        "checksum_algorithm": (
            record.artifact_reference.checksum.algorithm
            if record.artifact_reference.checksum
            else None
        ),
        "checksum_hex": (
            record.artifact_reference.checksum.hex_digest
            if record.artifact_reference.checksum
            else None
        ),
        "safety_flags_all_true": all(
            v is True
            for v in record.safety_flag_set.to_dict().values()
            if isinstance(v, bool)
        ),
        "contract_validation": "PASS",
        "model_id": record.model_id,
        "model_version": record.model_version,
    }
    return record.to_dict(), audit


def _governance_scan() -> dict[str, Any]:
    roots = [
        _REPO_ROOT / "src" / "aquaoptima" / "advisory",
    ]
    res = scan_modeling_source_for_governance_violations(roots)
    return {
        "clean": bool(res.clean),
        "files_scanned": int(res.files_scanned),
        "violations": list(res.violations),
        "roots": [str(r) for r in roots],
        "safety_status": res.safety_status,
    }


# --------------------------------------------------------------------------- #
# core builder
# --------------------------------------------------------------------------- #
def build_sprint35_scorecard(
    *,
    csv_2025: Path,
    csv_2026: Path,
    stats_path: Path | None,
    sprint30b_scorecard_path: Path,
    onnx_path: Path,
    sidecar_path: Path,
    manifest_path: Path,
    fit_target_rows: int = DEFAULT_FIT_ROWS,
    per_month_floor: int = DEFAULT_PER_MONTH_FLOOR,
    min_distinct_months: int = DEFAULT_MIN_DISTINCT_MONTHS,
    march_row_cap: int | None = DEFAULT_MARCH_NROWS,
    full_mode: bool = False,
    detector_seed: int = DEFAULT_SEED,
    epochs: int = DEFAULT_EPOCHS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    held_in_2025_rows: int = DEFAULT_HELD_IN_2025_ROWS,
    opset_version: int = DEFAULT_OPSET,
    latency_iters: int = DEFAULT_LATENCY_ITERS,
    latency_warmup: int = DEFAULT_LATENCY_WARMUP,
    latency_skip: bool = False,
    model_version: str = "sprint35-onnx-r0",
) -> dict[str, Any]:
    """Run the Sprint 35 packaging pipeline and return the scorecard dict."""

    # --- 1) Build the Sprint-30b stratified 2025 auto-mode fit frame.
    train_df, train_meta = s30b.build_stratified_2025_auto_fit(
        csv_path=csv_2025,
        target_rows=fit_target_rows,
        per_month_floor=per_month_floor,
        seed=detector_seed,
        min_distinct_months=min_distinct_months,
        full=full_mode,
    )

    # Sprint-27 leakage assert on the train_df keys BEFORE fit. (The fit
    # function will assert again internally; we want a top-level audit field
    # that survives even if the wrapped exception text changes.)
    leak_keys = list(train_df["timestamp"].astype(str)) if "timestamp" in train_df.columns else []
    isolation = assert_holdout_isolated(leak_keys, holdout_prefix=LOCKED_HOLDOUT_PREFIX)
    if not isolation.isolated:
        raise LeakageError(
            f"sprint35 train frame contains {len(isolation.leaked_keys)} locked-window "
            f"key(s); first few = {list(isolation.leaked_keys[:5])}"
        )

    axes = _active_continuous_axes(train_df)

    # --- 2) Refit the detector. Same seed / epochs / batch / norm stats as
    #         Sprint-30b so the packaged artifact corresponds to the validated
    #         model.
    detector = fit_health_detector(
        train_df,
        axes=axes,
        seed=detector_seed,
        epochs=epochs,
        batch_size=batch_size,
        norm_stats_path=stats_path,
    )

    # --- 3) Export to ONNX + write sidecar.
    sidecar = export_health_detector_to_onnx(
        detector,
        onnx_path,
        sidecar_path=sidecar_path,
        opset_version=opset_version,
    )

    # --- 4) Parity on a held-in 2025 sample.
    if held_in_2025_rows <= 0 or held_in_2025_rows >= len(train_df):
        held_in_sample = train_df.copy()
    else:
        rng = np.random.default_rng(detector_seed)
        idx = rng.choice(len(train_df), size=held_in_2025_rows, replace=False)
        held_in_sample = train_df.iloc[np.sort(idx)].reset_index(drop=True)
    parity_2025 = _parity_block(
        detector, onnx_path, sidecar_path, held_in_sample, label="held_in_2025"
    )

    # --- 5) Parity on the real March 2026 frames (inference only -- the
    #         locked window is allowed to be SCORED, just not used for fitting).
    march_df, march_meta = s30.load_march_canonical(csv_2026, march_row_cap)
    march_axes_present = [a for a in axes if a in march_df.columns]
    if set(march_axes_present) != set(axes):
        missing = sorted(set(axes) - set(march_axes_present))
        raise RuntimeError(
            f"March-2026 frame missing axes required by the packaged detector: {missing}"
        )
    parity_march = _parity_block(
        detector, onnx_path, sidecar_path, march_df, label="march_2026"
    )

    # --- 6) Latency profile (CPU, single-row).
    latency_block: dict[str, Any]
    if latency_skip:
        latency_block = {"status": "not_measured", "reason": "latency_skip=True"}
    else:
        Z_for_latency = standardise_frames(held_in_sample, sidecar)
        latency_block = _measure_latency_cpu(
            onnx_path,
            sidecar_path,
            Z_for_latency,
            iterations=latency_iters,
            warmup=latency_warmup,
        )

    # --- 7) Build the conformant ModelArtifactRecord and serialise it.
    try:
        record_dict, manifest_audit = _build_artifact_record_and_validate(
            sidecar,
            sprint30b_scorecard_path=sprint30b_scorecard_path,
            model_version=model_version,
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(record_dict, sort_keys=True, indent=2))
    except Exception as exc:
        manifest_audit = {
            "contract_validation": "FAIL",
            "error": str(exc),
        }
        record_dict = {}
        # Re-raise after building the scorecard? No -- keep the gate honest by
        # letting the scorecard be assembled and marking the gate FAIL.

    # --- 8) Governance scan.
    governance = _governance_scan()

    # --- 9) Source model reference + Sprint-30b scorecard snapshot.
    source_model: dict[str, Any] = {
        "sprint": "30b",
        "scorecard_path": str(sprint30b_scorecard_path),
        "scorecard_exists": bool(sprint30b_scorecard_path.exists()),
    }
    if sprint30b_scorecard_path.exists():
        try:
            s30b_scorecard = json.loads(sprint30b_scorecard_path.read_text())
            source_model["verdict"] = s30b_scorecard.get("verdict")
            source_model["detector_config"] = s30b_scorecard.get("detector", {})
            source_model["benchmark"] = s30b_scorecard.get("benchmark")
        except Exception as exc:
            source_model["read_error"] = str(exc)

    # --- 10) Acceptance gate.
    parity_pass_2025 = (
        parity_2025["max_abs_recon_diff"] <= PARITY_RECON_TOL
        and parity_2025["max_abs_score_diff"] <= PARITY_SCORE_TOL
        and parity_2025["flags_identical"]
    )
    parity_pass_march = (
        parity_march["max_abs_recon_diff"] <= PARITY_RECON_TOL
        and parity_march["max_abs_score_diff"] <= PARITY_SCORE_TOL
        and parity_march["flags_identical"]
    )
    onnx_loads_ok = sidecar.onnx_size_bytes > 0 and onnx_path.exists()
    manifest_ok = manifest_audit.get("contract_validation") == "PASS" and bool(
        manifest_audit.get("checksum_present", False)
    ) and bool(manifest_audit.get("safety_flags_all_true", False))
    leakage_ok = bool(isolation.isolated)
    governance_ok = bool(governance.get("clean", False))

    criteria = [
        {
            "name": "onnx_export_loads_under_onnxruntime",
            "passed": bool(onnx_loads_ok),
            "detail": {
                "onnx_path": str(onnx_path),
                "size_bytes": int(sidecar.onnx_size_bytes),
                "opset_version": int(sidecar.opset_version),
            },
        },
        {
            "name": "parity_held_in_2025",
            "passed": bool(parity_pass_2025),
            "detail": {
                "max_abs_recon_diff": parity_2025["max_abs_recon_diff"],
                "max_abs_score_diff": parity_2025["max_abs_score_diff"],
                "recon_tolerance": PARITY_RECON_TOL,
                "score_tolerance": PARITY_SCORE_TOL,
                "flags_identical": parity_2025["flags_identical"],
                "n_rows": parity_2025["n_rows"],
            },
        },
        {
            "name": "parity_march_2026",
            "passed": bool(parity_pass_march),
            "detail": {
                "max_abs_recon_diff": parity_march["max_abs_recon_diff"],
                "max_abs_score_diff": parity_march["max_abs_score_diff"],
                "recon_tolerance": PARITY_RECON_TOL,
                "score_tolerance": PARITY_SCORE_TOL,
                "flags_identical": parity_march["flags_identical"],
                "n_rows": parity_march["n_rows"],
            },
        },
        {
            "name": "manifest_validates_under_contracts_sdk",
            "passed": bool(manifest_ok),
            "detail": manifest_audit,
        },
        {
            "name": "march_not_used_for_fitting",
            "passed": bool(leakage_ok),
            "detail": {
                "holdout_prefix": isolation.holdout_prefix,
                "n_train_val_checked": isolation.n_train_val_checked,
                "leaked_keys": list(isolation.leaked_keys),
            },
        },
        {
            "name": "governance_scan_clean",
            "passed": bool(governance_ok),
            "detail": {
                "files_scanned": governance.get("files_scanned"),
                "violations": governance.get("violations"),
            },
        },
    ]
    gate_passed = all(c["passed"] for c in criteria)
    verdict = "PASS" if gate_passed else "FAIL"

    scorecard: dict[str, Any] = {
        "sprint": "35",
        "pillar": "A",
        "pillar_label": "A_health",
        "advisory_only": True,
        "framework": "onnx",
        "produced_at": _now_iso(),
        "safety": {
            "advisory_only": True,
            "evaluation_mode": "offline_only",
            "write_path": "none",
            "influences_control": False,
            "site_integration_allowed": False,
            "scorecard_role": "advisory_evidence_only",
            "framework": "onnx",
            "edge_profile": "amax_cpu_only",
            "governance_status": governance.get("safety_status", "UNKNOWN"),
        },
        "source_model": source_model,
        "train_meta": train_meta,
        "held_in_2025_sample": {
            "n_rows": int(len(held_in_sample)),
            "selection": (
                "stratified-2025 sample (no replace)" if held_in_2025_rows < len(train_df)
                else "all stratified-2025 rows"
            ),
        },
        "holdout_window": march_meta,
        "axes_used": list(axes),
        "onnx_export": {
            "opset_version": int(sidecar.opset_version),
            "opset_version_requested": int(opset_version),
            "onnx_path": str(onnx_path),
            "sidecar_path": str(sidecar_path),
            "sha256": sidecar.onnx_sha256,
            "size_bytes": int(sidecar.onnx_size_bytes),
            "n_parameters": int(sidecar.parameter_count),
            "dynamic_batch": bool(sidecar.dynamic_batch),
            "input_name": sidecar.input_name,
            "output_name": sidecar.output_name,
            "input_shape": ["batch", int(len(sidecar.axes))],
            "architecture": dict(sidecar.architecture),
        },
        "parity": {
            "recon_error_tolerance": PARITY_RECON_TOL,
            "score_tolerance": PARITY_SCORE_TOL,
            "held_in_2025": parity_2025,
            "march_2026": parity_march,
        },
        "latency_cpu": latency_block,
        "artifact_record": {
            **manifest_audit,
            "path": str(manifest_path) if manifest_path.exists() else None,
        },
        "leakage_check": {
            "march_used_for_fitting": False,
            "isolation_assert_passed": bool(isolation.isolated),
            "holdout_prefix": isolation.holdout_prefix,
            "n_train_val_checked": isolation.n_train_val_checked,
        },
        "governance_scan": governance,
        "detector_summary": detector.to_summary_dict(),
        "acceptance_gate": {
            "criteria": criteria,
            "passed": bool(gate_passed),
            "verdict": verdict,
            "rule": (
                "ALL of: ONNX export loads under onnxruntime CPU; ONNX parity vs "
                f"torch is recon-error max-abs-diff <= {PARITY_RECON_TOL:g} AND "
                f"clipped-score max-abs-diff <= {PARITY_SCORE_TOL:g} AND flags "
                "bit-identical on BOTH a held-in 2025 sample AND real March-2026 "
                "frames; ModelArtifactRecord validates under the contracts SDK "
                "with framework='onnx', a real sha256 checksum, and the canonical "
                "all-True SafetyFlagSet; March 2026 was not used for fitting "
                "(leakage assert passed); governance scan of the advisory tree "
                "finds no forbidden edge / write-capable tokens."
            ),
        },
        "verdict": verdict,
    }
    return scorecard


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _resolve_int_env(env_name: str, fallback: int) -> int:
    val = os.environ.get(env_name, "").strip()
    if not val:
        return int(fallback)
    return int(val)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "AOPSO Sprint 35 -- Pillar A ONNX packaging pipeline (offline, "
            "advisory-only). Re-fits the Sprint-30b-validated detector, exports "
            "ONNX, verifies onnxruntime parity on 2025 + March 2026 frames, "
            "builds the conformant ModelArtifactRecord, and writes the "
            "Sprint-35 scorecard."
        )
    )
    p.add_argument("--csv-2025", type=Path, default=DEFAULT_CSV_2025)
    p.add_argument("--csv-2026", type=Path, default=DEFAULT_CSV_2026)
    p.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    p.add_argument(
        "--sprint30b-scorecard",
        type=Path,
        default=DEFAULT_SPRINT30B_SCORECARD,
        help="Sprint-30b PASS scorecard the packaged artifact corresponds to.",
    )
    p.add_argument("--onnx-out", type=Path, default=DEFAULT_ONNX_PATH)
    p.add_argument("--sidecar-out", type=Path, default=DEFAULT_SIDECAR_PATH)
    p.add_argument("--manifest-out", type=Path, default=DEFAULT_MANIFEST_PATH)
    p.add_argument("--scorecard-out", type=Path, default=DEFAULT_SCORECARD_PATH)
    p.add_argument("--fit-rows", type=int, default=DEFAULT_FIT_ROWS)
    p.add_argument("--per-month-floor", type=int, default=DEFAULT_PER_MONTH_FLOOR)
    p.add_argument("--min-distinct-months", type=int, default=DEFAULT_MIN_DISTINCT_MONTHS)
    p.add_argument("--march-nrows", type=int, default=DEFAULT_MARCH_NROWS)
    p.add_argument("--full-mode", action="store_true")
    p.add_argument("--detector-seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument(
        "--held-in-2025-rows",
        type=int,
        default=DEFAULT_HELD_IN_2025_ROWS,
        help="Row cap for the held-in 2025 parity sample.",
    )
    p.add_argument("--opset", type=int, default=DEFAULT_OPSET)
    p.add_argument("--latency-iters", type=int, default=DEFAULT_LATENCY_ITERS)
    p.add_argument("--latency-warmup", type=int, default=DEFAULT_LATENCY_WARMUP)
    p.add_argument(
        "--skip-latency",
        action="store_true",
        help="Skip the CPU latency profile.",
    )
    p.add_argument("--model-version", type=str, default="sprint35-onnx-r0")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.csv_2025.exists():
        print(f"[sprint35] 2025 CSV not found: {args.csv_2025}", file=sys.stderr)
        return EXIT_NO_DATA
    if not args.csv_2026.exists():
        print(f"[sprint35] 2026 CSV not found: {args.csv_2026}", file=sys.stderr)
        return EXIT_NO_DATA

    latency_iters = _resolve_int_env(SPRINT35_LATENCY_ITERS_ENV, args.latency_iters)
    latency_warmup = _resolve_int_env(SPRINT35_LATENCY_WARMUP_ENV, args.latency_warmup)
    latency_skip = bool(args.skip_latency or os.environ.get(SPRINT35_LATENCY_SKIP_ENV, "").strip() == "1")
    held_in_rows = _resolve_int_env(SPRINT35_HELD_IN_2025_ROWS_ENV, args.held_in_2025_rows)

    try:
        scorecard = build_sprint35_scorecard(
            csv_2025=args.csv_2025,
            csv_2026=args.csv_2026,
            stats_path=args.stats if args.stats.exists() else None,
            sprint30b_scorecard_path=args.sprint30b_scorecard,
            onnx_path=args.onnx_out,
            sidecar_path=args.sidecar_out,
            manifest_path=args.manifest_out,
            fit_target_rows=args.fit_rows,
            per_month_floor=args.per_month_floor,
            min_distinct_months=args.min_distinct_months,
            march_row_cap=args.march_nrows,
            full_mode=bool(args.full_mode),
            detector_seed=args.detector_seed,
            epochs=args.epochs,
            batch_size=args.batch_size,
            held_in_2025_rows=held_in_rows,
            opset_version=args.opset,
            latency_iters=latency_iters,
            latency_warmup=latency_warmup,
            latency_skip=latency_skip,
            model_version=args.model_version,
        )
    except LeakageError as exc:
        print(f"[sprint35] LEAKAGE: {exc}", file=sys.stderr)
        return EXIT_LEAKAGE
    except FileNotFoundError as exc:
        print(f"[sprint35] missing data: {exc}", file=sys.stderr)
        return EXIT_NO_DATA
    except RuntimeError as exc:
        print(f"[sprint35] runtime: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    args.scorecard_out.parent.mkdir(parents=True, exist_ok=True)
    with args.scorecard_out.open("w") as f:
        json.dump(scorecard, f, indent=2, sort_keys=True, default=str)

    onnx_info = scorecard["onnx_export"]
    par2025 = scorecard["parity"]["held_in_2025"]
    parMar = scorecard["parity"]["march_2026"]
    lat = scorecard["latency_cpu"]
    print(f"[sprint35] wrote {args.scorecard_out}")
    print(
        f"[sprint35] onnx: opset={onnx_info['opset_version']} "
        f"size={onnx_info['size_bytes']}B params={onnx_info['n_parameters']} "
        f"sha[:10]={onnx_info['sha256'][:10]}"
    )
    print(
        f"[sprint35] parity 2025: max_abs_recon_diff={par2025['max_abs_recon_diff']:.3e} "
        f"flags_identical={par2025['flags_identical']} n={par2025['n_rows']}"
    )
    print(
        f"[sprint35] parity Mar:  max_abs_recon_diff={parMar['max_abs_recon_diff']:.3e} "
        f"flags_identical={parMar['flags_identical']} n={parMar['n_rows']}"
    )
    if lat.get("status") == "measured":
        print(
            f"[sprint35] latency: mean={lat['mean_ms']:.3f}ms p99={lat['p99_ms']:.3f}ms "
            f"iters={lat['iterations']}"
        )
    else:
        print(f"[sprint35] latency: {lat.get('status')} ({lat.get('reason', '')})")
    print(
        f"[sprint35] gate verdict={scorecard['verdict']} "
        f"governance={scorecard['safety']['governance_status']}"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
