# Sprint 37 — advisory safety contract

## Goal

Add a typed, frozen, read-only **advisory safety contract** surface
to the dPHM. Given a contract plus a list of hypothetical advisory
proposals (and optionally a Sprint 36 `DPLCalibrationLossReport`),
the surface answers — deterministically and auditably — which
proposals the contract would *accept* and which it would *reject*,
together with the exact reasons and rule descriptors that triggered
each rejection.

Sprint 37 is **offline / read-only / no-write / no-control / no live
OT binding / no setpoint output / advisory proposal audit only**. No
live OT adapter is opened, no actuator surface is exposed, no
setpoint output is emitted, no dPHM forward solve is invoked, no
training loop is added.

## Files changed

- `src/aquaoptima/dphm/advisory_contract.py` (new module) — frozen
  dataclasses (`AdvisoryContractDiagnostics`, `AdvisoryRule`,
  `AdvisoryContract`, `AdvisoryProposal`, `AdvisoryDecision`), the
  canonical axis tokens (`ADVISORY_AXES` and per-axis constants),
  the decision status tokens (`ADVISORY_STATUS_ACCEPTED`,
  `ADVISORY_STATUS_REJECTED`, `ADVISORY_STATUSES`), the public
  builder `build_advisory_contract`, and the public evaluator
  `evaluate_advisory_proposals`.
- `src/aquaoptima/dphm/__init__.py` (updated) — re-exports the new
  dataclasses, axis constants, status tokens, builder, and evaluator.
  No existing exports change.
- `tests/dphm/test_advisory_contract.py` (new) — 60+ focused tests
  covering the public surface, the strict / non-strict contract,
  every required Sprint 37 behaviour (frozen surface, accept path,
  deny-list rejection, allow-list miss, min/max bounds, max delta,
  residual support gate, DPL axis-loss gate, deterministic ordering,
  build-time / eval-time diagnostics, read-only invariant, no live
  adapter substrings, docs / report evidence).
- `docs/advisory-contract.md` (new) — Sprint 37 surface documentation
  including the public API, axis mapping table, evaluation order,
  strict / non-strict semantics, the reaffirmed safety boundary, and
  a worked example.
- `SPRINT37_REPORT.md` (this file).

No other source file is touched. The new module imports only the
Sprint 34 axis tokens (re-exported through Sprint 36), the Sprint 36
`DPLCalibrationLossReport` dataclass, and stdlib `math` /
`dataclasses` / `typing`. No new third-party dependency. No parser,
solver, IO, or training module is modified.

## API design

Five frozen dataclasses:

- `AdvisoryContractDiagnostics(warnings: tuple[str, ...] = (),
  errors: tuple[str, ...] = ())` — deterministic warning / error
  tuples, identical surface shape to Sprint 34 / 35 / 36 diagnostics.
- `AdvisoryRule(axis, target_id, min_value=None, max_value=None,
  max_abs_delta=None, min_residual_support=None, max_axis_loss=None,
  note="")` — single allow- or deny-list entry within a contract.
- `AdvisoryContract(name="", allow_rules=(), deny_rules=(),
  diagnostics=AdvisoryContractDiagnostics())` — frozen top-level
  container.
- `AdvisoryProposal(proposal_id, axis, target_id, proposed_value,
  current_value=None, observed_value=None, reason="", source="",
  metadata={})` — proposed advisory value, **never** an actuator
  command.
- `AdvisoryDecision(proposal, accepted, status, reasons=(),
  violated_rules=(), diagnostics=AdvisoryContractDiagnostics())` —
  deterministic per-proposal verdict.

Two public functions:

- `build_advisory_contract(*, name="", allow_rules=(), deny_rules=(),
  strict=True) -> AdvisoryContract` — pure builder that canonicalises
  and validates contract inputs. Never mutates inputs; never opens a
  binding.
- `evaluate_advisory_proposals(contract, proposals, *,
  loss_report=None, strict=True) -> tuple[AdvisoryDecision, ...]` —
  pure deterministic evaluator. Never mutates inputs; never opens a
  binding; never invokes the forward solver.

Eight advisory axis constants (`ADVISORY_AXIS_PUMP_SPEED`,
`ADVISORY_AXIS_VALVE_POSITION`, `ADVISORY_AXIS_RESERVOIR_HEAD`,
`ADVISORY_AXIS_TANK_LEVEL`, `ADVISORY_AXIS_NODE_PRESSURE`,
`ADVISORY_AXIS_EDGE_FLOW`, `ADVISORY_AXIS_EDGE_VELOCITY`,
`ADVISORY_AXIS_STATUS`) plus the `ADVISORY_AXES` tuple in canonical
order. Three decision-status tokens (`ADVISORY_STATUS_ACCEPTED`,
`ADVISORY_STATUS_REJECTED`, `ADVISORY_STATUSES`).

