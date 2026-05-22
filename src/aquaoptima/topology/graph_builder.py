"""Convert a dPHM :class:`~aquaoptima.dphm.Network` into ML-ready tensors.

A :class:`GraphFeatures` bundle carries the per-node, per-edge, and
sensor-observability tensors a graph-based model needs. The layout is
intentionally fixed (and documented per column) so downstream modules
can index by position rather than by name lookup.

Node feature columns (``x_node[:, k]``):
    0. demand                     (m^3/s, positive = consumption)
    1. fixed-head flag            (1.0 on boundary nodes, else 0.0)
    2. fixed-head value           (head in metres on fixed nodes, else 0.0)

Edge feature columns (``edge_attr[:, k]``):
    0. length          (m, ``0`` on non-pipe rows)
    1. diameter        (m, ``0`` on non-pipe rows)
    2. c_factor        (Hazen-Williams, ``0`` on non-pipe rows)
    3. pump_flag       (1.0 on pump edges, else 0.0)
    4. pump_a0
    5. pump_a1
    6. pump_a2
    7. pump_speed
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from aquaoptima.dphm import Network

NODE_FEATURE_DIM = 3
EDGE_FEATURE_DIM = 8


@dataclass
class GraphFeatures:
    """ML-ready tensor bundle for a :class:`Network`."""

    x_node: torch.Tensor
    edge_index: torch.Tensor
    edge_attr: torch.Tensor
    sensor_mask: torch.Tensor

    @property
    def num_nodes(self) -> int:
        return int(self.x_node.shape[0])

    @property
    def num_edges(self) -> int:
        return int(self.edge_index.shape[1])

    @property
    def node_feature_dim(self) -> int:
        return int(self.x_node.shape[1])

    @property
    def edge_feature_dim(self) -> int:
        return int(self.edge_attr.shape[1])


def build_graph_features(
    network: Network,
    sensor_mask: torch.Tensor | None = None,
) -> GraphFeatures:
    """Project a :class:`Network` onto fixed-layout node and edge tensors.

    If ``sensor_mask`` is omitted, every fixed-head boundary node is
    treated as observed and all other nodes are virtual. The caller can
    override this with any boolean ``[num_nodes]`` mask.
    """
    N = network.num_nodes
    E = network.num_edges

    fixed_flag = network.fixed_head_mask.to(torch.get_default_dtype())
    x_node = torch.stack(
        [
            network.demands.to(torch.get_default_dtype()),
            fixed_flag,
            network.fixed_head_values.to(torch.get_default_dtype()),
        ],
        dim=1,
    )
    assert x_node.shape == (N, NODE_FEATURE_DIM)

    pipe_flag = network.pipe_mask.to(torch.get_default_dtype())
    pump_flag = network.pump_mask.to(torch.get_default_dtype())

    edge_attr = torch.stack(
        [
            network.lengths.to(torch.get_default_dtype()) * pipe_flag,
            network.diameters.to(torch.get_default_dtype()) * pipe_flag,
            network.c_factors.to(torch.get_default_dtype()) * pipe_flag,
            pump_flag,
            network.pump_coeffs[:, 0].to(torch.get_default_dtype()) * pump_flag,
            network.pump_coeffs[:, 1].to(torch.get_default_dtype()) * pump_flag,
            network.pump_coeffs[:, 2].to(torch.get_default_dtype()) * pump_flag,
            network.pump_speeds.to(torch.get_default_dtype()) * pump_flag,
        ],
        dim=1,
    )
    assert edge_attr.shape == (E, EDGE_FEATURE_DIM)

    if sensor_mask is None:
        sensor_mask = network.fixed_head_mask.clone()
    else:
        if sensor_mask.dtype != torch.bool or sensor_mask.shape != (N,):
            raise ValueError(
                f"sensor_mask must be bool[{N}], got dtype={sensor_mask.dtype}, "
                f"shape={tuple(sensor_mask.shape)}"
            )

    return GraphFeatures(
        x_node=x_node,
        edge_index=network.edge_index.clone(),
        edge_attr=edge_attr,
        sensor_mask=sensor_mask,
    )
