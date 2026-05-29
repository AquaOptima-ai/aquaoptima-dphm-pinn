"""Sprint 27 scorecard-governance wiring tests.

Asserts the contract between :func:`build_governance_block` and
:func:`apply_governance_to_verdict`:

* ``build_governance_block`` returns ``governance_status="PASS"`` for a clean
  2025-only split, the real label-schema, the real normalization stats, and a
  clean modeling source tree;
* it returns ``governance_status="FAIL"`` when the split includes a
  March-2026 key (leakage);
* it returns ``governance_status="FAIL"`` when the scanned modeling source
  contains an edge import;
* ``apply_governance_to_verdict`` forces ``verdict="FAIL"`` / ``passed=False``
  on governance FAIL and appends a ``governance_guardrails`` criterion;
* it leaves a passing acceptance gate untouched on governance PASS.

Subset / fixture-based, deterministic, no full-CSV reads, no model training.
"""

from __future__ import annotations

import copy
import json

import pytest

from aquaoptima.advisory.schema_validation import (
    EXPECTED_ACTIVE_AXES,
    apply_governance_to_verdict,
    build_governance_block,
)


# --- shared fixtures -------------------------------------------------------

@pytest.fixture()
def clean_split(tmp_path):
    """A 2025-only split manifest (mirrors the real split structure)."""
    manifest = {
        "splits": {
            "train": {
                "days": ["2025-06-01", "2025-07-01"],
                "date_range": {
                    "start": "2025-06-01T00:00:00",
                    "end": "2025-07-01T00:00:00",
                },
            },
            "val": {
                "days": ["2025-08-01"],
                "date_range": {
                    "start": "2025-08-01T00:00:00",
                    "end": "2025-08-02T00:00:00",
                },
            },
            "holdout_march2026": {
                "date_range": {"start": "2026-03-01", "end": "2026-03-31"},
            },
        }
    }
    path = tmp_path / "split.json"
    path.write_text(json.dumps(manifest))
    return path


@pytest.fixture()
def leaky_split(tmp_path):
    """Split whose val days include a March-2026 timestamp (leakage)."""
    manifest = {
        "splits": {
            "train": {
                "days": ["2025-06-01"],
                "date_range": {
                    "start": "2025-06-01T00:00:00",
                    "end": "2025-06-30T00:00:00",
                },
            },
            "val": {
                # Direct leakage into the LOCKED holdout window.
                "days": ["2025-08-01", "2026-03-15 12:00:00"],
                "date_range": {
                    "start": "2025-08-01T00:00:00",
                    "end": "2026-03-31T00:00:00",
                },
            },
        }
    }
    path = tmp_path / "leaky.json"
    path.write_text(json.dumps(manifest))
    return path


@pytest.fixture()
def clean_stats(tmp_path):
    """Synthetic stats covering exactly the 8 expected axes with sigma > 0."""
    stats = {
        "split_version": "fixture",
        "active_axes": list(EXPECTED_ACTIVE_AXES),
        "stats": {
            axis: {"source_column": f"col_{axis}", "mu": float(i), "sigma": 1.0 + i}
            for i, axis in enumerate(EXPECTED_ACTIVE_AXES)
        },
    }
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(stats))
    return path


@pytest.fixture()
def clean_modeling_root(tmp_path):
    """A small, governance-clean fake modeling source tree."""
    root = tmp_path / "fake_modeling"
    root.mkdir()
    (root / "module.py").write_text(
        "import numpy as np\n"
        "from aquaoptima.advisory.label_schema import telemetry_axis_schema\n"
        "def forward(x): return x.mean()\n"
    )
    return root


@pytest.fixture()
def edge_violation_root(tmp_path):
    """Fake modeling source that does the forbidden edge import."""
    root = tmp_path / "edge_violation"
    root.mkdir()
    (root / "leaky.py").write_text("from aquaoptima.edge import package_validator\n")
    return root


# --- build_governance_block -----------------------------------------------

def test_clean_inputs_yield_governance_pass(
    clean_split, clean_stats, clean_modeling_root
):
    block = build_governance_block(
        split_manifest=clean_split,
        modeling_roots=(clean_modeling_root,),
        normalization_stats=clean_stats,
    )
    assert block["governance_status"] == "PASS"
    assert block["holdout_isolation"]["isolated"] is True
    assert block["holdout_isolation"]["leaked_keys"] == []
    assert block["import_connector_scan"]["clean"] is True
    assert block["import_connector_scan"]["violations"] == []
    assert block["axis_taxonomy"]["ok"] is True
    assert block["normalization_coverage"]["ok"] is True


def test_march_2026_key_fails_holdout_isolation(
    leaky_split, clean_stats, clean_modeling_root
):
    block = build_governance_block(
        split_manifest=leaky_split,
        modeling_roots=(clean_modeling_root,),
        normalization_stats=clean_stats,
    )
    assert block["governance_status"] == "FAIL"
    assert block["holdout_isolation"]["isolated"] is False
    leaked = block["holdout_isolation"]["leaked_keys"]
    assert any(k.startswith("2026-03") for k in leaked)
    # The clean guards remain ok individually.
    assert block["import_connector_scan"]["clean"] is True
    assert block["axis_taxonomy"]["ok"] is True
    assert block["normalization_coverage"]["ok"] is True


