"""Sprint 20 — EPANET ``[OPTIONS] Viscosity`` parsing (parser-only).

Sprint 19 added fallback support for the two-word ``[OPTIONS]
Specific Gravity`` directive and propagated fluid density to the two
places where it matters (PRV pressure-unit conversion for true
pressure units, POWER pump surrogate effective density). Sprint 20
adds fallback support for the single-word ``[OPTIONS] Viscosity``
directive as a **parser-only** compatibility feature.

Viscosity is a kinematic-viscosity ratio relative to water at 20 °C.
In EPANET it only matters for Darcy-Weisbach / Reynolds-based
friction models. The current dPHM core uses Hazen-Williams head loss,
which carries no viscosity term in its residual, so the directive
must be parsed and validated but must **not** change any hydraulic
output. These tests pin:

* :func:`resolve_viscosity` defaults, parsing, and validation surface;
* fallback-parser tolerance of case / whitespace variations on the
  ``Viscosity`` option key;
* fail-fast rejection of zero, negative, non-numeric, NaN, and Inf
  viscosity values (even though the value is not used);
* hydraulic invariance under Hazen-Williams across SI and US flow
  unit families:

  - junction demands,
  - reservoir / tank fixed heads,
  - pipe geometry (length, diameter, c_factor),
  - HEAD pump curve coefficients,
  - POWER pump surrogate coefficients,
  - PRV pressure conversion (including with Specific Gravity present),
  - TCV effective resistance,
  - Newton-solve heads and flows on a stable fixture;

* orthogonality to Sprint 18 (Demand Multiplier) and Sprint 19
  (Specific Gravity) — viscosity must not perturb either axis;
* compatibility with the Sprint 11 / 16 / 17 / 18 shipped fixtures;
* optional WNTR parity, which is documented as ambiguous for the
  Viscosity directive and not enforced.

None of the non-WNTR tests import WNTR or any external EPANET runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    load_network_from_inp,
    newton_solve,
)
from aquaoptima.dphm.inp_io import (
    resolve_demand_multiplier,
    resolve_specific_gravity,
    resolve_viscosity,
)


_FT_TO_M = 0.3048
_GPM_TO_M3S = 0.003785411784 / 60.0

_RHO = 1000.0
_G = 9.80665
_PA_PER_M_WATER = _RHO * _G
_PSI_TO_PA = 6894.757293168


_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "examples"
)
_LOOP_SI = _FIXTURE_DIR / "epanet_reference_loop.inp"
_LOOP_GPM = _FIXTURE_DIR / "epanet_reference_loop_gpm.inp"
_LOOP_GPM_DM = (
    _FIXTURE_DIR / "epanet_reference_loop_gpm_demand_multiplier.inp"
)
_PRV_GPM_PSI = _FIXTURE_DIR / "epanet_reference_prv_gpm_psi.inp"
_POWER_PUMP_SI = _FIXTURE_DIR / "epanet_reference_power_pump.inp"
_HEAD_PUMP_SI = _FIXTURE_DIR / "epanet_reference_pump.inp"


# ---------------------------------------------------------------------------
# resolve_viscosity — defaults and validation
# ---------------------------------------------------------------------------


def test_resolve_viscosity_default_is_one_when_missing() -> None:
    assert resolve_viscosity({}) == 1.0


def test_resolve_viscosity_default_is_one_when_empty_string() -> None:
    assert resolve_viscosity({"VISCOSITY": ""}) == 1.0


@pytest.mark.parametrize("value", [0.5, 0.85, 1.0, 1.2, 2.0, 10.0])
def test_resolve_viscosity_parses_valid_positive(value: float) -> None:
    assert resolve_viscosity({"VISCOSITY": str(value)}) == pytest.approx(value)


def test_resolve_viscosity_rejects_zero() -> None:
    with pytest.raises(ValueError, match="must be strictly positive"):
        resolve_viscosity({"VISCOSITY": "0"})
    with pytest.raises(ValueError, match="must be strictly positive"):
        resolve_viscosity({"VISCOSITY": "0.0"})


def test_resolve_viscosity_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must be strictly positive"):
        resolve_viscosity({"VISCOSITY": "-1.0"})


def test_resolve_viscosity_rejects_nan() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        resolve_viscosity({"VISCOSITY": "nan"})


def test_resolve_viscosity_rejects_inf() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        resolve_viscosity({"VISCOSITY": "inf"})
    with pytest.raises(ValueError, match="must be finite"):
        resolve_viscosity({"VISCOSITY": "-inf"})


def test_resolve_viscosity_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="is not numeric"):
        resolve_viscosity({"VISCOSITY": "thick"})


# ---------------------------------------------------------------------------
# Fallback parser — case / whitespace tolerance for Viscosity key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directive_row",
    [
        " Viscosity 1.0\n",         # canonical
        " VISCOSITY 0.8\n",         # all-upper
        " viscosity 2.0\n",         # all-lower
        " Viscosity    1.5\n",      # extra inter-token whitespace
        "   viscosity   0.85\n",    # leading + extra whitespace
        " ViScOsItY 1.2\n",         # mixed case
    ],
)
def test_fallback_viscosity_key_is_case_and_whitespace_tolerant(
    tmp_path: Path, directive_row: str
) -> None:
    """``Viscosity`` is a one-word key; the standard ``_parse_options``
    single-token branch handles it. We confirm that every case /
    whitespace variation parses cleanly by loading a minimal fixture
    and asserting the network loads without raising.
    """
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0   10.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   R1   J1   100   150   130   0   OPEN\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{directive_row}"
        "[END]\n"
    )
    path = tmp_path / "viscosity_case_whitespace.inp"
    path.write_text(inp)
    # Must not raise.
    net = load_network_from_inp(path, parser="fallback")
    # Demand survives the parse unchanged (10 L/s -> 0.010 m^3/s,
    # less mass-rebalance share onto the single reservoir).
    assert float(net.demands[0].item()) == pytest.approx(0.010, abs=1e-9)


# ---------------------------------------------------------------------------
# Fallback parser — invalid Viscosity values rejected by the parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, error_match",
    [
        ("0", "must be strictly positive"),
        ("0.0", "must be strictly positive"),
        ("-1.5", "must be strictly positive"),
        ("nan", "must be finite"),
        ("inf", "must be finite"),
        ("-inf", "must be finite"),
        ("oil", "is not numeric"),
    ],
)
def test_fallback_rejects_invalid_viscosity(
    tmp_path: Path, value: str, error_match: str
) -> None:
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0   10.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   R1   J1   100   150   130   0   OPEN\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f" Viscosity   {value}\n"
        "[END]\n"
    )
    path = (
        tmp_path
        / f"bad_visc_{value.replace('.', '_').replace('-', 'neg_')}.inp"
    )
    path.write_text(inp)
    with pytest.raises(ValueError, match=error_match):
        load_network_from_inp(path, parser="fallback")


# ---------------------------------------------------------------------------
# Hydraulic invariance — LPS loop fixture
# ---------------------------------------------------------------------------


def _write_lps_loop(tmp_path: Path, *, viscosity: float | None) -> Path:
    visc_line = (
        f" Viscosity   {viscosity}\n" if viscosity is not None else ""
    )
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0    10.0\n"
        " J2   0.0    15.0\n"
        " J3   0.0    12.0\n"
        " J4   0.0     8.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   R1   J1   300.0   250.0   130.0   0.0   OPEN\n"
        " P2   J1   J2   250.0   200.0   130.0   0.0   OPEN\n"
        " P3   J2   J3   220.0   150.0   130.0   0.0   OPEN\n"
        " P4   J3   J4   200.0   150.0   130.0   0.0   OPEN\n"
        " P5   J1   J4   280.0   150.0   130.0   0.0   OPEN\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{visc_line}"
        "[END]\n"
    )
    path = tmp_path / f"loop_lps_visc_{viscosity}.inp"
    path.write_text(inp)
    return path


def _assert_network_field_identical(net_a, net_b, attr: str) -> None:
    a = getattr(net_a, attr).double()
    b = getattr(net_b, attr).double()
    assert torch.allclose(a, b, atol=0.0), (
        f"{attr} differs between viscosity-present and viscosity-absent "
        f"networks"
    )


@pytest.mark.parametrize("viscosity", [0.5, 1.0, 1.2, 2.0])
def test_lps_loop_demands_invariant_under_viscosity(
    tmp_path: Path, viscosity: float
) -> None:
    net_none = load_network_from_inp(
        _write_lps_loop(tmp_path, viscosity=None), parser="fallback"
    )
    net_visc = load_network_from_inp(
        _write_lps_loop(tmp_path, viscosity=viscosity), parser="fallback"
    )
    _assert_network_field_identical(net_none, net_visc, "demands")


@pytest.mark.parametrize("viscosity", [0.5, 1.0, 1.2, 2.0])
def test_lps_loop_fixed_heads_invariant_under_viscosity(
    tmp_path: Path, viscosity: float
) -> None:
    net_none = load_network_from_inp(
        _write_lps_loop(tmp_path, viscosity=None), parser="fallback"
    )
    net_visc = load_network_from_inp(
        _write_lps_loop(tmp_path, viscosity=viscosity), parser="fallback"
    )
    _assert_network_field_identical(net_none, net_visc, "fixed_head_values")
    assert (
        net_none.fixed_head_mask.tolist()
        == net_visc.fixed_head_mask.tolist()
    )


@pytest.mark.parametrize("viscosity", [0.5, 1.0, 1.2, 2.0])
def test_lps_loop_geometry_invariant_under_viscosity(
    tmp_path: Path, viscosity: float
) -> None:
    net_none = load_network_from_inp(
        _write_lps_loop(tmp_path, viscosity=None), parser="fallback"
    )
    net_visc = load_network_from_inp(
        _write_lps_loop(tmp_path, viscosity=viscosity), parser="fallback"
    )
    for attr in ("lengths", "diameters", "c_factors"):
        _assert_network_field_identical(net_none, net_visc, attr)


def test_lps_loop_newton_solve_invariant_under_viscosity(
    tmp_path: Path,
) -> None:
    net_none = load_network_from_inp(
        _write_lps_loop(tmp_path, viscosity=None), parser="fallback"
    )
    net_visc = load_network_from_inp(
        _write_lps_loop(tmp_path, viscosity=2.0), parser="fallback"
    )
    res_none = newton_solve(
        net_none, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    res_visc = newton_solve(
        net_visc, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert res_none.converged and res_visc.converged
    assert torch.allclose(
        res_none.heads.double(), res_visc.heads.double(), atol=1e-9
    )
    assert torch.allclose(
        res_none.flows.double(), res_visc.flows.double(), atol=1e-12
    )


# ---------------------------------------------------------------------------
# Hydraulic invariance — GPM loop fixture (US-customary)
# ---------------------------------------------------------------------------


def _write_gpm_loop(tmp_path: Path, *, viscosity: float | None) -> Path:
    visc_line = (
        f" Viscosity   {viscosity}\n" if viscosity is not None else ""
    )
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0    100.0\n"
        " J2   0.0    150.0\n"
        " J3   0.0    120.0\n"
        " J4   0.0     80.0\n"
        "[RESERVOIRS]\n"
        " R1   328.0\n"
        "[PIPES]\n"
        " P1   R1   J1   984.0   10.0   130.0   0.0   OPEN\n"
        " P2   J1   J2   820.0    8.0   130.0   0.0   OPEN\n"
        " P3   J2   J3   720.0    6.0   130.0   0.0   OPEN\n"
        " P4   J3   J4   656.0    6.0   130.0   0.0   OPEN\n"
        " P5   J1   J4   919.0    6.0   130.0   0.0   OPEN\n"
        "[OPTIONS]\n"
        " Units      GPM\n"
        " Headloss   H-W\n"
        f"{visc_line}"
        "[END]\n"
    )
    path = tmp_path / f"loop_gpm_visc_{viscosity}.inp"
    path.write_text(inp)
    return path


@pytest.mark.parametrize("viscosity", [0.5, 1.0, 2.0])
def test_gpm_loop_dimensions_and_demands_invariant_under_viscosity(
    tmp_path: Path, viscosity: float
) -> None:
    """All converted SI dimensions / demands match between a GPM loop
    that declares Viscosity and the same loop without it.
    """
    net_none = load_network_from_inp(
        _write_gpm_loop(tmp_path, viscosity=None), parser="fallback"
    )
    net_visc = load_network_from_inp(
        _write_gpm_loop(tmp_path, viscosity=viscosity), parser="fallback"
    )
    for attr in (
        "demands",
        "fixed_head_values",
        "lengths",
        "diameters",
        "c_factors",
    ):
        _assert_network_field_identical(net_none, net_visc, attr)


# ---------------------------------------------------------------------------
# HEAD pump coefficients unaffected by viscosity
# ---------------------------------------------------------------------------


def _write_head_pump_fixture(
    tmp_path: Path, *, viscosity: float | None
) -> Path:
    visc_line = (
        f" Viscosity   {viscosity}\n" if viscosity is not None else ""
    )
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0    0.0\n"
        " J2   0.0   10.0\n"
        "[RESERVOIRS]\n"
        " R1   5.0\n"
        "[PIPES]\n"
        " P1   J1   J2   200   150   130   0   OPEN\n"
        "[PUMPS]\n"
        " PU1  R1   J1   HEAD   PUMPCURVE1\n"
        "[CURVES]\n"
        " PUMPCURVE1   0.0    45.0\n"
        " PUMPCURVE1  10.0    44.0\n"
        " PUMPCURVE1  20.0    41.0\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{visc_line}"
        "[END]\n"
    )
    path = tmp_path / f"head_pump_visc_{viscosity}.inp"
    path.write_text(inp)
    return path


@pytest.mark.parametrize("viscosity", [0.5, 1.0, 2.0])
def test_head_pump_coefficients_invariant_under_viscosity(
    tmp_path: Path, viscosity: float
) -> None:
    """HEAD curves are head-vs-flow tables — already metres of head —
    so viscosity must not touch the fitted coefficients.
    """
    net_none = load_network_from_inp(
        _write_head_pump_fixture(tmp_path, viscosity=None),
        parser="fallback",
    )
    net_visc = load_network_from_inp(
        _write_head_pump_fixture(tmp_path, viscosity=viscosity),
        parser="fallback",
    )
    assert torch.allclose(
        net_none.pump_coeffs.double(),
        net_visc.pump_coeffs.double(),
        atol=1e-12,
    )


# ---------------------------------------------------------------------------
# POWER pump coefficients unaffected by viscosity
# ---------------------------------------------------------------------------


def _write_power_pump_fixture(
    tmp_path: Path, *, viscosity: float | None
) -> Path:
    visc_line = (
        f" Viscosity   {viscosity}\n" if viscosity is not None else ""
    )
    inp = (
        "[JUNCTIONS]\n"
        " J1  0.0    0.0\n"
        " J2  0.0   15.0\n"
        "[RESERVOIRS]\n"
        " R1  5.0\n"
        "[PIPES]\n"
        " P1  J1  J2  200  150  130  0  OPEN\n"
        "[PUMPS]\n"
        " PU1  R1  J1  POWER  7.5\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{visc_line}"
        "[END]\n"
    )
    path = tmp_path / f"power_pump_visc_{viscosity}.inp"
    path.write_text(inp)
    return path


@pytest.mark.parametrize("viscosity", [0.5, 1.0, 2.0])
def test_power_pump_coefficients_invariant_under_viscosity(
    tmp_path: Path, viscosity: float
) -> None:
    """The POWER pump surrogate depends on power, nominal-flow anchor,
    shut-off multiplier, and specific gravity — none of which is a
    function of viscosity. Viscosity must not perturb a0/a1/a2.
    """
    net_none = load_network_from_inp(
        _write_power_pump_fixture(tmp_path, viscosity=None),
        parser="fallback",
    )
    net_visc = load_network_from_inp(
        _write_power_pump_fixture(tmp_path, viscosity=viscosity),
        parser="fallback",
    )
    assert torch.allclose(
        net_none.pump_coeffs.double(),
        net_visc.pump_coeffs.double(),
        atol=1e-12,
    )


# ---------------------------------------------------------------------------
# PRV pressure conversion unaffected by viscosity
# ---------------------------------------------------------------------------


def _write_prv_psi_fixture(
    tmp_path: Path,
    *,
    viscosity: float | None,
    specific_gravity: float | None,
) -> Path:
    visc_line = (
        f" Viscosity   {viscosity}\n" if viscosity is not None else ""
    )
    sg_line = (
        f" Specific Gravity   {specific_gravity}\n"
        if specific_gravity is not None
        else ""
    )
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0   0.0\n"
        " J3   0.0   2.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   R1   J1   2000   80   130   0   OPEN\n"
        " P2   J2   J3    200   80   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   J1   J2   80   PRV   30.0   0\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        " Pressure   PSI\n"
        f"{sg_line}"
        f"{visc_line}"
        "[END]\n"
    )
    path = (
        tmp_path
        / f"prv_psi_visc_{viscosity}_sg_{specific_gravity}.inp"
    )
    path.write_text(inp)
    return path


@pytest.mark.parametrize("viscosity", [0.5, 1.0, 2.0])
def test_prv_psi_unaffected_by_viscosity(
    tmp_path: Path, viscosity: float
) -> None:
    """PRV PSI conversion depends on pressure-unit table and SG; it
    must not depend on viscosity.
    """
    net_none = load_network_from_inp(
        _write_prv_psi_fixture(
            tmp_path, viscosity=None, specific_gravity=None
        ),
        parser="fallback",
    )
    net_visc = load_network_from_inp(
        _write_prv_psi_fixture(
            tmp_path, viscosity=viscosity, specific_gravity=None
        ),
        parser="fallback",
    )
    assert torch.allclose(
        net_none.fixed_head_values.double(),
        net_visc.fixed_head_values.double(),
        atol=1e-9,
    )


@pytest.mark.parametrize("viscosity", [0.5, 1.0, 2.0])
def test_prv_psi_with_sg_unaffected_by_viscosity(
    tmp_path: Path, viscosity: float
) -> None:
    """PRV PSI + Specific Gravity scaling stays orthogonal to
    viscosity: the same SG produces the same fluid head regardless of
    the declared viscosity.
    """
    net_no_visc = load_network_from_inp(
        _write_prv_psi_fixture(
            tmp_path, viscosity=None, specific_gravity=2.0
        ),
        parser="fallback",
    )
    net_with_visc = load_network_from_inp(
        _write_prv_psi_fixture(
            tmp_path, viscosity=viscosity, specific_gravity=2.0
        ),
        parser="fallback",
    )
    expected = 30.0 * (_PSI_TO_PA / _PA_PER_M_WATER) / 2.0
    assert float(net_no_visc.fixed_head_values[1].item()) == pytest.approx(
        expected, abs=1e-5
    )
    assert float(net_with_visc.fixed_head_values[1].item()) == pytest.approx(
        expected, abs=1e-5
    )


# ---------------------------------------------------------------------------
# TCV effective resistance unaffected by viscosity
# ---------------------------------------------------------------------------


def _write_tcv_fixture(
    tmp_path: Path, *, viscosity: float | None
) -> Path:
    visc_line = (
        f" Viscosity   {viscosity}\n" if viscosity is not None else ""
    )
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0  15.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   J1   J2   200   150   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   R1   J1   150   TCV   2.5   0\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{visc_line}"
        "[END]\n"
    )
    path = tmp_path / f"tcv_visc_{viscosity}.inp"
    path.write_text(inp)
    return path


@pytest.mark.parametrize("viscosity", [0.5, 1.0, 2.0])
def test_tcv_surrogate_invariant_under_viscosity(
    tmp_path: Path, viscosity: float
) -> None:
    """The TCV resistance surrogate depends on K, K_minor, diameter,
    Q_nom and the chosen Hazen-Williams C — none is a function of
    viscosity.
    """
    net_none = load_network_from_inp(
        _write_tcv_fixture(tmp_path, viscosity=None),
        parser="fallback",
    )
    net_visc = load_network_from_inp(
        _write_tcv_fixture(tmp_path, viscosity=viscosity),
        parser="fallback",
    )
    for attr in ("lengths", "diameters", "c_factors"):
        _assert_network_field_identical(net_none, net_visc, attr)


# ---------------------------------------------------------------------------
# Orthogonality with Sprint 18 Demand Multiplier and Sprint 19 SG
# ---------------------------------------------------------------------------


def test_demand_multiplier_independent_of_viscosity(tmp_path: Path) -> None:
    """Demand Multiplier scales junction demand; viscosity must not
    perturb the multiplied demand.
    """
    def write_loop(dm: float, visc: float | None) -> Path:
        visc_line = (
            f" Viscosity   {visc}\n" if visc is not None else ""
        )
        inp = (
            "[JUNCTIONS]\n"
            " J1  0.0   10.0\n"
            " J2  0.0   15.0\n"
            "[RESERVOIRS]\n"
            " R1  50.0\n"
            "[PIPES]\n"
            " P1  R1  J1  500  150  130  0  OPEN\n"
            " P2  J1  J2  300  150  130  0  OPEN\n"
            "[OPTIONS]\n"
            " Units      LPS\n"
            " Headloss   H-W\n"
            f" Demand Multiplier   {dm}\n"
            f"{visc_line}"
            "[END]\n"
        )
        p = tmp_path / f"loop_dm_{dm}_visc_{visc}.inp"
        p.write_text(inp)
        return p

    net_dm2_no_visc = load_network_from_inp(
        write_loop(2.0, None), parser="fallback"
    )
    net_dm2_visc = load_network_from_inp(
        write_loop(2.0, 2.0), parser="fallback"
    )
    assert torch.allclose(
        net_dm2_no_visc.demands.double(),
        net_dm2_visc.demands.double(),
        atol=1e-12,
    )
    # Sprint 18 multiplier still applies: 10 LPS * 1e-3 * 2.0 = 0.020.
    assert float(net_dm2_visc.demands[0].item()) == pytest.approx(
        0.020, abs=1e-7
    )


def test_specific_gravity_independent_of_viscosity(tmp_path: Path) -> None:
    """SG-scaled PRV PSI head must not depend on viscosity. SG is the
    only density-related scaling the current importer applies.
    """
    net_sg2_no_visc = load_network_from_inp(
        _write_prv_psi_fixture(
            tmp_path, viscosity=None, specific_gravity=2.0
        ),
        parser="fallback",
    )
    net_sg2_visc = load_network_from_inp(
        _write_prv_psi_fixture(
            tmp_path, viscosity=2.0, specific_gravity=2.0
        ),
        parser="fallback",
    )
    assert torch.allclose(
        net_sg2_no_visc.fixed_head_values.double(),
        net_sg2_visc.fixed_head_values.double(),
        atol=1e-9,
    )


def test_resolve_helpers_do_not_collide_on_viscosity_key() -> None:
    """A single options map containing Demand Multiplier, Specific
    Gravity, AND Viscosity must be parsed correctly by all three
    resolvers, each returning its own value.
    """
    opts = {
        "DEMAND MULTIPLIER": "1.5",
        "SPECIFIC GRAVITY": "0.85",
        "VISCOSITY": "1.2",
    }
    assert resolve_demand_multiplier(opts) == pytest.approx(1.5)
    assert resolve_specific_gravity(opts) == pytest.approx(0.85)
    assert resolve_viscosity(opts) == pytest.approx(1.2)


# ---------------------------------------------------------------------------
# Existing fixtures unchanged by Sprint 20
# ---------------------------------------------------------------------------


def test_existing_si_loop_fixture_unaffected_by_sprint20() -> None:
    """The Sprint 11 SI loop has no Viscosity directive; Sprint 20
    must not change demand or fixed-head values.
    """
    net = load_network_from_inp(_LOOP_SI, parser="fallback")
    expected_positive = torch.tensor([0.010, 0.015, 0.012, 0.008])
    assert torch.allclose(
        net.demands[:4].double(), expected_positive.double(), atol=1e-9
    )


def test_existing_gpm_loop_fixture_unaffected_by_sprint20() -> None:
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    junction_demands = torch.tensor(
        [100.0, 150.0, 120.0, 80.0]
    ) * _GPM_TO_M3S
    assert torch.allclose(
        net.demands[:4].double(), junction_demands.double(), atol=1e-8
    )


def test_existing_gpm_dm_fixture_unaffected_by_sprint20() -> None:
    """Sprint 18 fixture: GPM loop with Demand Multiplier 2.0, no
    Viscosity directive. Sprint 20 must not perturb demands.
    """
    net = load_network_from_inp(_LOOP_GPM_DM, parser="fallback")
    junction_demands = (
        torch.tensor([100.0, 150.0, 120.0, 80.0]) * _GPM_TO_M3S * 2.0
    )
    assert torch.allclose(
        net.demands[:4].double(), junction_demands.double(), atol=1e-7
    )


def test_existing_gpm_psi_prv_fixture_unaffected_by_sprint20() -> None:
    """Sprint 17 PRV fixture: GPM + PSI, no Viscosity, no SG. The
    pinned head value must match the Sprint 17 expected value.
    """
    net = load_network_from_inp(_PRV_GPM_PSI, parser="fallback")
    expected_head = 30.0 * (_PSI_TO_PA / _PA_PER_M_WATER)
    assert float(net.fixed_head_values[1].item()) == pytest.approx(
        expected_head, abs=1e-4
    )


def test_existing_power_pump_fixture_unaffected_by_sprint20() -> None:
    """The Sprint 14 POWER pump fixture has no Viscosity directive.
    Loaded a0 must remain positive and unchanged from Sprint 14/19.
    """
    net = load_network_from_inp(_POWER_PUMP_SI, parser="fallback")
    assert any(net.pump_mask.tolist())
    pump_idx = next(i for i, m in enumerate(net.pump_mask.tolist()) if m)
    assert float(net.pump_coeffs[pump_idx][0].item()) > 0.0


def test_existing_head_pump_fixture_unaffected_by_sprint20() -> None:
    """The Sprint 12 HEAD pump fixture has no Viscosity directive.
    Fitted coefficients must remain those Sprint 12 documented.
    """
    net = load_network_from_inp(_HEAD_PUMP_SI, parser="fallback")
    pump_idx = next(i for i, m in enumerate(net.pump_mask.tolist()) if m)
    a0 = float(net.pump_coeffs[pump_idx][0].item())
    a2 = float(net.pump_coeffs[pump_idx][2].item())
    # The Sprint 12 fixture lies on H = 45 - 800 * Q^2.
    assert a0 == pytest.approx(45.0, abs=1e-5)
    assert a2 == pytest.approx(-800.0, abs=1e-2)


# ---------------------------------------------------------------------------
# WNTR optional parity (documented as ambiguous for Viscosity)
# ---------------------------------------------------------------------------


def test_wntr_existing_si_loop_fixture_parity_unaffected_by_sprint20() -> None:
    """The Sprint 11 SI loop has no Viscosity directive; both parser
    back-ends still load identical demands.
    """
    pytest.importorskip("wntr")
    net_fb = load_network_from_inp(_LOOP_SI, parser="fallback")
    net_wn = load_network_from_inp(_LOOP_SI, parser="wntr")
    fb_demand = sorted(net_fb.demands.tolist())
    wn_demand = sorted(net_wn.demands.tolist())
    assert fb_demand == pytest.approx(wn_demand, abs=1e-7)


def test_wntr_fallback_parity_with_viscosity_directive(
    tmp_path: Path,
) -> None:
    """When an LPS loop adds a Viscosity directive, the fallback parser
    accepts it (Sprint 20) and produces a network whose demand /
    fixed-head / geometry values match the WNTR back-end (which
    ignores or stores viscosity internally, but does not propagate it
    to the Hazen-Williams residual either).

    The Viscosity directive is documented as a WNTR ambiguity: WNTR
    may or may not parse it depending on its release. Sprint 20 does
    not try to assert WNTR's internal handling; the test guarantees
    only that adding the directive does not break the back-end and
    that demand totals agree.
    """
    pytest.importorskip("wntr")
    path = _write_lps_loop(tmp_path, viscosity=1.2)
    net_fb = load_network_from_inp(path, parser="fallback")
    net_wn = load_network_from_inp(path, parser="wntr")
    fb_demand = sorted(net_fb.demands.tolist())
    wn_demand = sorted(net_wn.demands.tolist())
    assert fb_demand == pytest.approx(wn_demand, abs=1e-7)
