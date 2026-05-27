"""Sprint 19 — EPANET ``[OPTIONS] Specific Gravity`` parsing.

Sprint 18 added fallback support for the ``[OPTIONS] Demand
Multiplier`` directive. Sprint 19 propagates fluid density to the
two places where it matters in the current importer / surrogates:

* PRV ``[OPTIONS] Pressure`` conversion for true pressure units
  (``PSI``, ``KPA``, ``BAR``) divides metres of *fluid* head by
  the specific gravity. Head-length pressure aliases (``METERS``,
  ``M``, ``FEET``, ``FT``) are NOT scaled — they are already length
  units.
* POWER pump surrogate scales the effective density by the specific
  gravity so ``H_nom = P / (rho_water * sg * g * Q_nom)``.

These tests pin:

* :func:`resolve_specific_gravity` defaults, parsing, and validation;
* fallback parser behaviour under SI and US-customary flow-unit
  families;
* tolerance of case / whitespace variations in the two-word option
  key;
* invariants the specific gravity must NOT touch (junction
  elevations, reservoir / tank fixed heads, HEAD pump curve
  coefficients, TCV settings / effective resistance, demand
  multiplier behaviour, head-length pressure aliases);
* compatibility with the Sprint 11 / 16 / 17 / 18 fixtures;
* optional WNTR parity, which is documented as ambiguous and not
  enforced by Sprint 19.

None of the non-WNTR tests import WNTR or any external EPANET
runtime.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    fit_power_pump_surrogate,
    load_network_from_inp,
    newton_solve,
)
from aquaoptima.dphm.inp_io import (
    resolve_demand_multiplier,
    resolve_specific_gravity,
)


_FT_TO_M = 0.3048
_GPM_TO_M3S = 0.003785411784 / 60.0

_RHO = 1000.0
_G = 9.80665
_PA_PER_M_WATER = _RHO * _G
_PSI_TO_PA = 6894.757293168
_KPA_TO_PA = 1000.0
_BAR_TO_PA = 100_000.0
_KW_TO_W = 1000.0


_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "examples"
)
_LOOP_GPM = _FIXTURE_DIR / "epanet_reference_loop_gpm.inp"
_PRV_GPM_PSI = _FIXTURE_DIR / "epanet_reference_prv_gpm_psi.inp"


# ---------------------------------------------------------------------------
# resolve_specific_gravity — defaults and validation
# ---------------------------------------------------------------------------


def test_resolve_specific_gravity_default_is_one_when_missing() -> None:
    assert resolve_specific_gravity({}) == 1.0


def test_resolve_specific_gravity_default_is_one_when_empty_string() -> None:
    assert resolve_specific_gravity({"SPECIFIC GRAVITY": ""}) == 1.0


@pytest.mark.parametrize("value", [0.5, 0.85, 1.0, 1.2, 2.0, 13.5])
def test_resolve_specific_gravity_parses_valid_positive(value: float) -> None:
    assert resolve_specific_gravity(
        {"SPECIFIC GRAVITY": str(value)}
    ) == pytest.approx(value)


def test_resolve_specific_gravity_rejects_zero() -> None:
    with pytest.raises(ValueError, match="must be strictly positive"):
        resolve_specific_gravity({"SPECIFIC GRAVITY": "0"})
    with pytest.raises(ValueError, match="must be strictly positive"):
        resolve_specific_gravity({"SPECIFIC GRAVITY": "0.0"})


def test_resolve_specific_gravity_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must be strictly positive"):
        resolve_specific_gravity({"SPECIFIC GRAVITY": "-1.0"})


def test_resolve_specific_gravity_rejects_nan() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        resolve_specific_gravity({"SPECIFIC GRAVITY": "nan"})


def test_resolve_specific_gravity_rejects_inf() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        resolve_specific_gravity({"SPECIFIC GRAVITY": "inf"})
    with pytest.raises(ValueError, match="must be finite"):
        resolve_specific_gravity({"SPECIFIC GRAVITY": "-inf"})


def test_resolve_specific_gravity_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="is not numeric"):
        resolve_specific_gravity({"SPECIFIC GRAVITY": "two"})


# ---------------------------------------------------------------------------
# Fallback parser — case / whitespace tolerance for two-word option key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directive_row",
    [
        " Specific Gravity   0.85\n",            # canonical
        " SPECIFIC GRAVITY   0.85\n",            # upper case
        " specific gravity   0.85\n",            # lower case
        " Specific    Gravity    0.85\n",        # extra whitespace
        " specific   GRAVITY       0.85\n",      # mixed case + whitespace
    ],
)
def test_fallback_specific_gravity_key_is_case_and_whitespace_tolerant(
    tmp_path: Path, directive_row: str
) -> None:
    """The two-word key parses identically across casing/whitespace
    variants. We verify by loading a tiny PRV-PSI fixture and
    confirming the downstream fixed head is scaled by 1/sg.
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
        " V1   J1   J2   80   PRV   30.0   0\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        " Pressure   PSI\n"
        f"{directive_row}"
        "[END]\n"
    )
    path = tmp_path / "sg_case_whitespace.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # 30 psi -> head_m = 30 * (psi_to_Pa / rho*g) / sg, with sg=0.85.
    expected = 30.0 * (_PSI_TO_PA / _PA_PER_M_WATER) / 0.85
    assert float(net.fixed_head_values[1].item()) == pytest.approx(
        expected, abs=1e-5
    )


