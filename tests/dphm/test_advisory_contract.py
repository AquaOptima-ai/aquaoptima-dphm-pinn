"""Sprint 37 — advisory safety contract.

Sprint 37 introduces a typed, frozen, read-only audit surface for
hypothetical advisory proposals against an
:class:`AdvisoryContract`. The contract optionally consumes a
Sprint 36 :class:`DPLCalibrationLossReport` to gate residual support
and per-axis MSE.

These tests cover, in order:

1. Public exports (re-exported via ``aquaoptima.dphm``).
2. Frozen dataclasses.
3. Default-constructed dataclasses.
4. Build path: allow / deny rules canonicalised and frozen.
5. Strict / non-strict contract build diagnostics.
6. Accept path (every guard satisfied).
7. Deny-list rejection.
8. Allow-list miss (unknown target or axis-target pair).
9. Min / max value bound rejection.
10. Max delta rejection.
11. Residual support gate (accept and reject).
12. DPL axis-loss gate (accept and reject).
13. Status axis acceptance and rejection.
14. Deterministic ordering of decisions and reasons.
15. Strict vs non-strict proposal diagnostics.
16. Builder / evaluator do not mutate inputs.
17. No live adapter / write / control / setpoint substrings in module.
18. Docs / report contain safety-boundary and API evidence.
"""

from __future__ import annotations

import copy
import dataclasses
import math
from pathlib import Path

import pytest

from aquaoptima.dphm import (
    ADVISORY_AXES,
    ADVISORY_AXIS_EDGE_FLOW,
    ADVISORY_AXIS_EDGE_VELOCITY,
    ADVISORY_AXIS_NODE_PRESSURE,
    ADVISORY_AXIS_PUMP_SPEED,
    ADVISORY_AXIS_RESERVOIR_HEAD,
    ADVISORY_AXIS_STATUS,
    ADVISORY_AXIS_TANK_LEVEL,
    ADVISORY_AXIS_VALVE_POSITION,
    ADVISORY_STATUSES,
    ADVISORY_STATUS_ACCEPTED,
    ADVISORY_STATUS_REJECTED,
    AdvisoryContract,
    AdvisoryContractDiagnostics,
    AdvisoryDecision,
    AdvisoryProposal,
    AdvisoryRule,
    DPLCalibrationDiagnostics,
    DPLCalibrationLossReport,
    DPLResidual,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_EDGE_VALVE_POSITION,
    TELEMETRY_AXIS_NODE_LEVEL,
    TELEMETRY_AXIS_NODE_PRESSURE,
    build_advisory_contract,
    evaluate_advisory_proposals,
)
import aquaoptima.dphm as dphm
import aquaoptima.dphm.advisory_contract as advisory_contract_module


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pump_proposal(
    *,
    proposal_id: str = "P1",
    target_id: int = 0,
    proposed_value: float = 0.75,
    current_value: float | None = 0.80,
    observed_value: float | None = None,
) -> AdvisoryProposal:
    return AdvisoryProposal(
        proposal_id=proposal_id,
        axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=target_id,
        proposed_value=proposed_value,
        current_value=current_value,
        observed_value=observed_value,
    )


def _loss_report_with_pump_residuals(
    *, target_id: int = 0, count: int = 3, mse: float = 0.01
) -> DPLCalibrationLossReport:
    # Construct a hand-built loss report. The internals are inert
    # (Sprint 36 builder is not invoked) — the evaluator only reads
    # ``residuals``, ``mse_by_axis``.
    residuals = tuple(
        DPLResidual(
            frame_index=i,
            timestamp=float(i),
            axis=TELEMETRY_AXIS_EDGE_PUMP_SPEED,
            target_id=target_id,
            observed=0.80,
            predicted=0.80,
            residual=0.0,
            weight=1.0,
        )
        for i in range(count)
    )
    return DPLCalibrationLossReport(
        residuals=residuals,
        mse_by_axis={TELEMETRY_AXIS_EDGE_PUMP_SPEED: mse},
        mae_by_axis={TELEMETRY_AXIS_EDGE_PUMP_SPEED: math.sqrt(mse)},
        weighted_mse=mse,
        observation_count=count,
        diagnostics=DPLCalibrationDiagnostics(),
    )


# ---------------------------------------------------------------------------
# 1. Public exports
# ---------------------------------------------------------------------------


