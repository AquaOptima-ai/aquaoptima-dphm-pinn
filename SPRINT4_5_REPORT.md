# AquaOptima dPHM-PINN — Sprint 4.5 Report

## Scope delivered

Sprint 4.5 is a cleanup + architecture sprint that generalises the
SCADA-specific data path into a canonical telemetry abstraction,
introduces a PLC/PAC/SCADA tag-map foundation, fills in missing class
docstrings, and produces the first round of architecture
documentation. **No Sprint 5 physics-consistent training work and no
real PLC/PAC client / write path were implemented**, as required by
the brief.

Concretely:

1. **Canonical telemetry container.** New
   `aquaoptima.dataio.telemetry.TelemetrySeries` (with optional
   per-channel `quality` dict) supersedes the SCADA-named container.
2. **Canonical synthetic generator.** New
   `generate_synthetic_telemetry` with identical semantics to the
   Sprint 3 generator.
3. **Backward compatibility.** `ScadaSeries` and
   `generate_synthetic_scada` remain importable from both
   `aquaoptima.dataio` and the legacy
   `aquaoptima.dataio.synthetic_scada` module path; they are aliases
   to the canonical names, byte-for-byte identical output.
4. **Tag-map foundation.** New `aquaoptima.dataio.tag_map` ships
   `SourceType`, `TagKind`, `TagDefinition`, `SiteTagMap` with strict
   construction-time validation. Models the PLC/PAC/SCADA/historian/
   MQTT/CSV adapter contract without implementing any of the adapters.
5. **Quality flags.** New `aquaoptima.dataio.quality` ships
   `QualityFlag` (`GOOD | MISSING | STALE | FLATLINE | OUTLIER |
   BAD_QUALITY | MANUAL_OVERRIDE`) and an `is_usable` helper.
6. **Docstrings filled in** for `Network`, `SolveResult`,
   `SolveFailureReason`, `FeasibilityResult`, `DPHMPINN`, and
   `GRUTemporalEncoder`.
7. **Documentation** — six new files under `docs/` and a rewritten
   `README.md`.

## Files changed / created

### Production code (`src/aquaoptima/`)

| File                              | Status   | What                                                                 |
|-----------------------------------|----------|----------------------------------------------------------------------|
| `dataio/telemetry.py`             | NEW      | Canonical `TelemetrySeries` + `generate_synthetic_telemetry`         |
| `dataio/synthetic_scada.py`       | REWRITE  | Now a thin re-export shim over `telemetry.py` for back-compat        |
| `dataio/window_dataset.py`        | UPDATED  | Imports `TelemetrySeries` instead of `ScadaSeries`; docstring re-aimed |
| `dataio/tag_map.py`               | NEW      | `SourceType`, `TagKind`, `TagDefinition`, `SiteTagMap`               |
| `dataio/quality.py`               | NEW      | `QualityFlag`, `is_usable`                                           |
| `dataio/__init__.py`              | UPDATED  | Exports the canonical and aliased symbols                            |
| `dphm/network.py`                 | UPDATED  | Added `Network` class docstring                                      |
| `dphm/diagnostics.py`             | UPDATED  | Added `SolveFailureReason` + `SolveResult` class docstrings          |
| `dphm/feasibility.py`             | UPDATED  | Added `FeasibilityResult` class docstring                            |
| `models/dphm_pinn.py`             | UPDATED  | Added `DPHMPINN` class docstring                                     |
| `models/gru_encoder.py`           | UPDATED  | Added `GRUTemporalEncoder` class docstring                           |

### Tests (`tests/`)

| File                                  | Status | What                                                                            |
|---------------------------------------|--------|---------------------------------------------------------------------------------|
| `tests/dataio/test_telemetry_aliases.py` | NEW   | 6 tests for `TelemetrySeries` / generator / alias / `WindowDataset` interop     |
| `tests/dataio/test_tag_map.py`        | NEW    | 14 tests for tag-map validation rules                                            |
| `tests/dataio/test_quality.py`        | NEW    | 9 tests for `QualityFlag` and `is_usable`                                       |

### Documentation (`docs/`)

| File                                  | Status |
|---------------------------------------|--------|
| `docs/architecture.md`                | NEW    |
| `docs/units-and-sign-conventions.md`  | NEW    |
| `docs/telemetry-abstraction.md`       | NEW    |
| `docs/testing-strategy.md`            | NEW    |
| `docs/sprint-roadmap.md`              | NEW    |
| `docs/safety-boundary.md`             | NEW    |
| `README.md`                           | REWRITE — module map, status, adapter strategy, limitations, Sprint 5 plan |

## Tests added

**29 new tests** across three new test modules:

- `tests/dataio/test_telemetry_aliases.py` (6)
  - `ScadaSeries is TelemetrySeries` (alias identity).
  - `generate_synthetic_telemetry` shape contract.
  - Seeded reproducibility.
  - SCADA alias output matches telemetry generator output byte-for-byte.
  - `WindowDataset` accepts a `TelemetrySeries` directly.
  - `quality` field defaults to `None` and accepts dict.
- `tests/dataio/test_tag_map.py` (14)
  - `SourceType` / `TagKind` enum membership.
  - Well-formed `SiteTagMap` construction.
  - Sampling interval rejects `0` and negative.
  - Duplicate tag names rejected.
  - `PRESSURE` requires `node_id`.
  - `FLOW` requires `edge_id`.
  - `PUMP_SPEED` / `PUMP_STATUS` / `POWER` / `COMMAND` require
    `pump_id` (parametrised → 4 cases).
  - `COMMAND` tag default `writable=False`.
  - Explicit `writable=True` is honoured.
  - `SiteTagMap` is frozen (cannot mutate after construction).
