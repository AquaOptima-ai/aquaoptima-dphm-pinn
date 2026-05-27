from pathlib import Path

from aquaoptima_lite.app.demo import run_demo
from aquaoptima_lite.storage import SQLiteAuditStore

CONFIG_PATH = Path("config/examples/legacy_station_001.yaml")
REPLAY_PATH = Path("tests/fixtures/replay/legacy_station_replay.jsonl")


def test_demo_persists_performance_model_shadow_evidence_without_control_influence(tmp_path):
    audit_db = tmp_path / "audit.sqlite"

    summary = run_demo(
        config_path=CONFIG_PATH,
        replay_path=REPLAY_PATH,
        cycles=4,
        audit_db=audit_db,
        enable_learner_shadow=True,
        enable_performance_shadow=True,
    )

    perf = summary["performance_model"]
    assert perf["influences_control"] is False
    assert perf["readiness"] == "insufficient_data"
    assert "too_few_samples" in perf["reason_codes"]
    assert perf["training_sample_count"] == 1

    with SQLiteAuditStore(audit_db) as store:
        latest = store.latest()
    assert latest is not None
    assert latest.learner_shadow["performance_model"]["influences_control"] is False
    assert latest.learner_shadow["performance_model"]["readiness"] == "insufficient_data"