def test_advisory_contract_public_exports() -> None:
    expected_names = (
        "ADVISORY_AXES",
        "ADVISORY_AXIS_EDGE_FLOW",
        "ADVISORY_AXIS_EDGE_VELOCITY",
        "ADVISORY_AXIS_NODE_PRESSURE",
        "ADVISORY_AXIS_PUMP_SPEED",
        "ADVISORY_AXIS_RESERVOIR_HEAD",
        "ADVISORY_AXIS_STATUS",
        "ADVISORY_AXIS_TANK_LEVEL",
        "ADVISORY_AXIS_VALVE_POSITION",
        "ADVISORY_STATUSES",
        "ADVISORY_STATUS_ACCEPTED",
        "ADVISORY_STATUS_REJECTED",
        "AdvisoryContract",
        "AdvisoryContractDiagnostics",
        "AdvisoryDecision",
        "AdvisoryProposal",
        "AdvisoryRule",
        "build_advisory_contract",
        "evaluate_advisory_proposals",
    )
    for name in expected_names:
        assert hasattr(dphm, name), f"aquaoptima.dphm missing {name}"
        assert name in dphm.__all__, f"aquaoptima.dphm.__all__ missing {name}"
        assert name in advisory_contract_module.__all__, (
            f"advisory_contract module __all__ missing {name}"
        )


def test_advisory_axis_constants_are_complete() -> None:
    assert set(ADVISORY_AXES) == {
        ADVISORY_AXIS_PUMP_SPEED,
        ADVISORY_AXIS_VALVE_POSITION,
        ADVISORY_AXIS_RESERVOIR_HEAD,
        ADVISORY_AXIS_TANK_LEVEL,
        ADVISORY_AXIS_NODE_PRESSURE,
        ADVISORY_AXIS_EDGE_FLOW,
        ADVISORY_AXIS_EDGE_VELOCITY,
        ADVISORY_AXIS_STATUS,
    }
    assert ADVISORY_STATUSES == (
        ADVISORY_STATUS_ACCEPTED,
        ADVISORY_STATUS_REJECTED,
    )


# ---------------------------------------------------------------------------
# 2. Frozen dataclasses
# ---------------------------------------------------------------------------


def test_advisory_dataclasses_are_frozen() -> None:
    contract = build_advisory_contract(
        allow_rules=[
            AdvisoryRule(
                axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, min_value=0.0,
                max_value=1.0,
            )
        ]
    )
    proposal = _pump_proposal()
    decisions = evaluate_advisory_proposals(contract, [proposal])
    decision = decisions[0]
    rule = contract.allow_rules[0]
    diagnostics = contract.diagnostics

    for instance in (contract, proposal, decision, rule, diagnostics):
        cls = type(instance)
        assert dataclasses.is_dataclass(cls)
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen is True, f"{cls.__name__} must be frozen"

    with pytest.raises(dataclasses.FrozenInstanceError):
        contract.name = "x"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        proposal.proposed_value = 0.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.accepted = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.target_id = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        diagnostics.warnings = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. Default-constructed dataclasses
# ---------------------------------------------------------------------------


def test_default_advisory_dataclasses_are_constructible() -> None:
    diagnostics = AdvisoryContractDiagnostics()
    assert diagnostics.warnings == ()
    assert diagnostics.errors == ()

    contract = AdvisoryContract()
    assert contract.name == ""
    assert contract.allow_rules == ()
    assert contract.deny_rules == ()
    assert contract.diagnostics == AdvisoryContractDiagnostics()


# ---------------------------------------------------------------------------
# 4. Build path
# ---------------------------------------------------------------------------


def test_build_advisory_contract_canonicalises_inputs() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=2,
        min_value=0.1, max_value=0.95,
        max_abs_delta=0.10,
        note="primary pump speed envelope",
    )
    deny = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=9,
        note="reserve pump 9 — never propose",
    )
    contract = build_advisory_contract(
        name="primary", allow_rules=[rule], deny_rules=[deny]
    )
    assert contract.name == "primary"
    assert contract.allow_rules == (rule,)
    assert contract.deny_rules == (deny,)
    assert contract.diagnostics.errors == ()
    assert contract.diagnostics.warnings == ()


def test_build_advisory_contract_empty_default() -> None:
    contract = build_advisory_contract()
    assert contract.name == ""
    assert contract.allow_rules == ()
    assert contract.deny_rules == ()
    assert contract.diagnostics == AdvisoryContractDiagnostics()


# ---------------------------------------------------------------------------
# 5. Build diagnostics — strict / non-strict
# ---------------------------------------------------------------------------


def test_unknown_axis_in_rule_strict_raises() -> None:
    bad = AdvisoryRule(axis="nope", target_id=0)
    with pytest.raises(ValueError, match="not a recognised advisory axis"):
        build_advisory_contract(allow_rules=[bad])


