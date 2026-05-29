"""Evaluation-harness tests (AOPSO Sprint 25).

Runs the evaluator on a TINY synthetic March-2026 holdout fixture and asserts:
* the scorecard's ``shadow_report`` payload validates against the real
  ``ShadowRuntimeReport`` contract shape (not a fork),
* per-axis MSE/MAE keys are present for the continuous axes and accuracy keys
  for the binary axes (8 active axes total; edge_valve_position N/A/masked),
* the holdout-isolation check ran and the March row/window counts are real.

NO heavy training or full-March read happens here: we build a small fixture CSV
dated 2026-03 and an untrained model, and assert SHAPE/PLUMBING only. We do NOT
assert PASS/FAIL on the gate (that depends on real trained-model numbers, which
must never be faked).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import torch

from aquaoptima.dataio.yilan_axis_map import (
    CANONICAL_AXIS_TO_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_FORMAT,
)
from aquaoptima.models.tcn_dphm import TCN_DPHM
from aquaoptima.training.evaluation import evaluate
from aquaoptima_contracts.runtime.shadow_report import ShadowRuntimeReport

ACTIVE_AXES = [
    "edge_flow",
    "edge_power",
    "edge_pump_speed",
    "edge_status",
    "node_demand",
    "node_level",
    "node_pressure",
    "node_status",
]
CONTINUOUS = {
    "edge_flow",
    "edge_power",
    "edge_pump_speed",
    "node_demand",
    "node_level",
    "node_pressure",
}
BINARY = {"node_status", "edge_status"}


def _build_march_fixture(tmp_path, n_rows=400):
    """A tiny contiguous (60s cadence) March-2026 CSV + matching stats + manifest."""
    rng = np.random.default_rng(7)
    ts = pd.date_range("2026-03-10 00:00:00", periods=n_rows, freq="60s")
    df = pd.DataFrame({TIMESTAMP_COLUMN: ts.strftime(TIMESTAMP_FORMAT)})
    t = np.arange(n_rows)
    cols = {
        "system_flow_rate": 1500 + 300 * np.sin(t / 20.0) + rng.normal(0, 5, n_rows),
        "tb_system_real_power": 150 + 30 * np.sin(t / 25.0) + rng.normal(0, 1, n_rows),
        "P_1531A_frequency": 42 + 2 * np.sin(t / 15.0) + rng.normal(0, 0.1, n_rows),
        "P_1531A_status": (np.sin(t / 40.0) > -0.9).astype(float),
        "tb_system_predicted_flow_rate": 1520 + 280 * np.sin(t / 21.0) + rng.normal(0, 5, n_rows),
        "tank_level": 4.6 + 0.4 * np.sin(t / 30.0) + rng.normal(0, 0.01, n_rows),
        "system_pressure": 1.56 + 0.2 * np.sin(t / 18.0) + rng.normal(0, 0.005, n_rows),
        "tb_system_head": (np.sin(t / 35.0) > -0.95).astype(float),
    }
    for c, v in cols.items():
        df[c] = v
    csv_path = tmp_path / "march2026_fixture.csv"
    df.to_csv(csv_path, index=False)

    # Normalization stats over the active axes.
    stats = {"split_version": "fixture", "active_axes": ACTIVE_AXES, "stats": {}}
    for axis in ACTIVE_AXES:
        col = CANONICAL_AXIS_TO_COLUMN[axis]
        vals = pd.to_numeric(df[col]).to_numpy(dtype=float)
        mu = float(vals.mean())
        sigma = float(vals.std()) or 1.0
        stats["stats"][axis] = {"source_column": col, "mu": mu, "sigma": sigma}
    stats_path = tmp_path / "stats.json"
    stats_path.write_text(json.dumps(stats))

    # Manifest: 2025 train/val days (isolated from 2026-03), reference holdout.
    manifest = {
        "split_version": "fixture",
        "splits": {
            "train": {
                "days": ["2025-06-01", "2025-07-01"],
                "date_range": {"start": "2025-06-01T00:00:00", "end": "2025-07-01T00:00:00"},
            },
            "val": {
                "days": ["2025-08-01"],
                "date_range": {"start": "2025-08-01T00:00:00", "end": "2025-08-02T00:00:00"},
            },
            "holdout_march2026": {
                "date_range": {"start": "2026-03-01T00:00:00", "end": "2026-03-31T23:59:59"},
            },
        },
    }
    manifest_path = tmp_path / "split.json"
    manifest_path.write_text(json.dumps(manifest))

    return str(csv_path), str(manifest_path), str(stats_path), stats


def test_evaluate_produces_contract_shaped_scorecard(tmp_path):
    csv_path, manifest_path, stats_path, stats = _build_march_fixture(tmp_path)
    # Small untrained model (shape-correct); we are testing plumbing, not skill.
    torch.manual_seed(0)
    model = TCN_DPHM.from_norm_stats(stats)

    scorecard = evaluate(
        checkpoint="UNUSED-model-passed-directly",
        split_manifest=manifest_path,
        norm_stats=stats_path,
        holdout_key="holdout_march2026",
        march_csv=csv_path,
        config={"data": {"window": 10, "horizon": 1, "stride": 1}},
        model=model,
    )

    # --- contract validation: round-trips through the REAL contract ---
    payload = scorecard["shadow_report"]
    report = ShadowRuntimeReport.from_dict(payload)
    assert isinstance(report, ShadowRuntimeReport)
    assert report.frame_count == len(report.steps) == 1
    step = report.steps[0]
    # Continuous axes carry MSE/MAE in the contract step.
    for axis in CONTINUOUS:
        assert axis in step.mse_by_axis
        assert axis in step.mae_by_axis

    # --- per-axis metric keys for all 8 active axes ---
    dphm = scorecard["dphm_metrics"]
    assert set(dphm.keys()) == set(ACTIVE_AXES)
    for axis in CONTINUOUS:
        assert "mse" in dphm[axis] and "mae" in dphm[axis]
        assert np.isfinite(dphm[axis]["mse"]) and np.isfinite(dphm[axis]["mae"])
    for axis in BINARY:
        assert dphm[axis]["accuracy"] is not None
        assert 0.0 <= dphm[axis]["accuracy"] <= 1.0

    # --- edge_valve_position is N/A / masked ---
    assert scorecard["masked_axes"] == {"edge_valve_position": "N/A"}
    assert "edge_valve_position" not in dphm

    # --- baseline scored on identical holdout, deltas present ---
    assert set(scorecard["baseline_metrics"].keys()) == set(ACTIVE_AXES)
    assert set(scorecard["dphm_vs_baseline"].keys()) == set(ACTIVE_AXES)
    assert scorecard["baseline"] == "mvp_persistence"

    # --- gate verdict present (PASS or FAIL -- not asserted; numbers are real) ---
    assert scorecard["acceptance_gate"]["verdict"] in {"PASS", "FAIL"}
    assert isinstance(scorecard["acceptance_gate"]["passed"], bool)

    # --- holdout isolation ran; real row/window counts ---
    assert scorecard["holdout_isolation"]["isolated"] is True
    assert scorecard["march_2026_rows_loaded"] > 0
    assert scorecard["march_2026_windows_scored"] > 0
    assert scorecard["holdout_date_range"]["start"].startswith("2026-03")
    assert scorecard["advisory_only"] is True
    assert scorecard["safety"]["fail_blocks_packaging"] is True


def test_evaluate_stops_on_non_march_holdout(tmp_path):
    csv_path, _, stats_path, _ = _build_march_fixture(tmp_path)
    # Manifest whose holdout window is 2025-03, not 2026-03.
    manifest = {
        "splits": {
            "train": {"days": [], "date_range": {}},
            "holdout_march2026": {
                "date_range": {"start": "2025-03-01T00:00:00", "end": "2025-03-31T23:59:59"},
            },
        }
    }
    mp = tmp_path / "bad_split.json"
    mp.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="not the March-2026 benchmark"):
        evaluate(
            checkpoint="x",
            split_manifest=str(mp),
            norm_stats=stats_path,
            march_csv=csv_path,
        )
