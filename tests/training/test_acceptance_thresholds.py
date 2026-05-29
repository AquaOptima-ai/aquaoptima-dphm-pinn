"""Acceptance-gate tests (AOPSO Sprint 25): synthetic metrics above/below thresholds.

Verifies the machine-checkable PASS/FAIL gate:
* continuous-axis MSE <= 0.15 AND MAE <= 0.30 per active continuous axis,
* binary-axis accuracy >= 0.95,
* dPHM beats baseline (lower MSE) on >= 5 of 6 continuous axes.

All synthetic numbers here are TEST FIXTURES chosen to exercise the boundary
logic -- they are NOT real model metrics and never touch a checkpoint or CSV.
"""

from __future__ import annotations

from aquaoptima.training.acceptance import (
    AcceptanceThresholds,
    evaluate_gate,
)

CONTINUOUS = [
    "edge_flow",
    "edge_power",
    "edge_pump_speed",
    "node_demand",
    "node_level",
    "node_pressure",
]
BINARY = ["node_status", "edge_status"]


def _passing_dphm():
    m = {}
    for a in CONTINUOUS:
        m[a] = {"kind": "continuous", "mse": 0.10, "mae": 0.20, "accuracy": None}
    for a in BINARY:
        m[a] = {"kind": "binary", "accuracy": 0.97, "mse": 0.05, "mae": 0.10}
    return m


def _worse_baseline():
    # Baseline MSE strictly above dPHM on every continuous axis.
    m = {}
    for a in CONTINUOUS:
        m[a] = {"kind": "continuous", "mse": 0.25, "mae": 0.40, "accuracy": None}
    for a in BINARY:
        m[a] = {"kind": "binary", "accuracy": 0.90, "mse": 0.12, "mae": 0.20}
    return m


def test_gate_passes_when_all_criteria_met():
    gate = evaluate_gate(_passing_dphm(), _worse_baseline())
    assert gate.passed is True
    assert gate.verdict == "PASS"
    names = {c.name for c in gate.criteria}
    assert names == {
        "continuous_mse_within_threshold",
        "continuous_mae_within_threshold",
        "binary_accuracy_within_threshold",
        "beats_baseline_on_continuous_axes",
    }
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


def test_gate_fails_on_low_binary_accuracy():
    dphm = _passing_dphm()
    dphm["node_status"]["accuracy"] = 0.80  # < 0.95
    gate = evaluate_gate(dphm, _worse_baseline())
    assert gate.passed is False
    crit = {c.name: c for c in gate.criteria}
    assert crit["binary_accuracy_within_threshold"].passed is False


def test_threshold_boundaries_are_inclusive():
    # Exactly at thresholds -> still PASS (<=, >=).
    dphm = _passing_dphm()
    for a in CONTINUOUS:
        dphm[a]["mse"] = 0.15
        dphm[a]["mae"] = 0.30
    for a in BINARY:
        dphm[a]["accuracy"] = 0.95
    gate = evaluate_gate(dphm, _worse_baseline())
    crit = {c.name: c for c in gate.criteria}
    assert crit["continuous_mse_within_threshold"].passed is True
    assert crit["continuous_mae_within_threshold"].passed is True
    assert crit["binary_accuracy_within_threshold"].passed is True


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
