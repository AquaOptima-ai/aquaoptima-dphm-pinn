# Sprint 41 — Shared Contracts / SDK Plan (Implementation-Ready)

Sprint 41 is the **first implementation sprint** after the Sprint 40
approval gate. It delivers the minimum Shared Contracts / SDK
foundation that every later Phase 2 / Phase 3 component depends on,
without touching the AI / Optimization Server, Edge Runtime, or
Operations Console runtime surfaces, and without changing any Phase 1
public import path.

Sprint 41 implementation is gated on explicit user approval of
[`docs/product/sprint40-3plus1-approval-gate.md`](sprint40-3plus1-approval-gate.md).
Do not start until that approval is recorded.

Safety boundary (unchanged):

- No live OT binding.
- No PLC/PAC/SCADA write (required exact phrase: no PLC/PAC/SCADA write).
- No command emission.
- No setpoint output.
- No control-loop closure.
- No setpoint or command output unless later explicitly safety-gated
  and approved.
- Future edge / PAC work begins mock, offline, simulated, dry-run,
  read-only, lab-only, and capability-gated.

## Goal

Sprint 41 ships a Python package called `aquaoptima_contracts` (in-tree
under `src/`) containing:

1. The `ContractEnvelope` schema metadata wrapper.
2. The `SchemaVersion` SemVer helper.
3. `SafetyFlagSet`, with the canonical token list and unknown-flag
   rejection.
4. `CapabilityDeclaration` (advertised capabilities) and
   `CapabilityRequirement` (required capabilities), both
   deny-by-default.
5. A deterministic JSON helper (sorted keys, stable numeric format,
   stable ordering of arrays where required).
6. A golden-fixture harness that reads a fixture, decodes through SDK
   types, re-encodes, and asserts byte equality.
7. Phase 1 fixtures copied (not moved) into
   `aquaoptima_contracts/fixtures/phase1_shadow/`.
8. Negative tests for every rejection path the validators promise.

## Acceptance criterion (single sentence)

> The SDK can represent the Phase 1 safety boundary and capability
> vocabulary deterministically, and every deployable can depend on it
> in Sprint 42+ without importing another deployable's internals.

## Explicit non-goals

Sprint 41 is **not** allowed to:

1. Implement any AI / Optimization Server runtime API.
2. Implement any Edge Runtime mode, validator, watchdog, or report
   producer.
3. Implement any Operations Console UI, workflow, or LLM integration.
4. Rename, move, or remove any Phase 1 import path (`aquaoptima.dphm.*`,
   `aquaoptima.dataio.*`).
5. Move EPANET `.inp` import or `Network` construction into the SDK.
6. Move runtime evaluators (`evaluate_advisory_proposals`,
   `run_shadow_runtime`) into the SDK.
7. Introduce any command / write / setpoint / control / actuation
   vocabulary in any contract, validator, fixture, or test.
8. Open a live OT binding, even in read-only mode.
9. Add any HTTP / network code or REST endpoint.
10. Add any database, message broker, or filesystem-mutating I/O
    outside test `tmp_path` writes.
11. Add a runtime dependency outside the Python stdlib (the
    deterministic JSON helper must use stdlib `json` only).
12. Modify `tests/e2e/test_phase1_shadow_mode_pipeline.py` in a way
    that weakens its invariants. (An additive SDK-routed companion
    test is allowed and recommended, but the original test must
    continue to pass byte-for-byte.)

## Candidate public APIs and types

The Sprint 41 SDK public surface is intentionally small. Every type
below is documented here as a candidate; final field names and
ordering are settled in TDD-driven implementation.

### 1. `ContractEnvelope`

Frozen dataclass embedded (by composition or inheritance) in every
top-level contract.

Required fields:

- `schema_family: str` — one of the families listed in
  [`docs/architecture/contracts-inventory.md`](../architecture/contracts-inventory.md)
  (`safety`, `envelope`, `telemetry`, `dpl_calibration`, `advisory`,
  `operator_review`, `manifest`, `edge_capability`, `model_registry`,
  `runtime_report`, `topology_projection`).
- `schema_name: str` — e.g. `SafetyFlagSet`, `CapabilityDeclaration`.
- `schema_version: SchemaVersion`.
- `sdk_version: SchemaVersion`.

Optional fields:

