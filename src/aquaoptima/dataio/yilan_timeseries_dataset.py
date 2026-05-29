"""Gap-aware sliding-window PyTorch Dataset for Yilan 2025 (AOPSO Sprint 23).

``YilanTimeSeriesDataset`` produces fixed-length input windows over the active
canonical axes, with a 1-step prediction horizon. Windows never span a temporal
gap boundary (gaps from the profiler / inter-sample spacing > 5 min): a window
is only emitted if every sample inside the window-plus-horizon span is
contiguous (60s cadence, no gap break).

Cached z-score normalization (``data/normalization/yilan_2025_train_stats.json``)
is applied to every emitted window.

Safety: offline_only, write_path=none, influences_control=false,
site_integration_allowed=false. No edge imports, no training. Uses only
pandas/numpy/stdlib + ``torch.utils.data``.
"""

from __future__ import annotations

import os
from typing import Sequence

import numpy as np
import torch
from torch.utils.data import Dataset

from .yilan_axis_map import CANONICAL_AXIS_TO_COLUMN, TIMESTAMP_COLUMN
from .yilan_profiler import GAP_THRESHOLD_SECONDS, derive_mode, load_frame
from ..training.normalization import apply_normalization, load_stats


def _split_row_indices(manifest: dict, split_key: str) -> list[int]:
    split = manifest["splits"][split_key]
    indices: list[int] = []
    for start, end in split.get("row_index_ranges", []):
        indices.extend(range(int(start), int(end) + 1))
    return indices


