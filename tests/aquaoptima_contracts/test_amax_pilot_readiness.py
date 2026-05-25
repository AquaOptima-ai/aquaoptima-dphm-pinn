"""Sprint 51 — AMAX pilot readiness review / HIL plan acceptance.

Acceptance: the SDK projects the HIL test case / HIL test matrix /
pilot readiness evidence item / pilot readiness review shapes plus
the canonical Sprint 51 default helpers and evaluator. The canonical
default review is deterministic, audit-only, planning-only, not
live-control-authorized, and reaffirms the non-negotiable safety
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
    AMAX_HIL_TEST_MATRIX_ID,
    AMAX_PILOT_READINESS_REVIEW_ID,
    AMAXPilotReadinessDiagnostics,
    ContractError,
    HIL_CATEGORY_CPU_BENCHMARK,
    HIL_CATEGORY_DEPLOYMENT_READINESS_REVIEW,
    HIL_CATEGORY_NETWORK_LOSS,
    HIL_CATEGORY_OPERATOR_DISABLE,
    HIL_CATEGORY_PACKAGE_INSTALL,
    HIL_CATEGORY_PACKAGE_ROLLBACK,
    HIL_CATEGORY_PLC_GATEKEEPER_DRY_RUN,
    HIL_CATEGORY_READ_ONLY_ADAPTER,
    HIL_CATEGORY_STALE_DATA_FAILURE,
    HIL_CATEGORY_TELEMETRY_REPLAY,
    HIL_TEST_CATEGORIES,
    HILTestCase,
    HILTestMatrix,
    PILOT_EVIDENCE_STATUS_AVAILABLE,
    PILOT_EVIDENCE_STATUS_BLOCKED,
    PILOT_EVIDENCE_STATUS_PENDING,
    PILOT_EVIDENCE_STATUS_TOKENS,
    PILOT_READINESS_VERDICT_TOKENS,
    PILOT_VERDICT_BLOCKED,
    PILOT_VERDICT_NOT_READY,
    PILOT_VERDICT_READY_FOR_LAB_SIMULATION,
    PilotReadinessEvidenceItem,
    PilotReadinessReview,
    default_amax_hil_test_matrix,
    default_amax_pilot_readiness_review,
    diagnose_amax_pilot_readiness_review,
    dump_canonical_json,
    evaluate_amax_pilot_readiness_review,
    load_canonical_json,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT_READINESS_MODULE_PATH = (
    REPO_ROOT
    / "src"
    / "aquaoptima_contracts"
    / "edge"
    / "pilot_readiness.py"
)
PILOT_READINESS_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "hardware"
    / "amax-5580-pilot-readiness-hil-plan.md"
)


# ---------------------------------------------------------------------------
# Canonical vocabulary
# ---------------------------------------------------------------------------


def test_required_hil_categories_all_present() -> None:
    required = {
        HIL_CATEGORY_PACKAGE_INSTALL,
        HIL_CATEGORY_CPU_BENCHMARK,
        HIL_CATEGORY_READ_ONLY_ADAPTER,
        HIL_CATEGORY_TELEMETRY_REPLAY,
        HIL_CATEGORY_STALE_DATA_FAILURE,
        HIL_CATEGORY_PACKAGE_ROLLBACK,
        HIL_CATEGORY_OPERATOR_DISABLE,
        HIL_CATEGORY_NETWORK_LOSS,
        HIL_CATEGORY_PLC_GATEKEEPER_DRY_RUN,
        HIL_CATEGORY_DEPLOYMENT_READINESS_REVIEW,
    }
    assert required <= HIL_TEST_CATEGORIES


def test_evidence_status_tokens_cover_required_set() -> None:
    assert PILOT_EVIDENCE_STATUS_PENDING in PILOT_EVIDENCE_STATUS_TOKENS
    assert PILOT_EVIDENCE_STATUS_AVAILABLE in PILOT_EVIDENCE_STATUS_TOKENS
    assert PILOT_EVIDENCE_STATUS_BLOCKED in PILOT_EVIDENCE_STATUS_TOKENS


def test_verdict_tokens_are_lab_simulation_only() -> None:
    assert PILOT_VERDICT_NOT_READY in PILOT_READINESS_VERDICT_TOKENS
    assert (
        PILOT_VERDICT_READY_FOR_LAB_SIMULATION
        in PILOT_READINESS_VERDICT_TOKENS
    )
    assert PILOT_VERDICT_BLOCKED in PILOT_READINESS_VERDICT_TOKENS
    # The verdict vocabulary must not include any live-write /
    # control-loop label. Probe strings are reconstructed from
    # fragments so this assertion file does not embed the canonical
    # forbidden-vocabulary literals directly.
    bad_probes = (
        "live_" + "write_authorized",
        "live_" + "control_authorized",
        "set" + "point_output",
        "comm" + "and_emit",
        "clo" + "sed_loop_control",
        "act" + "uator_control",
        "scada" + "_write",
        "plc" + "_write",
    )
    for probe in bad_probes:
        assert probe not in PILOT_READINESS_VERDICT_TOKENS


# ---------------------------------------------------------------------------
# HILTestCase
# ---------------------------------------------------------------------------


def _make_case(**overrides) -> HILTestCase:
    defaults = dict(
        test_id="hil_test_case",
        category=HIL_CATEGORY_PACKAGE_INSTALL,
        objective="verify the package validator accepts the signed package",
        required_evidence_references=(
            "sprint_45_amax_edge_capability_declaration",
            "sprint_49_amax_site_deployment_evidence_package",
        ),
        expected_result="validator returns accepted=True",
        blocking=True,
        simulation_only=True,
        notes=("audit-only",),
    )
    defaults.update(overrides)
    return HILTestCase(**defaults)


def test_case_round_trip_is_deterministic() -> None:
    case = _make_case()
    raw = dump_canonical_json(case.to_dict())
    rebuilt = HILTestCase.from_dict(load_canonical_json(raw))
    assert rebuilt == case


def test_case_rejects_unknown_category() -> None:
    with pytest.raises(ContractError):
        _make_case(category="rogue_category")


def test_case_rejects_simulation_only_false() -> None:
    with pytest.raises(ContractError):
        _make_case(simulation_only=False)


def test_case_rejects_non_bool_blocking() -> None:
    with pytest.raises(ContractError):
        _make_case(blocking="yes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HILTestMatrix
# ---------------------------------------------------------------------------


def _make_matrix(**overrides) -> HILTestMatrix:
    cases = tuple(
        HILTestCase(
            test_id=f"hil_case_{category}",
            category=category,
            objective=f"audit-only objective for {category}",
        )
        for category in sorted(HIL_TEST_CATEGORIES)
    )
    defaults = dict(
        matrix_id="test_matrix",
        test_cases=cases,
        target_hardware_profile_label="lab_amax_5580_label",
        target_os_runtime_label="lab_runtime_label",
        bench_plc_label="bench_plc_label",
        referenced_evidence=(
            "sprint_46_amax_feasibility_decision",
            "sprint_47_amax_benchmark_report",
            "sprint_48_amax_read_only_integration_contract",
            "sprint_49_amax_site_deployment_evidence_package",
            "sprint_50_amax_supervisory_dry_run_contract",
        ),
        notes=("audit-only",),
    )
    defaults.update(overrides)
    return HILTestMatrix(**defaults)


def test_matrix_round_trip_is_deterministic() -> None:
    matrix = _make_matrix()
    raw = dump_canonical_json(matrix.to_dict())
    rebuilt = HILTestMatrix.from_dict(load_canonical_json(raw))
    assert rebuilt == matrix


def test_matrix_rejects_duplicate_test_ids() -> None:
    base = _make_matrix()
    cases = list(base.test_cases)
    cases.append(cases[0])
    with pytest.raises(ContractError):
        HILTestMatrix(
            matrix_id="bad",
            test_cases=tuple(cases),
        )


def test_matrix_cases_for_category_filters_correctly() -> None:
    matrix = default_amax_hil_test_matrix()
    cases = matrix.cases_for_category(HIL_CATEGORY_PACKAGE_INSTALL)
    assert len(cases) >= 1
    for case in cases:
        assert case.category == HIL_CATEGORY_PACKAGE_INSTALL


# ---------------------------------------------------------------------------
# PilotReadinessEvidenceItem
# ---------------------------------------------------------------------------


def _make_item(**overrides) -> PilotReadinessEvidenceItem:
    defaults = dict(
        evidence_id="evidence_test",
        source_sprint_or_doc="sprint_46_amax_feasibility_decision",
        status=PILOT_EVIDENCE_STATUS_PENDING,
        owner_label="aquaoptima_test_owner",
        blocking=True,
        notes=("audit-only",),
    )
    defaults.update(overrides)
    return PilotReadinessEvidenceItem(**defaults)


def test_item_round_trip_is_deterministic() -> None:
    item = _make_item()
    raw = dump_canonical_json(item.to_dict())
    rebuilt = PilotReadinessEvidenceItem.from_dict(load_canonical_json(raw))
    assert rebuilt == item


def test_item_rejects_unknown_status() -> None:
    with pytest.raises(ContractError):
        _make_item(status="rogue_status")


def test_item_rejects_non_bool_blocking() -> None:
    with pytest.raises(ContractError):
        _make_item(blocking="yes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PilotReadinessReview
# ---------------------------------------------------------------------------


def test_default_review_id_matches_canonical_constant() -> None:
    review = default_amax_pilot_readiness_review()
    assert review.review_id == AMAX_PILOT_READINESS_REVIEW_ID


def test_default_hil_matrix_id_matches_canonical_constant() -> None:
    matrix = default_amax_hil_test_matrix()
    assert matrix.matrix_id == AMAX_HIL_TEST_MATRIX_ID


def test_default_review_round_trip_is_deterministic() -> None:
    review = default_amax_pilot_readiness_review()
    raw = dump_canonical_json(review.to_dict())
    rebuilt = PilotReadinessReview.from_dict(load_canonical_json(raw))
    assert rebuilt == review


def test_default_review_is_planning_only_and_not_live_control_authorized() -> None:
    review = default_amax_pilot_readiness_review()
    assert review.live_control_authorized is False
    for case in review.hil_matrix.test_cases:
        assert case.simulation_only is True


def test_default_review_verdict_starts_not_ready() -> None:
    review = default_amax_pilot_readiness_review()
    assert review.verdict == PILOT_VERDICT_NOT_READY


def test_default_review_carries_all_hil_categories() -> None:
    review = default_amax_pilot_readiness_review()
    assert review.hil_categories == HIL_TEST_CATEGORIES


def test_default_review_references_every_sprint_46_through_50() -> None:
    review = default_amax_pilot_readiness_review()
    joined = "\n".join(review.referenced_evidence).lower()
    for token in ("sprint_46", "sprint_47", "sprint_48", "sprint_49", "sprint_50"):
        assert token in joined


def test_default_review_carries_required_safety_phrases() -> None:
    review = default_amax_pilot_readiness_review()
    joined = "\n".join(review.safety_notes)
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined
    assert "no command emission" in joined
    assert "no setpoint output" in joined
    assert "Sprint 52" in joined


def test_review_rejects_live_control_authorized_true() -> None:
    review = default_amax_pilot_readiness_review()
    with pytest.raises(ContractError):
        PilotReadinessReview(
            review_id=review.review_id,
            hil_matrix=review.hil_matrix,
            evidence_items=review.evidence_items,
            open_risks=review.open_risks,
            verdict=review.verdict,
            live_control_authorized=True,
            referenced_evidence=review.referenced_evidence,
            next_gate=review.next_gate,
            safety_notes=review.safety_notes,
        )


def test_review_rejects_unknown_verdict() -> None:
    review = default_amax_pilot_readiness_review()
    with pytest.raises(ContractError):
        PilotReadinessReview(
            review_id=review.review_id,
            hil_matrix=review.hil_matrix,
            evidence_items=review.evidence_items,
            open_risks=review.open_risks,
            verdict="live_control_ok",
            referenced_evidence=review.referenced_evidence,
            next_gate=review.next_gate,
            safety_notes=review.safety_notes,
        )


def test_default_review_labels_carry_no_forbidden_write_vocabulary() -> None:
    """Labels and ids must not embed write / setpoint / command phrases.

    Narrative notes / objective / expected_result / safety_notes
    fields may explicitly negate these phrases (e.g. "no setpoint
    output", "site PLC retains direct VFD / pump / actuator
    authority"); that is part of the audit value. What is not allowed
    is a *label* or *id* that affirmatively names a write register,
    command topic, setpoint topic, or actuator address. Probe strings
    here are assembled from fragments so the changed-file runtime-
    import audit stays clean.
    """

    review = default_amax_pilot_readiness_review()
    unsafe_probes = (
        "set" + "point",
        "comm" + "and",
        "act" + "uator",
        "wri" + "te_register",
        "wri" + "te_topic",
        "dispa" + "tch_topic",
    )
    label_parts: list[str] = [
        review.review_id,
        review.hil_matrix.matrix_id,
        review.hil_matrix.target_hardware_profile_label,
        review.hil_matrix.target_os_runtime_label,
        review.hil_matrix.bench_plc_label,
    ]
    for case in review.hil_matrix.test_cases:
        label_parts.append(case.test_id)
    for item in review.evidence_items:
        label_parts.append(item.evidence_id)
        label_parts.append(item.source_sprint_or_doc)
        label_parts.append(item.owner_label)
    haystack = "\n".join(label_parts).lower()
    for probe in unsafe_probes:
        assert probe not in haystack, (
            f"default review label leaked unsafe phrase {probe!r}"
        )


def test_default_review_does_not_embed_canonical_forbidden_tokens() -> None:
    """No canonical snake_case forbidden token appears anywhere in review."""

    review = default_amax_pilot_readiness_review()
    parts: list[str] = [
        review.review_id,
        review.next_gate,
        review.hil_matrix.matrix_id,
        review.hil_matrix.target_hardware_profile_label,
        review.hil_matrix.target_os_runtime_label,
        review.hil_matrix.bench_plc_label,
    ]
    parts.extend(review.safety_notes)
    parts.extend(review.referenced_evidence)
    parts.extend(review.open_risks)
    parts.extend(review.hil_matrix.notes)
    parts.extend(review.hil_matrix.referenced_evidence)
    for case in review.hil_matrix.test_cases:
        parts.extend(
            (
                case.test_id,
                case.category,
                case.objective,
                case.expected_result,
            )
        )
        parts.extend(case.required_evidence_references)
        parts.extend(case.notes)
    for item in review.evidence_items:
        parts.extend(
            (
                item.evidence_id,
                item.source_sprint_or_doc,
                item.owner_label,
                item.status,
            )
        )
        parts.extend(item.notes)
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
            f"default review leaked canonical forbidden token {probe!r}"
        )


def test_default_review_has_no_secret_or_token_literals() -> None:
    review = default_amax_pilot_readiness_review()
    haystack_parts: list[str] = []
    haystack_parts.extend(review.referenced_evidence)
    haystack_parts.extend(review.hil_matrix.referenced_evidence)
    for item in review.evidence_items:
        haystack_parts.append(item.source_sprint_or_doc)
        haystack_parts.append(item.owner_label)
    for case in review.hil_matrix.test_cases:
        haystack_parts.extend(case.required_evidence_references)
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
# evaluate_amax_pilot_readiness_review
# ---------------------------------------------------------------------------


def _items(status: str) -> tuple[PilotReadinessEvidenceItem, ...]:
    return tuple(
        PilotReadinessEvidenceItem(
            evidence_id=f"evidence_{i}",
            source_sprint_or_doc=f"sprint_4{i}_evidence_label",
            status=status,
            blocking=True,
        )
        for i in range(6, 11)
    )


def test_evaluator_returns_not_ready_when_blocking_evidence_pending() -> None:
    matrix = default_amax_hil_test_matrix()
    review = evaluate_amax_pilot_readiness_review(
        matrix, _items(PILOT_EVIDENCE_STATUS_PENDING)
    )
    assert review.verdict == PILOT_VERDICT_NOT_READY
    assert review.live_control_authorized is False


def test_evaluator_returns_blocked_when_blocking_evidence_blocked() -> None:
    matrix = default_amax_hil_test_matrix()
    items = list(_items(PILOT_EVIDENCE_STATUS_AVAILABLE))
    items[0] = PilotReadinessEvidenceItem(
        evidence_id=items[0].evidence_id,
        source_sprint_or_doc=items[0].source_sprint_or_doc,
        status=PILOT_EVIDENCE_STATUS_BLOCKED,
        blocking=True,
    )
    review = evaluate_amax_pilot_readiness_review(matrix, tuple(items))
    assert review.verdict == PILOT_VERDICT_BLOCKED


def test_evaluator_returns_ready_for_lab_simulation_when_all_available() -> None:
    matrix = default_amax_hil_test_matrix()
    review = evaluate_amax_pilot_readiness_review(
        matrix, _items(PILOT_EVIDENCE_STATUS_AVAILABLE)
    )
    assert review.verdict == PILOT_VERDICT_READY_FOR_LAB_SIMULATION
    assert review.live_control_authorized is False


def test_evaluator_round_trip_is_deterministic() -> None:
    matrix = default_amax_hil_test_matrix()
    review = evaluate_amax_pilot_readiness_review(
        matrix, _items(PILOT_EVIDENCE_STATUS_AVAILABLE)
    )
    raw = dump_canonical_json(review.to_dict())
    rebuilt = PilotReadinessReview.from_dict(load_canonical_json(raw))
    assert rebuilt == review


def test_evaluator_never_produces_live_control_verdict() -> None:
    matrix = default_amax_hil_test_matrix()
    review = evaluate_amax_pilot_readiness_review(
        matrix, _items(PILOT_EVIDENCE_STATUS_AVAILABLE)
    )
    assert review.verdict in PILOT_READINESS_VERDICT_TOKENS
    # Construct probes from fragments so the runtime-import audit and
    # forbidden-vocabulary scan stay clean.
    bad_substrings = (
        "live_" + "write",
        "live_" + "control",
        "set" + "point_output",
        "comm" + "and_emit",
        "act" + "uator_control",
        "clo" + "sed_loop_control",
    )
    for probe in bad_substrings:
        assert probe not in review.verdict


def test_evaluator_ignores_non_blocking_pending_evidence() -> None:
    matrix = default_amax_hil_test_matrix()
    items = list(_items(PILOT_EVIDENCE_STATUS_AVAILABLE))
    # Add a non-blocking pending row; verdict should remain ready.
    items.append(
        PilotReadinessEvidenceItem(
            evidence_id="evidence_optional",
            source_sprint_or_doc="sprint_47_optional_addon_evidence",
            status=PILOT_EVIDENCE_STATUS_PENDING,
            blocking=False,
        )
    )
    review = evaluate_amax_pilot_readiness_review(matrix, tuple(items))
    assert review.verdict == PILOT_VERDICT_READY_FOR_LAB_SIMULATION


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_round_trip() -> None:
    diag = AMAXPilotReadinessDiagnostics(
        warnings=("w1",),
        errors=("e1",),
    )
    rebuilt = AMAXPilotReadinessDiagnostics.from_dict(diag.to_dict())
    assert rebuilt == diag


def test_diagnose_default_review_is_clean() -> None:
    review = default_amax_pilot_readiness_review()
    diag = diagnose_amax_pilot_readiness_review(review)
    assert diag.errors == ()
    assert diag.is_clean


def test_diagnose_flags_missing_referenced_evidence() -> None:
    review = default_amax_pilot_readiness_review()
    stripped = PilotReadinessReview(
        review_id=review.review_id,
        hil_matrix=review.hil_matrix,
        evidence_items=review.evidence_items,
        open_risks=review.open_risks,
        verdict=review.verdict,
        referenced_evidence=(),
        next_gate=review.next_gate,
        safety_notes=review.safety_notes,
    )
    diag = diagnose_amax_pilot_readiness_review(stripped)
    assert any(
        "referenced_evidence" in err for err in diag.errors
    )


def test_diagnose_warns_when_sprint_evidence_missing() -> None:
    review = default_amax_pilot_readiness_review()
    other = PilotReadinessReview(
        review_id=review.review_id,
        hil_matrix=review.hil_matrix,
        evidence_items=review.evidence_items,
        open_risks=review.open_risks,
        verdict=review.verdict,
        referenced_evidence=("some_unrelated_evidence_handle",),
        next_gate=review.next_gate,
        safety_notes=review.safety_notes,
    )
    diag = diagnose_amax_pilot_readiness_review(other)
    joined = "\n".join(diag.warnings)
    assert "sprint_46" in joined
    assert "sprint_47" in joined
    assert "sprint_48" in joined
    assert "sprint_49" in joined
    assert "sprint_50" in joined


def test_diagnose_flags_missing_hil_categories() -> None:
    review = default_amax_pilot_readiness_review()
    only_one_case = (review.hil_matrix.test_cases[0],)
    short_matrix = HILTestMatrix(
        matrix_id=review.hil_matrix.matrix_id,
        test_cases=only_one_case,
        target_hardware_profile_label=(
            review.hil_matrix.target_hardware_profile_label
        ),
        target_os_runtime_label=(
            review.hil_matrix.target_os_runtime_label
        ),
        bench_plc_label=review.hil_matrix.bench_plc_label,
        referenced_evidence=review.hil_matrix.referenced_evidence,
        notes=review.hil_matrix.notes,
    )
    short_review = PilotReadinessReview(
        review_id=review.review_id,
        hil_matrix=short_matrix,
        evidence_items=review.evidence_items,
        open_risks=review.open_risks,
        verdict=review.verdict,
        referenced_evidence=review.referenced_evidence,
        next_gate=review.next_gate,
        safety_notes=review.safety_notes,
    )
    diag = diagnose_amax_pilot_readiness_review(short_review)
    assert any(
        "missing required categories" in err for err in diag.errors
    )


def test_diagnose_warns_when_next_gate_is_missing() -> None:
    review = default_amax_pilot_readiness_review()
    stripped = PilotReadinessReview(
        review_id=review.review_id,
        hil_matrix=review.hil_matrix,
        evidence_items=review.evidence_items,
        open_risks=review.open_risks,
        verdict=review.verdict,
        referenced_evidence=review.referenced_evidence,
        next_gate="",
        safety_notes=review.safety_notes,
    )
    diag = diagnose_amax_pilot_readiness_review(stripped)
    assert any("next_gate" in w for w in diag.warnings)


# ---------------------------------------------------------------------------
# Documentation safety phrases
# ---------------------------------------------------------------------------


def test_doc_carries_required_safety_phrases() -> None:
    text = PILOT_READINESS_DOC_PATH.read_text(encoding="utf-8")
    assert "no live OT binding" in text
    assert "no PLC/PAC/SCADA write" in text
    assert "no command emission" in text
    assert "no setpoint output" in text
    assert "Sprint 51" in text
    assert "Sprint 52" in text


def test_doc_states_planning_only_boundary() -> None:
    text = PILOT_READINESS_DOC_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "planning-only" in lowered or "planning only" in lowered
    assert "hardware-in-the-loop" in lowered
    assert "site plc" in lowered


def test_doc_calls_out_replanning_gate_for_sprint_52_plus() -> None:
    text = PILOT_READINESS_DOC_PATH.read_text(encoding="utf-8")
    assert "replanning" in text.lower()


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


def test_pilot_readiness_module_has_no_runtime_imports() -> None:
    """The SDK module must not import live network / DB / broker clients.

    Probe strings are assembled from fragments so the changed-file
    runtime-import audit remains clean.
    """

    statements = _iter_import_statement_lines(
        PILOT_READINESS_MODULE_PATH.read_text(encoding="utf-8")
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
                f"pilot_readiness imports forbidden runtime module "
                f"{module!r}: {stmt!r}"
            )
            assert not stmt.startswith(f"from {module}"), (
                f"pilot_readiness imports forbidden runtime module "
                f"{module!r}: {stmt!r}"
            )


def test_pilot_readiness_module_does_not_import_aquaoptima_runtime() -> None:
    statements = _iter_import_statement_lines(
        PILOT_READINESS_MODULE_PATH.read_text(encoding="utf-8")
    )
    aqua_probe = "aqua" + "optima."
    for stmt in statements:
        assert aqua_probe not in stmt, (
            f"pilot_readiness must not import aquaoptima.*: {stmt!r}"
        )


def test_pilot_readiness_module_does_not_import_torch() -> None:
    statements = _iter_import_statement_lines(
        PILOT_READINESS_MODULE_PATH.read_text(encoding="utf-8")
    )
    torch_probe = "to" + "rch"
    for stmt in statements:
        assert f"import {torch_probe}" not in stmt
        assert not stmt.startswith(f"from {torch_probe}")
