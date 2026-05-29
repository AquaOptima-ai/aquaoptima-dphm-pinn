"""Acceptance-gate tests (AOPSO Sprint 25, updated for the Sprint 26 API).

Verifies the machine-checkable PASS/FAIL gate:
* continuous-axis MSE <= 0.15 AND MAE <= 0.30 per active continuous axis,
* binary-axis BALANCED accuracy / F1 >= min (DEFECT 2 fix) -- and since Sprint 26
  has NO binary axes (node_status reclassified continuous, edge_status dropped
  as a binary target -> BINARY_AXES is empty), this criterion is VACUOUSLY
  satisfied; the gate must still PASS with no binary axes present,
* dPHM beats baseline (lower MSE) on >= 5 of 6 continuous axes.

Sprint 26 changes reflected here:
* The binary criterion was renamed ``binary_accuracy_within_threshold`` ->
  ``binary_balanced_accuracy_within_threshold`` and is now imbalance-aware.
* With BINARY_AXES empty, the gate's continuous axes are the only graded MSE/MAE
  axes; we keep the fixture to the 6 named continuous axes so the "beats
  baseline 5/6 vs 4/6" boundary stays exactly meaningful (6 continuous axes).

All synthetic numbers here are TEST FIXTURES chosen to exercise the boundary
logic -- they are NOT real model metrics and never touch a checkpoint or CSV.
"""

from __future__ import annotations

from aquaoptima.training.acceptance import (
    AcceptanceThresholds,
    evaluate_gate,
)
from aquaoptima.dataio.yilan_axis_map import BINARY_AXES

# The six continuous axes the boundary tests grade. (node_status / edge_status
# are now ALSO continuous, but the "beats baseline 5/6" contract is defined over
# these six, so we keep the graded fixture to exactly six to preserve intent.)
CONTINUOUS = [
    "edge_flow",
    "edge_power",
    "edge_pump_speed",
    "node_demand",
    "node_level",
    "node_pressure",
]

# Criterion-name set the gate now emits (Sprint 26 renamed the binary criterion).
EXPECTED_CRITERIA = {
    "continuous_mse_within_threshold",
    "continuous_mae_within_threshold",
    "binary_balanced_accuracy_within_threshold",
    "beats_baseline_on_continuous_axes",
}


def _passing_dphm():
    m = {}
    for a in CONTINUOUS:
        m[a] = {"kind": "continuous", "mse": 0.10, "mae": 0.20, "accuracy": None}
    return m


def _worse_baseline():
    # Baseline MSE strictly above dPHM on every continuous axis.
    m = {}
    for a in CONTINUOUS:
        m[a] = {"kind": "continuous", "mse": 0.25, "mae": 0.40, "accuracy": None}
    return m


def test_gate_passes_when_all_criteria_met():
    gate = evaluate_gate(_passing_dphm(), _worse_baseline())
    assert gate.passed is True
    assert gate.verdict == "PASS"
    names = {c.name for c in gate.criteria}
    assert names == EXPECTED_CRITERIA
    assert all(c.passed for c in gate.criteria)


def test_gate_fails_on_high_mse():
    dphm = _passing_dphm()
    dphm["edge_power"]["mse"] = 0.30  # > 0.15
    gate = evaluate_gate(dphm, _worse_baseline())
    assert gate.passed is False
    crit = {c.name: c for c in gate.criteria}
    assert crit["continuous_mse_within_threshold"].passed is False
    # MAE criterion still passes; isolate the failing one.
    assert crit["continuous_mae_within_threshold"].passed is True
    assert crit["continuous_mse_within_threshold"].detail["per_axis"]["edge_power"]["passed"] is False


def test_gate_fails_on_high_mae():
    dphm = _passing_dphm()
    dphm["node_level"]["mae"] = 0.50  # > 0.30
    gate = evaluate_gate(dphm, _worse_baseline())
    assert gate.passed is False
    crit = {c.name: c for c in gate.criteria}
    assert crit["continuous_mae_within_threshold"].passed is False


