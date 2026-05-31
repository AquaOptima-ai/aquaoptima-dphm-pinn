"""Sprint 47 — AMAX CPU dPHM-PINN benchmark / packaging smoke CLI.

Run from the repo root::

    python scripts/run_amax_cpu_benchmark.py --output artifacts/amax_cpu_benchmark_report.json

The CLI executes the canonical Sprint 47 benchmark scenarios on CPU,
prints a concise human-readable summary, and (optionally) writes a
deterministic JSON report through the SDK's canonical writer.

Defaults: surrogate host mode, CPU-only. No external services /
credentials / network / PLC / SCADA / AMAX hardware required. The
harness must not perform live OT binding, PLC/PAC/SCADA write, command
emission, setpoint output, or control-loop closure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aquaoptima.edge.benchmark import (
    DEFAULT_BENCHMARK_HOST_LABEL,
    DEFAULT_BENCHMARK_ITERATIONS,
    DEFAULT_BENCHMARK_WARMUP,
    run_amax_cpu_benchmark,
)
from aquaoptima_contracts.base.serialization import write_canonical_json


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Sprint 47 AMAX CPU dPHM-PINN benchmark / packaging "
            "smoke harness. Host-derived runs are surrogate until "
            "executed on real AMAX-8580 hardware."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional output path for the deterministic JSON report. "
            "When omitted, the CLI prints only the human-readable summary."
        ),
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_BENCHMARK_ITERATIONS,
        help="Measured iterations per scenario (default: %(default)s).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=DEFAULT_BENCHMARK_WARMUP,
        help="Warmup iterations per scenario (default: %(default)s).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Deterministic seed for torch / synthetic inputs (default: %(default)s).",
    )
    parser.add_argument(
        "--host-label",
        type=str,
        default=DEFAULT_BENCHMARK_HOST_LABEL,
        help=(
            "Host identifier recorded in the metrics record. Defaults "
            "to a surrogate developer-host label."
        ),
    )
    parser.add_argument(
        "--package-manifest-reference",
        type=str,
        default="",
        help=(
            "Optional package manifest reference (e.g. a Sprint 44 "
            "deployment package id) recorded on every report."
        ),
    )
    parser.add_argument(
        "--mark-real-hardware",
        action="store_true",
        help=(
            "Mark the run as real AMAX-8580 hardware evidence instead "
            "of surrogate. Off by default — surrogate evidence is the "
            "Sprint 47 expectation."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    result = run_amax_cpu_benchmark(
        iterations=args.iterations,
        warmup=args.warmup,
        seed=args.seed,
        host_label=args.host_label,
        surrogate_hardware=not args.mark_real_hardware,
        package_manifest_reference=args.package_manifest_reference,
    )

    print("Sprint 47 AMAX CPU dPHM-PINN benchmark / packaging smoke")
    print("(no live OT binding, no PLC/PAC/SCADA write, no command emission, no setpoint output)")
    print(
        "{:<28} {:>8} {:>10} {:>10} {:>10} {:<20}".format(
            "scenario", "iters", "p50_ms", "p95_ms", "p99_ms", "cadence"
        )
    )
    for report in result.reports:
        m = report.metrics
        print(
            "{:<28} {:>8} {:>10.3f} {:>10.3f} {:>10.3f} {:<20}".format(
                report.scenario.scenario_id,
                m.iterations,
                m.latency_p50_ms,
                m.latency_p95_ms,
                m.latency_p99_ms,
                report.cadence_classification,
            )
        )
        if not report.surrogate_hardware:
            print(f"  (real-hardware run: host={m.host_label})")
        else:
            print(f"  (surrogate evidence; host={m.host_label})")

    if args.output is not None:
        payload = {
            "sprint": 47,
            "harness": "amax_cpu_benchmark_packaging_smoke",
            "surrogate_hardware": not args.mark_real_hardware,
            "reports": [r.to_dict() for r in result.reports],
            "safety": [
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ],
        }
        write_canonical_json(payload, args.output)
        print(f"wrote {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
