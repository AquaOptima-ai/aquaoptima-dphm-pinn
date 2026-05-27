# Advisory safety contract (Sprint 37)

Sprint 37 adds the first typed, frozen, read-only **advisory safety
contract** surface to the dPHM. The contract answers, given a list of
hypothetical advisory proposals and optionally a Sprint 36
`DPLCalibrationLossReport`:

- which proposals would the contract **accept**?
- which proposals would it **reject**, and which rules did each
  proposal violate?
- can a future advisory layer prove it satisfies the contract before
  emitting anything?

Sprint 37 only audits hypothetical proposals. It never writes a
setpoint, never issues a command, never opens a live OT binding, and
never produces an actuator output. The contract surface is
**offline / read-only / no-write / no-control / no live OT binding /
no setpoint output / advisory proposal audit only**.

## Where it lives

`src/aquaoptima/dphm/advisory_contract.py`, re-exported through
`aquaoptima.dphm`.

## Public API

```python
from aquaoptima.dphm import (
    # Frozen dataclasses
    AdvisoryContractDiagnostics,
    AdvisoryRule,
    AdvisoryContract,
    AdvisoryProposal,
    AdvisoryDecision,
    # Builder / evaluator
    build_advisory_contract,
    evaluate_advisory_proposals,
    # Axis tokens
    ADVISORY_AXES,
    ADVISORY_AXIS_PUMP_SPEED,
    ADVISORY_AXIS_VALVE_POSITION,
    ADVISORY_AXIS_RESERVOIR_HEAD,
    ADVISORY_AXIS_TANK_LEVEL,
    ADVISORY_AXIS_NODE_PRESSURE,
    ADVISORY_AXIS_EDGE_FLOW,
    ADVISORY_AXIS_EDGE_VELOCITY,
    ADVISORY_AXIS_STATUS,
    # Decision status tokens
    ADVISORY_STATUSES,
    ADVISORY_STATUS_ACCEPTED,
    ADVISORY_STATUS_REJECTED,
    # Sprint 36 loss report the contract consumes
    DPLCalibrationLossReport,
)
```

## Concepts

A **contract** carries an allow-list and a deny-list of
`AdvisoryRule` entries. Each rule names an `(axis, target_id)` pair
and optional guard fields:

| Guard | Meaning |
|-------|---------|
| `min_value` | Inclusive lower bound on the proposed value. |
| `max_value` | Inclusive upper bound on the proposed value. |
| `max_abs_delta` | Maximum `|proposed - reference|`. Reference is `current_value` if present, otherwise `observed_value`. If neither is supplied, the guard is skipped and a deterministic warning is recorded. |
| `min_residual_support` | Minimum residual count for `(dpl_axis, target_id)` in a supplied `DPLCalibrationLossReport`. Requires the rule's axis to be mappable to a DPL axis. |
| `max_axis_loss` | Maximum MSE for `dpl_axis` in a supplied `DPLCalibrationLossReport`. Requires the rule's axis to be mappable to a DPL axis. |

A **proposal** is an `AdvisoryProposal` describing a hypothetical
advisory value. It is *never* an actuator command:

- `proposal_id` — required non-empty audit identifier.
- `axis` — one of `ADVISORY_AXES`.
- `target_id` — zero-based dPHM node / edge id (`>= 0`).
- `proposed_value` — numeric for non-status axes; `bool` / `0` / `1`
  for `status`.
- `current_value`, `observed_value` — optional reference values used
  by the `max_abs_delta` guard.
- `reason`, `source`, `metadata` — optional audit fields kept
  verbatim.

A **decision** is an `AdvisoryDecision` returned by
`evaluate_advisory_proposals`:

- `proposal` — the proposal verbatim.
- `accepted` — `True` iff every applicable allow rule passed and no
  deny rule matched.
- `status` — `"accepted"` or `"rejected"`.
- `reasons` — deterministic tuple of human-readable rejection
  explanations.
