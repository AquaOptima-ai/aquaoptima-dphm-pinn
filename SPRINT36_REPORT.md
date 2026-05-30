# AOPSO Sprint 36 — Pillar A Linux deployment package (offline / shadow only)

SPRINT36_STATUS: COMPLETE
SPRINT36_GATE: PASS

## Goal

Wrap the already-validated, already-ONNX-packaged Sprint-35 Pillar-A health
detector into a **reproducible Linux deployment package** for the
AMAX-8580 / AMAX-5580 linux/amd64 CPU-only profile:

* a multi-stage Dockerfile that builds a read-only, non-root, CPU-only
  inference sidecar (no torch, no CUDA, no network at runtime);
* a contracts-SDK `DeploymentPackageManifest` (audit-evidence) that wraps
  the Sprint-35 `ModelArtifactRecord` and passes the AMAX-5580 Edge
  package validator with zero errors;
* a shadow-mode runbook that states explicitly the package is offline /
  shadow only and **not** authorized to control the site;
* a serving entrypoint whose scoring is bit-faithful to the Sprint-35
  ONNX wrapper, proven in-process so correctness does not depend on
  Docker being available.

## What this sprint IS and IS NOT

* **IS**: a Linux container image (linux/amd64) running the Sprint-35
  ONNX detector as a read-only, offline inference sidecar; a
  contracts-SDK `DeploymentPackageManifest`; a shadow-mode runbook; a
  test suite proving the package validates and the boundary holds.
* **IS NOT**: live site integration. No setpoints, no actuation, no
  control language, no live OT binding, no write path. First deployment
  is **shadow / offline only**. Packaging is **not** deployment
  authorization — a separate safety qualification is still required.

## Hard safety boundary (non-negotiable)

* No setpoints, no actuation, no control surface, no live OT binding,
  no write path.
* The container image is designed to run with:
  ```
  --read-only --network=none --user 1001:1001 \
  --cap-drop=ALL --security-opt=no-new-privileges
  ```
  These flags are smoke-tested below; the container produces evidence
  files and exits zero with all of them set.
* No `aquaoptima.edge` / `aquaoptima_contracts.edge` import in the
  serving module. No write-capable connector anywhere in the package.
  The contracts SDK was consumed read-only; no SDK file was modified.
* March 2026 stays a frozen holdout. This sprint packages an existing
  artifact; it does not re-fit. The Sprint-35 leakage isolation result
  is the underlying audit anchor.

## Files added or changed

### Serving entrypoint (in-process and container)

* `src/aquaoptima/advisory/packaging/serve_advisory.py` (new) —
  read-only / offline / advisory-only batch scorer. Loads the .onnx +
  sidecar, reads telemetry from CSV or JSON-records, writes a per-row
  evidence CSV (`row_index`, `detector_recon_error`,
  `detector_anomaly_score`, `detector_flag`) plus a per-run JSON summary
  to a configured evidence sink path.
* `scripts/serve_pillarA_advisory.py` (new) — thin ENTRYPOINT shim the
  container calls.
* `src/aquaoptima/advisory/packaging/__init__.py` (updated) — re-export
  the new serving entry points; deployment_manifest exports are exposed
  via lazy `__getattr__` so the runtime container's torch-free import
  graph stays clean (the deployment manifest builder transitively needs
  `aquaoptima.dataio.telemetry`, which depends on `torch`; the runtime
  scorer never touches it).
* `src/aquaoptima/advisory/packaging/onnx_export.py` (updated) — `torch`
  and `FittedHealthDetector` made into lazy / TYPE_CHECKING imports so
  the scoring path (used inside the container) does not pull torch.

### Container image

* `deploy/pillarA_advisory/Dockerfile` (new) — multi-stage
  `python:3.12-slim` (`--platform=linux/amd64`), pip-installs the
  vendored requirements, COPYs the Sprint-35 .onnx + sidecar + the
  advisory package + the entrypoint shim, creates UID/GID 1001 `aopso`
  user, switches `USER 1001:1001`, declares `VOLUME ["/telemetry",
  "/evidence"]`, and sets the entrypoint to the advisory CLI.
* `deploy/pillarA_advisory/requirements.txt` (new) — pinned, CPU-only:
  `numpy==1.26.4`, `onnxruntime==1.20.1`, `pandas==2.2.2`. No torch.
  No CUDA. No TensorRT.
* `deploy/pillarA_advisory/.dockerignore` (new) — strict `*`-then-allowlist
  so only the files explicitly named by the Dockerfile reach the build
  context.

### Build script

* `scripts/build_pillarA_image.sh` (new) — detects `docker` or `podman`,
  builds against the repo-root context, records the resulting image
  digest. If no builder is present it exits 0 with
  `skipped_no_builder:<reason>` so the scorecard captures an honest "no
  builder" outcome.

### Deployment manifest

* `src/aquaoptima/advisory/packaging/deployment_manifest.py` (new) —
  composes the contracts-SDK `DeploymentPackageManifest`:
  * `ContractEnvelope(schema_family="manifest", schema_name="deployment_package_manifest", schema_version=1.0.0, sdk_version=0.1.0, created_by_component="ai_server")`
  * `package_id = "aopso-pillarA-linux-advisory-package"`
  * `package_version = "sprint36-r0"`
  * `PackageSafetyDeclaration` with the canonical all-True
    `default_safety_flag_set()` and matching `package_id` /
    `capability_requirement`
  * `model_artifacts = (sprint-35 ModelArtifactRecord re-built from the
    on-disk artifact record JSON, with the sha256 of the .onnx
    re-verified end-to-end)`
  * one `ArtifactManifest` for the sidecar JSON (role
    `"audit_evidence"`)
  * `notes` use neutral advisory phrasing only; the SDK's forbidden-
    vocabulary check rejects any control / setpoint / dispatch wording
    before construction.
