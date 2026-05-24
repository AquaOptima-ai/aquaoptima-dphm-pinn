"""Sprint 15 — WNTR valve translation helpers.

These tests exercise the pure-Python helpers
:func:`aquaoptima.dphm.inp_io._wntr_extract_valve_fields` and
:func:`aquaoptima.dphm.inp_io._wntr_translate_valve` against
duck-typed fakes that mimic WNTR's public valve API surface. None of
these tests import WNTR, so they run in the default test suite even
when the optional ``wntr`` dependency is missing.

Why fakes? WNTR's Valve API has shifted across releases (e.g.
``initial_setting`` vs ``setting``); our adapter is written against
the *stable* public surface and tolerates either attribute name.
Fakes let us pin that contract explicitly under test without forcing
a dependency on any specific WNTR version.
"""

from __future__ import annotations

import math

import pytest

from aquaoptima.dphm import (
    fit_tcv_resistance_surrogate,
    translate_valve_to_surrogate,
)
from aquaoptima.dphm.inp_io import (
    _wntr_extract_valve_fields,
    _wntr_translate_valve,
)


# ---------------------------------------------------------------------------
# fakes — minimal WNTR-shaped duck types
# ---------------------------------------------------------------------------


class _FakeValve:
    """Mimic the subset of ``wntr.network.elements.Valve`` we read.

    Exposes both ``initial_setting`` and ``setting`` so the
    extractor's preference (``initial_setting`` first) is testable.
    """

    def __init__(
        self,
        *,
        valve_type="PRV",
        diameter=0.15,
        initial_setting=20.0,
        setting=None,
        minor_loss=0.0,
        start_node_name="J1",
        end_node_name="J2",
        name="V1",
    ):
        self.valve_type = valve_type
        self.diameter = diameter
        if initial_setting is not None:
            self.initial_setting = initial_setting
        if setting is not None:
            self.setting = setting
        self.minor_loss = minor_loss
        self.start_node_name = start_node_name
        self.end_node_name = end_node_name
        self.name = name


# ---------------------------------------------------------------------------
# _wntr_extract_valve_fields
# ---------------------------------------------------------------------------


def test_extract_valve_fields_returns_canonical_shape() -> None:
    v = _FakeValve(valve_type="PRV", diameter=0.15, initial_setting=20.0, minor_loss=0.0)
    fields = _wntr_extract_valve_fields(v)
    assert fields == {
        "valve_type": "PRV",
        "diameter_m": 0.15,
        "setting": 20.0,
        "minor_loss": 0.0,
        "start_node_name": "J1",
        "end_node_name": "J2",
    }


def test_extract_valve_fields_normalises_valve_type_case() -> None:
    v = _FakeValve(valve_type="tcv")
    fields = _wntr_extract_valve_fields(v)
    assert fields["valve_type"] == "TCV"


def test_extract_valve_fields_prefers_initial_setting_over_setting() -> None:
    v = _FakeValve(initial_setting=20.0, setting=99.0)
    assert _wntr_extract_valve_fields(v)["setting"] == pytest.approx(20.0)


def test_extract_valve_fields_falls_back_to_setting_attr() -> None:
    class _OldStyle:
        valve_type = "PRV"
        diameter = 0.10
        setting = 15.0
        minor_loss = 0.0
        start_node_name = "J1"
        end_node_name = "J2"

    fields = _wntr_extract_valve_fields(_OldStyle())
    assert fields["setting"] == pytest.approx(15.0)


def test_extract_valve_fields_rejects_missing_valve_type() -> None:
    class _Bare:
        diameter = 0.1
        initial_setting = 1.0

    with pytest.raises(ValueError, match="valve_type"):
        _wntr_extract_valve_fields(_Bare())


def test_extract_valve_fields_rejects_missing_diameter() -> None:
    class _NoDia:
        valve_type = "PRV"
        initial_setting = 1.0

    with pytest.raises(ValueError, match="diameter"):
        _wntr_extract_valve_fields(_NoDia())


