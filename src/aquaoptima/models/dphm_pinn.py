"""dPHM-PINN model composition.

Forward path:

1. **Graph encoder** — embed the static topology features
   ``(x_node[N, F_node], edge_index, edge_attr)`` into per-node
   embeddings ``h_topo[N, hidden]``.
2. **Temporal encoder** — feed the 32-step SCADA sequence
   ``x_seq[T, N, F_seq]`` (or batched ``[B, T, N, F_seq]``) into a
   per-node GRU. Final hidden state ``h_temp[N, hidden]`` or
   ``[B, N, hidden]``.
3. **Fusion** — concatenate ``[h_topo, h_temp]`` and project back to
   ``hidden``. Graph topology features are static across the batch so
   ``h_topo`` is broadcast to ``[B, N, hidden]`` when the temporal
   path is batched.
4. **Heads** — pressure, flow, demand-forecast, setpoint-advisory.
   Outputs are ``[N] / [E] / [K]`` (unbatched) or ``[B, N] / [B, E] /
   [B, K]`` (batched).
"""

from __future__ import annotations

import torch
from torch import nn

from aquaoptima.topology import GraphFeatures

from .graph_encoder import FallbackGraphEncoder, GraphEncoder
from .gru_encoder import GRUTemporalEncoder
from .heads import DemandForecastHead, FlowHead, PressureHead, SetpointAdvisoryHead


class DPHMPINN(nn.Module):
    """Composed dPHM-PINN: graph encoder + GRU + fusion + four heads.

    Accepts either ``[T, N, F_seq]`` or ``[B, T, N, F_seq]`` telemetry
    windows plus a :class:`GraphFeatures` bundle and returns a dict of
    per-task predictions. The leading batch dimension propagates through
    all heads.
    """

    def __init__(
        self,
        node_in_dim: int,
        edge_in_dim: int,
        seq_in_dim: int,
        hidden_dim: int = 32,
        num_setpoint_outputs: int = 1,
        force_fallback: bool = False,
    ) -> None:
        super().__init__()
        self.hidden_dim = int(hidden_dim)
        self.graph_encoder = GraphEncoder(
            node_in_dim=node_in_dim,
            edge_in_dim=edge_in_dim,
            hidden_dim=hidden_dim,
            force_fallback=force_fallback,
        )
        self.temporal_encoder = GRUTemporalEncoder(
            input_dim=seq_in_dim,
            hidden_dim=hidden_dim,
        )
        self.fusion = nn.Sequential(
            nn.Linear(2 * hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.pressure_head = PressureHead(hidden_dim)
        self.flow_head = FlowHead(hidden_dim)
        self.demand_head = DemandForecastHead(hidden_dim)
        self.setpoint_head = SetpointAdvisoryHead(hidden_dim, num_setpoint_outputs)

    def forward(
        self, x_seq: torch.Tensor, features: GraphFeatures
    ) -> dict[str, torch.Tensor]:
        if x_seq.dim() == 3:
            batched = False
            T, N, _ = x_seq.shape
        elif x_seq.dim() == 4:
            batched = True
            B, T, N, _ = x_seq.shape
        else:
            raise ValueError(
                f"x_seq must be [T, N, F] or [B, T, N, F], "
                f"got shape {tuple(x_seq.shape)}"
            )

        if N != features.num_nodes:
            raise ValueError(
                f"x_seq node dim {N} != features.num_nodes {features.num_nodes}"
            )

        h_topo = self.graph_encoder(
            features.x_node, features.edge_index, features.edge_attr
        )  # [N, hidden]
        h_temp = self.temporal_encoder(x_seq)  # [N, hidden] or [B, N, hidden]

        if batched:
            # Broadcast static topology embedding across batch.
            h_topo_b = h_topo.unsqueeze(0).expand(B, -1, -1)  # [B, N, hidden]
            h = self.fusion(torch.cat([h_topo_b, h_temp], dim=-1))  # [B, N, hidden]
        else:
            h = self.fusion(torch.cat([h_topo, h_temp], dim=-1))  # [N, hidden]

        return {
            "pressure": self.pressure_head(h),
            "flow": self.flow_head(h, features.edge_index),
            "demand_forecast": self.demand_head(h),
            "setpoint_advisory": self.setpoint_head(h),
        }


__all__ = ["DPHMPINN", "FallbackGraphEncoder"]