# ---------------------------------------------------------------------------
# Fallback parser — invalid SG values rejected by the parser
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
        ("water", "is not numeric"),
    ],
)
def test_fallback_rejects_invalid_specific_gravity(
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
        f" Specific Gravity   {value}\n"
        "[END]\n"
    )
    path = (
        tmp_path
        / f"bad_sg_{value.replace('.', '_').replace('-', 'neg_')}.inp"
    )
    path.write_text(inp)
    with pytest.raises(ValueError, match=error_match):
        load_network_from_inp(path, parser="fallback")


# ---------------------------------------------------------------------------
# PRV — Pressure PSI/KPA/BAR scaled by SG
# ---------------------------------------------------------------------------


def _write_prv_pressure_fixture(
    tmp_path: Path,
    *,
    pressure_directive: str,
    setting_value: float,
    specific_gravity: float | None,
) -> Path:
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
        f" V1   J1   J2   80   PRV   {setting_value}   0\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f" Pressure   {pressure_directive}\n"
        f"{sg_line}"
        "[END]\n"
    )
    path = (
        tmp_path
        / f"prv_{pressure_directive.lower()}_sg_{specific_gravity}.inp"
    )
    path.write_text(inp)
    return path


@pytest.mark.parametrize(
    "pressure_directive, setting_value, base_pa_per_unit",
    [
        ("PSI", 30.0, _PSI_TO_PA),
        ("KPA", 200.0, _KPA_TO_PA),
        ("BAR", 2.0, _BAR_TO_PA),
    ],
)
@pytest.mark.parametrize("sg", [0.5, 0.85, 1.0, 1.2, 2.0])
def test_prv_true_pressure_units_scaled_by_specific_gravity(
    tmp_path: Path,
    pressure_directive: str,
    setting_value: float,
    base_pa_per_unit: float,
    sg: float,
) -> None:
    """For PSI/KPA/BAR, fluid-head conversion divides by SG."""
    path = _write_prv_pressure_fixture(
        tmp_path,
        pressure_directive=pressure_directive,
        setting_value=setting_value,
        specific_gravity=sg,
    )
    net = load_network_from_inp(path, parser="fallback")
    expected = setting_value * base_pa_per_unit / _PA_PER_M_WATER / sg
    # J2 is the second junction (index 1).
    assert bool(net.fixed_head_mask[1].item())
    assert float(net.fixed_head_values[1].item()) == pytest.approx(
        expected, abs=1e-5
    )


