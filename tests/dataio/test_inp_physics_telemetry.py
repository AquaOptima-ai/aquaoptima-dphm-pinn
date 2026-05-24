"""Sprint 11 — physics-consistent telemetry on an INP-loaded network.

The Sprint 8 physics-consistent telemetry generator already accepts
any :class:`Network`. This test bundle simply checks that a network
*sourced from an EPANET ``.inp`` file* (via the Sprint 11 fallback
parser) round-trips through the same generator and produces a small,
finite-residual series — i.e. the INP loader does not introduce a
shape, dtype, or mass-balance regression.

Uses the analytic Jacobian path (Sprint 9) for speed.
"""

from __future__ import annotations

from pathlib import Path

import torch

from aquaoptima.dataio.telemetry import generate_physics_consistent_telemetry
from aquaoptima.dphm import (
    assemble_residuals_batched,
    load_network_from_inp,
)


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_loop.inp"
)


def test_inp_loaded_network_drives_physics_consistent_telemetry() -> None:
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")

    series = generate_physics_consistent_telemetry(
        net,
        num_steps=8,
        seed=11,
        window=4,
        demand_amplitude=0.1,
        demand_noise_std=0.005,
        solver_tol=1e-9,
        jacobian_mode="analytic",
    )

    assert series.num_steps == 8
    assert series.num_nodes == net.num_nodes
    assert series.num_edges == net.num_edges
    assert torch.isfinite(series.pressure).all()
    assert torch.isfinite(series.flow).all()
    assert torch.isfinite(series.demand).all()


def test_inp_telemetry_residuals_are_small() -> None:
    """Every timestep must satisfy mass+energy residuals to a small bound.

    The generator solves at float64 with ``solver_tol=1e-9`` and casts
    its output to the default torch dtype (float32 on the standard
    test runner). The residual bound therefore reflects float32
    round-trip accuracy on a 100-m-head fixture, not the float64
    solver tolerance.
    """
    from dataclasses import replace

    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    series = generate_physics_consistent_telemetry(
        net,
        num_steps=6,
        seed=42,
        window=4,
        demand_amplitude=0.1,
        demand_noise_std=0.005,
        solver_tol=1e-9,
        jacobian_mode="analytic",
    )

    # Round-trip the per-step demand back through the network so the
    # mass term lines up; check residual in float64 precision.
    work_dtype = torch.float64
    for i in range(series.num_steps):
        net_i = replace(net, demands=series.demand[i].to(work_dtype))
        heads = series.pressure[i].to(work_dtype).unsqueeze(0)
        flows = series.flow[i].to(work_dtype).unsqueeze(0)
        r = assemble_residuals_batched(net_i, heads, flows)
        rnorm = float(torch.linalg.vector_norm(r).item())
        assert rnorm < 1e-3, f"step {i} residual {rnorm} above bound"
