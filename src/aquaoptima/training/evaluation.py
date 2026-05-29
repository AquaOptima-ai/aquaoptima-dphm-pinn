"""Offline evaluation harness vs the LOCKED March 2026 benchmark.

Sprint 25 introduced this harness; **Sprint 26** reworks it for the
residual-over-persistence reframe and multi-horizon scoring:

* **Residual decoding** -- when the checkpoint was trained with
  ``target_mode="residual"`` the model emits a normalized DELTA. The absolute
  prediction is reconstructed as ``last_value + Delta_hat`` and then
  inverse-transformed (z-score un-normalized) to physical units. Absolute mode
  is still supported for comparison.
* **Absolute-value metrics** -- per-axis MSE/MAE are now reported in PHYSICAL
  (de-normalized) units so they are directly comparable to Sprint 25 and have
  engineering meaning, alongside the explicit dPHM-vs-persistence deltas.
* **Multi-horizon sweep** -- ``--horizons 1 5 15 30`` (60s cadence, so steps ==
  minutes) re-scores the holdout at each horizon. Persistence decays as the
  horizon grows; the packaging gate is evaluated at every horizon.
* **Binary decode fix (DEFECT 3)** -- genuine BCE axes (listed in
  ``BINARY_AXES``) are decoded via ``sigmoid(logit) >= 0.5`` and gated on
  BALANCED accuracy / F1, not raw accuracy. This sprint ``BINARY_AXES`` is
  EMPTY (node_status reclassified continuous, edge_status dropped), so the
  binary branch is vestigial but kept correct for future re-enablement.

Holdout construction / isolation are unchanged from Sprint 25 (read the 2026
CSV, filter to 2026-03, normalize with TRAIN stats, gap-aware windows; re-assert
the March window does not intersect any train/val day).

CRITICAL HONESTY: this harness reports whatever the model actually scores. No
hardcoded / illustrative metric values. A FAIL is a valid outcome.

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
from .metrics import binary_classification_metrics
from .normalization import load_stats

__all__ = [
    "MarchHoldoutWindows",
    "score_predictions",
    "reconstruct_absolute",
    "evaluate",
    "evaluate_multi_horizon",
    "assert_holdout_isolated",
    "main",
    "DEFAULT_MARCH_CSV",
    "YILAN_2026_CSV_ENV",
    "DEFAULT_HORIZONS",
]

DEFAULT_MARCH_CSV = (
    "/home/hunter_lin/projects/yilan-site-model-testing/"
    "yearlong_drive/source1_2026.csv"
)
YILAN_2026_CSV_ENV = "YILAN_2026_CSV"

MASKED_AXIS = "edge_valve_position"

# Sprint 26 multi-horizon sweep (60s cadence -> steps == minutes).
DEFAULT_HORIZONS: tuple[int, ...] = (1, 5, 15, 30)


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

    def arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return ``(X, Y, last)`` normalized arrays.

        ``X``: ``[n_windows, window, n_axes]`` (normalized input windows);
        ``Y``: ``[n_windows, n_axes]`` (normalized ABSOLUTE target at ``t+h``);
        ``last``: ``[n_windows, n_axes]`` (normalized last input step ==
        persistence prediction / residual anchor).

        ``Y`` is always the absolute target regardless of the model's
        ``target_mode``; residual reconstruction (``last + Delta_hat``) happens
        in the scorer. NaNs are zero-filled after normalization (consistent with
        training).
        """
        xs: list[np.ndarray] = []
        ys: list[np.ndarray] = []
        lasts: list[np.ndarray] = []
        for start in self._starts:
            w_end = start + self.window
            t_idx = w_end + self.horizon - 1
            x_raw = self.features[start:w_end, :]
            y_raw = self.features[t_idx, :]
            x = (x_raw - self._mu) / self._sigma
            y = (y_raw - self._mu) / self._sigma
            x = np.nan_to_num(x, nan=0.0)
            xs.append(x)
            ys.append(np.nan_to_num(y, nan=0.0))
            lasts.append(x[-1, :])
        if not xs:
            n_axes = len(self.active_axes)
            return (
                np.zeros((0, self.window, n_axes), dtype=float),
                np.zeros((0, n_axes), dtype=float),
                np.zeros((0, n_axes), dtype=float),
            )
        return (
            np.stack(xs).astype(float),
            np.stack(ys).astype(float),
            np.stack(lasts).astype(float),
        )