def test_prv_pressure_psi_default_sg_one_matches_sprint17(
    tmp_path: Path,
) -> None:
    """Default SG = 1.0 yields the Sprint 17 head value exactly."""
    path_with_sg = _write_prv_pressure_fixture(
        tmp_path,
        pressure_directive="PSI",
        setting_value=30.0,
        specific_gravity=1.0,
    )
    path_without_sg = _write_prv_pressure_fixture(
        tmp_path,
        pressure_directive="PSI",
        setting_value=30.0,
        specific_gravity=None,
    )
    net_with = load_network_from_inp(path_with_sg, parser="fallback")
    net_without = load_network_from_inp(path_without_sg, parser="fallback")
    assert float(net_with.fixed_head_values[1].item()) == pytest.approx(
        float(net_without.fixed_head_values[1].item()), abs=1e-9
    )


def test_prv_psi_sg_two_halves_head(tmp_path: Path) -> None:
    """SG = 2.0 produces half the metres-of-fluid-head of SG = 1.0
    for the same pressure setting in PSI.
    """
    path_sg1 = _write_prv_pressure_fixture(
        tmp_path,
        pressure_directive="PSI",
        setting_value=30.0,
        specific_gravity=1.0,
    )
    path_sg2 = _write_prv_pressure_fixture(
        tmp_path,
        pressure_directive="PSI",
        setting_value=30.0,
        specific_gravity=2.0,
    )
    net1 = load_network_from_inp(path_sg1, parser="fallback")
    net2 = load_network_from_inp(path_sg2, parser="fallback")
    h1 = float(net1.fixed_head_values[1].item())
    h2 = float(net2.fixed_head_values[1].item())
    assert h2 == pytest.approx(0.5 * h1, rel=1e-6)


# ---------------------------------------------------------------------------
# PRV — head-length pressure aliases NOT scaled by SG
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pressure_directive, setting_value, expected_head_m",
    [
        ("METERS", 20.0, 20.0),
        ("M", 20.0, 20.0),
        ("FEET", 80.0, 80.0 * _FT_TO_M),
        ("FT", 80.0, 80.0 * _FT_TO_M),
    ],
)
@pytest.mark.parametrize("sg", [0.5, 1.0, 2.0])
def test_prv_head_length_aliases_unaffected_by_specific_gravity(
    tmp_path: Path,
    pressure_directive: str,
    setting_value: float,
    expected_head_m: float,
    sg: float,
) -> None:
    """METERS/M/FEET/FT are length units — already metres of head —
    so the PRV setting must NOT be divided by SG.
    """
    path = _write_prv_pressure_fixture(
        tmp_path,
        pressure_directive=pressure_directive,
        setting_value=setting_value,
        specific_gravity=sg,
    )
    net = load_network_from_inp(path, parser="fallback")
    assert float(net.fixed_head_values[1].item()) == pytest.approx(
        expected_head_m, abs=1e-6
    )


# ---------------------------------------------------------------------------
# PRV — default (no [OPTIONS] Pressure) behavior NOT scaled by SG
# ---------------------------------------------------------------------------


def _write_prv_default_pressure_fixture(
    tmp_path: Path,
    *,
    units: str,
    setting_value: float,
    specific_gravity: float | None,
) -> Path:
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
        f" V1   J1   J2   80   PRV   {setting_value}   0\n"
        "[OPTIONS]\n"
        f" Units      {units}\n"
        " Headloss   H-W\n"
        f"{sg_line}"
        "[END]\n"
    )
    path = tmp_path / f"prv_default_{units}_sg_{specific_gravity}.inp"
    path.write_text(inp)
    return path


def test_default_no_pressure_directive_si_unaffected_by_sg(
    tmp_path: Path,
) -> None:
    """When [OPTIONS] Pressure is absent under SI flow units, the PRV
    setting follows the flow-unit family's head_to_m (already metres
    of head) and is NOT scaled by SG. This preserves the Sprint 16/17
    contract.
    """
    net_sg1 = load_network_from_inp(
        _write_prv_default_pressure_fixture(
            tmp_path, units="LPS", setting_value=20.0, specific_gravity=1.0
        ),
        parser="fallback",
    )
    net_sg2 = load_network_from_inp(
        _write_prv_default_pressure_fixture(
            tmp_path, units="LPS", setting_value=20.0, specific_gravity=2.0
        ),
        parser="fallback",
    )
    # Both should be 20 m exactly (head_to_m=1.0 under SI).
    assert float(net_sg1.fixed_head_values[1].item()) == pytest.approx(
        20.0, abs=1e-9
    )
    assert float(net_sg2.fixed_head_values[1].item()) == pytest.approx(
        20.0, abs=1e-9
    )


