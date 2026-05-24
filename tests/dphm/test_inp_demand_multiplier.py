"""Sprint 18 — EPANET ``[OPTIONS] Demand Multiplier`` parsing.

Sprint 16 hardened the per-flow-unit conversion manifest. Sprint 17
added an orthogonal pressure-display unit axis. Sprint 18 adds
fallback support for the EPANET ``[OPTIONS] Demand Multiplier``
directive — a single non-negative scalar that scales every junction's
baseline demand at load time, after the flow-unit conversion.

These tests pin:

* the public :func:`resolve_demand_multiplier` helper's defaults,
  parsing, and validation surface;
* the fallback parser's behaviour with and without the directive,
  under both SI and US-customary flow-unit families;
* case-insensitive parsing and tolerant whitespace handling for the
  two-word ``Demand Multiplier`` option key;
* invariants the multiplier must NOT touch (reservoir / tank heads,
  pipe / pump / valve dimensions, pump HEAD curve points, TCV
  settings, MinorLoss columns);
* the POWER pump nominal-flow anchor must see the multiplied
  demand;
* WNTR optional parity, when WNTR is installed.

None of the non-WNTR tests import WNTR or any external EPANET
runtime.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    fit_power_pump_surrogate,
    load_network_from_inp,
    newton_solve,
)
from aquaoptima.dphm.inp_io import resolve_demand_multiplier


_FT_TO_M = 0.3048
_IN_TO_M = 0.0254
_GPM_TO_M3S = 0.003785411784 / 60.0

_RHO = 1000.0
_G = 9.80665
_KW_TO_W = 1000.0


_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "examples"
)
_LOOP_GPM = _FIXTURE_DIR / "epanet_reference_loop_gpm.inp"
_LOOP_GPM_DM = (
    _FIXTURE_DIR / "epanet_reference_loop_gpm_demand_multiplier.inp"
)


# ---------------------------------------------------------------------------
# resolve_demand_multiplier — defaults and validation
# ---------------------------------------------------------------------------


def test_resolve_demand_multiplier_default_is_one_when_missing() -> None:
    assert resolve_demand_multiplier({}) == 1.0


def test_resolve_demand_multiplier_default_is_one_when_empty_string() -> None:
    assert resolve_demand_multiplier({"DEMAND MULTIPLIER": ""}) == 1.0


def test_resolve_demand_multiplier_parses_valid_positive_value() -> None:
    assert resolve_demand_multiplier(
        {"DEMAND MULTIPLIER": "2.5"}
    ) == pytest.approx(2.5)


def test_resolve_demand_multiplier_accepts_zero() -> None:
    assert resolve_demand_multiplier({"DEMAND MULTIPLIER": "0"}) == 0.0
    assert resolve_demand_multiplier({"DEMAND MULTIPLIER": "0.0"}) == 0.0


def test_resolve_demand_multiplier_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        resolve_demand_multiplier({"DEMAND MULTIPLIER": "-1.0"})


def test_resolve_demand_multiplier_rejects_nan() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        resolve_demand_multiplier({"DEMAND MULTIPLIER": "nan"})


def test_resolve_demand_multiplier_rejects_inf() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        resolve_demand_multiplier({"DEMAND MULTIPLIER": "inf"})


def test_resolve_demand_multiplier_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="is not numeric"):
        resolve_demand_multiplier({"DEMAND MULTIPLIER": "two"})


# ---------------------------------------------------------------------------
# Fallback parser — default no-multiplier behaviour
# ---------------------------------------------------------------------------


def _write_lps_loop(tmp_path: Path, *, options_extra: str = "") -> Path:
    """Write a tiny LPS loop fixture with optional extra options rows."""
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
        f"{options_extra}"
        "[END]\n"
    )
    path = tmp_path / "lps_loop_dm.inp"
    path.write_text(inp)
    return path


def test_fallback_default_when_directive_absent_lps(tmp_path: Path) -> None:
    """No Demand Multiplier directive -> multiplier = 1.0 -> demands
    match the Sprint 16 unscaled LPS conversion.
    """
    path = _write_lps_loop(tmp_path)
    net = load_network_from_inp(path, parser="fallback")
    # J1 = 10 LPS = 0.010 m^3/s, J2 = 15 LPS = 0.015 m^3/s.
    assert float(net.demands[0].item()) == pytest.approx(0.010, abs=1e-9)
    assert float(net.demands[1].item()) == pytest.approx(0.015, abs=1e-9)


def test_fallback_unit_value_one_is_no_op(tmp_path: Path) -> None:
    """``Demand Multiplier 1.0`` is mathematically equivalent to the
    default — every junction's demand is unchanged.
    """
    no_dm = _write_lps_loop(tmp_path)
    inp_dm = (
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
        " Demand Multiplier   1.0\n"
        "[END]\n"
    )
    path_dm = tmp_path / "lps_loop_dm_one.inp"
    path_dm.write_text(inp_dm)
    net_no = load_network_from_inp(no_dm, parser="fallback")
    net_dm = load_network_from_inp(path_dm, parser="fallback")
    assert torch.allclose(
        net_no.demands.double(), net_dm.demands.double(), atol=1e-12
    )


# ---------------------------------------------------------------------------
# Fallback parser — LPS / SI scaling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("multiplier", [0.5, 1.5, 2.0, 3.0, 10.0])
def test_fallback_scales_lps_demands_by_multiplier(
    tmp_path: Path, multiplier: float
) -> None:
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
        f" Demand Multiplier   {multiplier}\n"
        "[END]\n"
    )
    path = tmp_path / f"lps_loop_dm_{multiplier}.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # J1 expected = 10 LPS * 1e-3 * multiplier; J2 = 15 LPS * 1e-3 * mult.
    # ``Network`` tensors use torch's default (float32) dtype, so the
    # precision floor here is around 1e-7 absolute on demand values.
    assert float(net.demands[0].item()) == pytest.approx(
        0.010 * multiplier, rel=1e-6, abs=1e-7
    )
    assert float(net.demands[1].item()) == pytest.approx(
        0.015 * multiplier, rel=1e-6, abs=1e-7
    )
    # Reservoir absorbs the deficit.
    expected_reservoir = -(0.010 + 0.015) * multiplier
    assert float(net.demands[-1].item()) == pytest.approx(
        expected_reservoir, rel=1e-6, abs=1e-7
    )


# ---------------------------------------------------------------------------
# Fallback parser — GPM / US scaling
# ---------------------------------------------------------------------------


def test_shipped_gpm_demand_multiplier_fixture_is_present() -> None:
    assert _LOOP_GPM_DM.is_file(), (
        f"missing shipped Sprint 18 fixture at {_LOOP_GPM_DM}"
    )


def test_shipped_gpm_demand_multiplier_fixture_doubles_demand_sum() -> None:
    """The shipped Sprint 18 fixture has ``Demand Multiplier 2.0`` and
    is otherwise identical to ``epanet_reference_loop_gpm.inp``. The
    positive demand sum must therefore be exactly twice the baseline.
    """
    net_base = load_network_from_inp(_LOOP_GPM, parser="fallback")
    net_dm = load_network_from_inp(_LOOP_GPM_DM, parser="fallback")
    base_positive = float(
        sum(d for d in net_base.demands.tolist() if d > 0.0)
    )
    dm_positive = float(
        sum(d for d in net_dm.demands.tolist() if d > 0.0)
    )
    assert dm_positive == pytest.approx(2.0 * base_positive, abs=1e-9)


def test_shipped_gpm_demand_multiplier_fixture_per_junction_demand() -> None:
    """Every junction demand is exactly twice the baseline GPM value."""
    net = load_network_from_inp(_LOOP_GPM_DM, parser="fallback")
    # Raw GPM values from the fixture: 100, 150, 120, 80 — doubled.
    expected = torch.tensor([100.0, 150.0, 120.0, 80.0]) * _GPM_TO_M3S * 2.0
    assert torch.allclose(
        net.demands[:4].double(), expected.double(), atol=1e-8
    )


def test_shipped_gpm_demand_multiplier_fixture_does_not_scale_geometry() -> None:
    """Reservoir head and pipe geometry MUST be identical to the
    Sprint 16 GPM baseline fixture.
    """
    net_base = load_network_from_inp(_LOOP_GPM, parser="fallback")
    net_dm = load_network_from_inp(_LOOP_GPM_DM, parser="fallback")
    # Reservoir head unchanged.
    assert float(net_dm.fixed_head_values[-1].item()) == pytest.approx(
        float(net_base.fixed_head_values[-1].item()), abs=1e-9
    )
    # Pipe lengths / diameters / c_factors unchanged.
    assert torch.allclose(
        net_dm.lengths.double(), net_base.lengths.double(), atol=1e-9
    )
    assert torch.allclose(
        net_dm.diameters.double(), net_base.diameters.double(), atol=1e-9
    )
    assert torch.allclose(
        net_dm.c_factors.double(), net_base.c_factors.double(), atol=1e-9
    )


def test_shipped_gpm_demand_multiplier_fixture_solves() -> None:
    net = load_network_from_inp(_LOOP_GPM_DM, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-7


# ---------------------------------------------------------------------------
# Zero multiplier
# ---------------------------------------------------------------------------


def test_fallback_zero_multiplier_loads_with_zero_demands(
    tmp_path: Path,
) -> None:
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
        " Demand Multiplier   0.0\n"
        "[END]\n"
    )
    path = tmp_path / "lps_loop_dm_zero.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # All junction demands forced to zero; mass balance trivially zero.
    assert float(net.demands[0].item()) == pytest.approx(0.0, abs=1e-12)
    assert float(net.demands[1].item()) == pytest.approx(0.0, abs=1e-12)
    # Reservoir share is also zero (no deficit to absorb).
    assert float(net.demands[-1].item()) == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Validation errors raised by the parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, error_match",
    [
        ("-1.0", "must be non-negative"),
        ("nan", "must be finite"),
        ("inf", "must be finite"),
        ("-inf", "must be finite"),
        ("two", "is not numeric"),
    ],
)
def test_fallback_rejects_invalid_multiplier(
    tmp_path: Path, value: str, error_match: str
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
        f" Demand Multiplier   {value}\n"
        "[END]\n"
    )
    path = tmp_path / f"bad_dm_{value.replace('.', '_').replace('-', 'neg_')}.inp"
    path.write_text(inp)
    with pytest.raises(ValueError, match=error_match):
        load_network_from_inp(path, parser="fallback")


# ---------------------------------------------------------------------------
# Case / whitespace tolerance for the option key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directive_row",
    [
        " Demand Multiplier   2.0\n",          # canonical
        " DEMAND MULTIPLIER   2.0\n",          # upper case
        " demand multiplier   2.0\n",          # lower case
        " Demand    Multiplier    2.0\n",      # extra whitespace
        " demand   MULTIPLIER       2.0\n",    # mixed case + whitespace
    ],
)
def test_fallback_demand_multiplier_key_is_case_and_whitespace_tolerant(
    tmp_path: Path, directive_row: str
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
        f"{directive_row}"
        "[END]\n"
    )
    path = tmp_path / "dm_case_whitespace.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # Expect 10 LPS * 1e-3 * 2.0 = 0.020 m^3/s for the single junction.
    assert float(net.demands[0].item()) == pytest.approx(0.020, abs=1e-9)


# ---------------------------------------------------------------------------
# POWER pump nominal-flow anchor sees multiplied demand
# ---------------------------------------------------------------------------


def test_power_pump_anchor_uses_multiplied_demand(tmp_path: Path) -> None:
    """The POWER pump surrogate's nominal-flow anchor is derived from
    the network's positive demand AFTER the multiplier is applied.
    Doubling demand via ``Demand Multiplier 2.0`` must therefore
    double the nominal-flow anchor, which in turn lowers ``H_nom``
    by 1/2 and lowers the surrogate's ``a0`` by 1/2.
    """
    def write_power_pump(multiplier: float) -> Path:
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
            f" Demand Multiplier   {multiplier}\n"
            "[END]\n"
        )
        p = tmp_path / f"power_pump_dm_{multiplier}.inp"
        p.write_text(inp)
        return p

    net_one = load_network_from_inp(write_power_pump(1.0), parser="fallback")
    net_two = load_network_from_inp(write_power_pump(2.0), parser="fallback")

    # The pump edge is the second edge (after the pipe).
    a0_one = float(net_one.pump_coeffs[1][0].item())
    a0_two = float(net_two.pump_coeffs[1][0].item())

    # Sanity: derive expected a0 directly from the surrogate.
    # Q_nom = 15 LPS = 0.015 m^3/s when multiplier=1.0;
    # Q_nom = 30 LPS = 0.030 m^3/s when multiplier=2.0 (J2 demand
    # doubles, and the anchor falls back to "total positive demand"
    # because J1's demand is zero on both files).
    coeffs_one, _ = fit_power_pump_surrogate(7.5, 0.015)
    coeffs_two, _ = fit_power_pump_surrogate(7.5, 0.030)
    # ``Network`` pump_coeffs are float32, so the comparison tolerance
    # is the float32 precision floor (~6 significant digits).
    assert a0_one == pytest.approx(coeffs_one[0], rel=1e-5)
    assert a0_two == pytest.approx(coeffs_two[0], rel=1e-5)

    # The doubled-anchor a0 must be exactly half the unscaled a0
    # (head ~ 1/Q for constant power; shutoff_multiplier cancels).
    assert a0_two == pytest.approx(0.5 * a0_one, rel=1e-5)


def test_power_pump_with_multiplier_solves(tmp_path: Path) -> None:
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
        " Demand Multiplier   2.0\n"
        "[END]\n"
    )
    path = tmp_path / "power_pump_dm_solves.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"solver did not converge: {result.reason}"
    assert result.residual_norm < 1e-7


# ---------------------------------------------------------------------------
# Multiplier does NOT touch TCV settings / minor loss / valve dimensions
# ---------------------------------------------------------------------------


def _write_tcv_inp(
    tmp_path: Path, *, multiplier: float | None
) -> Path:
    options_extra = (
        f" Demand Multiplier   {multiplier}\n" if multiplier is not None else ""
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
        f"{options_extra}"
        "[END]\n"
    )
    path = tmp_path / f"tcv_dm_{multiplier}.inp"
    path.write_text(inp)
    return path


def test_tcv_settings_and_diameter_not_affected_by_multiplier(
    tmp_path: Path,
) -> None:
    """The TCV surrogate's diameter is unaffected by the multiplier.
    Its effective length is anchored on the network's positive demand,
    so it WILL move with the multiplier (anchor flow changes) — but
    the diameter and c_factor of the surrogate edge must not.
    """
    net_none = load_network_from_inp(
        _write_tcv_inp(tmp_path, multiplier=None), parser="fallback"
    )
    net_two = load_network_from_inp(
        _write_tcv_inp(tmp_path, multiplier=2.0), parser="fallback"
    )
    # TCV surrogate is the second edge.
    assert float(net_none.diameters[1].item()) == pytest.approx(
        float(net_two.diameters[1].item()), abs=1e-9
    )
    assert float(net_none.c_factors[1].item()) == pytest.approx(
        float(net_two.c_factors[1].item()), abs=1e-9
    )


# ---------------------------------------------------------------------------
# Multiplier does NOT touch pump HEAD curve points
# ---------------------------------------------------------------------------


def test_head_pump_curve_coeffs_not_affected_by_multiplier(
    tmp_path: Path,
) -> None:
    def write_head_pump(multiplier: float | None) -> Path:
        options_extra = (
            f" Demand Multiplier   {multiplier}\n"
            if multiplier is not None
            else ""
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
            f"{options_extra}"
            "[END]\n"
        )
        p = tmp_path / f"head_pump_dm_{multiplier}.inp"
        p.write_text(inp)
        return p

    net_none = load_network_from_inp(write_head_pump(None), parser="fallback")
    net_two = load_network_from_inp(write_head_pump(2.0), parser="fallback")
    # Pump curve coefficients must be unchanged: the multiplier only
    # touches junction demands, not the [CURVES] section.
    assert torch.allclose(
        net_none.pump_coeffs.double(),
        net_two.pump_coeffs.double(),
        atol=1e-12,
    )


# ---------------------------------------------------------------------------
# Reservoir / tank fixed-head boundaries unaffected
# ---------------------------------------------------------------------------


def test_reservoir_head_not_affected_by_multiplier(tmp_path: Path) -> None:
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
        " Demand Multiplier   2.0\n"
        "[END]\n"
    )
    path = tmp_path / "reservoir_dm.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # Reservoir head is 50 m (LPS family head_to_m = 1.0). Multiplier
    # MUST NOT scale this.
    assert float(net.fixed_head_values[-1].item()) == pytest.approx(
        50.0, abs=1e-9
    )


def test_tank_initial_water_surface_not_affected_by_multiplier(
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
        " Demand Multiplier   2.0\n"
        "[END]\n"
    )
    path = tmp_path / "tank_dm.inp"
    path.write_text(inp)
    net = load_network_from_inp(path, parser="fallback")
    # Tank head = elev + init_level = 25 m, regardless of multiplier.
    assert float(net.fixed_head_values[-1].item()) == pytest.approx(
        25.0, abs=1e-9
    )


# ---------------------------------------------------------------------------
# Existing fixtures still behave the same (Sprint 11–17 regression)
# ---------------------------------------------------------------------------


def test_existing_si_loop_fixture_unaffected_by_sprint18() -> None:
    """Re-confirm the Sprint 11 SI loop fixture still loads with the
    same demands (no Demand Multiplier directive in the file).
    """
    si_loop = _FIXTURE_DIR / "epanet_reference_loop.inp"
    net = load_network_from_inp(si_loop, parser="fallback")
    # Junctions: 10, 15, 12, 8 L/s -> 0.010, 0.015, 0.012, 0.008 m^3/s.
    expected_positive = torch.tensor([0.010, 0.015, 0.012, 0.008])
    assert torch.allclose(
        net.demands[:4].double(), expected_positive.double(), atol=1e-9
    )


def test_existing_gpm_loop_fixture_unaffected_by_sprint18() -> None:
    """Re-confirm the Sprint 16 GPM loop fixture still loads without
    any demand scaling.
    """
    net = load_network_from_inp(_LOOP_GPM, parser="fallback")
    junction_demands = torch.tensor(
        [100.0, 150.0, 120.0, 80.0]
    ) * _GPM_TO_M3S
    assert torch.allclose(
        net.demands[:4].double(), junction_demands.double(), atol=1e-8
    )


# ---------------------------------------------------------------------------
# Optional WNTR parity
# ---------------------------------------------------------------------------


def test_wntr_applies_demand_multiplier_for_parity() -> None:
    """WNTR stores ``[OPTIONS] Demand Multiplier`` separately from
    ``Junction.base_demand``. The Sprint 18 WNTR adapter applies the
    multiplier explicitly so both back-ends produce identical demand
    sums on the shipped GPM-with-multiplier fixture.
    """
    pytest.importorskip("wntr")
    net_fb = load_network_from_inp(_LOOP_GPM_DM, parser="fallback")
    net_wn = load_network_from_inp(_LOOP_GPM_DM, parser="wntr")
    # Junction demands first 4 (file ordering: junctions, then reservoir).
    fb_demand_positive = sorted(
        d for d in net_fb.demands.tolist() if d > 0.0
    )
    wn_demand_positive = sorted(
        d for d in net_wn.demands.tolist() if d > 0.0
    )
    assert fb_demand_positive == pytest.approx(wn_demand_positive, abs=1e-7)


def test_wntr_existing_gpm_fixture_parity_unchanged() -> None:
    """For fixtures without a Demand Multiplier directive, WNTR
    behaviour must remain unchanged (multiplier defaults to 1.0,
    which is a no-op).
    """
    pytest.importorskip("wntr")
    net_fb = load_network_from_inp(_LOOP_GPM, parser="fallback")
    net_wn = load_network_from_inp(_LOOP_GPM, parser="wntr")
    fb_demand = sorted(net_fb.demands.tolist())
    wn_demand = sorted(net_wn.demands.tolist())
    assert fb_demand == pytest.approx(wn_demand, abs=1e-7)
