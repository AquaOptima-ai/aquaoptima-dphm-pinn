"""Tests for the Sprint 29b product-grounded acceptance gate v2.

Asserts the GATE LOGIC only (synthetic eval dicts) -- never a specific real-data outcome.
v2 credits a material false-alarm reduction at non-inferior AUROC, which v1 did not.
"""

from __future__ import annotations

import math

from aquaoptima.advisory.health_gate import (
    GATE_V2_FAR_IMPROVEMENT_FACTOR,
    GATE_V2_AUROC_NONINFERIORITY_TOL,
    health_acceptance_gate,
    health_acceptance_gate_v2,
)


def _eval(d_auroc, b_auroc, d_far, b_far, d_lead=10.0, b_lead=8.0):
    return {
        "detector": {"auroc": d_auroc, "false_alarm_rate": d_far, "mean_lead_time": d_lead},
        "baseline": {"auroc": b_auroc, "false_alarm_rate": b_far, "mean_lead_time": b_lead},
    }


def test_v2_passes_noninferior_auroc_with_material_far_improvement():
    # detector slightly above baseline AUROC, FAR ~21x better -> PASS under v2
    g = health_acceptance_gate_v2(_eval(0.8158, 0.8072, 0.0076, 0.1618))
    assert g["verdict"] == "PASS"
    assert g["gate_version"] == "v2"
    assert all(c["passed"] for c in g["criteria"])


def test_v2_disagrees_with_v1_on_the_sprint29_case():
    # The whole point: same numbers, v1 FAIL (AUROC margin), v2 PASS (FAR-credited).
    ev = _eval(0.8158, 0.8072, 0.0076, 0.1618)
    assert health_acceptance_gate(ev)["verdict"] == "FAIL"
    assert health_acceptance_gate_v2(ev)["verdict"] == "PASS"


def test_v2_fails_strictly_worse_detector():
    g = health_acceptance_gate_v2(_eval(0.60, 0.81, 0.30, 0.16))
    assert g["verdict"] == "FAIL"


def test_v2_fails_when_far_not_materially_better_even_with_high_auroc():
    # great AUROC but FAR only equal to baseline (not halved) -> FAIL
    g = health_acceptance_gate_v2(_eval(0.95, 0.81, 0.16, 0.16))
    assert g["verdict"] == "FAIL"
    far_clause = next(c for c in g["criteria"] if c["name"] == "detector_false_alarm_materially_better")
    assert far_clause["passed"] is False


def test_v2_fails_below_absolute_auroc_floor():
    # FAR great and non-inferior to a weak baseline, but below 0.70 floor -> FAIL
    g = health_acceptance_gate_v2(_eval(0.66, 0.66, 0.01, 0.16))
    assert g["verdict"] == "FAIL"
    floor = next(c for c in g["criteria"] if c["name"] == "detector_auroc_minimum")
    assert floor["passed"] is False


def test_v2_fails_on_material_auroc_regression_beyond_tolerance():
    # detector AUROC 0.05 below baseline (> 0.01 tol) -> non-inferiority FAIL
    g = health_acceptance_gate_v2(_eval(0.76, 0.81, 0.01, 0.16))
    assert g["verdict"] == "FAIL"
    ni = next(c for c in g["criteria"] if c["name"] == "detector_auroc_noninferior")
    assert ni["passed"] is False


def test_v2_fails_on_lead_time_regression():
    # everything good but detector warns much later than baseline -> FAIL
    g = health_acceptance_gate_v2(_eval(0.82, 0.81, 0.01, 0.16, d_lead=2.0, b_lead=8.0))
    assert g["verdict"] == "FAIL"
    lead = next(c for c in g["criteria"] if c["name"] == "detector_lead_time_noninferior")
    assert lead["passed"] is False


def test_v2_lead_time_nan_is_not_a_hard_fail():
    # degenerate lead-time (NaN) must not fabricate a pass nor force a fail on that clause
    g = health_acceptance_gate_v2(_eval(0.82, 0.81, 0.01, 0.16, d_lead=float("nan"), b_lead=8.0))
    lead = next(c for c in g["criteria"] if c["name"] == "detector_lead_time_noninferior")
    assert lead["passed"] is True
    # other clauses still govern
    assert g["verdict"] == "PASS"


def test_v2_threshold_constants_are_documented_values():
    assert GATE_V2_FAR_IMPROVEMENT_FACTOR == 2.0
    assert math.isclose(GATE_V2_AUROC_NONINFERIORITY_TOL, 0.01)
