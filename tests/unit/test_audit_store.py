import json
from pathlib import Path

from aquaoptima_lite.baseline import FallbackBaselineEngine, default_demand_target
from aquaoptima_lite.config import load_site_config
from aquaoptima_lite.runtime import ControlIntent, evaluate_authority, evaluate_quality, snapshot_from_dict
from aquaoptima_lite.storage import SQLiteAuditStore

SNAPSHOT = snapshot_from_dict(json.loads(Path("tests/fixtures/snapshots/snapshot_pass.json").read_text()))
CONFIG = load_site_config("config/examples/legacy_station_001.yaml")


def test_sqlite_audit_store_records_cycle_payloads():
    quality = evaluate_quality(SNAPSHOT, CONFIG)
    rec = FallbackBaselineEngine().recommend(SNAPSHOT, default_demand_target())
    authority = evaluate_authority(
        SNAPSHOT,
        quality,
        ControlIntent(source="none", write_requested=False),
        CONFIG,
    )

    with SQLiteAuditStore() as store:
        row_id = store.record_cycle(
            site_id=SNAPSHOT.site_id,
            runtime_mode=SNAPSHOT.mode,
            config_hash=SNAPSHOT.config_hash,
            snapshot=SNAPSHOT,
            quality=quality,
            recommendation=rec,
            authority=authority,
            created_at="2026-05-26T00:00:00+00:00",
        )

        assert row_id == 1
        assert store.count() == 1
        latest = store.latest(SNAPSHOT.site_id)
        assert latest is not None
        assert latest.site_id == SNAPSHOT.site_id
        assert latest.snapshot["site_id"] == SNAPSHOT.site_id
        assert latest.quality["status"] == quality.status
        assert latest.recommendation["source"] == rec.source
        assert latest.authority["decision"] == authority.decision
