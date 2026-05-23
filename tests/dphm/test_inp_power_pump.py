"""Sprint 14 — EPANET ``POWER`` pump translation and surrogate.

EPANET ``POWER`` pumps declare a constant shaft power
``P = rho * g * Q * H``, which is hyperbolic in ``Q`` and singular at
``Q -> 0``. The dPHM core only consumes the quadratic affinity model
``H(Q, s) = a0 s^2 + a1 s Q + a2 Q^2``, so Sprint 14 ships a
deliberately conservative surrogate
:func:`aquaoptima.dphm.fit_power_pump_surrogate` plus fallback / WNTR
parser hooks that route ``[PUMPS] ... POWER value`` rows through it.

These tests cover:

* the public surrogate helper — exact formula on a known operating
  point, diagnostics shape, droop sign, and validation of malformed
  inputs;
* the fallback INP parser path for a POWER pump row;
* the shipped reference fixture
  ``docs/examples/epanet_reference_power_pump.inp`` — load + solve;
* the analytic-Newton solve + per-pump residual at the operating
  point.

None of these tests import WNTR or any external EPANET runtime. WNTR
behaviour is exercised under
``tests/dphm/test_wntr_optional_import.py`` and
``tests/dphm/test_wntr_pump_helpers.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    assemble_residuals,
    fit_power_pump_surrogate,
    load_network_from_inp,
    newton_solve,
    pump_energy_residual,
    pump_head_gain,
)


_POWER_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_power_pump.inp"
)


# Physical constants the surrogate uses internally. We re-declare them
# here so the formula assertions don't depend on importing private
# module symbols.
_RHO = 1000.0      # kg/m^3
_G = 9.80665       # m/s^2
_KW_TO_W = 1000.0


# ---------------------------------------------------------------------------
# fit_power_pump_surrogate — formula + diagnostics
# ---------------------------------------------------------------------------


def test_surrogate_recovers_known_formula() -> None:
    """Surrogate must match the documented closed form to fp64 precision."""
    power_kw = 7.5
    q_nom = 0.015
    shutoff_multiplier = 1.5

    coeffs, diag = fit_power_pump_surrogate(
        power_kw, q_nom, shutoff_multiplier=shutoff_multiplier
    )
    a0, a1, a2 = coeffs

    expected_h_nom = (power_kw * _KW_TO_W) / (_RHO * _G * q_nom)
    expected_a0 = shutoff_multiplier * expected_h_nom
    expected_a1 = 0.0
    expected_a2 = (expected_h_nom - expected_a0) / (q_nom * q_nom)

    assert a0 == pytest.approx(expected_a0, abs=1e-9)
    assert a1 == pytest.approx(expected_a1, abs=1e-15)
    assert a2 == pytest.approx(expected_a2, abs=1e-6)

    # Sanity: surrogate passes through (Q_nom, H_nom).
    h_at_q_nom = a0 + a1 * q_nom + a2 * q_nom * q_nom
    assert h_at_q_nom == pytest.approx(expected_h_nom, abs=1e-9)


def test_surrogate_droops_with_default_multiplier() -> None:
    """Default shutoff_multiplier > 1 -> a2 < 0 (drooping curve)."""
    coeffs, diag = fit_power_pump_surrogate(7.5, 0.02)
    _, _, a2 = coeffs
    assert a2 < 0.0
    # And shut-off head exceeds the operating head.
    assert diag["shutoff_head_m"] > diag["head_at_nominal_m"]


def test_surrogate_diagnostics_shape() -> None:
    """The diagnostics dict carries the documented keys."""
    _, diag = fit_power_pump_surrogate(5.0, 0.01)
    expected_keys = {
        "approximation",
        "power_kw",
        "nominal_flow_m3s",
        "head_at_nominal_m",
        "shutoff_head_m",
        "shutoff_multiplier",
        "a0",
        "a1",
        "a2",
    }
    assert set(diag.keys()) == expected_keys
    assert diag["approximation"] == "constant_power_surrogate"
    assert diag["power_kw"] == pytest.approx(5.0)
    assert diag["nominal_flow_m3s"] == pytest.approx(0.01)
    # No 'rmse' — the surrogate is not a fit.
    assert "rmse" not in diag


def test_surrogate_respects_custom_shutoff_multiplier() -> None:
    """Larger shutoff_multiplier -> steeper droop (more negative a2)."""
    _, diag_low = fit_power_pump_surrogate(7.5, 0.015, shutoff_multiplier=1.2)
    _, diag_high = fit_power_pump_surrogate(7.5, 0.015, shutoff_multiplier=2.0)
    assert diag_high["a2"] < diag_low["a2"] < 0.0
    assert diag_high["shutoff_head_m"] > diag_low["shutoff_head_m"]


def test_surrogate_pump_head_gain_consistent_at_nominal() -> None:
    """``pump_head_gain`` at s=1 reproduces H_nom at Q=Q_nom."""
    coeffs, diag = fit_power_pump_surrogate(7.5, 0.015)
    coeffs_t = torch.tensor(coeffs, dtype=torch.float64)
    q = torch.tensor(0.015, dtype=torch.float64)
    s = torch.tensor(1.0, dtype=torch.float64)
    h = pump_head_gain(q, s, coeffs_t)
    assert float(h.item()) == pytest.approx(diag["head_at_nominal_m"], abs=1e-9)


# ---------------------------------------------------------------------------
# fit_power_pump_surrogate — validation
# ---------------------------------------------------------------------------


def test_surrogate_rejects_zero_power() -> None:
    with pytest.raises(ValueError, match="power_kw"):
        fit_power_pump_surrogate(0.0, 0.015)


def test_surrogate_rejects_negative_power() -> None:
    with pytest.raises(ValueError, match="power_kw"):
        fit_power_pump_surrogate(-1.0, 0.015)


def test_surrogate_rejects_non_finite_power() -> None:
    with pytest.raises(ValueError, match="power_kw"):
        fit_power_pump_surrogate(float("inf"), 0.015)
    with pytest.raises(ValueError, match="power_kw"):
        fit_power_pump_surrogate(float("nan"), 0.015)


def test_surrogate_rejects_zero_nominal_flow() -> None:
    with pytest.raises(ValueError, match="nominal_flow_m3s"):
        fit_power_pump_surrogate(7.5, 0.0)


def test_surrogate_rejects_negative_nominal_flow() -> None:
    with pytest.raises(ValueError, match="nominal_flow_m3s"):
        fit_power_pump_surrogate(7.5, -0.01)


def test_surrogate_rejects_non_finite_nominal_flow() -> None:
    with pytest.raises(ValueError, match="nominal_flow_m3s"):
        fit_power_pump_surrogate(7.5, float("nan"))


def test_surrogate_rejects_shutoff_multiplier_at_or_below_one() -> None:
    with pytest.raises(ValueError, match="shutoff_multiplier"):
        fit_power_pump_surrogate(7.5, 0.015, shutoff_multiplier=1.0)
    with pytest.raises(ValueError, match="shutoff_multiplier"):
        fit_power_pump_surrogate(7.5, 0.015, shutoff_multiplier=0.5)


# ---------------------------------------------------------------------------
# shipped POWER fixture — fallback parser
# ---------------------------------------------------------------------------


def test_power_fixture_exists() -> None:
    assert _POWER_FIXTURE_PATH.is_file(), (
        f"missing shipped POWER pump INP fixture at {_POWER_FIXTURE_PATH}"
    )


def test_power_fixture_loads_via_fallback_parser() -> None:
    net = load_network_from_inp(_POWER_FIXTURE_PATH, parser="fallback")
    assert isinstance(net, Network)
    # Two junctions + one reservoir = 3 nodes; one pipe + one pump = 2 edges.
    assert net.num_nodes == 3
    assert net.num_edges == 2
    assert net.num_fixed_heads == 1

    # Edge ordering: pipes first, then pumps (file-order convention).
    assert net.pipe_mask.tolist() == [True, False]
    assert net.pump_mask.tolist() == [False, True]


def test_power_fixture_pump_coeffs_match_surrogate_formula() -> None:
    """Shipped 7.5 kW pump + 15 L/s demand anchor -> known surrogate row."""
    net = load_network_from_inp(_POWER_FIXTURE_PATH, parser="fallback")
    pump_row = net.pump_coeffs[net.pump_mask][0]
    a0 = float(pump_row[0].item())
    a1 = float(pump_row[1].item())
    a2 = float(pump_row[2].item())

    # The fallback parser anchors on the total positive demand
    # (15 L/s = 0.015 m^3/s) for this fixture because the
    # downstream node J1 has zero demand. The Network stores
    # coefficients in the default torch dtype (float32), so we
    # compare with tolerances matched to that precision.
    expected_coeffs, _ = fit_power_pump_surrogate(7.5, 0.015)
    assert a0 == pytest.approx(expected_coeffs[0], abs=1e-3)
    assert a1 == pytest.approx(expected_coeffs[1], abs=1e-4)
    # a2 is large in magnitude (~1.1e5), so use a magnitude-matched
    # absolute tolerance rounded for float32.
    assert a2 == pytest.approx(expected_coeffs[2], rel=1e-5)

    # Surrogate is droop-shaped + finite.
    assert a0 > 0.0
    assert a2 < 0.0
    assert math.isfinite(a0) and math.isfinite(a1) and math.isfinite(a2)

    # Pump speed initialised to nominal s = 1.0.
    assert float(net.pump_speeds[net.pump_mask][0].item()) == pytest.approx(1.0)


def test_power_fixture_demand_balance() -> None:
    """Demand sum balances to zero after fixed-head rebalancing."""
    net = load_network_from_inp(_POWER_FIXTURE_PATH, parser="fallback")
    demand_sum = float(net.demands.sum().item())
    assert demand_sum == pytest.approx(0.0, abs=1e-9)
    # J2 is the only junction with a consumer.
    j2_demand = float(net.demands[1].item())
    assert j2_demand == pytest.approx(0.015, abs=1e-9)


# ---------------------------------------------------------------------------
# solver / residual evidence
# ---------------------------------------------------------------------------


def test_power_fixture_solves_with_analytic_newton() -> None:
    net = load_network_from_inp(_POWER_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-8


def test_power_fixture_residual_is_small_at_solution() -> None:
    """Full assembled residual at the solver's solution must be ~ 0."""
    net = load_network_from_inp(_POWER_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged

    r = assemble_residuals(net, result.heads, result.flows)
    assert torch.isfinite(r).all()
    assert float(torch.linalg.vector_norm(r).item()) < 1e-7


def test_power_fixture_pump_residual_and_gain_at_operating_point() -> None:
    """At the solved Q, the surrogate's per-pump residual is ~ 0."""
    net = load_network_from_inp(_POWER_FIXTURE_PATH, parser="fallback")
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

    # The pump must push positive flow (R1 -> J1) toward the consumer.
    assert float(Q.item()) > 0.0
    # Gain at the anchor flow should be close to the surrogate's
    # head_at_nominal (~50.99 m). Allow generous slack for the small
    # pipe head-loss term shifting the operating point slightly.
    assert 30.0 < float(gain.item()) < 80.0


# ---------------------------------------------------------------------------
# error paths on the integrated POWER parser
# ---------------------------------------------------------------------------


def _power_inp(pumps_body: str) -> str:
    return f"""[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0  15.0
[RESERVOIRS]
 R1   5.0
[PIPES]
 P1   J1   J2   200   150   130   0   OPEN
[PUMPS]
{pumps_body}[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""


def test_power_pump_non_numeric_value_raises(tmp_path: Path) -> None:
    inp = _power_inp(" PU1   R1   J1   POWER   not_a_number\n")
    path = tmp_path / "bad_power.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="not numeric"):
        load_network_from_inp(path, parser="fallback")


def test_power_pump_negative_value_raises(tmp_path: Path) -> None:
    inp = _power_inp(" PU1   R1   J1   POWER   -2.5\n")
    path = tmp_path / "neg_power.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="strictly positive"):
        load_network_from_inp(path, parser="fallback")


def test_power_pump_zero_value_raises(tmp_path: Path) -> None:
    inp = _power_inp(" PU1   R1   J1   POWER   0\n")
    path = tmp_path / "zero_power.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="strictly positive"):
        load_network_from_inp(path, parser="fallback")


def test_power_pump_with_unknown_endpoint_raises(tmp_path: Path) -> None:
    inp = _power_inp(" PU1   GHOST   J1   POWER   5\n")
    path = tmp_path / "ghost.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unknown source node"):
        load_network_from_inp(path, parser="fallback")


def test_power_pump_falls_back_to_default_nominal_when_no_demand(
    tmp_path: Path,
) -> None:
    """No positive demand anywhere -> surrogate uses 1 L/s default anchor.

    All junctions have zero demand and the only consumer (R1 reservoir)
    is fixed-head, so neither the downstream-demand nor
    total-positive-demand branch can fire. The parser must still load
    a finite, droop-shaped pump row.
    """
    inp = _power_inp(" PU1   R1   J1   POWER   5\n").replace(
        " J2   0.0  15.0", " J2   0.0   0.0"
    )
    path = tmp_path / "no_demand.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    pump_row = net.pump_coeffs[net.pump_mask][0]
    a0 = float(pump_row[0].item())
    a2 = float(pump_row[2].item())
    # Default fallback anchors on 1 L/s = 1e-3 m^3/s. Compare with
    # float32-matched tolerances; ``rel=1e-5`` covers both the
    # ~7.6e2 magnitude of a0 and the ~3.8e8 magnitude of a2.
    expected_coeffs, _ = fit_power_pump_surrogate(5.0, 1.0e-3)
    assert a0 == pytest.approx(expected_coeffs[0], rel=1e-5)
    assert a2 == pytest.approx(expected_coeffs[2], rel=1e-5)
    assert a0 > 0.0 and a2 < 0.0


def test_head_curve_pump_still_works_alongside_power_path(tmp_path: Path) -> None:
    """Sprint 12 HEAD curve path is unchanged by the Sprint 14 POWER addition."""
    inp = """[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0  10.0
[RESERVOIRS]
 R1   5.0
[PIPES]
 P1   J1   J2   100   150   130   0   OPEN
[PUMPS]
 PU1   R1   J1   HEAD   CV1
[CURVES]
 CV1   0    45
 CV1  10   44.92
 CV1  20   44.68
 CV1  30   44.28
[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""
    path = tmp_path / "head_after_power.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    pump_row = net.pump_coeffs[net.pump_mask][0]
    assert float(pump_row[0].item()) == pytest.approx(45.0, abs=1e-3)
    assert float(pump_row[2].item()) == pytest.approx(-800.0, abs=1e0)
