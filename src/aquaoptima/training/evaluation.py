"""Offline evaluation harness vs the LOCKED March 2026 benchmark (AOPSO Sprint 25).

Loads a trained dPHM checkpoint (``model_best.pt``), scores the **frozen March
2026 holdout** (read-only), and emits a ``ShadowRuntimeReport``-shaped scorecard
with per-axis normalized MSE/MAE for the 6 continuous axes and accuracy for the
2 binary axes (``node_status``, ``edge_status``). ``edge_valve_position`` is
N/A / masked (no backing column). An MVP-v1 persistence baseline is scored on
the IDENTICAL holdout windows, and a machine-checkable acceptance gate decides
PASS/FAIL ("good enough to package").

Holdout construction
---------------------
The March 2026 benchmark lives at ``$YILAN_2026_CSV`` (default
``.../yearlong_drive/source1_2026.csv``), same schema as 2025. We read it,
filter to ``month == 3`` (calendar 2026-03), apply the canonical axis map and
the *training* normalization stats, and build gap-aware sliding windows
identical to training (``window`` / ``horizon`` / ``stride`` from config).

Holdout isolation
-----------------
Before scoring, the harness re-checks the split manifest and asserts the March
2026 window (2026-03) does not intersect any train/val split day — a hard STOP
on leakage. 2026 data is never used to fit normalization or the model.

CRITICAL HONESTY: this harness reports whatever the model actually scores.
There are NO hardcoded / illustrative metric values anywhere. A FAIL is a valid,
valuable outcome (do not package; iterate training).

Safety: offline scoring only. Reads static CSV-derived holdout (read-only),
loads an inert ``.pt`` state_dict, writes only an advisory scorecard JSON. No
edge imports, no ONNX, no contract writes, no OT/PLC/SCADA, no control output.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import torch

from ..dataio.yilan_axis_map import (
    CANONICAL_AXIS_TO_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_FORMAT,
)
from ..dataio.yilan_profiler import GAP_THRESHOLD_SECONDS
from ..models.tcn_dphm import TCN_DPHM
from .acceptance import (
    BINARY_AXES,
    CONTINUOUS_AXES,
    AcceptanceThresholds,
    evaluate_gate,
)
from .baseline_mvp import PERSISTENCE_NAME, persistence_predict
from .dphm_trainer import load_config
from .eval_report import build_shadow_report, validate_shadow_report_shape
from .normalization import load_stats

__all__ = [
    "MarchHoldoutWindows",
    "score_predictions",
    "evaluate",
    "assert_holdout_isolated",
    "main",
    "DEFAULT_MARCH_CSV",
    "YILAN_2026_CSV_ENV",
]

DEFAULT_MARCH_CSV = (
    "/home/hunter_lin/projects/yilan-site-model-testing/"
    "yearlong_drive/source1_2026.csv"
)
YILAN_2026_CSV_ENV = "YILAN_2026_CSV"

MASKED_AXIS = "edge_valve_position"


# --------------------------------------------------------------------------- #
# Holdout isolation
# --------------------------------------------------------------------------- #
def assert_holdout_isolated(
    manifest: dict, *, holdout_key: str = "holdout_march2026"
) -> dict:
    """STOP-condition guard: March 2026 window must not intersect any train/val day.

    Re-checks the manifest: collects the day sets of the ``train`` and ``val``
    splits and asserts none of them falls inside the holdout's calendar window
    (2026-03). Returns a small diagnostic dict on success; raises ``ValueError``
    on any intersection (data leakage).
    """
    splits = manifest.get("splits", {})
    holdout = splits.get(holdout_key, {})
    dr = holdout.get("date_range", {})
    start = dr.get("start")
    end = dr.get("end")
    if not start or not end:
        raise ValueError(
            f"holdout '{holdout_key}' has no date_range; cannot verify isolation"
        )
    h_start = pd.Timestamp(start)
    h_end = pd.Timestamp(end)
    if h_start.year != 2026 or h_start.month != 3:
        raise ValueError(
            f"holdout window {h_start}..{h_end} is not the March-2026 benchmark"
        )

    intersecting: dict[str, list[str]] = {}
    for key in ("train", "val"):
        split = splits.get(key, {})
        bad: list[str] = []
        for day in split.get("days", []):
            ts = pd.Timestamp(day)
            if h_start <= ts <= h_end:
                bad.append(day)
        # Also defensively check the split's own date_range.
        sdr = split.get("date_range", {})
        for bound in (sdr.get("start"), sdr.get("end")):
            if bound:
                bts = pd.Timestamp(bound)
                if h_start <= bts <= h_end and str(bts.date()) not in bad:
                    bad.append(str(bts.date()))
        if bad:
            intersecting[key] = sorted(set(bad))

    if intersecting:
        raise ValueError(
            "STOP: March 2026 holdout intersects train/val split days "
            f"-> data leakage: {intersecting}"
        )
    return {
        "holdout_key": holdout_key,
        "holdout_window": {"start": str(h_start), "end": str(h_end)},
        "train_val_intersection": {},
        "isolated": True,
    }


# --------------------------------------------------------------------------- #
# March 2026 holdout windows
# --------------------------------------------------------------------------- #
def _load_march_frame(
    csv_path: str | os.PathLike[str], *, nrows: int | None = None
) -> pd.DataFrame:
    """Read the 2026 CSV and filter to calendar month March (2026-03)."""
    header = pd.read_csv(csv_path, nrows=0)
    backing = [c for c in CANONICAL_AXIS_TO_COLUMN.values() if c is not None]
    wanted = [TIMESTAMP_COLUMN, *backing]
    present = [c for c in wanted if c in header.columns]
    if TIMESTAMP_COLUMN not in present:
        raise ValueError(
            f"March CSV {csv_path} missing required '{TIMESTAMP_COLUMN}' column"
        )
    df = pd.read_csv(csv_path, usecols=present, nrows=nrows, low_memory=False)
    df[TIMESTAMP_COLUMN] = pd.to_datetime(
        df[TIMESTAMP_COLUMN], format=TIMESTAMP_FORMAT, errors="coerce"
    )
    df = df.dropna(subset=[TIMESTAMP_COLUMN])
    df = df.sort_values(TIMESTAMP_COLUMN, kind="stable").reset_index(drop=True)
    march = df[(df[TIMESTAMP_COLUMN].dt.year == 2026) & (df[TIMESTAMP_COLUMN].dt.month == 3)]
    march = march.reset_index(drop=True)
    for col in backing:
        if col in march.columns:
            march[col] = pd.to_numeric(march[col], errors="coerce")
    return march


class MarchHoldoutWindows:
    """Gap-aware sliding windows over the March-2026 holdout, normalized.

    Mirrors :class:`YilanTimeSeriesDataset` windowing (same gap threshold, same
    z-score from the training stats) but reads the 2026 CSV filtered to March
    rather than a manifest split. Exposes raw numpy arrays for batched scoring.
    """

    def __init__(
        self,
        stats: dict,
        *,
        csv_path: str | os.PathLike[str],
        window: int = 10,
        horizon: int = 1,
        stride: int = 1,
        nrows: int | None = None,
        gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
    ) -> None:
        if window < 1 or horizon < 1 or stride < 1:
            raise ValueError("window, horizon, stride must all be >= 1")
        self.window = window
        self.horizon = horizon
        self.stride = stride
        self.active_axes: list[str] = list(stats["active_axes"])
        if not self.active_axes:
            raise ValueError("no active axes in normalization stats")

        df = _load_march_frame(csv_path, nrows=nrows)
        self.n_rows = int(len(df))
        if self.n_rows == 0:
            raise ValueError(
                "STOP: could not load any March 2026 rows from "
                f"{csv_path} (month==3 filter returned 0 rows)"
            )
        self.date_range = {
            "start": str(df[TIMESTAMP_COLUMN].min()),
            "end": str(df[TIMESTAMP_COLUMN].max()),
        }

        cols = [CANONICAL_AXIS_TO_COLUMN[a] for a in self.active_axes]
        feats = df[cols].apply(lambda c: c.astype(float)).to_numpy(dtype=float)
        self.features = feats
        ts = df[TIMESTAMP_COLUMN].reset_index(drop=True)

        secs = ts.diff().dt.total_seconds().to_numpy()
        n = self.n_rows
        gap_after = np.zeros(n, dtype=bool)
        for i in range(1, n):
            if np.isfinite(secs[i]) and secs[i] > gap_threshold_seconds:
                gap_after[i - 1] = True

        span = window + horizon
        starts: list[int] = []
        for start in range(0, n - span + 1, stride):
            end = start + span - 1
            if np.any(gap_after[start:end]):
                continue
            starts.append(start)
        self._starts = starts

        self._mu = np.array([stats["stats"][a]["mu"] for a in self.active_axes], dtype=float)
        self._sigma = np.array(
            [stats["stats"][a]["sigma"] for a in self.active_axes], dtype=float
        )

    def __len__(self) -> int:
        return len(self._starts)

    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(X, Y)`` normalized arrays.

        ``X``: ``[n_windows, window, n_axes]``; ``Y``: ``[n_windows, n_axes]``.
        NaNs are zero-filled after normalization (consistent with training).
        """
        xs: list[np.ndarray] = []
        ys: list[np.ndarray] = []
        for start in self._starts:
            w_end = start + self.window
            t_idx = w_end + self.horizon - 1
            x_raw = self.features[start:w_end, :]
            y_raw = self.features[t_idx, :]
            x = (x_raw - self._mu) / self._sigma
            y = (y_raw - self._mu) / self._sigma
            xs.append(np.nan_to_num(x, nan=0.0))
            ys.append(np.nan_to_num(y, nan=0.0))
        if not xs:
            n_axes = len(self.active_axes)
            return (
                np.zeros((0, self.window, n_axes), dtype=float),
                np.zeros((0, n_axes), dtype=float),
            )
        return np.stack(xs).astype(float), np.stack(ys).astype(float)