def test_extract_valve_fields_rejects_non_numeric_diameter() -> None:
    v = _FakeValve(diameter="nope")
    with pytest.raises(ValueError, match="non-numeric diameter"):
        _wntr_extract_valve_fields(v)


def test_extract_valve_fields_rejects_non_positive_diameter() -> None:
    v = _FakeValve(diameter=0.0)
    with pytest.raises(ValueError, match="non-positive"):
        _wntr_extract_valve_fields(v)
    v2 = _FakeValve(diameter=-0.1)
    with pytest.raises(ValueError, match="non-positive"):
        _wntr_extract_valve_fields(v2)


def test_extract_valve_fields_rejects_non_finite_diameter() -> None:
    v = _FakeValve(diameter=float("inf"))
    with pytest.raises(ValueError, match="non-positive or non-finite"):
        _wntr_extract_valve_fields(v)


def test_extract_valve_fields_rejects_non_numeric_setting() -> None:
    v = _FakeValve(initial_setting="oops")
    with pytest.raises(ValueError, match="non-numeric setting"):
        _wntr_extract_valve_fields(v)


def test_extract_valve_fields_tolerates_none_minor_loss() -> None:
    v = _FakeValve(minor_loss=None)
    fields = _wntr_extract_valve_fields(v)
    assert fields["minor_loss"] == pytest.approx(0.0)


def test_extract_valve_fields_rejects_missing_endpoints() -> None:
    class _NoEnds:
        valve_type = "PRV"
        diameter = 0.1
        initial_setting = 10.0
        minor_loss = 0.0

    with pytest.raises(ValueError, match="start/end node names"):
        _wntr_extract_valve_fields(_NoEnds())


# ---------------------------------------------------------------------------
# _wntr_translate_valve — PRV
# ---------------------------------------------------------------------------


def test_translate_valve_prv_pins_downstream() -> None:
    v = _FakeValve(valve_type="PRV", diameter=0.10, initial_setting=25.0)
    desc = _wntr_translate_valve(
        v, valve_id="V1", downstream_elev_m=5.0, total_positive_demand=0.01
    )
    assert desc["valve_type"] == "PRV"
    assert desc["downstream_fixed_head_m"] == pytest.approx(30.0)
    assert desc["start_node_name"] == "J1"
    assert desc["end_node_name"] == "J2"
    assert desc["diagnostics"]["valve_id"] == "V1"
    assert desc["diagnostics"]["approximation"] == "prv_pressure_boundary_surrogate"


def test_translate_valve_prv_uses_valve_name_when_id_omitted() -> None:
    v = _FakeValve(valve_type="PRV", initial_setting=20.0, name="VALV_NAME")
    desc = _wntr_translate_valve(v, downstream_elev_m=0.0)
    assert desc["diagnostics"]["valve_id"] == "VALV_NAME"


# ---------------------------------------------------------------------------
# _wntr_translate_valve — TCV
# ---------------------------------------------------------------------------


def test_translate_valve_tcv_matches_fit_helper() -> None:
    """TCV path delegates to ``fit_tcv_resistance_surrogate``."""
    v = _FakeValve(
        valve_type="TCV",
        diameter=0.15,
        initial_setting=2.5,
        minor_loss=0.0,
    )
    desc = _wntr_translate_valve(
        v, valve_id="V1", total_positive_demand=0.015
    )
    expected_params, _expected_diag = fit_tcv_resistance_surrogate(
        diameter_m=0.15, setting_k=2.5, nominal_flow_m3s=0.015
    )
    assert desc["pipe_params"]["length_m"] == pytest.approx(
        expected_params["length_m"], rel=1e-9
    )
    assert desc["pipe_params"]["diameter_m"] == pytest.approx(0.15)
    assert desc["downstream_fixed_head_m"] is None
    assert desc["diagnostics"]["valve_id"] == "V1"
    assert desc["diagnostics"]["approximation"] == "tcv_resistance_surrogate"


