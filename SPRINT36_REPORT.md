# Sprint 36 — dPL calibration prototype

## Goal

Add the first deterministic dPL calibration-loss prototype that
consumes Sprint 35 `ShadowReplayDataset` frames as observation
targets and produces residual / loss values against caller-supplied
per-frame predictions. The prototype answers, given a Sprint 35
dataset plus a sequence of supplied predictions:

- Given model / dPHM predicted values for `node_pressure`,
  `edge_flow`, `edge_pump_speed`, etc., what replay observations are
  available?
- What residuals / loss values result?
- Which observations were missing from predictions?
- Which predictions were unused?
- Can future dPL calibration loops consume this without touching
  live OT systems?

The builder is read-only / offline-only. It activates no live
SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST binding,
exposes no write / control / setpoint path, invokes no dPHM forward
solver, and produces no advisory output.

## Files changed

- `src/aquaoptima/dphm/dpl_calibration.py` (new module) — frozen
  dataclasses (`DPLCalibrationDiagnostics`, `DPLResidual`,
  `DPLCalibrationLossReport`), the canonical axis constants
  (`DPL_AXES`, `DPL_NUMERIC_AXES`, `DPL_STATUS_AXES`), and the
  public builder `build_dpl_calibration_loss_report`.
- `src/aquaoptima/dphm/__init__.py` (updated) — re-exports the new
  dataclasses, axis constants, and builder. No existing export
  changes.
- `tests/dphm/test_dpl_calibration.py` (new) — 47 focused tests
  covering the surface, the strict / non-strict contract, every
  required behaviour (frozen surface, empty replay, single
  residual, multi-axis / multi-target, weighted MSE, missing
  prediction, extra prediction, invalid weight, bool status,
  length mismatch, deterministic ordering, read-only contract,
  Sprint 35 pipeline compatibility, no live adapter surface).
- `docs/dpl-calibration.md` (new) — Sprint 36 surface documentation
  including the predictions input shape, supported axes, residual /
  loss formulas, strict / non-strict semantics, and the reaffirmed
  safety boundary.
- `SPRINT36_REPORT.md` (this file).

No other source file is touched. The new module imports only
Sprint 34 axis constants, the Sprint 35 dataclasses, and stdlib
`math` / `dataclasses` / `typing`. No parser, solver, training,
or data-IO module is modified. No new third-party dependency.

## API design

Three frozen dataclasses:

- `DPLCalibrationDiagnostics(warnings: tuple[str, ...] = (), errors: tuple[str, ...] = ())`
  — deterministic warning / error tuples; identical surface shape
  to Sprint 34 / Sprint 35 diagnostics.
- `DPLResidual(frame_index, timestamp, axis, target_id, observed,
  predicted, residual, weight=1.0)` — single per-observation
  residual record. `residual == predicted - observed`. Status
  values are coerced to `0.0` / `1.0` before storing on the record.
- `DPLCalibrationLossReport(residuals, mse_by_axis, mae_by_axis,
  weighted_mse, observation_count, diagnostics)` — frozen
  top-level container; `residuals` is an immutable tuple in
  deterministic frame → axis → target order.

One builder:

- `build_dpl_calibration_loss_report(replay, predictions, *,
  axis_weights=None, strict=True)` — pure offline builder over a
  Sprint 35 `ShadowReplayDataset` and a per-frame predictions
  `Sequence`. Never mutates inputs; never opens a binding; never
  invokes the forward solver.

Three axis constants:

- `DPL_NUMERIC_AXES` — the seven canonical numeric axes
  (`node_pressure`, `node_demand`, `node_level`, `edge_flow`,
  `edge_pump_speed`, `edge_power`, `edge_valve_position`).
- `DPL_STATUS_AXES` — the two canonical status axes
  (`node_status`, `edge_status`).
- `DPL_AXES` — concatenation of the two, in deterministic order;
  this is the order the residuals tuple uses.

All public symbols are re-exported through `aquaoptima.dphm`.

## Loss formulas