def test_unknown_axis_in_rule_non_strict_records_error() -> None:
    good = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=1)
    bad = AdvisoryRule(axis="nope", target_id=0)
    contract = build_advisory_contract(
        allow_rules=[good, bad], strict=False
    )
    assert contract.allow_rules == (good,)
    assert any("not a recognised" in e for e in contract.diagnostics.errors)


def test_negative_target_id_strict_raises() -> None:
    bad = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=-1)
    with pytest.raises(ValueError, match=">= 0"):
        build_advisory_contract(allow_rules=[bad])


def test_non_finite_bound_strict_raises() -> None:
    bad = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=math.nan,
    )
    with pytest.raises(ValueError, match="finite"):
        build_advisory_contract(allow_rules=[bad])


def test_min_greater_than_max_strict_raises() -> None:
    bad = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.9, max_value=0.1,
    )
    with pytest.raises(ValueError, match="greater than max_value"):
        build_advisory_contract(allow_rules=[bad])


def test_negative_max_abs_delta_strict_raises() -> None:
    bad = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_abs_delta=-0.1
    )
    with pytest.raises(ValueError, match="max_abs_delta"):
        build_advisory_contract(allow_rules=[bad])


def test_negative_min_residual_support_strict_raises() -> None:
    bad = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, min_residual_support=-1
    )
    with pytest.raises(ValueError, match="min_residual_support"):
        build_advisory_contract(allow_rules=[bad])


def test_bool_min_residual_support_rejected() -> None:
    bad = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_residual_support=True,  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="min_residual_support"):
        build_advisory_contract(allow_rules=[bad])


def test_residual_guard_on_axis_without_dpl_mapping_rejected() -> None:
    bad = AdvisoryRule(
        axis=ADVISORY_AXIS_EDGE_VELOCITY, target_id=0,
        min_residual_support=1,
    )
    with pytest.raises(ValueError, match="no DPL axis mapping"):
        build_advisory_contract(allow_rules=[bad])


def test_axis_loss_guard_on_axis_without_dpl_mapping_rejected() -> None:
    bad = AdvisoryRule(
        axis=ADVISORY_AXIS_STATUS, target_id=0, max_axis_loss=0.1
    )
    with pytest.raises(ValueError, match="no DPL axis mapping"):
        build_advisory_contract(allow_rules=[bad])


def test_duplicate_allow_rule_records_warning() -> None:
    r1 = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, min_value=0.1,
    )
    r2 = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_value=0.95,
    )
    contract = build_advisory_contract(allow_rules=[r1, r2])
    assert contract.allow_rules == (r1, r2)
    assert any("duplicate" in w for w in contract.diagnostics.warnings)


def test_allow_and_deny_overlap_records_warning() -> None:
    a = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)
    d = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)
    contract = build_advisory_contract(allow_rules=[a], deny_rules=[d])
    assert any(
        "deny-list takes precedence" in w
        for w in contract.diagnostics.warnings
    )


def test_allow_rules_not_a_sequence_rejected() -> None:
    with pytest.raises(ValueError, match="Sequence"):
        build_advisory_contract(allow_rules=(r for r in ()))  # type: ignore[arg-type]


def test_allow_rules_string_rejected() -> None:
    with pytest.raises(ValueError, match="not a string"):
        build_advisory_contract(allow_rules="not a list")  # type: ignore[arg-type]


def test_rule_not_an_advisory_rule_rejected() -> None:
    with pytest.raises(ValueError, match="expected AdvisoryRule"):
        build_advisory_contract(allow_rules=[object()])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# 6. Accept path
# ---------------------------------------------------------------------------


def test_accept_path_with_basic_min_max() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.1, max_value=0.95,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal(proposed_value=0.75, current_value=0.80)
    decisions = evaluate_advisory_proposals(contract, [proposal])
    assert len(decisions) == 1
    d = decisions[0]
    assert d.accepted is True
    assert d.status == ADVISORY_STATUS_ACCEPTED
    assert d.reasons == ()
    assert d.violated_rules == ()
    assert d.proposal is proposal


def test_accept_path_no_guards_no_reference() -> None:
    rule = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=3)
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = AdvisoryProposal(
        proposal_id="P", axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=3, proposed_value=0.50,
    )
    decisions = evaluate_advisory_proposals(contract, [proposal])
    assert decisions[0].accepted is True


# ---------------------------------------------------------------------------
# 7. Deny-list rejection
# ---------------------------------------------------------------------------