def test_translate_valve_tcv_falls_back_to_default_nominal_flow() -> None:
    """Zero total_positive_demand -> 1 L/s default anchor."""
    v = _FakeValve(valve_type="TCV", diameter=0.15, initial_setting=2.5)
    desc = _wntr_translate_valve(v, valve_id="V1")
    assert desc["diagnostics"]["nominal_flow_m3s"] == pytest.approx(1.0e-3)


def test_translate_valve_tcv_with_extra_minor_loss() -> None:
    """``minor_loss`` column adds to ``setting_k`` in the surrogate."""
    v = _FakeValve(
        valve_type="TCV",
        diameter=0.15,
        initial_setting=2.5,
        minor_loss=1.5,
    )
    desc = _wntr_translate_valve(
        v, valve_id="V1", total_positive_demand=0.015
    )
    expected_params, _ = fit_tcv_resistance_surrogate(
        diameter_m=0.15, setting_k=2.5,
        nominal_flow_m3s=0.015, minor_loss=1.5,
    )
    assert desc["pipe_params"]["length_m"] == pytest.approx(
        expected_params["length_m"], rel=1e-9
    )


# ---------------------------------------------------------------------------
# _wntr_translate_valve — error paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("vtype", ["FCV", "PSV", "PBV", "GPV"])
def test_translate_valve_rejects_unsupported(vtype: str) -> None:
    v = _FakeValve(valve_type=vtype, diameter=0.15, initial_setting=1.0)
    with pytest.raises(ValueError, match="unsupported valve type"):
        _wntr_translate_valve(v, valve_id="V1", total_positive_demand=0.015)


def test_translate_valve_propagates_translator_errors() -> None:
    """A non-positive PRV setting must surface as a clear ValueError."""
    v = _FakeValve(valve_type="PRV", diameter=0.1, initial_setting=-1.0)
    with pytest.raises(ValueError, match="setting"):
        _wntr_translate_valve(v, valve_id="V1")


def test_translate_valve_propagates_extract_errors() -> None:
    """Non-numeric diameter on the fake must surface as ValueError."""
    v = _FakeValve(diameter="bad")
    with pytest.raises(ValueError, match="diameter"):
        _wntr_translate_valve(v, valve_id="V1")


# ---------------------------------------------------------------------------
# Cross-check: WNTR translator agrees with direct translate call
# ---------------------------------------------------------------------------


def test_wntr_and_direct_translator_agree_on_prv() -> None:
    v = _FakeValve(
        valve_type="PRV",
        diameter=0.10,
        initial_setting=25.0,
        minor_loss=0.0,
    )
    via_wntr = _wntr_translate_valve(
        v, valve_id="V1", downstream_elev_m=5.0
    )
    direct = translate_valve_to_surrogate(
        valve_id="V1",
        valve_type="PRV",
        diameter_m=0.10,
        setting=25.0,
        downstream_elev_m=5.0,
    )
    assert via_wntr["downstream_fixed_head_m"] == pytest.approx(
        direct["downstream_fixed_head_m"]
    )
    assert via_wntr["pipe_params"] == direct["pipe_params"]


def test_wntr_and_direct_translator_agree_on_tcv() -> None:
    v = _FakeValve(
        valve_type="TCV",
        diameter=0.15,
        initial_setting=2.5,
        minor_loss=0.5,
    )
    via_wntr = _wntr_translate_valve(
        v, valve_id="V1", total_positive_demand=0.015
    )
    direct = translate_valve_to_surrogate(
        valve_id="V1",
        valve_type="TCV",
        diameter_m=0.15,
        setting=2.5,
        minor_loss=0.5,
        nominal_flow_m3s=0.015,
    )
    assert via_wntr["pipe_params"]["length_m"] == pytest.approx(
        direct["pipe_params"]["length_m"], rel=1e-9
    )
