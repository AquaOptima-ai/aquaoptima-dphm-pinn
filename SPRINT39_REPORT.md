# Sprint 39 — shadow-mode deployment packaging

## Goal

Add a small, typed, deterministic *export / packaging* surface for
the shadow-mode MVP. The packaging surface collects metadata for
Sprint 35 replay datasets, Sprint 36 calibration loss reports,
Sprint 37 advisory contracts / audit decisions, and Sprint 38
shadow runtime reports into a single frozen
`ShadowDeploymentManifest` and a stdlib-only JSON writer for the
manifest itself.

Sprint 39 is **offline / read-only / no-write / no-control / no live
OT binding / no setpoint output / packaging / audit only**. It is
**not** a live deployment service, **not** a controller, **not** a
container builder, **not** a CI/CD pipeline, **not** a training
loop, and **not** an advisory emission layer. The "deployment" in
`ShadowDeploymentManifest` refers to a packaging / audit-evidence
bundle for **shadow-mode MVP** artifacts only.

## Files changed

- `src/aquaoptima/dphm/shadow_deployment.py` (new module) — frozen
  dataclasses (`ShadowDeploymentPackageDiagnostics`,
  `ShadowDeploymentArtifact`, `ShadowDeploymentManifest`), plus the
  public builder `build_shadow_deployment_manifest` and the JSON
  writer `write_shadow_deployment_manifest_json`. Stdlib-only
  (`hashlib`, `json`, `os`, `pathlib`, `dataclasses`, `typing`,
  `importlib.metadata` for best-effort code-version probing).
- `src/aquaoptima/dphm/__init__.py` (updated) — re-exports the new
  dataclasses, builder, writer, artifact-kind constants, the safety
  boundary phrases tuple, the deterministic timestamp default, and
  the unknown-version marker. No existing export changes.
- `tests/dphm/test_shadow_deployment.py` (new) — focused tests
  covering the public surface, frozen dataclasses, minimal build,
  artifact hashing from bytes and from a local file, JSON writer
  determinism, strict / non-strict diagnostics, Sprint 35-38 typed
  summary integration, safety-flag override semantics, references
  validation, credential-key rejection, "no live adapter substring"
  enforcement, and docs / report evidence.
- `docs/shadow-deployment.md` (new) — Sprint 39 packaging surface
  documentation: public API, artifact spec schema, deterministic
  ordering, strict / non-strict semantics, the reaffirmed safety
  boundary, and a worked example.
- `SPRINT39_REPORT.md` (this file).

No other source file is touched. The new module imports only
Sprint 35-38 dataclasses and the standard library. No new
third-party dependency, no parser / solver / IO / training module
modification.

## API design

Three frozen dataclasses:

- `ShadowDeploymentPackageDiagnostics(warnings: tuple[str, ...] = (),
  errors: tuple[str, ...] = ())` — identical surface shape to
  Sprint 34-38 diagnostics.
- `ShadowDeploymentArtifact(kind, name, artifact_id="", path="",
  sha256="", size_bytes=None, description="", summary={})` —
  per-artifact metadata.
- `ShadowDeploymentManifest(package_name="", package_version="",
  build_id="", created_at=DEFAULT_CREATED_AT,
  code_version=UNKNOWN_VERSION_MARKER, artifacts=(),
  safety_boundary=SAFETY_BOUNDARY_PHRASES, safety_flags={},
  references={}, notes="",
  diagnostics=ShadowDeploymentPackageDiagnostics())` — top-level
  manifest.

Two public functions:

- `build_shadow_deployment_manifest(package_name, *,
  package_version="", build_id="", created_at=None,
  code_version=None, artifacts=None, summary_objects=None,
  safety_flags=None, references=None, notes="", strict=True) ->
  ShadowDeploymentManifest`.
- `write_shadow_deployment_manifest_json(manifest, path) ->
  pathlib.Path`.

Plus seven artifact-kind constants
(`ARTIFACT_KIND_SHADOW_REPLAY`, `ARTIFACT_KIND_DPL_LOSS_REPORT`,
`ARTIFACT_KIND_ADVISORY_CONTRACT`,
`ARTIFACT_KIND_ADVISORY_DECISIONS`,
`ARTIFACT_KIND_SHADOW_RUNTIME_REPORT`, `ARTIFACT_KIND_FILE`,
`ARTIFACT_KIND_BLOB`), the kinds tuple
`SHADOW_DEPLOYMENT_ARTIFACT_KINDS`, the
`SAFETY_BOUNDARY_PHRASES` tuple, the `DEFAULT_CREATED_AT` string,
and the `UNKNOWN_VERSION_MARKER` string — all re-exported through
`aquaoptima.dphm`.

## Package / manifest behaviour summary

Per call, `build_shadow_deployment_manifest` executes the following
deterministic steps:

1. Type-check the required / optional fields. Programmer errors
   always raise (non-string `package_name`, empty `created_at`,
   non-bool / unknown `safety_flags` override).
2. Resolve `code_version` via `importlib.metadata.version` when not
   supplied, falling back to `UNKNOWN_VERSION_MARKER`.
3. Resolve the safety-flag mapping. The default set documents that
   the bundle is offline / read-only / no-write / no-control / no
   live OT binding / no setpoint output / packaging-audit-only.
   Overrides may only relax to `True`; any `False` is rejected.
4. Walk `summary_objects` (recognised Sprint 35-38 typed objects)
   in order, emitting one summary artifact per recognised object
   with a deterministic scalar `summary` mapping.
