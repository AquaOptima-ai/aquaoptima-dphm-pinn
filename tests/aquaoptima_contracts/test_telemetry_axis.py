"""TDD — ``TelemetryAxis`` canonical axis token enum (Sprint 42).

Acceptance: every Phase 1 canonical axis is in the SDK projection.
The SDK never absorbs the runtime Network-dimension validation —
``TelemetryAxis`` is a pure token vocabulary.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    CANONICAL_TELEMETRY_AXES,
    ContractError,
    TelemetryAxis,
)


def test_phase1_axes_are_all_in_sdk_vocabulary() -> None:
    expected = {
        "node_pressure",
        "node_demand",
        "node_level",
        "node_status",
        "edge_flow",
        "edge_pump_speed",
        "edge_status",
        "edge_power",
        "edge_valve_position",
    }
    assert expected.issubset(CANONICAL_TELEMETRY_AXES)


def test_telemetry_axis_round_trips_through_canonical_json() -> None:
    axis = TelemetryAxis("node_pressure")
    assert axis.value == "node_pressure"
    assert axis.to_dict() == {"value": "node_pressure"}
    restored = TelemetryAxis.from_dict({"value": "node_pressure"})
    assert restored == axis


def test_telemetry_axis_rejects_unknown_token() -> None:
    with pytest.raises(ContractError):
        TelemetryAxis("not_an_axis")


def test_telemetry_axis_rejects_non_string() -> None:
    with pytest.raises(ContractError):
        TelemetryAxis(value=123)  # type: ignore[arg-type]


@pytest.mark.parametrize("axis_value", sorted(CANONICAL_TELEMETRY_AXES))
def test_every_canonical_axis_constructs(axis_value: str) -> None:
    assert TelemetryAxis(axis_value).value == axis_value


def test_telemetry_axis_is_hashable() -> None:
    a = TelemetryAxis("edge_flow")
    b = TelemetryAxis("edge_flow")
    assert {a, b} == {a}