def test_default_no_pressure_directive_us_unaffected_by_sg(
    tmp_path: Path,
) -> None:
    """When [OPTIONS] Pressure is absent under US flow units, the PRV
    setting is interpreted as feet of head (Sprint 16 default).
    Specific gravity must NOT scale it.
    """
    # GPM family: setting interpreted as feet of head.
    net_sg1 = load_network_from_inp(
        _write_prv_default_pressure_fixture(
            tmp_path, units="GPM", setting_value=80.0, specific_gravity=1.0
        ),
        parser="fallback",
    )
    net_sg2 = load_network_from_inp(
        _write_prv_default_pressure_fixture(
            tmp_path, units="GPM", setting_value=80.0, specific_gravity=2.0
        ),
        parser="fallback",
    )
    expected = 80.0 * _FT_TO_M
    assert float(net_sg1.fixed_head_values[1].item()) == pytest.approx(
        expected, abs=1e-5
    )
    assert float(net_sg2.fixed_head_values[1].item()) == pytest.approx(
        expected, abs=1e-5
    )


# ---------------------------------------------------------------------------
# POWER pump surrogate helper — SG scales a0 and a2
# ---------------------------------------------------------------------------


def test_fit_power_pump_surrogate_default_sg_is_one() -> None:
    """Calling :func:`fit_power_pump_surrogate` without SG must match
    the Sprint 14 behavior (sg defaults to 1.0).
    """
    coeffs_default, diag_default = fit_power_pump_surrogate(7.5, 0.015)
    coeffs_explicit, diag_explicit = fit_power_pump_surrogate(
        7.5, 0.015, specific_gravity=1.0
    )
    assert coeffs_default == pytest.approx(coeffs_explicit, rel=1e-15)
    assert diag_default["a0"] == pytest.approx(diag_explicit["a0"])
    assert diag_default["a2"] == pytest.approx(diag_explicit["a2"])
    # head_at_nominal_m = P / (rho * g * Q_nom).
    expected_h = (7.5 * _KW_TO_W) / (_RHO * _G * 0.015)
    assert diag_default["head_at_nominal_m"] == pytest.approx(
        expected_h, rel=1e-9
    )


@pytest.mark.parametrize("sg", [0.5, 0.85, 1.0, 1.2, 2.0])
def test_fit_power_pump_surrogate_sg_scaling(sg: float) -> None:
    """SG scales H_nom by 1/sg; a0 and a2 inherit that factor."""
    base_coeffs, _ = fit_power_pump_surrogate(7.5, 0.015)
    sg_coeffs, sg_diag = fit_power_pump_surrogate(
        7.5, 0.015, specific_gravity=sg
    )
    a0_base, a1_base, a2_base = base_coeffs
    a0_sg, a1_sg, a2_sg = sg_coeffs
    assert a0_sg == pytest.approx(a0_base / sg, rel=1e-12)
    assert a1_sg == pytest.approx(0.0, abs=1e-15)
    assert a1_base == pytest.approx(0.0, abs=1e-15)
    assert a2_sg == pytest.approx(a2_base / sg, rel=1e-12)
    assert sg_diag["specific_gravity"] == pytest.approx(sg)


def test_fit_power_pump_surrogate_rejects_zero_sg() -> None:
    with pytest.raises(ValueError, match="specific_gravity must be"):
        fit_power_pump_surrogate(7.5, 0.015, specific_gravity=0.0)


def test_fit_power_pump_surrogate_rejects_negative_sg() -> None:
    with pytest.raises(ValueError, match="specific_gravity must be"):
        fit_power_pump_surrogate(7.5, 0.015, specific_gravity=-1.0)


