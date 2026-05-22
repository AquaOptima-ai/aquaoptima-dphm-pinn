"""Tests for the Sprint 5 physics-consistent telemetry generator.

The generator must produce ``TelemetrySeries`` whose per-timestep
``(pressure, flow, demand)`` triple satisfies the dPHM mass + energy
residual to a tight numeric tolerance — not just look plausible. The
tests below cover shape, determinism, residual closeness, fixture
generalisation (branch / single_loop / pump), and backward compatibility
with the existing ``generate_synthetic_telemetry`` / ``generate_synthetic_scada``
aliases.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from aquaoptima.dataio import (
    ScadaSeries,
    TelemetrySeries,
    WindowDataset,
    generate_synthetic_scada,
    generate_synthetic_telemetry,
)
from aquaoptima.dataio.telemetry import generate_physics_consistent_telemetry
from aquaoptima.dphm import (
    assemble_residuals,
    make_branch_network,
    make_pump_network,
    make_single_loop_network,
)


# ---------------------------------------------------------------------------
# shape and dataset compatibility
# ---------------------------------------------------------------------------


def test_physics_consistent_returns_telemetry_series_with_correct_shape() -> None:
    net = make_branch_network()
    series = generate_physics_consistent_telemetry(
        net, num_steps=33, seed=0, window=32
    )
    assert isinstance(series, TelemetrySeries)
    assert series.pressure.shape == (33, net.num_nodes)
    assert series.flow.shape == (33, net.num_edges)
    assert series.demand.shape == (33, net.num_nodes)


def test_physics_consistent_compatible_with_window_dataset() -> None:
    net = make_branch_network()
    series = generate_physics_consistent_telemetry(
        net, num_steps=40, seed=0, window=32
    )
    ds = WindowDataset(series, window=32)
    assert len(ds) == 8
    sample = ds[0]
    assert sample["x_seq"].shape == (32, net.num_nodes, ds.node_feature_dim)
    assert sample["target_pressure"].shape == (net.num_nodes,)
    assert sample["target_flow"].shape == (net.num_edges,)


def test_physics_consistent_requires_positive_num_steps() -> None:
    net = make_branch_network()
    with pytest.raises(ValueError):
        generate_physics_consistent_telemetry(net, num_steps=0, seed=0)


def test_physics_consistent_requires_num_steps_above_window() -> None:
    net = make_branch_network()
    with pytest.raises(ValueError):
        generate_physics_consistent_telemetry(
            net, num_steps=8, seed=0, window=32
        )


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_physics_consistent_is_deterministic_for_same_seed() -> None:
    net = make_branch_network()
    s1 = generate_physics_consistent_telemetry(net, num_steps=33, seed=42)
    s2 = generate_physics_consistent_telemetry(net, num_steps=33, seed=42)
    assert torch.equal(s1.pressure, s2.pressure)
    assert torch.equal(s1.flow, s2.flow)
    assert torch.equal(s1.demand, s2.demand)


def test_physics_consistent_changes_with_seed() -> None:
    net = make_branch_network()
    s1 = generate_physics_consistent_telemetry(net, num_steps=33, seed=1)
    s2 = generate_physics_consistent_telemetry(net, num_steps=33, seed=2)
    assert not torch.equal(s1.pressure, s2.pressure)
    assert not torch.equal(s1.demand, s2.demand)


# ---------------------------------------------------------------------------
# physics consistency: assemble_residuals norm is low at every timestep
# ---------------------------------------------------------------------------


def _residual_norm_at(net, demand_t, pressure_t, flow_t) -> float:
    perturbed = replace(net, demands=demand_t.to(torch.float64))
    r = assemble_residuals(
        perturbed, pressure_t.to(torch.float64), flow_t.to(torch.float64)
    )
    return float(torch.linalg.vector_norm(r).item())


@pytest.mark.parametrize(
    "factory",
    [make_branch_network, make_single_loop_network, make_pump_network],
)
def test_physics_consistent_residual_norm_is_low(factory) -> None:
    net = factory()
    series = generate_physics_consistent_telemetry(
        net, num_steps=33, seed=0, window=32
    )
    # Every step must satisfy the dPHM residual to a tight tolerance.
    worst = 0.0
    for t in range(series.num_steps):
        worst = max(
            worst,
            _residual_norm_at(
                net, series.demand[t], series.pressure[t], series.flow[t]
            ),
        )
    assert worst < 1e-3, f"max residual norm across steps was {worst}"


def test_legacy_synthetic_telemetry_residual_is_not_zero() -> None:
    """Sanity check: the old shape-only generator does not satisfy the
    dPHM residual — this is the Sprint 5 problem we are solving. If this
    starts being true, our gate metric is no longer meaningful.
    """
    net = make_branch_network()
    series = generate_synthetic_telemetry(
        net, num_steps=33, seed=0, window=32
    )
    norm = _residual_norm_at(
        net, series.demand[0], series.pressure[0], series.flow[0]
    )
    assert norm > 1.0


# ---------------------------------------------------------------------------
# backward compatibility: aliases still resolve and behave as before
# ---------------------------------------------------------------------------


def test_scada_alias_still_imports() -> None:
    assert ScadaSeries is TelemetrySeries


def test_generate_synthetic_scada_alias_still_runs() -> None:
    net = make_branch_network()
    a = generate_synthetic_scada(net, num_steps=32, seed=3)
    b = generate_synthetic_telemetry(net, num_steps=32, seed=3)
    assert torch.equal(a.pressure, b.pressure)
    assert torch.equal(a.flow, b.flow)
    assert torch.equal(a.demand, b.demand)