def test_edge_import_in_modeling_source_fails_scan(
    clean_split, clean_stats, edge_violation_root
):
    block = build_governance_block(
        split_manifest=clean_split,
        modeling_roots=(edge_violation_root,),
        normalization_stats=clean_stats,
    )
    assert block["governance_status"] == "FAIL"
    assert block["import_connector_scan"]["clean"] is False
    assert any(
        "forbidden edge import" in v
        for v in block["import_connector_scan"]["violations"]
    )
    # Holdout guard still PASSes on its own merits.
    assert block["holdout_isolation"]["isolated"] is True


def test_governance_block_accepts_in_memory_split(clean_stats, clean_modeling_root):
    in_memory_manifest = {
        "splits": {
            "train": {
                "days": ["2025-09-01"],
                "date_range": {"start": "2025-09-01", "end": "2025-09-02"},
            },
            "val": {
                "days": ["2025-10-01"],
                "date_range": {"start": "2025-10-01", "end": "2025-10-02"},
            },
        }
    }
    block = build_governance_block(
        split_manifest=in_memory_manifest,
        modeling_roots=(clean_modeling_root,),
        normalization_stats=clean_stats,
    )
    assert block["governance_status"] == "PASS"


# --- apply_governance_to_verdict ------------------------------------------

def _make_passing_gate() -> dict:
    return {
        "verdict": "PASS",
        "passed": True,
        "criteria": [
            {"name": "continuous_mse_within_threshold", "passed": True},
            {"name": "beats_baseline_on_continuous_axes", "passed": True},
        ],
    }


def _make_pass_governance_block() -> dict:
    return {
        "governance_status": "PASS",
        "holdout_isolation": {"isolated": True, "leaked_keys": []},
        "import_connector_scan": {"clean": True, "violations": []},
        "axis_taxonomy": {"ok": True, "errors": []},
        "normalization_coverage": {"ok": True, "errors": []},
    }


def _make_fail_governance_block(reason: str = "leakage") -> dict:
    if reason == "leakage":
        return {
            "governance_status": "FAIL",
            "holdout_isolation": {
                "isolated": False,
                "leaked_keys": ["2026-03-15 12:00:00"],
            },
            "import_connector_scan": {"clean": True, "violations": []},
            "axis_taxonomy": {"ok": True, "errors": []},
            "normalization_coverage": {"ok": True, "errors": []},
        }
    return {
        "governance_status": "FAIL",
        "holdout_isolation": {"isolated": True, "leaked_keys": []},
        "import_connector_scan": {
            "clean": False,
            "violations": ["bad.py: forbidden edge import 'from aquaoptima.edge'"],
        },
        "axis_taxonomy": {"ok": True, "errors": []},
        "normalization_coverage": {"ok": True, "errors": []},
    }


def test_apply_governance_passes_through_when_clean():
    gate = _make_passing_gate()
    original = copy.deepcopy(gate)
    out = apply_governance_to_verdict(gate, _make_pass_governance_block())
    assert out["verdict"] == "PASS"
    assert out["passed"] is True
    # No governance criterion appended on PASS.
    assert all(c["name"] != "governance_guardrails" for c in out["criteria"])
    # Source gate not mutated in place.
    assert gate == original


def test_apply_governance_forces_fail_on_governance_fail():
    gate = _make_passing_gate()
    block = _make_fail_governance_block("leakage")
    out = apply_governance_to_verdict(gate, block)
    assert out["verdict"] == "FAIL"
    assert out["passed"] is False
    assert out["governance_override"] is True
    crit = next(c for c in out["criteria"] if c["name"] == "governance_guardrails")
    assert crit["passed"] is False
    assert crit["detail"]["governance_status"] == "FAIL"
    leaked = crit["detail"]["failing_guards"][0]
    assert leaked["guard"] == "holdout_isolation"
    assert "2026-03-15 12:00:00" in leaked["leaked_keys"]


def test_apply_governance_reports_import_scan_failure():
    gate = _make_passing_gate()
    block = _make_fail_governance_block("import_scan")
    out = apply_governance_to_verdict(gate, block)
    assert out["verdict"] == "FAIL"
    crit = next(c for c in out["criteria"] if c["name"] == "governance_guardrails")
    failing_guards = crit["detail"]["failing_guards"]
    assert any(g["guard"] == "import_connector_scan" for g in failing_guards)


def test_apply_governance_does_not_remove_existing_criteria():
    gate = _make_passing_gate()
    original_names = [c["name"] for c in gate["criteria"]]
    out = apply_governance_to_verdict(gate, _make_fail_governance_block("leakage"))
    out_names = [c["name"] for c in out["criteria"]]
    assert out_names[: len(original_names)] == original_names


# --- end-to-end: governance FAIL FORCES scorecard FAIL --------------------

def test_governance_fail_forces_scorecard_acceptance_gate_fail(
    clean_stats, clean_modeling_root, leaky_split
):
    """A leaky split + a (synthetically) passing acceptance gate must FAIL overall."""
    block = build_governance_block(
        split_manifest=leaky_split,
        modeling_roots=(clean_modeling_root,),
        normalization_stats=clean_stats,
    )
    assert block["governance_status"] == "FAIL"

    passing_metrics_gate = _make_passing_gate()
    gated = apply_governance_to_verdict(passing_metrics_gate, block)
    assert gated["verdict"] == "FAIL"
    assert gated["passed"] is False
    assert any(c["name"] == "governance_guardrails" for c in gated["criteria"])
