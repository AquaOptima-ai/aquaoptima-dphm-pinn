"""Incidence matrix and node-level mass-balance residuals.

``edge_index`` follows the PyG convention: a ``[2, E]`` long tensor where row 0
is the source node and row 1 is the target node of each directed edge.
Positive flow leaves the source and enters the target, so the source row in
the incidence matrix carries ``-1`` and the target row carries ``+1``.

The nodal mass-balance residual is

    r_n = inflow_n - outflow_n - demand_n  =  (A @ flows)_n - demand_n

where ``demand_n`` is positive for consumption and negative for supply.
"""

from __future__ import annotations

import torch


def _validate_edge_index(edge_index: torch.Tensor, num_nodes: int) -> torch.Tensor:
    if edge_index.dim() != 2 or edge_index.shape[0] != 2:
        raise ValueError(
            f"edge_index must have shape [2, E], got {tuple(edge_index.shape)}"
        )
    if edge_index.dtype not in (torch.int32, torch.int64):
        edge_index = edge_index.long()
    if num_nodes <= 0:
        raise ValueError(f"num_nodes must be positive, got {num_nodes}")
    if edge_index.numel() and int(edge_index.max().item()) >= num_nodes:
        raise ValueError(
            "edge_index references a node id >= num_nodes "
            f"(max={int(edge_index.max().item())}, num_nodes={num_nodes})"
        )
    if edge_index.numel() and int(edge_index.min().item()) < 0:
        raise ValueError("edge_index must not contain negative node ids")
    return edge_index


def incidence_matrix(edge_index: torch.Tensor, num_nodes: int) -> torch.Tensor:
    """Dense signed incidence matrix of shape ``[num_nodes, num_edges]``."""
    edge_index = _validate_edge_index(edge_index, num_nodes)
    num_edges = edge_index.shape[1]
    A = torch.zeros((num_nodes, num_edges), dtype=torch.get_default_dtype())
    edge_ids = torch.arange(num_edges, dtype=torch.long)
    A[edge_index[0], edge_ids] = -1.0
    A[edge_index[1], edge_ids] = 1.0
    return A


def cached_incidence_matrix(network, dtype: torch.dtype) -> torch.Tensor:
    """Per-``Network`` cached dense incidence matrix at the given ``dtype``.

    Repeated Newton iterations and batched residual assembly invoke
    :func:`incidence_matrix` once per call, rebuilding the same dense
    ``[N, E]`` matrix each time. This helper memoises the result on a
    lazily-created ``_incidence_cache`` dict attached to the
    ``Network`` instance, keyed by ``dtype``. The cache is invisible to
    the dataclass contract and to external readers, and stays cheap
    because dPHM networks reuse a fixed topology across batches.

    Falls back transparently to :func:`incidence_matrix` if the
    network object disallows attribute assignment.
    """
    cache = getattr(network, "_incidence_cache", None)
    if cache is None:
        cache = {}
        try:
            object.__setattr__(network, "_incidence_cache", cache)
        except (AttributeError, TypeError):
            return incidence_matrix(network.edge_index, network.num_nodes).to(dtype)
    A = cache.get(dtype)
    if A is None:
        A = incidence_matrix(network.edge_index, network.num_nodes).to(dtype)
        cache[dtype] = A
    return A


def node_flow_balance(
    edge_index: torch.Tensor,
    flows: torch.Tensor,
    demands: torch.Tensor,
    num_nodes: int,
) -> torch.Tensor:
    """Nodal mass-balance residual, shape ``[num_nodes]``.

    Returns ``A @ flows - demands`` where ``A`` is the signed incidence matrix.
    Zero residual everywhere = network is mass-balanced.
    """
    edge_index = _validate_edge_index(edge_index, num_nodes)
    if flows.shape[-1] != edge_index.shape[1]:
        raise ValueError(
            f"flows length {flows.shape[-1]} does not match num_edges {edge_index.shape[1]}"
        )
    if demands.shape[-1] != num_nodes:
        raise ValueError(
            f"demands length {demands.shape[-1]} does not match num_nodes {num_nodes}"
        )

    A = incidence_matrix(edge_index, num_nodes).to(flows.dtype)
    return A @ flows - demands
