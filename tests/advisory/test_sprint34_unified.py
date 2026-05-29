"""AOPSO Sprint 34 -- Unified A+B offline evidence package tests.

These tests pin the safety / honesty contract of the Sprint 34 unified
package: both pillars' verdicts are reflected honestly, the safety banner
appears on every surface, the dashboard is read-only, the modeling-source
governance scan is clean, the artifact manifest conforms to the contracts
SDK, and the cannot-claim section is preserved verbatim on every report.

These tests build the package IN MEMORY from the real pillar scorecards in
``data/eval/pillarA/`` and ``data/eval/pillarB/``. They do NOT depend on
the writer; they reuse the same builder the writer uses.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from aquaoptima_contracts import ModelArtifactRecord
from aquaoptima_contracts.safety.flags import default_safety_flag_set

from aquaoptima.advisory.governance import (
    FORBIDDEN_CONNECTOR_TOKENS,
    FORBIDDEN_IMPORT_PATTERNS,
    scan_modeling_source_for_governance_violations,
)
from aquaoptima.advisory.sprint34_unified_package import (
    ALLOWED_PILLAR_B_LANGUAGE,
    CANNOT_CLAIM_STATEMENTS,
    DEFAULT_PILLAR_A_SCORECARD,
    DEFAULT_PILLAR_B_SCORECARD,
    PACKAGING_BLOCKS,
    REPORT_VERSION,
    SAFETY_BANNER,
    SPRINT,
    UnifiedPackage,
    build_artifact_manifest_records,
    build_efficiency_advisory_export,
    build_health_event_export,
    build_unified_package,
    write_unified_package,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parents[2]
PILLAR_A = REPO_ROOT / DEFAULT_PILLAR_A_SCORECARD
PILLAR_B = REPO_ROOT / DEFAULT_PILLAR_B_SCORECARD


@pytest.fixture(scope="module")
def unified_package() -> UnifiedPackage:
    assert PILLAR_A.is_file(), f"missing pillar A scorecard {PILLAR_A}"
    assert PILLAR_B.is_file(), f"missing pillar B scorecard {PILLAR_B}"
    return build_unified_package(
        repo_root=REPO_ROOT,
        pillar_a_scorecard_path=PILLAR_A,
        pillar_b_scorecard_path=PILLAR_B,
        generated_at_utc="2026-05-29T00:00:00Z",
    )


# --------------------------------------------------------------------------- #
# Scorecard surface tests
# --------------------------------------------------------------------------- #
def test_scorecard_contains_both_verdicts(unified_package: UnifiedPackage) -> None:
    sc = unified_package.scorecard
    assert sc["sprint"] == SPRINT
    assert sc["report_version"] == REPORT_VERSION
    assert "pillar_a_verdict" in sc
    assert "pillar_b_verdict" in sc
    # Both verdicts must be the canonical strings PASS/FAIL (or UNKNOWN)
    assert sc["pillar_a_verdict"] in {"PASS", "FAIL", "UNKNOWN"}
    assert sc["pillar_b_verdict"] in {"PASS", "FAIL", "UNKNOWN"}


def test_scorecard_pillar_a_is_pass_per_sprint30b(unified_package: UnifiedPackage) -> None:
    # Sprint 30b's locked-March holdout under gate v2 was PASS.
    assert unified_package.scorecard["pillar_a_verdict"] == "PASS"


def test_scorecard_pillar_b_is_fail_per_sprint33(unified_package: UnifiedPackage) -> None:
    # Sprint 33's locked-March eval was FAIL (positive_opportunity_robust
    # criterion failed because p25 kWh was 0.0). The unified package must
    # report this honestly.
    assert unified_package.scorecard["pillar_b_verdict"] == "FAIL"


def test_product_status_reflects_both_verdicts_honestly(
    unified_package: UnifiedPackage,
) -> None:
    sc = unified_package.scorecard
    status = sc["product_status"]
    assert isinstance(status, str)
    # Must mention BOTH pillars; must not imply deployment readiness.
    assert "Pillar A" in status
    assert "Pillar B" in status
    assert "deployment NOT authorized" in status
    assert "FAILED" in status  # because Pillar B failed honestly


def test_scorecard_safety_flags(unified_package: UnifiedPackage) -> None:
    sc = unified_package.scorecard
    assert sc["advisory_only"] is True
    assert sc["evaluation_mode"] == "offline_only"
    assert sc["site_integration_allowed"] is False
    assert sc["influences_control"] is False
    assert sc["is_evidence_not_setpoint"] is True


# --------------------------------------------------------------------------- #
# Safety banner appears on every surface
# --------------------------------------------------------------------------- #
def _every_surface(pkg: UnifiedPackage) -> list[tuple[str, str]]:
    """All textual surfaces produced by the package."""
    return [
        ("scorecard_json", json.dumps(pkg.scorecard, default=str)),
        ("dashboard_html", pkg.dashboard_html),
        ("executive_report_md", pkg.executive_report_md),
        ("ml_audit_md", pkg.ml_audit_md),
        ("plant_manager_summary_md", pkg.plant_manager_summary_md),
        ("health_event_csv", pkg.health_event_csv),
        ("efficiency_advisory_csv", pkg.efficiency_advisory_csv),
        ("health_event_export_json", json.dumps(pkg.health_event_export, default=str)),
        (
            "efficiency_advisory_export_json",
            json.dumps(pkg.efficiency_advisory_export, default=str),
        ),
        ("artifact_manifest_json", json.dumps(pkg.artifact_manifest, default=str)),
    ]


def test_safety_banner_present_on_every_surface(unified_package: UnifiedPackage) -> None:
    for name, text in _every_surface(unified_package):
        assert SAFETY_BANNER in text, f"safety banner missing from surface {name!r}"


def test_safety_banner_exact_string_is_pinned() -> None:
    # If you change the banner, you change the product's safety posture.
    # This test pins the exact string so any change is intentional.
    assert SAFETY_BANNER == (
        "ADVISORY-ONLY OFFLINE EVIDENCE - NOT FOR ACTUATION OR CONTROL - "
        "NO LIVE SITE INTEGRATION - SITE DEPLOYMENT NOT AUTHORIZED IN THIS VERSION"
    )


# --------------------------------------------------------------------------- #
# Cannot-claim block is verbatim on every prose report
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("surface_name", [
    "executive_report_md", "ml_audit_md", "plant_manager_summary_md",
    "dashboard_html",
])
def test_every_prose_surface_contains_every_cannot_claim_statement(
    surface_name: str, unified_package: UnifiedPackage,
) -> None:
    surface = getattr(unified_package, surface_name)
    for claim in CANNOT_CLAIM_STATEMENTS:
        assert claim in surface, (
            f"cannot-claim statement {claim!r} missing from {surface_name}"
        )


def test_cannot_claim_statements_are_negative_and_non_empty() -> None:
    assert CANNOT_CLAIM_STATEMENTS, "must have at least one cannot-claim statement"
    for claim in CANNOT_CLAIM_STATEMENTS:
        assert "do NOT claim" in claim or "do not claim" in claim.lower()


# --------------------------------------------------------------------------- #
# Dashboard HTML has NO controls that set anything
# --------------------------------------------------------------------------- #
FORBIDDEN_HTML_TAGS_OR_ATTRS = (
    "<form", "<input", "<button", "<textarea", "<select",
    "method=\"post\"", "method='post'", "method=post",
    "onclick=", "onsubmit=", "onchange=", "onload=", "onerror=",
    "fetch(", "xmlhttprequest", "websocket",
    "<script",
)


@pytest.mark.parametrize("token", FORBIDDEN_HTML_TAGS_OR_ATTRS)
def test_dashboard_has_no_forbidden_html_token(
    token: str, unified_package: UnifiedPackage,
) -> None:
    assert token not in unified_package.dashboard_html.lower(), (
        f"dashboard contains forbidden token {token!r}: would imply a UI control "
        "that sets state, posts a value, or fetches dynamic state"
    )


def test_dashboard_has_persistent_banner_in_every_section(
    unified_package: UnifiedPackage,
) -> None:
    # We render the safety banner at top-of-page and again inside every <section>.
    n_banner = unified_package.dashboard_html.count(SAFETY_BANNER)
    # At minimum the header + 4 sections = 5 occurrences.
    assert n_banner >= 5, f"banner appears only {n_banner} times; expected >= 5"


# --------------------------------------------------------------------------- #
# Governance scan over the package source
# --------------------------------------------------------------------------- #
def test_governance_scan_over_modeling_source_is_clean(
    unified_package: UnifiedPackage,
) -> None:
    governance = unified_package.governance
    assert governance.clean, (
        f"governance scan found violations: {list(governance.violations)}"
    )
    assert governance.files_scanned > 0
    assert governance.safety_status == "PASS"


def test_governance_scan_sees_sprint34_module() -> None:
    # The Sprint 34 module itself must be in the scan and remain clean.
    result = scan_modeling_source_for_governance_violations(
        [REPO_ROOT / "src" / "aquaoptima" / "advisory"]
    )
    sprint34_seen = (
        REPO_ROOT / "src" / "aquaoptima" / "advisory" / "sprint34_unified_package.py"
    ).is_file()
    assert sprint34_seen, "sprint34_unified_package.py missing from src tree"
    assert result.clean, f"sprint34 module triggered governance: {result.violations}"


def test_no_forbidden_edge_imports_anywhere_in_advisory_tree() -> None:
    advisory_root = REPO_ROOT / "src" / "aquaoptima" / "advisory"
    for py in advisory_root.rglob("*.py"):
        if py.name == "governance.py":
            continue  # defines the patterns
        text = py.read_text(encoding="utf-8", errors="ignore")
        for pat in FORBIDDEN_IMPORT_PATTERNS:
            assert pat.search(text) is None, (
                f"{py} contains forbidden edge import"
            )


def test_no_forbidden_connector_tokens_in_sprint34_module() -> None:
    sprint34 = (
        REPO_ROOT / "src" / "aquaoptima" / "advisory" / "sprint34_unified_package.py"
    )
    text = sprint34.read_text(encoding="utf-8")
    low = text.lower()
    for tok in FORBIDDEN_CONNECTOR_TOKENS:
        assert re.search(rf"\b{re.escape(tok)}\b", low) is None, (
            f"sprint34 module contains forbidden connector token {tok!r}"
        )


# --------------------------------------------------------------------------- #
# Artifact manifest conformance to the contracts SDK
# --------------------------------------------------------------------------- #
def test_artifact_manifest_has_two_records(unified_package: UnifiedPackage) -> None:
    records = unified_package.artifact_manifest["records"]
    assert len(records) == 2
    pillars = sorted(r["summary"]["pillar"] for r in records)
    assert pillars == ["A_health", "B_efficiency"]


def test_artifact_manifest_each_record_is_a_model_artifact_record() -> None:
    # Construct the records (this is what the manifest builder does) and
    # round-trip them through ModelArtifactRecord.from_dict to confirm the
    # contracts SDK accepts them as a conformant record. The SDK does the
    # all-True safety flag enforcement and forbidden-vocabulary scan.
    records = build_artifact_manifest_records(
        repo_root=REPO_ROOT,
        pillar_a_scorecard_path=PILLAR_A,
        pillar_b_scorecard_path=PILLAR_B,
        pillar_a_verdict="PASS",
        pillar_b_verdict="FAIL",
    )
    canonical = default_safety_flag_set()
    for rec in records:
        assert isinstance(rec, ModelArtifactRecord)
        assert rec.safety_flag_set == canonical
        # Round-trip via to_dict / from_dict.
        d = rec.to_dict()
        rebuilt = ModelArtifactRecord.from_dict(d)
        assert rebuilt.safety_flag_set == canonical
        # Every safety flag must be True.
        for flag, value in rebuilt.safety_flag_set.to_dict().items():
            assert value is True, f"safety flag {flag!r} is not True"
        # The artifact checksum must be a real sha256 of an existing
        # scorecard file (not a placeholder).
        cs = rebuilt.artifact_reference.checksum
        assert cs is not None
        assert cs.algorithm == "sha256"
        assert len(cs.hex_digest) == 64
        assert cs.size_bytes > 0


def test_artifact_manifest_records_carry_advisory_only_summary(
    unified_package: UnifiedPackage,
) -> None:
    for rec in unified_package.artifact_manifest["records"]:
        summ = rec["summary"]
        assert summ["advisory_only"] is True
        assert summ["actuates"] is False
        assert summ["safety_banner"] == SAFETY_BANNER
        assert summ["edge_export"].startswith("BLOCKED")
        assert summ["artifact_kind"] == "evidence_scorecard_only_no_weights"


# --------------------------------------------------------------------------- #
# Exports honour the "no claim on unsupported intervals" boundary
# --------------------------------------------------------------------------- #
def test_efficiency_export_emits_no_unsupported_advisory_rows(
    unified_package: UnifiedPackage,
) -> None:
    export = unified_package.efficiency_advisory_export
    advisories = export.get("advisories", [])
    # All emitted rows must be supported=True (no claim on unsupported).
    assert advisories, "expected at least one supported advisory row"
    for row in advisories:
        assert row["supported"] is True, (
            f"advisory row carries supported=False -- violates Sprint 33 contract: {row}"
        )


def test_efficiency_export_metadata_records_unsupported_count(
    unified_package: UnifiedPackage,
) -> None:
    md = unified_package.efficiency_advisory_export["metadata"]
    # The Sprint 33 scorecard reported 37 unsupported intervals. The metadata
    # must record the exclusion count so a reviewer sees the rejection volume.
    assert md["n_unsupported_intervals_excluded"] >= 1
    assert md["safety_banner"] == SAFETY_BANNER
    assert md["claim_discipline"].startswith(
        "counterfactual_offline_opportunity_on_supported_intervals_only"
    )


def test_health_event_export_metadata(unified_package: UnifiedPackage) -> None:
    md = unified_package.health_event_export["metadata"]
    assert md["safety_banner"] == SAFETY_BANNER
    assert md["advisory_only"] is True
    assert md["evaluation_mode"] == "offline_only"
    assert md["label_regime"].startswith("synthetic_injected_faults")
    assert md["n_episodes"] >= 1
    # Every emitted event row carries the advisory-only flag.
    for ev in unified_package.health_event_export["events"]:
        assert ev["advisory_only"] is True
        assert ev["is_evidence_not_setpoint"] is True


# --------------------------------------------------------------------------- #
# Packaging gate
# --------------------------------------------------------------------------- #
def test_packaging_gate_passes_overall(unified_package: UnifiedPackage) -> None:
    gate = unified_package.packaging_gate
    assert gate["verdict"] == "PASS"
    assert gate["passed"] is True


@pytest.mark.parametrize("criterion_name", [
    "safety_banner_on_every_surface",
    "no_control_endpoint_or_ui_control_in_dashboard",
    "leakage_and_safety_checks_pass",
    "reports_include_cannot_claim_statements",
    "edge_site_control_packaging_remains_blocked",
])
def test_each_packaging_gate_criterion_passes(
    criterion_name: str, unified_package: UnifiedPackage,
) -> None:
    crit = next(
        c for c in unified_package.packaging_gate["criteria"] if c["name"] == criterion_name
    )
    assert crit["passed"] is True, f"criterion {criterion_name} failed: {crit['detail']}"


def test_packaging_blocks_inventory_is_complete(unified_package: UnifiedPackage) -> None:
    # The packaging-blocks inventory must explicitly cover every dimension we
    # do NOT ship in this sprint.
    sc = unified_package.scorecard
    blocks = sc["packaging_blocks"]
    assert set(PACKAGING_BLOCKS).issubset(blocks.keys())
    for key, value in blocks.items():
        assert value.upper().startswith("BLOCKED"), (
            f"packaging block {key} is not BLOCKED: {value!r}"
        )


# --------------------------------------------------------------------------- #
# Writer round-trip
# --------------------------------------------------------------------------- #
def test_writer_produces_every_expected_file(
    unified_package: UnifiedPackage, tmp_path: Path,
) -> None:
    paths = write_unified_package(unified_package, out_dir=tmp_path)
    for key, p in paths.items():
        assert p.is_file(), f"writer did not produce {key} at {p}"
        assert p.stat().st_size > 0, f"writer produced an empty {key} at {p}"
    # Re-read the scorecard JSON and confirm both verdicts survived.
    sc = json.loads(paths["scorecard"].read_text(encoding="utf-8"))
    assert sc["pillar_a_verdict"] == unified_package.scorecard["pillar_a_verdict"]
    assert sc["pillar_b_verdict"] == unified_package.scorecard["pillar_b_verdict"]


# --------------------------------------------------------------------------- #
# Source scorecards are referenced (not silently fabricated)
# --------------------------------------------------------------------------- #
def test_scorecard_names_source_evidence_files(unified_package: UnifiedPackage) -> None:
    sc = unified_package.scorecard
    refs = sc["source_scorecards"]
    assert refs["pillar_a"].endswith("sprint30b_fullyear_holdout_scorecard.json")
    assert refs["pillar_b"].endswith("sprint33_locked_march_scorecard.json")


def test_pillar_views_carry_holdout_window_and_gate_metadata(
    unified_package: UnifiedPackage,
) -> None:
    sc = unified_package.scorecard
    a = sc["pillar_a"]
    b = sc["pillar_b"]
    assert a["holdout_window"]["all_in_2026_03"] is True
    assert b["holdout_window"]["all_in_2026_03"] is True
    assert b["frozen_gate"]["gate_version"].startswith("sprint32")
    assert b["frozen_gate"]["march_used_for_tuning"] is False
    assert a["gate_version"] == "v2"


def test_allowed_pillar_b_language_is_present_in_executive_report(
    unified_package: UnifiedPackage,
) -> None:
    for phrase in ALLOWED_PILLAR_B_LANGUAGE:
        assert phrase in unified_package.executive_report_md, (
            f"allowed advisory phrase missing from executive report: {phrase!r}"
        )