def test_deny_list_rejection_is_unconditional() -> None:
    deny = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=9)
    contract = build_advisory_contract(deny_rules=[deny])
    proposal = _pump_proposal(target_id=9, proposed_value=0.5)
    decisions = evaluate_advisory_proposals(contract, [proposal])
    d = decisions[0]
    assert d.accepted is False
    assert d.status == ADVISORY_STATUS_REJECTED
    assert any("deny_rules[0]" in r for r in d.reasons)
    assert "deny_rules[0]" in d.violated_rules


def test_deny_list_rejection_wins_over_allow() -> None:
    allow = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=9,
        min_value=0.0, max_value=1.0,
    )
    deny = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=9)
    contract = build_advisory_contract(
        allow_rules=[allow], deny_rules=[deny]
    )
    proposal = _pump_proposal(target_id=9, proposed_value=0.5)
    decisions = evaluate_advisory_proposals(contract, [proposal])
    assert decisions[0].accepted is False
    assert any("deny_rules" in v for v in decisions[0].violated_rules)


# ---------------------------------------------------------------------------
# 8. Allow-list miss
# ---------------------------------------------------------------------------


def test_no_matching_allow_rule_rejects() -> None:
    rule = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal(target_id=7)
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    assert any("no allow_rules entry matches" in r for r in d.reasons)
    assert "allow_rules:miss" in d.violated_rules


def test_axis_mismatch_rejects() -> None:
    rule = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = AdvisoryProposal(
        proposal_id="P", axis=ADVISORY_AXIS_VALVE_POSITION,
        target_id=0, proposed_value=0.5,
    )
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    assert "allow_rules:miss" in d.violated_rules


# ---------------------------------------------------------------------------
# 9. Min / max value rejection
# ---------------------------------------------------------------------------


def test_min_value_rejection() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, min_value=0.5
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal(proposed_value=0.30, current_value=0.40)
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    assert any("below" in r and "min_value" in r for r in d.reasons)
    assert "allow_rules[0]:min_value" in d.violated_rules


def test_max_value_rejection() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_value=0.95
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal(proposed_value=1.10, current_value=1.0)
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    assert any("above" in r and "max_value" in r for r in d.reasons)
    assert "allow_rules[0]:max_value" in d.violated_rules


def test_inclusive_bounds_accept_edges() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.10, max_value=0.95,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    # exactly min
    p1 = _pump_proposal(proposed_value=0.10, current_value=0.10)
    # exactly max
    p2 = _pump_proposal(
        proposal_id="P2", proposed_value=0.95, current_value=0.95
    )
    decisions = evaluate_advisory_proposals(contract, [p1, p2])
    assert decisions[0].accepted is True
    assert decisions[1].accepted is True


# ---------------------------------------------------------------------------
# 10. Max delta rejection
# ---------------------------------------------------------------------------


def test_max_abs_delta_rejection_against_current_value() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_abs_delta=0.10
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal(proposed_value=0.50, current_value=0.80)
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    assert any("max_abs_delta" in r for r in d.reasons)
    assert "allow_rules[0]:max_abs_delta" in d.violated_rules


def test_max_abs_delta_falls_back_to_observed_value() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_abs_delta=0.10
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = AdvisoryProposal(
        proposal_id="P", axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        proposed_value=0.50, observed_value=0.80,
    )
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    assert any("max_abs_delta" in r for r in d.reasons)


def test_max_abs_delta_without_reference_emits_warning() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_abs_delta=0.10
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = AdvisoryProposal(
        proposal_id="P", axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        proposed_value=0.50,
    )
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    # No reference value → guard is skipped, accept the proposal.
    assert d.accepted is True
    assert any(
        "max_abs_delta" in w and "skipped" in w for w in d.diagnostics.warnings
    )


def test_max_abs_delta_accepts_inside_envelope() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_abs_delta=0.10
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal(proposed_value=0.75, current_value=0.80)
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is True


# ---------------------------------------------------------------------------
# 11. Residual support gate
# ---------------------------------------------------------------------------


def test_min_residual_support_accept() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, min_residual_support=2,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    report = _loss_report_with_pump_residuals(target_id=0, count=3)
    proposal = _pump_proposal(proposed_value=0.75, current_value=0.80)
    d = evaluate_advisory_proposals(
        contract, [proposal], loss_report=report
    )[0]
    assert d.accepted is True


