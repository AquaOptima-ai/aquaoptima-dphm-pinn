"""Observed / virtual node masks for SCADA-style supervision.

A "sensor" node is one we believe is instrumented in the field — its
state is directly observed by SCADA. A "virtual" node is everywhere else
in the network where the dPHM-PINN must predict state without a direct
measurement. The convention here is deliberately simple: the sensor
mask is a boolean ``[N]`` tensor, and the virtual mask is its
complement.
"""

from __future__ import annotations

from typing import Iterable

import torch


def sensor_mask_from_indices(
    num_nodes: int, observed: Iterable[int]
) -> torch.Tensor:
    """Build a ``[num_nodes]`` boolean mask from a list of observed node ids.

    Raises ``ValueError`` if any id falls outside ``[0, num_nodes)``.
    """
    if num_nodes <= 0:
        raise ValueError(f"num_nodes must be positive, got {num_nodes}")
    mask = torch.zeros(num_nodes, dtype=torch.bool)
    for idx in observed:
        if idx < 0 or idx >= num_nodes:
            raise ValueError(
                f"observed index {idx} out of range [0, {num_nodes})"
            )
        mask[idx] = True
    return mask


def virtual_node_mask(sensor_mask: torch.Tensor) -> torch.Tensor:
    """Complement of ``sensor_mask`` — nodes the model must infer."""
    if sensor_mask.dtype != torch.bool:
        raise ValueError(
            f"sensor_mask must be bool, got dtype={sensor_mask.dtype}"
        )
    return ~sensor_mask
