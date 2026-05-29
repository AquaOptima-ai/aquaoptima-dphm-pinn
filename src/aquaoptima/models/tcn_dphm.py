"""TCN-based multi-task dPHM regression model (AOPSO Sprint 24).

``TCN_DPHM`` is a 3-layer dilated Temporal Convolutional Network encoder
followed by a linear multi-task head. It consumes a normalized input window
of shape ``[B, window, n_features]`` and predicts the next-step value of every
active canonical axis, ``[B, n_axes]``.

DIMENSION REALITY (vs roadmap)
------------------------------
The Sprint 24 roadmap guessed "11 input features -> 8 output axes". The Sprint
23 dataset/normalization pipeline actually exposes EXACTLY 8 *active* canonical
axes (``edge_valve_position`` has 0% coverage at the Yilan site and is
excluded). ``YilanTimeSeriesDataset`` emits one feature per active axis, so the
real shape is ``[B, window, 8] -> [B, 8]``: input feature dim == output axis
dim == number of active axes.

To avoid magic numbers, the canonical constructor is
:meth:`TCN_DPHM.from_norm_stats`, which derives both ``n_features`` and
``n_axes`` from the cached normalization stats (its ``active_axes`` list). The
plain ``__init__`` still takes explicit dims for testing/flexibility, but the
training pipeline always derives them from the data contract.

Safety: offline only. Pure ``torch.nn`` module, no edge imports, no I/O, no
control influence, no ONNX export (deferred to Sprint 26). The forward pass is
inert numerics on tensors.
"""

from __future__ import annotations

import torch
import torch.nn as nn

__all__ = ["TCN_DPHM", "TCNBlock"]


class TCNBlock(nn.Module):
    """One dilated causal 1D conv block with residual connection.

    Causal padding (``(kernel_size - 1) * dilation`` on the left, trimmed on
    the right) keeps the temporal length identical to the input so blocks can
    be stacked and residually added.
    """

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int,
        dilation: int,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        self.pad = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(
            in_channels,
            out_channels,
            kernel_size=kernel_size,
            dilation=dilation,
            padding=self.pad,
        )
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)
        # 1x1 conv to match channels for the residual path when needed.
        self.downsample = (
            nn.Conv1d(in_channels, out_channels, kernel_size=1)
            if in_channels != out_channels
            else None
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # [B, C_in, T]
        out = self.conv(x)
        if self.pad:
            out = out[..., : -self.pad]  # trim right -> causal, length preserved
        out = self.dropout(self.relu(out))
        res = x if self.downsample is None else self.downsample(x)
        return out + res


class TCN_DPHM(nn.Module):
    """3-layer dilated TCN encoder + linear multi-task head.

    Parameters
    ----------
    n_features
        Number of input features per timestep (== number of active axes).
    n_axes
        Number of output axes to predict. Defaults to ``n_features`` because
        the dPHM task predicts the next-step value of every active axis.
    channels
        Hidden channel width of the TCN encoder.
    kernel_size
        Conv kernel size.
    dropout
        Dropout probability inside TCN blocks.
    """

    def __init__(
        self,
        n_features: int,
        n_axes: int | None = None,
        *,
        channels: int = 32,
        kernel_size: int = 3,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        if n_features < 1:
            raise ValueError("n_features must be >= 1")
        n_axes = int(n_features) if n_axes is None else int(n_axes)
        if n_axes < 1:
            raise ValueError("n_axes must be >= 1")

        self.n_features = int(n_features)
        self.n_axes = n_axes
        self.channels = int(channels)
        self.kernel_size = int(kernel_size)

        # Exactly three dilated blocks (dilations 1, 2, 4 -> receptive field
        # grows exponentially with depth).
        dilations = (1, 2, 4)
        blocks: list[nn.Module] = []
        in_ch = self.n_features
        for d in dilations:
            blocks.append(
                TCNBlock(in_ch, self.channels, kernel_size, dilation=d, dropout=dropout)
            )
            in_ch = self.channels
        self.tcn = nn.Sequential(*blocks)

        # Linear multi-task head: pooled encoder features -> per-axis output.
        self.head = nn.Linear(self.channels, self.n_axes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """``x``: ``[B, window, n_features]`` -> ``[B, n_axes]``."""
        if x.dim() != 3:
            raise ValueError(
                f"expected [B, window, n_features], got shape {tuple(x.shape)}"
            )
        if x.shape[-1] != self.n_features:
            raise ValueError(
                f"input feature dim {x.shape[-1]} != model n_features {self.n_features}"
            )
        # Conv1d wants [B, C, T]; our axes are channels, window is time.
        h = x.transpose(1, 2)  # [B, n_features, window]
        h = self.tcn(h)  # [B, channels, window]
        h = h[..., -1]  # take last timestep -> [B, channels]
        return self.head(h)  # [B, n_axes]

    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())

    @classmethod
    def from_norm_stats(
        cls,
        stats: dict,
        *,
        channels: int = 32,
        kernel_size: int = 3,
        dropout: float = 0.0,
    ) -> "TCN_DPHM":
        """Build a model whose dims are derived from normalization stats.

        ``n_features`` and ``n_axes`` both equal the number of *active* axes in
        the stats contract (8 for Yilan 2025), NOT a hardcoded constant.
        """
        active = list(stats["active_axes"])
        n = len(active)
        if n < 1:
            raise ValueError("normalization stats expose no active axes")
        return cls(
            n_features=n,
            n_axes=n,
            channels=channels,
            kernel_size=kernel_size,
            dropout=dropout,
        )
