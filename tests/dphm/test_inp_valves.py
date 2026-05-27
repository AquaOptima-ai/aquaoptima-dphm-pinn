"""Sprint 15 — EPANET ``[VALVES]`` import (PRV / TCV).

Sprint 15 widens the dPHM INP importer to accept conservative
translations of the two steady-state-compatible EPANET valve forms:

* ``PRV`` (pressure-reducing valve) — pinned downstream as a
  fixed-head boundary at ``elev + setting``; the valve edge becomes
  a short pipe-like resistance. Documented limitation: mass balance
  on the now-fixed downstream node is dropped from the residual, so
  the PRV does NOT enforce flow / pressure regulation actively.
* ``TCV`` (throttle control valve) — pipe-like resistance edge whose
  effective Hazen-Williams length reproduces the minor-loss head
  loss ``K * V^2 / (2 g)`` at one anchor flow.

These tests cover:

* the public ``fit_tcv_resistance_surrogate`` helper — exact formula
  on a known operating point, diagnostics shape, validation;
* ``translate_valve_to_surrogate`` for PRV and TCV;
* the shipped reference fixtures ``epanet_reference_tcv.inp`` and
  ``epanet_reference_prv.inp`` — load + solve + diagnostic
  evidence;
* fallback-parser error paths for unsupported / malformed valves;
* preservation of Sprint 12 (HEAD curve), Sprint 14 (POWER pump)
  behaviour alongside the new valve path.

None of these tests import WNTR. WNTR helpers / integration are
exercised under ``tests/dphm/test_wntr_valve_helpers.py`` and
``tests/dphm/test_wntr_optional_import.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    assemble_residuals,
    fit_tcv_resistance_surrogate,
    load_network_from_inp,
    newton_solve,
    translate_valve_to_surrogate,
)


_TCV_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_tcv.inp"
)
_PRV_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_prv.inp"
)


_G = 9.80665  # m/s^2 — must match the helper's internal value


# ---------------------------------------------------------------------------
# fit_tcv_resistance_surrogate — formula + diagnostics
# ---------------------------------------------------------------------------


def test_tcv_surrogate_matches_minor_loss_at_anchor_flow() -> None:
    """``L_eff`` reproduces ``K * V^2/(2 g)`` exactly at Q_nom."""
    diameter = 0.15
    k = 2.5
    q_nom = 0.015
    params, diag = fit_tcv_resistance_surrogate(
        diameter_m=diameter, setting_k=k, nominal_flow_m3s=q_nom
    )

    area = math.pi * diameter * diameter / 4.0
    expected_h_minor = k * (q_nom ** 2) / (2.0 * _G * area * area)
    assert diag["head_loss_at_nominal_m"] == pytest.approx(expected_h_minor, abs=1e-12)

    # HW head loss at Q_nom with the chosen L_eff must match the minor
    # loss exactly.
    c = params["c_factor"]
    L = params["length_m"]
    h_hw = 10.67 * L / ((c ** 1.852) * (diameter ** 4.87)) * (q_nom ** 1.852)
    assert h_hw == pytest.approx(expected_h_minor, abs=1e-12)


def test_tcv_surrogate_adds_minor_loss_column() -> None:
    """``minor_loss`` is added to ``setting_k`` before computing L_eff."""
    diameter = 0.15
    q_nom = 0.015
    params_no_minor, _ = fit_tcv_resistance_surrogate(
        diameter_m=diameter, setting_k=2.5, nominal_flow_m3s=q_nom
    )
    params_with_minor, diag = fit_tcv_resistance_surrogate(
        diameter_m=diameter,
        setting_k=2.5,
        nominal_flow_m3s=q_nom,
        minor_loss=2.5,
    )
    # K_total doubled -> head loss at anchor doubled -> L_eff doubled.
    assert params_with_minor["length_m"] == pytest.approx(
        2.0 * params_no_minor["length_m"], rel=1e-9
    )
    assert diag["minor_loss"] == pytest.approx(2.5)


def test_tcv_surrogate_diagnostics_shape() -> None:
    _, diag = fit_tcv_resistance_surrogate(
        diameter_m=0.15, setting_k=2.5, nominal_flow_m3s=0.015
    )
    expected_keys = {
        "approximation",
        "valve_type",
        "diameter_m",
        "setting",
        "minor_loss",
        "nominal_flow_m3s",
        "effective_length_m",
        "effective_c_factor",
        "head_loss_at_nominal_m",
        "limitations",
    }
    assert set(diag.keys()) == expected_keys
    assert diag["approximation"] == "tcv_resistance_surrogate"
    assert diag["valve_type"] == "TCV"
    assert isinstance(diag["limitations"], str)


def test_tcv_surrogate_zero_setting_floors_length() -> None:
    """A fully-open TCV (K = 0) produces a positive floored length."""
    params, diag = fit_tcv_resistance_surrogate(
        diameter_m=0.15, setting_k=0.0, nominal_flow_m3s=0.015
    )
    assert params["length_m"] > 0.0
    assert params["length_m"] == pytest.approx(1.0e-6, abs=1e-18)
    assert diag["head_loss_at_nominal_m"] == pytest.approx(0.0, abs=1e-12)


def test_tcv_surrogate_rejects_non_positive_diameter() -> None:
    with pytest.raises(ValueError, match="diameter_m"):
        fit_tcv_resistance_surrogate(
            diameter_m=0.0, setting_k=2.5, nominal_flow_m3s=0.015
        )
    with pytest.raises(ValueError, match="diameter_m"):
        fit_tcv_resistance_surrogate(
            diameter_m=-0.1, setting_k=2.5, nominal_flow_m3s=0.015
        )


def test_tcv_surrogate_rejects_negative_setting() -> None:
    with pytest.raises(ValueError, match="setting_k"):
        fit_tcv_resistance_surrogate(
            diameter_m=0.15, setting_k=-1.0, nominal_flow_m3s=0.015
        )


def test_tcv_surrogate_rejects_non_finite_inputs() -> None:
    with pytest.raises(ValueError, match="diameter_m"):
        fit_tcv_resistance_surrogate(
            diameter_m=float("nan"), setting_k=2.5, nominal_flow_m3s=0.015
        )
    with pytest.raises(ValueError, match="nominal_flow_m3s"):
        fit_tcv_resistance_surrogate(
            diameter_m=0.15, setting_k=2.5, nominal_flow_m3s=float("inf")
        )


def test_tcv_surrogate_rejects_non_positive_nominal_flow() -> None:
    with pytest.raises(ValueError, match="nominal_flow_m3s"):
        fit_tcv_resistance_surrogate(
            diameter_m=0.15, setting_k=2.5, nominal_flow_m3s=0.0
        )


def test_tcv_surrogate_rejects_negative_minor_loss() -> None:
    with pytest.raises(ValueError, match="minor_loss"):
        fit_tcv_resistance_surrogate(
            diameter_m=0.15, setting_k=2.5,
            nominal_flow_m3s=0.015, minor_loss=-0.1,
        )


def test_tcv_surrogate_rejects_non_positive_c_factor() -> None:
    with pytest.raises(ValueError, match="c_factor"):
        fit_tcv_resistance_surrogate(
            diameter_m=0.15, setting_k=2.5,
            nominal_flow_m3s=0.015, c_factor=0.0,
        )


# ---------------------------------------------------------------------------
# translate_valve_to_surrogate — PRV path
# ---------------------------------------------------------------------------


def test_translate_prv_sets_downstream_fixed_head_with_elev() -> None:
    desc = translate_valve_to_surrogate(
        valve_id="V1",
        valve_type="PRV",
        diameter_m=0.08,
        setting=25.0,
        downstream_elev_m=10.0,
    )
    assert desc["valve_type"] == "PRV"
    assert desc["downstream_fixed_head_m"] == pytest.approx(35.0)
    diag = desc["diagnostics"]
    assert diag["approximation"] == "prv_pressure_boundary_surrogate"
    assert diag["valve_id"] == "V1"
    assert diag["setting"] == pytest.approx(25.0)
    assert diag["downstream_elev_m"] == pytest.approx(10.0)
    # Pipe surrogate must be a short, well-conditioned edge.
    p = desc["pipe_params"]
    assert p["length_m"] > 0.0
    assert p["diameter_m"] == pytest.approx(0.08)
    assert p["c_factor"] == pytest.approx(130.0)


def test_translate_prv_accepts_zero_elev() -> None:
    desc = translate_valve_to_surrogate(
        valve_id="V1", valve_type="PRV", diameter_m=0.1, setting=20.0
    )
    assert desc["downstream_fixed_head_m"] == pytest.approx(20.0)


def test_translate_prv_rejects_non_positive_setting() -> None:
    with pytest.raises(ValueError, match="setting"):
        translate_valve_to_surrogate(
            valve_id="V1", valve_type="PRV", diameter_m=0.1, setting=0.0
        )
    with pytest.raises(ValueError, match="setting"):
        translate_valve_to_surrogate(
            valve_id="V1", valve_type="PRV", diameter_m=0.1, setting=-5.0
        )


def test_translate_prv_rejects_non_finite_setting() -> None:
    with pytest.raises(ValueError, match="setting"):
        translate_valve_to_surrogate(
            valve_id="V1",
            valve_type="PRV",
            diameter_m=0.1,
            setting=float("nan"),
        )


def test_translate_prv_rejects_non_finite_elev() -> None:
    with pytest.raises(ValueError, match="downstream_elev_m"):
        translate_valve_to_surrogate(
            valve_id="V1",
            valve_type="PRV",
            diameter_m=0.1,
            setting=20.0,
            downstream_elev_m=float("inf"),
        )


# ---------------------------------------------------------------------------
# translate_valve_to_surrogate — TCV path
# ---------------------------------------------------------------------------


def test_translate_tcv_routes_through_fit_helper() -> None:
    desc = translate_valve_to_surrogate(
        valve_id="V1",
        valve_type="TCV",
        diameter_m=0.15,
        setting=2.5,
        nominal_flow_m3s=0.015,
    )
    assert desc["valve_type"] == "TCV"
    assert desc["downstream_fixed_head_m"] is None
    diag = desc["diagnostics"]
    assert diag["approximation"] == "tcv_resistance_surrogate"
    assert diag["valve_id"] == "V1"


def test_translate_tcv_requires_nominal_flow() -> None:
    with pytest.raises(ValueError, match="nominal_flow_m3s|nominal"):
        translate_valve_to_surrogate(
            valve_id="V1",
            valve_type="TCV",
            diameter_m=0.15,
            setting=2.5,
        )


# ---------------------------------------------------------------------------
# translate_valve_to_surrogate — unsupported / unknown forms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("vtype", ["FCV", "PSV", "PBV", "GPV"])
def test_translate_rejects_unsupported_active_valves(vtype: str) -> None:
    with pytest.raises(ValueError, match="unsupported valve type"):
        translate_valve_to_surrogate(
            valve_id="V1",
            valve_type=vtype,
            diameter_m=0.1,
            setting=10.0,
            nominal_flow_m3s=0.015,
        )


def test_translate_rejects_unknown_valve_type() -> None:
    with pytest.raises(ValueError, match="unknown valve type"):
        translate_valve_to_surrogate(
            valve_id="V1",
            valve_type="MYSTERY",
            diameter_m=0.1,
            setting=10.0,
            nominal_flow_m3s=0.015,
        )


def test_translate_rejects_non_positive_diameter() -> None:
    with pytest.raises(ValueError, match="diameter"):
        translate_valve_to_surrogate(
            valve_id="V1", valve_type="TCV", diameter_m=0.0,
            setting=2.5, nominal_flow_m3s=0.015,
        )


def test_translate_rejects_negative_minor_loss() -> None:
    with pytest.raises(ValueError, match="minor_loss"):
        translate_valve_to_surrogate(
            valve_id="V1", valve_type="TCV", diameter_m=0.1,
            setting=2.5, minor_loss=-0.1, nominal_flow_m3s=0.015,
        )


def test_translate_error_includes_valve_id() -> None:
    """Every translator error must tag the offending valve id."""
    with pytest.raises(ValueError, match=r"'MY_VALVE'"):
        translate_valve_to_surrogate(
            valve_id="MY_VALVE",
            valve_type="FCV",
            diameter_m=0.1,
            setting=10.0,
            nominal_flow_m3s=0.015,
        )


# ---------------------------------------------------------------------------
# Shipped TCV fixture — fallback parser
# ---------------------------------------------------------------------------


def test_tcv_fixture_exists() -> None:
    assert _TCV_FIXTURE_PATH.is_file(), (
        f"missing shipped TCV INP fixture at {_TCV_FIXTURE_PATH}"
    )


def test_tcv_fixture_loads_via_fallback_parser() -> None:
    net = load_network_from_inp(_TCV_FIXTURE_PATH, parser="fallback")
    assert isinstance(net, Network)
    # J1 + J2 + R1 = 3 nodes; P1 + V1 = 2 edges; R1 is the only fixed head.
    assert net.num_nodes == 3
    assert net.num_edges == 2
    assert net.num_fixed_heads == 1
    # Pipes first, then valves (both have pipe_mask=True).
    assert net.pipe_mask.tolist() == [True, True]
    assert net.pump_mask.tolist() == [False, False]


def test_tcv_fixture_edge_uses_surrogate_length() -> None:
    """The valve edge length must match the surrogate's L_eff at Q_nom=15 L/s."""
    net = load_network_from_inp(_TCV_FIXTURE_PATH, parser="fallback")
    expected_params, _ = fit_tcv_resistance_surrogate(
        diameter_m=0.15, setting_k=2.5, nominal_flow_m3s=0.015
    )
    # Edge ordering: [P1 (pipe), V1 (valve-pipe)].
    valve_length = float(net.lengths[1].item())
    valve_diameter = float(net.diameters[1].item())
    valve_c = float(net.c_factors[1].item())
    assert valve_length == pytest.approx(expected_params["length_m"], rel=1e-5)
    assert valve_diameter == pytest.approx(0.15, abs=1e-6)
    assert valve_c == pytest.approx(130.0, abs=1e-6)


