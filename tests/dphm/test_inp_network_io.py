"""Sprint 11 — EPANET ``.inp`` topology loader, fallback parser.

These tests exercise the dependency-free :mod:`aquaoptima.dphm.inp_io`
parser. They never touch WNTR or any external EPANET runtime, never
hit the network, and are deterministic — they only round-trip the
shipped fixture under ``docs/examples/`` and a small set of
hand-built malformed snippets.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    assemble_residuals_batched,
    load_network_from_inp,
    newton_solve,
)


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_loop.inp"
)


# ---------------------------------------------------------------------------
# happy path — shipped fixture
# ---------------------------------------------------------------------------


def test_shipped_fixture_exists() -> None:
    assert _FIXTURE_PATH.is_file(), (
        f"missing shipped INP fixture at {_FIXTURE_PATH}"
    )


def test_fallback_parser_loads_shipped_fixture() -> None:
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    assert isinstance(net, Network)
    # Four junctions + one reservoir = 5 nodes, five pipes = 5 edges.
    assert net.num_nodes == 5
    assert net.num_edges == 5
    assert net.num_fixed_heads == 1
    assert bool(net.pipe_mask.all().item())
    assert not bool(net.pump_mask.any().item())


def test_fallback_parser_accepts_str_path() -> None:
    net = load_network_from_inp(str(_FIXTURE_PATH), parser="fallback")
    assert net.num_nodes == 5


def test_fallback_parser_preserves_node_ordering() -> None:
    """Junctions appear first (file order), then reservoirs, then tanks."""
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    # The fixture has J1..J4 (junctions) followed by R1 (reservoir).
    # Only the reservoir is fixed-head, and it is the *last* node.
    assert net.fixed_head_mask.tolist() == [False, False, False, False, True]
    assert float(net.fixed_head_values[-1].item()) == pytest.approx(100.0)


def test_fallback_parser_converts_lps_demands_to_cms() -> None:
    """[OPTIONS] Units = LPS -> demands divided by 1000 (L/s -> m^3/s)."""
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    # Junctions: 10, 15, 12, 8 L/s -> 0.010, 0.015, 0.012, 0.008 m^3/s.
    # The reservoir absorbs the balance: -0.045 m^3/s.
    expected = torch.tensor([0.010, 0.015, 0.012, 0.008, -0.045])
    assert torch.allclose(net.demands.double(), expected.double(), atol=1e-9)


def test_fallback_parser_converts_mm_to_m_for_diameter() -> None:
    """Diameters declared in mm in the file -> stored in m on the Network."""
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    expected = torch.tensor([0.250, 0.200, 0.150, 0.150, 0.150])
    assert torch.allclose(net.diameters.double(), expected.double(), atol=1e-9)


def test_fallback_parser_keeps_lengths_in_metres() -> None:
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    expected = torch.tensor([300.0, 250.0, 220.0, 200.0, 280.0])
    assert torch.allclose(net.lengths.double(), expected.double(), atol=1e-9)


def test_fallback_parser_keeps_roughness_unchanged() -> None:
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    assert torch.allclose(
        net.c_factors.double(), torch.full((5,), 130.0, dtype=torch.float64)
    )


# ---------------------------------------------------------------------------
# solver / residual compatibility
# ---------------------------------------------------------------------------


def test_loaded_inp_network_solves_with_analytic_newton() -> None:
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-8


def test_loaded_inp_network_solves_with_autograd_newton() -> None:
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="autograd"
    )
    assert result.converged
    assert result.residual_norm < 1e-8


def test_loaded_inp_network_analytic_matches_autograd() -> None:
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    r_auto = newton_solve(net, max_iterations=200, tol=1e-9, jacobian_mode="autograd")
    r_ana = newton_solve(net, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
    assert torch.allclose(r_auto.heads, r_ana.heads, atol=1e-7, rtol=0.0)
    assert torch.allclose(r_auto.flows, r_ana.flows, atol=1e-7, rtol=0.0)


def test_loaded_inp_network_works_with_batched_residual() -> None:
    net = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    heads = result.heads.unsqueeze(0).repeat(3, 1)
    flows = result.flows.unsqueeze(0).repeat(3, 1)
    res = assemble_residuals_batched(net, heads, flows)
    assert res.shape == (3, net.num_free_nodes + net.num_edges)
    # Same row replicated -> identical residual per batch row.
    assert torch.allclose(res[0], res[1])
    assert torch.allclose(res[0], res[2])
    # And the residual norm should match the solver's converged norm.
    assert float(torch.linalg.vector_norm(res[0]).item()) < 1e-7


# ---------------------------------------------------------------------------
# comment / blank-line handling
# ---------------------------------------------------------------------------


def test_fallback_parser_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    """Inline ``;`` comments and blank rows must not perturb parsing."""
    inp = """