- `created_at: str` (ISO 8601 UTC, deterministic if supplied).
- `created_by_component: str` (`edge_runtime`, `ai_server`,
  `operations_console`, `sdk`, `test`).
- `artifact_id: str`.
- `correlation_id: str`.
- `provenance: Provenance | None` (deferred to Sprint 42; envelope
  carries only the optional reference).

Rules:

- Frozen, hashable, JSON-serializable.
- Two envelopes with identical fields render identical JSON.
- Validation rejects unknown `schema_family` values.

### 2. `SchemaVersion`

SemVer triple with helpers.

```python
@dataclass(frozen=True)
class SchemaVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> "SchemaVersion": ...
    def render(self) -> str: ...
    def is_compatible_reader(self, other: "SchemaVersion") -> bool: ...
```

Rules:

- Same-major versions are reader-compatible regardless of minor /
  patch.
- Different-major versions are rejected by readers (until a
  deprecation overlap window is added in Sprint 42+).
- `render()` produces `"{major}.{minor}.{patch}"`.

### 3. `SafetyFlagSet`

Frozen dataclass owning the canonical safety flag tokens and their
values.

Canonical tokens (Sprint 41 set):

```text
offline
read_only
no_write
no_control
no_live_ot_binding
no_setpoint_output
packaging_audit_only
```

Behavior:

- Construction requires every canonical token to be present.
- Each canonical token defaults to `True` for the current product
  boundary and must be explicitly `True` in every Phase 2 manifest.
- Unknown flag names are rejected with a clear error.
- A flag value other than `True` for any canonical token causes
  rejection.
- The set is frozen and hashable.

### 4. `CapabilityDeclaration` and `CapabilityRequirement`

Two frozen dataclasses sharing the same capability token vocabulary.

```python
@dataclass(frozen=True)
class CapabilityDeclaration:
    component: str
    declared: frozenset[str]
    sdk_version: SchemaVersion

@dataclass(frozen=True)
class CapabilityRequirement:
    package_id: str
    required: frozenset[str]
    sdk_version: SchemaVersion
```

Rules:

- Both reject unknown capability tokens.
- Both reject any token in the forbidden capability list (see
  [`docs/safety/capability-model-and-safety-gates.md`](../safety/capability-model-and-safety-gates.md)).
- Deny-by-default: empty declared sets advertise nothing; empty
  required sets are allowed only for packages that intentionally
  declare no capability needs (e.g. validation-only packages).
- A helper function `evaluate_capability_gate(decl, req)` returns a
  structured result naming missing capabilities. Sprint 41 ships the
  helper; Edge enforcement remains Sprint 45 work.

### 5. Deterministic JSON helpers

`aquaoptima_contracts/base/serialization.py` exposes:

```python
def dump_canonical_json(obj: Any) -> str: ...
def load_canonical_json(raw: str) -> Any: ...
def write_canonical_json(obj: Any, path: Path) -> Path: ...
```

Rules:

- Output uses sorted keys.
- Floats render with a fixed format (e.g. `repr` or
  `format(value, '.17g')`) that round-trips losslessly.
- Lists preserve caller-provided order; mappings sort alphabetically.
- The writer emits a trailing newline and `utf-8` encoding.
- Re-encoding a decoded document must return byte-equal output.

### 6. Golden fixture harness

`aquaoptima_contracts/testing/golden_files.py` exposes:

```python
def assert_golden_roundtrip(
    fixture_path: Path,
    *,
    schema: type[Contract],
) -> None: ...
```

The helper:

1. Reads the fixture from disk.
2. Decodes through the given SDK contract type.
3. Re-encodes via `dump_canonical_json` (or
   `write_canonical_json`).
4. Asserts byte equality with the on-disk fixture.

The harness is exercised by Sprint 41 negative and positive tests and
becomes the foundation for cross-component compatibility tests in
Sprint 42+.

### 7. Phase 1 golden fixtures

The Phase 1 fixtures used by
`tests/e2e/test_phase1_shadow_mode_pipeline.py` are **copied** (not
moved) into:

```text
src/aquaoptima_contracts/fixtures/phase1_shadow/
  tag_map.json
  telemetry.csv
  README.md
```

