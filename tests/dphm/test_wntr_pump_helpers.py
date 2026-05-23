"""Sprint 13 — WNTR pump translation helpers.

These tests exercise the pure-Python helpers
:func:`aquaoptima.dphm.inp_io._wntr_extract_pump_curve_points` and
:func:`aquaoptima.dphm.inp_io._wntr_translate_pump` against
duck-typed fakes that mimic WNTR's public pump/curve API surface.
None of these tests import WNTR, so they run in the default test
suite even when the optional ``wntr`` dependency is missing.

Why fakes? WNTR's API has shifted slightly across releases, and our
adapter is intentionally written against the *stable* public surface
(``pump_type``, ``get_pump_curve()``, ``Curve.points``,
``Curve.curve_type``). Fakes let us encode that contract explicitly
and pin it under test.
"""

from __future__ import annotations

import pytest

from aquaoptima.dphm import fit_pump_head_curve
from aquaoptima.dphm.inp_io import (
    _wntr_extract_pump_curve_points,
    _wntr_translate_pump,
)


# ---------------------------------------------------------------------------
# fakes — minimal WNTR-shaped duck types
# ---------------------------------------------------------------------------


class _FakeCurve:
    """Mimic the subset of ``wntr.network.elements.Curve`` we read."""

    def __init__(self, points, curve_type="HEAD"):
        self.points = list(points)
        self.curve_type = curve_type


class _FakeHeadPump:
    """Mimic the subset of ``wntr.network.elements.HeadPump`` we read."""

    def __init__(self, curve, base_speed=1.0, pump_type="HEAD"):
        self.pump_type = pump_type
        self._curve = curve
        self.base_speed = base_speed
        self.start_node_name = "R1"
        self.end_node_name = "J1"

    def get_pump_curve(self):
        return self._curve


class _FakePowerPump:
    """Mimic the subset of ``wntr.network.elements.PowerPump`` we read."""

    def __init__(self, power=5000.0):
        self.pump_type = "POWER"
        self.power = power
        self.base_speed = 1.0
        self.start_node_name = "R1"
        self.end_node_name = "J1"


# ---------------------------------------------------------------------------
# _wntr_extract_pump_curve_points
# ---------------------------------------------------------------------------


def test_extract_returns_points_unchanged_in_si() -> None:
    """WNTR delivers SI points; our helper must NOT apply demand_factor."""
    # WNTR-style SI curve: H = 45 - 800 Q^2 at Q in m^3/s.
    si_points = [(0.0, 45.0), (0.01, 44.92), (0.02, 44.68), (0.05, 43.0)]
    pump = _FakeHeadPump(_FakeCurve(si_points))
    got = _wntr_extract_pump_curve_points(pump)
    assert got == si_points


def test_extract_accepts_curve_with_no_curve_type() -> None:
    """Older WNTR may omit Curve.curve_type; our extractor tolerates None."""
    si_points = [(0.0, 45.0), (0.02, 44.68), (0.05, 43.0)]
    pump = _FakeHeadPump(_FakeCurve(si_points, curve_type=None))
    got = _wntr_extract_pump_curve_points(pump)
    assert got == si_points


def test_extract_rejects_non_head_curve_type() -> None:
    pump = _FakeHeadPump(_FakeCurve([(0, 1), (1, 2), (2, 3)], curve_type="EFFICIENCY"))
    with pytest.raises(ValueError, match="EFFICIENCY"):
        _wntr_extract_pump_curve_points(pump)


def test_extract_rejects_power_pump() -> None:
    pump = _FakePowerPump()
    with pytest.raises(ValueError, match="POWER"):
        _wntr_extract_pump_curve_points(pump)


def test_extract_rejects_unknown_pump_type() -> None:
    pump = _FakeHeadPump(_FakeCurve([(0, 1)]), pump_type="LINEAR")
    with pytest.raises(ValueError, match="LINEAR"):
        _wntr_extract_pump_curve_points(pump)


def test_extract_rejects_pump_without_pump_type() -> None:
    class _BarePump:
        start_node_name = "R1"
        end_node_name = "J1"

    with pytest.raises(ValueError, match="pump_type"):
        _wntr_extract_pump_curve_points(_BarePump())