def test_min_residual_support_reject_due_to_low_count() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, min_residual_support=5,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    report = _loss_report_with_pump_residuals(target_id=0, count=3)
    proposal = _pump_proposal(proposed_value=0.75, current_value=0.80)
    d = evaluate_advisory_proposals(
        contract, [proposal], loss_report=report
    )[0]
    assert d.accepted is False
    assert any(
        "min_residual_support" in r and "residual support 3" in r
        for r in d.reasons
    )


def test_min_residual_support_requires_report() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, min_residual_support=1,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal(proposed_value=0.75, current_value=0.80)
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    assert any(
        "requires a DPLCalibrationLossReport" in r for r in d.reasons
    )


def test_min_residual_support_counts_only_matching_target() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, min_residual_support=2,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    # Three residuals on target 7, none on target 0.
    report = _loss_report_with_pump_residuals(target_id=7, count=3)
    proposal = _pump_proposal(target_id=0, proposed_value=0.75, current_value=0.80)
    d = evaluate_advisory_proposals(
        contract, [proposal], loss_report=report
    )[0]
    assert d.accepted is False
    assert any("residual support 0" in r for r in d.reasons)


# ---------------------------------------------------------------------------
# 12. Axis-loss gate
# ---------------------------------------------------------------------------


def test_max_axis_loss_accept() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_axis_loss=0.10,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    report = _loss_report_with_pump_residuals(mse=0.01)
    proposal = _pump_proposal(proposed_value=0.75, current_value=0.80)
    d = evaluate_advisory_proposals(
        contract, [proposal], loss_report=report
    )[0]
    assert d.accepted is True


def test_max_axis_loss_reject() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_axis_loss=0.001,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    report = _loss_report_with_pump_residuals(mse=0.01)
    proposal = _pump_proposal(proposed_value=0.75, current_value=0.80)
    d = evaluate_advisory_proposals(
        contract, [proposal], loss_report=report
    )[0]
    assert d.accepted is False
    assert any("max_axis_loss" in r for r in d.reasons)


def test_max_axis_loss_requires_report() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_axis_loss=0.10,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal(proposed_value=0.75, current_value=0.80)
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    assert any(
        "requires a DPLCalibrationLossReport" in r for r in d.reasons
    )


# ---------------------------------------------------------------------------
# 13. Status axis
# ---------------------------------------------------------------------------


def test_status_axis_bool_acceptance() -> None:
    rule = AdvisoryRule(axis=ADVISORY_AXIS_STATUS, target_id=0)
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = AdvisoryProposal(
        proposal_id="STAT1", axis=ADVISORY_AXIS_STATUS, target_id=0,
        proposed_value=True,
    )
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is True


def test_status_axis_numeric_outside_01_rejected_strict() -> None:
    rule = AdvisoryRule(axis=ADVISORY_AXIS_STATUS, target_id=0)
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = AdvisoryProposal(
        proposal_id="STAT", axis=ADVISORY_AXIS_STATUS, target_id=0,
        proposed_value=0.5,
    )
    with pytest.raises(ValueError, match="not coercible"):
        evaluate_advisory_proposals(contract, [proposal])


def test_status_axis_numeric_outside_01_non_strict_rejected_decision() -> None:
    rule = AdvisoryRule(axis=ADVISORY_AXIS_STATUS, target_id=0)
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = AdvisoryProposal(
        proposal_id="STAT", axis=ADVISORY_AXIS_STATUS, target_id=0,
        proposed_value=0.5,
    )
    d = evaluate_advisory_proposals(contract, [proposal], strict=False)[0]
    assert d.accepted is False
    assert "malformed_proposal" in d.violated_rules
    assert any("not coercible" in e for e in d.diagnostics.errors)


# ---------------------------------------------------------------------------
# 14. Deterministic ordering
# ---------------------------------------------------------------------------


def test_decisions_preserve_proposal_input_order() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.0, max_value=1.0,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposals = [
        _pump_proposal(proposal_id="P3", proposed_value=0.30, current_value=0.40),
        _pump_proposal(proposal_id="P1", proposed_value=0.50, current_value=0.55),
        _pump_proposal(proposal_id="P2", proposed_value=0.70, current_value=0.75),
    ]
    decisions = evaluate_advisory_proposals(contract, proposals)
    assert [d.proposal.proposal_id for d in decisions] == ["P3", "P1", "P2"]


