"""Sprint 16 — EPANET unit-system manifest and US-customary parsing.

The fallback parser uses an internal :class:`EpanetUnitSystem` manifest
to capture the per-flow-unit conventions EPANET applies to pipe
length, diameter, head/elevation, and demand. Sprint 16 extends the
fallback to the five US-customary flow units (``GPM``, ``CFS``,
``MGD``, ``IMGD``, ``AFD``) on top of the five SI units (``LPS``,
``LPM``, ``MLD``, ``CMH``, ``CMD``).

These tests pin every supported conversion constant to a documented
source (NIST conversion factors / EPANET user manual section 4.2)
plus exercise the parser surface for case-insensitive ``Units``
parsing and the unsupported-unit ValueError path.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from aquaoptima.dphm.inp_io import (
    EpanetUnitSystem,
    SUPPORTED_FLOW_UNITS,
    resolve_unit_system,
)


# Authoritative conversion-factor expectations. These are the
# arithmetic anchors the parser is allowed to round into; if any of
# these constants drift, the Sprint 16 manifest is broken.
_FT_TO_M = 0.3048
_IN_TO_M = 0.0254
_US_GAL_TO_M3 = 0.003785411784  # exact, per NIST HB-44
_IMP_GAL_TO_M3 = 0.00454609     # exact, per UK Weights & Measures Act
_ACRE_FOOT_TO_M3 = 1233.48183754752  # exact, derived from US-survey-foot acre
_DAY_S = 86_400.0
_MIN_S = 60.0


@pytest.mark.parametrize(
    "unit_name, flow_to_m3s, length_to_m, diameter_to_m, head_to_m, pressure_setting_to_m",
    [
        # SI family — length in metres, diameter in millimetres,
        # head/elevation in metres.
        ("LPS", 1.0e-3,                 1.0,     1.0e-3, 1.0, 1.0),
        ("LPM", 1.0 / 60_000.0,          1.0,     1.0e-3, 1.0, 1.0),
        ("MLD", 1_000.0 / 86_400.0,      1.0,     1.0e-3, 1.0, 1.0),
        ("CMH", 1.0 / 3600.0,            1.0,     1.0e-3, 1.0, 1.0),
        ("CMD", 1.0 / 86_400.0,          1.0,     1.0e-3, 1.0, 1.0),
        # US-customary family — length in feet, diameter in inches,
        # head/elevation in feet.
        ("CFS", 0.028316846592,                                _FT_TO_M, _IN_TO_M, _FT_TO_M, _FT_TO_M),
        ("GPM", _US_GAL_TO_M3 / _MIN_S,                        _FT_TO_M, _IN_TO_M, _FT_TO_M, _FT_TO_M),
        ("MGD", 1_000_000.0 * _US_GAL_TO_M3 / _DAY_S,           _FT_TO_M, _IN_TO_M, _FT_TO_M, _FT_TO_M),
        ("IMGD", 1_000_000.0 * _IMP_GAL_TO_M3 / _DAY_S,         _FT_TO_M, _IN_TO_M, _FT_TO_M, _FT_TO_M),
        ("AFD", _ACRE_FOOT_TO_M3 / _DAY_S,                      _FT_TO_M, _IN_TO_M, _FT_TO_M, _FT_TO_M),
    ],
)
def test_unit_manifest_constants_match_documented_values(
    unit_name: str,
    flow_to_m3s: float,
    length_to_m: float,
    diameter_to_m: float,
    head_to_m: float,
    pressure_setting_to_m: float,
) -> None:
    sys = resolve_unit_system(unit_name)
    assert isinstance(sys, EpanetUnitSystem)
    assert sys.units == unit_name
    assert sys.flow_to_m3s == pytest.approx(flow_to_m3s, rel=1e-12, abs=1e-18)
    assert sys.length_to_m == pytest.approx(length_to_m, rel=1e-12, abs=1e-18)
    assert sys.diameter_to_m == pytest.approx(diameter_to_m, rel=1e-12, abs=1e-18)
    assert sys.head_to_m == pytest.approx(head_to_m, rel=1e-12, abs=1e-18)
    assert sys.pressure_setting_to_m == pytest.approx(
        pressure_setting_to_m, rel=1e-12, abs=1e-18
    )


def test_supported_flow_units_lists_every_documented_unit() -> None:
    expected = {"LPS", "LPM", "MLD", "CMH", "CMD",
                "GPM", "CFS", "MGD", "IMGD", "AFD"}
    assert set(SUPPORTED_FLOW_UNITS) == expected


def test_resolve_unit_system_is_case_insensitive() -> None:
    upper = resolve_unit_system("GPM")
    lower = resolve_unit_system("gpm")
    mixed = resolve_unit_system("Gpm")
    assert upper.units == "GPM" == lower.units == mixed.units
    assert upper.flow_to_m3s == lower.flow_to_m3s == mixed.flow_to_m3s


def test_resolve_unit_system_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="unknown EPANET flow unit"):
        resolve_unit_system("BARRELS")


def test_resolve_unit_system_rejects_known_but_unsupported_aliases() -> None:
    # ``CMS`` was previously in the SI table but is not a real
    # EPANET-recognised token; Sprint 16 narrows the table to the ten
    # documented EPANET units.
    with pytest.raises(ValueError, match="unknown EPANET flow unit"):
        resolve_unit_system("CMS")


def test_us_flow_unit_factors_match_si_equivalents_at_round_numbers() -> None:
    """Sanity-check: 1 CFS ≈ 28.316846592 L/s, etc."""
    cfs = resolve_unit_system("CFS").flow_to_m3s
    lps = resolve_unit_system("LPS").flow_to_m3s
    assert cfs / lps == pytest.approx(28.316846592, rel=1e-12)

    gpm = resolve_unit_system("GPM").flow_to_m3s
    # 1 GPM = 6.30901964e-5 m^3/s
    assert gpm == pytest.approx(6.30901964e-5, rel=1e-9)

    mgd = resolve_unit_system("MGD").flow_to_m3s
    # 1 MGD = 0.0438125636 m^3/s (US)
    assert mgd == pytest.approx(0.04381263638889, rel=1e-9)

    imgd = resolve_unit_system("IMGD").flow_to_m3s
    # 1 IMGD = 0.0526168 m^3/s
    assert imgd == pytest.approx(0.05261678240741, rel=1e-9)

    afd = resolve_unit_system("AFD").flow_to_m3s
    # 1 AFD = 1233.48183754752 / 86400 = 0.014276410157 m^3/s
    assert afd == pytest.approx(0.014276410156823, rel=1e-9)