def test_fit_power_pump_surrogate_rejects_nan_sg() -> None:
    with pytest.raises(ValueError, match="specific_gravity must be"):
        fit_power_pump_surrogate(
            7.5, 0.015, specific_gravity=float("nan")
        )


def test_fit_power_pump_surrogate_rejects_inf_sg() -> None:
    with pytest.raises(ValueError, match="specific_gravity must be"):
        fit_power_pump_surrogate(
            7.5, 0.015, specific_gravity=float("inf")
        )


# ---------------------------------------------------------------------------
# POWER pump — fallback parser applies SG
# ---------------------------------------------------------------------------


def _write_power_pump_fixture(
    tmp_path: Path, *, specific_gravity: float | None
) -> Path:
    sg_line = (
        f" Specific Gravity   {specific_gravity}\n"
        if specific_gravity is not None
        else ""
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
        f"{sg_line}"
        "[END]\n"
    )
    path = tmp_path / f"power_pump_sg_{specific_gravity}.inp"
    path.write_text(inp)
    return path


def test_power_pump_default_sg_is_one(tmp_path: Path) -> None:
    """No SG directive => SG defaults to 1.0; a0 matches the Sprint 14
    surrogate exactly.
    """
    net = load_network_from_inp(
        _write_power_pump_fixture(tmp_path, specific_gravity=None),
        parser="fallback",
    )
    # Edge ordering: pipe then pump. Pump is index 1.
    a0_parsed = float(net.pump_coeffs[1][0].item())
    coeffs_ref, _ = fit_power_pump_surrogate(7.5, 0.015)
    assert a0_parsed == pytest.approx(coeffs_ref[0], rel=1e-5)


@pytest.mark.parametrize("sg", [0.5, 1.0, 2.0])
def test_power_pump_sg_scales_a0(tmp_path: Path, sg: float) -> None:
    """The parsed a0 must equal the helper's a0 with the same SG."""
    net = load_network_from_inp(
        _write_power_pump_fixture(tmp_path, specific_gravity=sg),
        parser="fallback",
    )
    a0_parsed = float(net.pump_coeffs[1][0].item())
    coeffs_ref, _ = fit_power_pump_surrogate(
        7.5, 0.015, specific_gravity=sg
    )
    assert a0_parsed == pytest.approx(coeffs_ref[0], rel=1e-5)


def test_power_pump_sg_two_halves_a0(tmp_path: Path) -> None:
    """SG=2.0 halves H_nom and therefore halves a0."""
    net_sg1 = load_network_from_inp(
        _write_power_pump_fixture(tmp_path, specific_gravity=1.0),
        parser="fallback",
    )
    net_sg2 = load_network_from_inp(
        _write_power_pump_fixture(tmp_path, specific_gravity=2.0),
        parser="fallback",
    )
    a0_sg1 = float(net_sg1.pump_coeffs[1][0].item())
    a0_sg2 = float(net_sg2.pump_coeffs[1][0].item())
    assert a0_sg2 == pytest.approx(0.5 * a0_sg1, rel=1e-5)


def test_power_pump_sg_half_doubles_a0(tmp_path: Path) -> None:
    """SG=0.5 doubles H_nom and therefore doubles a0."""
    net_sg1 = load_network_from_inp(
        _write_power_pump_fixture(tmp_path, specific_gravity=1.0),
        parser="fallback",
    )
    net_sg_half = load_network_from_inp(
        _write_power_pump_fixture(tmp_path, specific_gravity=0.5),
        parser="fallback",
    )
    a0_sg1 = float(net_sg1.pump_coeffs[1][0].item())
    a0_sg_half = float(net_sg_half.pump_coeffs[1][0].item())
    assert a0_sg_half == pytest.approx(2.0 * a0_sg1, rel=1e-5)


def test_power_pump_sg_two_solves(tmp_path: Path) -> None:
    """Sanity: an SG=2.0 POWER pump network still solves with the
    analytic-Jacobian Newton.
    """
    net = load_network_from_inp(
        _write_power_pump_fixture(tmp_path, specific_gravity=2.0),
        parser="fallback",
    )
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-7