5. Walk `artifacts` (caller-supplied artifact specs) in order. For
   each spec: hash supplied `content` bytes with SHA-256; if the
   spec carries a `path` that exists on disk, stream-hash it with
   SHA-256 and record the file size. Pre-supplied `sha256` /
   `size_bytes` are cross-checked against the computed value and
   the mismatch is rejected.
6. Reject every `summary` / `references` key whose lowercased form
   contains a credential-style fragment (`password`, `secret`,
   `token`, `api_key`, `private_key`, `credential`,
   `connection_string`, `conn_str`).
7. Return a frozen `ShadowDeploymentManifest`. The artifacts tuple
   is in deterministic builder-input order (typed summaries first,
   then caller-supplied specs).

`write_shadow_deployment_manifest_json` is a deterministic
serialiser:

* `json.dumps(payload, sort_keys=True, indent=2,
  ensure_ascii=False)`;
* trailing newline;
* parent directories created if necessary;
* one and only one file written — the manifest JSON at the
  caller-supplied path.

Calling `build_shadow_deployment_manifest(...)` twice on the same
inputs returns equal manifests; calling
`write_shadow_deployment_manifest_json(...)` twice on equal
manifests produces byte-identical JSON files.

## Verification outputs

- `python -m pip install -e .` — succeeded.
- `import aquaoptima` resolves to the in-repo `src/aquaoptima`
  package.
- `python -m pytest tests/dphm/test_shadow_deployment.py -q` —
  passes (focused Sprint 39 tests covering the public surface,
  frozen dataclasses, minimal build, artifact hashing from bytes
  and from a local file, JSON writer determinism, strict /
  non-strict diagnostics, summary-object integration, safety-flag
  override semantics, references validation, credential-key
  rejection, no live adapter substring enforcement, docs / report
  evidence).
- `python -m pytest tests/dphm tests/models -q` — passes (Sprint 39
  additions do not regress Sprint 1-38 tests).
- `python -m pytest -q` — full suite passes.
- `python -m compileall src tests` — passes.
- `git diff --check` — clean.
- `wntr` import — works.
- Secret scan over changed files — no private keys, API keys,
  passwords, tokens, secrets, credentials, or connection strings.

## Safety boundary / limitations

Sprint 39 deliberately preserves the offline / read-only / no-write
/ no-control / no live OT binding / no setpoint output /
packaging-audit-only boundary established in Sprint 23 and
tightened through Sprints 34-38:

- no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter is imported, registered, or polled;
- no write / control / setpoint path is exposed;
- no live OT binding is opened;
- no actuator / write surface is offered;
- no setpoint output is emitted, even when an artifact summarises
  accepted advisory decisions;
- no automatic setpoint recommendation is produced — Sprint 39
  only **packages audit evidence** for shadow-mode MVP artifacts;
- no dPHM forward solve is invoked;
- no training loop / optimiser integration is performed;
- no ONNX / TensorRT / Jetson deployment is performed;
- no container, image, CI/CD pipeline, or service runtime is
  produced;
- no production savings / control claim is made;
- no credentials, API keys, tokens, passwords, secrets, or
  connection strings are read, hashed, or embedded in the manifest
  — credential-style keys in any `summary` / `references` mapping
  are rejected by the builder;
- the JSON writer is the **only** filesystem write performed; it
  writes the manifest JSON to the caller-supplied path and nothing
  else.

Limitations:

- The packaging surface is intentionally schema-light: artifacts
  are referenced by `path` / `name` / `sha256` / `size_bytes`, not
  copied or vendored into the manifest. Caller-supplied `content`
  bytes are hashed verbatim but never stored.
- Code-version resolution uses `importlib.metadata.version` only;
  there is no VCS / commit-hash probing. A future sprint can
  layer that on without changing the public API.
- The `summary_objects` extractor table covers Sprint 35-38 typed
  classes only; a caller wishing to summarise a custom object
  must supply an explicit artifact spec with a scalar `summary`.
- The JSON schema id (`aquaoptima.dphm.shadow_deployment_manifest/v1`)
  is part of the public surface; a future schema change would
  bump the version suffix.

## Next sprint recommendation

Two options, both compatible with the offline / read-only /
no-write / no-control boundary and explicitly oriented toward
**Phase 2 advisory / supervised-control product planning**:

1. **Phase 2 advisory product plan & operator-sign-off scaffolding**.
   Add an offline `AdvisoryOperatorSignoff` value surface that
   wraps a `ShadowDeploymentManifest` plus an operator decision
   record (`reviewer`, `decision`, `notes`, `signed_at`) and a
   deterministic JSON serialiser. Still **offline** and **audit
   only** — no live binding, no setpoint output — but it makes the
   trust-boundary handoff for a future advisory deployment
   reviewable on disk. This unblocks Phase 2 product planning
   (what does the operator-in-the-loop UX look like?) without
   touching the live OT seam.
2. **Shadow-mode regression bundle differ**. Add a stdlib-only
   `diff_shadow_deployment_manifests(old, new)` helper that
   reports per-artifact sha256 / size / summary deltas. Pairs
   with option 1 because the operator-sign-off record only makes
   sense if the operator can see what changed between two
   manifests.

Recommended: option 1 first (cheap, opens the formal
operator-in-the-loop boundary required by Phase 2 advisory /
supervised-control planning), then option 2 once operator
sign-off records exist and need to be compared across builds.

Phase 2 itself — advisory output that an operator can accept and
emit as a setpoint — remains explicitly **out of scope** until the
trust-boundary plumbing (write authorisation, audit retention,
operator UX) is designed; Sprint 39 only ships the read-only
packaging seam that a future Phase 2 deployment review would
consume.
