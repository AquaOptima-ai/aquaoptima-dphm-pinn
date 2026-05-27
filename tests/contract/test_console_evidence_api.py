import json
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None

from aquaoptima_lite.api import create_app
from aquaoptima_lite.app import RuntimeCycle
from aquaoptima_lite.config import load_site_config
from aquaoptima_lite.learner import (
    AdvisoryRankingService,
    LearnerSampleCollector,
    LearnerShadowService,
    StatisticalPerformanceModel,
)
from aquaoptima_lite.runtime import snapshot_from_dict


def _provider_with_shadow_evidence():
    config = load_site_config("config/examples/legacy_station_001.yaml")
    cycle = RuntimeCycle(config=config)
    collector = LearnerSampleCollector(min_samples_for_shadow=2)
    frames = [
        json.loads(Path("tests/fixtures/snapshots/snapshot_pass.json").read_text()),
        json.loads(Path("tests/fixtures/snapshots/snapshot_missing_flow_warn.json").read_text()),
    ]
    for raw in frames:
        result = cycle.run(snapshot_from_dict(raw))
        collector.collect(result.snapshot, result.quality, cycle.demand)
    assert cycle._latest is not None
    learner = LearnerShadowService(collector).build_evidence().to_dict()
    learner["performance_model"] = StatisticalPerformanceModel(min_samples_per_combo=2).evaluate(collector.samples).to_dict()
    learner["advisory_ranking"] = AdvisoryRankingService(min_samples_per_combo=2).rank(
        collector.samples,
        baseline=cycle._latest.recommendation,
    ).to_dict()
    cycle.audit_store.attach_learner_shadow(cycle._latest.audit_id, learner)
    return cycle


def test_console_evidence_endpoint_exposes_read_only_operator_report():
    if TestClient is None:
        return
    client = TestClient(create_app(_provider_with_shadow_evidence()))

    response = client.get("/console/evidence/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "optimizer_lite"
    assert payload["site_id"] == "legacy_station_001"
    assert payload["read_only"] is True
    assert payload["influences_control"] is False
    assert payload["safety"]["no_console_direct_write_path"] is True
    assert payload["safety"]["no_new_field_write_path"] is True
    assert payload["quality"]["status"] == "warn"
    assert payload["baseline"]["source"] == "baseline_fallback"
    assert payload["learner_shadow"]["influences_control"] is False
    assert payload["performance_model"]["influences_control"] is False
    assert payload["advisory_ranking"]["influences_control"] is False
    assert payload["advisory_ranking"]["baseline_combo_key"] == "pump_1"


def test_console_evidence_endpoint_handles_no_cycle_without_commands():
    if TestClient is None:
        return
    client = TestClient(create_app())

    response = client.get("/console/evidence/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_cycle"] is False
    assert payload["read_only"] is True
    assert payload["influences_control"] is False
    assert payload["safety"]["no_console_direct_write_path"] is True
    assert payload["safety"]["no_new_field_write_path"] is True
    assert payload["baseline"] is None
    assert payload["learner_shadow"] == {}