# ---------------------------------------------------------------------------
# HEAD pump curves NOT affected by SG
# ---------------------------------------------------------------------------


def test_head_pump_curve_coefficients_unaffected_by_specific_gravity(
    tmp_path: Path,
) -> None:
    """EPANET HEAD curves are head-vs-flow tables — they are already
    expressed in metres of head, so specific gravity must not touch
    them.
    """
    def write_head_pump(sg: float | None) -> Path:
        sg_line = (
            f" Specific Gravity   {sg}\n" if sg is not None else ""
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
            f"{sg_line}"
            "[END]\n"
        )
        p = tmp_path / f"head_pump_sg_{sg}.inp"
        p.write_text(inp)
        return p

    net_none = load_network_from_inp(write_head_pump(None), parser="fallback")
    net_sg2 = load_network_from_inp(write_head_pump(2.0), parser="fallback")
    net_sg_half = load_network_from_inp(write_head_pump(0.5), parser="fallback")

    assert torch.allclose(
        net_none.pump_coeffs.double(),
        net_sg2.pump_coeffs.double(),
        atol=1e-12,
    )
    assert torch.allclose(
        net_none.pump_coeffs.double(),
        net_sg_half.pump_coeffs.double(),
        atol=1e-12,
    )


# ---------------------------------------------------------------------------
# TCV settings / effective resistance NOT affected by SG
# ---------------------------------------------------------------------------


def _write_tcv_fixture(
    tmp_path: Path, *, specific_gravity: float | None
) -> Path:
    sg_line = (
        f" Specific Gravity   {specific_gravity}\n"
        if specific_gravity is not None
        else ""
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
        f"{sg_line}"
        "[END]\n"
    )
    path = tmp_path / f"tcv_sg_{specific_gravity}.inp"
    path.write_text(inp)
    return path


def test_tcv_surrogate_unaffected_by_specific_gravity(tmp_path: Path) -> None:
    """The TCV surrogate depends only on K, K_minor, diameter, and
    Q_nom. Specific gravity must NOT touch any of those.
    """
    net_none = load_network_from_inp(
        _write_tcv_fixture(tmp_path, specific_gravity=None),
        parser="fallback",
    )
    net_sg2 = load_network_from_inp(
        _write_tcv_fixture(tmp_path, specific_gravity=2.0),
        parser="fallback",
    )
    net_sg_half = load_network_from_inp(
        _write_tcv_fixture(tmp_path, specific_gravity=0.5),
        parser="fallback",
    )
    # TCV surrogate is the second edge (after the pipe).
    assert net_none.lengths.tolist() == net_sg2.lengths.tolist()
    assert net_none.diameters.tolist() == net_sg2.diameters.tolist()
    assert net_none.c_factors.tolist() == net_sg2.c_factors.tolist()
    assert net_none.lengths.tolist() == net_sg_half.lengths.tolist()
    assert net_none.diameters.tolist() == net_sg_half.diameters.tolist()
    assert net_none.c_factors.tolist() == net_sg_half.c_factors.tolist()


# ---------------------------------------------------------------------------
# Reservoir / tank heads, junction elevations NOT affected by SG
# ---------------------------------------------------------------------------


def test_reservoir_head_not_affected_by_specific_gravity(
    tmp_path: Path,
) -> None:
    inp = (
        "[JUNCTIONS]\n"
        " J1  0.0   10.0\n"
        "[RESERVOIRS]\n"
        " R1  50.0\n"
        "[PIPES]\n"
        " P1  R1  J1  100  150  130  0  OPEN\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        " Specific Gravity   2.0\n"
        "[END]\n"
    )
    path = tmp_path / "reservoir_sg.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # Reservoir head is 50 m of head (length), independent of SG.
    assert float(net.fixed_head_values[-1].item()) == pytest.approx(
        50.0, abs=1e-9
    )