For every `(frame_index, axis, target_id)` triple where the replay
frame carries an observation **and** the supplied prediction
carries a matching value:

```
residual           = predicted - observed                 (per record)
mse_by_axis[axis]  = mean( residual ** 2 ) over residuals on that axis
mae_by_axis[axis]  = mean( abs(residual) ) over residuals on that axis
```

The weighted MSE aggregates across all residuals using the axis
weights (default `1.0`):

```
weighted_mse = sum_i ( weight(axis_i) * residual_i ** 2 )
               -----------------------------------------
                          sum_i weight(axis_i)
```

Edge cases:

- `observation_count == 0` → `weighted_mse == 0.0` exactly;
- `mse_by_axis` / `mae_by_axis` carry **only** axes that produced
  at least one residual (no `0.0` placeholders for absent axes);
- residual ordering is deterministic: outer frame index, then
  `DPL_AXES` order, then ascending `target_id`.

Status axes are scored on the same `0.0` / `1.0` numeric line as
numeric axes — i.e. a misprediction of `False` against `True`
contributes `1.0` to MSE / MAE / weighted MSE.

## Strict / non-strict behaviour

`strict=True` (default) raises `ValueError` for any of:

- `len(predictions) != len(replay.frames)`;
- a predicted value is missing for an observed
  `(axis, target_id)`;
- a per-frame prediction is not a `Mapping`, or a per-axis
  sub-value is not a `Mapping`;
- a supplied predicted value cannot be coerced (numeric NaN / inf
  / bool / wrong type, status outside `{True, False, 0, 1}`);
- `predictions` is not a `Sequence` (e.g. a generator) or is a
  string;
- `replay` is not a `ShadowReplayDataset`.

`strict=False` returns a populated report whose
`diagnostics.errors` lists every offending pair in input order;
the offending residual is **omitted** from the report. The
overlapping prefix of `predictions` and `replay.frames` is still
processed deterministically.

Extra predictions (predicted `(axis, target_id)` with no
observation) are always **warnings**, never errors — in either
mode. Predictions naming an unsupported axis are also warnings.

`axis_weights` validation is **not** gated by `strict`. Negative,
zero, non-finite, or unknown-axis weights are programmer errors
and always raise `ValueError`. This avoids silently collapsing the
weighted MSE into the wrong scalar.

## Tests added

`tests/dphm/test_dpl_calibration.py` — 47 tests covering, in
order:

1. Frozen dataclass surfaces (assigning to any frozen field
   raises `FrozenInstanceError`).
2. Default-constructed dataclasses.
3. Empty replay returns an empty report (strict and non-strict).
4. Single node-pressure residual with the expected
   `residual`, `mse_by_axis`, `mae_by_axis`, and `weighted_mse`.
5. Zero residual when prediction matches observation.
6. Multi-axis + multi-target frame with expected per-axis MSE /
   MAE.
7. Weighted MSE applies axis weights deterministically.
8. Default weight is `1.0`; weighted MSE reduces to mean square.
9. Missing prediction strict raises (per-target and per-axis
   variants).
10. Missing prediction non-strict skips the residual and records
    the error string.
11. Extra prediction records a warning (no error).
12. Extra prediction on an unsupported axis records a warning.
13. Negative axis weight rejected.
14. Zero axis weight rejected.
15. NaN axis weight rejected.
16. Inf axis weight rejected.
17. Unknown axis in `axis_weights` rejected.
18. Bool axis weight rejected.
19. Non-mapping `axis_weights` rejected.
20. Bool status observation and prediction (both axes, multiple
    targets) — verifies the `0.0` / `1.0` coercion and the
    resulting MSE / MAE.
21. Status observation as `bool` with prediction as `int 0`
    works.
22. Numeric prediction outside `{0, 1}` for status axis strict
    raises.
23. Numeric prediction outside `{0, 1}` for status axis
    non-strict records error.
24. Length mismatch strict raises.
25. Length mismatch non-strict records error and still emits the
    overlapping-prefix residuals.
