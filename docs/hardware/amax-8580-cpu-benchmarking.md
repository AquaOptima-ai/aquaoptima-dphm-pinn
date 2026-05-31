# AMAX-8580 CPU Benchmark / Packaging Smoke Harness (Sprint 47)

Sprint 47 ships an **offline, CPU-only** dPHM-PINN benchmark and
packaging smoke harness for the Advantech AMAX-8580 primary Edge target.
This document is the audit-only companion to:

- `src/aquaoptima_contracts/edge/benchmark.py` — SDK dataclasses
  (`AMAXBenchmarkScenario`, `AMAXBenchmarkMetrics`,
  `AMAXBenchmarkReport`) and the
  `classify_supervisory_cadence` evidence helper;
- `src/aquaoptima/edge/benchmark.py` — runtime helper that drives a
  `DPHMPINN` over the canonical branch / single-loop / pump fixtures;
- `scripts/run_amax_cpu_benchmark.py` — CLI that prints a concise
  summary and (optionally) writes a deterministic JSON report.

## What this sprint proves

The harness produces **surrogate** evidence that:

- a small `DPHMPINN` can be instantiated and run forward-only on a
  developer host without CUDA, TensorRT, or any GPU dependency;
- p50 / p95 / p99 latency and a peak-RSS envelope can be captured
  deterministically with stdlib-only tooling
  (`time.perf_counter`, `statistics`, `resource`);
- the SDK contract shapes (`AMAXBenchmarkScenario`,
  `AMAXBenchmarkMetrics`, `AMAXBenchmarkReport`) round-trip through
  canonical JSON byte-for-byte;
- the harness can be re-run on actual AMAX-8580 hardware later
  without any code change (the `--mark-real-hardware` flag flips the
  surrogate evidence flag).

## What this sprint explicitly does NOT prove

Host-derived runs are **surrogate** until executed on real AMAX-8580
hardware. The harness must never be interpreted as:

- a real-time control safety proof;
- a guarantee about CODESYS Linux Control V3 SP20 co-tenancy with the
  PyTorch process on AdvLinuxTU;
- a guarantee about Python `>= 3.10` wheel availability on Ubuntu 18
  / AdvLinuxTU;
- a guarantee about modern PyTorch CPU wheel glibc compatibility on
  AdvLinuxTU;
- a write, dispatch, actuation, setpoint, or control surface of any
  kind.

## Cadence classification

`classify_supervisory_cadence(p95_ms)` is an **evidence classifier**.
It maps a measured p95 latency to one of:

- `sub_1s_supervisory` for `p95 <= 1000 ms`;
- `sub_5s_supervisory` for `1000 < p95 <= 5000 ms`;
- `sub_60s_supervisory` for `5000 < p95 <= 60000 ms`;
- `slower_than_60s` for `p95 > 60000 ms`.

The classification is **not** a control-loop guarantee. AquaOptima
Edge does not own a control loop. The site PLC / pump-station PLC
retains direct VFD / pump / actuator authority.

## Canonical scenarios

The Sprint 47 benchmark scenario tuple is stable and ordered:

1. `amax_cpu_branch_smoke` — branch fixture (4 nodes, 3 edges);
2. `amax_cpu_single_loop_smoke` — single-loop fixture (4 nodes, 4 edges);
3. `amax_cpu_pump_smoke` — pump fixture (3 nodes, 2 edges).

Each scenario uses sequence length 32 (matching the Sprint 3 SCADA
window), batch size 1, hidden dim 16, framework `pytorch_cpu`, and
thread count 1. The scenario tuple is intentionally tiny so the
harness completes in seconds on a developer host and remains cheap
enough for CI.

## Running the CLI

From the repo root:

```bash
python scripts/run_amax_cpu_benchmark.py \
    --output artifacts/amax_cpu_benchmark_report.json \
    --iterations 3 \
    --warmup 1
```

The CLI prints a per-scenario table and writes a deterministic JSON
report through the SDK's canonical writer. Host-derived runs default
to surrogate evidence; pass `--mark-real-hardware` only when the run
is executed on an actual AMAX-8580 device.

## Boundary (reaffirmed)

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop;
- no HTTP / network / database / message-broker code added in this
  sprint;
- no Edge Runtime daemon / service implementation;
- no AI / Optimization Server runtime, no Operations Console runtime;
- no live PLC/SCADA/OPC UA/Modbus client;
- no CUDA / TensorRT runtime dependency;
- no model artifact loading from disk;
- no inline model weights;
- Sprint 48 should remain a **read-only** PLC/SCADA integration
  contract gate after Sprint 47 passes.