* `data/eval/packaging/pillarA_deployment_package_manifest.json` (new) —
  serialized manifest.

### Shadow-mode runbook

* `docs/product/aopso-health-efficiency-ab/08-pillarA-linux-deployment-runbook.md`
  (new) — how to build, distribute, and run the container in shadow
  mode on the AMAX-5580 box; documents the enforced-boundary
  `docker run` line, the evidence sink layout, and the explicit
  "not control-authorized" framing.

### Scorecard & tests

* `scripts/sprint36_deployment_package_scorecard.py` (new) — composes
  and writes the Sprint-36 acceptance-gate scorecard.
* `data/eval/packaging/sprint36_deployment_package_scorecard.json` (new) —
  the resulting scorecard.
* `tests/advisory/test_sprint36_deployment_package.py` (new) — 12 focused
  tests proving the entrypoint reproduces Sprint-35 scores, the manifest
  passes the AMAX-5580 Edge validator, the on-disk .onnx sha256 matches
  the model record, the contracts SDK rejects a deliberately
  control-flavoured note, and the Dockerfile / requirements / build
  script / .dockerignore are well-formed.

## Manifest validation result

```
package_id      = aopso-pillarA-linux-advisory-package
package_version = sprint36-r0
schema_family   = manifest
safety_flags    = all-True (offline, read_only, no_write, no_control,
                  no_live_ot_binding, no_setpoint_output, packaging_audit_only)
model_artifacts = 1  (framework=onnx, sha256=787c2f1f... 3747 bytes)
artifacts       = 1  (sidecar JSON, role=audit_evidence)

validate_deployment_package_for_edge(manifest, default_amax_edge_capability_declaration())
  accepted                     = True
  errors                       = []
  warnings                     = []
  profile_id                   = advantech_amax_5580
  rejected_accelerator_tokens  = []
  rejected_frameworks          = []
```

## Serving-parity result

In-process, on a 256-row synthetic fixture seeded with both
in-distribution and out-of-distribution rows:

```
flags_identical                = True
max_abs_score_diff_vs_sprint35 = 0.0
n_rows                         = 256
```

Container-vs-in-process bit-for-bit check (1000-row synthetic frame):
flags identical, recon-error diff `0.0`, anomaly-score diff `0.0`.

## CPU latency (AMAX-5580 surrogate)

`onnxruntime` CPU EP, `intra=1 inter=1`:

| Metric | Value |
| --- | --- |
| Single-row mean | 2.72 ms |
| Single-row p50 | 2.68 ms |
| Single-row p99 | 3.35 ms |
| Batch (256 rows) | 2.41 ms |

These are surrogate numbers on this build host; the AMAX-5580 CPU
profile is x86_64 with the same ONNX graph, so the per-row envelope is
comparable. The pillar's frame cadence is on the order of 10s+ so the
sidecar runs cleanly in batch / sliding-window mode.

## Container image

| Field | Value |
| --- | --- |
| Tag | `aopso/pillara-advisory:sprint36-r0` |
| Platform | `linux/amd64` |
| Base | `python:3.12-slim` |
| Digest | `sha256:32cc3f7bf74ed4e52f38dda0837a103dbf4b3ffcd8ab330d76efd5a859aedc79` |
| Size | ~553 MB |
| User | `aopso:aopso` (UID/GID 1001:1001) |
| Network | designed for `--network=none` |
| FS | designed for `--read-only` |

Container smoke test (with `--read-only --network=none --user 1001:1001
--cap-drop=ALL --security-opt=no-new-privileges`): wrote
`pillarA_advisory_evidence.csv` and `pillarA_advisory_evidence_summary.json`
into the evidence sink, exited zero, produced bit-identical scores to the
in-process Sprint-35 wrapper.

## Acceptance gate (honest)

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Dockerfile + .dockerignore + build script well-formed, linux/amd64, USER 1001:1001, read-only-friendly | PASS |
| 2 | Serving entrypoint reproduces Sprint-35 ONNX scores in-process (flags identical, score diff <= 1e-12) | PASS |
| 3 | `DeploymentPackageManifest` validates against AMAX-5580 Edge declaration (zero errors, safety flags all-True) | PASS |
| 4 | Boundary holds (no control-plane network, no write path, runs read-only, forbidden-token + governance scans clean) | PASS |
| 5 | Shadow-mode runbook present, explicitly shadow / offline / not-control-authorized | PASS |

`SPRINT36_GATE: PASS`

A FAIL would have been a valid, honest outcome — none was needed.

## Test results

* `python -m pytest tests/advisory/test_sprint36_deployment_package.py -q`
  → **12 passed**.
* `python -m pytest tests/advisory -q` → **245 passed** (no regressions
  versus the Sprint-35 baseline).
* `python -m pytest tests -q` → see in-line run below.

## Cannot claim

This sprint does **not** authorize any of the following:

* Site control of any kind. Packaging is not deployment authorization.
  The site PLC retains direct VFD / pump / actuator authority.
* Live OT binding. The container is offline. The serving module does
  not import any write-capable connector and does not open a network
  socket. `--network=none` is the enforced runtime posture.
* Setpoint, dispatch, command, or actuation emission. The evidence sink
  carries only per-row health flags + reconstruction error +
  anomaly score. There is no API that emits a control payload.
* AMAX-5580 hardware validation. This package targets the AMAX profile
  and the image was built linux/amd64, but no on-device test has been
  run. AMAX HIL evidence is a future sprint, separately gated.
* Field readiness. First deployment is shadow / offline against
  exported or read-only-tapped telemetry. Anything beyond that requires
  its own safety qualification.
