# Shadow-mode runtime harness (Sprint 38)

Sprint 38 wires Sprint 35's replay dataset, the caller-supplied
per-frame predictions, the Sprint 36 `DPLCalibrationLossReport`
builder, and the Sprint 37 `AdvisoryContract` proposal evaluator into
a single typed, deterministic *runtime audit harness*.

Sprint 38 is **offline / read-only / no-write / no-control / no live
OT binding / no setpoint output / replay/audit only**. It is **not**
a live runtime, **not** a controller, and **not** an advisory
emission layer. Even an accepted advisory decision is never
transformed into a setpoint write here — Sprint 38 only reports.

## Where it lives

`src/aquaoptima/dphm/shadow_runtime.py`, re-exported through
`aquaoptima.dphm`.

## Public API

```python
from aquaoptima.dphm import (
    # Frozen dataclasses
    ShadowRuntimeDiagnostics,
    ShadowRuntimeStepReport,
    ShadowRuntimeReport,
    # Driver
    run_shadow_runtime,
)
```

`run_shadow_runtime` signature:

```python
def run_shadow_runtime(
    replay: ShadowReplayDataset,
    predictions: Sequence[Mapping[str, Mapping[int, float]]],
    *,
    advisory_contract: AdvisoryContract | None = None,
    proposal_builder: Callable[[int, ShadowReplayFrame], Sequence[AdvisoryProposal]] | None = None,
    proposals_by_frame: Sequence[Sequence[AdvisoryProposal]] | None = None,
    axis_weights: Mapping[str, float] | None = None,
    strict: bool = True,
) -> ShadowRuntimeReport: ...
```

## Concepts

A **replay** is a Sprint 35 `ShadowReplayDataset` (offline frames
keyed by canonical dPHM axis / id).

**Predictions** are a sequence of `{axis: {target_id: value}}`
mappings, one per replay frame, in the same canonical units as the
observations. They are forwarded verbatim to
`build_dpl_calibration_loss_report`.

An **advisory contract** is a Sprint 37 `AdvisoryContract`. When
supplied together with one of the two proposal sources, every
proposal scoped to a frame is audited against the contract — and
the contract's `max_axis_loss` / `min_residual_support` guards see
the run's own `DPLCalibrationLossReport`.

Two mutually-exclusive proposal sources are supported:

- `proposal_builder` — a callback
  `(frame_index, frame) -> Sequence[AdvisoryProposal]` invoked once
  per frame in replay order. Returning `None` or an empty sequence
  means "no proposals this frame".
- `proposals_by_frame` — a sequence of per-frame proposal sequences
  indexed by frame number. Must have the same length as the replay
  (strict mode raises, non-strict mode records a warning).

Supplying both raises `ValueError`. Supplying proposals without an
`advisory_contract` is accepted but records a warning and produces
no decisions (Sprint 38 never silently audits without a contract,
and it never emits anything).

## Output shape

```text
ShadowRuntimeReport
├── steps: tuple[ShadowRuntimeStepReport, ...]   # one per replay frame
│   ├── frame_index, timestamp
│   ├── observation_counts: {axis: count}
│   ├── prediction_axes: tuple[str, ...]
│   ├── prediction_counts: {axis: count}
│   ├── residuals: tuple[DPLResidual, ...]       # scoped to this frame
│   ├── observation_count: int                   # = len(residuals)
│   ├── mse_by_axis / mae_by_axis                # per-frame, non-empty axes only
│   ├── advisory_decisions: tuple[AdvisoryDecision, ...]
│   └── diagnostics: ShadowRuntimeDiagnostics
├── loss_report: DPLCalibrationLossReport       # whole-run Sprint 36 report
├── advisory_decisions: tuple[AdvisoryDecision, ...]   # flat, frame-then-input order
├── frame_count, observation_count
├── proposal_count, accepted_count, rejected_count
└── diagnostics: ShadowRuntimeDiagnostics
```

All collection fields are frozen tuples or freshly allocated
dicts; the dataclasses themselves are frozen.

## Determinism

Every list, tuple, and mapping the harness emits is in a fully
deterministic order:

- `steps` follows `replay.frames` order.
- `step.residuals` is in Sprint 36 order (frame index, then
  canonical axis order, then ascending target id).
- `step.advisory_decisions` is in per-frame input order.
- `advisory_decisions` (run-level) is frame order, then per-frame
  input order.
- `step.observation_counts`, `step.prediction_counts`,
  `step.mse_by_axis`, `step.mae_by_axis` honour the canonical
  `DPL_AXES` order; unsupported prediction axes are appended in
  `sorted` order.

