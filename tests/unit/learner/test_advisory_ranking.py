from aquaoptima_lite.baseline.interface import BaselineRecommendation, PumpSetpoint
from aquaoptima_lite.learner import (
    AdvisoryRankingService,
    AdvisoryCandidate,
    LearnerSample,
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


def _baseline(combo_key="pump_1"):
    return BaselineRecommendation(
        source="baseline_fallback",
        mode="AUTO",
        pump_setpoints=(PumpSetpoint(combo_key, True, 45.0),),
        reason_codes=("fallback_hold_running_pumps",),
        confidence=0.8,
        write_intent=False,
    )


def test_advisory_candidate_contract_forces_evidence_only():
    candidate = AdvisoryCandidate(
        combo_key="pump_1",
        rank=1,
        readiness="ready",
        score=0.91,
        confidence=0.82,
        reason_codes=("lower_specific_energy",),
        estimated_specific_energy_kwh_per_m3=0.31,
        estimated_flow_m3h=180.0,
        estimated_head_m=42.0,
        estimated_power_kw=56.0,
        influences_control=True,
    )

    assert candidate.influences_control is False
    assert candidate.to_dict()["influences_control"] is False


def test_ranking_orders_ready_candidates_by_specific_energy_and_compares_to_baseline():
    samples = [
        _sample("pump_1", flow=180.0, power=72.0),
        _sample("pump_1", flow=182.0, power=73.0),
        _sample("pump_2", flow=178.0, power=54.0),
        _sample("pump_2", flow=181.0, power=55.0),
    ]
    service = AdvisoryRankingService(min_samples_per_combo=2)

    result = service.rank(samples, baseline=_baseline("pump_1"))

    assert result.influences_control is False
    assert result.readiness == "ready"
    assert result.top_candidate is not None
    assert result.top_candidate.combo_key == "pump_2"
    assert result.candidates[0].rank == 1
    assert result.candidates[1].rank == 2
    assert result.baseline_combo_key == "pump_1"
    assert result.baseline_rank == 2
    assert result.delta_vs_baseline_specific_energy_kwh_per_m3 < 0
    assert "top_candidate_differs_from_baseline" in result.reason_codes
    assert result.to_dict()["influences_control"] is False


def test_ranking_reports_insufficient_data_without_replacing_baseline():
    service = AdvisoryRankingService(min_samples_per_combo=3)

    result = service.rank([_sample("pump_1")], baseline=_baseline("pump_1"))

    assert result.readiness == "insufficient_data"
    assert result.top_candidate is None
    assert result.baseline_combo_key == "pump_1"
    assert result.baseline_rank is None
    assert "no_ready_candidates" in result.reason_codes
    assert result.influences_control is False
