"""Tests for the feasibility checker."""

import torch

from aquaoptima.dphm.feasibility import FeasibilityResult, check_feasibility


def test_empty_call_is_ok():
    result = check_feasibility()
    assert isinstance(result, FeasibilityResult)
    assert result.ok is True
    assert result.violations == []


def test_pressure_in_bounds_is_ok():
    pressures = torch.tensor([20.0, 30.0, 40.0])
    result = check_feasibility(pressures=pressures, pressure_min=15.0, pressure_max=60.0)
    assert result.ok
    assert result.violations == []


def test_pressure_below_minimum_recorded():
    pressures = torch.tensor([10.0, 30.0, 40.0])
    result = check_feasibility(pressures=pressures, pressure_min=15.0, pressure_max=60.0)
    assert not result.ok
    assert any("pressure" in v and "min" in v for v in result.violations)


def test_pressure_above_maximum_recorded():
    pressures = torch.tensor([20.0, 70.0])
    result = check_feasibility(pressures=pressures, pressure_min=15.0, pressure_max=60.0)
    assert not result.ok
    assert any("pressure" in v and "max" in v for v in result.violations)


def test_pump_speed_out_of_range_recorded():
    speeds = torch.tensor([0.5, 1.6])
    result = check_feasibility(
        pump_speeds=speeds, pump_speed_min=0.0, pump_speed_max=1.5
    )
    assert not result.ok
    assert any("pump_speed" in v for v in result.violations)


def test_flow_magnitude_violation_recorded():
    flows = torch.tensor([0.1, -0.4])
    result = check_feasibility(flows=flows, max_abs_flow=0.3)
    assert not result.ok
    assert any("flow" in v for v in result.violations)


def test_skips_constraint_when_arg_is_none():
    # If pressures provided but neither pressure_min nor pressure_max set, no checks run.
    pressures = torch.tensor([-1000.0, 99999.0])
    result = check_feasibility(pressures=pressures)
    assert result.ok
    assert result.violations == []


def test_multiple_violations_accumulated():
    pressures = torch.tensor([5.0])
    speeds = torch.tensor([2.0])
    flows = torch.tensor([10.0])
    result = check_feasibility(
        pressures=pressures,
        pressure_min=15.0,
        pressure_max=60.0,
        pump_speeds=speeds,
        pump_speed_min=0.0,
        pump_speed_max=1.5,
        flows=flows,
        max_abs_flow=1.0,
    )
    assert not result.ok
    # At least one violation per category.
    assert any("pressure" in v for v in result.violations)
    assert any("pump_speed" in v for v in result.violations)
    assert any("flow" in v for v in result.violations)