Sprint 41 also adds a JSON snapshot of a representative
`ShadowDeploymentManifest` produced by the Phase 1 chain into the same
directory (rendered through Sprint 39's writer) so that Sprint 42 has a
golden manifest to validate against once the manifest SDK schema lands.

The originals at `tests/fixtures/shadow_phase1/` remain in place.
Both copies must remain byte-identical; a Sprint 41 test asserts this.

## TDD acceptance criteria

Each subsection below is one TDD slice with a one-line acceptance
statement and the negative tests that must accompany it.

### A. `SchemaVersion`

Acceptance: parsing, rendering, and compatibility-check helpers are
total functions that reject malformed input.

Tests:

- `SchemaVersion.parse("1.0.0")` round-trips through `render()`.
- `parse("1.0")`, `parse("v1.0.0")`, `parse("1.0.0-pre")` raise.
- `is_compatible_reader` is reflexive within the same major and
  rejects across majors.

### B. `ContractEnvelope`

Acceptance: every envelope is frozen, deterministic, and rejects
unknown families.

Tests:

- A minimal envelope renders to byte-stable JSON.
- Two envelopes with identical fields hash identically.
- Unknown `schema_family` raises.
- Optional fields, when absent, do not appear in the JSON output.

### C. `SafetyFlagSet`

Acceptance: only the canonical token list is accepted; each token must
be `True` for the current product boundary.

Tests (positive):

- A `SafetyFlagSet` constructed with all canonical tokens set to
  `True` round-trips through `dump_canonical_json` / `load_canonical_json`.

Tests (negative):

- Missing any one of the seven canonical tokens raises.
- Setting a canonical token to `False` raises.
- Adding any non-canonical token raises.
- Any forbidden-vocabulary token used as a flag name raises.

### D. `CapabilityDeclaration` / `CapabilityRequirement`

Acceptance: capability tokens are deny-by-default; unknown and
forbidden tokens are rejected.

Tests (positive):

- A declaration with the full default allowed-capability set encodes
  deterministically.
- An empty requirement is accepted for a validation-only package.
- `evaluate_capability_gate` reports `missing == set()` when the
  declaration covers the requirement.

Tests (negative):

- Unknown capability token raises on construction.
- Any forbidden capability token raises on construction.
- `evaluate_capability_gate` reports a non-empty `missing` set when
  the requirement exceeds the declaration.

### E. Deterministic JSON helper

Acceptance: encoding is deterministic and round-trips losslessly.

Tests:

- Encoding a mapping with shuffled key order produces stable output.
- Encoding the same float twice produces byte-identical output.
- `load_canonical_json(dump_canonical_json(x)) == x`.
- `write_canonical_json` followed by re-read returns byte-identical
  content on disk.

### F. Phase 1 fixture compatibility

Acceptance: the Phase 1 fixture set decodes through the Sprint 41
types and re-encodes byte-for-byte where applicable.

Tests:

- The Phase 1 `tag_map.json` fixture remains valid input to the
  existing `load_telemetry_tag_map_json` API (untouched in Sprint 41).
- The SDK fixture copy is byte-identical to
  `tests/fixtures/shadow_phase1/tag_map.json`.
- The Phase 1 manifest snapshot produced by Sprint 39's writer
  matches the SDK `dump_canonical_json` output **for the
  envelope/safety/capability subset only** (full manifest schema
  lands in Sprint 42).
- The existing `tests/e2e/test_phase1_shadow_mode_pipeline.py`
  continues to pass.

### G. Forbidden-vocabulary scan

Acceptance: no forbidden token appears anywhere in the new SDK code,
tests, or fixtures.

Tests:

- A grep-style test scans `src/aquaoptima_contracts/`,
  `tests/aquaoptima_contracts/` (if added), and the fixture directory
  for any token in the forbidden list and fails the build if any are
  found (excluding the canonical denylist constant in the safety
  module itself).

## Files to create

```text
src/aquaoptima_contracts/
  __init__.py
  version.py
  base/
    __init__.py
    envelope.py            # ContractEnvelope, ContractError
    identifiers.py         # ArtifactReference (skeleton; full Sprint 42)
    serialization.py       # dump_canonical_json, load_canonical_json,
                           #   write_canonical_json
    validation.py          # shared validators / token guards
  safety/
    __init__.py
    flags.py               # SafetyFlagSet + canonical token list
    capability_gates.py    # CapabilityDeclaration, CapabilityRequirement,
                           #   allowed + forbidden token lists,
                           #   evaluate_capability_gate
    vocabulary.py          # forbidden-vocabulary tokens; helper
                           #   contains_forbidden_token
  testing/
    __init__.py
    golden_files.py        # assert_golden_roundtrip
    builders.py            # convenience constructors used by tests
  fixtures/
    phase1_shadow/
      tag_map.json         # copy of tests/fixtures/shadow_phase1/tag_map.json
      telemetry.csv        # copy of tests/fixtures/shadow_phase1/telemetry.csv
      manifest_snapshot.json
      README.md

tests/aquaoptima_contracts/
  __init__.py
  test_schema_version.py
  test_contract_envelope.py
  test_safety_flag_set.py
  test_capability_declaration.py
  test_deterministic_json.py
  test_phase1_fixture_compat.py
  test_forbidden_vocabulary_scan.py
```

## Files to modify

- `pyproject.toml` — register `aquaoptima_contracts` as a package
  source (or update `packages` / `find` directives so an editable
  install picks it up).
- `README.md` — add a brief subsection naming the SDK package and
  pointing to `docs/architecture/shared-contracts-sdk.md`.
- `docs/sprint-roadmap.md` — append a Sprint 40 / Sprint 41 entry that
  points to the planning documents.

No Phase 1 module is modified.

## Verification commands (Sprint 41 acceptance)

```bash
test -d src/aquaoptima_contracts
test -d tests/aquaoptima_contracts
test -d src/aquaoptima_contracts/fixtures/phase1_shadow
test -f docs/product/sprint40-3plus1-approval-gate.md
python -m compileall src tests
python -m pytest tests/aquaoptima_contracts -q
python -m pytest tests/e2e/test_phase1_shadow_mode_pipeline.py -q
python -m pytest tests/dphm tests/models -q
python -m pytest -q
```

Sprint 41 may be declared complete only when every command above
exits zero and the forbidden-vocabulary scan test reports zero hits.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| SDK starts to absorb runtime logic. | Sprint 41 ships only types, validators, deterministic helpers, and tests. No HTTP, DB, or runtime evaluator code is added. PRs touching `src/aquaoptima_contracts/` must not import any deployable module. |
| Phase 1 fixtures drift from SDK copies. | Sprint 41 ships a byte-equality test between fixture pairs. CI fails on drift. |
| Forbidden vocabulary leaks. | Sprint 41 ships a build-failing grep scan over SDK source / tests / fixtures. |
| `ContractEnvelope` design churn. | Sprint 41 commits a small, conservative envelope (family / name / version / sdk_version + optional fields). Sprint 42 adds provenance, pagination, and richer artifact references. |
| Non-deterministic JSON output. | Sprint 41 ships a `dump_canonical_json` round-trip test and a stable-format float test. CI fails on non-determinism. |
| Sprint scope creep into Sprint 42 contracts. | Sprint 41 does **not** ship `TelemetryTagMap`, `ShadowReplayDataset`, advisory, or manifest schemas. Those land in Sprint 42 with their own TDD slices. |
| Unsafe import order between `aquaoptima` and `aquaoptima_contracts`. | The SDK does not import `aquaoptima.*`. The Phase 1 code does not import `aquaoptima_contracts` in Sprint 41. |
| Operator confusion with "deployment". | The Sprint 39 `ShadowDeploymentManifest` doc already states the term refers to a packaging / audit-evidence bundle. Sprint 41 reaffirms this in `safety/vocabulary.py` docstrings. |

## Out-of-scope reminders (do not implement in Sprint 41)

- `TelemetryTagMap`, `ShadowReplayDataset`, `AdvisoryContract`,
  `AdvisoryProposal`, `ShadowRuntimeReport`,
  `ShadowDeploymentManifest`, `EpanetImportQualityReport` SDK schemas
  — Sprint 42.
- AI Server APIs and package generation — Sprints 43–44.
- Edge Runtime validation / shadow runtime / health — Sprints 45–47.
- Operations Console dashboards / workflows / LLM — Sprints 48–49, 66.
- Phase 3 PAC-like edge lab branch — Sprints 52+.
- Any live OT binding, dry-run read-only adapter, simulated write, or
  supervised write — gated behind Sprint 40's safety gates and
  separate approvals.
