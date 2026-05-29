"""Smoke training test (AOPSO Sprint 24).

Trains 2 epochs on a small (<=5000-row) subset and asserts:
* train_loss[1] < train_loss[0] (loss strictly decreases epoch 1 -> 2), and
* model_best.pt is written.

To keep the test fast (Sprint 23 timeout lesson), we build a tiny synthetic
fixture CSV with the real Yilan column names, plus a matching split manifest and
normalization stats, instead of loading the 489k-row production CSV.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from aquaoptima.dataio.yilan_axis_map import (
    CANONICAL_AXIS_TO_COLUMN,
    MODE_AUTO_COLUMN,
    MODE_MANUAL_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_FORMAT,
)
from aquaoptima.training.dphm_trainer import load_config, train

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


def _build_fixture(tmp_path, n_rows=600):
    """Write a tiny contiguous (gap-free, 60s cadence) auto-mode CSV + split + stats."""
    rng = np.random.default_rng(0)
    ts = pd.date_range("2025-06-01 00:00:00", periods=n_rows, freq="60s")
    df = pd.DataFrame({TIMESTAMP_COLUMN: ts.strftime(TIMESTAMP_FORMAT)})
    df[MODE_AUTO_COLUMN] = True
    df[MODE_MANUAL_COLUMN] = False

    # Smooth-ish signals so a 1-step predictor can actually reduce loss.
    t = np.arange(n_rows)
    cols = {}
    cols["system_flow_rate"] = 1500 + 300 * np.sin(t / 20.0) + rng.normal(0, 5, n_rows)
    cols["tb_system_real_power"] = 150 + 30 * np.sin(t / 25.0) + rng.normal(0, 1, n_rows)
    cols["P_1531A_frequency"] = 42 + 2 * np.sin(t / 15.0) + rng.normal(0, 0.1, n_rows)
    cols["P_1531A_status"] = (np.sin(t / 40.0) > -0.9).astype(float)  # mostly 1
    cols["tb_system_predicted_flow_rate"] = (
        1520 + 280 * np.sin(t / 21.0) + rng.normal(0, 5, n_rows)
    )
    cols["tank_level"] = 4.6 + 0.4 * np.sin(t / 30.0) + rng.normal(0, 0.01, n_rows)
    cols["system_pressure"] = 1.56 + 0.2 * np.sin(t / 18.0) + rng.normal(0, 0.005, n_rows)
    cols["tb_system_head"] = (np.sin(t / 35.0) > -0.95).astype(float)  # mostly 1 binary
    for c, v in cols.items():
        df[c] = v

    csv_path = tmp_path / "fixture.csv"
    df.to_csv(csv_path, index=False)

    # Split manifest: train = first 400 rows, val = next 150 rows (contiguous).
    manifest = {
        "split_version": "fixture",
        "splits": {
            "train": {"mode": "auto", "row_index_ranges": [[0, 399]]},
            "val": {"mode": "auto", "row_index_ranges": [[400, 549]]},
        },
    }
    manifest_path = tmp_path / "split.json"
    manifest_path.write_text(json.dumps(manifest))

    # Normalization stats over the active axes (computed from fixture train rows).
    stats = {"split_version": "fixture", "active_axes": ACTIVE_AXES, "stats": {}}
    train_df = df.iloc[0:400]
    for axis in ACTIVE_AXES:
        col = CANONICAL_AXIS_TO_COLUMN[axis]
        vals = pd.to_numeric(train_df[col]).to_numpy(dtype=float)
        mu = float(vals.mean())
        sigma = float(vals.std()) or 1.0
        stats["stats"][axis] = {"source_column": col, "mu": mu, "sigma": sigma}
    stats_path = tmp_path / "stats.json"
    stats_path.write_text(json.dumps(stats))

    return str(csv_path), str(manifest_path), str(stats_path)


def test_smoke_train_2_epochs_loss_decreases(tmp_path):
    csv_path, manifest_path, stats_path = _build_fixture(tmp_path)
    ckpt = tmp_path / "ckpt"

    result = train(
        config=None,
        split_manifest=manifest_path,
        norm_stats=stats_path,
        epochs=2,
        batch_size=32,
        lr=1e-3,
        subset_rows=5000,
        checkpoint_dir=str(ckpt),
        csv_path=csv_path,
        verbose=False,
    )

    losses = result["train_losses"]
    assert len(losses) == 2
    for v in losses:
        assert np.isfinite(v)
    # STOP condition: loss must strictly decrease epoch1 -> epoch2.
    assert losses[1] < losses[0], f"train loss did not decrease: {losses}"

    assert (ckpt / "model_best.pt").exists()
    assert (ckpt / "model_final.pt").exists()
    assert (ckpt / "training_log.csv").exists()
    assert (ckpt / "normalization_stats.json").exists()

    assert result["n_features"] == 8
    assert result["n_axes"] == 8


def test_config_yaml_loads():
    import os

    repo = os.path.join(os.path.dirname(__file__), "..", "..")
    cfg = load_config(os.path.join(repo, "configs", "yilan_dphm_v1.yaml"))
    assert cfg["train"]["scheduler"]["patience"] == 5
    assert cfg["train"]["scheduler"]["factor"] == 0.5
    assert cfg["train"]["early_stopping"]["patience"] == 10
