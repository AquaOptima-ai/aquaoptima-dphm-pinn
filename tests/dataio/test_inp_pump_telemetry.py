"""Sprint 12 — analytic-Newton solve & physics-consistent telemetry
on the EPANET ``.inp`` pump fixture.

The pump fixture exercises the Sprint 12 ``[PUMPS] HEAD ...``
translation, so it is a credible end-to-end gate: parse → fit curve →
solver → telemetry. None of these tests touch WNTR or any external
EPANET runtime.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import torch

from aquaoptima.dataio.telemetry import generate_physics_consistent_telemetry
from aquaoptima.dphm import (
    assemble_residuals,
    assemble_residuals_batched,
    load_network_from_inp,
    newton_solve,
    pump_energy_residual,
    pump_head_gain,
)


_PUMP_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_pump.inp"
)


# ---------------------------------------------------------------------------
# solver
# ---------------------------------------------------------------------------


def test_pump_fixture_solves_with_analytic_newton() -> None:
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-8


def test_pump_fixture_analytic_matches_autograd() -> None:
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    r_auto = newton_solve(net, max_iterations=200, tol=1e-9, jacobian_mode="autograd")
    r_ana = newton_solve(net, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
    assert r_auto.converged and r_ana.converged
    assert torch.allclose(r_auto.heads, r_ana.heads, atol=1e-7, rtol=0.0)
    assert torch.allclose(r_auto.flows, r_ana.flows, atol=1e-7, rtol=0.0)


def test_pump_fixture_pump_residual_is_finite_and_small() -> None:
    """Per-pump energy residual at the solved operating point must be ≈0."""
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged

    pump_idx = int(net.pump_edge_indices[0].item())
    src = int(net.edge_index[0, pump_idx].item())
    dst = int(net.edge_index[1, pump_idx].item())
    h_u = result.heads[src]
    h_d = result.heads[dst]
    Q = result.flows[pump_idx]
    gain = pump_head_gain(
        Q,
        net.pump_speeds[pump_idx].to(Q.dtype),
        net.pump_coeffs[pump_idx].to(Q.dtype),
    )
    r_pump = pump_energy_residual(h_u, h_d, gain)
    assert torch.isfinite(r_pump)
    assert abs(float(r_pump.item())) < 1e-7
    # The pump actually adds head — verify gain is sensible (~45 m shut-off,
    # less ~ small Q² droop at the operating point).
    assert 40.0 < float(gain.item()) < 46.0


def test_pump_fixture_full_residual_batched() -> None:
    """Full assembled residual must be finite and below the working tolerance."""
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged

    r = assemble_residuals(net, result.heads, result.flows)
    assert torch.isfinite(r).all()
    assert float(torch.linalg.vector_norm(r).item()) < 1e-7

    # Batched path agrees on a replicated row.
    rb = assemble_residuals_batched(
        net, result.heads.unsqueeze(0), result.flows.unsqueeze(0)
    )
    assert rb.shape == (1, net.num_free_nodes + net.num_edges)
    assert torch.allclose(rb[0], r, atol=1e-9)


# ---------------------------------------------------------------------------
# physics-consistent telemetry
# ---------------------------------------------------------------------------


def test_pump_fixture_drives_physics_consistent_telemetry() -> None:
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")

    series = generate_physics_consistent_telemetry(
        net,
        num_steps=8,
        seed=12,
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


def test_pump_fixture_telemetry_residuals_are_small() -> None:
    """Every timestep satisfies the assembled residual to a small bound."""
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
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

    work_dtype = torch.float64
    for i in range(series.num_steps):
        net_i = replace(net, demands=series.demand[i].to(work_dtype))
        heads = series.pressure[i].to(work_dtype).unsqueeze(0)
        flows = series.flow[i].to(work_dtype).unsqueeze(0)
        r = assemble_residuals_batched(net_i, heads, flows)
        rnorm = float(torch.linalg.vector_norm(r).item())
        assert rnorm < 1e-3, f"step {i} residual {rnorm} above bound"


def test_pump_fixture_telemetry_pump_flow_is_positive() -> None:
    """Sanity check: the pump always pushes flow from reservoir to discharge."""
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    series = generate_physics_consistent_telemetry(
        net,
        num_steps=8,
        seed=7,
        window=4,
        demand_amplitude=0.1,
        demand_noise_std=0.005,
        solver_tol=1e-9,
        jacobian_mode="analytic",
    )
    pump_idx = int(net.pump_edge_indices[0].item())
    assert (series.flow[:, pump_idx] > 0).all(), (
        "pump flow should remain positive across the telemetry window"
    )
