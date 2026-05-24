"""Sprint 16 — US-customary EPANET ``.inp`` fixtures.

These tests exercise the Sprint 16 unit-conversion code path on
shipped GPM/ft/in fixtures parallel to the SI fixtures from
Sprints 11 / 12 / 15. They cover:

* fallback parser end-to-end load of loop, pump, and TCV fixtures
* exact dimension conversions (feet/inches/GPM -> SI metres / m^3/s)
* analytic-Newton solve convergence on each US fixture
* fallback-vs-WNTR parity on each US fixture (skipped if WNTR
  is not installed)

None of the non-WNTR tests import WNTR or any external EPANET
runtime, and none touch the network.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    load_network_from_inp,
    newton_solve,
)
from aquaoptima.dphm.inp_io import resolve_unit_system


_FT_TO_M = 0.3048
_IN_TO_M = 0.0254
_GPM_TO_M3S = 0.003785411784 / 60.0


_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "examples"
)
_LOOP_GPM = _FIXTURE_DIR / "epanet_reference_loop_gpm.inp"
_PUMP_GPM = _FIXTURE_DIR / "epanet_reference_pump_gpm.inp"
_TCV_GPM = _FIXTURE_DIR / "epanet_reference_tcv_gpm.inp"

_LOOP_SI = _FIXTURE_DIR / "epanet_reference_loop.inp"


# ---------------------------------------------------------------------------
# fixtures present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", [_LOOP_GPM, _PUMP_GPM, _TCV_GPM], ids=["loop", "pump", "tcv"]
)
def test_us_fixtures_are_shipped(path: Path) -> None:
    assert path.is_file(), f"missing shipped US INP fixture at {path}"


# ---------------------------------------------------------------------------
# loop fixture (GPM)
# ---------------------------------------------------------------------------


def test_loop_gpm_loads_via_fallback_parser() -> None:
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    assert isinstance(net, Network)
    assert net.num_nodes == 5
    assert net.num_edges == 5
    assert net.num_fixed_heads == 1
    assert bool(net.pipe_mask.all().item())
    assert not bool(net.pump_mask.any().item())


def test_loop_gpm_converts_lengths_feet_to_metres() -> None:
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    expected = torch.tensor(
        [1000.0, 800.0, 700.0, 650.0, 900.0]
    ) * _FT_TO_M
    assert torch.allclose(net.lengths.double(), expected.double(), atol=1e-4)


def test_loop_gpm_converts_diameters_inches_to_metres() -> None:
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    expected = torch.tensor([10.0, 8.0, 6.0, 6.0, 6.0]) * _IN_TO_M
    assert torch.allclose(net.diameters.double(), expected.double(), atol=1e-6)


def test_loop_gpm_converts_reservoir_head_feet_to_metres() -> None:
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    # The reservoir is the last node by convention (junctions first,
    # then reservoirs/tanks).
    assert net.fixed_head_mask.tolist() == [False, False, False, False, True]
    assert float(net.fixed_head_values[-1].item()) == pytest.approx(
        300.0 * _FT_TO_M, abs=1e-4
    )


def test_loop_gpm_converts_demands_gpm_to_cms() -> None:
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    junction_demands_si = torch.tensor(
        [100.0, 150.0, 120.0, 80.0]
    ) * _GPM_TO_M3S
    # Junctions are the first four nodes.
    assert torch.allclose(
        net.demands[:4].double(), junction_demands_si.double(), atol=1e-8
    )
    # Reservoir absorbs the supply deficit -> -sum(junctions).
    assert float(net.demands[-1].item()) == pytest.approx(
        -float(junction_demands_si.sum().item()), abs=1e-8
    )


def test_loop_gpm_solves_with_analytic_newton() -> None:
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-7


def test_loop_gpm_solves_with_autograd_newton() -> None:
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="autograd"
    )
    assert result.converged
    assert result.residual_norm < 1e-7


# ---------------------------------------------------------------------------
# pump fixture (GPM)
# ---------------------------------------------------------------------------


def test_pump_gpm_loads_via_fallback_parser() -> None:
    net = load_network_from_inp(_PUMP_GPM, parser="fallback")
    assert isinstance(net, Network)
    assert net.num_nodes == 3
    assert net.num_edges == 2
    assert net.num_fixed_heads == 1
    assert net.pipe_mask.tolist() == [True, False]
    assert net.pump_mask.tolist() == [False, True]


def test_pump_gpm_recovers_si_curve_after_unit_conversion() -> None:
    """HEAD curve points are converted from (GPM, ft) -> (m^3/s, m)
    before fitting; the recovered quadratic must match the SI values.
    """
    net = load_network_from_inp(_PUMP_GPM, parser="fallback")
    pump_row = net.pump_coeffs[net.pump_mask][0]
    a0 = float(pump_row[0].item())
    a2 = float(pump_row[2].item())

    # The fixture's curve in raw units is (0, 150), (100, 148.5),
    # (200, 144), (300, 136.5), (400, 126), (500, 112.5).
    # Converted: a0 = 150 ft -> ~45.72 m. a2 needs to match the
    # quadratic fit on the converted points.
    assert a0 == pytest.approx(150.0 * _FT_TO_M, abs=1e-3)
    # The curve is roughly H_ft = 150 - 0.00015 Q_gpm^2 -> in SI
    # ``a2_si = -0.00015 ft / gpm^2 * 0.3048 m/ft / (6.309e-5)^2 (m^3/s/gpm)^-2``
    # ≈ -11486 m / (m^3/s)^2.
    expected_a2 = -0.00015 * _FT_TO_M / (_GPM_TO_M3S ** 2)
    assert a2 == pytest.approx(expected_a2, rel=1e-3)


def test_pump_gpm_demand_balance() -> None:
    net = load_network_from_inp(_PUMP_GPM, parser="fallback")
    demand_sum = float(net.demands.sum().item())
    assert demand_sum == pytest.approx(0.0, abs=1e-8)
    # J2 (200 GPM consumer) -> m^3/s.
    j2_demand = float(net.demands[1].item())
    assert j2_demand == pytest.approx(200.0 * _GPM_TO_M3S, abs=1e-7)


def test_pump_gpm_solves_with_analytic_newton() -> None:
    net = load_network_from_inp(_PUMP_GPM, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-7


# ---------------------------------------------------------------------------
# TCV fixture (GPM)
# ---------------------------------------------------------------------------


def test_tcv_gpm_loads_via_fallback_parser() -> None:
    net = load_network_from_inp(_TCV_GPM, parser="fallback")
    assert isinstance(net, Network)
    assert net.num_nodes == 3
    # 1 pipe + 1 TCV surrogate pipe = 2 edges (both pipe_mask=True).
    assert net.num_edges == 2
    assert net.pipe_mask.tolist() == [True, True]
    assert net.pump_mask.tolist() == [False, False]


def test_tcv_gpm_converts_valve_diameter_inches_to_metres() -> None:
    net = load_network_from_inp(_TCV_GPM, parser="fallback")
    # The TCV surrogate edge is the second edge.
    assert float(net.diameters[1].item()) == pytest.approx(
        6.0 * _IN_TO_M, abs=1e-6
    )


def test_tcv_gpm_setting_k_is_not_unit_scaled() -> None:
    """TCV setting K is dimensionless; the parser must NOT scale it.

    The TCV surrogate's effective length depends on K through
    ``K * V^2 / (2 g)``. If the parser accidentally scaled K by
    ``head_to_m = 0.3048``, the effective length would shrink by
    the same ratio compared to the equivalent SI fixture's TCV.
    Here we just confirm the effective length is positive and the
    network solves; the parity test below pins exact behaviour.
    """
    net = load_network_from_inp(_TCV_GPM, parser="fallback")
    assert float(net.lengths[1].item()) > 0.0


def test_tcv_gpm_solves_with_analytic_newton() -> None:
    net = load_network_from_inp(_TCV_GPM, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged
    assert result.residual_norm < 1e-7


# ---------------------------------------------------------------------------
# fallback vs WNTR parity (optional)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", [_LOOP_GPM, _PUMP_GPM, _TCV_GPM], ids=["loop", "pump", "tcv"]
)
def test_us_fixture_fallback_matches_wntr(path: Path) -> None:
    """For each US fixture: WNTR-parsed and fallback-parsed Networks
    must agree on every Sprint 11 / 12 / 15-relevant field to within
    the float32 tensor representation precision.
    """
    pytest.importorskip("wntr")
    net_fb = load_network_from_inp(path, parser="fallback")
    net_wn = load_network_from_inp(path, parser="wntr")

    assert net_wn.num_nodes == net_fb.num_nodes
    assert net_wn.num_edges == net_fb.num_edges
    assert net_wn.num_fixed_heads == net_fb.num_fixed_heads
    # Pipe / pump masks compared by integer-cast counts because WNTR's
    # node ordering can differ but the structural counts must match.
    assert int(net_wn.pipe_mask.sum().item()) == int(net_fb.pipe_mask.sum().item())
    assert int(net_wn.pump_mask.sum().item()) == int(net_fb.pump_mask.sum().item())

    # Sorted dimension tensors compared elementwise so node-ordering
    # differences between back-ends don't cause spurious failures.
    fb_lens = sorted(net_fb.lengths.tolist())
    wn_lens = sorted(net_wn.lengths.tolist())
    assert fb_lens == pytest.approx(wn_lens, rel=1e-5, abs=1e-5)
    fb_dia = sorted(net_fb.diameters.tolist())
    wn_dia = sorted(net_wn.diameters.tolist())
    assert fb_dia == pytest.approx(wn_dia, rel=1e-5, abs=1e-6)

    fb_demand_sum = float(net_fb.demands.sum().item())
    wn_demand_sum = float(net_wn.demands.sum().item())
    assert fb_demand_sum == pytest.approx(wn_demand_sum, abs=1e-9)

    fb_fixed_heads = sorted(
        v for v, m in zip(
            net_fb.fixed_head_values.tolist(), net_fb.fixed_head_mask.tolist()
        ) if m
    )
    wn_fixed_heads = sorted(
        v for v, m in zip(
            net_wn.fixed_head_values.tolist(), net_wn.fixed_head_mask.tolist()
        ) if m
    )
    assert fb_fixed_heads == pytest.approx(wn_fixed_heads, abs=1e-4)


def test_us_loop_fixture_wntr_solve_matches_fallback_heads() -> None:
    pytest.importorskip("wntr")
    net_fb = load_network_from_inp(_LOOP_GPM, parser="fallback")
    net_wn = load_network_from_inp(_LOOP_GPM, parser="wntr")
    r_fb = newton_solve(net_fb, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
    r_wn = newton_solve(net_wn, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
    assert r_fb.converged and r_wn.converged
    # Heads compared sorted (node ordering can differ across back-ends).
    fb_heads = sorted(r_fb.heads.tolist())
    wn_heads = sorted(r_wn.heads.tolist())
    assert fb_heads == pytest.approx(wn_heads, abs=1e-4)


# ---------------------------------------------------------------------------
# fallback US-vs-SI sanity (same physical network, different units)
# ---------------------------------------------------------------------------


def test_loop_gpm_units_are_not_si_loop_fixture() -> None:
    """The two shipped loop fixtures are different physical networks
    (chosen for round-number readability in each unit family). This
    test exists so future maintainers don't assume they are bit-equal:
    the parity test we DO ship is fallback-vs-WNTR on the *same* US
    fixture, above.
    """
    net_si = load_network_from_inp(_LOOP_SI, parser="fallback")
    net_us = load_network_from_inp(_LOOP_GPM, parser="fallback")
    # Both have 5 nodes, 5 pipes, 1 fixed-head boundary.
    assert net_si.num_nodes == net_us.num_nodes == 5
    assert net_si.num_edges == net_us.num_edges == 5


# ---------------------------------------------------------------------------
# POWER pump nominal flow uses converted demand
# ---------------------------------------------------------------------------


def test_power_pump_nominal_flow_uses_converted_us_demand(tmp_path: Path) -> None:
    """A POWER pump under US flow units should anchor on the
    *converted* downstream demand (m^3/s), not the raw GPM value.
    Otherwise the surrogate's head-at-nominal would be off by
    ``1/_GPM_TO_M3S`` (~15800x).
    """
    inp = """[JUNCTIONS]
 J1   0.0     0.0
 J2   0.0   200.0