- `violated_rules` — deterministic tuple of rule descriptors
  (e.g. `"allow_rules[3]:max_value"`, `"deny_rules[1]"`,
  `"allow_rules:miss"`, `"malformed_proposal"`).
- `diagnostics` — per-decision warnings (e.g. skipped
  `max_abs_delta` guard because no reference value was supplied).

## Supported axes

| Advisory axis | DPL axis (for residual / loss gating) |
|---------------|---------------------------------------|
| `pump_speed` | `edge_pump_speed` |
| `valve_position` | `edge_valve_position` |
| `reservoir_head` | `node_pressure` |
| `tank_level` | `node_level` |
| `node_pressure` | `node_pressure` |
| `edge_flow` | `edge_flow` |
| `edge_velocity` | *(no DPL mapping — residual / loss guards are rejected)* |
| `status` | *(no DPL mapping — residual / loss guards are rejected)* |

The contract builder rejects any rule that sets
`min_residual_support` or `max_axis_loss` on an axis without a DPL
mapping; this prevents a silently misconfigured residual gate.

Status axes (`status`) accept `bool` or numeric `0` / `1` on the
proposal side; numeric values outside `{0, 1}` are rejected with the
strict / non-strict contract described below.

## Evaluation order

For each proposal:

1. Validate the proposal shape. Malformed proposals raise
   `ValueError` in `strict=True` mode; in `strict=False` mode the
   proposal is rejected with `violated_rules == ("malformed_proposal",)`
   and the explanation appears on `decision.diagnostics.errors`.
2. Apply deny rules. Any deny rule on `(axis, target_id)` produces
   a rejection reason naming the rule index.
3. Apply allow rules. If no allow rule matches `(axis, target_id)`,
   reject with `violated_rules == ("allow_rules:miss",)`. Otherwise,
   apply every matching allow rule — *each* must pass.
4. For every matching allow rule, evaluate every guard that is set
   (`min_value`, `max_value`, `max_abs_delta`, `min_residual_support`,
   `max_axis_loss`). All violations are accumulated, never
   short-circuited, so the decision audit lists every cause.

A proposal is accepted iff `reasons` is empty after this loop.

The decision tuple is returned in the same order as the input
proposals. Two evaluations on equal inputs return equal decision
tuples.

## Strict vs non-strict behaviour

`build_advisory_contract(..., strict=True)` (the default) raises
`ValueError` for any malformed rule:

- non-`AdvisoryRule` rule entry;
- axis not in `ADVISORY_AXES`;
- `target_id` is bool, non-int, or negative;
- non-finite or wrong-typed bound;
- `min_value > max_value`;
- negative `max_abs_delta` / `max_axis_loss`;
- `min_residual_support` is bool, non-int, or negative;
- residual / axis-loss guard on an axis without a DPL mapping.

`strict=False` returns a populated contract whose
`diagnostics.errors` lists each offending rule and *omits* it from
the contract. The contract is still usable for proposals that match
the valid rules. Duplicate-allow rules and allow / deny overlaps are
**always** warnings, never errors.

`evaluate_advisory_proposals(..., strict=True)` (the default) raises
`ValueError` for any structural problem with `contract`, `proposals`,
or `loss_report`, and for malformed individual proposals (empty
`proposal_id`, wrong axis, negative `target_id`, non-coercible
`proposed_value`, etc.). `strict=False` emits a rejected
`AdvisoryDecision` carrying the explanation in
`decision.diagnostics.errors` and continues processing.

`contract`, `proposals`, and `loss_report` argument-type errors
(passing a non-`AdvisoryContract`, a generator, a string) always
raise — they are programmer errors and are not gated by `strict`.

## Read-only contract

The builder and evaluator:

- never mutate the supplied `allow_rules` / `deny_rules` /
  `proposals` / `loss_report` (verified by deep-copy snapshot in the
  tests);
- never open a socket / process / live binding;
- never invoke the dPHM forward solver;
- never publish, write, or otherwise contact an external system;
- never return a write or control surface.

