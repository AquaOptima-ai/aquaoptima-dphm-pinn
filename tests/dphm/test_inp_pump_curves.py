"""Sprint 12 — pump HEAD-curve parsing and quadratic curve fitting.

The fallback INP parser now translates ``[PUMPS] ... HEAD curve_id``
rows into a dPHM pump edge by fitting the referenced ``[CURVES]``
points against the affinity-style quadratic
``H(Q) = a0 + a1*Q + a2*Q^2`` at the static nominal speed ``s = 1``.

These tests cover:

* the public :func:`aquaoptima.dphm.fit_pump_head_curve` helper —
  exact recovery on noise-free quadratic data, diagnostics shape,
  validation of malformed input;
* the integrated fallback parser path that emits a Sprint 11-style
  :class:`Network` from a pump-bearing INP file;
* the shipped reference fixture under
  ``docs/examples/epanet_reference_pump.inp``.

None of these tests import WNTR or any external EPANET runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    fit_pump_head_curve,
    load_network_from_inp,
    pump_head_gain,
)


_PUMP_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_pump.inp"
)


# ---------------------------------------------------------------------------
# fit_pump_head_curve — recovery + diagnostics
# ---------------------------------------------------------------------------


def test_fit_recovers_exact_quadratic_coefficients() -> None:
    """A noise-free quadratic must recover ``[a0, a1, a2]`` to fp64 precision."""
    a0_true, a1_true, a2_true = 45.0, 0.0, -800.0
    Qs = [0.0, 0.010, 0.020, 0.030, 0.040, 0.050]
    pts = [(q, a0_true + a1_true * q + a2_true * q * q) for q in Qs]

    coeffs, diag = fit_pump_head_curve(pts)
    a0, a1, a2 = coeffs

    assert a0 == pytest.approx(a0_true, abs=1e-9)
    assert a1 == pytest.approx(a1_true, abs=1e-7)
    assert a2 == pytest.approx(a2_true, abs=1e-6)

    assert diag["rmse"] == pytest.approx(0.0, abs=1e-9)
    assert diag["max_abs_error"] == pytest.approx(0.0, abs=1e-9)
    assert diag["num_points"] == pytest.approx(len(Qs))
    assert diag["q_min"] == pytest.approx(min(Qs))
    assert diag["q_max"] == pytest.approx(max(Qs))
    assert diag["droop_ok"] == pytest.approx(1.0)


def test_fit_recovers_quadratic_with_nonzero_linear_term() -> None:
    """A pump curve with a non-zero ``a1`` term still fits cleanly."""
    a0_true, a1_true, a2_true = 30.0, -50.0, -400.0
    Qs = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05]
    pts = [(q, a0_true + a1_true * q + a2_true * q * q) for q in Qs]
    coeffs, diag = fit_pump_head_curve(pts)
    a0, a1, a2 = coeffs
    assert a0 == pytest.approx(a0_true, abs=1e-6)
    assert a1 == pytest.approx(a1_true, abs=1e-4)
    assert a2 == pytest.approx(a2_true, abs=1e-3)
    assert diag["droop_ok"] == pytest.approx(1.0)


def test_fit_consistent_with_pump_head_gain() -> None:
    """``pump_head_gain`` at ``s=1`` must reproduce the curve points."""
    pts = [(0.0, 45.0), (0.020, 44.68), (0.040, 43.72), (0.050, 43.00)]
    coeffs, _ = fit_pump_head_curve(pts)
    coeffs_t = torch.tensor(coeffs, dtype=torch.float64)
    for q, h in pts:
        gain = pump_head_gain(
            torch.tensor(q, dtype=torch.float64),
            torch.tensor(1.0, dtype=torch.float64),
            coeffs_t,
        )
        assert float(gain.item()) == pytest.approx(h, abs=1e-9)


def test_fit_flags_non_droop_curve() -> None:
    """``droop_ok`` is 0 when ``a2 > 0`` (head increases with Q)."""
    # Synthetic non-physical curve: H rises with Q.
    Qs = [0.0, 0.01, 0.02, 0.03, 0.04]
    pts = [(q, 10.0 + 500.0 * q * q) for q in Qs]
    coeffs, diag = fit_pump_head_curve(pts)
    assert coeffs[2] > 0.0
    assert diag["droop_ok"] == pytest.approx(0.0)


def test_fit_raises_on_too_few_points() -> None:
    with pytest.raises(ValueError, match="at least 3 points"):
        fit_pump_head_curve([(0.0, 10.0), (0.01, 9.0)])


def test_fit_raises_on_negative_flow() -> None:
    pts = [(-0.01, 10.0), (0.0, 10.0), (0.01, 9.5)]
    with pytest.raises(ValueError, match="non-negative"):
        fit_pump_head_curve(pts)


def test_fit_raises_on_non_positive_head() -> None:
    pts = [(0.0, 10.0), (0.01, 0.0), (0.02, -1.0)]
    with pytest.raises(ValueError, match="positive"):
        fit_pump_head_curve(pts)


def test_fit_raises_on_negative_shutoff_head() -> None:
    """Linear-extrapolation curve forces a0<=0 -> validation fires."""
    # Three colinear points that extrapolate to a0 = -10 at Q=0.
    pts = [(0.10, 10.0), (0.20, 30.0), (0.30, 50.0)]
    with pytest.raises(ValueError, match="shut-off head"):
        fit_pump_head_curve(pts)


# ---------------------------------------------------------------------------
# shipped fixture
# ---------------------------------------------------------------------------


def test_pump_fixture_exists() -> None:
    assert _PUMP_FIXTURE_PATH.is_file(), (
        f"missing shipped pump INP fixture at {_PUMP_FIXTURE_PATH}"
    )


def test_pump_fixture_loads_via_fallback_parser() -> None:
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    assert isinstance(net, Network)
    # Two junctions + one reservoir = 3 nodes; one pipe + one pump = 2 edges.
    assert net.num_nodes == 3
    assert net.num_edges == 2
    assert net.num_fixed_heads == 1

    # Edge ordering: pipes first, then pumps (file-order convention).
    assert net.pipe_mask.tolist() == [True, False]
    assert net.pump_mask.tolist() == [False, True]


def test_pump_fixture_recovers_known_curve_coefficients() -> None:
    """The shipped curve sits exactly on H = 45 - 800 Q^2 (m³/s units)."""
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    pump_row = net.pump_coeffs[net.pump_mask][0]
    a0 = float(pump_row[0].item())
    a1 = float(pump_row[1].item())
    a2 = float(pump_row[2].item())
    assert a0 == pytest.approx(45.0, abs=1e-4)
    assert a1 == pytest.approx(0.0, abs=1e-3)
    assert a2 == pytest.approx(-800.0, abs=1e-1)
    # Pump speed initialised to nominal s = 1.0.
    assert float(net.pump_speeds[net.pump_mask][0].item()) == pytest.approx(1.0)


def test_pump_fixture_demand_balance_and_units() -> None:
    """LPS demand -> m³/s conversion + fixed-head boundary absorbs the deficit."""
    net = load_network_from_inp(_PUMP_FIXTURE_PATH, parser="fallback")
    # J1 (no consumer) + J2 (15 L/s) + R1 (absorbs -15 L/s) -> sums to 0.
    demand_sum = float(net.demands.sum().item())
    assert demand_sum == pytest.approx(0.0, abs=1e-9)
    # J2 is the only junction with a consumer.
    j2_demand = float(net.demands[1].item())
    assert j2_demand == pytest.approx(0.015, abs=1e-6)


# ---------------------------------------------------------------------------
# error paths on the integrated parser
# ---------------------------------------------------------------------------


def _pump_inp(pumps_body: str, curves_body: str) -> str:
    return f"""[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0  10.0
[RESERVOIRS]
 R1   5.0
[PIPES]
 P1   J1   J2   100   150   130   0   OPEN
[PUMPS]
{pumps_body}[CURVES]
{curves_body}[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""


def test_pump_referencing_undefined_curve_raises(tmp_path: Path) -> None:
    inp = _pump_inp(
        pumps_body=" PU1   R1   J1   HEAD   GHOST\n",
        curves_body=" REAL   0   45\n REAL  20  44\n REAL  40  43\n",
    )
    path = tmp_path / "ghost_curve.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="undefined HEAD curve"):
        load_network_from_inp(path, parser="fallback")


def test_pump_with_unsupported_keyword_raises(tmp_path: Path) -> None:
    # POWER is supported from Sprint 14 onwards; SPEED is not — the
    # fallback parser only accepts ``HEAD curve_id`` and ``POWER value``.
    inp = _pump_inp(
        pumps_body=" PU1   R1   J1   SPEED   1.0\n",
        curves_body=" REAL   0   45\n REAL  20  44\n REAL  40  43\n",
    )
    path = tmp_path / "speed_pump.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unsupported keyword"):
        load_network_from_inp(path, parser="fallback")


def test_pump_curve_with_too_few_points_raises(tmp_path: Path) -> None:
    inp = _pump_inp(
        pumps_body=" PU1   R1   J1   HEAD   SHORT\n",
        curves_body=" SHORT   0   45\n SHORT  20  44\n",
    )
    path = tmp_path / "short_curve.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="at least 3 points"):
        load_network_from_inp(path, parser="fallback")


def test_pump_curve_with_negative_flow_raises(tmp_path: Path) -> None:
    inp = _pump_inp(
        pumps_body=" PU1   R1   J1   HEAD   BAD\n",
        curves_body=" BAD   -1   45\n BAD   0   44\n BAD  10  43\n",
    )
    path = tmp_path / "neg_q.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="negative flow"):
        load_network_from_inp(path, parser="fallback")


def test_pump_with_unknown_endpoint_raises(tmp_path: Path) -> None:
    inp = _pump_inp(
        pumps_body=" PU1   GHOST   J1   HEAD   REAL\n",
        curves_body=" REAL   0   45\n REAL  20  44\n REAL  40  43\n",
    )
    path = tmp_path / "ghost_endpoint.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unknown source node"):
        load_network_from_inp(path, parser="fallback")


