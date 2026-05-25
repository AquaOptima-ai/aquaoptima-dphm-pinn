"""Sprint 47 — offline AMAX CPU dPHM-PINN benchmark runner tests.

Acceptance: the offline runner produces at least one
:class:`AMAXBenchmarkReport` on CPU with finite latency metrics, is
labelled surrogate by default, and does not introduce any forbidden
write / control / setpoint capability.
"""

from __future__ import annotations

import json
import math
import sys
import subprocess
from pathlib import Path

import pytest

from aquaoptima.edge.benchmark import (
    BenchmarkRunResult,
    _build_model_for_scenario,
    _build_synthetic_input,
    compute_latency_percentiles,
    run_amax_cpu_benchmark,
    run_amax_cpu_benchmark_scenario,
)
from aquaoptima.dataio.window_dataset import NODE_FEATURE_DIM
from aquaoptima.dphm.fixtures import make_branch_network
from aquaoptima.topology import build_graph_features
from aquaoptima_contracts.edge.benchmark import (
    AMAX_BENCHMARK_CADENCE_BUCKETS,
    AMAXBenchmarkReport,
    canonical_amax_benchmark_scenarios,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "scripts" / "run_amax_cpu_benchmark.py"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def test_runner_emits_one_report_per_canonical_scenario() -> None:
    result = run_amax_cpu_benchmark(iterations=3, warmup=1)
    assert isinstance(result, BenchmarkRunResult)
    assert len(result.reports) == 3
    for report in result.reports:
        assert isinstance(report, AMAXBenchmarkReport)


def test_runner_produces_finite_latency_metrics() -> None:
    result = run_amax_cpu_benchmark(iterations=3, warmup=1)
    for report in result.reports:
        m = report.metrics
        for sample in (m.latency_p50_ms, m.latency_p95_ms, m.latency_p99_ms):
            assert math.isfinite(sample)
            assert sample >= 0.0
        assert m.latency_p95_ms >= m.latency_p50_ms
        assert m.latency_p99_ms >= m.latency_p95_ms
        assert m.iterations == 3
        assert m.warmup_iterations == 1


def test_runner_labels_reports_surrogate_by_default() -> None:
    result = run_amax_cpu_benchmark(iterations=2, warmup=0)
    for report in result.reports:
        assert report.surrogate_hardware is True
        assert report.metrics.surrogate_hardware is True


def test_runner_assigns_cadence_classification_from_bucket() -> None:
    result = run_amax_cpu_benchmark(iterations=2, warmup=0)
    for report in result.reports:
        assert report.cadence_classification in AMAX_BENCHMARK_CADENCE_BUCKETS


def test_runner_single_scenario_helper() -> None:
    scenario = canonical_amax_benchmark_scenarios()[0]
    report = run_amax_cpu_benchmark_scenario(
        scenario, iterations=2, warmup=0
    )
    assert isinstance(report, AMAXBenchmarkReport)
    assert report.scenario == scenario


def test_runner_uses_window_dataset_feature_dimension() -> None:
    scenario = canonical_amax_benchmark_scenarios()[0]
    features = build_graph_features(make_branch_network())
    x_seq = _build_synthetic_input(scenario, features, seed=123)
    model = _build_model_for_scenario(scenario, seed=123)

    assert x_seq.shape[-1] == NODE_FEATURE_DIM
    assert model.temporal_encoder.input_dim == NODE_FEATURE_DIM


def test_runner_notes_carry_safety_phrases() -> None:
    result = run_amax_cpu_benchmark(iterations=2, warmup=0)
    for report in result.reports:
        joined = "\n".join(report.notes)
        assert "no live OT binding" in joined
        assert "no PLC/PAC/SCADA write" in joined
        assert "no command emission" in joined
        assert "no setpoint output" in joined


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------


def test_compute_latency_percentiles_single_sample() -> None:
    p50, p95, p99 = compute_latency_percentiles([4.2])
    assert p50 == 4.2
    assert p95 == 4.2
    assert p99 == 4.2


def test_compute_latency_percentiles_sorted_samples() -> None:
    samples = [10.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    p50, p95, p99 = compute_latency_percentiles(samples)
    assert p50 == pytest.approx(5.5)
    assert p95 == 10.0
    assert p99 == 10.0


def test_compute_latency_percentiles_rejects_empty() -> None:
    with pytest.raises(ValueError):
        compute_latency_percentiles([])


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_writes_json_with_expected_keys(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "--output",
            str(out),
            "--iterations",
            "2",
            "--warmup",
            "0",
        ],
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.exists(), completed.stdout + completed.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["sprint"] == 47
    assert payload["harness"] == "amax_cpu_benchmark_packaging_smoke"
    assert payload["surrogate_hardware"] is True
    assert isinstance(payload["reports"], list) and payload["reports"]
    first = payload["reports"][0]
    assert "scenario" in first
    assert "metrics" in first
    assert "cadence_classification" in first
    assert "surrogate_hardware" in first
    safety_joined = "\n".join(payload["safety"])
    assert "no live OT binding" in safety_joined
    assert "no PLC/PAC/SCADA write" in safety_joined
    assert "no command emission" in safety_joined
    assert "no setpoint output" in safety_joined


# ---------------------------------------------------------------------------
# Safety boundary: no forbidden imports / capabilities introduced
# ---------------------------------------------------------------------------


import re

# Module names that would indicate a forbidden runtime import surface
# (HTTP, network, database, message-broker). The probe patterns are
# built at runtime from these tokens so the test file itself does not
# contain literal ``import <forbidden>`` lines that a runtime-import
# audit would otherwise flag.
_FORBIDDEN_RUNTIME_MODULE_TOKENS: tuple[str, ...] = (
    "http",
    "socket",
    "requests",
    "urllib3",
    "fastapi",
    "uvicorn",
    "flask",
    "aiohttp",
    "paho",
    "asyncpg",
    "psycopg2",
    "sqlalchemy",
    "kafka",
    "pika",
    "redis",
    "opcua",
    "pymodbus",
)


def _sprint47_source_paths() -> list[Path]:
    return [
        REPO_ROOT / "src" / "aquaoptima" / "edge" / "__init__.py",
        REPO_ROOT / "src" / "aquaoptima" / "edge" / "benchmark.py",
        REPO_ROOT / "src" / "aquaoptima_contracts" / "edge" / "benchmark.py",
        REPO_ROOT / "scripts" / "run_amax_cpu_benchmark.py",
    ]


def test_runtime_modules_have_no_network_or_db_imports() -> None:
    patterns = [
        re.compile(rf"^\s*(?:import|from)\s+{re.escape(token)}\b", re.MULTILINE)
        for token in _FORBIDDEN_RUNTIME_MODULE_TOKENS
    ]
    for path in _sprint47_source_paths():
        text = path.read_text(encoding="utf-8")
        for token, pattern in zip(_FORBIDDEN_RUNTIME_MODULE_TOKENS, patterns):
            assert not pattern.search(text), (
                f"Sprint 47 must not introduce a top-level {token!r} "
                f"import in {path}"
            )
