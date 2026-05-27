from pathlib import Path

from aquaoptima_lite.app.demo import run_demo
from aquaoptima_lite.storage import SQLiteAuditStore

CONFIG_PATH = Path("config/examples/legacy_station_001.yaml")
REPLAY_PATH = Path("tests/fixtures/replay/legacy_station_replay.jsonl")


def test_demo_persists_advisory_ranking_evidence_without_control_influence(tmp_path):
    audit_db = tmp_path / "audit.sqlite"

    summary = run_demo(
        config_path=CONFIG_PATH,
        replay_path=REPLAY_PATH,
        cycles=4,
        audit_db=audit_db,
        enable_learner_shadow=True,
        enable_performance_shadow=True,
        enable_advisory_ranking=True,
    )

    ranking = summary["advisory_ranking"]
    assert ranking["influences_control"] is False
    assert ranking["readiness"] == "insufficient_data"
    assert ranking["baseline_combo_key"] == "pump_1"
    assert "no_ready_candidates" in ranking["reason_codes"]

    with SQLiteAuditStore(audit_db) as store:
        latest = store.latest()
    assert latest is not None
    assert latest.learner_shadow["advisory_ranking"]["influences_control"] is False
    assert latest.learner_shadow["advisory_ranking"]["baseline_combo_key"] == "pump_1"
