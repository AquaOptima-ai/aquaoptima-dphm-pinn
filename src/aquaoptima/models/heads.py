"""Output heads for the dPHM-PINN.

Heads are deliberately thin linear-or-2-layer MLPs. Sprint 6 extended
them to broadcast over an optional leading batch dimension:

* ``[N, hidden]`` → ``[N]`` / ``[E]`` / ``[K]`` (legacy)
* ``[B, N, hidden]`` → ``[B, N]`` / ``[B, E]`` / ``[B, K]``

Batching is implemented by leaving the linear projections rank-agnostic
and only specialising the node-pair gather in :class:`FlowHead` and the
node-pool in :class:`SetpointAdvisoryHead`.
"""

from __future__ import annotations

import torch
from torch import nn


class PressureHead(nn.Module):
    """Per-node pressure prediction: ``[N, hidden] -> [N]``."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.proj = nn.Linear(hidden_dim, 1)

    def forward(self, h_node: torch.Tensor) -> torch.Tensor:
        return self.proj(h_node).squeeze(-1)


class FlowHead(nn.Module):
    """Per-edge flow prediction.

    Concatenates source and target node embeddings, projects to scalar
    flow. Output shape: ``[E]`` (unbatched) or ``[B, E]`` (batched).
    """

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.proj = nn.Sequential(
            nn.Linear(2 * hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, h_node: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        src, dst = edge_index[0], edge_index[1]
        if h_node.dim() == 2:
            edge_feat = torch.cat([h_node[src], h_node[dst]], dim=-1)
            return self.proj(edge_feat).squeeze(-1)
        if h_node.dim() == 3:
            # h_node: [B, N, H] -> gather along node axis (dim=1)
            src_emb = h_node[:, src, :]
            dst_emb = h_node[:, dst, :]
            edge_feat = torch.cat([src_emb, dst_emb], dim=-1)  # [B, E, 2H]
            return self.proj(edge_feat).squeeze(-1)
        raise ValueError(
            f"h_node must be [N, H] or [B, N, H], got shape {tuple(h_node.shape)}"
        )


class DemandForecastHead(nn.Module):
    """Next-step per-node demand forecast: ``[N, hidden] -> [N]``."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.proj = nn.Linear(hidden_dim, 1)

    def forward(self, h_node: torch.Tensor) -> torch.Tensor:
        return self.proj(h_node).squeeze(-1)


class SetpointAdvisoryHead(nn.Module):
    """Global setpoint advisory vector.

    Mean-pools node embeddings to a graph-level vector, then projects
    to ``num_outputs``. Shapes: ``[N, H] -> [K]`` or ``[B, N, H] -> [B, K]``.
    """

    def __init__(self, hidden_dim: int, num_outputs: int = 1) -> None:
        super().__init__()
        self.num_outputs = int(num_outputs)
        self.proj = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, num_outputs),
        )

    def forward(self, h_node: torch.Tensor) -> torch.Tensor:
        if h_node.dim() == 2:
            pooled = h_node.mean(dim=0)        # [H]
        elif h_node.dim() == 3:
            pooled = h_node.mean(dim=1)        # [B, H]
        else:
            raise ValueError(
                f"h_node must be [N, H] or [B, N, H], got shape {tuple(h_node.shape)}"
            )
        return self.proj(pooled)
