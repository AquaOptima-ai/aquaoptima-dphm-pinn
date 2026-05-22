"""Graph encoders for the dPHM-PINN.

Two implementations live here:

* :class:`PyGGraphEncoder` — a stack of ``torch_geometric``
  ``GATv2Conv`` layers (default 3) with edge-attribute conditioning.
  This is the roadmap encoder and is selected automatically by the
  :func:`GraphEncoder` factory when ``torch_geometric`` is installed.
* :class:`FallbackGraphEncoder` — a hand-rolled message-passing encoder
  built on plain PyTorch. It performs one round of edge-conditioned
  message aggregation (mean over incoming edges, with edge attributes
  concatenated into each message) followed by an MLP node update. Used
  when PyG is unavailable or when callers pass ``force_fallback=True``.

:func:`GraphEncoder` is a factory that returns the PyG implementation
when available and the fallback otherwise.
"""

from __future__ import annotations

import torch
from torch import nn

try:  # pragma: no cover - exercised in PyG-installed environments only
    from torch_geometric.nn import GATv2Conv  # type: ignore[import-untyped]

    _PYG_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means "no PyG"
    GATv2Conv = None  # type: ignore[assignment]
    _PYG_AVAILABLE = False


class FallbackGraphEncoder(nn.Module):
    """Plain-PyTorch message-passing encoder.

    Aggregation: for each node, average the messages on its *incoming*
    edges. Each message is computed by passing
    ``[x_src, x_dst, edge_attr]`` through a small MLP.
    """

    def __init__(
        self,
        node_in_dim: int,
        edge_in_dim: int,
        hidden_dim: int,
    ) -> None:
        super().__init__()
        self.node_in_dim = int(node_in_dim)
        self.edge_in_dim = int(edge_in_dim)
        self.hidden_dim = int(hidden_dim)

        self.message_mlp = nn.Sequential(
            nn.Linear(2 * node_in_dim + edge_in_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.update_mlp = nn.Sequential(
            nn.Linear(node_in_dim + hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )

    def forward(
        self,
        x_node: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
    ) -> torch.Tensor:
        N = x_node.shape[0]
        src, dst = edge_index[0], edge_index[1]

        msg_input = torch.cat([x_node[src], x_node[dst], edge_attr], dim=-1)
        messages = self.message_mlp(msg_input)  # [E, hidden]

        agg = torch.zeros(N, self.hidden_dim, dtype=messages.dtype, device=messages.device)
        agg.index_add_(0, dst, messages)
        counts = torch.zeros(N, dtype=messages.dtype, device=messages.device)
        counts.index_add_(0, dst, torch.ones_like(dst, dtype=messages.dtype))
        counts = counts.clamp_min(1.0).unsqueeze(-1)
        agg = agg / counts

        return self.update_mlp(torch.cat([x_node, agg], dim=-1))


class PyGGraphEncoder(nn.Module):
    """Multi-layer ``GATv2Conv`` stack used when ``torch_geometric`` is
    available.

    Defaults to a 3-layer encoder (the Sprint 6 roadmap target). Every
    layer is edge-conditioned via ``edge_dim`` so the pipe / pump
    physical attributes assembled by
    :func:`aquaoptima.topology.build_graph_features` participate in
    attention. Layer 1 maps ``node_in_dim -> hidden_dim``; subsequent
    layers operate at ``hidden_dim``. A ReLU activation is applied
    between layers but not after the final one (so the encoder output
    is unbounded and gradients flow freely into the fusion MLP).
    """

    def __init__(
        self,
        node_in_dim: int,
        edge_in_dim: int,
        hidden_dim: int,
        heads: int = 2,
        num_layers: int = 3,
    ) -> None:
        super().__init__()
        if not _PYG_AVAILABLE:
            raise RuntimeError("torch_geometric not available")
        if num_layers < 1:
            raise ValueError(f"num_layers must be >= 1, got {num_layers}")

        self.node_in_dim = int(node_in_dim)
        self.edge_in_dim = int(edge_in_dim)
        self.hidden_dim = int(hidden_dim)
        self.num_layers = int(num_layers)
        self.heads = int(heads)

        convs: list[nn.Module] = []
        for layer_idx in range(self.num_layers):
            in_dim = node_in_dim if layer_idx == 0 else hidden_dim
            convs.append(
                GATv2Conv(
                    in_channels=in_dim,
                    out_channels=hidden_dim,
                    heads=heads,
                    edge_dim=edge_in_dim,
                    concat=False,
                )
            )
        self.convs = nn.ModuleList(convs)
        self.act = nn.ReLU()

    def forward(
        self,
        x_node: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
    ) -> torch.Tensor:
        h = x_node
        last = len(self.convs) - 1
        for i, conv in enumerate(self.convs):
            h = conv(h, edge_index, edge_attr)
            if i != last:
                h = self.act(h)
        return h


def GraphEncoder(
    node_in_dim: int,
    edge_in_dim: int,
    hidden_dim: int,
    force_fallback: bool = False,
    num_layers: int = 3,
) -> nn.Module:
    """Factory returning the best available encoder.

    Set ``force_fallback=True`` to skip the PyG check entirely (used in
    tests and in deployments where deterministic CPU-only behaviour is
    preferred). ``num_layers`` only applies to the PyG path.
    """
    if not force_fallback and _PYG_AVAILABLE:
        return PyGGraphEncoder(
            node_in_dim, edge_in_dim, hidden_dim, num_layers=num_layers
        )
    return FallbackGraphEncoder(node_in_dim, edge_in_dim, hidden_dim)


__all__ = ["FallbackGraphEncoder", "GraphEncoder", "PyGGraphEncoder"]
