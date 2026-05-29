"""Sprint 27 governance guardrail tests: data-leakage guard + import/connector scan."""

from __future__ import annotations

from pathlib import Path

from aquaoptima.advisory.governance import (
    LOCKED_HOLDOUT_PREFIX,
    assert_holdout_isolated,
    scan_modeling_source_for_governance_violations,
    scan_text_for_governance_violations,
)


# --- leakage guard ---------------------------------------------------------

def test_holdout_isolated_when_only_2025_keys():
    res = assert_holdout_isolated(
        ["2025-01-05 00:00:00", "2025-07-21 12:30:00", "2025-12-31 23:59:00"]
    )
    assert res.isolated is True
    assert res.leaked_keys == ()
    assert res.n_train_val_checked == 3
    assert res.holdout_prefix == LOCKED_HOLDOUT_PREFIX


def test_leakage_detected_when_march_2026_key_present():
    res = assert_holdout_isolated(
        ["2025-12-31 23:59:00", "2026-03-15 08:00:00", "2026-03-01 00:00:53"]
    )
    assert res.isolated is False
    assert res.leaked_keys == ("2026-03-01 00:00:53", "2026-03-15 08:00:00")


def test_month_bucket_keys_also_work():
    assert assert_holdout_isolated(["2025-03", "2025-11"]).isolated is True
    assert assert_holdout_isolated(["2025-03", "2026-03"]).isolated is False


# --- governance scan -------------------------------------------------------

def test_clean_modeling_text_passes():
    text = (
        "import torch\n"
        "from aquaoptima.advisory.label_schema import telemetry_axis_schema\n"
        "def forward(x): return model(x)\n"
    )
    assert scan_text_for_governance_violations(text) == []


def test_edge_import_is_flagged():
    text = "from aquaoptima.edge import package_validator\n"
    violations = scan_text_for_governance_violations(text, label="bad.py")
    assert any("forbidden edge import" in v for v in violations)


def test_contracts_edge_import_is_flagged():
    text = "import aquaoptima_contracts.edge.package_validator as v\n"
    violations = scan_text_for_governance_violations(text)
    assert any("forbidden edge import" in v for v in violations)


def test_write_connector_token_is_flagged():
    text = "def push(): write_setpoint(vfd, 50.0)\n"
    violations = scan_text_for_governance_violations(text)
    assert any("write/actuation token" in v for v in violations)


def test_scan_real_advisory_package_is_clean(tmp_path):
    # The advisory package we just authored must itself pass the governance scan.
    advisory_dir = Path(__file__).resolve().parents[2] / "src" / "aquaoptima" / "advisory"
    res = scan_modeling_source_for_governance_violations([advisory_dir])
    assert res.files_scanned >= 4
    assert res.clean is True, f"unexpected violations: {res.violations}"
    assert res.safety_status == "PASS"


def test_safety_status_fails_on_violation(tmp_path):
    bad = tmp_path / "leaky_model.py"
    bad.write_text("from aquaoptima.edge import x\n")
    res = scan_modeling_source_for_governance_violations([tmp_path])
    assert res.clean is False
    assert res.safety_status == "FAIL"
