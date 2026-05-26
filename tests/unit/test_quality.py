import json
from pathlib import Path

from aquaoptima_lite.config import load_site_config
from aquaoptima_lite.runtime import ReasonCode, evaluate_quality, snapshot_from_dict

CONFIG = load_site_config("config/examples/legacy_station_001.yaml")
FIXTURE_DIR = Path("tests/fixtures/snapshots")


def fixture(name: str):
    return snapshot_from_dict(json.loads((FIXTURE_DIR / name).read_text()))


def test_quality_pass_for_complete_auto_snapshot():
    decision = evaluate_quality(fixture("snapshot_pass.json"), CONFIG)

    assert decision.status == "pass"
    assert decision.reason_codes == ()
    assert decision.blocked_for_advisory is False
    assert decision.blocked_for_learning is False
    assert decision.blocked_for_future_control is False


def test_quality_blocks_manual_mode():
    decision = evaluate_quality(fixture("snapshot_manual_mode_block.json"), CONFIG)

    assert decision.status == "block"
    assert ReasonCode.MANUAL_MODE_ACTIVE.value in decision.reason_codes
    assert decision.blocked_for_advisory is True
    assert decision.blocked_for_learning is True
    assert decision.blocked_for_future_control is True


def test_quality_blocks_pump_trip():
    decision = evaluate_quality(fixture("snapshot_trip_block.json"), CONFIG)

    assert decision.status == "block"
    assert ReasonCode.PUMP_TRIP_ACTIVE.value in decision.reason_codes
    assert decision.blocked_for_advisory is True
    assert decision.blocked_for_learning is True


def test_quality_warns_for_missing_flow_without_blocking_baseline_advisory():
    decision = evaluate_quality(fixture("snapshot_missing_flow_warn.json"), CONFIG)

    assert decision.status == "warn"
    assert ReasonCode.FLOW_MISSING_LEARNING_LIMITED.value in decision.reason_codes
    assert decision.blocked_for_advisory is False
    assert decision.blocked_for_learning is True
    assert decision.confidence_penalty > 0
