"""Sprint 30 holdout-evaluation tests.

These tests exercise the **mechanics** of the locked-March-2026 out-of-sample
evaluation harness on tiny synthetic fixtures only -- they NEVER read the real
129 MB March CSV. The honest model verdict on the real holdout is produced by
running ``scripts/sprint30_holdout_eval.py`` in CI, NOT here.

Coverage:
  * backing-column -> canonical-axis rename maps all 8 active axes correctly.
  * the eval pipeline runs end to end on a March-shaped synthetic frame and
    emits a real ``gate_version='v2'`` verdict dict (SHAPE only; we deliberately
    do NOT assert PASS/FAIL on synthetic data).
  * leakage tripwire: passing a 2026-03 key into ``fit_health_detector`` raises
    :class:`LeakageError` BEFORE any fit work happens.
  * governance FAIL still forces verdict=FAIL after the v2 gate composes through
    ``apply_governance_to_verdict``.

All subset/fixture-based, fully deterministic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import sprint30_holdout_eval as s30  # noqa: E402

from aquaoptima.advisory.health_baselines import LeakageError  # noqa: E402
from aquaoptima.advisory.health_detector import fit_health_detector  # noqa: E402
from aquaoptima.advisory.label_schema import active_axes_ordered  # noqa: E402
from aquaoptima.advisory.schema_validation import (  # noqa: E402
    apply_governance_to_verdict,
)
from aquaoptima.dataio.yilan_axis_map import (  # noqa: E402
    CANONICAL_AXIS_TO_COLUMN,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
_ACTIVE_AXES = tuple(a for a in active_axes_ordered() if a in CANONICAL_AXIS_TO_COLUMN
                     and CANONICAL_AXIS_TO_COLUMN[a] is not None)


def _backing_columns() -> dict[str, str]:
    return {
        axis: col
        for axis, col in CANONICAL_AXIS_TO_COLUMN.items()
        if col is not None
    }


def _march_backing_frame(n: int = 800, seed: int = 11) -> pd.DataFrame:
    """A tiny synthetic 'March-shaped' frame using the REAL Yilan backing column names."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-03-05 00:00:00", periods=n, freq="60s")
    flow = rng.normal(loc=1500.0, scale=70.0, size=n)
    speed = rng.normal(loc=42.0, scale=1.5, size=n)
    power = 0.05 * flow + 1.5 * speed + rng.normal(loc=0.0, scale=2.0, size=n)
    pressure = rng.normal(loc=1.56, scale=0.05, size=n)
    level = rng.normal(loc=4.57, scale=0.10, size=n)
    demand = rng.normal(loc=1520.0, scale=65.0, size=n)
    head = rng.normal(loc=18.3, scale=0.5, size=n)
    status = np.clip(rng.normal(loc=0.9999, scale=0.005, size=n), 0.0, 1.0)
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "system_pressure": pressure,
            "tank_level": level,
            "tb_system_predicted_flow_rate": demand,
            "tb_system_head": head,
            "system_flow_rate": flow,
            "P_1531A_frequency": speed,
            "P_1531A_status": status,
            "tb_system_real_power": power,
        }
    )
    return df


