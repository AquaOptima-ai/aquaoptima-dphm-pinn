"""Sprint 23: normalization stats tests.

Loads cached z-score stats, applies them to the training sample, and asserts
per-axis mean ~= 0 and std ~= 1 within tolerance. Also verifies the
zero-coverage axis (edge_valve_position) is excluded.
"""

from __future__ import annotations

import numpy as np

from aquaoptima.dataio import split_builder
from aquaoptima.dataio.yilan_axis_map import CANONICAL_AXIS_TO_COLUMN
from aquaoptima.dataio.yilan_profiler import load_frame
from aquaoptima.training import normalization


def _stats(yilan_csv):
    manifest = split_builder.build_split(yilan_csv)
    stats = normalization.compute_train_stats(manifest, csv_path=yilan_csv)
    return manifest, stats


def test_active_axes_have_finite_stats(yilan_csv):
    _, stats = _stats(yilan_csv)
    assert stats["active_axes"], "expected at least one active axis"
    for axis in stats["active_axes"]:
        s = stats["stats"][axis]
        assert np.isfinite(s["mu"])
        assert np.isfinite(s["sigma"]) and s["sigma"] > 0


def test_valve_position_excluded(yilan_csv):
    _, stats = _stats(yilan_csv)
    assert "edge_valve_position" in stats["excluded_axes"]
    assert "edge_valve_position" not in stats["active_axes"]


def test_round_trip_to_disk(yilan_csv, tmp_path):
    _, stats = _stats(yilan_csv)
    path = tmp_path / "stats.json"
    normalization.write_stats(stats, path)
    loaded = normalization.load_stats(path)
    assert loaded["active_axes"] == stats["active_axes"]


def test_applied_normalization_is_zero_mean_unit_std(yilan_csv):
    manifest, stats = _stats(yilan_csv)
    # Reconstruct the TRAIN sample matrix in active-axis order.
    df = load_frame(yilan_csv)
    indices = []
    for start, end in manifest["splits"]["train"]["row_index_ranges"]:
        indices.extend(range(start, end + 1))
    sub = df.iloc[indices]
    axes = stats["active_axes"]
    cols = [CANONICAL_AXIS_TO_COLUMN[a] for a in axes]
    raw = sub[cols].to_numpy(dtype=float)

    normed = normalization.apply_normalization(raw, axes, stats)

    means = np.nanmean(normed, axis=0)
    stds = np.nanstd(normed, axis=0)
    assert np.allclose(means, 0.0, atol=1e-6), f"means not ~0: {means}"
    assert np.allclose(stds, 1.0, atol=1e-6), f"stds not ~1: {stds}"