def test_reasons_aggregate_all_violations_deterministically() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.5, max_value=0.6,
        max_abs_delta=0.05,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    # proposed=0.10, current=0.80 → below min AND delta exceeds.
    proposal = _pump_proposal(proposed_value=0.10, current_value=0.80)
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    # Both violations should be present.
    descriptors = list(d.violated_rules)
    assert "allow_rules[0]:min_value" in descriptors
    assert "allow_rules[0]:max_abs_delta" in descriptors
    # Order is deterministic (min_value before max_abs_delta).
    assert descriptors.index("allow_rules[0]:min_value") < descriptors.index(
        "allow_rules[0]:max_abs_delta"
    )


def test_repeat_evaluation_is_deterministic() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.0, max_value=1.0,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal()
    a = evaluate_advisory_proposals(contract, [proposal])
    b = evaluate_advisory_proposals(contract, [proposal])
    assert a == b


# ---------------------------------------------------------------------------
# 15. Strict vs non-strict proposal diagnostics
# ---------------------------------------------------------------------------


def test_malformed_proposal_strict_raises() -> None:
    contract = build_advisory_contract(
        allow_rules=[AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)]
    )
    bad = AdvisoryProposal(
        proposal_id="", axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=0, proposed_value=0.5,
    )
    with pytest.raises(ValueError, match="proposal_id"):
        evaluate_advisory_proposals(contract, [bad])


def test_malformed_proposal_non_strict_records_rejected_decision() -> None:
    contract = build_advisory_contract(
        allow_rules=[AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)]
    )
    bad = AdvisoryProposal(
        proposal_id="", axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=0, proposed_value=0.5,
    )
    decisions = evaluate_advisory_proposals(contract, [bad], strict=False)
    assert decisions[0].accepted is False
    assert decisions[0].status == ADVISORY_STATUS_REJECTED
    assert "malformed_proposal" in decisions[0].violated_rules
    assert any("proposal_id" in e for e in decisions[0].diagnostics.errors)


def test_non_advisory_proposal_object_strict_raises() -> None:
    contract = build_advisory_contract()
    with pytest.raises(ValueError, match="expected AdvisoryProposal"):
        evaluate_advisory_proposals(contract, [object()])  # type: ignore[list-item]


def test_proposed_value_non_finite_strict_raises() -> None:
    contract = build_advisory_contract(
        allow_rules=[AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)]
    )
    bad = AdvisoryProposal(
        proposal_id="P", axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=0, proposed_value=math.nan,
    )
    with pytest.raises(ValueError, match="not coercible"):
        evaluate_advisory_proposals(contract, [bad])


def test_proposed_value_bool_rejected_on_numeric_axis() -> None:
    contract = build_advisory_contract(
        allow_rules=[AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)]
    )
    bad = AdvisoryProposal(
        proposal_id="P", axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=0, proposed_value=True,  # bool on numeric axis
    )
    with pytest.raises(ValueError, match="not coercible"):
        evaluate_advisory_proposals(contract, [bad])


def test_proposals_string_rejected() -> None:
    contract = build_advisory_contract()
    with pytest.raises(ValueError, match="not a string"):
        evaluate_advisory_proposals(contract, "")  # type: ignore[arg-type]


def test_proposals_generator_rejected() -> None:
    contract = build_advisory_contract()
    def gen():
        yield _pump_proposal()
    with pytest.raises(ValueError, match="Sequence"):
        evaluate_advisory_proposals(contract, gen())  # type: ignore[arg-type]


def test_contract_argument_type_rejected() -> None:
    with pytest.raises(ValueError, match="AdvisoryContract"):
        evaluate_advisory_proposals(object(), [])  # type: ignore[arg-type]


def test_loss_report_argument_type_rejected() -> None:
    contract = build_advisory_contract()
    with pytest.raises(ValueError, match="DPLCalibrationLossReport"):
        evaluate_advisory_proposals(
            contract, [], loss_report=object(),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# 16. Builder / evaluator do not mutate inputs
# ---------------------------------------------------------------------------


def test_builder_and_evaluator_do_not_mutate_inputs() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.0, max_value=1.0,
    )
    deny = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=9)
    allow_rules = [rule]
    deny_rules = [deny]
    allow_snapshot = copy.deepcopy(allow_rules)
    deny_snapshot = copy.deepcopy(deny_rules)

    contract = build_advisory_contract(
        allow_rules=allow_rules, deny_rules=deny_rules
    )
    assert allow_rules == allow_snapshot
    assert deny_rules == deny_snapshot

    proposal = _pump_proposal()
    proposals = [proposal]
    proposals_snapshot = copy.deepcopy(proposals)
    report = _loss_report_with_pump_residuals()
    report_snapshot = copy.deepcopy(report)

    evaluate_advisory_proposals(contract, proposals, loss_report=report)
    assert proposals == proposals_snapshot
    assert report == report_snapshot


