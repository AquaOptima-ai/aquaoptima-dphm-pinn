"""Sprint 47 — AMAX CPU benchmark / packaging smoke SDK contracts.

Acceptance: the SDK projects the AMAX-5580 CPU benchmark scenario /
metrics / report shapes and the supervisory cadence classifier;
canonical scenarios are deterministic and reaffirm the non-negotiable
safety boundary (no live OT binding, no PLC/PAC/SCADA write, no command
emission, no setpoint output).
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    AMAX_5580_PROFILE_ID,
    AMAX_BENCHMARK_CADENCE_BUCKETS,
    AMAX_BENCHMARK_FRAMEWORKS,
    AMAX_BENCHMARK_SCENARIO_BRANCH,
    AMAX_BENCHMARK_SCENARIO_PUMP,
    AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP,
    AMAXBenchmarkMetrics,
    AMAXBenchmarkReport,
    AMAXBenchmarkScenario,
    ContractError,
    canonical_amax_benchmark_scenarios,
    classify_supervisory_cadence,
    dump_canonical_json,
    load_canonical_json,
)


# ---------------------------------------------------------------------------
# Canonical scenarios
# ---------------------------------------------------------------------------


def test_canonical_scenarios_cover_branch_single_loop_pump() -> None:
    scenarios = canonical_amax_benchmark_scenarios()
    ids = {s.scenario_id for s in scenarios}
    assert ids == {
        AMAX_BENCHMARK_SCENARIO_BRANCH,
        AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP,
        AMAX_BENCHMARK_SCENARIO_PUMP,
    }


def test_canonical_scenarios_carry_size_and_thread_metadata() -> None:
    for scenario in canonical_amax_benchmark_scenarios():
        assert scenario.num_nodes >= 1
        assert scenario.num_edges >= 1
        assert scenario.sequence_length == 32
        assert scenario.batch_size >= 1
        assert scenario.hidden_dim >= 1
        assert scenario.thread_count >= 1
        assert scenario.framework in AMAX_BENCHMARK_FRAMEWORKS
        assert scenario.target_hardware_profile_id == AMAX_5580_PROFILE_ID


def test_canonical_scenarios_carry_safety_phrases() -> None:
    for scenario in canonical_amax_benchmark_scenarios():
        joined = "\n".join(scenario.notes)
        assert "no live OT binding" in joined
        assert "no PLC/PAC/SCADA write" in joined
        assert "no command emission" in joined
        assert "no setpoint output" in joined


def test_scenario_round_trip_is_deterministic() -> None:
    for scenario in canonical_amax_benchmark_scenarios():
        payload = scenario.to_dict()
        raw = dump_canonical_json(payload)
        decoded = load_canonical_json(raw)
        rebuilt = AMAXBenchmarkScenario.from_dict(decoded)
        assert rebuilt == scenario


def test_scenario_rejects_unknown_framework() -> None:
    with pytest.raises(ContractError):
        AMAXBenchmarkScenario(
            scenario_id="rogue",
            description="rogue scenario",
            num_nodes=4,
            num_edges=3,
            sequence_length=32,
            batch_size=1,
            hidden_dim=16,
            framework="cuda_tensorrt",
            thread_count=1,
            target_hardware_profile_id=AMAX_5580_PROFILE_ID,
        )


def test_scenario_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ContractError):
        AMAXBenchmarkScenario(
            scenario_id="rogue",
            description="rogue scenario",
            num_nodes=0,
            num_edges=3,
            sequence_length=32,
            batch_size=1,
            hidden_dim=16,
            framework="pytorch_cpu",
            thread_count=1,
            target_hardware_profile_id=AMAX_5580_PROFILE_ID,
        )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _make_valid_metrics(**overrides) -> AMAXBenchmarkMetrics:
    defaults = dict(
        latency_p50_ms=1.0,
        latency_p95_ms=2.0,
        latency_p99_ms=3.0,
        iterations=4,
        warmup_iterations=1,
        framework="pytorch_cpu",
        python_version="3.10.0",
        torch_version="2.0.0",
        host_label="developer-host-surrogate",
        surrogate_hardware=True,
        memory_rss_max_kb=12345,
    )
    defaults.update(overrides)
    return AMAXBenchmarkMetrics(**defaults)


def test_metrics_round_trip_is_deterministic() -> None:
    metrics = _make_valid_metrics()
    payload = metrics.to_dict()
    raw = dump_canonical_json(payload)
    decoded = load_canonical_json(raw)
    rebuilt = AMAXBenchmarkMetrics.from_dict(decoded)
    assert rebuilt == metrics


def test_metrics_reject_inverted_percentiles() -> None:
    with pytest.raises(ContractError):
        _make_valid_metrics(latency_p50_ms=5.0, latency_p95_ms=4.0)
    with pytest.raises(ContractError):
        _make_valid_metrics(latency_p95_ms=10.0, latency_p99_ms=9.0)


def test_metrics_default_surrogate_true() -> None:
    metrics = _make_valid_metrics()
    assert metrics.surrogate_hardware is True


def test_metrics_round_trip_without_rss() -> None:
    metrics = _make_valid_metrics(memory_rss_max_kb=None)
    raw = dump_canonical_json(metrics.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = AMAXBenchmarkMetrics.from_dict(decoded)
    assert rebuilt == metrics
    assert rebuilt.memory_rss_max_kb is None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _make_valid_report(**overrides) -> AMAXBenchmarkReport:
    scenario = canonical_amax_benchmark_scenarios()[0]
    metrics = _make_valid_metrics()
    defaults = dict(
        scenario=scenario,
        metrics=metrics,
        cadence_classification="sub_1s_supervisory",
        feasibility_profile_id=AMAX_5580_PROFILE_ID,
        package_manifest_reference="",
        surrogate_hardware=True,
        warnings=(),
        notes=(
            "Sprint 47 AMAX CPU benchmark / packaging smoke evidence",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
        ),
    )
    defaults.update(overrides)
    return AMAXBenchmarkReport(**defaults)


def test_report_round_trip_is_deterministic() -> None:
    report = _make_valid_report()
    payload = report.to_dict()
    raw = dump_canonical_json(payload)
    decoded = load_canonical_json(raw)
    rebuilt = AMAXBenchmarkReport.from_dict(decoded)
    assert rebuilt == report


def test_report_default_surrogate_true() -> None:
    report = _make_valid_report()
    assert report.surrogate_hardware is True
    assert report.metrics.surrogate_hardware is True


def test_report_rejects_surrogate_mismatch() -> None:
    metrics = _make_valid_metrics(surrogate_hardware=False)
    with pytest.raises(ContractError):
        AMAXBenchmarkReport(
            scenario=canonical_amax_benchmark_scenarios()[0],
            metrics=metrics,
            cadence_classification="sub_1s_supervisory",
            surrogate_hardware=True,
        )


def test_report_rejects_unknown_cadence_classification() -> None:
    with pytest.raises(ContractError):
        _make_valid_report(cadence_classification="instant")


def test_report_notes_carry_safety_phrases() -> None:
    report = _make_valid_report()
    joined = "\n".join(report.notes)
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined
    assert "no command emission" in joined
    assert "no setpoint output" in joined


# ---------------------------------------------------------------------------
# Cadence classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "p95_ms,expected",
    [
        (0.0, "sub_1s_supervisory"),
        (123.0, "sub_1s_supervisory"),
        (1000.0, "sub_1s_supervisory"),
        (1000.001, "sub_5s_supervisory"),
        (4999.0, "sub_5s_supervisory"),
        (5000.0, "sub_5s_supervisory"),
        (5000.001, "sub_60s_supervisory"),
        (59000.0, "sub_60s_supervisory"),
        (60000.0, "sub_60s_supervisory"),
        (60000.001, "slower_than_60s"),
        (120000.0, "slower_than_60s"),
    ],
)
def test_classify_supervisory_cadence_thresholds(
    p95_ms: float, expected: str
) -> None:
    assert classify_supervisory_cadence(p95_ms) == expected


def test_classify_supervisory_cadence_rejects_negative_latency() -> None:
    with pytest.raises(ContractError):
        classify_supervisory_cadence(-1.0)


def test_cadence_buckets_locked() -> None:
    assert AMAX_BENCHMARK_CADENCE_BUCKETS == (
        "sub_1s_supervisory",
        "sub_5s_supervisory",
        "sub_60s_supervisory",
        "slower_than_60s",
    )