def test_binary_criterion_vacuously_passes_with_no_binary_axes():
    # Sprint 26: BINARY_AXES is empty (node_status reclassified continuous,
    # edge_status dropped as a binary target). The renamed balanced-accuracy
    # criterion must be PRESENT and VACUOUSLY satisfied (nothing to gate), so it
    # never blocks packaging on its own. This replaces the old
    # ``test_gate_fails_on_low_binary_accuracy`` whose premise (a gradeable
    # binary axis below the accuracy bar) no longer exists.
    assert BINARY_AXES == frozenset()
    gate = evaluate_gate(_passing_dphm(), _worse_baseline())
    crit = {c.name: c for c in gate.criteria}
    binc = crit["binary_balanced_accuracy_within_threshold"]
    assert binc.passed is True
    assert binc.detail["n_axes"] == 0
    # The detail records that the criterion was vacuously satisfied.
    assert "vacuously" in binc.detail["note"]


def test_threshold_boundaries_are_inclusive():
    # Exactly at thresholds -> still PASS (<=, >=).
    dphm = _passing_dphm()
    for a in CONTINUOUS:
        dphm[a]["mse"] = 0.15
        dphm[a]["mae"] = 0.30
    gate = evaluate_gate(dphm, _worse_baseline())
    crit = {c.name: c for c in gate.criteria}
    assert crit["continuous_mse_within_threshold"].passed is True
    assert crit["continuous_mae_within_threshold"].passed is True
    # No binary axes -> balanced-accuracy criterion vacuously passes at the
    # boundary scenario too.
    assert crit["binary_balanced_accuracy_within_threshold"].passed is True


def test_beats_baseline_exactly_5_of_6_passes():
    dphm = _passing_dphm()
    baseline = _worse_baseline()
    # Make dPHM LOSE on exactly one continuous axis (5 of 6 win -> meets >=5).
    baseline["edge_flow"]["mse"] = 0.05  # baseline better than dphm's 0.10 here
    gate = evaluate_gate(dphm, baseline)
    crit = {c.name: c for c in gate.criteria}
    beats = crit["beats_baseline_on_continuous_axes"]
    assert beats.detail["n_beats"] == 5
    assert beats.passed is True
    assert gate.passed is True


def test_beats_baseline_only_4_of_6_fails():
    dphm = _passing_dphm()
    baseline = _worse_baseline()
    # dPHM loses on TWO continuous axes -> only 4 wins -> below the >=5 bar.
    baseline["edge_flow"]["mse"] = 0.05
    baseline["edge_power"]["mse"] = 0.05
    gate = evaluate_gate(dphm, baseline)
    crit = {c.name: c for c in gate.criteria}
    beats = crit["beats_baseline_on_continuous_axes"]
    assert beats.detail["n_beats"] == 4
    assert beats.passed is False
    assert gate.passed is False


def test_no_baseline_fails_beats_criterion():
    gate = evaluate_gate(_passing_dphm(), None)
    crit = {c.name: c for c in gate.criteria}
    assert crit["beats_baseline_on_continuous_axes"].passed is False
    assert gate.passed is False


def test_thresholds_from_config_block():
    cfg = {
        "eval": {
            "continuous_mse_max": 0.05,
            "continuous_mae_max": 0.10,
            "binary_accuracy_min": 0.99,
            "beats_baseline_min": 6,
        }
    }
    th = AcceptanceThresholds.from_config(cfg)
    assert th.continuous_mse_max == 0.05
    assert th.continuous_mae_max == 0.10
    assert th.binary_accuracy_min == 0.99
    assert th.beats_baseline_min == 6
    # Defaults when no config.
    d = AcceptanceThresholds.from_config(None)
    assert d.continuous_mse_max == 0.15
    assert d.beats_baseline_min == 5