Every dataclass on the public surface is `frozen=True`. The
`allow_rules` / `deny_rules` / `reasons` / `violated_rules` /
`warnings` / `errors` are immutable Python tuples. The
`metadata` mapping on `AdvisoryProposal` is kept verbatim — the
evaluator never parses it.

## Safety boundary

This sprint adds **no** live binding. In particular:

- no SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST adapter
  is imported, registered, or polled;
- no write / control / setpoint path is exposed;
- no live OT binding is opened;
- no actuator surface is offered;
- no setpoint output is emitted — the Sprint 37 surface
  **audits hypothetical proposals only**;
- no automatic setpoint recommendation is produced;
- no dPHM forward solve is invoked — Sprint 37 reads the Sprint 36
  loss report when supplied, but never re-runs the forward model;
- no advisory output is published to any external system;
- no setpoint optimization is performed;
- no training-loop / optimizer integration is performed;
- no ONNX / TensorRT / Jetson deployment is performed;
- no production savings / control claim is made.

A future advisory layer would have to:

1. Build a contract via `build_advisory_contract`.
2. Compose a list of hypothetical `AdvisoryProposal` records.
3. Call `evaluate_advisory_proposals` and inspect the decision tuple.
4. Drop every rejected proposal **before** any downstream emission
   step.

Sprint 37 ships only steps 1–3. Step 4 (and any subsequent emission)
is **out of scope** for Sprint 37 and is intentionally not exposed by
this module.

## Worked example

```python
from aquaoptima.dphm import (
    ADVISORY_AXIS_PUMP_SPEED,
    AdvisoryProposal,
    AdvisoryRule,
    build_advisory_contract,
    evaluate_advisory_proposals,
)

contract = build_advisory_contract(
    name="primary-pumps",
    allow_rules=[
        AdvisoryRule(
            axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
            min_value=0.10, max_value=0.95,
            max_abs_delta=0.15,
            min_residual_support=2,
            max_axis_loss=0.05,
            note="primary pump envelope",
        ),
    ],
    deny_rules=[
        AdvisoryRule(
            axis=ADVISORY_AXIS_PUMP_SPEED, target_id=9,
            note="reserve pump 9 — never propose",
        ),
    ],
)

proposals = [
    AdvisoryProposal(
        proposal_id="P-2026-05-23-001",
        axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=0,
        proposed_value=0.70,
        current_value=0.80,
        reason="reduce energy at off-peak",
        source="dpl-shadow@v0",
    ),
    AdvisoryProposal(
        proposal_id="P-2026-05-23-002",
        axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=9,            # deny-listed
        proposed_value=0.50,
        current_value=0.50,
    ),
]

# loss_report is a Sprint 36 DPLCalibrationLossReport. Pass None
# during prototyping to exercise the contract without residual
# / axis-loss gates.
decisions = evaluate_advisory_proposals(
    contract, proposals, loss_report=None,
)

for d in decisions:
    print(d.proposal.proposal_id, d.status, d.reasons)
```

## Limitations

- Sprint 37 audits proposals against a contract. It never emits an
  advisory or setpoint and never opens a live binding — that is
  intentional and constitutes the safety boundary.
- The `min_residual_support` and `max_axis_loss` guards require a
  Sprint 36 `DPLCalibrationLossReport`. Without a report, rules that
  set those guards always reject (so a future caller cannot quietly
  bypass them by forgetting to pass a report).
- `max_abs_delta` only fires when the proposal carries a reference
  value (`current_value` or `observed_value`). When neither is
  supplied, the guard is skipped and a deterministic warning is
  recorded on the decision — this matches the audit-only contract
  surface and is intentional.
- Advisory axes without a DPL mapping (`edge_velocity`, `status`)
  cannot carry residual / axis-loss guards. The contract builder
  rejects such rules.
- The evaluator is O(rules) per proposal; allow rules are indexed by
  `(axis, target_id)` for O(1) lookup.
