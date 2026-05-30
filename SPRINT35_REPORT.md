# AOPSO Sprint 35 — Pillar A packaging: PyTorch → ONNX (offline, advisory, CPU-only)

**Status:** Pillar A was validated by Sprint 30b (out-of-sample PASS on the
locked March 2026 holdout under the pre-registered v2 gate). Sprint 35 banks
that win by exporting the validated detector to ONNX for the AMAX CPU-only
edge profile (Option A). This is an OFFLINE packaging sprint: a portable
inference artifact + conformant manifest, no live wiring of any kind.

SPRINT35_STATUS: COMPLETE
SPRINT35_GATE: PASS

## What was packaged

The frozen Pillar A health detector (autoencoder, n_axes=8 → hidden=16 →
latent=8 → hidden=16 → n_axes=8, Tanh activations, 560 trainable parameters)
re-fit with the same Sprint-30b configuration (seed=0, epochs=60,
batch_size=256, frozen 2025 z-score stats, full-year stratified auto-mode 2025
fit frame, 8 distinct months) was exported to ONNX (opset 17, dynamic batch
axis, float32 `[batch, 8]` input). A JSON sidecar carries the standardisation
constants `(mu, sigma)`, the score denominator (`val_error_p995`), the binary
flag threshold (`flag_threshold_error`), plus audit metadata (architecture,
parameter count, effective opset, sha256, size). Together the ONNX graph +
sidecar fully reproduce `FittedHealthDetector.score()` under onnxruntime CPU
with no torch dependency at inference time.

A conformant contracts-SDK `ModelArtifactRecord` was built via the existing
`build_health_artifact_record(...)` factory with `framework="onnx"`, the real
sha256 + size of the `.onnx` bytes, the canonical all-True `SafetyFlagSet`,
and the JSON-scalar summary mapping (architecture + standardisation +
calibration constants embedded as JSON strings so the SDK validator stays
happy). It validates without raising `ContractError`.

## Files changed / added

- `src/aquaoptima/advisory/packaging/__init__.py` (new) — packaging surface
  exports.
- `src/aquaoptima/advisory/packaging/onnx_export.py` (new) — `OnnxHealthDetectorSidecar`,
  `OnnxScoringResult`, `export_health_detector_to_onnx`, `score_with_onnx`,
  `score_axes_with_onnx`, `standardise_frames`, `build_health_detector_sidecar`.
- `scripts/sprint35_pillarA_onnx_package.py` (new) — end-to-end packaging
  pipeline: refit the Sprint-30b detector, export ONNX, parity-check on a
  held-in 2025 sample and on the real March-2026 frames, build the manifest,
  CPU latency profile, governance scan, write scorecard.
- `tests/advisory/test_sprint35_onnx_packaging.py` (new) — 11 tests covering
  export round-trip, sha256 cross-check, sidecar JSON round-trip, dynamic
  batch axis, parity within tolerance on the fixture, `ModelArtifactRecord`
  validation, deliberately-bad-input `ContractError` cases, governance scan
  clean.
- `data/eval/packaging/pillarA_health_detector.onnx` (new) — exported model
  bytes (3,747 bytes, sha256 prefix `787c2f1f54`).
- `data/eval/packaging/pillarA_health_detector.sidecar.json` (new) —
  standardisation + calibration sidecar.
- `data/eval/packaging/pillarA_onnx_artifact_record.json` (new) — conformant
  `ModelArtifactRecord` serialised JSON.
- `data/eval/packaging/sprint35_pillarA_onnx_scorecard.json` (new) — the
  Sprint-35 scorecard with the acceptance-gate verdict.

The contracts SDK (`src/aquaoptima_contracts/`) was NOT modified.
The edge package (`src/aquaoptima/edge/`) was NOT modified.

## Environment

- Python 3.11.15.
- torch 2.12.0+cpu.
- `onnx` 1.21.0 (installed at the start of this sprint via `pip install onnx`).
- `onnxruntime` 1.26.0 (CPU-only).
- `onnxscript` 0.7.0 (pulled in by torch.onnx for the dynamo exporter).

## Parity numbers

| dataset | n_rows | max_abs_recon_diff | max_abs_score_diff | flags_identical | torch_flag_rate | onnx_flag_rate |
|---|---:|---:|---:|---:|---:|---:|
| held-in 2025 stratified sample | 8,000 | 5.13e-06 | 6.60e-06 | True | 0.20% | 0.20% |
| **LOCKED March 2026 holdout** | **42,674** | **4.58e-05** | **4.59e-06** | **True** | **1.230%** | **1.230%** |

Tolerance set in the gate:

- `recon_error` max-abs-diff ≤ 1e-4 (raw per-row MSE over standardised axes;
  float32 amplification is significant on anomalous-magnitude inputs)
- `anomaly_score` max-abs-diff ≤ 1e-5 (clipped to [0,1], the downstream
  observable)
- binary flag must be bit-identical

All three thresholds cleared on both datasets. Mean abs recon diff is
~3e-8 on 2025 and ~1.5e-7 on March 2026 — element-wise ONNX/torch parity is
essentially float32 round-off; the per-row max reflects float32 amplification
when standardised inputs reach ~30σ on injected-fault-style values.

Both `onnx_flag_rate` and `torch_flag_rate` on the real March 2026 frames are
`0.012302572995266438` — bit-identical, and identical to the
`detector_flag_rate` reported in `sprint30b_fullyear_holdout_scorecard.json`.
The packaged ONNX artifact reproduces the validated Sprint-30b detector
exactly at the flag level.

## CPU latency (onnxruntime, single-threaded, single-row inference)

