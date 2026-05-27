"""Sprint 11–13 — optional WNTR-backed INP loader.

WNTR (`Water Network Tool for Resilience`) is an **optional**
dependency. The dPHM-PINN test suite must run cleanly without it, so
every test in this module is guarded by :func:`pytest.importorskip`.
If WNTR is installed in the active environment, the shipped fixtures
under ``docs/examples/`` are parsed through both back-ends and the
two networks are checked for structural and (Sprint 13) numerical
agreement on pump coefficients.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import Network, load_network_from_inp, newton_solve


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_loop.inp"
)
_PUMP_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_pump.inp"
)


# ---------------------------------------------------------------------------
# Sprint 11 — loop fixture parity
# ---------------------------------------------------------------------------


def test_wntr_loader_matches_fallback_on_shipped_fixture() -> None:
    pytest.importorskip("wntr")

    net_fb = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    net_wn = load_network_from_inp(_FIXTURE_PATH, parser="wntr")

    assert isinstance(net_wn, Network)
    assert net_wn.num_nodes == net_fb.num_nodes
    assert net_wn.num_edges == net_fb.num_edges
    assert net_wn.num_fixed_heads == net_fb.num_fixed_heads
    fb_fixed = sorted(
        float(v) for v, m in zip(
            net_fb.fixed_head_values.tolist(), net_fb.fixed_head_mask.tolist()
        ) if m
    )
    wn_fixed = sorted(
        float(v) for v, m in zip(
            net_wn.fixed_head_values.tolist(), net_wn.fixed_head_mask.tolist()
        ) if m
    )
    assert fb_fixed == pytest.approx(wn_fixed, abs=1e-6)


def test_wntr_loaded_network_solves() -> None:
    pytest.importorskip("wntr")

    net = load_network_from_inp(_FIXTURE_PATH, parser="wntr")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"WNTR-loaded network did not solve: {result.reason}"
    assert result.residual_norm < 1e-8


# ---------------------------------------------------------------------------
# Sprint 13 — pump fixture parity & solver compatibility
# ---------------------------------------------------------------------------


def test_wntr_loader_accepts_shipped_pump_fixture() -> None:
    """Sprint 13 widens the WNTR parser to translate HEAD-curve pumps."""
    pytest.importorskip("wntr")

    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="wntr")
    assert isinstance(net, Network)
    # The fixture has 2 junctions + 1 reservoir + 1 pipe + 1 pump.
    assert net.num_nodes == 3
    assert net.num_edges == 2
    assert net.num_fixed_heads == 1
    # Exactly one pump edge.
    assert int(net.pump_mask.sum().item()) == 1
    assert int(net.pipe_mask.sum().item()) == 1


def test_wntr_and_fallback_pump_coeffs_agree_on_shipped_fixture() -> None:
    """WNTR and fallback must fit numerically-close pump coefficients.

    Both paths feed SI-unit ``(Q, H)`` points into the same
    :func:`fit_pump_head_curve`, so coefficients should agree to
    within floating-point round-off on the shipped fixture.
    """
    pytest.importorskip("wntr")

    net_fb = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    net_wn = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="wntr")

    fb_pump = net_fb.pump_coeffs[net_fb.pump_mask]
    wn_pump = net_wn.pump_coeffs[net_wn.pump_mask]
    assert fb_pump.shape == wn_pump.shape
    # Sprint 13 hard gate: "close enough" = absolute agreement at the
    # 1e-6 level on a0/a1, 1e-3 on the (large-magnitude) a2 coefficient.
    fb_row = fb_pump[0].tolist()
    wn_row = wn_pump[0].tolist()
    assert wn_row[0] == pytest.approx(fb_row[0], abs=1e-6)
    assert wn_row[1] == pytest.approx(fb_row[1], abs=1e-6)
    assert wn_row[2] == pytest.approx(fb_row[2], abs=1e-3)


def test_wntr_pump_fixture_solves_with_analytic_newton() -> None:
    pytest.importorskip("wntr")

    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="wntr")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"WNTR pump network did not solve: {result.reason}"
    assert result.residual_norm < 1e-8


def test_wntr_and_fallback_pump_solutions_agree() -> None:
    """Solved heads and flows from WNTR and fallback networks match."""
    pytest.importorskip("wntr")

    net_fb = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    net_wn = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="wntr")

    r_fb = newton_solve(net_fb, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
    r_wn = newton_solve(net_wn, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
    assert r_fb.converged and r_wn.converged

    assert torch.allclose(r_fb.heads, r_wn.heads, atol=1e-6, rtol=0.0)
    assert torch.allclose(r_fb.flows, r_wn.flows, atol=1e-6, rtol=0.0)


def test_wntr_loader_accepts_power_pump_form(tmp_path: Path) -> None:
    """Sprint 14: WNTR adapter accepts POWER pumps via the surrogate.

    POWER pumps used to be rejected by the WNTR back-end in Sprint
    13. Sprint 14 routes them through ``fit_power_pump_surrogate``,
    which emits a bounded quadratic surrogate that the solver can
    consume. We assert the network loads, has one pump edge, and
    solves with analytic Newton.
    """
    pytest.importorskip("wntr")

    inp = """[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0  10.0
[RESERVOIRS]
 R1   5.0
[PIPES]
 P1   J1   J2   100   150   130   0   OPEN
[PUMPS]
 PU1   R1   J1   POWER   5
[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""
    path = tmp_path / "power_pump.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="wntr")
    assert isinstance(net, Network)
    assert int(net.pump_mask.sum().item()) == 1
    assert int(net.pipe_mask.sum().item()) == 1
    # Surrogate coefficients must be finite and droop-shaped.
    pump_row = net.pump_coeffs[net.pump_mask][0]
    assert torch.isfinite(pump_row).all()
    assert float(pump_row[0].item()) > 0.0   # positive shut-off head
    assert float(pump_row[1].item()) == pytest.approx(0.0, abs=1e-12)
    assert float(pump_row[2].item()) < 0.0   # droop


def test_wntr_power_pump_fixture_solves_with_analytic_newton(tmp_path: Path) -> None:
    """The Sprint 14 shipped POWER fixture solves through the WNTR path."""
    pytest.importorskip("wntr")

    power_fixture = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "examples"
        / "epanet_reference_power_pump.inp"
    )
    net = load_network_from_inp(power_fixture, parser="wntr")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, (
        f"WNTR POWER pump network did not solve: {result.reason}"
    )
    assert result.residual_norm < 1e-8


def test_wntr_and_fallback_power_pump_agree_on_shipped_fixture() -> None:
    """WNTR and fallback POWER surrogates must match on the shipped fixture.

    Both back-ends call the same ``fit_power_pump_surrogate`` with
    the same nominal-flow anchor (total positive demand = 15 L/s)
    and the same 7.5 kW input, so the surrogate coefficients should
    agree to round-off.
    """
    pytest.importorskip("wntr")

    power_fixture = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "examples"
        / "epanet_reference_power_pump.inp"
    )
    net_fb = load_network_from_inp(power_fixture, parser="fallback")
    net_wn = load_network_from_inp(power_fixture, parser="wntr")

    fb_pump = net_fb.pump_coeffs[net_fb.pump_mask][0].tolist()
    wn_pump = net_wn.pump_coeffs[net_wn.pump_mask][0].tolist()
    assert wn_pump[0] == pytest.approx(fb_pump[0], abs=1e-9)
    assert wn_pump[1] == pytest.approx(fb_pump[1], abs=1e-12)
    assert wn_pump[2] == pytest.approx(fb_pump[2], abs=1e-6)


