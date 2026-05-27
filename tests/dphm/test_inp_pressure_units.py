"""Sprint 17 — EPANET ``[OPTIONS] Pressure`` parsing and pressure unit manifest.

Sprint 16 captured every per-flow-unit conversion (length, diameter,
head/elevation, demand) in a single :class:`EpanetUnitSystem`
manifest. Sprint 17 adds an orthogonal axis: the EPANET
``[OPTIONS] Pressure`` directive, which selects the pressure-display
unit used for pressure-related fields such as PRV settings.

These tests pin the conversion constants for every supported
pressure unit, exercise the case-insensitive lookup surface, and
confirm that the fallback parser:

* Uses the explicit pressure-unit conversion for PRV settings when
  ``[OPTIONS] Pressure`` is present.
* Preserves Sprint 16 behaviour when ``[OPTIONS] Pressure`` is
  absent (PRV settings follow the flow-unit family's head
  conversion).
* Does not apply the pressure-unit conversion to TCV settings or
  minor-loss coefficients, which remain dimensionless.

None of these tests import WNTR or any external EPANET runtime.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from aquaoptima.dphm import load_network_from_inp
from aquaoptima.dphm.inp_io import (
    EpanetPressureUnit,
    SUPPORTED_PRESSURE_UNITS,
    resolve_pressure_unit,
)


_RHO = 1000.0
_G = 9.80665
_PA_PER_M_WATER = _RHO * _G  # 9806.65 Pa per metre of water head
_PSI_TO_PA = 6894.757293168    # exact (NIST, international foot-pound-second)
_KPA_TO_PA = 1000.0
_BAR_TO_PA = 100_000.0
_FT_TO_M = 0.3048


# ---------------------------------------------------------------------------
# Pressure unit manifest constants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit_name, pressure_to_head_m",
    [
        ("METERS", 1.0),
        ("M", 1.0),
        ("FEET", _FT_TO_M),
        ("FT", _FT_TO_M),
        ("KPA", _KPA_TO_PA / _PA_PER_M_WATER),
        ("PSI", _PSI_TO_PA / _PA_PER_M_WATER),
        ("BAR", _BAR_TO_PA / _PA_PER_M_WATER),
    ],
)
def test_pressure_unit_manifest_constants_match_documented_values(
    unit_name: str, pressure_to_head_m: float
) -> None:
    pu = resolve_pressure_unit(unit_name)
    assert isinstance(pu, EpanetPressureUnit)
    assert pu.name == unit_name
    assert pu.pressure_to_head_m == pytest.approx(
        pressure_to_head_m, rel=1e-12, abs=1e-18
    )


def test_supported_pressure_units_lists_all_units() -> None:
    assert set(SUPPORTED_PRESSURE_UNITS) == {
        "PSI", "KPA", "METERS", "M", "FEET", "FT", "BAR",
    }


def test_resolve_pressure_unit_is_case_insensitive() -> None:
    upper = resolve_pressure_unit("PSI")
    lower = resolve_pressure_unit("psi")
    mixed = resolve_pressure_unit("Psi")
    assert upper.name == lower.name == mixed.name == "PSI"
    assert upper.pressure_to_head_m == lower.pressure_to_head_m
    assert upper.pressure_to_head_m == mixed.pressure_to_head_m


def test_resolve_pressure_unit_rejects_unknown_token() -> None:
    with pytest.raises(ValueError, match="unknown EPANET pressure unit"):
        resolve_pressure_unit("PASCAL")


def test_resolve_pressure_unit_rejects_empty_token() -> None:
    with pytest.raises(ValueError, match="unknown EPANET pressure unit"):
        resolve_pressure_unit("")


def test_psi_to_metres_round_number() -> None:
    """Sanity check: ~0.703 m of water head per psi."""
    psi = resolve_pressure_unit("PSI").pressure_to_head_m
    assert psi == pytest.approx(0.7030695796466831, rel=1e-9)


def test_bar_to_metres_round_number() -> None:
    """Sanity check: 1 bar ≈ 10.197 m of water head."""
    bar = resolve_pressure_unit("BAR").pressure_to_head_m
    assert bar == pytest.approx(10.197162129779281, rel=1e-9)


def test_kpa_to_metres_round_number() -> None:
    """Sanity check: 1 kPa ≈ 0.10197 m of water head."""
    kpa = resolve_pressure_unit("KPA").pressure_to_head_m
    assert kpa == pytest.approx(0.10197162129779281, rel=1e-9)


def test_metres_pressure_unit_is_unity() -> None:
    assert resolve_pressure_unit("METERS").pressure_to_head_m == 1.0
    assert resolve_pressure_unit("M").pressure_to_head_m == 1.0


def test_feet_pressure_unit_matches_ft_to_m() -> None:
    assert resolve_pressure_unit("FEET").pressure_to_head_m == _FT_TO_M
    assert resolve_pressure_unit("FT").pressure_to_head_m == _FT_TO_M


# ---------------------------------------------------------------------------
# Fallback parser — explicit [OPTIONS] Pressure handling
# ---------------------------------------------------------------------------


_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "examples"
)
_PRV_GPM_PSI = _FIXTURE_DIR / "epanet_reference_prv_gpm_psi.inp"


def test_prv_gpm_psi_fixture_is_shipped() -> None:
    assert _PRV_GPM_PSI.is_file(), (
        f"missing shipped Sprint 17 fixture at {_PRV_GPM_PSI}"
    )


def test_prv_gpm_psi_fixture_pins_downstream_via_psi_conversion() -> None:
    """The shipped GPM + Pressure PSI fixture pins its PRV downstream
    node via the psi -> m conversion (~0.703 m/psi), NOT via the
    flow-unit family's feet -> m conversion (0.3048 m/ft).
    """
    net = load_network_from_inp(_PRV_GPM_PSI, parser="fallback")
    # Pressure setting in the fixture is 30 psi; downstream elev is 0.
    expected_head = 30.0 * (_PSI_TO_PA / _PA_PER_M_WATER)
    # If the parser fell back to the flow-unit head conversion, the
    # value would be 30 * 0.3048 = 9.144 m. Confirm we got the psi
    # conversion (~21.09 m), not the ft conversion.
    assert expected_head == pytest.approx(21.09208739, abs=1e-4)
    # J2 is the second junction (index 1) by the fixture's section ordering.
    assert bool(net.fixed_head_mask[1].item())
    actual_head = float(net.fixed_head_values[1].item())
    assert actual_head == pytest.approx(expected_head, abs=1e-4)
    # Affirmatively reject the wrong (feet) conversion.
    assert actual_head != pytest.approx(30.0 * _FT_TO_M, abs=1e-3)


def test_prv_gpm_psi_fixture_solves_with_analytic_newton() -> None:
    from aquaoptima.dphm import newton_solve

    net = load_network_from_inp(_PRV_GPM_PSI, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-7


# ---------------------------------------------------------------------------
# Default no-Pressure behavior must remain Sprint 16-compatible
# ---------------------------------------------------------------------------


def _write_prv_lps_fixture(tmp_path: Path, *, with_pressure: str | None) -> Path:
    """Write a tiny LPS-PRV fixture with optional Pressure directive."""
    pressure_line = f" Pressure   {with_pressure}\n" if with_pressure else ""
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0   0.0\n"
        " J3   0.0   2.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   R1   J1   2000   80   130   0   OPEN\n"
        " P2   J2   J3    200   80   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   J1   J2   80   PRV   20.0   0\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{pressure_line}"
        "[END]\n"
    )
    path = tmp_path / "prv_lps_test.inp"
    path.write_text(inp)
    return path


def test_default_no_pressure_directive_preserves_sprint16_prv(
    tmp_path: Path,
) -> None:
    """When [OPTIONS] Pressure is absent, PRV setting follows the
    flow-unit family's head conversion (Sprint 16 contract).
    """
    path = _write_prv_lps_fixture(tmp_path, with_pressure=None)
    net = load_network_from_inp(path, parser="fallback")
    # SI flow units => setting in metres; PRV downstream pinned to 20 m.
    assert bool(net.fixed_head_mask[1].item())
    assert float(net.fixed_head_values[1].item()) == pytest.approx(20.0, abs=1e-9)


def test_default_no_pressure_directive_preserves_us_prv_feet(
    tmp_path: Path,
) -> None:
    """When [OPTIONS] Pressure is absent under US flow units, the
    PRV setting is interpreted as feet of head (Sprint 16 contract).
    """
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0   0.0\n"
        " J3   0.0  50.0\n"
        "[RESERVOIRS]\n"
        " R1   200.0\n"
        "[PIPES]\n"
        " P1   R1   J1   2000   3   130   0   OPEN\n"
        " P2   J2   J3    200   3   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   J1   J2     3   PRV   80.0   0\n"
        "[OPTIONS]\n"
        " Units    GPM\n"
        " Headloss H-W\n"
        "[END]\n"
    )
    path = tmp_path / "prv_gpm_feet.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # 80 ft -> 80 * 0.3048 = 24.384 m (Sprint 16 default behaviour).
    assert float(net.fixed_head_values[1].item()) == pytest.approx(
        80.0 * _FT_TO_M, abs=1e-4
    )


# ---------------------------------------------------------------------------
# Pressure directive overrides default conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pressure_directive, setting_value, expected_head_m",
    [
        ("METERS", 20.0, 20.0),
        ("M", 20.0, 20.0),
        ("FEET", 20.0, 20.0 * _FT_TO_M),
        ("FT", 20.0, 20.0 * _FT_TO_M),
        ("KPA", 200.0, 200.0 * _KPA_TO_PA / _PA_PER_M_WATER),
        ("BAR", 2.0, 2.0 * _BAR_TO_PA / _PA_PER_M_WATER),
        ("PSI", 30.0, 30.0 * _PSI_TO_PA / _PA_PER_M_WATER),
    ],
)
def test_explicit_pressure_directive_overrides_prv_conversion(
    tmp_path: Path,
    pressure_directive: str,
    setting_value: float,
    expected_head_m: float,
) -> None:
    """When [OPTIONS] Pressure is present, PRV setting conversion uses
    the explicit pressure unit, not the flow-unit family's head_to_m.
    """
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
        f" V1   J1   J2   80   PRV   {setting_value}   0\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f" Pressure   {pressure_directive}\n"
        "[END]\n"
    )
    path = tmp_path / f"prv_pressure_{pressure_directive.lower()}.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    assert bool(net.fixed_head_mask[1].item())
    assert float(net.fixed_head_values[1].item()) == pytest.approx(
        expected_head_m, abs=1e-6
    )


def test_pressure_directive_is_case_insensitive(tmp_path: Path) -> None:
    """``[OPTIONS] Pressure psi`` parses the same as ``PSI``."""
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
        " Pressure   psi\n"
        "[END]\n"
    )
    path = tmp_path / "prv_pressure_lowercase.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    expected = 30.0 * _PSI_TO_PA / _PA_PER_M_WATER
    assert float(net.fixed_head_values[1].item()) == pytest.approx(
        expected, abs=1e-6
    )


def test_pressure_directive_unknown_token_raises(tmp_path: Path) -> None:
    inp = (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   R1   J1   100   80   130   0   OPEN\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        " Pressure   PASCAL\n"
        "[END]\n"
    )
    path = tmp_path / "bad_pressure.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match="unknown EPANET pressure unit"):
        load_network_from_inp(path, parser="fallback")


# ---------------------------------------------------------------------------
# TCV settings remain dimensionless (NOT scaled by pressure unit)
# ---------------------------------------------------------------------------


def test_tcv_setting_not_affected_by_pressure_directive(
    tmp_path: Path,
) -> None:
    """TCV settings are dimensionless K coefficients; the pressure
    directive must not scale them.
    """
    # Same TCV network parsed with and without a Pressure directive
    # should produce identical surrogate pipe parameters.
    def write_tcv(pressure_directive: str | None) -> Path:
        pressure_line = (
            f" Pressure   {pressure_directive}\n" if pressure_directive else ""
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
            f"{pressure_line}"
            "[END]\n"
        )
        path = tmp_path / (
            f"tcv_pressure_{(pressure_directive or 'none').lower()}.inp"
        )
        path.write_text(inp)
        return path

    net_none = load_network_from_inp(write_tcv(None), parser="fallback")
    net_psi = load_network_from_inp(write_tcv("PSI"), parser="fallback")
    net_bar = load_network_from_inp(write_tcv("BAR"), parser="fallback")

    # The TCV surrogate length, diameter, and c_factor depend ONLY on
    # K, K_minor, diameter, and Q_nom — none of which change under
    # different pressure-unit declarations.
    assert net_none.lengths.tolist() == net_psi.lengths.tolist()
    assert net_none.lengths.tolist() == net_bar.lengths.tolist()
    assert net_none.diameters.tolist() == net_psi.diameters.tolist()
    assert net_none.c_factors.tolist() == net_psi.c_factors.tolist()


# ---------------------------------------------------------------------------
# Existing SI / GPM fixtures still work
# ---------------------------------------------------------------------------


def test_existing_si_prv_fixture_unaffected_by_sprint17() -> None:
    """Re-confirm the Sprint 15 SI PRV fixture still loads and pins
    J2 at 20 m, with no Pressure directive in the file.
    """
    si_prv = _FIXTURE_DIR / "epanet_reference_prv.inp"
    net = load_network_from_inp(si_prv, parser="fallback")
    # J2 is index 1.
    assert bool(net.fixed_head_mask[1].item())
    assert float(net.fixed_head_values[1].item()) == pytest.approx(20.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Optional WNTR path: do not double-convert
# ---------------------------------------------------------------------------


def test_wntr_si_prv_still_pins_downstream_at_setting() -> None:
    """WNTR normalises pressure settings internally; the WNTR
    back-end must not double-convert. The shipped SI PRV fixture
    has setting=20 m and downstream elev=0 — WNTR must report
    fixed-head 20 m.
    """
    pytest.importorskip("wntr")
    si_prv = _FIXTURE_DIR / "epanet_reference_prv.inp"
    net_fb = load_network_from_inp(si_prv, parser="fallback")
    net_wn = load_network_from_inp(si_prv, parser="wntr")
    fb_pinned = sorted(
        v for v, m in zip(
            net_fb.fixed_head_values.tolist(), net_fb.fixed_head_mask.tolist()
        ) if m
    )
    wn_pinned = sorted(
        v for v, m in zip(
            net_wn.fixed_head_values.tolist(), net_wn.fixed_head_mask.tolist()
        ) if m
    )
    assert fb_pinned == pytest.approx(wn_pinned, abs=1e-4)