# ---------------------------------------------------------------------------
# 17. No live-adapter / write / control surface
# ---------------------------------------------------------------------------


def test_advisory_contract_module_exports_no_live_surface() -> None:
    forbidden_substrings = (
        "write",
        "control",
        "setpoint",
        "actuate",
        "publish",
        "subscribe",
        "ingest",
        "poll",
        "scada",
        "plc",
        "historian",
        "opcua",
        "mqtt",
        "rest_client",
        "http_client",
        "open_socket",
        "open_connection",
        "train",
        "optim",
    )
    for name in advisory_contract_module.__all__:
        lname = name.lower()
        for needle in forbidden_substrings:
            assert needle not in lname, (
                f"advisory_contract exposes symbol {name!r} containing "
                f"forbidden substring {needle!r}"
            )

    for forbidden in ("socket", "asyncio", "ssl", "urllib", "smtplib"):
        assert not hasattr(advisory_contract_module, forbidden), (
            f"advisory_contract unexpectedly references {forbidden!r}"
        )


def test_advisory_contract_module_source_has_safety_phrases() -> None:
    source = Path(advisory_contract_module.__file__).read_text(encoding="utf-8")
    for phrase in (
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "advisory proposal audit only",
    ):
        assert phrase in source, (
            f"advisory_contract source must contain {phrase!r} safety phrase"
        )


def test_advisory_contract_module_no_live_adapter_substrings_in_source() -> None:
    source = Path(advisory_contract_module.__file__).read_text(encoding="utf-8")
    # These substrings must not name a live adapter / write surface.
    # The safety boundary docstring intentionally lists the forbidden
    # adapter names in the context of disclaiming them, so we look for
    # *callable* live patterns the module would invoke.
    forbidden_callables = (
        "socket.socket(",
        "subprocess.Popen(",
        "urllib.request.urlopen(",
        "smtplib.SMTP(",
        "asyncio.run(",
        "open_connection(",
        "publish(",
        "subscribe(",
    )
    for needle in forbidden_callables:
        assert needle not in source, (
            f"advisory_contract source contains forbidden call {needle!r}"
        )


# ---------------------------------------------------------------------------
# 18. Docs / report evidence
# ---------------------------------------------------------------------------


def test_docs_advisory_contract_has_safety_boundary_and_api() -> None:
    doc = (REPO_ROOT / "docs" / "advisory-contract.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "advisory proposal audit only",
    ):
        assert phrase in doc, f"docs/advisory-contract.md missing {phrase!r}"
    for name in (
        "AdvisoryContract",
        "AdvisoryContractDiagnostics",
        "AdvisoryDecision",
        "AdvisoryProposal",
        "AdvisoryRule",
        "build_advisory_contract",
        "evaluate_advisory_proposals",
    ):
        assert name in doc, f"docs/advisory-contract.md missing API name {name!r}"


def test_sprint37_report_has_safety_boundary_and_api() -> None:
    report = (REPO_ROOT / "SPRINT37_REPORT.md").read_text(encoding="utf-8")
    for phrase in (
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "advisory proposal audit only",
    ):
        assert phrase in report, f"SPRINT37_REPORT.md missing {phrase!r}"
    for name in (
        "AdvisoryContract",
        "AdvisoryProposal",
        "AdvisoryDecision",
        "AdvisoryContractDiagnostics",
        "build_advisory_contract",
        "evaluate_advisory_proposals",
    ):
        assert name in report, f"SPRINT37_REPORT.md missing API name {name!r}"


# ---------------------------------------------------------------------------
# Extra: combined integration with Sprint 36 loss report
# ---------------------------------------------------------------------------


def test_combined_residual_and_axis_loss_accept() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.1, max_value=0.95,
        max_abs_delta=0.20,
        min_residual_support=2,
        max_axis_loss=0.10,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    report = _loss_report_with_pump_residuals(target_id=0, count=3, mse=0.05)
    proposal = _pump_proposal(proposed_value=0.70, current_value=0.80)
    d = evaluate_advisory_proposals(
        contract, [proposal], loss_report=report
    )[0]
    assert d.accepted is True


def test_combined_guards_collect_all_violations() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.5, max_value=0.6,
        max_abs_delta=0.05,
        min_residual_support=10,
        max_axis_loss=0.001,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    report = _loss_report_with_pump_residuals(target_id=0, count=2, mse=0.10)
    proposal = _pump_proposal(proposed_value=0.10, current_value=0.80)
    d = evaluate_advisory_proposals(
        contract, [proposal], loss_report=report
    )[0]
    assert d.accepted is False
    descriptors = set(d.violated_rules)
    assert "allow_rules[0]:min_value" in descriptors
    assert "allow_rules[0]:max_abs_delta" in descriptors
    assert "allow_rules[0]:min_residual_support" in descriptors
    assert "allow_rules[0]:max_axis_loss" in descriptors


