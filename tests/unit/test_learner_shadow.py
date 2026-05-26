from pathlib import Path

from aquaoptima_lite.app.demo import run_demo
from aquaoptima_lite.baseline import default_demand_target
from aquaoptima_lite.config import load_site_config
from aquaoptima_lite.ingestion import JsonlReplayAdapter
from aquaoptima_lite.learner import LearnerSampleCollector, LearnerShadowService
from aquaoptima_lite.normalization import SnapshotBuilder
from aquaoptima_lite.runtime import evaluate_quality
from aquaoptima_lite.storage import SQLiteAuditStore

CONFIG_PATH = Path("config/examples/legacy_station_001.yaml")
REPLAY_PATH = Path("tests/fixtures/replay/legacy_station_replay.jsonl")


def _replay_results():
    config = load_site_config(CONFIG_PATH)
    builder = SnapshotBuilder(config)
    demand = default_demand_target()
    results = []
    for frame in JsonlReplayAdapter(REPLAY_PATH):
        snapshot = builder.build(frame)
        quality = evaluate_quality(snapshot, config)
        results.append((snapshot, quality, demand))
    return results


def test_collector_accepts_only_clean_running_pump_combo_samples():
    collector = LearnerSampleCollector(min_samples_for_shadow=2)
    decisions = [collector.collect(*items) for items in _replay_results()]

    assert [d.accepted for d in decisions] == [True, False, False, False]
    assert decisions[0].sample is not None
    assert decisions[0].sample.combo_key == "pump_1"
    assert decisions[0].sample.total_flow_m3h == 180.5
    assert decisions[0].sample.total_power_kw == 58.2
    assert decisions[0].sample.specific_energy_kwh_per_m3 > 0.0
    assert collector.summary().accepted_samples == 1
    assert collector.summary().rejected_samples == 3


def test_shadow_evidence_reports_confidence_and_data_limitations():
    collector = LearnerSampleCollector(min_samples_for_shadow=2)
    for items in _replay_results():
        collector.collect(*items)

    evidence = LearnerShadowService(collector).build_evidence()

    assert evidence.mode == "shadow_only"
    assert evidence.influences_control is False
    assert evidence.status == "insufficient_data"
    assert evidence.confidence == 0.5
    assert "min_samples_not_met" in evidence.data_limitations
    assert "rejected_samples_present" in evidence.data_limitations
    assert evidence.combo_stats["pump_1"].sample_count == 1


def test_demo_persists_learner_shadow_evidence_without_control_influence(tmp_path):
    audit_db = tmp_path / "audit.sqlite"
    summary = run_demo(
        config_path=CONFIG_PATH,
        replay_path=REPLAY_PATH,
        cycles=4,
        audit_db=audit_db,
        enable_learner_shadow=True,
    )

    assert summary["learner_shadow"]["mode"] == "shadow_only"
    assert summary["learner_shadow"]["influences_control"] is False
    assert summary["learner_shadow"]["summary"]["accepted_samples"] == 1
    assert summary["learner_shadow"]["summary"]["rejected_samples"] == 3

    with SQLiteAuditStore(audit_db) as store:
        records = list(store.iter_records())
    assert len(records) == 4
    latest = records[-1]
    assert latest.learner_shadow["mode"] == "shadow_only"
    assert latest.learner_shadow["influences_control"] is False
    assert latest.learner_shadow["summary"]["accepted_samples"] == 1
