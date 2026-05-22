"""Mass and energy residual primitives for the dPHM core.

Sign conventions:

* ``mass_residual`` follows the incidence-matrix convention from
  :mod:`aquaoptima.dphm.incidence`: ``A @ flows - demand`` per node.
* ``pipe_energy_residual`` is ``h_upstream - h_downstream - h_loss`` so that a
  signed Hazen-Williams loss closes the energy balance without sign juggling.
* ``pump_energy_residual`` is ``h_downstream - h_upstream - pump_gain`` so that
  a positive ``pump_gain`` (head added) closes the balance when downstream
  head exceeds upstream head.
"""

from __future__ import annotations

import torch

from .incidence import node_flow_balance


def mass_residual(
    edge_index: torch.Tensor,
    flows: torch.Tensor,
    demands: torch.Tensor,
    num_nodes: int,
) -> torch.Tensor:
    """Nodal mass-balance residual, see :func:`node_flow_balance`."""
    return node_flow_balance(edge_index, flows, demands, num_nodes)


def pipe_energy_residual(
    head_upstream: torch.Tensor,
    head_downstream: torch.Tensor,
    head_loss: torch.Tensor,
) -> torch.Tensor:
    """Energy residual across a pipe: ``h_u - h_d - h_loss``."""
    return head_upstream - head_downstream - head_loss


def pump_energy_residual(
    head_upstream: torch.Tensor,
    head_downstream: torch.Tensor,
    pump_gain: torch.Tensor,
) -> torch.Tensor:
    """Energy residual across a pump: ``h_d - h_u - pump_gain``."""
    return head_downstream - head_upstream - pump_gain