def test_extract_rejects_pump_missing_get_pump_curve() -> None:
    class _MissingCurveAccessor:
        pump_type = "HEAD"
        base_speed = 1.0

    with pytest.raises(ValueError, match="get_pump_curve"):
        _wntr_extract_pump_curve_points(_MissingCurveAccessor())


def test_extract_rejects_empty_curve() -> None:
    pump = _FakeHeadPump(_FakeCurve([]))
    with pytest.raises(ValueError, match="no points"):
        _wntr_extract_pump_curve_points(pump)


def test_extract_rejects_malformed_curve_point() -> None:
    pump = _FakeHeadPump(_FakeCurve([(0.0, 45.0), ("nan_x", 44.0), (0.05, 43.0)]))
    with pytest.raises(ValueError, match="malformed"):
        _wntr_extract_pump_curve_points(pump)


def test_extract_propagates_get_pump_curve_error() -> None:
    class _ThrowingPump:
        pump_type = "HEAD"
        base_speed = 1.0
        start_node_name = "R1"
        end_node_name = "J1"

        def get_pump_curve(self):
            raise RuntimeError("WNTR internal failure")

    with pytest.raises(ValueError, match="RuntimeError"):
        _wntr_extract_pump_curve_points(_ThrowingPump())


# ---------------------------------------------------------------------------
# _wntr_translate_pump
# ---------------------------------------------------------------------------


def test_translate_matches_fit_pump_head_curve_on_si_points() -> None:
    """Reusing fit_pump_head_curve must yield equivalent coefficients.

    ``torch.linalg.lstsq`` is not bit-for-bit reproducible across
    separate calls (sub-ulp differences in BLAS round-off), so we
    compare with a tight absolute tolerance rather than asserting
    exact list equality.
    """
    si_points = [(q, 45.0 - 800.0 * q * q) for q in (0.0, 0.01, 0.02, 0.03, 0.04, 0.05)]
    pump = _FakeHeadPump(_FakeCurve(si_points), base_speed=1.0)
    coeffs, base_speed, diag = _wntr_translate_pump(pump)

    expected_coeffs, expected_diag = fit_pump_head_curve(si_points)
    assert coeffs == pytest.approx(expected_coeffs, abs=1e-9)
    # Diagnostic floats agree to the same tolerance; comparing dicts
    # directly would inherit the same lstsq round-off issue.
    for key, expected_val in expected_diag.items():
        assert diag[key] == pytest.approx(expected_val, abs=1e-9), key
    assert base_speed == pytest.approx(1.0)


def test_translate_preserves_non_unity_base_speed() -> None:
    si_points = [(0.0, 45.0), (0.02, 44.68), (0.05, 43.0)]
    pump = _FakeHeadPump(_FakeCurve(si_points), base_speed=0.85)
    _, base_speed, _ = _wntr_translate_pump(pump)
    assert base_speed == pytest.approx(0.85)


def test_translate_defaults_base_speed_when_missing() -> None:
    class _NoSpeed:
        pump_type = "HEAD"
        start_node_name = "R1"
        end_node_name = "J1"

        def get_pump_curve(self):
            return _FakeCurve([(0.0, 45.0), (0.02, 44.68), (0.05, 43.0)])

    _, base_speed, _ = _wntr_translate_pump(_NoSpeed())
    assert base_speed == pytest.approx(1.0)


def test_translate_defaults_base_speed_on_non_finite_value() -> None:
    pump = _FakeHeadPump(
        _FakeCurve([(0.0, 45.0), (0.02, 44.68), (0.05, 43.0)]),
        base_speed=float("nan"),
    )
    _, base_speed, _ = _wntr_translate_pump(pump)
    assert base_speed == pytest.approx(1.0)


def test_translate_defaults_base_speed_on_negative_value() -> None:
    pump = _FakeHeadPump(
        _FakeCurve([(0.0, 45.0), (0.02, 44.68), (0.05, 43.0)]),
        base_speed=-0.5,
    )
    _, base_speed, _ = _wntr_translate_pump(pump)
    assert base_speed == pytest.approx(1.0)


def test_translate_propagates_fit_errors() -> None:
    """A degenerate curve must surface as a clear ValueError."""
    pump = _FakeHeadPump(_FakeCurve([(0.0, 45.0), (0.02, 44.68)]))  # only 2 pts
    with pytest.raises(ValueError, match="at least 3 points"):
        _wntr_translate_pump(pump)
