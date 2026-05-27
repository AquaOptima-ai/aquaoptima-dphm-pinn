import json
from pathlib import Path

import pytest

from aquaoptima_lite.runtime import PumpState, StationSnapshot, snapshot_from_dict

FIXTURE_DIR = Path("tests/fixtures/snapshots")


def load_fixture(name: str) -> StationSnapshot:
    return snapshot_from_dict(json.loads((FIXTURE_DIR / name).read_text()))


def test_snapshot_fixture_parses_to_frozen_dataclass():
    snapshot = load_fixture("snapshot_pass.json")

    assert snapshot.site_id == "legacy_station_001"
    assert snapshot.mode == "baseline_plus_learning_shadow"
    assert snapshot.auto_mode is True
    assert snapshot.manual_mode is False
    assert snapshot.flow_m3h == 180.5
    assert len(snapshot.pumps) == 2
    assert snapshot.pumps[0].pump_id == "pump_1"
    assert snapshot.pumps[0].frequency_hz == 45.0

    with pytest.raises(Exception):
        snapshot.site_id = "mutated"  # type: ignore[misc]


def test_snapshot_requires_core_fields():
    with pytest.raises(ValueError, match="snapshot missing required fields"):
        snapshot_from_dict({"site_id": "legacy_station_001"})


def test_pump_state_preserves_optional_values():
    pump = PumpState(
        pump_id="p",
        running=False,
        available=True,
        frequency_hz=None,
        trip_active=False,
        alarm_active=False,
    )
    assert pump.frequency_hz is None
    assert pump.flow_m3h is None