All public symbols are re-exported through `aquaoptima.dphm`.

## Behaviour summary

Per proposal, the evaluator executes the following deterministic
steps:

1. Validate proposal shape. Malformed proposals raise in strict
   mode; in non-strict mode they produce a rejected decision with
   `violated_rules == ("malformed_proposal",)`.
2. Apply deny rules. Every deny rule on `(axis, target_id)`
   contributes one rejection reason naming the rule index.
3. Apply allow rules. If no allow rule matches `(axis, target_id)`,
   reject with `violated_rules == ("allow_rules:miss",)`. Otherwise
   *every* matching allow rule must pass.
4. For each matching allow rule, evaluate every set guard
   (`min_value`, `max_value`, `max_abs_delta`, `min_residual_support`,
   `max_axis_loss`). All violations are accumulated.

The decision tuple is returned in the same order as the input
proposals. Two evaluations on equal inputs return equal decisions.

Guard semantics:

- `min_value` / `max_value` are inclusive bounds on `proposed_value`.
- `max_abs_delta` compares the proposed value to a reference value
  (`current_value` if present, otherwise `observed_value`). When
  neither is supplied the guard is skipped and a deterministic
  warning is recorded.
- `min_residual_support` requires `count >= threshold` residuals on
  `(dpl_axis, target_id)` in the supplied `DPLCalibrationLossReport`.
  Without a report, the rule rejects every proposal it applies to
  (this prevents silently bypassing the gate).
- `max_axis_loss` requires `mse_by_axis[dpl_axis] <= threshold` in
  the supplied `DPLCalibrationLossReport`. Without a report the rule
  rejects.

Status axes (`status`) accept `bool` or numeric `0 / 1`. Numeric
values outside `{0, 1}` are rejected with the same strict / non-strict
contract as other malformed proposals.

The contract builder enforces:

- well-formed `AdvisoryRule` entries (recognised axis, non-negative
  `target_id`, finite bounds, `min_value <= max_value`,
  non-negative deltas / losses, integer `min_residual_support`);
- residual / axis-loss guards are only set on axes that have a DPL
  mapping;
- duplicate-allow rules and allow / deny overlaps are warnings
  (deny always wins at evaluation time).

## Safety boundary

This sprint adds **no** live binding. In particular:

- no SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST adapter
  is imported, registered, or polled;
- no write / control / setpoint path is exposed;
- no live OT binding is opened;
- no setpoint output is emitted — Sprint 37 only audits
  hypothetical proposals;
- no automatic setpoint recommendation is produced;
- no dPHM forward solve is invoked — Sprint 37 reads the Sprint 36
  loss report when supplied, but never re-runs the forward model;
- no advisory output is published to any external system;
- no setpoint optimization is performed;
- no training-loop / optimizer integration is performed;
- no ONNX / TensorRT / Jetson deployment is performed;
- no production savings / control claim is made.

Every dataclass on the public surface is `frozen=True`. The
`allow_rules` / `deny_rules` / `reasons` / `violated_rules` /
`warnings` / `errors` are immutable Python tuples. The
`AdvisoryDecision` carries the proposal verbatim (identity-preserving
passthrough for the original `AdvisoryProposal` reference).

Sprint 37 stops at *auditing* proposals. The downstream emission step
(actually issuing a setpoint to a live actuator) is **out of scope**
and is intentionally not exposed by this module.

## Tests added

`tests/dphm/test_advisory_contract.py` covers:

1. Public exports (re-exported via `aquaoptima.dphm`).
2. Frozen-dataclass surfaces (assigning to any frozen field raises
   `FrozenInstanceError`).
3. Default-constructed dataclasses.
4. Empty contract build.
5. Strict raises / non-strict records errors for malformed rules
   (unknown axis, negative target id, non-finite bound, min > max,
   negative delta, negative or bool residual-support, residual /
   axis-loss guard on axis without DPL mapping).
6. Duplicate-allow and allow/deny-overlap warnings.
7. `allow_rules` / `deny_rules` must be sequences (string / generator
   rejected).
8. Accept path with basic min / max guards.
9. Accept path with no guards and no reference value.
10. Deny-list rejection is unconditional.
11. Deny-list wins over allow-list overlap.
12. Allow-list miss rejection (`allow_rules:miss`).
13. Axis-mismatch rejection.
14. `min_value` / `max_value` rejection (above and below).
15. Inclusive bound edges accept exactly at the boundary.
16. `max_abs_delta` rejection against `current_value`.
17. `max_abs_delta` falls back to `observed_value` when
    `current_value` is absent.
