import json
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None

from aquaoptima_lite.api import create_app
from aquaoptima_lite.app import RuntimeCycle
from aquaoptima_lite.config import load_site_config
from aquaoptima_lite.runtime import snapshot_from_dict


def test_create_app_without_state_provider():
    app = create_app()
    assert app is not None


def test_api_serves_latest_runtime_state():
    if TestClient is None:
        return
    config = load_site_config("config/examples/legacy_station_001.yaml")
    snapshot = snapshot_from_dict(json.loads(Path("tests/fixtures/snapshots/snapshot_pass.json").read_text()))
    cycle = RuntimeCycle(config=config)
    cycle.run(snapshot)
    client = TestClient(create_app(cycle))

    status = client.get("/status")
    assert status.status_code == 200
    assert status.json()["has_cycle"] is True

    rec = client.get("/recommendation/current")
    assert rec.status_code == 200
    assert rec.json()["source"] == "baseline_fallback"

    quality = client.get("/quality/current")
    assert quality.status_code == 200
    assert quality.json()["status"] == "pass"

    snap = client.get("/snapshot/current")
    assert snap.status_code == 200
    assert snap.json()["site_id"] == "legacy_station_001"
