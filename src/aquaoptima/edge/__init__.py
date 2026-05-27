"""AquaOptima Edge runtime-side helpers (Sprint 47).

Sprint 47 ships an **offline, CPU-only** dPHM-PINN benchmark and
packaging smoke harness under :mod:`aquaoptima.edge.benchmark`. The
helpers are not an Edge Runtime daemon, not an HTTP / network /
database / message-broker client, not a PLC/PAC/SCADA client, and they
do not perform live OT binding, write paths, command emission, setpoint
output, or control-loop closure. Host-derived benchmark output is
explicitly labelled surrogate until executed on real AMAX-5580 hardware.
"""

from .benchmark import (
    DEFAULT_BENCHMARK_HOST_LABEL,
    DEFAULT_BENCHMARK_ITERATIONS,
    DEFAULT_BENCHMARK_WARMUP,
    BenchmarkRunResult,
    compute_latency_percentiles,
    run_amax_cpu_benchmark,
    run_amax_cpu_benchmark_scenario,
)

__all__ = [
    "BenchmarkRunResult",
    "DEFAULT_BENCHMARK_HOST_LABEL",
    "DEFAULT_BENCHMARK_ITERATIONS",
    "DEFAULT_BENCHMARK_WARMUP",
    "compute_latency_percentiles",
    "run_amax_cpu_benchmark",
    "run_amax_cpu_benchmark_scenario",
]