18. `max_abs_delta` is skipped (warning) when neither reference is
    supplied.
19. `max_abs_delta` accepts inside the envelope.
20. `min_residual_support` accept with sufficient residuals.
21. `min_residual_support` reject due to low count.
22. `min_residual_support` rejects when no loss report is supplied.
23. `min_residual_support` counts only matching `(axis, target_id)`.
24. `max_axis_loss` accept (MSE within budget).
25. `max_axis_loss` reject (MSE over budget).
26. `max_axis_loss` rejects when no loss report is supplied.
27. Status axis accepts `bool` proposals.
28. Status axis numeric outside `{0,1}` raises in strict.
29. Status axis numeric outside `{0,1}` produces rejected decision in
    non-strict.
30. Decision tuple preserves proposal input order.
31. Reasons aggregate all violations deterministically.
32. Repeat evaluation produces equal results.
33. Malformed proposal strict raises.
34. Malformed proposal non-strict records rejected decision.
35. Non-`AdvisoryProposal` object rejected.
36. `proposed_value=NaN` rejected.
37. `proposed_value=True` rejected on numeric axis.
38. `proposals=""` rejected.
39. `proposals=generator` rejected.
40. Non-`AdvisoryContract` `contract` rejected.
41. Non-`DPLCalibrationLossReport` `loss_report` rejected.
42. Builder / evaluator do not mutate inputs (deep-copy snapshot
    comparison).
43. No live-adapter substrings (`write`, `control`, `setpoint`,
    `actuate`, `publish`, `subscribe`, `ingest`, `poll`, `scada`,
    `plc`, `historian`, `opcua`, `mqtt`, `rest_client`, `http_client`,
    `open_socket`, `open_connection`, `train`, `optim`) in the
    module's `__all__`.
44. No live-network stdlib references (`socket`, `asyncio`, `ssl`,
    `urllib`, `smtplib`) on the module.
45. No forbidden live-callable patterns (e.g. `socket.socket(`,
    `subprocess.Popen(`, `urllib.request.urlopen(`,
    `smtplib.SMTP(`, `asyncio.run(`, `open_connection(`,
    `publish(`, `subscribe(`) in the module source.
46. Module source contains every required safety phrase
    (`offline`, `read-only`, `no-write`, `no-control`,
    `no live OT binding`, `no setpoint output`,
    `advisory proposal audit only`).
47. `docs/advisory-contract.md` contains every required safety
    phrase and names every public dataclass and function.
48. `SPRINT37_REPORT.md` contains every required safety phrase and
    names every public dataclass and function.
49. Combined guard accept (every guard passes simultaneously).
50. Combined guard reject collects every violation descriptor.
51. Multiple allow rules on the same `(axis, target_id)` — all must
    pass.
52. `max_axis_loss=0.0` with `mse=0.0` accepts (strict equality
    boundary).
53. Decision carries the original `AdvisoryProposal` by identity.
54. Empty proposals → empty decisions tuple.
55. Proposal `metadata` is preserved verbatim.
56. `reservoir_head` and `tank_level` axes correctly route to DPL
    `node_pressure` / `node_level` for residual gating.

(See the test file for the exact enumeration; the file ships 60+
test functions.)

## Verification commands / results

Run from the worktree root:

```bash
python -m pip install -e .
python -c "import aquaoptima, pathlib; print(pathlib.Path(aquaoptima.__file__).resolve())"
python -m pytest tests/dphm/test_advisory_contract.py -q
python -m pytest tests/dphm tests/models -q
python -m pytest -q
python -m compileall src tests
git diff --check
python -c "import wntr; print('wntr', wntr.__version__)"
git status --short
```

Results captured at report write-time:

- `python -m pip install -e .` → editable install succeeds.
- `python -c "import aquaoptima, pathlib; print(...)"` →
  `/home/hunter_lin/projects/aquaoptima-dphm-pinn-sprint37/src/aquaoptima/__init__.py`.
- `python -m pytest tests/dphm/test_advisory_contract.py -q` →
  **70 passed** in ~2.3s.
- `python -m pytest tests/dphm tests/models -q` →
  **1405 passed, 1 skipped** (existing WNTR optional-import skip).
- `python -m pytest -q` → **1541 passed, 1 skipped** (Sprint 36
  baseline of 1471 + 70 new Sprint 37 tests = 1541).
- `python -m compileall src tests` → clean.
- `git diff --check` → clean.
- `python -c "import wntr; print('wntr', wntr.__version__)"` →
  `wntr 1.4.0`.
- Secret scan over changed files → no private-key / API-key /
  password / token / secret / credential substrings.
- `git status --short` → only the Sprint 37 files (new module, new
  test, new doc, new report, `__init__.py` re-exports).