# --------------------------------------------------------------------------- #
# Metric computation
# --------------------------------------------------------------------------- #
def score_predictions(
    pred: np.ndarray,
    target: np.ndarray,
    active_axes: list[str],
    *,
    mu: np.ndarray | None = None,
    sigma: np.ndarray | None = None,
) -> dict[str, dict]:
    """Per-axis metrics: MSE/MAE (normalized) for continuous axes, accuracy for binary.

    ``pred`` / ``target`` are normalized ``[N, n_axes]`` arrays in ``active_axes``
    column order. For binary axes, accuracy is computed on the de-normalized
    values thresholded at 0.5 (recovering the 0/1 status class). ``mu`` / ``sigma``
    are required to de-normalize binary axes; if absent, binary accuracy is None.
    """
    pred = np.asarray(pred, dtype=float)
    target = np.asarray(target, dtype=float)
    out: dict[str, dict] = {}
    for j, axis in enumerate(active_axes):
        p = pred[:, j]
        t = target[:, j]
        if axis in BINARY_AXES:
            if mu is not None and sigma is not None:
                p_denorm = p * sigma[j] + mu[j]
                t_denorm = t * sigma[j] + mu[j]
                p_cls = (p_denorm >= 0.5).astype(int)
                t_cls = (t_denorm >= 0.5).astype(int)
            else:
                p_cls = (p >= 0.5).astype(int)
                t_cls = (t >= 0.5).astype(int)
            acc = float(np.mean(p_cls == t_cls)) if p_cls.size else float("nan")
            out[axis] = {
                "kind": "binary",
                "accuracy": acc,
                # Also report normalized MSE/MAE for completeness / reporting.
                "mse": float(np.mean((p - t) ** 2)) if p.size else float("nan"),
                "mae": float(np.mean(np.abs(p - t))) if p.size else float("nan"),
            }
        else:
            out[axis] = {
                "kind": "continuous",
                "mse": float(np.mean((p - t) ** 2)) if p.size else float("nan"),
                "mae": float(np.mean(np.abs(p - t))) if p.size else float("nan"),
                "accuracy": None,
            }
    return out


