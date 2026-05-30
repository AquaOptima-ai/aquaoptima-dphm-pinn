# AOPSO Sprint 36 — Pillar A Linux deployment runbook (shadow / offline)

This runbook describes how to **package**, **distribute**, and **run** the
Pillar-A health detector on an AMAX-5580 (linux/amd64, CPU-only) target as
a read-only, offline, advisory-only sidecar.

> **This document does not authorize site control or actuation.** The
> Pillar-A package is a *shadow / offline* advisory artifact. Its first
> deployment is read-only or telemetry-replay only. Packaging is **not**
> deployment authorization — a separate safety qualification must clear
> the package before any live operational use, and even then the site
> PLC retains direct VFD / pump / actuator authority.

---

## 1. What is in the package

| Artifact | Path (repo) | Purpose |
| --- | --- | --- |
| ONNX detector | `data/eval/packaging/pillarA_health_detector.onnx` | Sprint-35 autoencoder forward pass (CPU-only) |
| Sidecar | `data/eval/packaging/pillarA_health_detector.sidecar.json` | Axis order, standardisation constants, flag threshold |
| ModelArtifactRecord | `data/eval/packaging/pillarA_onnx_artifact_record.json` | Sprint-35 audit-evidence record |
| DeploymentPackageManifest | `data/eval/packaging/pillarA_deployment_package_manifest.json` | Sprint-36 SDK audit-evidence shape |
| Dockerfile | `deploy/pillarA_advisory/Dockerfile` | linux/amd64, python:3.12-slim, non-root |
| `.dockerignore` | `deploy/pillarA_advisory/.dockerignore` | Strict include-list |
| Runtime pins | `deploy/pillarA_advisory/requirements.txt` | `onnxruntime`, `numpy`, `pandas` only |
| Build script | `scripts/build_pillarA_image.sh` | Detects docker / podman, builds, records digest |
| Serving CLI shim | `scripts/serve_pillarA_advisory.py` | Container ENTRYPOINT |
| Advisory entry module | `src/aquaoptima/advisory/packaging/serve_advisory.py` | Read-only batch scoring logic |

## 2. Safety posture (non-negotiable)

* **Advisory only.** The container produces per-row reconstruction error,
  anomaly score, and a binary health flag. It produces NO setpoint, NO
  dispatch, NO command, NO actuation, NO control payload.
* **Offline.** No network at runtime. The Dockerfile does not install any
  HTTP / MQTT / Modbus / OPC-UA / message-broker client. The image is
  designed to run with `--network=none`.
* **Read-only.** The container is designed to run with `--read-only`. The
  ONLY writable mount is the evidence sink (`/evidence`). The site PLC
  retains direct VFD / pump / actuator authority.
* **Non-root.** The image creates a system user `aopso:aopso` (UID/GID
  1001:1001) and switches to it before declaring the ENTRYPOINT.
* **CPU-only.** The runtime image carries `onnxruntime` CPU; no torch,
  no CUDA, no TensorRT, no GPU dependency.
* **First deployment is shadow / offline.** Telemetry is either an
  exported snapshot or a read-only tap on the historian. Evidence is
  written to a local directory or read-only-replayed against the
  Sprint-34 unified offline evidence pipeline.

## 3. Build the image

```bash
# from the repo root
scripts/build_pillarA_image.sh \
    --tag aopso/pillara-advisory:sprint36-r0 \
    --digest-file build/pillarA_image_digest.txt
```

The script:

1. Picks `docker` or `podman` from `PATH`. If neither is present it
   reports `skipped_no_builder:<reason>` and exits 0 so CI can capture
   an honest "no builder available" outcome.
2. Builds against `deploy/pillarA_advisory/Dockerfile` with the repo
   root as build context (the `.dockerignore` keeps the context tiny).
3. Tags the image with the supplied (or default) tag and inspects the
   resulting digest into the digest sink file.

## 4. Run the container (shadow / offline)

The enforced-boundary `docker run` line is:

```bash
docker run --rm \
    --read-only \
    --network=none \
    --user 1001:1001 \
    --cap-drop=ALL \
    --security-opt=no-new-privileges \
    -v "$PWD/telemetry":/telemetry:ro \
    -v "$PWD/evidence":/evidence \
    aopso/pillara-advisory:sprint36-r0 \
    --onnx         /app/model/pillarA_health_detector.onnx \
    --sidecar      /app/model/pillarA_health_detector.sidecar.json \
    --input        /telemetry/input.csv \
    --evidence-dir /evidence
```

Notes:

* `--read-only` enforces an immutable root filesystem.
* `--network=none` removes the container from every network namespace —
  the entrypoint cannot reach a control plane even if a future commit
  accidentally added a client.
* `--cap-drop=ALL` plus `--security-opt=no-new-privileges` strips the
  container down to the minimum.
* The `/telemetry` mount is bind-mounted **read-only**. The `/evidence`
  mount is the ONLY writable path and is the evidence sink.

## 5. Inputs and outputs

### Input (read-only mount)

Either `.csv` or `.json` / `.jsonl` / `.ndjson`. Each row must carry every
axis the sidecar declares (8 axes in the Sprint-35 record), in any column
order; the sidecar's `axes` tuple defines the canonical order.

### Output (evidence sink)

* `pillarA_advisory_evidence.csv` — one row per input row carrying
  `row_index`, `detector_recon_error`, `detector_anomaly_score`,
  `detector_flag`.
* `pillarA_advisory_evidence_summary.json` — per-run summary: input /
  ONNX / sidecar paths, sha256, flag positives count, score
  distribution, and the explicit advisory-boundary block.

## 6. Verify the package without Docker

The serving entrypoint is exercised in-process by
`tests/advisory/test_sprint36_deployment_package.py` — running the
Sprint-36 test suite proves bit-faithful parity with the Sprint-35 ONNX
scoring wrapper, the manifest passes the AMAX-5580 edge validator, and
the on-disk sha256 of the `.onnx` matches the model record. Run:

```bash
python -m pytest tests/advisory/test_sprint36_deployment_package.py -q
```

## 7. Validate the manifest

```bash
python - <<'PY'
import json
from pathlib import Path
from aquaoptima_contracts import (
    DeploymentPackageManifest,
    default_amax_edge_capability_declaration,
    validate_deployment_package_for_edge,
)

path = Path("data/eval/packaging/pillarA_deployment_package_manifest.json")
manifest = DeploymentPackageManifest.from_dict(json.loads(path.read_text()))
result = validate_deployment_package_for_edge(
    manifest, default_amax_edge_capability_declaration()
)
print("accepted:", result.accepted)
print("errors:",   list(result.errors))
print("warnings:", list(result.warnings))
PY
```

The expected output is `accepted: True`, no errors, no warnings.

## 8. CPU latency note (AMAX-5580 profile)

The Sprint-35 ONNX scoring wrapper was profiled CPU-only on a single
thread on the same architecture. Sprint 36 reuses that wrapper verbatim
inside the serving entrypoint, so the per-row latency envelope is the
Sprint-35 envelope plus container start-up. The pillar's frame cadence
(10s+) is comfortably above the per-row inference cost, and the
container is designed to run as a batch / sliding-window scorer rather
than a hot-loop.

## 9. What this runbook is **not**

* Not a control authorization.
* Not a live OT binding plan.
* Not a setpoint / dispatch / actuation rollout.
* Not a substitute for the safety qualification that any future move
  beyond shadow / offline must clear.
