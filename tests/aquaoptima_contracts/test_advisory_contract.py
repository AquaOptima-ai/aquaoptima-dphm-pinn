"""TDD — advisory SDK projections (Sprint 43).

Acceptance: the SDK ``AdvisoryRule`` / ``AdvisoryContract`` /
``AdvisoryProposal`` / ``AdvisoryDecision`` / ``AdvisoryEvaluation``
/ ``AdvisoryRejectionReason`` types capture the *audit-only* shape
of the Phase 1 Sprint 37 advisory surface. The SDK projection
intentionally cannot represent a write or actuation payload.

Boundary: the SDK advisory module is audit-only. It never imports
``aquaoptima.*`` from inside SDK package code, never invokes the
Phase 1 ``evaluate_advisory_proposals`` runtime evaluator, and
never produces a setpoint, command, or control output.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    AdvisoryContract,
    AdvisoryDecision,
    AdvisoryEvaluation,
    AdvisoryProposal,
    AdvisoryRejectionReason,
    AdvisoryRule,
    ContractError,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.advisory import (
    ADVISORY_DECISION_STATUSES,
    ADVISORY_REJECTION_REASONS,
    ADVISORY_SDK_AXES,
    project_phase1_advisory_decisions,
)


def test_advisory_rule_round_trip() -> None:
    rule = AdvisoryRule(
        rule_id="r0",
        axis="pump_speed",
        target_id=0,
        mode="allow",
        min_value=0.5,
        max_value=1.0,
        note="audit only",
    )
    decoded = load_canonical_json(dump_canonical_json(rule))
    assert decoded["axis"] == "pump_speed"
    restored = AdvisoryRule.from_dict(decoded)
    assert restored == rule


def test_advisory_rule_rejects_unknown_axis() -> None:
    with pytest.raises(ContractError):
        AdvisoryRule(
            rule_id="r0",
            axis="not_a_real_axis",
            target_id=0,
            mode="allow",
        )


def test_advisory_rule_rejects_negative_target_id() -> None:
    with pytest.raises(ContractError):
        AdvisoryRule(
            rule_id="r0",
            axis="pump_speed",
            target_id=-1,
            mode="allow",
        )


def test_advisory_rule_rejects_unknown_mode() -> None:
    with pytest.raises(ContractError):
        AdvisoryRule(
            rule_id="r0",
            axis="pump_speed",
            target_id=0,
            mode="execute",
        )


def test_advisory_rule_rejects_inverted_bounds() -> None:
    with pytest.raises(ContractError):
        AdvisoryRule(
            rule_id="r0",
            axis="pump_speed",
            target_id=0,
            mode="allow",
            min_value=1.0,
            max_value=0.5,
        )


def test_advisory_rule_rejects_non_finite_bound() -> None:
    with pytest.raises(ContractError):
        AdvisoryRule(
            rule_id="r0",
            axis="pump_speed",
            target_id=0,
            mode="allow",
            min_value=float("nan"),
        )


def test_advisory_contract_round_trip() -> None:
    contract = AdvisoryContract(
        name="ctr",
        allow_rules=(
            AdvisoryRule(
                rule_id="r0",
                axis="pump_speed",
                target_id=0,
                mode="allow",
                min_value=0.0,
                max_value=1.0,
            ),
        ),
        deny_rules=(
            AdvisoryRule(
                rule_id="r1",
                axis="valve_position",
                target_id=2,
                mode="deny",
            ),
        ),
    )
    decoded = load_canonical_json(dump_canonical_json(contract))
    restored = AdvisoryContract.from_dict(decoded)
    assert restored == contract


def test_advisory_contract_rejects_allow_rule_with_deny_mode() -> None:
    with pytest.raises(ContractError):
        AdvisoryContract(
            allow_rules=(
                AdvisoryRule(
                    rule_id="r0",
                    axis="pump_speed",
                    target_id=0,
                    mode="deny",
                ),
            ),
        )


def test_advisory_contract_rejects_deny_rule_with_allow_mode() -> None:
    with pytest.raises(ContractError):
        AdvisoryContract(
            deny_rules=(
                AdvisoryRule(
                    rule_id="r0",
                    axis="pump_speed",
                    target_id=0,
                    mode="allow",
                ),
            ),
        )


def test_advisory_proposal_round_trip() -> None:
    proposal = AdvisoryProposal(
        proposal_id="p0",
        axis="pump_speed",
        target_id=0,
        proposed_value=0.7,
        current_value=0.6,
        reason="raise speed to meet pressure target",
        source="dpl_model_v1",
    )
    decoded = load_canonical_json(dump_canonical_json(proposal))
    restored = AdvisoryProposal.from_dict(decoded)
    assert restored == proposal


def test_advisory_proposal_rejects_empty_id() -> None:
    with pytest.raises(ContractError):
        AdvisoryProposal(
            proposal_id="",
            axis="pump_speed",
            target_id=0,
            proposed_value=0.7,
        )


def test_advisory_proposal_rejects_unknown_axis() -> None:
    with pytest.raises(ContractError):
        AdvisoryProposal(
            proposal_id="p0",
            axis="not_a_real_axis",
            target_id=0,
            proposed_value=0.7,
        )


def test_advisory_proposal_rejects_non_finite_value() -> None:
    with pytest.raises(ContractError):
        AdvisoryProposal(
            proposal_id="p0",
            axis="pump_speed",
            target_id=0,
            proposed_value=float("inf"),
        )


def test_advisory_proposal_to_dict_carries_no_actuation_field() -> None:
    proposal = AdvisoryProposal(
        proposal_id="p0",
        axis="pump_speed",
        target_id=0,
        proposed_value=0.7,
    )
    decoded = load_canonical_json(dump_canonical_json(proposal))
    for key in decoded:
        assert "setpoint" not in key
        assert "write" not in key
        assert "control" not in key
        assert "command" not in key
        assert "actuate" not in key
        assert "dispatch" not in key


def test_advisory_decision_round_trip() -> None:
    proposal = AdvisoryProposal(
        proposal_id="p0",
        axis="pump_speed",
        target_id=0,
        proposed_value=0.7,
    )
    decision = AdvisoryDecision(
        proposal=proposal,
        status="accepted",
        accepted=True,
    )
    decoded = load_canonical_json(dump_canonical_json(decision))
    restored = AdvisoryDecision.from_dict(decoded)
    assert restored == decision


def test_advisory_decision_rejects_unknown_status() -> None:
    proposal = AdvisoryProposal(
        proposal_id="p0",
        axis="pump_speed",
        target_id=0,
        proposed_value=0.7,
    )
    with pytest.raises(ContractError):
        AdvisoryDecision(
            proposal=proposal,
            status="executed",
            accepted=True,
        )


def test_advisory_decision_rejects_inconsistent_accepted_flag() -> None:
    proposal = AdvisoryProposal(
        proposal_id="p0",
        axis="pump_speed",
        target_id=0,
        proposed_value=0.7,
    )
    with pytest.raises(ContractError):
        AdvisoryDecision(
            proposal=proposal,
            status="rejected",
            accepted=True,
        )


def test_advisory_rejection_reason_round_trip() -> None:
    reason = AdvisoryRejectionReason(
        code="out_of_bounds",
        rule_id="r0",
        description="proposed value exceeds rule bound",
    )
    decoded = load_canonical_json(dump_canonical_json(reason))
    restored = AdvisoryRejectionReason.from_dict(decoded)
    assert restored == reason


def test_advisory_rejection_reason_rejects_unknown_code() -> None:
    with pytest.raises(ContractError):
        AdvisoryRejectionReason(
            code="forbidden_actuation",
            rule_id="r0",
            description="any",
        )


def test_advisory_evaluation_round_trip() -> None:
    proposal = AdvisoryProposal(
        proposal_id="p0",
        axis="pump_speed",
        target_id=0,
        proposed_value=0.7,
    )
    decision = AdvisoryDecision(
        proposal=proposal,
        status="rejected",
        accepted=False,
        rejection_reasons=(
            AdvisoryRejectionReason(
                code="out_of_bounds",
                rule_id="r0",
                description="proposed value exceeds rule bound",
            ),
        ),
        violated_rule_ids=("r0",),
    )
    evaluation = AdvisoryEvaluation(
        contract_name="ctr",
        decisions=(decision,),
        proposal_count=1,
        accepted_count=0,
        rejected_count=1,
    )
    decoded = load_canonical_json(dump_canonical_json(evaluation))
    restored = AdvisoryEvaluation.from_dict(decoded)
    assert restored == evaluation


def test_advisory_evaluation_rejects_inconsistent_counts() -> None:
    proposal = AdvisoryProposal(
        proposal_id="p0",
        axis="pump_speed",
        target_id=0,
        proposed_value=0.7,
    )
    decision = AdvisoryDecision(
        proposal=proposal,
        status="accepted",
        accepted=True,
    )
    with pytest.raises(ContractError):
        AdvisoryEvaluation(
            contract_name="ctr",
            decisions=(decision,),
            proposal_count=2,
            accepted_count=1,
            rejected_count=1,
        )


def test_advisory_axis_tokens_have_no_actuation_verbs() -> None:
    for axis in ADVISORY_SDK_AXES:
        for forbidden in (
            "execute",
            "dispatch",
            "write",
            "actuate",
            "emit",
        ):
            assert forbidden not in axis


def test_advisory_decision_statuses_have_no_actuation_verbs() -> None:
    for status in ADVISORY_DECISION_STATUSES:
        assert status in {"accepted", "rejected"}


def test_advisory_rejection_reasons_are_canonical() -> None:
    expected = {
        "out_of_bounds",
        "delta_exceeded",
        "deny_rule_match",
        "no_allow_rule_match",
        "insufficient_evidence",
        "axis_loss_exceeded",
        "malformed_proposal",
    }
    assert set(ADVISORY_REJECTION_REASONS) == expected


def test_phase1_advisory_projection_round_trips() -> None:
    """Project a Phase 1 advisory decision tuple into the SDK shape.

    The projection adapter must not import advisory runtime code from
    inside SDK package code; this test invokes the Phase 1 evaluator
    externally and projects the result.
    """
    from aquaoptima.dphm.advisory_contract import (
        AdvisoryProposal as Phase1AdvisoryProposal,
        AdvisoryRule as Phase1AdvisoryRule,
        build_advisory_contract,
        evaluate_advisory_proposals,
    )

    phase1_contract = build_advisory_contract(
        name="ctr",
        allow_rules=(
            Phase1AdvisoryRule(
                axis="pump_speed",
                target_id=0,
                min_value=0.0,
                max_value=1.0,
            ),
        ),
    )
    proposals = (
        Phase1AdvisoryProposal(
            proposal_id="p0",
            axis="pump_speed",
            target_id=0,
            proposed_value=0.5,
        ),
        Phase1AdvisoryProposal(
            proposal_id="p1",
            axis="pump_speed",
            target_id=0,
            proposed_value=1.5,
        ),
    )
    phase1_decisions = evaluate_advisory_proposals(phase1_contract, proposals)
    evaluation = project_phase1_advisory_decisions(
        phase1_decisions, contract_name="ctr"
    )
    assert isinstance(evaluation, AdvisoryEvaluation)
    assert evaluation.proposal_count == 2
    assert evaluation.accepted_count == 1
    assert evaluation.rejected_count == 1
    assert evaluation.decisions[0].accepted is True
    assert evaluation.decisions[1].accepted is False
    decoded = load_canonical_json(dump_canonical_json(evaluation))
    restored = AdvisoryEvaluation.from_dict(decoded)
    assert restored == evaluation
