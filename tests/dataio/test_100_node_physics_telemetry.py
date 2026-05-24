"""Sprint 10 — Physics-consistent telemetry on a 100-node grid.

This test extends ``tests/dataio/test_large_physics_telemetry.py`` to
the 10x10 = 100-node grid required by the Sprint 10 science gate. Per
the Sprint 9 performance work, telemetry generation routes the per-step
Newton solve through the analytic Jacobian (``jacobian_mode="analytic"``),
which makes a 32-step series on this fixture tractable inside the
automated test budget.

What this file covers (and what it does not):

* shape correctness of the returned :class:`TelemetrySeries`,
* finiteness of every channel,
* dPHM mass + energy residual at every timestep,
* batched residual at ``B>=8`` against the per-row unbatched call
  (energy block, where the comparison is well-defined regardless of
  per-row demand re-balancing),
* feeding :class:`WindowDataset` without surprises.

It does **not** train a model; the bounded science gate lives in
``tests/training/test_sprint10_100_node_gate.py``.
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


_SPRINT10_NUM_STEPS = 32
_SPRINT10_WINDOW = 24
_SPRINT10_SEED = 0


def _residual_norm_at(net, demand_t, pressure_t, flow_t) -> float:
    perturbed = replace(net, demands=demand_t.to(torch.float64))
    r = assemble_residuals(
        perturbed, pressure_t.to(torch.float64), flow_t.to(torch.float64)
    )
    return float(torch.linalg.vector_norm(r).item())


# ---------------------------------------------------------------------------
# Module-scoped fixtures — 32 steps of physics-consistent telemetry on a
# 10x10 grid is generated exactly once and reused across every assertion.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def grid_net_100():
    """10x10 grid: 100 nodes, 180 edges."""
    return make_grid_network(rows=10, cols=10, seed=_SPRINT10_SEED)


@pytest.fixture(scope="module")
def grid_telemetry_100(grid_net_100):
    return generate_physics_consistent_telemetry(
        grid_net_100,
        num_steps=_SPRINT10_NUM_STEPS,
        seed=_SPRINT10_SEED,
        window=_SPRINT10_WINDOW,
        solver_tol=1e-7,
        jacobian_mode="analytic",
    )


# ---------------------------------------------------------------------------
# topology sanity
# ---------------------------------------------------------------------------


def test_100_node_grid_topology_summary(grid_net_100) -> None:
    assert grid_net_100.num_nodes == 100
    assert grid_net_100.num_edges == 180
    # Exactly one reservoir / fixed-head node at the (0,0) corner.
    assert int(grid_net_100.fixed_head_mask.sum().item()) == 1
    assert bool(grid_net_100.fixed_head_mask[0].item())


# ---------------------------------------------------------------------------
# shape + finiteness
# ---------------------------------------------------------------------------


def test_100_node_telemetry_returns_correct_shape(
    grid_net_100, grid_telemetry_100
) -> None:
    series = grid_telemetry_100
    assert isinstance(series, TelemetrySeries)
    assert series.pressure.shape == (_SPRINT10_NUM_STEPS, grid_net_100.num_nodes)
    assert series.flow.shape == (_SPRINT10_NUM_STEPS, grid_net_100.num_edges)
    assert series.demand.shape == (_SPRINT10_NUM_STEPS, grid_net_100.num_nodes)


def test_100_node_telemetry_is_finite_everywhere(grid_telemetry_100) -> None:
    series = grid_telemetry_100
    assert torch.isfinite(series.pressure).all().item()
    assert torch.isfinite(series.flow).all().item()
    assert torch.isfinite(series.demand).all().item()


# ---------------------------------------------------------------------------
# dPHM residual at every step
# ---------------------------------------------------------------------------


def test_100_node_telemetry_residual_is_small_at_every_step(
    grid_net_100, grid_telemetry_100
) -> None:
    """Every timestep must satisfy the dPHM residual to solver tolerance."""
    series = grid_telemetry_100
    worst = 0.0
    for t in range(series.num_steps):
        worst = max(
            worst,
            _residual_norm_at(
                grid_net_100,
                series.demand[t],
                series.pressure[t],
                series.flow[t],
            ),
        )
    # Residual generated at solver_tol=1e-7; allow slack for the float32
    # cast at the generator -> downstream boundary.
    assert worst < 1e-3, f"max residual norm across steps was {worst}"


# ---------------------------------------------------------------------------
# batched residual at B=8 — parity against per-row unbatched call
# ---------------------------------------------------------------------------


def test_100_node_batched_residual_shape_and_finite(
    grid_net_100, grid_telemetry_100
) -> None:
    series = grid_telemetry_100
    B = 8
    heads_b = series.pressure[:B].to(torch.float64)
    flows_b = series.flow[:B].to(torch.float64)

    r_batched = assemble_residuals_batched(grid_net_100, heads_b, flows_b)
    assert r_batched.shape == (
        B,
        grid_net_100.num_free_nodes + grid_net_100.num_edges,
    )
    assert torch.isfinite(r_batched).all().item()


def test_100_node_batched_residual_matches_unbatched_energy_block(
    grid_net_100, grid_telemetry_100
) -> None:
    """Batched residual must match per-row unbatched on the energy block.

    The mass block depends on the per-step demand vector (which differs
    from the network's nominal demand), so we compare only the energy
    block — same convention as the Sprint 8 5x5 test.
    """
    series = grid_telemetry_100
    B = 8
    heads_b = series.pressure[:B].to(torch.float64)
    flows_b = series.flow[:B].to(torch.float64)

    r_batched = assemble_residuals_batched(grid_net_100, heads_b, flows_b)
    E = grid_net_100.num_edges
    for b in range(B):
        net_b = replace(
            grid_net_100, demands=series.demand[b].to(torch.float64)
        )
        r_single = assemble_residuals(net_b, heads_b[b], flows_b[b])
        edge_b = r_batched[b, -E:]
        edge_s = r_single[-E:]
        assert torch.allclose(edge_b, edge_s, atol=1e-9, rtol=0.0)


# ---------------------------------------------------------------------------
# window dataset hand-off
# ---------------------------------------------------------------------------


def test_100_node_telemetry_feeds_window_dataset(
    grid_net_100, grid_telemetry_100
) -> None:
    ds = WindowDataset(grid_telemetry_100, window=_SPRINT10_WINDOW)
    # 32 steps - 24 window = 8 sliding samples (window-end at t=24..31).
    assert len(ds) == _SPRINT10_NUM_STEPS - _SPRINT10_WINDOW
    sample = ds[0]
    assert sample["x_seq"].shape == (
        _SPRINT10_WINDOW,
        grid_net_100.num_nodes,
        ds.node_feature_dim,
    )
    assert sample["target_pressure"].shape == (grid_net_100.num_nodes,)
    assert sample["target_flow"].shape == (grid_net_100.num_edges,)


# ---------------------------------------------------------------------------
# determinism + jacobian_mode parity
# ---------------------------------------------------------------------------


def test_100_node_telemetry_is_deterministic_for_same_seed(grid_net_100) -> None:
    s1 = generate_physics_consistent_telemetry(
        grid_net_100,
        num_steps=_SPRINT10_NUM_STEPS,
        seed=7,
        window=_SPRINT10_WINDOW,
        solver_tol=1e-7,
        jacobian_mode="analytic",
    )
    s2 = generate_physics_consistent_telemetry(
        grid_net_100,
        num_steps=_SPRINT10_NUM_STEPS,
        seed=7,
        window=_SPRINT10_WINDOW,
        solver_tol=1e-7,
        jacobian_mode="analytic",
    )
    assert torch.equal(s1.pressure, s2.pressure)
    assert torch.equal(s1.flow, s2.flow)
    assert torch.equal(s1.demand, s2.demand)


def test_telemetry_analytic_and_autograd_match_on_small_grid() -> None:
    """``jacobian_mode`` must be a perf knob only — telemetry must match.

    Run on a 5x5 grid + 4 steps to keep the autograd path under the
    Sprint 9 perf-gate target time, while still cross-checking both
    code paths produce the same physically-consistent telemetry.
    """
    net = make_grid_network(rows=5, cols=5, seed=0)
    s_auto = generate_physics_consistent_telemetry(
        net,
        num_steps=8,
        seed=3,
        window=4,
        solver_tol=1e-8,
        jacobian_mode="autograd",
    )
    s_ana = generate_physics_consistent_telemetry(
        net,
        num_steps=8,
        seed=3,
        window=4,
        solver_tol=1e-8,
        jacobian_mode="analytic",
    )
    # Demand schedule is deterministic and independent of the Jacobian.
    assert torch.equal(s_auto.demand, s_ana.demand)
    # Heads and flows must agree to solver tolerance.
    assert torch.allclose(s_auto.pressure, s_ana.pressure, atol=1e-5, rtol=0.0)
    assert torch.allclose(s_auto.flow, s_ana.flow, atol=1e-5, rtol=0.0)