# --------------------------------------------------------------------------- #
# Prediction reconstruction (residual / absolute -> physical units)
# --------------------------------------------------------------------------- #
def reconstruct_absolute(
    model_out: np.ndarray,
    last_norm: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
    *,
    target_mode: str,
    active_axes: list[str],
    binary_axes: Iterable[str] = (),
) -> np.ndarray:
    """Turn raw model output into ABSOLUTE (physical-unit) predictions.

    Parameters
    ----------
    model_out
        Raw model output ``[N, n_axes]``. For ``target_mode="residual"`` this is
        a normalized DELTA per axis; for ``"absolute"`` it is the normalized
        absolute value. For binary axes it is a BCE LOGIT.
    last_norm
        Normalized last-observed value ``[N, n_axes]`` (the residual anchor /
        persistence prediction).
    mu, sigma
        Per-axis z-score parameters ``[n_axes]``.
    target_mode
        ``"residual"`` or ``"absolute"``.
    binary_axes
        Axes decoded via ``sigmoid(logit) >= 0.5`` (DEFECT 3 fix). For those
        axes the output is the 0/1 class, NOT a de-normalized value.

    Returns
    -------
    np.ndarray
        ``[N, n_axes]`` absolute predictions in physical units (continuous axes)
        or 0/1 class (binary axes).
    """
    model_out = np.asarray(model_out, dtype=float)
    last_norm = np.asarray(last_norm, dtype=float)
    binset = set(binary_axes)

    if target_mode == "residual":
        abs_norm = last_norm + model_out  # last_value + Delta_hat (normalized)
    elif target_mode == "absolute":
        abs_norm = model_out
    else:
        raise ValueError(f"unknown target_mode {target_mode!r}")

    # Inverse z-score -> physical units for continuous axes.
    abs_phys = abs_norm * sigma + mu

    out = abs_phys.copy()
    for j, axis in enumerate(active_axes):
        if axis in binset:
            # DEFECT 3 fix: binary axes are BCE logits -> sigmoid -> 0/1 class.
            prob = 1.0 / (1.0 + np.exp(-model_out[:, j]))
            out[:, j] = (prob >= 0.5).astype(float)
    return out


