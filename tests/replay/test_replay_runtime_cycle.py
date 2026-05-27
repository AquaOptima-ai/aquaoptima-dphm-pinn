from pathlib import Path
from typing import cast

from aquaoptima_lite.app.demo import run_demo
from aquaoptima_lite.config import load_site_config
from aquaoptima_lite.ingestion import JsonlReplayAdapter
from aquaoptima_lite.normalization import SnapshotBuilder, map_tags
from aquaoptima_lite.runtime import evaluate_quality

CONFIG_PATH = Path("config/examples/legacy_station_001.yaml")
REPLAY_PATH = Path("tests/fixtures/replay/legacy_station_replay.jsonl")


def test_replay_adapter_reads_four_frames():
    frames = list(JsonlReplayAdapter(REPLAY_PATH))

    assert len(frames) == 4
    assert frames[0].timestamp == "2026-05-26T09:00:00+08:00"
    assert frames[0].tags["pumpa_freq"] == 45.0


def test_tag_mapper_maps_legacy_keys():
    frame = next(iter(JsonlReplayAdapter(REPLAY_PATH)))
    mapped = map_tags(frame.tags)

    assert mapped.station["head_m"] == 42.8
    assert mapped.station["flow_m3h"] == 180.5
    assert mapped.station["auto_mode"] is True
    assert mapped.pumps["pump_1"]["running"] is True
    assert mapped.pumps["pump_1"]["frequency_hz"] == 45.0


def test_snapshot_builder_and_quality_cover_demo_cases():
    config = load_site_config(CONFIG_PATH)
    builder = SnapshotBuilder(config)
    statuses = []
    for frame in JsonlReplayAdapter(REPLAY_PATH):
        snapshot = builder.build(frame)
        statuses.append(evaluate_quality(snapshot, config).status)

    assert statuses == ["pass", "block", "block", "warn"]


def test_run_demo_records_one_audit_row_per_cycle(tmp_path):
    audit_db = tmp_path / "audit.sqlite"
    summary = run_demo(config_path=CONFIG_PATH, replay_path=REPLAY_PATH, cycles=4, audit_db=audit_db)

    assert summary["cycles"] == 4
    assert summary["audit_count"] == 4
    assert audit_db.exists()
    lines = cast(list[str], summary["lines"])
    assert len(lines) == 4
    assert "quality=pass" in lines[0]
    assert "quality=warn" in lines[3]