[RESERVOIRS]
 R1   20.0
[PIPES]
 P1   J1   J2   660   6   130   0   OPEN
[PUMPS]
 PU1   R1   J1   POWER   10.0
[OPTIONS]
 Units    GPM
 Headloss H-W
[END]
"""
    path = tmp_path / "power_us.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")

    pump_row = net.pump_coeffs[net.pump_mask][0]
    a0 = float(pump_row[0].item())

    # Reproduce the surrogate calculation by hand:
    # - 10 HP -> 7.457 kW (Sprint 16 HP->kW conversion in US flow units)
    # - downstream demand: 200 GPM -> 200 * _GPM_TO_M3S m^3/s
    # - head_at_nominal = P_W / (rho g Q)  where P_W = 7457 W,
    #   rho = 1000, g = 9.80665, Q = 200 * _GPM_TO_M3S
    # - a0 (shut-off head) = 1.5 * head_at_nominal
    q_nom = 200.0 * _GPM_TO_M3S
    p_w = 10.0 * 0.7457 * 1.0e3
    head_at_nom = p_w / (1000.0 * 9.80665 * q_nom)
    expected_a0 = 1.5 * head_at_nom
    assert a0 == pytest.approx(expected_a0, rel=1e-4)


# ---------------------------------------------------------------------------
# PRV setting conversion under US flow units
# ---------------------------------------------------------------------------


def test_prv_setting_under_us_units_converts_feet_of_head_to_metres(
    tmp_path: Path,
) -> None:
    """PRV setting is declared in the head unit of the flow family
    (feet under US), and must be converted to metres before pinning
    the downstream node as a fixed-head boundary.
    """
    inp = """[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0   0.0
 J3   0.0  50.0
[RESERVOIRS]
 R1   200.0
[PIPES]
 P1   R1   J1   2000   3   130   0   OPEN
 P2   J2   J3    200   3   130   0   OPEN
[VALVES]
 V1   J1   J2     3   PRV   80.0   0
[OPTIONS]
 Units    GPM
 Headloss H-W
[END]
"""
    path = tmp_path / "prv_us.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # J2 is index 1, pinned by the PRV at elev + setting = 0 + 80 ft.
    assert bool(net.fixed_head_mask[1].item())
    assert float(net.fixed_head_values[1].item()) == pytest.approx(
        80.0 * _FT_TO_M, abs=1e-4
    )