# --------------------------------------------------------------------------- #
# Metric computation (PHYSICAL / absolute units)
# --------------------------------------------------------------------------- #
def score_predictions(
    pred_abs: np.ndarray,
    target_abs: np.ndarray,
    active_axes: list[str],
    *,
    binary_axes: Iterable[str] = (),
) -> dict[str, dict]:
    """Per-axis metrics in PHYSICAL units.

    ``pred_abs`` / ``target_abs`` are ABSOLUTE ``[N, n_axes]`` arrays in
    ``active_axes`` column order (physical units for continuous axes; 0/1 class
    for binary axes -- see :func:`reconstruct_absolute`). Continuous axes report
    absolute MSE/MAE; binary axes report raw accuracy PLUS imbalance-aware
    balanced accuracy / F1 (DEFECT 2 fix).
    """
    pred_abs = np.asarray(pred_abs, dtype=float)
    target_abs = np.asarray(target_abs, dtype=float)
    binset = set(binary_axes)
    out: dict[str, dict] = {}
    for j, axis in enumerate(active_axes):
        p = pred_abs[:, j]
        t = target_abs[:, j]
        if axis in binset:
            p_cls = (p >= 0.5).astype(int)
            t_cls = (t >= 0.5).astype(int)
            bm = binary_classification_metrics(t_cls, p_cls)
            out[axis] = {
                "kind": "binary",
                "accuracy": bm["accuracy"],
                "balanced_accuracy": bm["balanced_accuracy"],
                "f1": bm["f1"],
                "confusion": {
                    "tp": bm["tp"],
                    "tn": bm["tn"],
                    "fp": bm["fp"],
                    "fn": bm["fn"],
                },
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


def _load_run_meta(checkpoint: str) -> dict:
    """Read sibling ``run_meta.json`` (target_mode/horizon) next to a checkpoint."""
    meta_path = Path(checkpoint).parent / "run_meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except Exception:  # pragma: no cover - defensive
            return {}
    return {}


def _score_one_horizon(
    *,
    holdout: "MarchHoldoutWindows",
    active_axes: list[str],
    binary_axes: frozenset[str],
    model: torch.nn.Module,
    target_mode: str,
    baseline: str,
    thresholds: AcceptanceThresholds,
) -> dict:
    """Score one already-built holdout (single horizon). Returns a per-horizon block."""
    X, Y, last = holdout.arrays()
    n_windows = X.shape[0]
    if n_windows == 0:
        raise ValueError(
            "STOP: March 2026 holdout produced 0 scorable windows "
            "(check gap threshold / window length vs available rows)"
        )

    mu = holdout._mu
    sigma = holdout._sigma

    # --- dPHM raw output -> reconstructed ABSOLUTE (physical) prediction ---
    model.eval()
    with torch.no_grad():
        x_t = torch.as_tensor(X, dtype=torch.float32)
        dphm_raw = model(x_t).cpu().numpy()
    dphm_abs = reconstruct_absolute(
        dphm_raw, last, mu, sigma,
        target_mode=target_mode, active_axes=active_axes, binary_axes=binary_axes,
    )

    # --- persistence baseline: predict last value (residual Delta == 0) ---
    if baseline != PERSISTENCE_NAME:
        raise ValueError(f"unsupported baseline {baseline!r}; only {PERSISTENCE_NAME}")
    base_raw = persistence_predict(X)  # normalized last step == last
    # Persistence in residual space is Delta=0; in absolute space it's `last`.
    base_abs = reconstruct_absolute(
        np.zeros_like(base_raw), last, mu, sigma,
        target_mode="residual", active_axes=active_axes, binary_axes=binary_axes,
    )

    # --- ground truth ABSOLUTE (physical) values ---
    target_abs = reconstruct_absolute(
        np.zeros_like(Y), Y, mu, sigma,
        target_mode="residual", active_axes=active_axes, binary_axes=binary_axes,
    )
    # NB: target reconstruction uses Y as the "last" anchor with Delta=0 so that
    # `abs_norm = Y` and inverse-transform yields the true physical target; for
    # binary axes the sigmoid path keys off model_out (zeros) -> harmless, so we
    # recompute the binary truth class directly from Y below.
    for j, axis in enumerate(active_axes):
        if axis in binary_axes:
            t_norm = Y[:, j]
            t_phys = t_norm * sigma[j] + mu[j]
            target_abs[:, j] = (t_phys >= 0.5).astype(float)

    dphm_metrics = score_predictions(
        dphm_abs, target_abs, active_axes, binary_axes=binary_axes
    )
    base_metrics = score_predictions(
        base_abs, target_abs, active_axes, binary_axes=binary_axes
    )

    gate = evaluate_gate(dphm_metrics, base_metrics, thresholds=thresholds)

    # --- per-axis dPHM-vs-persistence deltas (absolute units) ---
    deltas: dict[str, dict] = {}
    for axis in active_axes:
        d = dphm_metrics[axis]
        b = base_metrics[axis]
        if axis in binary_axes:
            deltas[axis] = {
                "dphm_balanced_accuracy": d.get("balanced_accuracy"),
                "baseline_balanced_accuracy": b.get("balanced_accuracy"),
                "dphm_f1": d.get("f1"),
                "baseline_f1": b.get("f1"),
                "beats_baseline": (
                    d.get("balanced_accuracy") is not None
                    and b.get("balanced_accuracy") is not None
                    and d["balanced_accuracy"] > b["balanced_accuracy"]
                ),
            }
        else:
            deltas[axis] = {
                "dphm_mse": d["mse"],
                "baseline_mse": b["mse"],
                "mse_improvement": b["mse"] - d["mse"],
                "dphm_mae": d["mae"],
                "baseline_mae": b["mae"],
                "beats_baseline": d["mse"] < b["mse"],
            }

    return {
        "horizon": holdout.horizon,
        "windows_scored": n_windows,
        "metric_space": "absolute_physical_units",
        "dphm_metrics": dphm_metrics,
        "baseline_metrics": base_metrics,
        "dphm_vs_baseline": deltas,
        "acceptance_gate": gate.to_dict(),
    }


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
    target_mode: str | None = None,
    horizon: int | None = None,
) -> dict:
    """Score a checkpoint at ONE horizon on the March 2026 holdout; return a scorecard.

    Sprint 26: predictions are reconstructed to ABSOLUTE physical units (residual
    or absolute mode) and metrics are reported in those units, with explicit
    dPHM-vs-persistence deltas. ``target_mode`` / ``horizon`` fall back to the
    checkpoint's ``run_meta.json``, then the config, then residual / h=1.
    """
    cfg = config or {}
    dcfg = cfg.get("data", {})
    window = int(dcfg.get("window", 10))
    stride = int(dcfg.get("stride", 1))

    meta = _load_run_meta(checkpoint)
    target_mode = str(
        target_mode
        if target_mode is not None
        else meta.get("target_mode", dcfg.get("target_mode", "residual"))
    )
    horizon = int(
        horizon
        if horizon is not None
        else meta.get("horizon", dcfg.get("horizon", 1))
    )

    manifest = json.loads(Path(split_manifest).read_text())
    isolation = assert_holdout_isolated(manifest, holdout_key=holdout_key)

    stats = load_stats(norm_stats)
    active_axes = list(stats["active_axes"])
    binary_axes = frozenset(a for a in active_axes if a in BINARY_AXES)

    march_path = _resolve_march_csv(march_csv)
    holdout = MarchHoldoutWindows(
        stats,
        csv_path=march_path,
        window=window,
        horizon=horizon,
        stride=stride,
        nrows=nrows,
    )

    if model is None:
        model = TCN_DPHM.from_norm_stats(stats)
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        model.load_state_dict(state)

    thresholds = AcceptanceThresholds.from_config(cfg)
    block = _score_one_horizon(
        holdout=holdout,
        active_axes=active_axes,
        binary_axes=binary_axes,
        model=model,
        target_mode=target_mode,
        baseline=baseline,
        thresholds=thresholds,
    )
    n_windows = block["windows_scored"]
    dphm_metrics = block["dphm_metrics"]

    # --- contract-shaped report (continuous axes carry absolute MSE/MAE) ---
    mse_by_axis = {
        a: dphm_metrics[a]["mse"] for a in active_axes if a in CONTINUOUS_AXES
    }
    mae_by_axis = {
        a: dphm_metrics[a]["mae"] for a in active_axes if a in CONTINUOUS_AXES
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
            f"target_mode={target_mode}; metrics in absolute physical units; "
            f"horizon={horizon} step(s)",
        ],
    )
    shadow_payload = report.to_dict()
    validate_shadow_report_shape(shadow_payload)

    scorecard = {
        "sprint": "AOPSO Sprint 26",
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
        "target_mode": target_mode,
        "horizon": horizon,
        "metric_space": "absolute_physical_units",
        "dphm_metrics": dphm_metrics,
        "baseline_metrics": block["baseline_metrics"],
        "dphm_vs_baseline": block["dphm_vs_baseline"],
        "acceptance_gate": block["acceptance_gate"],
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


def evaluate_multi_horizon(
    *,
    checkpoint: str,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    split_manifest: str = "data/splits/yilan_2025_split_v1.json",
    norm_stats: str = "data/normalization/yilan_2025_train_stats.json",
    holdout_key: str = "holdout_march2026",
    baseline: str = PERSISTENCE_NAME,
    march_csv: str | None = None,
    config: dict | None = None,
    nrows: int | None = None,
    model: torch.nn.Module | None = None,
    target_mode: str | None = None,
) -> dict:
    """Sweep horizons (default 1/5/15/30) and produce a multi-horizon scorecard.

    Re-builds the holdout windows at each horizon and scores the SAME model.
    Reports per-horizon, per-axis absolute MSE/MAE + persistence deltas, and a
    per-horizon acceptance gate. The aggregate ``packaging_gate`` PASSes only if
    EVERY evaluated horizon passes (the bar must hold at the longer horizons too).
    """
    cfg = config or {}
    dcfg = cfg.get("data", {})
    window = int(dcfg.get("window", 10))
    stride = int(dcfg.get("stride", 1))

    meta = _load_run_meta(checkpoint)
    target_mode = str(
        target_mode
        if target_mode is not None
        else meta.get("target_mode", dcfg.get("target_mode", "residual"))
    )

    manifest = json.loads(Path(split_manifest).read_text())
    isolation = assert_holdout_isolated(manifest, holdout_key=holdout_key)

    stats = load_stats(norm_stats)
    active_axes = list(stats["active_axes"])
    binary_axes = frozenset(a for a in active_axes if a in BINARY_AXES)
    march_path = _resolve_march_csv(march_csv)
    thresholds = AcceptanceThresholds.from_config(cfg)

    if model is None:
        model = TCN_DPHM.from_norm_stats(stats)
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        model.load_state_dict(state)

    horizons = [int(h) for h in horizons]
    per_horizon: dict[str, dict] = {}
    date_range = None
    rows_loaded = 0
    for h in horizons:
        holdout = MarchHoldoutWindows(
            stats,
            csv_path=march_path,
            window=window,
            horizon=h,
            stride=stride,
            nrows=nrows,
        )
        date_range = holdout.date_range
        rows_loaded = holdout.n_rows
        per_horizon[str(h)] = _score_one_horizon(
            holdout=holdout,
            active_axes=active_axes,
            binary_axes=binary_axes,
            model=model,
            target_mode=target_mode,
            baseline=baseline,
            thresholds=thresholds,
        )

    all_pass = all(
        per_horizon[str(h)]["acceptance_gate"]["passed"] for h in horizons
    )

    return {
        "sprint": "AOPSO Sprint 26",
        "benchmark": "LOCKED March 2026 holdout (multi-horizon)",
        "advisory_only": True,
        "checkpoint": str(checkpoint),
        "split_manifest": str(split_manifest),
        "norm_stats": str(norm_stats),
        "march_csv": str(march_path),
        "holdout_key": holdout_key,
        "holdout_isolation": isolation,
        "march_2026_rows_loaded": rows_loaded,
        "holdout_date_range": date_range,
        "active_axes": active_axes,
        "continuous_axes": sorted(a for a in active_axes if a in CONTINUOUS_AXES),
        "binary_axes": sorted(a for a in active_axes if a in BINARY_AXES),
        "masked_axes": {MASKED_AXIS: "N/A"},
        "baseline": baseline,
        "target_mode": target_mode,
        "horizons": horizons,
        "metric_space": "absolute_physical_units",
        "per_horizon": per_horizon,
        "packaging_gate": {
            "verdict": "PASS" if all_pass else "FAIL",
            "passed": all_pass,
            "rule": "every evaluated horizon must pass the acceptance gate",
            "per_horizon_verdict": {
                str(h): per_horizon[str(h)]["acceptance_gate"]["verdict"]
                for h in horizons
            },
        },
        "safety": {
            "evaluation_mode": "offline_only",
            "write_path": "scorecard_json_only",
            "influences_control": False,
            "site_integration_allowed": False,
            "scorecard_role": "advisory_evidence_only",
            "fail_blocks_packaging": True,
        },
    }


def _print_summary(scorecard: dict) -> None:
    n = scorecard["march_2026_windows_scored"]
    rows = scorecard["march_2026_rows_loaded"]
    print(f"=== March 2026 LOCKED holdout ({rows} rows, {n} windows) ===")
    tm = scorecard.get("target_mode", "?")
    h = scorecard.get("horizon", "?")
    print(f"target_mode={tm}  horizon={h} step(s)  metrics=ABSOLUTE physical units")
    print(f"{'axis':<22}{'MSE(abs)':>13}{'MAE(abs)':>13}{'baseline_MSE':>15}{'beats':>8}")
    dphm = scorecard["dphm_metrics"]
    base = scorecard["baseline_metrics"]
    for axis in scorecard["continuous_axes"]:
        d = dphm[axis]
        b = base[axis]
        beats = "yes" if d["mse"] < b["mse"] else "no"
        print(f"{axis:<22}{d['mse']:>13.4f}{d['mae']:>13.4f}{b['mse']:>15.4f}{beats:>8}")
    for axis in scorecard["binary_axes"]:
        d = dphm[axis]
        b = base[axis]
        d_bal = d.get("balanced_accuracy") or 0.0
        b_bal = b.get("balanced_accuracy") or 0.0
        beats = "yes" if d_bal > b_bal else "no"
        print(
            f"{axis+' (bal_acc)':<22}{d_bal:>13.4f}{'-':>13}{b_bal:>15.4f}{beats:>8}"
        )
    print(f"{MASKED_AXIS:<22}{'N/A':>13}{'N/A':>13}{'N/A':>15}{'N/A':>8}")
    gate = scorecard["acceptance_gate"]
    verdict = gate["verdict"]
    suffix = "good enough to package -> Sprint 27 unblocked" if verdict == "PASS" else "DO NOT package -> iterate / pivot objective"
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
