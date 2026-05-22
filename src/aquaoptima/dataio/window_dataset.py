"""Sliding-window dataset over a :class:`TelemetrySeries`.

Each item indexes a 32-step window of historical features and the
next-step target. The window covers telemetry steps ``[idx, idx + window)``
and the target is step ``idx + window``. By construction no item ever
exposes the model to its own target step in the input window
(no future leakage).

Per-window feature layout (matches
:mod:`aquaoptima.topology.graph_builder`):

``x_seq[t, n, k]``:
    k=0 → demand at step (idx + t), node n
    k=1 → pressure at step (idx + t), node n
"""

from __future__ import annotations

import torch
from torch.utils.data import Dataset

from .telemetry import TelemetrySeries

NODE_FEATURE_DIM = 2


class WindowDataset(Dataset):
    """Sliding 32-step windows over a :class:`TelemetrySeries`.

    Accepts any source-shaped telemetry series — synthetic, CSV, PLC,
    PAC, historian, MQTT — because the dataset only depends on the
    canonical tensor contract of :class:`TelemetrySeries`.
    """

    def __init__(self, series: TelemetrySeries, window: int = 32) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        if series.num_steps < window + 1:
            raise ValueError(
                f"series has {series.num_steps} steps; need >= window + 1 = "
                f"{window + 1}"
            )
        self.series = series
        self.window = int(window)
        self._length = series.num_steps - self.window

    @property
    def node_feature_dim(self) -> int:
        return NODE_FEATURE_DIM

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        if idx < 0 or idx >= self._length:
            raise IndexError(
                f"index {idx} out of range for dataset of length {self._length}"
            )

        end = idx + self.window
        demand_window = self.series.demand[idx:end]      # [T, N]
        pressure_window = self.series.pressure[idx:end]  # [T, N]
        x_seq = torch.stack([demand_window, pressure_window], dim=-1)  # [T, N, 2]

        return {
            "x_seq": x_seq,
            "target_pressure": self.series.pressure[end].clone(),
            "target_flow": self.series.flow[end].clone(),
            "target_demand": self.series.demand[end].clone(),
        }
