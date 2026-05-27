from pathlib import Path

from aquaoptima_lite.deployment import DeploymentReadinessChecker

CONFIG_PATH = Path("config/examples/legacy_station_001.yaml")
REPLAY_PATH = Path("tests/fixtures/replay/legacy_station_replay.jsonl")


def test_readiness_checker_reports_pilot_ready_bundle_with_safety_gate():
    report = DeploymentReadinessChecker().check(
        config_path=CONFIG_PATH,
        replay_path=REPLAY_PATH,
        cycles=4,
    )

    assert report.status == "ready_for_pilot_review"
    assert report.influences_control is False
    assert report.read_only is True
    assert report.safety.no_console_direct_write_path is True
    assert report.safety.no_new_field_write_path is True
    assert report.safety.baseline_remains_authority is True
    assert report.config.site_id == "legacy_station_001"
    assert report.replay.requested_cycles == 4
    assert report.replay.audit_count == 4
    assert report.api.has_console_evidence_endpoint is True
    assert report.handoff.operator_review_required is True
    assert "review_console_evidence_before_pilot" in report.handoff.checklist
    assert report.to_dict()["influences_control"] is False


def test_readiness_checker_blocks_missing_replay_without_control_influence(tmp_path):
    missing_replay = tmp_path / "missing.jsonl"

    report = DeploymentReadinessChecker().check(
        config_path=CONFIG_PATH,
        replay_path=missing_replay,
        cycles=4,
    )

    assert report.status == "blocked"
    assert report.influences_control is False
    assert report.read_only is True
    assert any(gate.name == "replay_exists" and gate.status == "block" for gate in report.gates)
    assert "missing_replay_file" in report.reason_codes
