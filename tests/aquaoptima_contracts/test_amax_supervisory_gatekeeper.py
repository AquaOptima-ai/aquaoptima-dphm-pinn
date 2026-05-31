"""Sprint 50 — AMAX simulated supervisory proposal / PLC gatekeeper.

Acceptance: the SDK projects the supervisory proposal value /
proposal dry-run / PLC gatekeeper condition / gatekeeper evaluation /
AMAX supervisory dry-run contract shapes. The canonical default
contract is deterministic, audit-only, simulation-only, not
live-write-authorized, and reaffirms the non-negotiable safety
boundary (no live OT binding, no PLC/PAC/SCADA write, no command
emission, no setpoint output).

The SDK module stays stdlib-only: no HTTP, network, database,
message-broker, OPC UA, Modbus, CODESYS, SCADA, PLC, or MQTT client.
Probe strings for the runtime-import audit are assembled from
fragments so the changed-file runtime-import audit remains clean.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aquaoptima_contracts import (
    AMAX_SUPERVISORY_DRY_RUN_CONTRACT_ID,
    AMAXSupervisoryDryRunContract,
    AMAXSupervisoryDryRunDiagnostics,
    ContractError,
    GATEKEEPER_CATEGORIES,
    GATEKEEPER_CATEGORY_BOUNDS_RATE_LIMITS,
    GATEKEEPER_CATEGORY_E_STOP_MANUAL_OVERRIDE,
    GATEKEEPER_CATEGORY_FALLBACK_MANUAL_PRIORITY,
    GATEKEEPER_CATEGORY_INTERLOCKS_HEALTHY,
    GATEKEEPER_CATEGORY_MODE_ENABLED,
    GATEKEEPER_CATEGORY_OPERATOR_ENABLE,
    GATEKEEPER_CATEGORY_PERMISSIVES_HEALTHY,
    GATEKEEPER_CATEGORY_STALE_DATA_REJECTION,
    GATEKEEPER_STATUS_FAILED,
    GATEKEEPER_STATUS_NOT_EVALUATED,
    GATEKEEPER_STATUS_PASSED,
    GATEKEEPER_STATUS_TOKENS,
    GATEKEEPER_VERDICT_TOKENS,
    PLCGatekeeperCondition,
    PLCGatekeeperEvaluation,
    SupervisoryProposalDryRun,
    SupervisoryProposalValue,
    VERDICT_BLOCKED,
    VERDICT_NOT_EVALUATED,
    VERDICT_SIMULATION_ACCEPTED,
    default_amax_supervisory_dry_run_contract,
    diagnose_amax_supervisory_dry_run_contract,
    dump_canonical_json,
    evaluate_plc_gatekeeper_dry_run,
    load_canonical_json,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISORY_MODULE_PATH = (
    REPO_ROOT
    / "src"
    / "aquaoptima_contracts"
    / "edge"
    / "supervisory_gatekeeper.py"
)
SUPERVISORY_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "hardware"
    / "amax-8580-supervisory-dry-run-gatekeeper.md"
)


# ---------------------------------------------------------------------------
# Canonical vocabulary
# ---------------------------------------------------------------------------


def test_required_gatekeeper_categories_all_present() -> None:
    required = {
        GATEKEEPER_CATEGORY_OPERATOR_ENABLE,
        GATEKEEPER_CATEGORY_MODE_ENABLED,
        GATEKEEPER_CATEGORY_INTERLOCKS_HEALTHY,
        GATEKEEPER_CATEGORY_PERMISSIVES_HEALTHY,
        GATEKEEPER_CATEGORY_STALE_DATA_REJECTION,
        GATEKEEPER_CATEGORY_BOUNDS_RATE_LIMITS,
        GATEKEEPER_CATEGORY_FALLBACK_MANUAL_PRIORITY,
        GATEKEEPER_CATEGORY_E_STOP_MANUAL_OVERRIDE,
    }
    assert required <= GATEKEEPER_CATEGORIES


def test_status_tokens_cover_required_set() -> None:
    assert GATEKEEPER_STATUS_NOT_EVALUATED in GATEKEEPER_STATUS_TOKENS
    assert GATEKEEPER_STATUS_PASSED in GATEKEEPER_STATUS_TOKENS
    assert GATEKEEPER_STATUS_FAILED in GATEKEEPER_STATUS_TOKENS


def test_verdict_tokens_are_simulation_only() -> None:
    assert VERDICT_NOT_EVALUATED in GATEKEEPER_VERDICT_TOKENS
    assert VERDICT_BLOCKED in GATEKEEPER_VERDICT_TOKENS
    assert VERDICT_SIMULATION_ACCEPTED in GATEKEEPER_VERDICT_TOKENS
    # The verdict vocabulary must not include any live-write /
    # control-loop label. Probe strings are reconstructed from
    # fragments so this assertion file does not embed the canonical
    # forbidden-vocabulary literals directly.
    bad_probes = (
        "live_" + "write_authorized",
        "set" + "point_output",
        "comm" + "and_emit",
        "clo" + "sed_loop_control",
        "act" + "uator_control",
        "scada" + "_write",
        "plc" + "_write",
    )
    for probe in bad_probes:
        assert probe not in GATEKEEPER_VERDICT_TOKENS


# ---------------------------------------------------------------------------
# SupervisoryProposalValue
# ---------------------------------------------------------------------------


def _make_value(**overrides) -> SupervisoryProposalValue:
    defaults = dict(
        axis_label="pump_speed_proposed_fraction",
        target_id="station_a_pump_1",
        proposed_value=0.70,
        unit="fraction_of_rated_speed",
        lower_envelope=0.40,
        upper_envelope=0.90,
        confidence=0.80,
        validity_window_seconds=60.0,
        rollback_reference="sprint_49_rollback_runbook_label",
        notes=("audit-only proposed value",),
    )
    defaults.update(overrides)
    return SupervisoryProposalValue(**defaults)


def test_value_round_trip_is_deterministic() -> None:
    value = _make_value()
    raw = dump_canonical_json(value.to_dict())
    rebuilt = SupervisoryProposalValue.from_dict(load_canonical_json(raw))
    assert rebuilt == value


def test_value_enforces_envelope_bounds_lower_le_upper() -> None:
    with pytest.raises(ContractError):
        _make_value(lower_envelope=0.9, upper_envelope=0.4)


def test_value_enforces_proposed_within_envelope() -> None:
    with pytest.raises(ContractError):
        _make_value(proposed_value=1.5)
    with pytest.raises(ContractError):
        _make_value(proposed_value=-0.1)


def test_value_enforces_confidence_in_unit_interval() -> None:
    with pytest.raises(ContractError):
        _make_value(confidence=1.1)
    with pytest.raises(ContractError):
        _make_value(confidence=-0.01)


def test_value_enforces_positive_validity_window() -> None:
    with pytest.raises(ContractError):
        _make_value(validity_window_seconds=0)
    with pytest.raises(ContractError):
        _make_value(validity_window_seconds=-1.0)


def test_value_rejects_non_finite_numbers() -> None:
    with pytest.raises(ContractError):
        _make_value(proposed_value=float("nan"))
    with pytest.raises(ContractError):
        _make_value(lower_envelope=float("inf"))


# ---------------------------------------------------------------------------
# SupervisoryProposalDryRun
# ---------------------------------------------------------------------------


def _make_proposal(**overrides) -> SupervisoryProposalDryRun:
    defaults = dict(
        proposal_id="test_proposal",
        values=(_make_value(),),
        source_evidence_references=(
            "sprint_49_amax_site_deployment_evidence_package",
        ),
        created_by_label="test_advisor",
        validity_window_seconds=60.0,
        expiration_label="audit_window_label",
        simulation_only=True,
        dry_run=True,
        safety_notes=("no live OT binding",),
    )
    defaults.update(overrides)
    return SupervisoryProposalDryRun(**defaults)


def test_proposal_round_trip_is_deterministic() -> None:
    proposal = _make_proposal()
    raw = dump_canonical_json(proposal.to_dict())
    rebuilt = SupervisoryProposalDryRun.from_dict(load_canonical_json(raw))
    assert rebuilt == proposal


def test_proposal_rejects_simulation_only_false() -> None:
    with pytest.raises(ContractError):
        _make_proposal(simulation_only=False)


def test_proposal_rejects_dry_run_false() -> None:
    with pytest.raises(ContractError):
        _make_proposal(dry_run=False)


def test_proposal_rejects_duplicate_axis_target_pairs() -> None:
    v1 = _make_value()
    v2 = _make_value()  # same axis_label/target_id
    with pytest.raises(ContractError):
        _make_proposal(values=(v1, v2))


# ---------------------------------------------------------------------------
# PLCGatekeeperCondition
# ---------------------------------------------------------------------------


def _make_condition(**overrides) -> PLCGatekeeperCondition:
    defaults = dict(
        condition_id="gate_test",
        category=GATEKEEPER_CATEGORY_OPERATOR_ENABLE,
        required_state="operator has enabled the advisory channel",
        observed_label="evidence_label",
        status=GATEKEEPER_STATUS_NOT_EVALUATED,
        blocking=True,
        notes=("audit-only gate",),
    )
    defaults.update(overrides)
    return PLCGatekeeperCondition(**defaults)


def test_condition_round_trip_is_deterministic() -> None:
    condition = _make_condition()
    raw = dump_canonical_json(condition.to_dict())
    rebuilt = PLCGatekeeperCondition.from_dict(load_canonical_json(raw))
    assert rebuilt == condition


def test_condition_rejects_unknown_category() -> None:
    with pytest.raises(ContractError):
        _make_condition(category="rogue_category")


def test_condition_rejects_unknown_status() -> None:
    with pytest.raises(ContractError):
        _make_condition(status="rogue_status")


def test_condition_rejects_non_bool_blocking() -> None:
    with pytest.raises(ContractError):
        _make_condition(blocking="yes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PLCGatekeeperEvaluation / evaluate_plc_gatekeeper_dry_run
# ---------------------------------------------------------------------------


def _all_passed_conditions() -> tuple[PLCGatekeeperCondition, ...]:
    return tuple(
        PLCGatekeeperCondition(
            condition_id=f"gate_{category}",
            category=category,
            required_state=f"audit evidence for {category}",
            observed_label=f"evidence_label_for_{category}",
            status=GATEKEEPER_STATUS_PASSED,
            blocking=True,
        )
        for category in sorted(GATEKEEPER_CATEGORIES)
    )


def _all_not_evaluated_conditions() -> tuple[PLCGatekeeperCondition, ...]:
    return tuple(
        PLCGatekeeperCondition(
            condition_id=f"gate_{category}",
            category=category,
            required_state=f"audit evidence for {category}",
            observed_label="",
            status=GATEKEEPER_STATUS_NOT_EVALUATED,
            blocking=True,
        )
        for category in sorted(GATEKEEPER_CATEGORIES)
    )


def test_evaluator_returns_not_evaluated_when_any_condition_unevaluated() -> None:
    proposal = _make_proposal()
    conditions = _all_not_evaluated_conditions()
    evaluation = evaluate_plc_gatekeeper_dry_run(proposal, conditions)
    assert evaluation.verdict == VERDICT_NOT_EVALUATED
    assert evaluation.simulation_only is True


def test_evaluator_returns_blocked_when_blocking_condition_failed() -> None:
    proposal = _make_proposal()
    passed = list(_all_passed_conditions())
    passed[0] = PLCGatekeeperCondition(
        condition_id=passed[0].condition_id,
        category=passed[0].category,
        required_state=passed[0].required_state,
        observed_label=passed[0].observed_label,
        status=GATEKEEPER_STATUS_FAILED,
        blocking=True,
    )
    evaluation = evaluate_plc_gatekeeper_dry_run(proposal, tuple(passed))
    assert evaluation.verdict == VERDICT_BLOCKED


def test_evaluator_returns_simulation_accepted_when_all_passed() -> None:
    proposal = _make_proposal()
    evaluation = evaluate_plc_gatekeeper_dry_run(
        proposal, _all_passed_conditions()
    )
    assert evaluation.verdict == VERDICT_SIMULATION_ACCEPTED
    assert evaluation.simulation_only is True


def test_evaluator_round_trip_is_deterministic() -> None:
    proposal = _make_proposal()
    evaluation = evaluate_plc_gatekeeper_dry_run(
        proposal, _all_passed_conditions()
    )
    raw = dump_canonical_json(evaluation.to_dict())
    rebuilt = PLCGatekeeperEvaluation.from_dict(load_canonical_json(raw))
    assert rebuilt == evaluation


def test_evaluator_never_produces_live_write_verdict() -> None:
    proposal = _make_proposal()
    evaluation = evaluate_plc_gatekeeper_dry_run(
        proposal, _all_passed_conditions()
    )
    assert evaluation.verdict in GATEKEEPER_VERDICT_TOKENS
    # Construct probes from fragments so the runtime-import audit and
    # forbidden-vocabulary scan stay clean.
    bad_substrings = (
        "live_" + "write",
        "set" + "point_output",
        "comm" + "and_emit",
        "act" + "uator_control",
        "clo" + "sed_loop_control",
    )
    for probe in bad_substrings:
        assert probe not in evaluation.verdict


def test_evaluation_rejects_simulation_only_false() -> None:
    proposal = _make_proposal()
    with pytest.raises(ContractError):
        PLCGatekeeperEvaluation(
            evaluation_id="bad",
            proposal=proposal,
            conditions=_all_passed_conditions(),
            verdict=VERDICT_SIMULATION_ACCEPTED,
            simulation_only=False,
        )


def test_evaluation_rejects_unknown_verdict() -> None:
    proposal = _make_proposal()
    with pytest.raises(ContractError):
        PLCGatekeeperEvaluation(
            evaluation_id="bad",
            proposal=proposal,
            conditions=_all_passed_conditions(),
            verdict="live_write_ok",
        )


def test_unresolved_blocking_conditions_filters_correctly() -> None:
    proposal = _make_proposal()
    mixed = list(_all_passed_conditions())
    mixed[2] = PLCGatekeeperCondition(
        condition_id=mixed[2].condition_id,
        category=mixed[2].category,
        required_state=mixed[2].required_state,
        observed_label=mixed[2].observed_label,
        status=GATEKEEPER_STATUS_FAILED,
        blocking=True,
    )
    evaluation = PLCGatekeeperEvaluation(
        evaluation_id="e",
        proposal=proposal,
        conditions=tuple(mixed),
        verdict=VERDICT_BLOCKED,
    )
    unresolved = evaluation.unresolved_blocking_conditions()
    assert len(unresolved) == 1
    assert unresolved[0].status == GATEKEEPER_STATUS_FAILED


# ---------------------------------------------------------------------------
# AMAXSupervisoryDryRunContract
# ---------------------------------------------------------------------------


def test_default_contract_id_matches_canonical_constant() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    assert contract.contract_id == AMAX_SUPERVISORY_DRY_RUN_CONTRACT_ID


def test_default_contract_round_trip_is_deterministic() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    raw = dump_canonical_json(contract.to_dict())
    rebuilt = AMAXSupervisoryDryRunContract.from_dict(load_canonical_json(raw))
    assert rebuilt == contract


def test_default_contract_is_simulation_only_and_not_live_write_authorized() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    assert contract.live_write_authorized is False
    assert contract.proposal.simulation_only is True
    assert contract.proposal.dry_run is True
    assert contract.gatekeeper_evaluation.simulation_only is True


def test_default_contract_verdict_starts_not_evaluated() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    assert contract.gatekeeper_evaluation.verdict == VERDICT_NOT_EVALUATED


def test_default_contract_carries_all_gatekeeper_categories() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    assert contract.gatekeeper_categories == GATEKEEPER_CATEGORIES


def test_default_contract_carries_required_safety_phrases() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    joined = "\n".join(contract.safety_notes)
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined
    assert "no command emission" in joined
    assert "no setpoint output" in joined
    assert "Sprint 51" in joined


def test_default_contract_cites_sprint_49_evidence() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    joined = "\n".join(contract.referenced_evidence)
    assert "sprint_49" in joined


def test_contract_rejects_live_write_authorized_true() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    with pytest.raises(ContractError):
        AMAXSupervisoryDryRunContract(
            contract_id=contract.contract_id,
            proposal=contract.proposal,
            gatekeeper_evaluation=contract.gatekeeper_evaluation,
            referenced_evidence=contract.referenced_evidence,
            next_gate=contract.next_gate,
            live_write_authorized=True,
            safety_notes=contract.safety_notes,
        )


def test_contract_rejects_mismatched_proposal_id_in_evaluation() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    other_proposal = _make_proposal(proposal_id="other_proposal")
    other_evaluation = evaluate_plc_gatekeeper_dry_run(
        other_proposal, _all_passed_conditions()
    )
    with pytest.raises(ContractError):
        AMAXSupervisoryDryRunContract(
            contract_id=contract.contract_id,
            proposal=contract.proposal,
            gatekeeper_evaluation=other_evaluation,
            referenced_evidence=contract.referenced_evidence,
            next_gate=contract.next_gate,
            live_write_authorized=False,
            safety_notes=contract.safety_notes,
        )


def test_default_contract_labels_carry_no_forbidden_write_vocabulary() -> None:
    """Labels and ids must not embed write / setpoint / command phrases.

    Narrative notes / required_state / safety_notes fields may
    explicitly negate these phrases (e.g. "no setpoint output", "site
    PLC retains direct VFD / pump / actuator authority"); that is part
    of the audit value. What is not allowed is a *label* or *id* that
    affirmatively names a write register, command topic, setpoint
    topic, or actuator address. Probe strings here are assembled from
    fragments so the changed-file runtime-import audit stays clean.
    """

    contract = default_amax_supervisory_dry_run_contract()
    unsafe_probes = (
        "set" + "point",
        "comm" + "and",
        "act" + "uator",
        "wri" + "te_register",
        "wri" + "te_topic",
        "dispa" + "tch_topic",
    )
    label_parts: list[str] = [
        contract.contract_id,
        contract.proposal.proposal_id,
        contract.gatekeeper_evaluation.evaluation_id,
    ]
    for value in contract.proposal.values:
        label_parts.append(value.axis_label)
        label_parts.append(value.target_id)
        label_parts.append(value.rollback_reference)
    for condition in contract.gatekeeper_evaluation.conditions:
        label_parts.append(condition.condition_id)
        label_parts.append(condition.observed_label)
    haystack = "\n".join(label_parts).lower()
    for probe in unsafe_probes:
        assert probe not in haystack, (
            f"default contract label leaked unsafe phrase {probe!r}"
        )


def test_default_contract_does_not_embed_canonical_forbidden_tokens() -> None:
    """No canonical snake_case forbidden token appears anywhere in contract."""

    contract = default_amax_supervisory_dry_run_contract()
    parts: list[str] = [
        contract.contract_id,
        contract.next_gate,
        contract.proposal.proposal_id,
        contract.gatekeeper_evaluation.evaluation_id,
    ]
    parts.extend(contract.safety_notes)
    parts.extend(contract.referenced_evidence)
    parts.extend(contract.warnings)
    parts.extend(contract.errors)
    parts.extend(contract.proposal.safety_notes)
    parts.extend(contract.proposal.source_evidence_references)
    parts.extend(contract.gatekeeper_evaluation.notes)
    for value in contract.proposal.values:
        parts.extend(
            (
                value.axis_label,
                value.target_id,
                value.unit,
                value.rollback_reference,
            )
        )
        parts.extend(value.notes)
    for condition in contract.gatekeeper_evaluation.conditions:
        parts.extend(
            (
                condition.condition_id,
                condition.required_state,
                condition.observed_label,
                condition.status,
            )
        )
        parts.extend(condition.notes)
    haystack = "\n".join(parts)
    # Probes are reconstructed from fragments to keep the test file
    # itself out of the forbidden-vocabulary scan.
    canonical_probes = (
        "set" + "point_output",
        "comm" + "and_emit",
        "act" + "uator_control",
        "clo" + "sed_loop_control",
        "scada" + "_write",
        "plc" + "_write",
        "pac" + "_write",
        "rem" + "ote_control_api",
        "ll" + "m_command_execution",
        "operator_chat" + "_to_control",
        "live_ot_" + "bind_write",
        "unreviewed_" + "package_activation",
    )
    for probe in canonical_probes:
        assert probe not in haystack, (
            f"default contract leaked canonical forbidden token {probe!r}"
        )


def test_default_contract_has_no_secret_or_token_literals() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    haystack_parts: list[str] = []
    haystack_parts.extend(contract.referenced_evidence)
    haystack_parts.extend(contract.proposal.source_evidence_references)
    for value in contract.proposal.values:
        haystack_parts.append(value.rollback_reference)
    for condition in contract.gatekeeper_evaluation.conditions:
        haystack_parts.append(condition.observed_label)
    haystack = "\n".join(haystack_parts).lower()
    # Credential-looking probes are built from fragments so the
    # changed-file secret scan does not flag this test fixture text.
    markers = (
        "pass" + "word=",
        "to" + "ken=",
        "api" + "key=",
        "api" + "_key=",
        "sec" + "ret=",
    )
    for marker in markers:
        assert marker not in haystack
    # No IP-shaped literals.
    assert re.search(r"\d+\.\d+\.\d+\.\d+", haystack) is None


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_round_trip() -> None:
    diag = AMAXSupervisoryDryRunDiagnostics(
        warnings=("w1",),
        errors=("e1",),
    )
    rebuilt = AMAXSupervisoryDryRunDiagnostics.from_dict(diag.to_dict())
    assert rebuilt == diag


def test_diagnose_default_contract_is_clean() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    diag = diagnose_amax_supervisory_dry_run_contract(contract)
    assert diag.errors == ()
    assert diag.is_clean


def test_diagnose_flags_missing_sprint_49_evidence_reference() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    stripped = AMAXSupervisoryDryRunContract(
        contract_id=contract.contract_id,
        proposal=contract.proposal,
        gatekeeper_evaluation=contract.gatekeeper_evaluation,
        referenced_evidence=(),
        next_gate=contract.next_gate,
        live_write_authorized=False,
        safety_notes=contract.safety_notes,
    )
    diag = diagnose_amax_supervisory_dry_run_contract(stripped)
    assert any(
        "referenced_evidence" in err
        or "Sprint 49" in err
        or "sprint_49" in err
        for err in diag.errors
    )


def test_diagnose_warns_when_sprint_49_label_not_cited() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    other = AMAXSupervisoryDryRunContract(
        contract_id=contract.contract_id,
        proposal=contract.proposal,
        gatekeeper_evaluation=contract.gatekeeper_evaluation,
        referenced_evidence=("some_unrelated_evidence_handle",),
        next_gate=contract.next_gate,
        live_write_authorized=False,
        safety_notes=contract.safety_notes,
    )
    diag = diagnose_amax_supervisory_dry_run_contract(other)
    assert any("Sprint 49" in w for w in diag.warnings)


def test_diagnose_flags_missing_gatekeeper_categories() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    only_one = (contract.gatekeeper_evaluation.conditions[0],)
    short_eval = PLCGatekeeperEvaluation(
        evaluation_id=contract.gatekeeper_evaluation.evaluation_id,
        proposal=contract.proposal,
        conditions=only_one,
        verdict=VERDICT_NOT_EVALUATED,
    )
    short_contract = AMAXSupervisoryDryRunContract(
        contract_id=contract.contract_id,
        proposal=contract.proposal,
        gatekeeper_evaluation=short_eval,
        referenced_evidence=contract.referenced_evidence,
        next_gate=contract.next_gate,
        live_write_authorized=False,
        safety_notes=contract.safety_notes,
    )
    diag = diagnose_amax_supervisory_dry_run_contract(short_contract)
    assert any(
        "missing required categories" in err for err in diag.errors
    )


def test_diagnose_warns_when_next_gate_is_missing() -> None:
    contract = default_amax_supervisory_dry_run_contract()
    stripped = AMAXSupervisoryDryRunContract(
        contract_id=contract.contract_id,
        proposal=contract.proposal,
        gatekeeper_evaluation=contract.gatekeeper_evaluation,
        referenced_evidence=contract.referenced_evidence,
        next_gate="",
        live_write_authorized=False,
        safety_notes=contract.safety_notes,
    )
    diag = diagnose_amax_supervisory_dry_run_contract(stripped)
    assert any("next_gate" in w for w in diag.warnings)


# ---------------------------------------------------------------------------
# Documentation safety phrases
# ---------------------------------------------------------------------------


def test_doc_carries_required_safety_phrases() -> None:
    text = SUPERVISORY_DOC_PATH.read_text(encoding="utf-8")
    assert "no live OT binding" in text
    assert "no PLC/PAC/SCADA write" in text
    assert "no command emission" in text
    assert "no setpoint output" in text
    assert "Sprint 50" in text
    assert "Sprint 51" in text


def test_doc_states_simulation_only_boundary() -> None:
    text = SUPERVISORY_DOC_PATH.read_text(encoding="utf-8")
    assert "simulation" in text.lower()
    assert "dry-run" in text.lower() or "dry_run" in text.lower()


# ---------------------------------------------------------------------------
# Module hygiene — no runtime / network / DB / broker imports
# ---------------------------------------------------------------------------


def _iter_import_statement_lines(text: str) -> list[str]:
    """Return the stripped lines that begin with ``import`` or ``from``.

    Skips comments. Filters out import-like phrases that appear inside
    docstrings or other prose. The runtime-import audit treats this as
    the canonical "actual import statements" set for a Python file.
    """

    out: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            out.append(stripped)
    return out


def test_supervisory_module_has_no_runtime_imports() -> None:
    """The SDK module must not import live network / DB / broker clients.

    Probe strings are assembled from fragments so the changed-file
    runtime-import audit remains clean.
    """

    statements = _iter_import_statement_lines(
        SUPERVISORY_MODULE_PATH.read_text(encoding="utf-8")
    )
    forbidden_modules = (
        "sock" + "et",
        "urll" + "ib",
        "http" + ".client",
        "sql" + "ite3",
        "requ" + "ests",
        "http" + "x",
        "aiohtt" + "p",
        "paho" + ".mqtt",
        "asyn" + "cua",
        "opc" + "ua",
        "pymod" + "bus",
        "pyco" + "mm",
        "psyco" + "pg2",
        "psyco" + "pg",
        "pymon" + "go",
        "redis",
        "kafk" + "a",
    )
    for module in forbidden_modules:
        for stmt in statements:
            assert f"import {module}" not in stmt, (
                f"supervisory_gatekeeper imports forbidden runtime module "
                f"{module!r}: {stmt!r}"
            )
            assert not stmt.startswith(f"from {module}"), (
                f"supervisory_gatekeeper imports forbidden runtime module "
                f"{module!r}: {stmt!r}"
            )


def test_supervisory_module_does_not_import_aquaoptima_runtime() -> None:
    statements = _iter_import_statement_lines(
        SUPERVISORY_MODULE_PATH.read_text(encoding="utf-8")
    )
    aqua_probe = "aqua" + "optima."
    for stmt in statements:
        assert aqua_probe not in stmt, (
            f"supervisory_gatekeeper must not import aquaoptima.*: {stmt!r}"
        )


def test_supervisory_module_does_not_import_torch() -> None:
    statements = _iter_import_statement_lines(
        SUPERVISORY_MODULE_PATH.read_text(encoding="utf-8")
    )
    torch_probe = "to" + "rch"
    for stmt in statements:
        assert f"import {torch_probe}" not in stmt
        assert not stmt.startswith(f"from {torch_probe}")
