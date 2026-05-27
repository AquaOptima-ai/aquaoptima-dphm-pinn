"""Sprint 14 — analytic-Newton solve & physics-consistent telemetry
on the EPANET ``.inp`` POWER pump fixture.

The fixture exercises the Sprint 14 ``[PUMPS] ... POWER value``
translation through :func:`fit_power_pump_surrogate`, so this is a
credible end-to-end gate: parse -> surrogate -> solver -> telemetry.
None of these tests touch WNTR or any external EPANET runtime.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import torch

from aquaoptima.dataio.telemetry import generate_physics_consistent_telemetry
from aquaoptima.dphm import (
    assemble_residuals_batched,
    load_network_from_inp,
)


_POWER_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_power_pump.inp"
)


def test_power_fixture_drives_physics_consistent_telemetry() -> None:
    net = load_network_from_inp(_POWER_FIXTURE_PATH, parser="fallback")

    series = generate_physics_consistent_telemetry(
        net,
        num_steps=8,
        seed=21,
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


def test_power_fixture_telemetry_residuals_are_small() -> None:
    """Every telemetry step satisfies the assembled residual to a small bound."""
    net = load_network_from_inp(_POWER_FIXTURE_PATH, parser="fallback")
    series = generate_physics_consistent_telemetry(
        net,
        num_steps=6,
        seed=43,
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


def test_power_fixture_telemetry_pump_flow_is_positive() -> None:
    """The POWER pump pushes flow from reservoir to discharge at every step."""
    net = load_network_from_inp(_POWER_FIXTURE_PATH, parser="fallback")
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
    pump_idx = int(net.pump_edge_indices[0].item())
    assert (series.flow[:, pump_idx] > 0).all(), (
        "POWER pump flow should remain positive across the telemetry window"
    )
