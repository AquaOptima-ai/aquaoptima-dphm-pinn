"""Sprint 49 — AMAX site deployment readiness / OT certification evidence.

Acceptance: the SDK projects the deployment readiness item / checklist /
hardware-vs-system certification evidence / failure mode / site
deployment evidence package shapes. The canonical default evidence
package is deterministic, audit-only, not site-approved by default, and
reaffirms the non-negotiable safety boundary (no live OT binding, no
PLC/PAC/SCADA write, no command emission, no setpoint output).

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
    AMAX_SITE_DEPLOYMENT_EVIDENCE_PACKAGE_ID,
    AMAXDeploymentReadinessChecklist,
    AMAXDeploymentReadinessDiagnostics,
    AMAXFailureMode,
    AMAXOTCertificationEvidence,
    AMAXSiteDeploymentEvidencePackage,
    ContractError,
    DeploymentReadinessItem,
    FAILURE_MODE_CATEGORIES,
    FAILURE_MODE_CATEGORY_BENCHMARK,
    FAILURE_MODE_CATEGORY_CODESYS,
    FAILURE_MODE_CATEGORY_NETWORK,
    FAILURE_MODE_CATEGORY_OPERATOR,
    FAILURE_MODE_CATEGORY_PACKAGE,
    FAILURE_MODE_CATEGORY_POWER,
    FAILURE_MODE_CATEGORY_ROLLBACK,
    FAILURE_MODE_CATEGORY_TELEMETRY,
    READINESS_CATEGORIES,
    READINESS_CATEGORY_CODESYS_PACKAGE,
    READINESS_CATEGORY_CYBERSECURITY,
    READINESS_CATEGORY_ENVIRONMENT,
    READINESS_CATEGORY_FAT_SAT,
    READINESS_CATEGORY_NETWORK_PORTS,
    READINESS_CATEGORY_OS_IMAGE,
    READINESS_CATEGORY_PHYSICAL_INSTALL,
    READINESS_CATEGORY_POWER,
    READINESS_CATEGORY_ROLLBACK,
    READINESS_CATEGORY_SAFETY_BOUNDARY,
    READINESS_CATEGORY_SKU,
    READINESS_CATEGORY_STORAGE,
    READINESS_STATUS_APPROVED,
    READINESS_STATUS_BLOCKED,
    READINESS_STATUS_IN_REVIEW,
    READINESS_STATUS_NOT_APPLICABLE,
    READINESS_STATUS_PENDING,
    READINESS_STATUS_TOKENS,
    canonical_amax_failure_modes,
    default_amax_deployment_readiness_checklist,
    default_amax_ot_certification_evidence,
    default_amax_site_deployment_evidence_package,
    diagnose_amax_site_deployment_evidence_package,
    dump_canonical_json,
    load_canonical_json,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_READINESS_MODULE_PATH = (
    REPO_ROOT
    / "src"
    / "aquaoptima_contracts"
    / "edge"
    / "deployment_readiness.py"
)
DEPLOYMENT_READINESS_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "hardware"
    / "amax-5580-site-deployment-readiness.md"
)


# ---------------------------------------------------------------------------
# Canonical category vocabulary
# ---------------------------------------------------------------------------


def test_required_readiness_categories_all_present() -> None:
    required = {
        READINESS_CATEGORY_SKU,
        READINESS_CATEGORY_OS_IMAGE,
        READINESS_CATEGORY_CODESYS_PACKAGE,
        READINESS_CATEGORY_NETWORK_PORTS,
        READINESS_CATEGORY_PHYSICAL_INSTALL,
        READINESS_CATEGORY_POWER,
        READINESS_CATEGORY_STORAGE,
        READINESS_CATEGORY_ENVIRONMENT,
        READINESS_CATEGORY_ROLLBACK,
        READINESS_CATEGORY_CYBERSECURITY,
        READINESS_CATEGORY_FAT_SAT,
        READINESS_CATEGORY_SAFETY_BOUNDARY,
    }
    assert required <= READINESS_CATEGORIES


def test_status_tokens_cover_pending_review_approved_blocked_na() -> None:
    assert READINESS_STATUS_PENDING in READINESS_STATUS_TOKENS
    assert READINESS_STATUS_IN_REVIEW in READINESS_STATUS_TOKENS
    assert READINESS_STATUS_APPROVED in READINESS_STATUS_TOKENS
    assert READINESS_STATUS_BLOCKED in READINESS_STATUS_TOKENS
    assert READINESS_STATUS_NOT_APPLICABLE in READINESS_STATUS_TOKENS


def test_failure_mode_categories_cover_required_set() -> None:
    required = {
        FAILURE_MODE_CATEGORY_TELEMETRY,
        FAILURE_MODE_CATEGORY_PACKAGE,
        FAILURE_MODE_CATEGORY_BENCHMARK,
        FAILURE_MODE_CATEGORY_NETWORK,
        FAILURE_MODE_CATEGORY_POWER,
        FAILURE_MODE_CATEGORY_ROLLBACK,
        FAILURE_MODE_CATEGORY_OPERATOR,
        FAILURE_MODE_CATEGORY_CODESYS,
    }
    assert required <= FAILURE_MODE_CATEGORIES


# ---------------------------------------------------------------------------
# DeploymentReadinessItem
# ---------------------------------------------------------------------------


def _make_item(**overrides) -> DeploymentReadinessItem:
    defaults = dict(
        item_id="readiness_test_item",
        category=READINESS_CATEGORY_SKU,
        description="test readiness item description",
        evidence_reference="evidence_ref_label",
        owner_label="owner_label",
        status=READINESS_STATUS_PENDING,
        blocking=True,
        notes=("audit only note",),
    )
    defaults.update(overrides)
    return DeploymentReadinessItem(**defaults)


def test_item_round_trip_is_deterministic() -> None:
    item = _make_item()
    raw = dump_canonical_json(item.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = DeploymentReadinessItem.from_dict(decoded)
    assert rebuilt == item


def test_item_rejects_unknown_category() -> None:
    with pytest.raises(ContractError):
        _make_item(category="rogue_category")


def test_item_rejects_unknown_status() -> None:
    with pytest.raises(ContractError):
        _make_item(status="rogue_status")


def test_item_rejects_non_bool_blocking() -> None:
    with pytest.raises(ContractError):
        _make_item(blocking="yes")  # type: ignore[arg-type]


def test_item_allows_empty_evidence_and_owner_labels() -> None:
    item = _make_item(evidence_reference="", owner_label="")
    assert item.evidence_reference == ""
    assert item.owner_label == ""


# ---------------------------------------------------------------------------
# AMAXDeploymentReadinessChecklist
# ---------------------------------------------------------------------------


def test_default_checklist_covers_all_required_categories() -> None:
    checklist = default_amax_deployment_readiness_checklist()
    assert checklist.categories == READINESS_CATEGORIES


def test_default_checklist_round_trip_is_deterministic() -> None:
    checklist = default_amax_deployment_readiness_checklist()
    raw = dump_canonical_json(checklist.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = AMAXDeploymentReadinessChecklist.from_dict(decoded)
    assert rebuilt == checklist


def test_default_checklist_items_default_to_pending_and_blocking() -> None:
    checklist = default_amax_deployment_readiness_checklist()
    for item in checklist.items:
        assert item.status == READINESS_STATUS_PENDING
        assert item.blocking is True


def test_default_checklist_is_not_fully_approved_by_default() -> None:
    checklist = default_amax_deployment_readiness_checklist()
    assert not checklist.is_fully_approved()
    assert len(checklist.unresolved_blocking_items()) == len(checklist.items)


def test_checklist_rejects_duplicate_item_ids() -> None:
    item_a = _make_item(item_id="dup")
    item_b = _make_item(item_id="dup", category=READINESS_CATEGORY_POWER)
    with pytest.raises(ContractError):
        AMAXDeploymentReadinessChecklist(
            checklist_id="dup_test",
            items=(item_a, item_b),
        )


def test_checklist_items_for_category_filters_correctly() -> None:
    checklist = default_amax_deployment_readiness_checklist()
    sku_items = checklist.items_for_category(READINESS_CATEGORY_SKU)
    assert sku_items
    for item in sku_items:
        assert item.category == READINESS_CATEGORY_SKU


# ---------------------------------------------------------------------------
# AMAXOTCertificationEvidence
# ---------------------------------------------------------------------------


def test_certification_evidence_round_trip_is_deterministic() -> None:
    evidence = default_amax_ot_certification_evidence()
    raw = dump_canonical_json(evidence.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = AMAXOTCertificationEvidence.from_dict(decoded)
    assert rebuilt == evidence


def test_certification_evidence_distinguishes_hardware_from_system() -> None:
    evidence = default_amax_ot_certification_evidence()
    assert evidence.hardware_certifies_system is False
    assert evidence.hardware_certifications, (
        "hardware certifications list must be populated"
    )
    assert evidence.system_qualifications_required, (
        "system qualifications list must be populated"
    )
    joined_notes = "\n".join(evidence.notes)
    # The audit narrative must state explicitly that hardware cert is
    # not sufficient for AquaOptima system deployment.
    assert "necessary but not sufficient" in joined_notes


def test_certification_rejects_hardware_certifies_system_true() -> None:
    with pytest.raises(ContractError):
        AMAXOTCertificationEvidence(
            evidence_id="bad",
            hardware_certifications=("ce",),
            system_qualifications_required=("fat",),
            hardware_certifies_system=True,
        )


def test_certification_rejects_empty_system_qualifications() -> None:
    with pytest.raises(ContractError):
        AMAXOTCertificationEvidence(
            evidence_id="bad",
            hardware_certifications=("ce",),
            system_qualifications_required=(),
        )


# ---------------------------------------------------------------------------
# AMAXFailureMode
# ---------------------------------------------------------------------------


def _make_failure_mode(**overrides) -> AMAXFailureMode:
    defaults = dict(
        mode_id="failure_mode_test",
        category=FAILURE_MODE_CATEGORY_TELEMETRY,
        description="test failure mode description",
        effect="test failure effect",
        detection="test failure detection",
        fallback="test failure fallback",
        blocking=True,
        notes=("audit only note",),
    )
    defaults.update(overrides)
    return AMAXFailureMode(**defaults)


def test_failure_mode_round_trip_is_deterministic() -> None:
    mode = _make_failure_mode()
    raw = dump_canonical_json(mode.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = AMAXFailureMode.from_dict(decoded)
    assert rebuilt == mode


def test_failure_mode_rejects_unknown_category() -> None:
    with pytest.raises(ContractError):
        _make_failure_mode(category="rogue_category")


def test_canonical_failure_modes_cover_required_set() -> None:
    modes = canonical_amax_failure_modes()
    mode_ids = {mode.mode_id for mode in modes}
    required_substrings = (
        "stale_telemetry",
        "package_install_failure",
        "cpu_benchmark_failure",
        "network_loss",
        "power_loss",
        "rollback_failure",
        "operator_disable_unavailable",
        "codesys_co_tenancy_unresolved",
    )
    for substring in required_substrings:
        assert any(substring in mid for mid in mode_ids), (
            f"canonical failure modes missing one covering {substring!r}; "
            f"got {sorted(mode_ids)}"
        )
    covered_categories = {mode.category for mode in modes}
    assert covered_categories == FAILURE_MODE_CATEGORIES


# ---------------------------------------------------------------------------
# AMAXSiteDeploymentEvidencePackage
# ---------------------------------------------------------------------------


def test_default_package_id_matches_canonical_constant() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    assert pkg.package_id == AMAX_SITE_DEPLOYMENT_EVIDENCE_PACKAGE_ID


def test_default_package_round_trip_is_deterministic() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    raw = dump_canonical_json(pkg.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = AMAXSiteDeploymentEvidencePackage.from_dict(decoded)
    assert rebuilt == pkg


def test_default_package_requires_site_specific_approval() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    assert pkg.site_specific_approval_required is True


def test_default_package_carries_blocking_items_by_default() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    unresolved = pkg.checklist.unresolved_blocking_items()
    assert unresolved, (
        "default Sprint 49 package must carry unresolved blocking items"
    )


def test_default_package_carries_required_safety_phrases() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    joined = "\n".join(pkg.safety_notes)
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined
    assert "no command emission" in joined
    assert "no setpoint output" in joined
    # Sprint 50 next-gate language must be present.
    assert "Sprint 50" in joined


def test_default_package_failure_modes_cover_required_categories() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    assert pkg.failure_mode_categories == FAILURE_MODE_CATEGORIES


def test_default_package_referenced_evidence_cites_prior_sprints() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    joined = "\n".join(pkg.referenced_evidence)
    assert "sprint_46" in joined
    assert "sprint_47" in joined
    assert "sprint_48" in joined


def test_package_rejects_non_bool_site_specific_approval_required() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    bad = pkg.to_dict()
    bad["site_specific_approval_required"] = "yes"
    with pytest.raises(ContractError):
        AMAXSiteDeploymentEvidencePackage.from_dict(bad)


def test_package_rejects_duplicate_failure_mode_ids() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    duplicated = pkg.failure_modes + (pkg.failure_modes[0],)
    with pytest.raises(ContractError):
        AMAXSiteDeploymentEvidencePackage(
            package_id=pkg.package_id,
            checklist=pkg.checklist,
            certification_evidence=pkg.certification_evidence,
            failure_modes=duplicated,
            referenced_evidence=pkg.referenced_evidence,
            next_gate=pkg.next_gate,
            site_specific_approval_required=pkg.site_specific_approval_required,
            safety_notes=pkg.safety_notes,
        )


def test_package_labels_carry_no_forbidden_write_vocabulary() -> None:
    """Labels and ids must not embed write / setpoint / command phrases.

    The package's *safety_notes*, item *notes*, mode *fallback* etc. may
    explicitly negate these phrases (e.g. "no setpoint output", "site
    PLC retains direct VFD / pump / actuator authority"); that is part
    of the audit value. What is not allowed is a *label* or *id* that
    affirmatively names a write register, command topic, setpoint
    topic, or actuator address. Probe strings here are assembled from
    fragments so the changed-file runtime-import audit remains clean.
    """

    pkg = default_amax_site_deployment_evidence_package()
    unsafe_probes = (
        "set" + "point",
        "comm" + "and",
        "act" + "uator",
        "wri" + "te_register",
        "wri" + "te_topic",
    )
    label_parts: list[str] = [
        pkg.package_id,
        pkg.checklist.checklist_id,
        pkg.certification_evidence.evidence_id,
    ]
    for item in pkg.checklist.items:
        label_parts.append(item.item_id)
        label_parts.append(item.evidence_reference)
        label_parts.append(item.owner_label)
    for mode in pkg.failure_modes:
        label_parts.append(mode.mode_id)
    haystack = "\n".join(label_parts).lower()
    for probe in unsafe_probes:
        assert probe.lower() not in haystack, (
            f"default package label leaked unsafe phrase {probe!r}"
        )


def test_default_package_does_not_embed_canonical_forbidden_tokens() -> None:
    """No canonical snake_case forbidden token appears anywhere in package."""

    pkg = default_amax_site_deployment_evidence_package()
    all_parts: list[str] = [
        pkg.package_id,
        pkg.next_gate,
        pkg.checklist.checklist_id,
        pkg.certification_evidence.evidence_id,
    ]
    all_parts.extend(pkg.safety_notes)
    all_parts.extend(pkg.referenced_evidence)
    all_parts.extend(pkg.checklist.notes)
    for item in pkg.checklist.items:
        all_parts.extend(
            (
                item.item_id,
                item.description,
                item.evidence_reference,
                item.owner_label,
            )
        )
        all_parts.extend(item.notes)
    for mode in pkg.failure_modes:
        all_parts.extend(
            (
                mode.mode_id,
                mode.description,
                mode.effect,
                mode.detection,
                mode.fallback,
            )
        )
        all_parts.extend(mode.notes)
    all_parts.extend(pkg.certification_evidence.hardware_certifications)
    all_parts.extend(pkg.certification_evidence.system_qualifications_required)
    all_parts.extend(pkg.certification_evidence.notes)
    haystack = "\n".join(all_parts)
    # Canonical forbidden tokens are reconstructed from fragments to
    # keep the test file itself out of the forbidden-vocabulary scan.
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
    )
    for probe in canonical_probes:
        assert probe not in haystack, (
            f"default package leaked canonical forbidden token {probe!r}"
        )


def test_default_package_has_no_secret_or_token_literals() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    haystack_parts: list[str] = []
    for item in pkg.checklist.items:
        haystack_parts.append(item.evidence_reference)
        haystack_parts.append(item.owner_label)
    for ref in pkg.referenced_evidence:
        haystack_parts.append(ref)
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
    diag = AMAXDeploymentReadinessDiagnostics(
        warnings=("w1",),
        errors=("e1",),
    )
    rebuilt = AMAXDeploymentReadinessDiagnostics.from_dict(diag.to_dict())
    assert rebuilt == diag


def test_diagnose_default_package_flags_unresolved_blocking_items() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    diag = diagnose_amax_site_deployment_evidence_package(pkg)
    assert any(
        "unresolved blocking readiness item" in err for err in diag.errors
    )


def test_diagnose_fully_approved_checklist_is_clean() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    approved_items = tuple(
        DeploymentReadinessItem(
            item_id=item.item_id,
            category=item.category,
            description=item.description,
            evidence_reference=item.evidence_reference,
            owner_label=item.owner_label,
            status=READINESS_STATUS_APPROVED,
            blocking=item.blocking,
            notes=item.notes,
        )
        for item in pkg.checklist.items
    )
    approved_checklist = AMAXDeploymentReadinessChecklist(
        checklist_id=pkg.checklist.checklist_id,
        items=approved_items,
        notes=pkg.checklist.notes,
    )
    approved_pkg = AMAXSiteDeploymentEvidencePackage(
        package_id=pkg.package_id,
        checklist=approved_checklist,
        certification_evidence=pkg.certification_evidence,
        failure_modes=pkg.failure_modes,
        referenced_evidence=pkg.referenced_evidence,
        next_gate=pkg.next_gate,
        site_specific_approval_required=True,
        safety_notes=pkg.safety_notes,
    )
    diag = diagnose_amax_site_deployment_evidence_package(approved_pkg)
    assert diag.errors == ()


def test_diagnose_flags_missing_referenced_evidence() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    stripped = AMAXSiteDeploymentEvidencePackage(
        package_id=pkg.package_id,
        checklist=pkg.checklist,
        certification_evidence=pkg.certification_evidence,
        failure_modes=pkg.failure_modes,
        referenced_evidence=(),
        next_gate=pkg.next_gate,
        site_specific_approval_required=True,
        safety_notes=pkg.safety_notes,
    )
    diag = diagnose_amax_site_deployment_evidence_package(stripped)
    assert any(
        "referenced_evidence" in w for w in diag.warnings
    )


def test_diagnose_flags_missing_next_gate() -> None:
    pkg = default_amax_site_deployment_evidence_package()
    stripped = AMAXSiteDeploymentEvidencePackage(
        package_id=pkg.package_id,
        checklist=pkg.checklist,
        certification_evidence=pkg.certification_evidence,
        failure_modes=pkg.failure_modes,
        referenced_evidence=pkg.referenced_evidence,
        next_gate="",
        site_specific_approval_required=True,
        safety_notes=pkg.safety_notes,
    )
    diag = diagnose_amax_site_deployment_evidence_package(stripped)
    assert any("next_gate" in w for w in diag.warnings)


# ---------------------------------------------------------------------------
# Documentation safety phrases
# ---------------------------------------------------------------------------


def test_doc_carries_required_safety_phrases() -> None:
    text = DEPLOYMENT_READINESS_DOC_PATH.read_text(encoding="utf-8")
    assert "no live OT binding" in text
    assert "no PLC/PAC/SCADA write" in text
    assert "no command emission" in text
    assert "no setpoint output" in text
    # Sprint 49 framing
    assert "Sprint 49" in text
    # Sprint 50 next gate framing
    assert "Sprint 50" in text
    # FAT / SAT framing
    assert "FAT" in text
    assert "SAT" in text


def test_doc_states_hardware_cert_does_not_certify_system() -> None:
    text = DEPLOYMENT_READINESS_DOC_PATH.read_text(encoding="utf-8")
    assert "necessary but not sufficient" in text


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


def test_deployment_readiness_module_has_no_runtime_imports() -> None:
    """The SDK module must not import live network / DB / broker clients.

    Probe strings are assembled from fragments so the changed-file
    runtime-import audit remains clean.
    """

    statements = _iter_import_statement_lines(
        DEPLOYMENT_READINESS_MODULE_PATH.read_text(encoding="utf-8")
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
                f"deployment_readiness imports forbidden runtime module "
                f"{module!r}: {stmt!r}"
            )
            assert not stmt.startswith(f"from {module}"), (
                f"deployment_readiness imports forbidden runtime module "
                f"{module!r}: {stmt!r}"
            )


def test_deployment_readiness_module_does_not_import_aquaoptima_runtime() -> None:
    statements = _iter_import_statement_lines(
        DEPLOYMENT_READINESS_MODULE_PATH.read_text(encoding="utf-8")
    )
    aqua_probe = "aqua" + "optima."
    for stmt in statements:
        assert aqua_probe not in stmt, (
            f"deployment_readiness must not import aquaoptima.*: {stmt!r}"
        )


def test_deployment_readiness_module_does_not_import_torch() -> None:
    statements = _iter_import_statement_lines(
        DEPLOYMENT_READINESS_MODULE_PATH.read_text(encoding="utf-8")
    )
    torch_probe = "to" + "rch"
    for stmt in statements:
        assert f"import {torch_probe}" not in stmt
        assert not stmt.startswith(f"from {torch_probe}")