26. Excess predictions non-strict records the length-mismatch
    error.
27. Deterministic residual ordering (frame → axis → target).
28. Repeat build returns equal reports.
29. Builder does not mutate `replay` or `predictions` (deep-copy
    snapshot comparison).
30. Mutating the input prediction after build does not affect the
    report (defensive copy via the `DPLResidual` value-typed
    fields).
31. Compatible with the Sprint 35 `build_shadow_replay_dataset`
    pipeline (bar → m, L/s → m3/s, percent → fraction).
32. Empty Sprint 35 dataset (empty tag map, empty rows) is a
    no-op in Sprint 36.
33. No live-adapter surface: substring screen across the module's
    `__all__` and re-export through `aquaoptima.dphm`; live
    stdlib networking modules (`socket`, `asyncio`, `ssl`,
    `urllib`, `smtplib`) are not referenced.
34. Generator `predictions` rejected (only true `Sequence`).
35. String `predictions` rejected.
36. `replay` argument type rejected.
37. Per-frame non-`Mapping` prediction strict raises.
38. Per-axis non-`Mapping` sub-value strict raises.
39. Numeric prediction on status axis outside `{0, 1}` rejected.
40. Bool prediction on numeric axis rejected.
41. NaN prediction rejected.
42. Inf prediction rejected.
43. `mse_by_axis` / `mae_by_axis` omit axes with no residuals.
44. Timestamp on `DPLResidual` is passed through verbatim
    (identity-preserved for sentinel objects).
45. `DPL_AXES` / `DPL_NUMERIC_AXES` / `DPL_STATUS_AXES`
    constants are complete and consistent.
46. Status observation + int prediction coercion.
47. (Combined-coverage assertions across the above — see the
    test file for exact enumeration.)

Plus the explicit "compatible with Sprint 35 pipeline" check
through `build_telemetry_tag_map` + `build_shadow_replay_dataset`
+ `build_dpl_calibration_loss_report` against a `make_pump_network`
fixture with `bar`, `l/s`, and `percent` units in the offline row.

## Validation commands / results

Run from the worktree root:

```bash
python -m pip install -e .
python -m pytest tests/dphm/test_dpl_calibration.py -q
python -m pytest tests/dphm tests/models tests/training tests/dataio -q
python -m pytest tests -q
python -m compileall -q src tests
git diff --check
```

Results captured before this report:

- `python -m pytest tests/dphm/test_dpl_calibration.py -q` →
  **47 passed**.
- `python -m pytest tests/dphm tests/models tests/training tests/dataio -q`
  → **1463 passed, 1 skipped** (existing WNTR optional-import skip).
- `python -m pytest tests -q` → **1471 passed, 1 skipped**.
- `python -m compileall -q src tests` → clean.
- `git diff --check` → clean.

## Compatibility notes

- Sprint 35's `ShadowReplayDataset` is consumed verbatim — the
  Sprint 36 builder reads `replay.frames[i]` axis maps and never
  re-validates the schema. Calling Sprint 35 in `strict=False`
  mode and feeding the resulting dataset to Sprint 36 is fully
  supported; the Sprint 35 diagnostics surface remains
  authoritative for replay-side issues.
- Sprint 34 axis constants are reused verbatim through the
  Sprint 35 import path.
- No existing public symbol changes. No existing test changes.
- No new third-party dependency: only stdlib `math` /
  `dataclasses` / `typing` are imported by the new module.
- The aquaoptima.dataio Sprint 4.5 telemetry abstraction is
  untouched; Sprint 36 sits behind the same dPHM-side surface as
  Sprints 34 / 35.

## Known limitations

- No tensor / autograd helper is exposed. Sprint 36 emits a plain
  `tuple[DPLResidual, ...]` plus float aggregates. A future
  sprint can add a `torch.Tensor` helper (residuals stacked by
  axis, weights vector, scalar loss) when a concrete training
  loop appears that needs it; the Sprint 36 surface is the data
  contract that helper would build on.
