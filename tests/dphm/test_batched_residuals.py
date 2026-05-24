"""Sprint 7 — Vectorized batched residual assembly.

``assemble_residuals_batched`` should evaluate the dPHM residual on a
batch of ``[B, N]`` head and ``[B, E]`` flow tensors in a single set
of vectorized tensor ops, returning ``[B, R]`` where
``R = num_free_nodes + num_edges``.

Coverage:

* shape contract: ``[B, N]`` + ``[B, E]`` -> ``[B, R]``.
* ``B=1`` parity vs the unbatched :func:`assemble_residuals` (the
  legacy code path is the source of truth).
* ``B=4`` parity vs a Python ``stack([assemble_residuals(...)] * B)``.
* finite gradients flow through both inputs.
* dtype is preserved (float32 stays float32, float64 stays float64).
* validation: rank-1 inputs and mismatched batch dims raise.
"""

from __future__ import annotations

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    assemble_residuals,
    make_branch_network,
    make_pump_network,
    make_single_loop_network,
)
from aquaoptima.dphm.solver import assemble_residuals_batched


@pytest.fixture(params=["branch", "single_loop", "pump"])
def network(request) -> Network:
    return {
        "branch": make_branch_network,
        "single_loop": make_single_loop_network,
        "pump": make_pump_network,
    }[request.param]()


def _make_state(network: Network, B: int, *, dtype=torch.float64, seed: int = 0):
    g = torch.Generator().manual_seed(seed)
    heads = (torch.randn(B, network.num_nodes, generator=g, dtype=dtype) * 0.5 + 100.0)
    flows = (torch.randn(B, network.num_edges, generator=g, dtype=dtype) * 0.01 + 0.05)
    return heads, flows


def test_batched_residuals_shape(network: Network) -> None:
    B = 5
    heads, flows = _make_state(network, B)
    R = network.num_free_nodes + network.num_edges
    out = assemble_residuals_batched(network, heads, flows)
    assert out.shape == (B, R)


def test_batched_residuals_b1_matches_unbatched(network: Network) -> None:
    heads, flows = _make_state(network, B=1, seed=1)
    out_b = assemble_residuals_batched(network, heads, flows)
    out_u = assemble_residuals(network, heads[0], flows[0])
    assert out_b.shape[0] == 1
    assert torch.allclose(out_b[0], out_u, atol=1e-10, rtol=0)


def test_batched_residuals_b4_matches_stack(network: Network) -> None:
    B = 4
    heads, flows = _make_state(network, B, seed=2)
    out_b = assemble_residuals_batched(network, heads, flows)
    stacked = torch.stack(
        [assemble_residuals(network, heads[i], flows[i]) for i in range(B)],
        dim=0,
    )
    assert torch.allclose(out_b, stacked, atol=1e-10, rtol=0)


def test_batched_residuals_gradients_finite(network: Network) -> None:
    heads, flows = _make_state(network, B=3, seed=3)
    heads = heads.requires_grad_(True)
    flows = flows.requires_grad_(True)
    out = assemble_residuals_batched(network, heads, flows)
    (out ** 2).sum().backward()
    assert heads.grad is not None and torch.isfinite(heads.grad).all()
    assert flows.grad is not None and torch.isfinite(flows.grad).all()


def test_batched_residuals_preserves_float32() -> None:
    net = make_branch_network()
    heads, flows = _make_state(net, B=2, dtype=torch.float32, seed=4)
    out = assemble_residuals_batched(net, heads, flows)
    assert out.dtype == torch.float32


def test_batched_residuals_preserves_float64() -> None:
    net = make_branch_network()
    heads, flows = _make_state(net, B=2, dtype=torch.float64, seed=5)
    out = assemble_residuals_batched(net, heads, flows)
    assert out.dtype == torch.float64


def test_batched_residuals_rejects_rank_mismatch() -> None:
    net = make_branch_network()
    heads = torch.zeros(net.num_nodes)
    flows = torch.zeros(net.num_edges)
    with pytest.raises(ValueError):
        assemble_residuals_batched(net, heads, flows)


def test_batched_residuals_rejects_batch_dim_mismatch() -> None:
    net = make_branch_network()
    heads = torch.zeros(3, net.num_nodes)
    flows = torch.zeros(4, net.num_edges)
    with pytest.raises(ValueError):
        assemble_residuals_batched(net, heads, flows)
