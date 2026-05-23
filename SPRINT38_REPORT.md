# Sprint 38 — shadow-mode runtime harness

## Goal

Wire the Sprint 35 `ShadowReplayDataset`, caller-supplied per-frame
predictions, the Sprint 36 `DPLCalibrationLossReport` builder, and the
Sprint 37 `AdvisoryContract` proposal evaluator into a single typed,
deterministic *runtime audit harness*: `run_shadow_runtime(...)`.

Sprint 38 is **offline / read-only / no-write / no-control / no live
OT binding / no setpoint output / replay/audit only**. It is **not**
a live runtime, **not** a controller, and **not** an advisory
emission layer. No live OT adapter is opened, no actuator surface is
exposed, no setpoint output is emitted, no dPHM forward solve is
invoked, no training loop is added, no filesystem write happens from
the harness function.

## Files changed

- `src/aquaoptima/dphm/shadow_runtime.py` (new module) — frozen
  dataclasses (`ShadowRuntimeDiagnostics`, `ShadowRuntimeStepReport`,
  `ShadowRuntimeReport`) plus the public driver
  `run_shadow_runtime`. Imports Sprint 35 / 36 / 37 dataclasses and
  the Sprint 36 / 37 builders only; pure stdlib otherwise.
- `src/aquaoptima/dphm/__init__.py` (updated) — re-exports the new
  dataclasses and driver. No existing export changes.
- `tests/dphm/test_shadow_runtime.py` (new) — focused tests covering
  the public surface, the strict / non-strict harness, every
  required Sprint 38 behaviour (frozen surface, minimal run, loss
  report integration, per-step shape, advisory contract integration
  via both proposal sources, deterministic ordering, harness-level
  diagnostics, no live adapter substrings, docs / report evidence).
- `docs/shadow-runtime.md` (new) — Sprint 38 harness documentation
  including the public API, output shape, deterministic ordering,
  strict / non-strict semantics, the reaffirmed safety boundary, and
  a worked example.
- `SPRINT38_REPORT.md` (this file).

No other source file is touched. The new module imports only the
Sprint 35-37 dataclasses + builders and stdlib `dataclasses` /
`typing`. No new third-party dependency. No parser, solver, IO, or
training module is modified.

## API design

Three frozen dataclasses:

- `ShadowRuntimeDiagnostics(warnings: tuple[str, ...] = (),
  errors: tuple[str, ...] = ())` — identical surface shape to
  Sprint 34/35/36/37 diagnostics.
- `ShadowRuntimeStepReport(frame_index, timestamp,
  observation_counts={}, prediction_axes=(), prediction_counts={},
  residuals=(), observation_count=0, mse_by_axis={}, mae_by_axis={},
  advisory_decisions=(), diagnostics=ShadowRuntimeDiagnostics())` —
  one per replay frame.
- `ShadowRuntimeReport(steps=(), loss_report=DPLCalibrationLossReport(),
  advisory_decisions=(), frame_count=0, observation_count=0,
  proposal_count=0, accepted_count=0, rejected_count=0,
  diagnostics=ShadowRuntimeDiagnostics())` — top-level result.

One public function:

- `run_shadow_runtime(replay, predictions, *, advisory_contract=None,
  proposal_builder=None, proposals_by_frame=None, axis_weights=None,
  strict=True) -> ShadowRuntimeReport`.

All four public symbols are re-exported through `aquaoptima.dphm`.

## Runtime behaviour summary

Per call, `run_shadow_runtime` executes the following deterministic
steps:

1. Type-check `replay`, `advisory_contract`, `proposal_builder`,
   and `proposals_by_frame`. Both proposal sources at once is
   rejected. Programmer errors always raise.
2. Invoke Sprint 36 `build_dpl_calibration_loss_report(replay,
   predictions, axis_weights=axis_weights, strict=strict)` once.
   Residual math is **not** re-implemented here.
3. Index the resulting residuals by `frame_index` for per-step
   lookup.
4. Resolve the per-frame proposal list (`proposal_builder`,
   `proposals_by_frame`, or none) in replay order. Builder
   exceptions are wrapped; non-sequence returns / entries are
   surfaced as errors (strict raises, non-strict records).