Calling `run_shadow_runtime(...)` twice on the same inputs returns
equal reports.

## Strict / non-strict semantics

In strict mode (`strict=True`, default):

- a proposal_builder that returns a non-sequence raises;
- a proposal_builder that raises an exception is wrapped in
  `ValueError`;
- a `proposals_by_frame` entry that is not a `Sequence` raises;
- a `proposals_by_frame` whose length does not match `replay.frames`
  raises;
- Sprint 36 `build_dpl_calibration_loss_report` raises on its
  structural errors (length mismatch, missing prediction, etc.);
- Sprint 37 `evaluate_advisory_proposals` raises on malformed
  proposals.

In non-strict mode (`strict=False`):

- the same conditions record a deterministic error string on
  `ShadowRuntimeReport.diagnostics.errors` (or, for the length-
  mismatch case, on `diagnostics.warnings`) and the offending input
  is treated as "no proposals" / "no residual" for the affected
  frame;
- `strict=False` is forwarded to Sprint 36 and Sprint 37, so their
  own per-row / per-proposal errors land on their respective
  diagnostics tuples instead of raising.

Programmer errors — non-`Sequence` `proposals_by_frame`, a non-
callable `proposal_builder`, a non-`AdvisoryContract` advisory
contract, supplying both proposal sources, invalid `axis_weights` —
always raise regardless of `strict`.

## Safety boundary

Sprint 38 reaffirms the safety boundary first declared in Sprint 23
and tightened by every shadow-mode sprint since:

- no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter is imported, registered, or polled;
- no write / control / setpoint path is exposed;
- no live OT binding is opened;
- no actuator / write surface is offered;
- no setpoint output is emitted;
- no automatic setpoint recommendation is produced — the harness
  only audits hypothetical advisory proposals against a read-only
  contract and reports dPL calibration loss against offline
  observations;
- no dPHM forward solve is invoked (the harness consumes
  caller-supplied predictions verbatim);
- no training loop / optimiser integration is performed;
- no ONNX / TensorRT / Jetson deployment is performed;
- no production savings / control claim is made;
- no filesystem writes are performed from the harness function
  (the harness is a pure function — it never opens a file).

The deliberate framing is **replay/audit only**: Sprint 38 is the
seam where a future deployment-readiness review would attach
trust-boundary plumbing, write-side authorisation, and
operator-in-the-loop sign-off — none of which exist yet.

## Worked example

```python
from aquaoptima.dphm import (
    AdvisoryRule, ADVISORY_AXIS_PUMP_SPEED,
    AdvisoryProposal,
    build_advisory_contract,
    build_shadow_replay_dataset,
    build_telemetry_tag_map,
    run_shadow_runtime,
    TelemetryTagSpec, TELEMETRY_TARGET_EDGE, TELEMETRY_TARGET_NODE,
    TELEMETRY_AXIS_NODE_PRESSURE, TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    make_pump_network,
)

network = make_pump_network()
tag_map = build_telemetry_tag_map(
    [
        TelemetryTagSpec("PT1", TELEMETRY_TARGET_NODE, 1, "pressure", "m"),
        TelemetryTagSpec("FT1", TELEMETRY_TARGET_EDGE, 1, "flow", "m3/s"),
        TelemetryTagSpec("PS1", TELEMETRY_TARGET_EDGE, 0, "pump_speed", "fraction"),
    ],
    network,
)
replay = build_shadow_replay_dataset(
    [{"timestamp": 0.0, "PT1": 10.5, "FT1": 0.020, "PS1": 0.80}],
    tag_map,
)
predictions = [
    {
        TELEMETRY_AXIS_NODE_PRESSURE: {1: 10.6},
        TELEMETRY_AXIS_EDGE_FLOW: {1: 0.019},
        TELEMETRY_AXIS_EDGE_PUMP_SPEED: {0: 0.80},
    }
]
contract = build_advisory_contract(
    allow_rules=[
        AdvisoryRule(
            axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
            min_value=0.10, max_value=0.95, max_abs_delta=0.20,
        )
    ]
)
proposals = [
    [
        AdvisoryProposal(
            proposal_id="P1", axis=ADVISORY_AXIS_PUMP_SPEED,
            target_id=0, proposed_value=0.78, current_value=0.80,
        )
    ]
]

report = run_shadow_runtime(
    replay, predictions,
    advisory_contract=contract,
    proposals_by_frame=proposals,
)

assert report.frame_count == 1
assert report.proposal_count == 1
assert report.accepted_count == 1
# Nothing is written, nothing is published, nothing is actuated.
# `report` is a frozen value the caller can serialise, log, or diff.
```