def _train_frame_2025(n: int = 2000, seed: int = 19) -> pd.DataFrame:
    """A tiny synthetic 2025 normal frame, canonical-axis-named, with timestamps."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-05-01 00:00:00", periods=n, freq="60s").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    flow = rng.normal(loc=1500.0, scale=80.0, size=n)
    speed = rng.normal(loc=42.0, scale=1.5, size=n)
    power = 0.05 * flow + 1.5 * speed + rng.normal(loc=0.0, scale=2.0, size=n)
    pressure = rng.normal(loc=1.56, scale=0.05, size=n)
    level = rng.normal(loc=4.57, scale=0.10, size=n)
    demand = rng.normal(loc=1520.0, scale=65.0, size=n)
    head = rng.normal(loc=18.3, scale=0.5, size=n)
    status = np.clip(rng.normal(loc=0.9999, scale=0.005, size=n), 0.0, 1.0)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "edge_flow": flow,
            "edge_power": power,
            "edge_pump_speed": speed,
            "edge_status": status,
            "node_demand": demand,
            "node_level": level,
            "node_pressure": pressure,
            "node_status": head,
        }
    )


# --------------------------------------------------------------------------- #
# 1) backing -> canonical rename
# --------------------------------------------------------------------------- #
def test_rename_backing_to_canonical_maps_eight_axes():
    df = _march_backing_frame()
    out = s30.rename_backing_to_canonical(df)

    # Every active (non-masked) canonical axis must be present after the rename.
    for axis in _ACTIVE_AXES:
        assert axis in out.columns, f"missing canonical axis {axis!r}"

    # The original backing column names must be gone (renamed in place).
    for axis, backing in _backing_columns().items():
        if backing in df.columns and backing != axis:
            assert backing not in out.columns, (
                f"backing column {backing!r} for {axis!r} was not renamed"
            )

    # Timestamp column must be preserved.
    assert "timestamp" in out.columns


def test_rename_backing_to_canonical_handles_partial_columns():
    df = _march_backing_frame()[["timestamp", "system_flow_rate", "system_pressure"]]
    out = s30.rename_backing_to_canonical(df)
    assert "edge_flow" in out.columns
    assert "node_pressure" in out.columns
    assert "edge_power" not in out.columns  # column wasn't there, stays absent


# --------------------------------------------------------------------------- #
# 2) end-to-end eval pipeline on the tiny synthetic March-shaped fixture
# --------------------------------------------------------------------------- #
def test_eval_pipeline_emits_v2_verdict_dict():
    train = _train_frame_2025(n=2000)
    march_backing = _march_backing_frame(n=1500)
    march = s30.rename_backing_to_canonical(march_backing)
    march["timestamp"] = march["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    sc = s30.build_sprint30_scorecard(
        train_df=train,
        march_df=march,
        axes=list(_ACTIVE_AXES),
        detector_seed=0,
        fault_seed=29,
        epochs=4,
        n_episodes_per_kind=2,
        drift_window=80,
        stuck_window=60,
        envelope_window=40,
        run_governance=False,
    )

    # Shape contract: top-level scorecard sections.
    assert sc["sprint"] == 30
    assert sc["pillar"] == "A_health"
    assert sc["safety"]["evaluation_mode"] == "offline_only"
    assert sc["safety"]["influences_control"] is False
    assert sc["safety"]["write_path"] == "none"
    assert sc["holdout_window"]["all_in_2026_03"] is True

    # Gate v2 contract: verdict / gate_version / metrics / criteria.
    gate = sc["acceptance_gate"]
    assert gate["gate_version"] == "v2"
    assert gate["verdict"] in {"PASS", "FAIL"}
    assert isinstance(gate["criteria"], list) and len(gate["criteria"]) == 4
    metrics = gate["metrics"]
    for key in (
        "detector_auroc",
        "baseline_auroc",
        "detector_false_alarm_rate",
        "baseline_false_alarm_rate",
        "detector_mean_lead_time",
        "baseline_mean_lead_time",
    ):
        assert key in metrics

    # Unsupervised raw-March flag rates must be in [0, 1].
    raw = sc["raw_march_flag_rates"]
    for key in ("detector_flag_rate", "baseline_flag_rate"):
        assert key in raw and 0.0 <= raw[key] <= 1.0

    # Pre-registration metadata
    assert sc["frozen_gate_v2"]["preregistered_before_evaluation"] is True
    assert sc["frozen_gate_v2"]["tuned_to_outcome"] is False


# --------------------------------------------------------------------------- #
# 3) leakage tripwire: a 2026-03 key in fit input must raise
# --------------------------------------------------------------------------- #
def test_fit_detector_rejects_march_2026_keys():
    leaked = _train_frame_2025(n=400).copy()
    # Stamp ONE row inside the locked-holdout window.
    leaked.loc[10, "timestamp"] = "2026-03-15 12:00:00"
    with pytest.raises(LeakageError):
        fit_health_detector(leaked, axes=list(_ACTIVE_AXES), seed=0, epochs=2)


# --------------------------------------------------------------------------- #
# 4) governance FAIL forces v2 verdict to FAIL
# --------------------------------------------------------------------------- #
def test_governance_fail_forces_v2_verdict_fail():
    passing_v2_gate = {
        "verdict": "PASS",
        "passed": True,
        "gate_version": "v2",
        "criteria": [
            {"name": "detector_auroc_noninferior", "passed": True, "detail": {}},
            {"name": "detector_false_alarm_materially_better", "passed": True, "detail": {}},
            {"name": "detector_auroc_minimum", "passed": True, "detail": {}},
            {"name": "detector_lead_time_noninferior", "passed": True, "detail": {}},
        ],
        "metrics": {},
    }
    forced = apply_governance_to_verdict(
        passing_v2_gate, {"governance_status": "FAIL"}
    )
    assert forced["verdict"] == "FAIL"
    assert forced["passed"] is False
    names = [c["name"] for c in forced["criteria"]]
    assert "governance_guardrails" in names
