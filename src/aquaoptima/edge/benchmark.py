"""Sprint 47 — offline, CPU-only AMAX dPHM-PINN benchmark runner.

This module is the runtime-side companion to the
:mod:`aquaoptima_contracts.edge.benchmark` SDK dataclasses. It uses the
existing dPHM fixtures (branch / single-loop / pump) plus
:class:`aquaoptima.models.DPHMPINN` to produce host-derived **surrogate**
latency / RSS evidence the Sprint 47 CLI then serialises as
:class:`AMAXBenchmarkReport` records.

The runner is intentionally narrow:

- **CPU-only.** ``torch.set_num_threads`` is honoured per scenario; no
  CUDA path; no GPU probing.
- **No model artifact loading from disk.** A small in-memory
  :class:`DPHMPINN` is instantiated per scenario with deterministic
  seeds.
- **No HTTP / network / database / message-broker IO.**
- **No live OT binding, no PLC/PAC/SCADA write, no command emission,
  no setpoint output, no control-loop closure.**
- **Surrogate by default.** Host-derived runs are labelled surrogate
  unless the caller explicitly passes ``surrogate_hardware=False``.

Sprint 48 should remain a read-only PLC/SCADA contract gate; this
runner only proves CPU inference packaging feasibility evidence.
"""

from __future__ import annotations

import platform
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Callable, Iterable

import torch

from aquaoptima.dataio.window_dataset import NODE_FEATURE_DIM
from aquaoptima.dphm.fixtures import (
    make_branch_network,
    make_pump_network,
    make_single_loop_network,
)
from aquaoptima.dphm.network import Network
from aquaoptima.models.dphm_pinn import DPHMPINN
from aquaoptima.topology import build_graph_features

from aquaoptima_contracts.edge.benchmark import (
    AMAX_BENCHMARK_SCENARIO_BRANCH,
    AMAX_BENCHMARK_SCENARIO_PUMP,
    AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP,
    AMAXBenchmarkMetrics,
    AMAXBenchmarkReport,
    AMAXBenchmarkScenario,
    canonical_amax_benchmark_scenarios,
    classify_supervisory_cadence,
)


DEFAULT_BENCHMARK_ITERATIONS: int = 8
DEFAULT_BENCHMARK_WARMUP: int = 2
DEFAULT_BENCHMARK_HOST_LABEL: str = "developer-host-surrogate"

# Maps a canonical Sprint 47 scenario id to a deterministic fixture
# factory. The fixtures are the same ones the Sprint 2 / Sprint 3 unit
# tests use, so the benchmark exercises code paths that already have
# good test coverage.
_SCENARIO_FACTORIES: dict[str, Callable[[], Network]] = {
    AMAX_BENCHMARK_SCENARIO_BRANCH: make_branch_network,
    AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP: make_single_loop_network,
    AMAX_BENCHMARK_SCENARIO_PUMP: make_pump_network,
}


@dataclass(frozen=True)
class BenchmarkRunResult:
    """Lightweight bundle returned by :func:`run_amax_cpu_benchmark`."""

    reports: tuple[AMAXBenchmarkReport, ...]

    def to_dict(self) -> dict:
        return {"reports": [r.to_dict() for r in self.reports]}


