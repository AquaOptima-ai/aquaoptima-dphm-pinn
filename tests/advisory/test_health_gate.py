"""Sprint 29 tests for the FROZEN health acceptance gate.

The gate is the empirical rule; the tests assert the LOGIC of that rule (PASS
when the detector clears the bar, FAIL when it does not, FAIL when governance
fails). We never assert a specific real-data outcome.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aquaoptima.advisory.health_baselines import fit_health_baseline_suite
from aquaoptima.advisory.health_detector import fit_health_detector
from aquaoptima.advisory.health_gate import (
    FROZEN_AUROC_MARGIN,
    FROZEN_DETECTOR_MIN_AUROC,
    FROZEN_GATE_RULE_TEXT,
    evaluate_detector_vs_baseline,
    health_acceptance_gate,
)
from aquaoptima.advisory.injected_faults import inject_faults
from aquaoptima.advisory.schema_validation import apply_governance_to_verdict


TEST_AXES = ("edge_flow", "edge_power", "edge_pump_speed", "node_pressure")


def _synthetic_2025_normal(n_rows: int = 1200, seed: int = 17) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    flow = rng.normal(loc=1500.0, scale=80.0, size=n_rows)
    speed = rng.normal(loc=42.0, scale=1.5, size=n_rows)
    power = 0.05 * flow + 1.5 * speed + rng.normal(loc=0.0, scale=2.0, size=n_rows)
    pressure = rng.normal(loc=18.0, scale=0.5, size=n_rows)
    ts = pd.date_range("2025-07-01 00:00:00", periods=n_rows, freq="1min").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return pd.DataFrame(
        {
            "timestamp": ts,
            "edge_flow": flow,
            "edge_power": power,
            "edge_pump_speed": speed,
            "node_pressure": pressure,
        }
    )


# --------------------------------------------------------------------------- #
# Pure gate logic
# --------------------------------------------------------------------------- #
def _make_eval(
    det_auroc: float,
    base_auroc: float,
    det_far: float,
    base_far: float,
    det_lt: float = 5.0,
    base_lt: float = 5.0,
) -> dict:
    """Synthesise an eval-shaped dict for pure gate-logic tests."""
    return {
        "n_rows": 1000,
        "n_positive": 100,
        "n_negative": 900,
        "n_episodes": 8,
        "detector": {
            "auroc": float(det_auroc),
            "false_alarm_rate": float(det_far),
            "mean_lead_time": float(det_lt),
        },
        "baseline": {
            "auroc": float(base_auroc),
            "false_alarm_rate": float(base_far),
            "mean_lead_time": float(base_lt),
        },
        "delta": {
            "auroc": float(det_auroc - base_auroc),
            "false_alarm_rate": float(det_far - base_far),
        },
    }


def test_gate_passes_when_detector_clearly_beats_baseline():
    e = _make_eval(det_auroc=0.92, base_auroc=0.80, det_far=0.02, base_far=0.05)
    gate = health_acceptance_gate(e)
    assert gate["verdict"] == "PASS"
    assert gate["passed"] is True
    assert gate["rule"] == FROZEN_GATE_RULE_TEXT


def test_gate_fails_when_auroc_margin_missing():
    # Detector beats but not by 0.02
    e = _make_eval(det_auroc=0.81, base_auroc=0.80, det_far=0.02, base_far=0.05)
    gate = health_acceptance_gate(e)
    assert gate["verdict"] == "FAIL"
    assert not gate["passed"]
    names = [c["name"] for c in gate["criteria"] if not c["passed"]]
    assert "detector_auroc_beats_baseline_by_margin" in names


def test_gate_fails_when_false_alarm_exceeds_baseline():
    e = _make_eval(det_auroc=0.90, base_auroc=0.70, det_far=0.10, base_far=0.05)
    gate = health_acceptance_gate(e)
    assert gate["verdict"] == "FAIL"
    names = [c["name"] for c in gate["criteria"] if not c["passed"]]
    assert "detector_false_alarm_at_or_below_baseline" in names


def test_gate_fails_when_detector_below_absolute_minimum():
    # Detector beats by margin and has lower FAR but is below 0.70 absolute.
    e = _make_eval(det_auroc=0.65, base_auroc=0.50, det_far=0.01, base_far=0.05)
    gate = health_acceptance_gate(e)
    assert gate["verdict"] == "FAIL"
    names = [c["name"] for c in gate["criteria"] if not c["passed"]]
    assert "detector_auroc_minimum" in names


def test_gate_includes_metrics_and_rule_text():
    e = _make_eval(det_auroc=0.90, base_auroc=0.80, det_far=0.02, base_far=0.05)
    gate = health_acceptance_gate(e)
    assert "metrics" in gate
    assert "rule_parameters" in gate
    assert gate["rule_parameters"]["auroc_margin"] == FROZEN_AUROC_MARGIN
    assert (
        gate["rule_parameters"]["min_detector_auroc"]
        == FROZEN_DETECTOR_MIN_AUROC
    )


def test_governance_fail_forces_verdict_fail_even_on_passing_metrics():
    e = _make_eval(det_auroc=0.95, base_auroc=0.70, det_far=0.01, base_far=0.05)
    gate = health_acceptance_gate(e)
    assert gate["verdict"] == "PASS"
    failing_gov = {
        "governance_status": "FAIL",
        "holdout_isolation": {"isolated": False, "leaked_keys": ["2026-03-01 00:00:00"]},
        "import_connector_scan": {"clean": True},
        "axis_taxonomy": {"ok": True},
        "normalization_coverage": {"ok": True},
    }
    forced = apply_governance_to_verdict(gate, failing_gov)
    assert forced["verdict"] == "FAIL"
    assert forced["passed"] is False
    assert any(
        c["name"] == "governance_guardrails" for c in forced["criteria"]
    )


def test_governance_pass_leaves_gate_unchanged():
    e = _make_eval(det_auroc=0.95, base_auroc=0.70, det_far=0.01, base_far=0.05)
    gate = health_acceptance_gate(e)
    passing_gov = {
        "governance_status": "PASS",
        "holdout_isolation": {"isolated": True, "leaked_keys": []},
        "import_connector_scan": {"clean": True},
        "axis_taxonomy": {"ok": True},
        "normalization_coverage": {"ok": True},
    }
    forced = apply_governance_to_verdict(gate, passing_gov)
    assert forced["verdict"] == gate["verdict"]
    assert forced["passed"] is True


# --------------------------------------------------------------------------- #
# End-to-end pipeline (real detector + baseline + injection)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def normal_frames() -> pd.DataFrame:
    return _synthetic_2025_normal()


def test_evaluate_detector_vs_baseline_runs_end_to_end(normal_frames):
    axes = list(TEST_AXES)
    det = fit_health_detector(normal_frames, axes=axes, seed=0, epochs=10, batch_size=64)
    suite = fit_health_baseline_suite(normal_frames, axes=axes)
    injected = inject_faults(
        normal_frames,
        seed=29,
        n_episodes_per_kind=2,
        drift_window=60,
        stuck_window=40,
        envelope_window=40,
        spike_tail=4,
    )
    e = evaluate_detector_vs_baseline(
        detector=det, baseline_suite=suite, injected=injected
    )
    assert 0.0 <= e["detector"]["auroc"] <= 1.0
    assert 0.0 <= e["baseline"]["auroc"] <= 1.0
    assert 0.0 <= e["detector"]["false_alarm_rate"] <= 1.0
    assert 0.0 <= e["baseline"]["false_alarm_rate"] <= 1.0
    gate = health_acceptance_gate(e)
    assert gate["verdict"] in ("PASS", "FAIL")


def test_auroc_helper_handles_degenerate_labels():
    # All-positive or all-negative => AUROC is 0.5 by contract (no fabricated pass).
    from aquaoptima.advisory.health_gate import _auroc

    scores = np.array([0.1, 0.5, 0.9])
    np.testing.assert_allclose(_auroc(scores, np.array([1, 1, 1])), 0.5)
    np.testing.assert_allclose(_auroc(scores, np.array([0, 0, 0])), 0.5)


def test_auroc_helper_matches_known_value():
    # Two perfectly separable groups => AUROC = 1.0.
    from aquaoptima.advisory.health_gate import _auroc

    scores = np.array([0.1, 0.2, 0.3, 0.9, 0.95, 1.0])
    labels = np.array([0, 0, 0, 1, 1, 1])
    np.testing.assert_allclose(_auroc(scores, labels), 1.0)
    # Random / interleaved => 0.5 +/- epsilon
    scores2 = np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.7])
    labels2 = np.array([0, 1, 0, 1, 0, 1])
    auroc2 = _auroc(scores2, labels2)
    assert auroc2 == pytest.approx(1.0)  # still separable


def test_default_gate_rule_text_is_documented():
    assert "auroc" in FROZEN_GATE_RULE_TEXT.lower()
    assert "false_alarm_rate" in FROZEN_GATE_RULE_TEXT.lower()
    assert "0.02" in FROZEN_GATE_RULE_TEXT
    assert "0.70" in FROZEN_GATE_RULE_TEXT
