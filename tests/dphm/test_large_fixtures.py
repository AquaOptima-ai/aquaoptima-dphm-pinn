"""Tests for the Sprint 8 larger deterministic synthetic networks.

The Sprint 1-7 tests rely on three hand-traced topologies (branch /
single_loop / pump) of 3-4 nodes each. Sprint 8 adds a deterministic
grid builder that yields an O(50-200)-node mesh so we can exercise
the existing solver, residual assembly, batched residual, and graph
feature builder on a network that is materially larger but still
synthetic / reference-only.

Tests here cover:

* Shape sanity (node count, edge count, masks).
* Determinism for a fixed seed; sensitivity to the seed.
* Mass conservation (``sum(demands) == 0``).
* Compatibility with :func:`assemble_residuals`,
  :func:`assemble_residuals_batched`, :func:`newton_solve`, and the
  graph feature builder.
"""

from __future__ import annotations

import math

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    assemble_residuals,
    assemble_residuals_batched,
    initial_guess,
    newton_solve,
)
from aquaoptima.dphm.large_fixtures import make_grid_network
from aquaoptima.topology import build_graph_features


# ---------------------------------------------------------------------------
# shape / structure
# ---------------------------------------------------------------------------


def test_default_grid_size_is_in_target_range() -> None:
    net = make_grid_network()
    assert isinstance(net, Network)
    # Target O(50-200) nodes.
    assert 50 <= net.num_nodes <= 200
    # Comparable edge count.
    assert net.num_edges >= net.num_nodes - 1


def test_grid_8x8_has_expected_topology() -> None:
    net = make_grid_network(rows=8, cols=8, seed=0)
    assert net.num_nodes == 64
    # Mesh grid: (rows*(cols-1)) horizontal + ((rows-1)*cols) vertical
    expected_edges = 8 * 7 + 7 * 8
    assert net.num_edges == expected_edges


def test_grid_has_at_least_one_fixed_head() -> None:
    net = make_grid_network()
    assert net.num_fixed_heads >= 1


def test_grid_is_mass_balanced() -> None:
    net = make_grid_network()
    # Tolerance matches the Sprint 1-2 fixtures (``test_fixtures.py``):
    # mass balance is exact in physical units up to float32 reduction noise.
    assert float(net.demands.sum().item()) == pytest.approx(0.0, abs=1e-6)


def test_grid_pipe_parameters_positive_on_pipe_edges() -> None:
    net = make_grid_network()
    pipes = net.pipe_mask
    assert bool((net.lengths[pipes] > 0).all().item())
    assert bool((net.diameters[pipes] > 0).all().item())
    assert bool((net.c_factors[pipes] > 0).all().item())


def test_grid_no_unclassified_edges() -> None:
    net = make_grid_network()
    assert bool((net.pipe_mask | net.pump_mask).all().item())
    assert not bool((net.pipe_mask & net.pump_mask).any().item())


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_grid_is_deterministic_for_same_seed() -> None:
    a = make_grid_network(rows=6, cols=6, seed=7)
    b = make_grid_network(rows=6, cols=6, seed=7)
    assert torch.equal(a.edge_index, b.edge_index)
    assert torch.allclose(a.demands, b.demands)
    assert torch.allclose(a.lengths, b.lengths)
    assert torch.allclose(a.diameters, b.diameters)
    assert torch.allclose(a.c_factors, b.c_factors)
    assert torch.allclose(a.fixed_head_values, b.fixed_head_values)


def test_grid_changes_with_seed() -> None:
    a = make_grid_network(rows=6, cols=6, seed=0)
    b = make_grid_network(rows=6, cols=6, seed=1)
    # At least one of demand / pipe parameter tensors should differ.
    assert not (
        torch.allclose(a.demands, b.demands)
        and torch.allclose(a.lengths, b.lengths)
        and torch.allclose(a.diameters, b.diameters)
        and torch.allclose(a.c_factors, b.c_factors)
    )


# ---------------------------------------------------------------------------
# solver / residual compatibility
# ---------------------------------------------------------------------------


def test_grid_assemble_residuals_returns_finite_tensor() -> None:
    net = make_grid_network(rows=6, cols=6, seed=0)
    heads, flows = initial_guess(net, dtype=torch.float64)
    r = assemble_residuals(net, heads, flows)
    assert r.shape == (net.num_free_nodes + net.num_edges,)
    assert torch.isfinite(r).all().item()


def test_grid_assemble_residuals_batched_matches_unbatched() -> None:
    net = make_grid_network(rows=5, cols=5, seed=0)
    heads, flows = initial_guess(net, dtype=torch.float64)

    r_single = assemble_residuals(net, heads, flows)
    r_batched = assemble_residuals_batched(
        net, heads.unsqueeze(0), flows.unsqueeze(0)
    )
    assert r_batched.shape == (1, r_single.shape[0])
    assert torch.allclose(r_batched.squeeze(0), r_single, atol=1e-9, rtol=0.0)


def test_grid_assemble_residuals_batched_b4() -> None:
    net = make_grid_network(rows=5, cols=5, seed=0)
    heads0, flows0 = initial_guess(net, dtype=torch.float64)
    B = 4
    heads = heads0.unsqueeze(0).expand(B, -1).contiguous()
    flows = flows0.unsqueeze(0).expand(B, -1).contiguous()
    r = assemble_residuals_batched(net, heads, flows)
    assert r.shape == (B, net.num_free_nodes + net.num_edges)
    assert torch.isfinite(r).all().item()


def test_grid_newton_solve_converges_on_small_grid() -> None:
    """Solver convergence on a 5x5 grid is the gate for using the larger
    grid in physics-consistent telemetry generation."""
    net = make_grid_network(rows=5, cols=5, seed=0)
    result = newton_solve(net, max_iterations=200, tol=1e-6)
    assert result.converged, (
        f"newton_solve failed on 5x5 grid: reason={result.reason}, "
        f"residual_norm={result.residual_norm}"
    )
    assert math.isfinite(result.residual_norm)


def test_grid_compatible_with_graph_feature_builder() -> None:
    net = make_grid_network(rows=6, cols=6, seed=0)
    feats = build_graph_features(net)
    assert feats.num_nodes == net.num_nodes
    assert feats.num_edges == net.num_edges
    assert feats.node_feature_dim >= 1
    assert feats.edge_feature_dim >= 1
