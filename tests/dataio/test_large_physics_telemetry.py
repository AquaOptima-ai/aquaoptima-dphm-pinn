"""Tests for physics-consistent telemetry on the Sprint 8 larger grid.

The Sprint 5 generator (``generate_physics_consistent_telemetry``) was
designed to be topology-agnostic — it solves a per-step Newton system
on whatever :class:`Network` is passed in. Sprint 8 validates that the
same generator works unchanged on the larger grid fixture
(:func:`make_grid_network`).

These tests are deliberately small (5x5 / 6x6 grids, short timeseries)
so they stay under CPU runtime budgets — the existing dense-Jacobian
solver scales as O(N^3) per Newton step. Larger fixtures (8x8 = 64
nodes) are exercised manually and reported in ``SPRINT8_REPORT.md``;
see that file for the dense-vs-sparse incidence recommendation.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from aquaoptima.dataio import TelemetrySeries, WindowDataset
from aquaoptima.dataio.telemetry import generate_physics_consistent_telemetry
from aquaoptima.dphm import (
    assemble_residuals,
    assemble_residuals_batched,
    make_grid_network,
)


def _residual_norm_at(net, demand_t, pressure_t, flow_t) -> float:
    perturbed = replace(net, demands=demand_t.to(torch.float64))
    r = assemble_residuals(
        perturbed, pressure_t.to(torch.float64), flow_t.to(torch.float64)
    )
    return float(torch.linalg.vector_norm(r).item())


# Module-scoped fixtures — telemetry generation runs an O(N^3) Newton
# Jacobian per timestep, so we generate the series once and reuse it
# across every shape / residual / dataset assertion below.


@pytest.fixture(scope="module")
def grid_net():
    return make_grid_network(rows=5, cols=5, seed=0)


@pytest.fixture(scope="module")
def grid_telemetry(grid_net):
    return generate_physics_consistent_telemetry(
        grid_net, num_steps=40, seed=0, window=32, solver_tol=1e-7
    )


def test_grid_telemetry_returns_correct_shape(grid_net, grid_telemetry) -> None:
    series = grid_telemetry
    assert isinstance(series, TelemetrySeries)
    assert series.pressure.shape == (40, grid_net.num_nodes)
    assert series.flow.shape == (40, grid_net.num_edges)
    assert series.demand.shape == (40, grid_net.num_nodes)


def test_grid_telemetry_is_finite_everywhere(grid_telemetry) -> None:
    series = grid_telemetry
    assert torch.isfinite(series.pressure).all().item()
    assert torch.isfinite(series.flow).all().item()
    assert torch.isfinite(series.demand).all().item()


def test_grid_telemetry_residual_is_small_at_every_step(
    grid_net, grid_telemetry
) -> None:
    """Every timestep must satisfy the dPHM residual to the solver tolerance."""
    series = grid_telemetry
    worst = 0.0
    for t in range(series.num_steps):
        worst = max(
            worst,
            _residual_norm_at(
                grid_net, series.demand[t], series.pressure[t], series.flow[t]
            ),
        )
    # Residual generated at solver_tol=1e-7; allow slack for the float32
    # cast that crosses the generator <-> downstream boundary.
    assert worst < 1e-3, f"max residual norm across steps was {worst}"


def test_grid_telemetry_batched_residual_matches_unbatched(
    grid_net, grid_telemetry
) -> None:
    series = grid_telemetry
    pressures = series.pressure.to(torch.float64)
    flows = series.flow.to(torch.float64)
    # Build a B=8 batch from the first eight timesteps.
    B = 8
    heads_b = pressures[:B]
    flows_b = flows[:B]

    r_batched = assemble_residuals_batched(grid_net, heads_b, flows_b)
    assert r_batched.shape == (B, grid_net.num_free_nodes + grid_net.num_edges)

    # The batched call uses the network's *nominal* demands and the
    # per-row energy residual; we compare that energy block to the
    # per-row unbatched call (whose demands also match the nominal
    # path on the energy block).
    for b in range(B):
        net_b = replace(grid_net, demands=series.demand[b].to(torch.float64))
        r_single = assemble_residuals(net_b, heads_b[b], flows_b[b])
        E = grid_net.num_edges
        edge_b = r_batched[b, -E:]
        edge_s = r_single[-E:]
        assert torch.allclose(edge_b, edge_s, atol=1e-9, rtol=0.0)


def test_grid_telemetry_feeds_window_dataset(grid_net, grid_telemetry) -> None:
    ds = WindowDataset(grid_telemetry, window=32)
    assert len(ds) == 8
    sample = ds[0]
    assert sample["x_seq"].shape == (32, grid_net.num_nodes, ds.node_feature_dim)
    assert sample["target_pressure"].shape == (grid_net.num_nodes,)
    assert sample["target_flow"].shape == (grid_net.num_edges,)


def test_grid_telemetry_is_deterministic_for_same_seed(grid_net) -> None:
    s1 = generate_physics_consistent_telemetry(
        grid_net, num_steps=33, seed=11, window=32, solver_tol=1e-7
    )
    s2 = generate_physics_consistent_telemetry(
        grid_net, num_steps=33, seed=11, window=32, solver_tol=1e-7
    )
    assert torch.equal(s1.pressure, s2.pressure)
    assert torch.equal(s1.flow, s2.flow)
    assert torch.equal(s1.demand, s2.demand)
