"""Multi-axis training loss for the dPHM model (AOPSO Sprint 24).

``MultiAxisLoss`` combines, per active canonical axis:

* **MSE** for the 6 continuous axes
  (``edge_flow``, ``edge_power``, ``edge_pump_speed``,
  ``node_demand``, ``node_level``, ``node_pressure``), and
* **BCE-with-logits** for the 2 binary axes (``node_status``, ``edge_status``).

Each axis carries a scalar weight (default ``1.0``). An axis can be *masked /
excluded* (weight 0, or listed in ``excluded_axes``); a masked axis contributes
EXACTLY zero to the total and its gradient. The routing (which axis is binary
vs continuous) is derived from axis NAMES against the active-axis ordering, not
from magic column indices, so it stays correct if the dataset's active-axis set
changes.

The reduction is a weighted mean over the *active, unmasked* axes, yielding a
single non-negative scalar.

Safety: offline only. Pure ``torch.nn`` numerics, no edge imports, no I/O.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import torch
import torch.nn as nn
import torch.nn.functional as F

# Single source of truth for axis taxonomy (Sprint 26): import from the axis
# map rather than redefining here, so loss / trainer / evaluation cannot drift
# apart. ``BINARY_AXES`` is EMPTY by default this sprint (node_status
# reclassified continuous, edge_status dropped as a binary target); the BCE
# routing below remains correct for any axis re-listed in ``BINARY_AXES``.
from ..dataio.yilan_axis_map import BINARY_AXES, CONTINUOUS_AXES

__all__ = ["MultiAxisLoss", "BINARY_AXES", "CONTINUOUS_AXES"]


class MultiAxisLoss(nn.Module):
    """Weighted per-axis MSE (continuous) + BCEWithLogits (binary).

    Parameters
    ----------
    active_axes
        Ordered list of active axis names. Column ``j`` of the prediction /
        target tensors corresponds to ``active_axes[j]``.
    weights
        Optional per-axis weight mapping (axis name -> float). Missing axes
        default to ``1.0``. Set an axis weight to ``0.0`` to mask it.
    excluded_axes
        Optional iterable of axis names to force-mask (contribute 0),
        regardless of weight.
    binary_axes
        Override the set of binary (BCE) axis names. Defaults to
        :data:`BINARY_AXES`.
    """

    def __init__(
        self,
        active_axes: Sequence[str],
        *,
        weights: Mapping[str, float] | None = None,
        excluded_axes: Iterable[str] | None = None,
        binary_axes: Iterable[str] | None = None,
    ) -> None:
        super().__init__()
        self.active_axes: list[str] = list(active_axes)
        if not self.active_axes:
            raise ValueError("active_axes must be non-empty")

        self.binary_axes = (
            BINARY_AXES if binary_axes is None else frozenset(binary_axes)
        )
        excluded = set(excluded_axes or ())

        w = dict(weights or {})
        # Effective per-axis weight: explicit weight (default 1.0), forced to 0
        # for excluded axes.
        eff = []
        for axis in self.active_axes:
            wv = float(w.get(axis, 1.0))
            if axis in excluded:
                wv = 0.0
            eff.append(wv)
        # Buffers so device/dtype follow the module; not learnable params.
        self.register_buffer("_weights", torch.tensor(eff, dtype=torch.float32))
        binmask = [1.0 if a in self.binary_axes else 0.0 for a in self.active_axes]
        self.register_buffer("_is_binary", torch.tensor(binmask, dtype=torch.float32))

    @property
    def weights(self) -> dict[str, float]:
        return {a: float(w) for a, w in zip(self.active_axes, self._weights.tolist())}

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """``pred``/``target``: ``[B, n_axes]`` -> non-negative scalar."""
        if pred.shape != target.shape:
            raise ValueError(
                f"pred shape {tuple(pred.shape)} != target shape {tuple(target.shape)}"
            )
        if pred.shape[-1] != len(self.active_axes):
            raise ValueError(
                f"axis dim {pred.shape[-1]} != n active axes {len(self.active_axes)}"
            )

        w = self._weights.to(pred.dtype)  # [n_axes]
        is_bin = self._is_binary.to(pred.dtype)  # [n_axes]

        # Per-axis loss (mean over batch), no reduction across axes yet.
        # Continuous: MSE over the batch for each axis -> [n_axes]
        mse_axis = ((pred - target) ** 2).mean(dim=0)  # [n_axes]

        # Binary: BCEWithLogits over the batch for each axis -> [n_axes].
        # Targets are normalized continuous floats in the dataset; for the
        # binary axes we treat the (denormalized-sign) presence as a probability
        # target clamped to [0, 1]. We use the raw target clamped to [0,1] so
        # BCE is well-defined and 0 when pred logits match. This keeps the loss
        # finite and non-negative on real normalized data.
        bce_target = target.clamp(0.0, 1.0)
        bce_axis = F.binary_cross_entropy_with_logits(
            pred, bce_target, reduction="none"
        ).mean(dim=0)  # [n_axes]

        per_axis = is_bin * bce_axis + (1.0 - is_bin) * mse_axis  # [n_axes]
        weighted = w * per_axis

        total_w = w.sum()
        if float(total_w) <= 0.0:
            # All axes masked -> exactly zero, with grad path preserved.
            return weighted.sum() * 0.0
        return weighted.sum() / total_w