5. If an `advisory_contract` is supplied, evaluate each frame's
   proposals via Sprint 37 `evaluate_advisory_proposals(contract,
   proposals, loss_report=loss_report, strict=strict)`. The
   contract's `max_axis_loss` / `min_residual_support` guards see
   the run's own loss report.
6. Build the per-frame `ShadowRuntimeStepReport`: timestamp,
   observation counts (DPL_AXES order), prediction axes / counts,
   residuals attributable to the frame, per-frame MSE / MAE
   restricted to non-empty axes, and the advisory decisions for
   that frame.
7. Assemble the top-level `ShadowRuntimeReport`: steps tuple, the
   Sprint 36 loss report, the flat advisory-decisions tuple in
   frame-then-input order, and aggregate counts.

The harness is **pure**: identical inputs produce identical reports
(repeat-stable). It never mutates `replay`, `predictions`,
`advisory_contract`, the proposal sources, or the axis weights.
It never opens a socket, file, or subprocess. It never invokes the
dPHM forward solver. It never emits a setpoint.

## Verification outputs

- `python -m pip install -e .` — succeeded.
- `import aquaoptima` resolves to the in-repo `src/aquaoptima`
  package.
- `python -m pytest tests/dphm/test_shadow_runtime.py -q` — passes
  (40 tests covering the public surface, frozen surface, run
  shape, per-step indexing, both proposal source paths, strict /
  non-strict diagnostics, deterministic ordering, type-check
  raises, safety boundary, doc evidence).
- `python -m pytest tests/dphm tests/models -q` — passes (Sprint 38
  additions do not regress Sprint 1-37 tests).
- `python -m pytest -q` — full suite passes.
- `python -m compileall src tests` — passes.
- `git diff --check` — clean.
- `wntr` import — works (1.x).
- Secret scan over changed files — no private keys, API keys,
  passwords, tokens, secrets, credentials, or connection strings.

## Safety boundary / limitations

Sprint 38 deliberately preserves the offline / read-only / no-write
/ no-control / no live OT binding / no setpoint output /
replay/audit only boundary established in Sprint 23 and tightened
through Sprints 34-37:

- no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter is imported, registered, or polled;
- no write / control / setpoint path is exposed;
- no live OT binding is opened;
- no actuator / write surface is offered;
- no setpoint output is emitted, even when every proposal is
  accepted;
- no automatic setpoint recommendation is produced — the harness
  only audits hypothetical proposals against a read-only contract
  and reports dPL calibration loss against offline observations;
- no dPHM forward solve is invoked — predictions are caller-
  supplied verbatim;
- no training loop / optimiser integration is performed;
- no ONNX / TensorRT / Jetson deployment is performed;
- no production savings / control claim is made;
- no filesystem writes are performed from the harness function.

Limitations:

- The harness consumes predictions verbatim. Sprint 38 does not
  call the dPHM forward solver; a future sprint that wires the
  solver behind a deterministic, still-offline cache could expose
  a `predictions_from_solver(replay, network)` helper instead.
- The advisory contract surface here is exactly the Sprint 37
  surface — no new guards, no new axes, no new statuses. The
  contract's `max_axis_loss` / `min_residual_support` guards see
  the run-level loss report, not the per-frame one.
- The proposal builder callback runs in-process, synchronously,
  one frame at a time. There is no scheduler, no concurrency, no
  retry / timeout behaviour.

## Next sprint recommendation

Two options, both compatible with the read-only boundary:

1. **Shadow-runtime artefact loader / serialiser**. Add a
   stdlib-only JSON serialiser for `ShadowRuntimeReport` (plus a
   matching loader) so offline runs can be persisted, diffed across
   model versions, and reviewed by a human operator without
   re-running the harness. This is a pure value-surface extension
   — no live binding, no setpoint output.
2. **Shadow-runtime conformance harness against a stub
   forward-solver wrapper**. Add a typed, deterministic adapter
   `predictions_from_solver(replay, network)` that calls the
   Sprint 1-12 forward solver behind a caching layer to produce
   per-frame predictions. The harness function itself would still
   be untouched — only the per-call helper that produces
   `predictions` would change — keeping the safety boundary intact.

Recommended: option 1 first (cheap, unlocks operator review and
regression tracking), then option 2 once a deterministic solver
wrapper exists.