| metric | value |
|---|---:|
| mean | 0.017 ms |
| median (p50) | 0.015 ms |
| p95 | 0.026 ms |
| p99 | 0.037 ms |
| min | 0.014 ms |
| max | 0.184 ms |
| iterations | 256 (after 16 warmup) |
| threads | 1 |
| input shape | [1, 8] |

Surrogate evidence: measured on developer host CPU, not on real AMAX-5580
hardware. Still: a 560-parameter MLP is comfortably below any plausible
supervisory cadence requirement.

## Acceptance gate

All 6 criteria passed:

| # | criterion | passed |
|---|---|---|
| 1 | `onnx_export_loads_under_onnxruntime` (3,747 bytes, effective opset 17, dynamic batch) | True |
| 2 | `parity_held_in_2025` (recon ≤ 1e-4 AND score ≤ 1e-5 AND flags identical on 8,000 rows) | True |
| 3 | `parity_march_2026` (same tolerances on 42,674 real March frames) | True |
| 4 | `manifest_validates_under_contracts_sdk` (framework=onnx, real sha256, all-True safety flags) | True |
| 5 | `march_not_used_for_fitting` (Sprint-27 isolation assert, 213 keys checked, 0 leaked) | True |
| 6 | `governance_scan_clean` (advisory tree, 18 files scanned, 0 violations) | True |

**Verdict: PASS.**

## Source model traceability

The packaged artifact corresponds to the Sprint-30b validated detector. The
scorecard embeds a `source_model` block referencing
`data/eval/pillarA/sprint30b_fullyear_holdout_scorecard.json` and lifting the
detector config + Sprint-30b verdict (PASS) into the audit trail. Calibration
constants match bit-for-bit:

| constant | Sprint-30b value | Sprint-35 packaged sidecar value |
|---|---|---|
| `val_error_p995` | 0.23723329603672028 | 0.23723329603672028 |
| `train_error_p995` | 0.009128015488386154 | 0.009128015488386154 |
| `flag_threshold_error` | 0.1310570389032364 | 0.1310570389032364 |

## Safety posture (unchanged)

- `advisory_only: true`
- `evaluation_mode: "offline_only"`
- `write_path: "none"`
- `influences_control: false`
- `site_integration_allowed: false`
- `framework: "onnx"` (advertised by the AMAX edge profile)
- `safety_flag_set`: all-True canonical set (offline, read_only, no_write,
  no_control, no_live_ot_binding, no_setpoint_output, packaging_audit_only)
- Governance scan on `src/aquaoptima/advisory` clean — no forbidden edge SDK
  imports, no write-capable connector tokens.

The packaging code module (`src/aquaoptima/advisory/packaging/`) imports
`torch`, `onnx`, and `onnxruntime` for the export path; it does NOT import
any write-capable connector or any `aquaoptima.edge` /
`aquaoptima_contracts.edge` symbol. Governance scan covered the packaging
subpackage and is clean.

## Tests

- New: `tests/advisory/test_sprint35_onnx_packaging.py` — 11 tests, all
  passing. Covers export round-trip, sha256 sidecar cross-check, sidecar
  JSON round-trip, dynamic-batch-axis support, parity within tolerance on a
  fixture, `ModelArtifactRecord` validation with `framework="onnx"`, bad
  framework rejection (`ContractError`), missing-checksum rejection
  (`ContractError`), non-default `SafetyFlagSet` rejection (`SafetyFlagError`),
  and a governance scan of the packaging subpackage.
- Full repo suite: **2,653 passed, 1 skipped** (one pre-existing WNTR optional
  skip unrelated to Sprint 35). No regressions.

## How to reproduce

```bash
# Install the ONNX runtime stack (CPU only)
pip install onnx onnxruntime onnxscript

# Run the Sprint 35 packaging pipeline end-to-end (writes the .onnx, the
# sidecar, the manifest, and the scorecard under data/eval/packaging/)
PYTHONPATH=src python scripts/sprint35_pillarA_onnx_package.py

# Run the Sprint 35 packaging tests
PYTHONPATH=src python -m pytest tests/advisory/test_sprint35_onnx_packaging.py -q
```

The pipeline is deterministic given the same CSV inputs + `--detector-seed 0`
(default). Re-running produces the same sha256 hex on the `.onnx` file.

## Cannot claim

Packaging is **not** deployment authorisation. The Sprint-35 deliverables
prove that:

- the Pillar A detector forward pass survives ONNX export round-trip,
- the ONNX artifact + sidecar reproduce `FittedHealthDetector.score()` under
  onnxruntime CPU within tight numerical tolerance,
- the contracts-SDK `ModelArtifactRecord` validates with the canonical
  all-True safety flag set and a real sha256 checksum,
- and that no write-capable surface was introduced by the packaging code.

What this sprint does **NOT** authorise or evidence:

- Any site integration. The Yilan site has no AOPSO controller deployed and
  no write path opened by this work.
- Any control language, setpoint emission, or actuation. The packaged
  artifact only produces `detector_recon_error / detector_anomaly_score /
  detector_flag`, all advisory signals.
- Any claim that the model would behave as well on a different site,
  different sensor configuration, or different operating regime than the
  full-year-stratified 2025 Yilan auto-mode data it was fit on.
- Any claim about the latency or memory profile on the real AMAX-5580
  hardware. The CPU latency numbers above are surrogate, measured on a
  developer host. They are useful for ordering-of-magnitude sanity-checking
  only.
- Any claim about Pillar B. Sprint 33 FAILED Pillar B on the locked March
  holdout; Pillar B is explicitly NOT packaged here.
- Any claim that the ONNX artifact replaces the torch implementation for
  scientific evaluation. The torch detector remains the source of truth; the
  ONNX artifact is its CPU-edge deployment surface representation.

The acceptance criterion is parity-and-conformance. Real edge deployment
remains gated behind site integration approvals that this sprint does not
touch and does not seek.