def test_tcv_fixture_solves_with_analytic_newton() -> None:
    net = load_network_from_inp(_TCV_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-8


def test_tcv_fixture_residual_at_solution_is_small() -> None:
    net = load_network_from_inp(_TCV_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged
    r = assemble_residuals(net, result.heads, result.flows)
    assert torch.isfinite(r).all()
    assert float(torch.linalg.vector_norm(r).item()) < 1e-7


def test_tcv_fixture_demand_balances_to_zero() -> None:
    """Demand sum balances to zero after fixed-head rebalancing."""
    net = load_network_from_inp(_TCV_FIXTURE_PATH, parser="fallback")
    demand_sum = float(net.demands.sum().item())
    assert demand_sum == pytest.approx(0.0, abs=1e-9)


def test_tcv_fixture_valve_head_loss_matches_minor_loss() -> None:
    """The TCV edge's head loss at the solved Q matches the minor loss
    at Q_nom (because Q ≈ Q_nom for this fixture, the surrogate is
    near-exact)."""
    net = load_network_from_inp(_TCV_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged
    # Edge 1 is the valve (V1, R1 -> J1). Find its src/dst.
    src = int(net.edge_index[0, 1].item())
    dst = int(net.edge_index[1, 1].item())
    head_loss = float((result.heads[src] - result.heads[dst]).item())
    # K * V^2 / (2 g) at Q = 0.015 m^3/s, D = 0.15 m, K = 2.5.
    expected = (
        2.5 * 0.015 * 0.015
        / (2.0 * _G * (math.pi * 0.15 * 0.15 / 4.0) ** 2)
    )
    assert head_loss == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# Shipped PRV fixture — fallback parser
# ---------------------------------------------------------------------------


def test_prv_fixture_exists() -> None:
    assert _PRV_FIXTURE_PATH.is_file(), (
        f"missing shipped PRV INP fixture at {_PRV_FIXTURE_PATH}"
    )


def test_prv_fixture_loads_via_fallback_parser() -> None:
    net = load_network_from_inp(_PRV_FIXTURE_PATH, parser="fallback")
    assert isinstance(net, Network)
    # J1 + J2 + J3 + R1 = 4 nodes; P1 + P2 + V1 = 3 edges.
    assert net.num_nodes == 4
    assert net.num_edges == 3
    # Two fixed heads: R1 (reservoir) and J2 (pinned by PRV).
    assert net.num_fixed_heads == 2
    assert net.pipe_mask.tolist() == [True, True, True]
    assert net.pump_mask.tolist() == [False, False, False]


def test_prv_fixture_pins_downstream_to_setting() -> None:
    """J2 must be marked fixed-head at elev + setting = 0 + 20 = 20 m."""
    net = load_network_from_inp(_PRV_FIXTURE_PATH, parser="fallback")
    # Node ordering: J1(0), J2(1), J3(2), R1(3).
    assert net.fixed_head_mask.tolist() == [False, True, False, True]
    assert float(net.fixed_head_values[1].item()) == pytest.approx(20.0)
    assert float(net.fixed_head_values[3].item()) == pytest.approx(50.0)


def test_prv_fixture_solves_with_analytic_newton() -> None:
    net = load_network_from_inp(_PRV_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-8


def test_prv_fixture_downstream_head_equals_setting() -> None:
    """After solve, head at J2 must equal the pinned PRV setting."""
    net = load_network_from_inp(_PRV_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged
    j2_head = float(result.heads[1].item())
    assert j2_head == pytest.approx(20.0, abs=1e-6)


def test_prv_fixture_documents_mass_balance_caveat() -> None:
    """Document the PRV surrogate's known limitation: mass at the
    now-fixed downstream node is dropped from the residual, so flow
    through the PRV may differ from downstream demand.

    The test asserts the *limitation is real* (Q_V1 != Q_consumer)
    rather than pretending the surrogate enforces conservation. This
    is the documented PRV-as-pressure-boundary caveat.
    """
    net = load_network_from_inp(_PRV_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged
    # Edges: P1 (R1->J1), P2 (J2->J3), V1 (J1->J2). flows[2] is V1.
    q_prv = float(result.flows[2].item())
    q_consumer = float(result.flows[1].item())  # P2 J2->J3
    # Consumer demand is 2 L/s and Q_P2 equals demand (mass balance at J3).
    assert q_consumer == pytest.approx(0.002, abs=1e-6)
    # PRV flow is determined by the upstream path's pressure budget,
    # not by downstream demand. The two differ — that's the documented
    # surrogate limitation.
    assert q_prv > 0.0
    assert abs(q_prv - q_consumer) > 1e-4


# ---------------------------------------------------------------------------
# Fallback parser — error paths on integrated [VALVES] handling
# ---------------------------------------------------------------------------


def _valve_inp(valves_body: str) -> str:
    return f"""[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0  15.0
[RESERVOIRS]
 R1   50.0
[PIPES]
 P1   J1   J2   200   150   130   0   OPEN
[VALVES]
{valves_body}[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""


def test_unsupported_valve_type_raises(tmp_path: Path) -> None:
    """FCV / PSV / PBV / GPV rows must raise via the translator."""
    inp = _valve_inp(" V1   R1   J1   150   FCV   1.0   0\n")
    path = tmp_path / "fcv.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unsupported valve type"):
        load_network_from_inp(path, parser="fallback")


def test_unknown_valve_type_raises(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   R1   J1   150   MYSTERY   1.0   0\n")
    path = tmp_path / "mystery.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unknown valve type"):
        load_network_from_inp(path, parser="fallback")


def test_valve_non_numeric_diameter_raises(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   R1   J1   notnum   TCV   2.5   0\n")
    path = tmp_path / "baddia.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match=r"'V1' diameter column"):
        load_network_from_inp(path, parser="fallback")


def test_valve_non_numeric_setting_raises(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   R1   J1   150   TCV   notnum   0\n")
    path = tmp_path / "badset.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match=r"'V1' setting column"):
        load_network_from_inp(path, parser="fallback")


def test_valve_non_numeric_minor_loss_raises(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   R1   J1   150   TCV   2.5   notnum\n")
    path = tmp_path / "badminor.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match=r"'V1' minor-loss column"):
        load_network_from_inp(path, parser="fallback")


def test_valve_non_positive_diameter_raises(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   R1   J1   0   TCV   2.5   0\n")
    path = tmp_path / "zerodia.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="non-positive"):
        load_network_from_inp(path, parser="fallback")


def test_valve_negative_diameter_raises(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   R1   J1   -150   TCV   2.5   0\n")
    path = tmp_path / "negdia.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="non-positive"):
        load_network_from_inp(path, parser="fallback")


def test_valve_negative_setting_raises_for_tcv(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   R1   J1   150   TCV   -1.0   0\n")
    path = tmp_path / "negset.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="non-negative|setting_k"):
        load_network_from_inp(path, parser="fallback")


def test_valve_non_positive_prv_setting_raises(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   R1   J1   150   PRV   0.0   0\n")
    path = tmp_path / "zeroprv.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="(PRV).*setting"):
        load_network_from_inp(path, parser="fallback")


def test_valve_short_row_raises(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   R1   J1   150   TCV\n")
    path = tmp_path / "short.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match=r"\[VALVES\]"):
        load_network_from_inp(path, parser="fallback")


def test_valve_unknown_endpoint_raises(tmp_path: Path) -> None:
    inp = _valve_inp(" V1   GHOST   J1   150   TCV   2.5   0\n")
    path = tmp_path / "ghost.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unknown source node"):
        load_network_from_inp(path, parser="fallback")


def test_valve_duplicate_id_raises(tmp_path: Path) -> None:
    """Valve id must be unique across pipes / pumps / valves."""
    inp = """[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0  15.0
[RESERVOIRS]
 R1   50.0
[PIPES]
 V1   J1   J2   200   150   130   0   OPEN
[VALVES]
 V1   R1   J1   150   TCV   2.5   0
[OPTIONS]
 Units    LPS
[END]
"""
    path = tmp_path / "dup.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="duplicate edge"):
        load_network_from_inp(path, parser="fallback")


def test_prv_downstream_already_fixed_raises(tmp_path: Path) -> None:
    """A PRV whose downstream is already a reservoir/tank must raise.

    Overwriting an existing fixed-head boundary would silently change
    the network's physics, so the parser refuses.
    """
    inp = """[JUNCTIONS]
 J1   0.0   0.0
[RESERVOIRS]
 R1   80.0
[PIPES]
 P1   R1   J1   100   150   130   0   OPEN
[VALVES]
 V1   J1   R1   150   PRV   50.0   0
[OPTIONS]
 Units    LPS
[END]
"""
    path = tmp_path / "prv_into_reservoir.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="already a fixed-head"):
        load_network_from_inp(path, parser="fallback")


def test_empty_valves_section_is_tolerated(tmp_path: Path) -> None:
    """An empty [VALVES] section must not perturb a valveless network."""
    inp = """[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0   5.0
[RESERVOIRS]
 R1   50.0
[PIPES]
 P1   R1   J1   100   150   130   0   OPEN
 P2   J1   J2   100   150   130   0   OPEN
[VALVES]
;ID   Node1   Node2   Diameter   Type   Setting   MinorLoss
[OPTIONS]
 Units    LPS
[END]
"""
    path = tmp_path / "empty_valves.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    assert net.num_edges == 2
    assert net.pipe_mask.tolist() == [True, True]


# ---------------------------------------------------------------------------
# Backwards compatibility — pump + valve in the same file
# ---------------------------------------------------------------------------


def test_head_curve_pump_alongside_valve(tmp_path: Path) -> None:
    """A HEAD-curve pump and a TCV valve coexist in the same .inp."""
    inp = """[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0  10.0
[RESERVOIRS]
 R1   5.0
[PIPES]
 P1   J1   J2   100   150   130   0   OPEN
[PUMPS]
 PU1   R1   J1   HEAD   CV1
[VALVES]
 V1   J1   J2   150   TCV   1.0   0
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
    path = tmp_path / "head_and_valve.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # Ordering: P1 (pipe), PU1 (pump), V1 (valve as pipe-like).
    assert net.pipe_mask.tolist() == [True, False, True]
    assert net.pump_mask.tolist() == [False, True, False]
    assert net.num_edges == 3


def test_power_pump_alongside_valve(tmp_path: Path) -> None:
    """A POWER pump and a PRV valve coexist; PRV pins J1 to setting."""
    inp = """[JUNCTIONS]
 J1   0.0    0.0
 J2   0.0    5.0
 J3   0.0    0.0
[RESERVOIRS]
 R1   5.0
[PIPES]
 P1   J1   J2   100   150   130   0   OPEN
 P2   J3   J2   100   150   130   0   OPEN
[PUMPS]
 PU1   R1   J3   POWER   5
[VALVES]
 V1   R1   J1   150   PRV   30.0   0
[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""
    path = tmp_path / "power_and_prv.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # J1 must be fixed-head at 30 m (PRV setting + elev 0).
    j1_idx = 0  # JUNCTIONS appear first
    assert bool(net.fixed_head_mask[j1_idx].item())
    assert float(net.fixed_head_values[j1_idx].item()) == pytest.approx(30.0)
    # Ordering: P1, P2 (pipes), PU1 (pump), V1 (valve).
    assert net.pipe_mask.tolist() == [True, True, False, True]
    assert net.pump_mask.tolist() == [False, False, True, False]