def compute_latency_percentiles(
    samples_ms: Iterable[float],
) -> tuple[float, float, float]:
    """Compute deterministic p50 / p95 / p99 from a sample list.

    Uses :func:`statistics.median` for p50 (so single-sample runs return
    a finite value) and an explicit ceiling-rank order statistic for
    p95 / p99 so the helper does not depend on numpy.
    """

    values = sorted(float(v) for v in samples_ms)
    if not values:
        raise ValueError("compute_latency_percentiles requires >= 1 sample")
    p50 = statistics.median(values)

    def _percentile(p: float) -> float:
        if len(values) == 1:
            return values[0]
        # Ceiling-rank order statistic, 1-indexed: rank = ceil(p * N).
        rank = int(-(-len(values) * p // 1))
        rank = max(1, min(rank, len(values)))
        return values[rank - 1]

    return p50, _percentile(0.95), _percentile(0.99)


def _max_rss_kb() -> int | None:
    """Return peak resident set size in kilobytes on Linux hosts."""

    try:
        import resource  # type: ignore[import-untyped]
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # ru_maxrss is kilobytes on Linux, bytes on macOS. The benchmark
    # harness only targets Linux AMAX-8580 surrogates; if a future
    # caller wants macOS support they can divide by 1024 explicitly.
    if sys.platform == "darwin":
        return int(usage.ru_maxrss // 1024)
    return int(usage.ru_maxrss)


def _build_synthetic_input(
    scenario: AMAXBenchmarkScenario,
    features,
    *,
    seed: int,
) -> torch.Tensor:
    generator = torch.Generator(device="cpu").manual_seed(seed)
    shape = (
        scenario.batch_size,
        scenario.sequence_length,
        features.num_nodes,
        NODE_FEATURE_DIM,
    )
    return torch.randn(*shape, generator=generator, dtype=torch.float32)


def _build_model_for_scenario(
    scenario: AMAXBenchmarkScenario,
    *,
    seed: int,
) -> DPHMPINN:
    torch.manual_seed(seed)
    return DPHMPINN(
        node_in_dim=3,
        edge_in_dim=8,
        seq_in_dim=NODE_FEATURE_DIM,
        hidden_dim=scenario.hidden_dim,
        num_setpoint_outputs=1,
        force_fallback=True,
    )


def run_amax_cpu_benchmark_scenario(
    scenario: AMAXBenchmarkScenario,
    *,
    iterations: int = DEFAULT_BENCHMARK_ITERATIONS,
    warmup: int = DEFAULT_BENCHMARK_WARMUP,
    seed: int = 0,
    host_label: str = DEFAULT_BENCHMARK_HOST_LABEL,
    surrogate_hardware: bool = True,
    package_manifest_reference: str = "",
) -> AMAXBenchmarkReport:
    """Benchmark a single canonical Sprint 47 scenario on CPU.

    Returns a deterministic :class:`AMAXBenchmarkReport`. The runner
    enforces CPU-only inference (:func:`torch.set_num_threads` is set
    from ``scenario.thread_count``; no CUDA path is taken). Host
    output is labelled surrogate unless the caller explicitly identifies
    real AMAX-8580 hardware.
    """

    if scenario.scenario_id not in _SCENARIO_FACTORIES:
        raise ValueError(
            f"Sprint 47 offline runner does not know scenario "
            f"{scenario.scenario_id!r}; expected one of "
            f"{sorted(_SCENARIO_FACTORIES)}"
        )
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if warmup < 0:
        raise ValueError("warmup must be non-negative")

    torch.set_num_threads(int(scenario.thread_count))
    network = _SCENARIO_FACTORIES[scenario.scenario_id]()
    features = build_graph_features(network)
    if features.num_nodes != scenario.num_nodes:
        # Tolerated mismatch: keep going but emit a warning so callers
        # can spot fixture drift without aborting the benchmark.
        warnings: list[str] = [
            (
                f"fixture num_nodes={features.num_nodes} does not match "
                f"scenario.num_nodes={scenario.num_nodes}"
            )
        ]
    else:
        warnings = []

    model = _build_model_for_scenario(scenario, seed=seed)
    model.eval()
    x_seq = _build_synthetic_input(scenario, features, seed=seed)

    samples_ms: list[float] = []
    with torch.inference_mode():
        for _ in range(int(warmup)):
            model(x_seq, features)
        for _ in range(int(iterations)):
            start = time.perf_counter()
            model(x_seq, features)
            end = time.perf_counter()
            samples_ms.append((end - start) * 1000.0)

    p50, p95, p99 = compute_latency_percentiles(samples_ms)
    cadence = classify_supervisory_cadence(p95)
    rss_kb = _max_rss_kb()

    metrics_notes: tuple[str, ...] = (
        "host-derived surrogate evidence",
        "CPU-only inference; no CUDA path",
        "no live OT binding",
        "no PLC/PAC/SCADA write",
        "no command emission",
        "no setpoint output",
    )
    metrics = AMAXBenchmarkMetrics(
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        latency_p99_ms=p99,
        iterations=int(iterations),
        warmup_iterations=int(warmup),
        framework=scenario.framework,
        python_version=platform.python_version(),
        torch_version=str(torch.__version__),
        host_label=host_label,
        surrogate_hardware=bool(surrogate_hardware),
        memory_rss_max_kb=rss_kb,
        notes=metrics_notes,
    )

    report_notes: tuple[str, ...] = (
        "Sprint 47 AMAX CPU benchmark / packaging smoke evidence",
        "evidence is surrogate until run on real AMAX-8580 hardware",
        "no live OT binding",
        "no PLC/PAC/SCADA write",
        "no command emission",
        "no setpoint output",
    )

    return AMAXBenchmarkReport(
        scenario=scenario,
        metrics=metrics,
        cadence_classification=cadence,
        package_manifest_reference=package_manifest_reference,
        surrogate_hardware=bool(surrogate_hardware),
        warnings=tuple(warnings),
        notes=report_notes,
    )


def run_amax_cpu_benchmark(
    scenarios: Iterable[AMAXBenchmarkScenario] | None = None,
    *,
    iterations: int = DEFAULT_BENCHMARK_ITERATIONS,
    warmup: int = DEFAULT_BENCHMARK_WARMUP,
    seed: int = 0,
    host_label: str = DEFAULT_BENCHMARK_HOST_LABEL,
    surrogate_hardware: bool = True,
    package_manifest_reference: str = "",
) -> BenchmarkRunResult:
    """Run the Sprint 47 offline benchmark over a scenario tuple.

    If ``scenarios`` is ``None``, the canonical Sprint 47 scenario
    tuple from :func:`canonical_amax_benchmark_scenarios` is used.
    Returns a :class:`BenchmarkRunResult` carrying one
    :class:`AMAXBenchmarkReport` per scenario.
    """

    chosen = (
        canonical_amax_benchmark_scenarios()
        if scenarios is None
        else tuple(scenarios)
    )
    reports: list[AMAXBenchmarkReport] = []
    for scenario in chosen:
        report = run_amax_cpu_benchmark_scenario(
            scenario,
            iterations=iterations,
            warmup=warmup,
            seed=seed,
            host_label=host_label,
            surrogate_hardware=surrogate_hardware,
            package_manifest_reference=package_manifest_reference,
        )
        reports.append(report)
    return BenchmarkRunResult(reports=tuple(reports))


__all__ = [
    "BenchmarkRunResult",
    "DEFAULT_BENCHMARK_HOST_LABEL",
    "DEFAULT_BENCHMARK_ITERATIONS",
    "DEFAULT_BENCHMARK_WARMUP",
    "compute_latency_percentiles",
    "run_amax_cpu_benchmark",
    "run_amax_cpu_benchmark_scenario",
]
