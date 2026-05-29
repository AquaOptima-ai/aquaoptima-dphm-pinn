# AOPSO A+B advisory — contract stubs & Sprint 27 guardrails (prep)

Preparation for executing **Sprints 27–29** of the AquaOptima Pump Station Optimizer Lite
(AOPSO) A+B pivot. Nothing here trains, loads, writes, actuates, or emits a setpoint — it
defines *what a conformant trained artifact must look like* and the offline guardrails the
product runs before any scorecard is accepted.

## Modules (`src/aquaoptima/advisory/`)

| Module | Purpose |
|--------|---------|
| `label_schema.py` | Single source of truth for the ordered telemetry axis/label schema (reuses `dataio.yilan_axis_map`). Emits the schema as a **JSON string** because the SDK forbids nested dicts in `ModelArtifactRecord.summary`. Guards against accelerator tokens. |
| `health_artifact_schema.py` | **Pillar A** — builds a conformant `ModelArtifactRecord` for a health/anomaly detector (health score + per-axis contribution + anomaly flag; baselines = persistence + SPC/EWMA). |
| `efficiency_artifact_schema.py` | **Pillar B** — builds a conformant `ModelArtifactRecord` for an efficiency/dPL advisory (efficient setpoint *envelope*, kWh/m³; explicitly `actuates=False`; baselines = site historical matched-condition + MVPv1 log). |
| `governance.py` | **Sprint 27** guardrails: `assert_holdout_isolated` (March-2026 leakage guard) and `scan_modeling_source_for_governance_violations` (FAILs on `aquaoptima.edge`/`contracts.edge` imports or write/actuation connector tokens). |

## What a trained artifact must satisfy (verified by tests)

1. **`framework="onnx"`** — the AMAX edge profile advertises onnx; CPU-only export keeps
   `validate_deployment_package_for_edge` green.
2. **Mandatory checksum** — `Checksum(algorithm="sha256", hex_digest=<64 hex>, size_bytes=N)`.
3. **Canonical all-True `SafetyFlagSet`** — the 7 tokens `offline, read_only, no_write,
   no_control, no_live_ot_binding, no_setpoint_output, packaging_audit_only`.
4. **Ordered axis schema** embedded in `summary` (as JSON string + flat `axis_order` list),
   index-aligned with the model's output vector.
5. **No accelerator tokens** (`cuda`/`tensorrt`/`jetson`/`orin`/`arm64`/`aarch64`) and **no
   forbidden-vocabulary tokens** anywhere in `summary` strings (the SDK scans them).
6. A `DeploymentPackageManifest` wrapping the record **passes the AMAX edge validator**
   (`result.accepted is True`, no rejected frameworks/accelerators).

## SDK constraints discovered (important for Sprint 27+)

- `ModelArtifactRecord.summary` values must be **scalar or flat list of scalars** — no
  nested dicts. Structured payloads go in as JSON *strings*.
- Summary strings are scanned for forbidden vocabulary; a token like `setpoint_output`
  is rejected even as a substring. Keep schema field names neutral.
- `EdgePackageValidationResult` exposes `.accepted` (not `.is_valid`), plus
  `.rejected_frameworks` / `.rejected_accelerator_tokens`.

## How Sprints 27–29 use this

- **Sprint 27** wires `governance.py` into CI + the scorecard pipeline (a governance FAIL
  forces scorecard safety status to FAIL regardless of metrics) and runs the leakage guard
  on the train/val split keys.
- **Sprint 28–29 (Pillar A)** train the detector, then wrap the exported ONNX artifact via
  `build_health_artifact_record(...)`; the conformance test proves it plugs in before any
  packaging is attempted (packaging itself stays blocked until a pillar PASSes).
- **Sprints 31–33 (Pillar B)** do the same via `build_efficiency_artifact_record(...)`.

## Tests

```bash
python -m pytest tests/advisory/ -q   # 21 tests, all green
```

The repo `conftest.py` shadows any globally-installed editable `aquaoptima` with this
worktree's `src/`, so tests resolve the local modules under development.