- `tests/dataio/test_quality.py` (9)
  - `QualityFlag` member set.
  - Values are lowercase strings.
  - `is_usable` returns `True` only for `GOOD`.
  - `is_usable` returns `False` for every other flag (parametrised
    → 6 cases).

## TDD evidence

Strict red → green per module. The red phase was an `ImportError`
during pytest collection before any production code existed; green
was the same pytest command after implementing only what the tests
required.

| Test module                              | Red (observed)                                                       | Green (final) |
|------------------------------------------|----------------------------------------------------------------------|---------------|
| `tests/dataio/test_telemetry_aliases.py` | `ImportError: cannot import name 'TelemetrySeries'`                  | 6 / 6         |
| `tests/dataio/test_tag_map.py`           | `ImportError: cannot import name 'SiteTagMap'`                       | 14 / 14       |
| `tests/dataio/test_quality.py`           | `ImportError: cannot import name 'QualityFlag'`                      | 9 / 9         |

No production code was written without a failing test first. No test
was relaxed to make a green pass.

## Commands run

```bash
# Baseline before changes
python -m pytest tests -q                                # 154 passed

# Red phase (failing tests before implementation)
python -m pytest tests/dataio/test_telemetry_aliases.py \
                 tests/dataio/test_tag_map.py \
                 tests/dataio/test_quality.py -q         # 3 collection errors

# After implementation — TDD green
python -m pytest tests/dataio -q                         # 39 passed

# Final validation
python -m pytest tests -q                                # 183 passed
python -m compileall src tests                           # clean
```

## Pass / fail status

- `python -m pytest tests/dataio -q` → **39 passed** (10 existing
  `test_window_dataset.py` + 29 new).
- `python -m pytest tests -q` → **183 passed** (Sprint 4's 154 + 29
  new).
- `python -m compileall src tests` → clean.

No skips, no xfails, no new warnings. Sprint 1–4's 154 tests continue
to pass alongside Sprint 4.5's 29 new tests.

## Compatibility notes

- **`ScadaSeries` and `generate_synthetic_scada` still import from
  `aquaoptima.dataio`** and from `aquaoptima.dataio.synthetic_scada`.
  Sprint 1–4 call sites need no changes.
- **Tensor output is byte-for-byte identical** for the same seed
  through either entry point — confirmed by
  `test_scada_alias_matches_telemetry_generator`.
- **`WindowDataset` signature unchanged.** It now type-hints
  `TelemetrySeries` but `ScadaSeries` is the same class, so all
  Sprint 1–4 calls continue to work.
- **No model / training / loss surface changed.** All 154 Sprint 1–4
  tests pass without modification.

## Known limitations

1. **Synthetic telemetry is still not physics-consistent.** The
   generator internals are the Sprint 3 sinusoid. Replacement with
   a `newton_solve`-driven generator is the Sprint 5 entry point.
2. **No real source adapters.** `SiteTagMap` is metadata only —
   nothing reads a real PLC, PAC, SCADA, historian, MQTT broker, or
   CSV file yet.
3. **No write path.** `TagDefinition.writable` defaults to `False`;
   no code path writes commands to a controller, and the
   `SetpointAdvisoryHead` output is not wired to any writer.
4. **Quality flags are vocabulary only.** `QualityFlag` /
   `is_usable` exist; no code path consumes them yet. The Sprint 5
   physics-consistent training loop will be the first consumer.
5. **`TelemetrySeries.quality` field is unenforced.** Shape of the
   quality dict is not validated against `pressure` / `flow` /
   `demand` shapes at construction. Enforcement lands when the field
   is actually consumed.
6. **No EPANET validation, no dPL, no ONNX / TensorRT, no batch
   dimension on the model** — all carried forward from Sprint 4.

## Sprint 5 recommendation — exact entry point

**Make the physics-informed loss measurably improve over sensor-only
on a physics-consistent synthetic dataset.** Concretely, in order:

1. **Physics-consistent synthetic generator.** Replace the sinusoid
   internals of `generate_synthetic_telemetry` (in
   `src/aquaoptima/dataio/telemetry.py`) with a per-step
   `newton_solve` driven by a randomised demand schedule. The
   resulting `(pressure, flow, demand)` triples will satisfy
   `assemble_residuals ≈ 0` by construction. Keep the function
   signature so `WindowDataset` and existing tests stay green.
2. **Convergence assertion in CI.** Add a new test that runs
   `run_ablation("sensor_plus_physics")` for ~200 iterations on the
   new generator and asserts the final masked-MSE on virtual nodes is
   *lower* than the same model run under `sensor_only`. This locks
   in the value claim of the PINN approach.
3. **Lambda warmup.** Promote the smoke loop from a fixed
   `lambda_physics=1e-4` to a `LinearRampLambda(start=0,
   end=tuned_value, ramp_steps=...)` so the physics term ramps in
   after the data loss has stabilised.
4. **Batchify.** Promote `x_seq` to `[B, T, N, F]` end-to-end (GRU
   batch dim absorbs `B*N`, graph encoder shared, heads broadcast
   over `B`, `composite_loss` reduces over `B`).
5. **Generalise the ablation harness.** Parametrise `run_ablation`
   by network fixture (`branch | single_loop | pump`) so the CI run
   exercises all three Sprint 2 fixtures.

Real adapters (Modbus / OPC-UA / MQTT / REST / CSV), EPANET validation,
dPL parameter learning, ONNX/TensorRT export, and the safety-gated
write path remain out of scope until Sprint 5's physics-consistent
training run shows a measurable benefit from the physics loss.
