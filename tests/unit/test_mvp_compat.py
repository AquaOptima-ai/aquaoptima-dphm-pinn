import json
from pathlib import Path

from aquaoptima_lite.baseline import (
    DemandTarget,
    mvp_input_from_snapshot,
    recommendation_from_mvp_output,
)
from aquaoptima_lite.runtime import snapshot_from_dict

SNAPSHOT = snapshot_from_dict(json.loads(Path("tests/fixtures/snapshots/snapshot_pass.json").read_text()))


def test_mvp_input_from_snapshot_maps_legacy_shape():
    demand = DemandTarget(target_head_m=40.0, flow_min_m3h=80.0, flow_max_m3h=320.0)

    payload = mvp_input_from_snapshot(SNAPSHOT, demand)

    assert payload["system_mode"] == "auto"
    assert payload["sensor_data"]["measured_head"] == 42.8
    assert payload["sensor_data"]["measured_flow"] == 180.5
    assert payload["sensor_data"]["pumpa_on"] == 1
    assert payload["sensor_data"]["pumpa_freq"] == 45.0
    assert payload["demand_info"] == {
        "target_head": 40.0,
        "flow_min": 80.0,
        "flow_max": 320.0,
    }


def test_recommendation_from_mvp_output_maps_setpoints():
    rec = recommendation_from_mvp_output(
        SNAPSHOT,
        {"pumpa_on": True, "pumpa_freq": 46.0, "confidence": 0.9, "write_intent": True},
    )

    assert rec.source == "baseline_mvp"
    assert rec.write_intent is True
    assert rec.confidence == 0.9
    assert rec.pump_setpoints[0].pump_id == "pump_1"
    assert rec.pump_setpoints[0].target_frequency_hz == 46.0