def test_multiple_allow_rules_all_must_pass() -> None:
    r1 = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0,
        min_value=0.1, max_value=0.95,
    )
    r2 = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_abs_delta=0.10,
    )
    contract = build_advisory_contract(allow_rules=[r1, r2])
    # First rule passes (0.50 ∈ [0.1, 0.95]); second fails (|0.50-0.80| > 0.10).
    proposal = _pump_proposal(proposed_value=0.50, current_value=0.80)
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.accepted is False
    assert any("max_abs_delta" in r for r in d.reasons)


def test_loss_report_with_zero_axis_mse_accepts_strict_axis_loss() -> None:
    rule = AdvisoryRule(
        axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0, max_axis_loss=0.0,
    )
    contract = build_advisory_contract(allow_rules=[rule])
    report = _loss_report_with_pump_residuals(mse=0.0)
    proposal = _pump_proposal(proposed_value=0.75, current_value=0.80)
    d = evaluate_advisory_proposals(
        contract, [proposal], loss_report=report
    )[0]
    assert d.accepted is True


def test_decision_proposal_is_passed_through_identity() -> None:
    rule = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)
    contract = build_advisory_contract(allow_rules=[rule])
    proposal = _pump_proposal()
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.proposal is proposal


def test_empty_evaluation_returns_empty_tuple() -> None:
    contract = build_advisory_contract()
    decisions = evaluate_advisory_proposals(contract, [])
    assert decisions == ()


def test_metadata_passthrough_is_preserved() -> None:
    rule = AdvisoryRule(axis=ADVISORY_AXIS_PUMP_SPEED, target_id=0)
    contract = build_advisory_contract(allow_rules=[rule])
    metadata = {"source_version": "v0", "confidence": 0.9}
    proposal = AdvisoryProposal(
        proposal_id="P",
        axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=0,
        proposed_value=0.50,
        metadata=metadata,
    )
    d = evaluate_advisory_proposals(contract, [proposal])[0]
    assert d.proposal.metadata == metadata


def test_reservoir_head_and_tank_level_axes_can_route_to_dpl() -> None:
    # reservoir_head → DPL node_pressure axis
    rule_res = AdvisoryRule(
        axis=ADVISORY_AXIS_RESERVOIR_HEAD, target_id=2,
        min_residual_support=1,
    )
    rule_tank = AdvisoryRule(
        axis=ADVISORY_AXIS_TANK_LEVEL, target_id=3,
        min_residual_support=1,
    )
    contract = build_advisory_contract(allow_rules=[rule_res, rule_tank])
    report = DPLCalibrationLossReport(
        residuals=(
            DPLResidual(
                frame_index=0, timestamp=0.0,
                axis=TELEMETRY_AXIS_NODE_PRESSURE, target_id=2,
                observed=10.0, predicted=10.1, residual=0.1, weight=1.0,
            ),
            DPLResidual(
                frame_index=0, timestamp=0.0,
                axis=TELEMETRY_AXIS_NODE_LEVEL, target_id=3,
                observed=5.0, predicted=5.1, residual=0.1, weight=1.0,
            ),
        ),
        mse_by_axis={
            TELEMETRY_AXIS_NODE_PRESSURE: 0.01,
            TELEMETRY_AXIS_NODE_LEVEL: 0.01,
        },
        mae_by_axis={
            TELEMETRY_AXIS_NODE_PRESSURE: 0.1,
            TELEMETRY_AXIS_NODE_LEVEL: 0.1,
        },
        weighted_mse=0.01,
        observation_count=2,
        diagnostics=DPLCalibrationDiagnostics(),
    )
    proposals = [
        AdvisoryProposal(
            proposal_id="R", axis=ADVISORY_AXIS_RESERVOIR_HEAD,
            target_id=2, proposed_value=12.0, current_value=10.0,
        ),
        AdvisoryProposal(
            proposal_id="T", axis=ADVISORY_AXIS_TANK_LEVEL,
            target_id=3, proposed_value=6.0, current_value=5.0,
        ),
    ]
    decisions = evaluate_advisory_proposals(
        contract, proposals, loss_report=report
    )
    assert all(d.accepted for d in decisions)