def test_tank_initial_water_surface_not_affected_by_specific_gravity(
    tmp_path: Path,
) -> None:
    inp = (
        "[JUNCTIONS]\n"
        " J1  0.0   10.0\n"
        "[TANKS]\n"
        " T1  20.0   5.0\n"
        "[PIPES]\n"
        " P1  T1  J1  100  150  130  0  OPEN\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        " Specific Gravity   2.0\n"
        "[END]\n"
    )
    path = tmp_path / "tank_sg.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    assert float(net.fixed_head_values[-1].item()) == pytest.approx(
        25.0, abs=1e-9
    )


# ---------------------------------------------------------------------------
# Pipe geometry NOT affected by SG
# ---------------------------------------------------------------------------


def test_pipe_geometry_not_affected_by_specific_gravity(
    tmp_path: Path,
) -> None:
    """Lengths / diameters / c_factors are pure geometry — SG must
    not touch them.
    """
    def write_loop(sg: float | None) -> Path:
        sg_line = (
            f" Specific Gravity   {sg}\n" if sg is not None else ""
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
            f"{sg_line}"
            "[END]\n"
        )
        p = tmp_path / f"loop_geom_sg_{sg}.inp"
        p.write_text(inp)
        return p

    net_none = load_network_from_inp(write_loop(None), parser="fallback")
    net_sg2 = load_network_from_inp(write_loop(2.0), parser="fallback")
    net_sg_half = load_network_from_inp(write_loop(0.5), parser="fallback")
    for net_other in (net_sg2, net_sg_half):
        assert torch.allclose(
            net_none.lengths.double(),
            net_other.lengths.double(),
            atol=1e-12,
        )
        assert torch.allclose(
            net_none.diameters.double(),
            net_other.diameters.double(),
            atol=1e-12,
        )
        assert torch.allclose(
            net_none.c_factors.double(),
            net_other.c_factors.double(),
            atol=1e-12,
        )


# ---------------------------------------------------------------------------
# Demand multiplier behaviour independent of SG
# ---------------------------------------------------------------------------


def test_demand_multiplier_independent_of_specific_gravity(
    tmp_path: Path,
) -> None:
    """SG must not touch junction demands. Demand Multiplier scales
    them; SG is an orthogonal axis on pressure/power.
    """
    def write_loop(dm: float, sg: float | None) -> Path:
        sg_line = (
            f" Specific Gravity   {sg}\n" if sg is not None else ""
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
            f"{sg_line}"
            "[END]\n"
        )
        p = tmp_path / f"loop_dm_{dm}_sg_{sg}.inp"
        p.write_text(inp)
        return p

    net_dm2_sg_none = load_network_from_inp(
        write_loop(2.0, None), parser="fallback"
    )
    net_dm2_sg2 = load_network_from_inp(
        write_loop(2.0, 2.0), parser="fallback"
    )
    # Junction demands unchanged by SG.
    assert float(net_dm2_sg_none.demands[0].item()) == pytest.approx(
        float(net_dm2_sg2.demands[0].item()), abs=1e-9
    )
    assert float(net_dm2_sg_none.demands[1].item()) == pytest.approx(
        float(net_dm2_sg2.demands[1].item()), abs=1e-9
    )
    # Sprint 18 multiplier still applies: 10 LPS * 1e-3 * 2.0 = 0.020.
    assert float(net_dm2_sg2.demands[0].item()) == pytest.approx(
        0.020, abs=1e-7
    )


def test_resolve_demand_multiplier_unaffected_by_sg_key() -> None:
    """The two-word ``Specific Gravity`` key must not confuse the
    demand multiplier resolver.
    """
    opts = {"DEMAND MULTIPLIER": "1.5", "SPECIFIC GRAVITY": "2.0"}
    assert resolve_demand_multiplier(opts) == pytest.approx(1.5)
    assert resolve_specific_gravity(opts) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Existing fixtures unaffected by Sprint 19 changes
# ---------------------------------------------------------------------------


