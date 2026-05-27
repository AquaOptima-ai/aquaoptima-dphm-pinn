# Shadow-mode deployment packaging (Sprint 39)

Sprint 39 adds a small, typed, deterministic *export / packaging*
surface for the shadow-mode MVP. It collects per-artifact metadata
(replay datasets, calibration loss reports, advisory audit decisions,
shadow runtime reports) into a single frozen `ShadowDeploymentManifest`
and provides a stdlib-only JSON writer for the manifest itself.

Sprint 39 is **offline / read-only / no-write / no-control / no live
OT binding / no setpoint output / packaging / audit only**. The
"deployment" in `ShadowDeploymentManifest` refers to a *packaging /
audit-evidence bundle* for **shadow-mode MVP** artifacts — **not** to
a live OT deployment, **not** to a service runtime, **not** to a
controller, **not** to an advisory emission layer.

## Where it lives

`src/aquaoptima/dphm/shadow_deployment.py`, re-exported through
`aquaoptima.dphm`.

## Public API

```python
from aquaoptima.dphm import (
    # Frozen dataclasses
    ShadowDeploymentArtifact,
    ShadowDeploymentManifest,
    ShadowDeploymentPackageDiagnostics,
    # Builders / writers
    build_shadow_deployment_manifest,
    write_shadow_deployment_manifest_json,
    # Tokens
    ARTIFACT_KIND_SHADOW_REPLAY,
    ARTIFACT_KIND_DPL_LOSS_REPORT,
    ARTIFACT_KIND_ADVISORY_CONTRACT,
    ARTIFACT_KIND_ADVISORY_DECISIONS,
    ARTIFACT_KIND_SHADOW_RUNTIME_REPORT,
    ARTIFACT_KIND_FILE,
    ARTIFACT_KIND_BLOB,
    SHADOW_DEPLOYMENT_ARTIFACT_KINDS,
    SAFETY_BOUNDARY_PHRASES,
    DEFAULT_CREATED_AT,
    UNKNOWN_VERSION_MARKER,
)
```

`build_shadow_deployment_manifest` signature:

```python
def build_shadow_deployment_manifest(
    package_name: str,
    *,
    package_version: str = "",
    build_id: str = "",
    created_at: str | None = None,
    code_version: str | None = None,
    artifacts: Sequence[Mapping[str, object]] | None = None,
    summary_objects: Sequence[object] | None = None,
    safety_flags: Mapping[str, bool] | None = None,
    references: Mapping[str, Mapping[str, object]] | None = None,
    notes: str = "",
    strict: bool = True,
) -> ShadowDeploymentManifest: ...
```

`write_shadow_deployment_manifest_json` signature:

```python
def write_shadow_deployment_manifest_json(
    manifest: ShadowDeploymentManifest,
    path: str | os.PathLike[str],
) -> pathlib.Path: ...
```

## Concepts

A **manifest** is a frozen `ShadowDeploymentManifest` value carrying:

* `package_name` / `package_version` / `build_id` — operator-facing
  identification fields kept verbatim;
* `created_at` — deterministic timestamp string (defaults to
  `1970-01-01T00:00:00Z` when not supplied so the manifest is
  reproducible regardless of host clock);
* `code_version` — resolved via `importlib.metadata.version` when not
  supplied; falls back to `"unknown"` when the package is not
  installed;
* `artifacts` — tuple of `ShadowDeploymentArtifact` entries in
  deterministic builder-input order;
* `safety_boundary` / `safety_flags` — fixed verbatim safety-boundary
  phrases and a small map of boolean flags that confirm the bundle is
  offline / read-only / no-write / no-control / no live OT binding /
  no setpoint output / packaging-audit-only;
* `references` — cross-sprint summary stats kept verbatim
  (`{name: {key: scalar}}`);
* `diagnostics` — deterministic warnings / errors tuples.

An **artifact** carries `kind`, `name`, optional `artifact_id`,
optional `path` (kept verbatim as a string), optional `sha256` hex
digest, optional `size_bytes`, optional free-form `description`, and
an optional scalar-only `summary` mapping.

Two complementary input paths produce artifacts:

* `artifacts=[...]` — caller supplies one mapping per artifact (see
  schema below) with optional `content` (bytes) and / or `path`. The
  builder hashes the supplied bytes / file content with SHA-256;
* `summary_objects=[...]` — caller supplies a Sprint 35-38 typed
  object directly (`ShadowReplayDataset`, `DPLCalibrationLossReport`,
  `AdvisoryContract`, `ShadowRuntimeReport`); the builder emits a
  summary artifact with deterministic scalar fields.

## Artifact spec schema

| Key           | Type                                  | Required | Notes |
|---------------|---------------------------------------|----------|-------|
| `kind`        | `str` (one of `SHADOW_DEPLOYMENT_ARTIFACT_KINDS`) | yes | |
| `name`        | non-empty `str`                       | yes      | |
| `artifact_id` | `str`                                 | no       | |
| `path`        | `str` / `PathLike`                    | no       | hashed if present and `hash=True` |
| `content`     | `bytes`                               | no       | hashed verbatim; **never embedded** |
| `sha256`      | 64-char lowercase hex `str`           | no       | must match computed hash if any |
| `size_bytes`  | non-negative `int`                    | no       | must match content length if any |
| `description` | `str`                                 | no       | |
| `summary`     | `Mapping[str, scalar]`                | no       | scalar / list-of-scalar only |
| `hash`        | `bool` (default `True`)               | no       | disables hashing when `False` |

Artifact `content` bytes are **only** used for hashing. They are
**never** copied into the manifest itself. Credential-style keys
(`password`, `secret`, `token`, `api_key`, `private_key`, etc.) in
any `summary` / `references` mapping are rejected by the builder.

