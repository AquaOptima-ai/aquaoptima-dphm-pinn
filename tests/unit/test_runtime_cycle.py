import json
from pathlib import Path

from aquaoptima_lite.app import RuntimeCycle
from aquaoptima_lite.config import load_site_config
from aquaoptima_lite.runtime import snapshot_from_dict

SNAPSHOT = snapshot_from_dict(json.loads(Path("tests/fixtures/snapshots/snapshot_pass.json").read_text()))
CONFIG = load_site_config("config/examples/legacy_station_001.yaml")


def test_runtime_cycle_records_latest_state():
    cycle = RuntimeCycle(config=CONFIG)

    result = cycle.run(SNAPSHOT)
    state = cycle.latest_state()

    assert result.audit_id == 1
    assert result.quality.status == "pass"
    assert state["status"]["has_cycle"] is True
    assert state["snapshot"].site_id == SNAPSHOT.site_id
    assert state["recommendation"].source == "baseline_fallback"