# --------------------------------------------------------------------------- #
# End-to-end evaluation
# --------------------------------------------------------------------------- #
def _resolve_march_csv(explicit: str | None) -> str:
    if explicit:
        return explicit
    return os.environ.get(YILAN_2026_CSV_ENV, DEFAULT_MARCH_CSV)


def evaluate(
    *,
    checkpoint: str,
    split_manifest: str = "data/splits/yilan_2025_split_v1.json",
    norm_stats: str = "data/normalization/yilan_2025_train_stats.json",
    holdout_key: str = "holdout_march2026",
    baseline: str = PERSISTENCE_NAME,
    march_csv: str | None = None,
    config: dict | None = None,
    nrows: int | None = None,
    model: torch.nn.Module | None = None,
) -> dict:
    """Score a checkpoint on the March 2026 holdout + baseline; return a scorecard.

    Returns a dict containing the contract-shaped ``shadow_report`` payload, the
    per-axis dPHM & baseline metrics, the dPHM-vs-baseline deltas, and the
    acceptance gate verdict. Performs holdout-isolation and contract-validation
    STOP-condition checks.
    """
    cfg = config or {}
    dcfg = cfg.get("data", {})
    window = int(dcfg.get("window", 10))
    horizon = int(dcfg.get("horizon", 1))
    stride = int(dcfg.get("stride", 1))

    manifest = json.loads(Path(split_manifest).read_text())
    isolation = assert_holdout_isolated(manifest, holdout_key=holdout_key)

    stats = load_stats(norm_stats)
    active_axes = list(stats["active_axes"])

    march_path = _resolve_march_csv(march_csv)
    holdout = MarchHoldoutWindows(
        stats,
        csv_path=march_path,
        window=window,
        horizon=horizon,
        stride=stride,
        nrows=nrows,
    )
    X, Y = holdout.arrays()
    n_windows = X.shape[0]
    if n_windows == 0:
        raise ValueError(
            "STOP: March 2026 holdout produced 0 scorable windows "
            "(check gap threshold / window length vs available rows)"
        )

    # --- dPHM predictions ---
    if model is None:
        model = TCN_DPHM.from_norm_stats(stats)
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
    model.eval()
    with torch.no_grad():
        x_t = torch.as_tensor(X, dtype=torch.float32)
        dphm_pred = model(x_t).cpu().numpy()

    # --- baseline predictions (identical holdout windows) ---
    if baseline != PERSISTENCE_NAME:
        raise ValueError(f"unsupported baseline {baseline!r}; only {PERSISTENCE_NAME}")
    base_pred = persistence_predict(X)

    mu = holdout._mu
    sigma = holdout._sigma
    dphm_metrics = score_predictions(dphm_pred, Y, active_axes, mu=mu, sigma=sigma)
    base_metrics = score_predictions(base_pred, Y, active_axes, mu=mu, sigma=sigma)

    # --- contract-shaped report (continuous axes only carry MSE/MAE) ---
    mse_by_axis = {
        a: dphm_metrics[a]["mse"]
        for a in active_axes
        if a in CONTINUOUS_AXES
    }
    mae_by_axis = {
        a: dphm_metrics[a]["mae"]
        for a in active_axes
        if a in CONTINUOUS_AXES
    }
    report = build_shadow_report(
        mse_by_axis=mse_by_axis,
        mae_by_axis=mae_by_axis,
        prediction_axes=[a for a in active_axes],
        observation_count=n_windows,
        timestamp=holdout.date_range["start"],
        warnings=[
            "advisory scorecard: offline evaluation only, never drives actuation",
            f"{MASKED_AXIS} reported N/A (no backing telemetry column / masked)",
        ],
    )
    shadow_payload = report.to_dict()
    # STOP-condition guard: payload MUST validate against the real contract.
    validate_shadow_report_shape(shadow_payload)

    # --- acceptance gate ---
    thresholds = AcceptanceThresholds.from_config(cfg)
    gate = evaluate_gate(dphm_metrics, base_metrics, thresholds=thresholds)

    # --- per-axis dPHM-vs-baseline deltas ---
    deltas: dict[str, dict] = {}
    for axis in active_axes:
        d = dphm_metrics[axis]
        b = base_metrics[axis]
        if axis in CONTINUOUS_AXES:
            deltas[axis] = {
                "dphm_mse": d["mse"],
                "baseline_mse": b["mse"],
                "mse_improvement": b["mse"] - d["mse"],
                "beats_baseline": d["mse"] < b["mse"],
            }
        elif axis in BINARY_AXES:
            deltas[axis] = {
                "dphm_accuracy": d["accuracy"],
                "baseline_accuracy": b["accuracy"],
                "beats_baseline": (
                    d["accuracy"] is not None
                    and b["accuracy"] is not None
                    and d["accuracy"] > b["accuracy"]
                ),
            }

    scorecard = {
        "sprint": "AOPSO Sprint 25",
        "benchmark": "LOCKED March 2026 holdout",
        "advisory_only": True,
        "checkpoint": str(checkpoint),
        "split_manifest": str(split_manifest),
        "norm_stats": str(norm_stats),
        "march_csv": str(march_path),
        "holdout_key": holdout_key,
        "holdout_isolation": isolation,
        "march_2026_rows_loaded": holdout.n_rows,
        "march_2026_windows_scored": n_windows,
        "holdout_date_range": holdout.date_range,
        "active_axes": active_axes,
        "continuous_axes": sorted(a for a in active_axes if a in CONTINUOUS_AXES),
        "binary_axes": sorted(a for a in active_axes if a in BINARY_AXES),
        "masked_axes": {MASKED_AXIS: "N/A"},
        "baseline": baseline,
        "dphm_metrics": dphm_metrics,
        "baseline_metrics": base_metrics,
        "dphm_vs_baseline": deltas,
        "acceptance_gate": gate.to_dict(),
        "shadow_report": shadow_payload,
        "safety": {
            "evaluation_mode": "offline_only",
            "write_path": "scorecard_json_only",
            "influences_control": False,
            "site_integration_allowed": False,
            "scorecard_role": "advisory_evidence_only",
            "fail_blocks_packaging": True,
        },
    }
    return scorecard


