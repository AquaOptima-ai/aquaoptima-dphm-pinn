"""Sprint 26: axis-taxonomy defect fixes (node_status no longer binary)."""
from aquaoptima.dataio.yilan_axis_map import (
    BINARY_AXES,
    CONTINUOUS_AXES,
    CANONICAL_AXIS_TO_COLUMN,
)


def test_node_status_not_binary():
    """DEFECT 1: node_status (tb_system_head, continuous) must NOT be binary."""
    assert "node_status" not in BINARY_AXES
    assert "node_status" in CONTINUOUS_AXES


def test_node_status_still_maps_to_head_column():
    assert CANONICAL_AXIS_TO_COLUMN["node_status"] == "tb_system_head"


def test_eight_active_continuous_axes():
    """edge_valve_position excluded; the other 8 are continuous this sprint."""
    expected = {
        "edge_flow", "edge_power", "edge_pump_speed", "edge_status",
        "node_demand", "node_level", "node_pressure", "node_status",
    }
    assert set(CONTINUOUS_AXES) == expected


def test_binary_axes_empty_or_balanced_gated():
    """DEFECT 2: edge_status dropped as a binary target this sprint (BINARY_AXES empty).

    If a future sprint re-adds a binary axis it must be gated on balanced
    accuracy / F1, never raw accuracy on the 99.85%-imbalanced pump signal.
    """
    assert set(BINARY_AXES) == set()