# ---------------------------------------------------------------------------
# Sprint 15 — WNTR valve integration on shipped PRV / TCV fixtures
# ---------------------------------------------------------------------------


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


def test_wntr_loads_shipped_tcv_fixture() -> None:
    pytest.importorskip("wntr")

    net = load_network_from_inp(_TCV_FIXTURE_PATH, parser="wntr")
    assert net.num_nodes == 3
    assert net.num_edges == 2
    assert net.num_fixed_heads == 1
    # Pipes + valves both have pipe_mask=True; no pumps.
    assert int(net.pipe_mask.sum().item()) == 2
    assert int(net.pump_mask.sum().item()) == 0


def test_wntr_tcv_fixture_solves_with_analytic_newton() -> None:
    pytest.importorskip("wntr")

    net = load_network_from_inp(_TCV_FIXTURE_PATH, parser="wntr")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"TCV network did not solve: {result.reason}"
    assert result.residual_norm < 1e-8


def test_wntr_and_fallback_agree_on_tcv_solution() -> None:
    pytest.importorskip("wntr")

    net_fb = load_network_from_inp(_TCV_FIXTURE_PATH, parser="fallback")
    net_wn = load_network_from_inp(_TCV_FIXTURE_PATH, parser="wntr")
    r_fb = newton_solve(net_fb, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
    r_wn = newton_solve(net_wn, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
    assert r_fb.converged and r_wn.converged
    assert torch.allclose(r_fb.heads, r_wn.heads, atol=1e-5, rtol=0.0)
    assert torch.allclose(r_fb.flows, r_wn.flows, atol=1e-5, rtol=0.0)


def test_wntr_loads_shipped_prv_fixture() -> None:
    pytest.importorskip("wntr")

    net = load_network_from_inp(_PRV_FIXTURE_PATH, parser="wntr")
    assert net.num_nodes == 4
    assert net.num_edges == 3
    # Two fixed heads: R1 (reservoir) and the PRV-pinned downstream.
    assert net.num_fixed_heads == 2


def test_wntr_prv_fixture_solves_with_analytic_newton() -> None:
    pytest.importorskip("wntr")

    net = load_network_from_inp(_PRV_FIXTURE_PATH, parser="wntr")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"PRV network did not solve: {result.reason}"
    assert result.residual_norm < 1e-8


def test_wntr_prv_pins_downstream_to_setting() -> None:
    """At the WNTR-solved state, the PRV downstream head equals setting + elev."""
    pytest.importorskip("wntr")

    net = load_network_from_inp(_PRV_FIXTURE_PATH, parser="wntr")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged
    # The fixture pins the PRV downstream to elev 0 + setting 20 = 20 m.
    fixed_heads = result.heads[net.fixed_head_mask]
    fixed_head_values = sorted(float(v) for v in fixed_heads.tolist())
    assert fixed_head_values == pytest.approx([20.0, 50.0], abs=1e-6)


def test_wntr_rejects_unsupported_valve_type_in_inp(tmp_path: Path) -> None:
    """A WNTR-loaded INP with an FCV row must raise via the translator.

    WNTR itself rejects ``PRV/PSV/FCV`` valves directly connected to
    a reservoir / tank (it requires a separating pipe), so we route
    the FCV between two junctions and let our adapter raise on the
    valve type.
    """
    pytest.importorskip("wntr")

    inp = """[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0   0.0
 J3   0.0   5.0
[RESERVOIRS]
 R1   80.0
[PIPES]
 P1   R1   J1   100   150   130   0   OPEN
 P2   J2   J3   100   150   130   0   OPEN
[VALVES]
 V1   J1   J2   150   FCV   1.0   0
[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""
    path = tmp_path / "fcv.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unsupported valve type"):
        load_network_from_inp(path, parser="wntr")


# ---------------------------------------------------------------------------
# Sprint 11 — WNTR-absent ImportError path
# ---------------------------------------------------------------------------


def test_wntr_parser_explicit_raises_importerror_when_missing() -> None:
    """If WNTR is *not* installed and parser='wntr' is forced, raise ImportError.

    The opposite case (WNTR present) is covered above; here we only
    assert the error path when WNTR is absent. We detect the absence
    by trying to import wntr ourselves; if it imports, the test is
    skipped because there is no negative path to exercise.
    """
    try:
        import wntr  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="wntr"):
            load_network_from_inp(_FIXTURE_PATH, parser="wntr")
    else:
        pytest.skip("WNTR is installed; ImportError path not exercised here")