- The builder requires a `Sequence` for `predictions` (rejects
  generators). This is deliberate: a generator would silently
  collapse after the first pass which would make a repeat-build
  determinism guarantee unsafe.
- Status residuals are scored on the integer `0.0` / `1.0` line.
  A future sprint that wants a softer logit-style loss can add a
  parallel API; Sprint 36 keeps the prototype surface narrow.
- `weighted_mse` averages by `sum(weights)` (a normalised weighted
  mean). A future training loop that wants an *un-normalised*
  weighted sum can recompute it from the residual tuple in O(N) —
  the residual records carry both `residual` and `weight`.
- The per-axis aggregate mappings on
  `DPLCalibrationLossReport` are plain `dict` objects (typed as
  `Mapping`). The dataclass binding itself is frozen, but a
  determined caller could mutate the dict in place. Callers that
  need a guaranteed-immutable view can wrap each mapping in
  `types.MappingProxyType` — Sprint 36 deliberately does not
  pre-wrap to keep ergonomics simple (matching Sprint 35).
- No training loop, no optimiser integration, no advisory
  surface, no setpoint optimisation, no live binding — strictly
  out of scope per the Sprint 36 brief.

## Verdict

Sprint 36 ships a typed, deterministic, read-only dPL calibration
loss prototype that consumes Sprint 35's `ShadowReplayDataset` and
a caller-supplied per-frame predictions sequence and emits a frozen
`DPLCalibrationLossReport` carrying residuals (frame / axis /
target keyed), per-axis MSE / MAE, and a deterministic weighted
MSE suitable as a calibration loss term. All required Sprint 36
verification items are exercised by the test suite; the existing
1,424-test baseline is preserved (1,471 passes including 47 new);
the new module adds no third-party dependency. The safety boundary
is unchanged: no live binding, no write / control / setpoint /
advisory path, no forward-solve invocation, no training-loop
integration.

Ready for Hermes verification.

## Sprint 37 recommendation

The Sprint 36 calibration surface cleanly emits per-observation
residuals keyed by `(frame_index, axis, target_id)` plus a scalar
weighted loss — exactly the shape a future dPL training loop would
consume. The remaining structural gap before any dPL training work
can begin is the **advisory safety contract**: a typed, frozen,
read-only declaration of which dPHM outputs an advisory layer is
allowed to *propose* (suggest, not act on), under what guards
(minimum residual support, maximum proposed setpoint delta,
allow-list of controllable edges) and which outputs it must never
touch (fixed-head reservoirs / tanks, surrogate edges
flagged by the Sprint 33 import-quality report). Sprint 36 closed
the offline observation→loss loop without exposing any advisory
surface; Sprint 37 should pin down the *contract* that a future
advisory layer would have to satisfy, while staying behind the
same shadow-mode safety boundary (still no live binding, still no
write path, still no control output).

**Recommendation: Sprint 37 → advisory safety contract.** Land a
typed, frozen `AdvisoryContract` describing the allow-list /
deny-list of controllable dPHM ids, the minimum residual support
required to *propose* a setpoint change, the maximum proposed
delta per axis, and a deterministic dry-run audit surface that
shows exactly which proposals a contract would accept or reject
against a given Sprint 36 `DPLCalibrationLossReport`. Keep the
contract read-only — Sprint 37 should produce a
`would_accept` / `would_reject` audit, never an actual setpoint
write. The smallest possible follow-up after that contract lands
is the dPL training-loop scaffolding (Sprint 38+), which can then
consume both the Sprint 36 loss surface and the Sprint 37 contract
as a hard precondition before any advisory output is emitted.

If, during Sprint 37 prototyping, a contract-blocking limitation
surfaces in the Sprint 36 surface (e.g. a need for per-target
weights rather than per-axis weights, or a need to surface the
*per-frame* MSE breakdown), the smallest possible follow-up — a
single additional field on the report plus a focused test pass —
should land as a Sprint 36a hardening pass before continuing the
contract work.
