import json
from pathlib import Path

from aquaoptima_lite.config import load_site_config
from aquaoptima_lite.config.models import SafetyConfig, SiteConfig
from aquaoptima_lite.runtime import (
    ControlIntent,
    ReasonCode,
    evaluate_authority,
    evaluate_quality,
    snapshot_from_dict,
)
from aquaoptima_lite.runtime.models import StationSnapshot

CONFIG = load_site_config("config/examples/legacy_station_001.yaml")
FIXTURE_DIR = Path("tests/fixtures/snapshots")


def fixture(name: str) -> StationSnapshot:
    return snapshot_from_dict(json.loads((FIXTURE_DIR / name).read_text()))


def with_mode(snapshot: StationSnapshot, mode: str) -> StationSnapshot:
    return StationSnapshot(
        timestamp=snapshot.timestamp,
        site_id=snapshot.site_id,
        mode=mode,
        pumps=snapshot.pumps,
        discharge_pressure_bar=snapshot.discharge_pressure_bar,
        head_m=snapshot.head_m,
        flow_m3h=snapshot.flow_m3h,
        manual_mode=snapshot.manual_mode,
        auto_mode=snapshot.auto_mode,
        quality_flags=snapshot.quality_flags,
        config_hash=snapshot.config_hash,
    )


def with_future_control(config: SiteConfig, enabled: bool) -> SiteConfig:
    safety = SafetyConfig(
        require_auto_mode=config.safety.require_auto_mode,
        block_on_any_trip=config.safety.block_on_any_trip,
        block_on_any_alarm=config.safety.block_on_any_alarm,
        baseline_control_enabled=config.safety.baseline_control_enabled,
        future_control_enabled=enabled,
        min_frequency_hz=config.safety.min_frequency_hz,
        max_frequency_hz=config.safety.max_frequency_hz,
        max_step_hz=config.safety.max_step_hz,
        min_pressure_bar=config.safety.min_pressure_bar,
        max_pressure_bar=config.safety.max_pressure_bar,
        min_flow_m3h=config.safety.min_flow_m3h,
        max_flow_m3h=config.safety.max_flow_m3h,
        min_model_confidence_for_advisory=config.safety.min_model_confidence_for_advisory,
    )
    return SiteConfig(
        site_id=config.site_id,
        site_name=config.site_name,
        timezone=config.timezone,
        runtime=config.runtime,
        safety=safety,
        data_requirements=config.data_requirements,
        pumps=config.pumps,
        tags=config.tags,
    )


def test_authority_allows_safe_baseline_control():
    snapshot = with_mode(fixture("snapshot_pass.json"), "baseline_control")
    quality = evaluate_quality(snapshot, CONFIG)
    intent = ControlIntent(
        source="baseline_mvp",
        pump_id="pump_1",
        target_frequency_hz=45.0,
        write_requested=True,
    )

    decision = evaluate_authority(snapshot, quality, intent, CONFIG)

    assert decision.decision == "allow"
    assert decision.write_allowed is True
    assert decision.source == "baseline_mvp"


def test_authority_observes_learner_in_shadow_mode():
    snapshot = fixture("snapshot_pass.json")
    quality = evaluate_quality(snapshot, CONFIG)
    intent = ControlIntent(source="learner", confidence=0.8, write_requested=False)

    decision = evaluate_authority(snapshot, quality, intent, CONFIG)

    assert decision.decision == "observe_only"
    assert decision.write_allowed is False


def test_authority_blocks_learner_write_in_shadow_mode():
    snapshot = fixture("snapshot_pass.json")
    quality = evaluate_quality(snapshot, CONFIG)
    intent = ControlIntent(
        source="learner",
        pump_id="pump_1",
        target_frequency_hz=46.0,
        confidence=0.8,
        write_requested=True,
    )

    decision = evaluate_authority(snapshot, quality, intent, CONFIG)

    assert decision.decision == "block"
    assert ReasonCode.SOURCE_NOT_ALLOWED_IN_MODE.value in decision.reason_codes


def test_authority_blocks_manual_mode_for_baseline():
    snapshot = with_mode(fixture("snapshot_manual_mode_block.json"), "baseline_control")
    quality = evaluate_quality(snapshot, CONFIG)
    intent = ControlIntent(source="baseline_mvp", target_frequency_hz=45.0, write_requested=True)

    decision = evaluate_authority(snapshot, quality, intent, CONFIG)

    assert decision.decision == "block"
    assert ReasonCode.MANUAL_MODE_ACTIVE.value in decision.reason_codes


def test_authority_blocks_trip_for_baseline():
    snapshot = with_mode(fixture("snapshot_trip_block.json"), "baseline_control")
    quality = evaluate_quality(snapshot, CONFIG)
    intent = ControlIntent(source="baseline_mvp", target_frequency_hz=45.0, write_requested=True)

    decision = evaluate_authority(snapshot, quality, intent, CONFIG)

    assert decision.decision == "block"
    assert ReasonCode.PUMP_TRIP_ACTIVE.value in decision.reason_codes


def test_authority_blocks_future_supervisory_when_disabled():
    snapshot = with_mode(fixture("snapshot_pass.json"), "learned_supervisory_control")
    quality = evaluate_quality(snapshot, CONFIG)
    intent = ControlIntent(source="learner", target_frequency_hz=45.0, confidence=0.9, write_requested=True)

    decision = evaluate_authority(snapshot, quality, intent, CONFIG)

    assert decision.decision == "block"
    assert ReasonCode.FUTURE_CONTROL_DISABLED.value in decision.reason_codes


def test_authority_blocks_frequency_out_of_bounds():
    snapshot = with_mode(fixture("snapshot_pass.json"), "baseline_control")
    quality = evaluate_quality(snapshot, CONFIG)
    intent = ControlIntent(source="baseline_mvp", target_frequency_hz=999.0, write_requested=True)

    decision = evaluate_authority(snapshot, quality, intent, CONFIG)

    assert decision.decision == "block"
    assert ReasonCode.FREQUENCY_OUT_OF_BOUNDS.value in decision.reason_codes