def _print_summary(scorecard: dict) -> None:
    n = scorecard["march_2026_windows_scored"]
    rows = scorecard["march_2026_rows_loaded"]
    print(f"=== March 2026 LOCKED holdout ({rows} rows, {n} windows) ===")
    print(f"{'axis':<22}{'MSE(norm)':>11}{'MAE(norm)':>11}{'baseline_MSE':>14}{'beats':>8}")
    dphm = scorecard["dphm_metrics"]
    base = scorecard["baseline_metrics"]
    for axis in scorecard["continuous_axes"]:
        d = dphm[axis]
        b = base[axis]
        beats = "yes" if d["mse"] < b["mse"] else "no"
        print(f"{axis:<22}{d['mse']:>11.4f}{d['mae']:>11.4f}{b['mse']:>14.4f}{beats:>8}")
    for axis in scorecard["binary_axes"]:
        d = dphm[axis]
        b = base[axis]
        beats = "yes" if (d["accuracy"] or 0) > (b["accuracy"] or 0) else "no"
        print(f"{axis+' (acc)':<22}{d['accuracy']:>11.4f}{'-':>11}{b['accuracy']:>14.4f}{beats:>8}")
    print(f"{MASKED_AXIS:<22}{'N/A':>11}{'N/A':>11}{'N/A':>14}{'N/A':>8}")
    gate = scorecard["acceptance_gate"]
    verdict = gate["verdict"]
    suffix = "good enough to package -> Sprint 26 unblocked" if verdict == "PASS" else "DO NOT package -> iterate training (Sprint 24)"
    print(f"GATE: {verdict} ({suffix})")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AOPSO Sprint 25 offline evaluation vs LOCKED March 2026 benchmark"
    )
    parser.add_argument(
        "--checkpoint", default="data/models/yilan_dphm_v1/model_best.pt"
    )
    parser.add_argument(
        "--split-manifest", default="data/splits/yilan_2025_split_v1.json"
    )
    parser.add_argument(
        "--norm-stats", default="data/normalization/yilan_2025_train_stats.json"
    )
    parser.add_argument("--holdout-key", default="holdout_march2026")
    parser.add_argument("--baseline", default=PERSISTENCE_NAME)
    parser.add_argument(
        "--output", default="data/eval/yilan_dphm_v1/march2026_scorecard.json"
    )
    parser.add_argument(
        "--march-csv",
        default=None,
        help="Override path to the 2026 CSV (default: $YILAN_2026_CSV or built-in)",
    )
    parser.add_argument("--config", default="configs/yilan_dphm_v1.yaml")
    parser.add_argument("--nrows", type=int, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    cfg = load_config(args.config) if args.config and Path(args.config).exists() else {}

    scorecard = evaluate(
        checkpoint=args.checkpoint,
        split_manifest=args.split_manifest,
        norm_stats=args.norm_stats,
        holdout_key=args.holdout_key,
        baseline=args.baseline,
        march_csv=args.march_csv,
        config=cfg,
        nrows=args.nrows,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scorecard, indent=2) + "\n")

    _print_summary(scorecard)
    print(f"scorecard -> {out}")
    # Exit code mirrors the gate so CI can branch on packaging readiness.
    return 0 if scorecard["acceptance_gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