[TITLE]
; line comment
   ; indented line comment

[JUNCTIONS]
;ID  Elev   Demand
 J1   0.0    1.0       ; trailing
                       ; just-a-comment row

 J2   0.0    2.0

[RESERVOIRS]
;ID  Head
 R1   50.0   ;trailing

[PIPES]
;ID   N1   N2   L     D     C    minor  status
 P1   R1   J1   100   200   130  0      OPEN
 P2   J1   J2   100   200   130  0      OPEN

[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""
    path = tmp_path / "stripped.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    assert net.num_nodes == 3
    assert net.num_edges == 2
    # 1 + 2 = 3 L/s in -> 0.003 m^3/s -> reservoir supplies -0.003.
    assert float(net.demands[-1].item()) == pytest.approx(-0.003, abs=1e-9)


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def _minimal_inp(extra_pipes: str = "") -> str:
    return f"""[JUNCTIONS]
 J1   0.0   5.0
[RESERVOIRS]
 R1   80.0
[PIPES]
 P1   R1   J1   100   150   130   0   OPEN
{extra_pipes}
[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""


def test_unknown_endpoint_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0.0  5.0
[RESERVOIRS]
 R1  80.0
[PIPES]
 P1  R1  ghost  100  150  130  0  OPEN
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "bad.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unknown target node"):
        load_network_from_inp(path, parser="fallback")


def test_missing_fixed_head_boundary_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0.0  5.0
 J2  0.0  5.0
[PIPES]
 P1  J1  J2  100  150  130  0  OPEN
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "no_reservoir.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="fixed-head"):
        load_network_from_inp(path, parser="fallback")


def test_missing_pipes_section_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0.0  5.0
[RESERVOIRS]
 R1  80.0
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "no_pipes.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="PIPES"):
        load_network_from_inp(path, parser="fallback")


def test_nonpositive_pipe_length_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0.0  5.0
[RESERVOIRS]
 R1  80.0
[PIPES]
 P1  R1  J1  0  150  130  0  OPEN
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "bad_len.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="non-positive length"):
        load_network_from_inp(path, parser="fallback")


def test_nonpositive_pipe_diameter_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0.0  5.0
[RESERVOIRS]
 R1  80.0
[PIPES]
 P1  R1  J1  100  -25  130  0  OPEN
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "bad_dia.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="non-positive diameter"):
        load_network_from_inp(path, parser="fallback")


def test_nonpositive_pipe_roughness_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0.0  5.0
[RESERVOIRS]
 R1  80.0
[PIPES]
 P1  R1  J1  100  150  -10  0  OPEN
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "bad_c.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="c_factor|roughness"):
        load_network_from_inp(path, parser="fallback")


def test_pumps_section_without_curve_raises_in_fallback(tmp_path: Path) -> None:
    """Sprint 12: pump rows that reference an *undefined* HEAD curve still raise.

    The Sprint 11 contract was "any [PUMPS] section raises". Sprint 12
    softens that — well-formed ``HEAD curve_id`` rows are translated into
    a dPHM pump edge when the referenced curve is declared in
    ``[CURVES]``. The error path therefore moves from "any pump" to
    "pump references undefined HEAD curve".
    """
    inp = """[JUNCTIONS]
 J1  0.0  0.0
 J2  0.0  5.0
[RESERVOIRS]
 R1  80.0
[PIPES]
 P1  J2  J1  100  150  130  0  OPEN
[PUMPS]
 PU1  R1  J2  HEAD curve1
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "with_pump.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="undefined HEAD curve"):
        load_network_from_inp(path, parser="fallback")


def test_unsupported_valves_section_raises(tmp_path: Path) -> None:
    """Sprint 15 supports PRV/TCV; unsupported valve types still raise.

    Sprint 11–14 rejected the entire ``[VALVES]`` section. Sprint 15
    softens that — ``PRV`` and ``TCV`` rows are translated through
    the conservative surrogate. Active flow / pressure-sustaining /
    pressure-breaker / general-purpose valves (``FCV``, ``PSV``,
    ``PBV``, ``GPV``) still raise a clear ``ValueError`` with the
    valve id.
    """
    inp = """[JUNCTIONS]
 J1  0.0  0.0
 J2  0.0  5.0
[RESERVOIRS]
 R1  80.0
[PIPES]
 P1  R1  J1  100  150  130  0  OPEN
[VALVES]
 V1  J1  J2  150  FCV  1.0  0
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "with_valve.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unsupported valve type"):
        load_network_from_inp(path, parser="fallback")


def test_duplicate_node_id_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0.0  5.0
 J1  0.0  5.0
[RESERVOIRS]
 R1  80.0
[PIPES]
 P1  R1  J1  100  150  130  0  OPEN
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "dup_node.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="duplicate node"):
        load_network_from_inp(path, parser="fallback")


def test_duplicate_pipe_id_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0.0  5.0
 J2  0.0  5.0
[RESERVOIRS]
 R1  80.0
[PIPES]
 P1  R1  J1  100  150  130  0  OPEN
 P1  J1  J2  100  150  130  0  OPEN
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "dup_pipe.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="duplicate edge"):
        load_network_from_inp(path, parser="fallback")


def test_us_customary_flow_unit_now_loads_in_fallback(tmp_path: Path) -> None:
    """Sprint 16: the fallback parser accepts US-customary flow units.

    Before Sprint 16 the fallback parser rejected any US flow unit
    with a clear ValueError. Sprint 16 widens the unit manifest to
    cover GPM/CFS/MGD/IMGD/AFD with the correct length/diameter/head
    conversions, so US-unit fixtures now parse cleanly. See
    :func:`aquaoptima.dphm.inp_io.resolve_unit_system`.
    """
    inp = """[JUNCTIONS]
 J1  0  5
[RESERVOIRS]
 R1  100
[PIPES]
 P1  R1  J1  100  6  130  0  OPEN
[OPTIONS]
 Units  GPM
"""
    path = tmp_path / "us_units.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # 100 ft -> 30.48 m, 6 in -> 0.1524 m, 100 ft head -> 30.48 m.
    # Tolerances reflect the dtype precision (float32 default) of the
    # underlying ``Network`` tensors.
    assert float(net.lengths[0].item()) == pytest.approx(30.48, abs=1e-4)
    assert float(net.diameters[0].item()) == pytest.approx(0.1524, abs=1e-6)
    assert float(net.fixed_head_values[-1].item()) == pytest.approx(
        100.0 * 0.3048, abs=1e-4
    )


def test_unknown_flow_unit_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0  5
[RESERVOIRS]
 R1  100
[PIPES]
 P1  R1  J1  100  150  130  0  OPEN
[OPTIONS]
 Units  BARRELS
"""
    path = tmp_path / "bad_units.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unknown EPANET flow unit"):
        load_network_from_inp(path, parser="fallback")


