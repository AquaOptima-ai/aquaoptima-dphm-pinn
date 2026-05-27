from aquaoptima_lite.learner import (
    LearnerSample,
    PerformanceFeatureBuilder,
    PerformanceModelResult,
    StatisticalPerformanceModel,
)


def _sample(combo_key="pump_1", flow=180.0, power=60.0, head=42.0):
    return LearnerSample(
        timestamp="2026-05-26T09:00:00+08:00",
        site_id="legacy_station_001",
        combo_key=combo_key,
        target_head_m=40.0,
        flow_min_m3h=80.0,
        flow_max_m3h=320.0,
        observed_head_m=head,
        total_flow_m3h=flow,
        total_power_kw=power,
        avg_frequency_hz=45.0,
        running_pump_count=1,
        specific_energy_kwh_per_m3=power / flow,
    )


def test_result_contract_forces_shadow_only_and_serializes_deterministically():
    result = PerformanceModelResult(
        model_id="local_statistical_performance_v1",
        model_version="0.1.0",
        readiness="ready",
        combo_key="pump_1",
        training_sample_count=3,
        confidence=0.75,
        reason_codes=("ready",),
        estimated_flow_m3h=181.0,
        estimated_head_m=42.0,
        estimated_power_kw=60.0,
        estimated_specific_energy_kwh_per_m3=0.331,
        influences_control=True,
    )

    assert result.influences_control is False
    assert result.to_dict() == result.to_dict()
    assert result.to_dict()["influences_control"] is False


def test_feature_builder_extracts_only_accepted_samples_and_reports_rejections():
    accepted = [_sample(), _sample(flow=182.0, power=61.0)]
    builder = PerformanceFeatureBuilder()

    feature_set = builder.from_samples(accepted)
    rejected_set = builder.from_samples([])

    assert feature_set.readiness == "ready"
    assert feature_set.feature_count == 2
    assert feature_set.features[0].combo_key == "pump_1"
    assert feature_set.features[0].specific_energy_kwh_per_m3 > 0.0
    assert feature_set.influences_control is False
    assert rejected_set.readiness == "insufficient_data"
    assert "no_accepted_samples" in rejected_set.reason_codes


def test_statistical_model_returns_insufficient_data_until_threshold_met():
    model = StatisticalPerformanceModel(min_samples_per_combo=3)
    result = model.fit_predict([_sample(), _sample(flow=181.0)], combo_key="pump_1")

    assert result.readiness == "insufficient_data"
    assert "too_few_samples" in result.reason_codes
    assert result.training_sample_count == 2
    assert result.influences_control is False


def test_statistical_model_produces_deterministic_combo_estimate_when_ready():
    samples = [
        _sample(flow=180.0, power=60.0, head=42.0),
        _sample(flow=182.0, power=61.0, head=43.0),
        _sample(flow=178.0, power=59.0, head=41.0),
        _sample(combo_key="pump_2", flow=220.0, power=90.0, head=44.0),
    ]
    model = StatisticalPerformanceModel(min_samples_per_combo=3)

    result = model.fit_predict(list(reversed(samples)), combo_key="pump_1")

    assert result.readiness == "ready"
    assert result.combo_key == "pump_1"
    assert result.training_sample_count == 3
    assert result.estimated_flow_m3h == 180.0
    assert result.estimated_head_m == 42.0
    assert result.estimated_power_kw == 60.0
    assert round(result.estimated_specific_energy_kwh_per_m3, 6) == round((60/180 + 61/182 + 59/178) / 3, 6)
    assert result.confidence == 1.0
    assert result.influences_control is False


def test_statistical_model_unsupported_combo_is_unavailable():
    model = StatisticalPerformanceModel(min_samples_per_combo=1)
    result = model.fit_predict([_sample(combo_key="pump_1")], combo_key="pump_9")

    assert result.readiness == "insufficient_data"
    assert "unsupported_combo" in result.reason_codes
    assert result.training_sample_count == 0
    assert result.influences_control is False