def test_pump_with_too_few_columns_raises(tmp_path: Path) -> None:
    inp = _pump_inp(
        pumps_body=" PU1   R1   J1   HEAD\n",  # missing curve id
        curves_body=" REAL   0   45\n REAL  20  44\n REAL  40  43\n",
    )
    path = tmp_path / "short_pump.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match=r"\[PUMPS\] row needs at least 5"):
        load_network_from_inp(path, parser="fallback")


def test_duplicate_pump_id_raises(tmp_path: Path) -> None:
    inp = _pump_inp(
        pumps_body=" PU1   R1   J1   HEAD   REAL\n PU1   R1   J1   HEAD   REAL\n",
        curves_body=" REAL   0   45\n REAL  20  44\n REAL  40  43\n",
    )
    path = tmp_path / "dup_pump.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="duplicate edge"):
        load_network_from_inp(path, parser="fallback")


def test_pump_id_clashing_with_pipe_id_raises(tmp_path: Path) -> None:
    """Pump id collides with an existing pipe id -> duplicate edge."""
    inp = """[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0  10.0
[RESERVOIRS]
 R1   5.0
[PIPES]
 SHARE   J1   J2   100   150   130   0   OPEN
[PUMPS]
 SHARE   R1   J1   HEAD   REAL
[CURVES]
 REAL   0   45
 REAL  20  44
 REAL  40  43
[OPTIONS]
 Units    LPS
[END]
"""
    path = tmp_path / "shared_id.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="duplicate edge"):
        load_network_from_inp(path, parser="fallback")


def test_curves_section_grouping_preserves_repeated_id(tmp_path: Path) -> None:
    """Repeated curve ids in [CURVES] are grouped under one id, in file order.

    Verified indirectly by parsing a pump that references the grouped
    curve and recovering the expected quadratic coefficients.
    """
    inp = """[JUNCTIONS]
 J1   0.0   0.0
 J2   0.0  10.0
[RESERVOIRS]
 R1   5.0
[PIPES]
 P1   J1   J2   100   150   130   0   OPEN
[PUMPS]
 PU1   R1   J1   HEAD   CURVE_A
[CURVES]
 CURVE_A   0    45
 CURVE_A  10   44.92
 CURVE_A  20   44.68
 CURVE_A  30   44.28
[OPTIONS]
 Units    LPS
[END]
"""
    path = tmp_path / "grouped.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    pump_row = net.pump_coeffs[net.pump_mask][0]
    assert float(pump_row[0].item()) == pytest.approx(45.0, abs=1e-3)
    assert float(pump_row[2].item()) == pytest.approx(-800.0, abs=5e-1)