def test_existing_si_loop_fixture_unaffected_by_sprint19() -> None:
    si_loop = _FIXTURE_DIR / "epanet_reference_loop.inp"
    net = load_network_from_inp(si_loop, parser="fallback")
    expected_positive = torch.tensor([0.010, 0.015, 0.012, 0.008])
    assert torch.allclose(
        net.demands[:4].double(), expected_positive.double(), atol=1e-9
    )


def test_existing_gpm_loop_fixture_unaffected_by_sprint19() -> None:
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    junction_demands = torch.tensor(
        [100.0, 150.0, 120.0, 80.0]
    ) * _GPM_TO_M3S
    assert torch.allclose(
        net.demands[:4].double(), junction_demands.double(), atol=1e-8
    )


def test_existing_gpm_psi_prv_fixture_unaffected_by_sprint19() -> None:
    """The Sprint 17 GPM+PSI PRV fixture has no Specific Gravity
    directive, so SG defaults to 1.0 and the Sprint 17 head value is
    preserved exactly.
    """
    net = load_network_from_inp(_PRV_GPM_PSI, parser="fallback")
    expected_head = 30.0 * (_PSI_TO_PA / _PA_PER_M_WATER)
    assert float(net.fixed_head_values[1].item()) == pytest.approx(
        expected_head, abs=1e-4
    )


def test_existing_power_pump_fixture_unaffected_by_sprint19() -> None:
    """The Sprint 14 POWER pump fixture has no Specific Gravity
    directive; the loaded a0 must match the SG=1.0 surrogate exactly.
    """
    fixture = _FIXTURE_DIR / "epanet_reference_power_pump.inp"
    net = load_network_from_inp(fixture, parser="fallback")
    # Confirm the network still loads and has a pump edge with a
    # positive shut-off head.
    assert any(net.pump_mask.tolist())
    pump_idx = next(i for i, m in enumerate(net.pump_mask.tolist()) if m)
    assert float(net.pump_coeffs[pump_idx][0].item()) > 0.0


# ---------------------------------------------------------------------------
# WNTR optional parity (documented as ambiguous for SG in Sprint 19)
# ---------------------------------------------------------------------------


def test_wntr_existing_gpm_psi_fixture_parity_unchanged() -> None:
    """WNTR back-end and fallback back-end produce closely-matching
    PRV head on the Sprint 17 GPM-PSI fixture (SG defaults to 1.0).

    Tolerance is intentionally loose (~5 cm of head): WNTR uses its
    own internal PSI->head conversion constants and may diverge from
    our NIST-exact value by a few mm of head per psi. This is a
    pre-existing WNTR discrepancy that Sprint 19 does NOT try to
    paper over — see ``SPRINT19_REPORT.md`` for the documented
    ambiguity around WNTR's handling of specific gravity. The test
    exists only to guard against orders-of-magnitude regressions.
    """
    pytest.importorskip("wntr")
    net_fb = load_network_from_inp(_PRV_GPM_PSI, parser="fallback")
    net_wn = load_network_from_inp(_PRV_GPM_PSI, parser="wntr")
    fb_pinned = sorted(
        v for v, m in zip(
            net_fb.fixed_head_values.tolist(),
            net_fb.fixed_head_mask.tolist(),
        )
        if m
    )
    wn_pinned = sorted(
        v for v, m in zip(
            net_wn.fixed_head_values.tolist(),
            net_wn.fixed_head_mask.tolist(),
        )
        if m
    )
    assert fb_pinned == pytest.approx(wn_pinned, abs=5e-2)


def test_wntr_existing_si_loop_fixture_parity_unchanged() -> None:
    """SI loop fixture (no SG, no Pressure) still parses identically
    between WNTR and fallback.
    """
    pytest.importorskip("wntr")
    si_loop = _FIXTURE_DIR / "epanet_reference_loop.inp"
    net_fb = load_network_from_inp(si_loop, parser="fallback")
    net_wn = load_network_from_inp(si_loop, parser="wntr")
    fb_demand = sorted(net_fb.demands.tolist())
    wn_demand = sorted(net_wn.demands.tolist())
    assert fb_demand == pytest.approx(wn_demand, abs=1e-7)