class YilanTimeSeriesDataset(Dataset):
    """Gap-aware sliding-window dataset over active canonical axes.

    Parameters
    ----------
    manifest
        Loaded split manifest (from ``split_builder``).
    stats
        Loaded normalization stats (from ``normalization``).
    split_key
        Which split's rows to draw from (``"train"`` / ``"val"`` / ...).
    window
        Input window length (timesteps). Default 10.
    horizon
        Prediction horizon (timesteps ahead). Default 1.
    stride
        Window start stride. Default 1.
    target_mode
        ``"residual"`` (Sprint 26 default) or ``"absolute"``.

        * ``"absolute"`` (Sprint 24/25 behaviour): the target is the normalized
          value at ``t+h`` -- the model predicts the absolute next value.
        * ``"residual"`` (Sprint 26, residual-over-persistence): the target is
          the normalized DELTA ``Delta = x_norm[t+h] - x_norm[t_last]`` where
          ``t_last`` is the last input step of the window. The model predicts
          the *change* from the last observed value; the final absolute
          prediction is ``last_value + Delta_hat``. This makes the persistence
          baseline equivalent to predicting ``Delta = 0`` by construction, so
          the model can only score by *beating* last-value. Because both terms
          are z-scored with the same per-axis sigma, the normalized residual
          equals ``(x_raw[t+h] - x_raw[t_last]) / sigma`` -- inverse-transforming
          back to an absolute value uses ``last_raw + Delta_norm * sigma``.
    csv_path / nrows
        Forwarded to ``load_frame``.
    """

    VALID_TARGET_MODES = ("absolute", "residual")

    def __init__(
        self,
        manifest: dict,
        stats: dict,
        *,
        split_key: str = "train",
        window: int = 10,
        horizon: int = 1,
        stride: int = 1,
        target_mode: str = "residual",
        csv_path: str | os.PathLike[str] | None = None,
        nrows: int | None = None,
        gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
    ) -> None:
        if window < 1 or horizon < 1 or stride < 1:
            raise ValueError("window, horizon, stride must all be >= 1")
        if target_mode not in self.VALID_TARGET_MODES:
            raise ValueError(
                f"target_mode must be one of {self.VALID_TARGET_MODES}, "
                f"got {target_mode!r}"
            )

        self.window = window
        self.horizon = horizon
        self.stride = stride
        self.target_mode = target_mode

        self.active_axes: list[str] = list(stats["active_axes"])
        if not self.active_axes:
            raise ValueError("no active axes in normalization stats")

        df = load_frame(csv_path, nrows=nrows)
        row_idx = _split_row_indices(manifest, split_key)
        row_idx = [i for i in row_idx if 0 <= i < len(df)]
        sub = df.iloc[row_idx].reset_index(drop=True)

        # Build the [N, n_active_axes] feature matrix in active-axis order.
        cols = [CANONICAL_AXIS_TO_COLUMN[a] for a in self.active_axes]
        feats = sub[cols].apply(lambda c: c.astype(float)).to_numpy(dtype=float)
        self.features = feats
        self.timestamps = sub[TIMESTAMP_COLUMN].reset_index(drop=True)

        # Identify gap boundaries WITHIN the selected rows. A boundary sits
        # between row i-1 and row i when their spacing exceeds the threshold.
        secs = self.timestamps.diff().dt.total_seconds().to_numpy()
        # boundary_after[i] True => there is a gap between row i and row i+1.
        n = len(sub)
        self.gap_after = np.zeros(n, dtype=bool)
        for i in range(1, n):
            if np.isfinite(secs[i]) and secs[i] > gap_threshold_seconds:
                self.gap_after[i - 1] = True

        # Precompute valid window start indices that do NOT span a gap.
        span = window + horizon  # samples consumed by one (input + target)
        self._starts: list[int] = []
        for start in range(0, n - span + 1, stride):
            end = start + span - 1  # last index touched (target)
            # Reject if any contiguous step inside [start, end] crosses a gap.
            if np.any(self.gap_after[start:end]):
                continue
            self._starts.append(start)

        self._mu = np.array(
            [stats["stats"][a]["mu"] for a in self.active_axes], dtype=float
        )
        self._sigma = np.array(
            [stats["stats"][a]["sigma"] for a in self.active_axes], dtype=float
        )
        self._stats = stats

    @classmethod
    def from_paths(
        cls,
        split_manifest_path: str | os.PathLike[str],
        stats_path: str | os.PathLike[str],
        **kwargs,
    ) -> "YilanTimeSeriesDataset":
        import json
        from pathlib import Path

        manifest = json.loads(Path(split_manifest_path).read_text())
        stats = load_stats(stats_path)
        return cls(manifest, stats, **kwargs)

    @property
    def n_active_axes(self) -> int:
        return len(self.active_axes)

    def __len__(self) -> int:
        return len(self._starts)

    def __getitem__(self, idx: int):
        start = self._starts[idx]
        w_end = start + self.window
        t_idx = w_end + self.horizon - 1

        x_raw = self.features[start:w_end, :]  # [window, n_active_axes]
        y_raw = self.features[t_idx, :]  # [n_active_axes]

        x = (x_raw - self._mu) / self._sigma  # normalized window
        y_abs = (y_raw - self._mu) / self._sigma  # normalized absolute target

        if self.target_mode == "residual":
            # Delta = x_norm[t+h] - x_norm[t_last]. The last input step is the
            # persistence prediction; the residual target is what must be ADDED
            # to it. Persistence == predicting Delta=0. NaNs in either term
            # collapse to a 0 residual after nan_to_num (consistent w/ training).
            last_norm = x[-1, :]
            y = y_abs - last_norm
        else:  # "absolute"
            y = y_abs

        x_t = torch.as_tensor(np.nan_to_num(x, nan=0.0), dtype=torch.float32)
        y_t = torch.as_tensor(np.nan_to_num(y, nan=0.0), dtype=torch.float32)
        return x_t, y_t

    def window_time_span(self, idx: int) -> tuple:
        """Return (start_ts, end_ts) of the input window for diagnostics."""
        start = self._starts[idx]
        w_end = start + self.window - 1
        return (self.timestamps.iloc[start], self.timestamps.iloc[w_end])

    def window_spans_gap(self, idx: int) -> bool:
        """True if the window+horizon span of ``idx`` crosses a gap boundary."""
        start = self._starts[idx]
        end = start + self.window + self.horizon - 1
        return bool(np.any(self.gap_after[start:end]))


__all__ = ["YilanTimeSeriesDataset"]