## Compatibility notes

- The Sprint 36 `DPLCalibrationLossReport` is consumed verbatim; the
  Sprint 37 evaluator reads `loss_report.residuals` and
  `loss_report.mse_by_axis` only, and never re-validates the
  Sprint 36 surface.
- No existing public symbol changes. No existing test changes.
- No new third-party dependency: only stdlib `math` /
  `dataclasses` / `typing` are imported by the new module.
- The aquaoptima.dataio Sprint 4.5 telemetry abstraction is
  untouched; Sprint 37 sits behind the same dPHM-side surface as
  Sprints 34 / 35 / 36.
- No live binding, no setpoint write, no control path, no
  advisory emission surface — strictly out of scope per the
  Sprint 37 brief.

## Known limitations

- Sprint 37 audits hypothetical proposals only. The downstream
  emission step (issuing the accepted advisory to any external
  system) is **out of scope** and is intentionally not exposed.
- `min_residual_support` and `max_axis_loss` require a Sprint 36
  `DPLCalibrationLossReport`. Without a report, rules that set those
  guards always reject — a future caller cannot quietly bypass them
  by forgetting to pass a report.
- `max_abs_delta` only fires when the proposal carries a reference
  value (`current_value` or `observed_value`). When neither is
  supplied, the guard is skipped and a deterministic warning is
  recorded.
- The advisory axes `edge_velocity` and `status` have no DPL
  counterpart, so residual / axis-loss guards cannot be set on them.
  The contract builder enforces this at build time.
- The evaluator processes proposals one at a time, in input order,
  with O(rules) work per proposal. Allow / deny rules are indexed by
  `(axis, target_id)` for O(1) lookup; no batched / vectorised
  evaluation surface is exposed.
- The `metadata` field on `AdvisoryProposal` is typed as `Mapping`
  but is not deep-copied — callers who care about pure immutability
  should pass a `MappingProxyType` or a frozen mapping. The
  `AdvisoryProposal` dataclass binding itself is `frozen=True`.
- No tensor / autograd helper is exposed. Sprint 37 stops at the
  data contract; downstream consumers can wrap it in their own
  PyTorch layer if needed.

## Verdict

Sprint 37 ships a typed, deterministic, frozen, read-only advisory
safety contract surface that accepts Sprint 36's
`DPLCalibrationLossReport` and a caller-supplied list of hypothetical
`AdvisoryProposal` records and emits a deterministic tuple of
`AdvisoryDecision` verdicts. The module is `offline`, `read-only`,
`no-write`, `no-control`, opens no live OT binding, emits no setpoint
output, and ships `advisory proposal audit only`. All required
Sprint 37 verification items are exercised by the test suite; the
existing repo-wide baseline is preserved; the new module adds no
third-party dependency.

Ready for Hermes verification.

## Sprint 38 recommendation

The contract surface now in place gives a future advisory layer the
*safety pre-condition* it must satisfy before any output can leave
the dPHM offline boundary. The remaining structural gap is a
**dPL training-loop scaffolding** that ties the Sprint 36 loss
prototype to a deterministic optimisation step and a Sprint 37
contract-audit pre-step before any candidate output is even logged.

**Recommendation: Sprint 38 → dPL shadow training-loop scaffolding.**
Land a typed, frozen `DPLTrainingScaffold` that wraps:

1. A Sprint 35 `ShadowReplayDataset` and a deterministic
   prediction-source callable (model / dPHM forward solve / hybrid).
2. A Sprint 36 `build_dpl_calibration_loss_report` call to compute
   per-axis MSE and the weighted MSE.
3. A Sprint 37 `evaluate_advisory_proposals` call against a
   caller-supplied `AdvisoryContract` over a candidate proposal list
   the scaffold *generates from observations but does not emit*.
4. A deterministic per-epoch `DPLTrainingReport` carrying the loss
   value, the contract-audit summary (`accepted_count` /
   `rejected_count` / first N rejection reasons), and a deterministic
   warnings / errors tuple.

Sprint 38 should remain shadow-mode only: no actuator surface, no
setpoint output, no live binding, no PyTorch `.backward()` call
(the optimisation step is a separate Sprint 39+). The smallest
possible follow-up after the scaffold lands is the actual
`torch.optim`-driven training step, which can then run under the
Sprint 37 contract as a hard precondition before any advisory output
would be considered for emission.

If, during Sprint 38 prototyping, a contract-blocking limitation
surfaces in the Sprint 37 surface (e.g. a need for per-frame instead
of axis-aggregate loss gates, or a need for batched evaluation), the
smallest possible follow-up — a single additional field on
`AdvisoryRule` plus a focused test pass — should land as a
Sprint 37a hardening pass before continuing the scaffold work.