## Determinism

Every list, tuple, and mapping the builder emits is in a fully
deterministic order:

* `artifacts` follows builder input order (typed summary objects
  first, then file / blob specs in their listed order);
* `safety_boundary` is the fixed `SAFETY_BOUNDARY_PHRASES` tuple;
* `safety_flags` carries a fixed set of boolean keys per build;
* the JSON writer sorts every nested key with `sort_keys=True` and
  uses a two-space indent so the output is diffable.

Calling `build_shadow_deployment_manifest(...)` twice on the same
inputs returns equal manifests; calling
`write_shadow_deployment_manifest_json(...)` twice on equal manifests
produces byte-identical JSON files.

## JSON output shape

```json
{
  "artifacts": [
    {
      "artifact_id": "",
      "description": "",
      "kind": "shadow_runtime_report",
      "name": "shadow_runtime_report",
      "path": "",
      "sha256": "",
      "size_bytes": null,
      "summary": {...}
    }
  ],
  "build_id": "",
  "code_version": "unknown",
  "created_at": "1970-01-01T00:00:00Z",
  "diagnostics": {"errors": [], "warnings": []},
  "notes": "",
  "package_name": "aquaoptima-dphm-shadow-mvp",
  "package_version": "",
  "references": {...},
  "safety_boundary": [...],
  "safety_flags": {...},
  "schema": "aquaoptima.dphm.shadow_deployment_manifest/v1"
}
```

## Strict / non-strict semantics

In strict mode (`strict=True`, default):

* a malformed artifact spec (missing `kind` / `name`, unknown `kind`,
  bad `path` type, non-scalar `summary` value) raises;
* an unsupported `summary_objects` entry raises;
* a supplied `sha256` that does not match the computed hash raises;
* a `safety_flags` override flipping any flag to `False` raises
  (Sprint 39 manifests never claim a live or write-capable bundle).

In non-strict mode (`strict=False`):

* the same conditions record a deterministic error string on
  `ShadowDeploymentManifest.diagnostics.errors` and the offending
  artifact / summary object is omitted from the manifest;
* a path that does not exist on disk records a deterministic warning
  on `diagnostics.warnings` and leaves the artifact with an empty
  `sha256` / `size_bytes`.

Programmer errors — non-string `package_name`, invalid
`safety_flags` override, invalid `references`, non-`Sequence`
artifacts / `summary_objects` — always raise regardless of `strict`.

## Safety boundary

Sprint 39 reaffirms the safety boundary first declared in Sprint 23
and tightened by every shadow-mode sprint since:

- no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter is imported, registered, or polled;
- no write / control / setpoint path is exposed;
- no live OT binding is opened;
- no actuator / write surface is offered;
- no setpoint output is emitted, even when an artifact summarises
  accepted advisory decisions;
- no automatic setpoint recommendation is produced — Sprint 39 only
  **packages audit evidence** for shadow-mode MVP artifacts;
- no dPHM forward solve is invoked;
- no training loop / optimiser integration is performed;
- no ONNX / TensorRT / Jetson deployment is performed;
- no production savings / control claim is made;
- no credentials, API keys, tokens, passwords, secrets, or
  connection strings are read, hashed, or embedded;
- the JSON writer is the **only** filesystem write; it writes the
  manifest JSON to the caller-supplied path and nothing else.

The deliberate framing is **packaging / audit only**: Sprint 39 is
the seam where a future advisory / supervised-control deployment
would consume the manifest as offline evidence. That consumption is
out of scope here.

## Worked example

```python
from aquaoptima.dphm import (
    ADVISORY_AXIS_PUMP_SPEED,
    AdvisoryProposal, AdvisoryRule,
    ARTIFACT_KIND_FILE,
    build_advisory_contract,
    build_shadow_deployment_manifest,
    build_shadow_replay_dataset,
    build_telemetry_tag_map,
    make_pump_network,
    run_shadow_runtime,
    TELEMETRY_AXIS_EDGE_FLOW, TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_TARGET_EDGE, TELEMETRY_TARGET_NODE,
    TelemetryTagSpec,
    write_shadow_deployment_manifest_json,
)

network = make_pump_network()
tag_map = build_telemetry_tag_map(
    [
        TelemetryTagSpec("PT1", TELEMETRY_TARGET_NODE, 1, "pressure", "m"),
        TelemetryTagSpec("FT1", TELEMETRY_TARGET_EDGE, 1, "flow", "m3/s"),
    ],
    network,
)
replay = build_shadow_replay_dataset(
    [{"timestamp": 0.0, "PT1": 10.5, "FT1": 0.020}], tag_map,
)
predictions = [
    {
        TELEMETRY_AXIS_NODE_PRESSURE: {1: 10.6},
        TELEMETRY_AXIS_EDGE_FLOW: {1: 0.019},
    }
]
contract = build_advisory_contract(
    name="pump-envelope",
    allow_rules=[
        AdvisoryRule(
            axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
            min_value=0.10, max_value=0.95, max_abs_delta=0.20,
        )
    ],
)
report = run_shadow_runtime(
    replay, predictions,
    advisory_contract=contract,
    proposals_by_frame=[[]],
)

manifest = build_shadow_deployment_manifest(
    "aquaoptima-dphm-shadow-mvp",
    package_version="0.1.0",
    build_id="ci-2026-05-23",
    created_at="2026-05-23T00:00:00Z",
    summary_objects=[replay, report.loss_report, contract, report],
)
out_path = write_shadow_deployment_manifest_json(
    manifest, "build/manifest.json"
)

# `manifest` is a frozen value the caller can serialise, hash, diff,
# and review offline. `out_path` carries only the manifest JSON —
# no live binding opened, no setpoint emitted, packaging/audit only.
```