def test_non_hw_headloss_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0  5
[RESERVOIRS]
 R1  100
[PIPES]
 P1  R1  J1  100  150  130  0  OPEN
[OPTIONS]
 Units    LPS
 Headloss D-W
"""
    path = tmp_path / "dw.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="Hazen-Williams|H-W"):
        load_network_from_inp(path, parser="fallback")


def test_invalid_parser_value_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="parser"):
        load_network_from_inp(_FIXTURE_PATH, parser="totally-made-up")


def test_invalid_units_value_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="units"):
        load_network_from_inp(_FIXTURE_PATH, units="cgs")


def test_invalid_default_c_factor_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="default_c_factor"):
        load_network_from_inp(
            _FIXTURE_PATH, parser="fallback", default_c_factor=0.0
        )


def test_closed_pipe_status_raises(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0  5
[RESERVOIRS]
 R1  100
[PIPES]
 P1  R1  J1  100  150  130  0  CLOSED
[OPTIONS]
 Units  LPS
"""
    path = tmp_path / "closed.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="status"):
        load_network_from_inp(path, parser="fallback")


def test_unknown_section_is_ignored(tmp_path: Path) -> None:
    """Sections like [COORDINATES] / [PATTERNS] must be silently ignored.

    Documented in ``docs/epanet-inp-import.md``: only sections that
    *materially* change topology matter; the dPHM core is steady-state
    and source-agnostic, so report / display / pattern metadata is
    safely dropped.
    """
    inp = """[JUNCTIONS]
 J1  0  5
[RESERVOIRS]
 R1  100
[PIPES]
 P1  R1  J1  100  150  130  0  OPEN
[COORDINATES]
 J1  10.0  20.0
 R1   0.0  20.0
[PATTERNS]
 PAT1   1.0  1.2  0.8
[REPORT]
 STATUS  YES
[OPTIONS]
 Units    LPS
 Headloss H-W
[END]
"""
    path = tmp_path / "with_extras.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    assert net.num_nodes == 2
    assert net.num_edges == 1


def test_no_options_section_assumes_lps_default(tmp_path: Path) -> None:
    inp = """[JUNCTIONS]
 J1  0  5
[RESERVOIRS]
 R1  100
[PIPES]
 P1  R1  J1  100  150  130  0  OPEN
[END]
"""
    path = tmp_path / "no_opts.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # Junction declared 5 L/s = 0.005 m^3/s.
    assert float(net.demands[0].item()) == pytest.approx(0.005, abs=1e-9)
