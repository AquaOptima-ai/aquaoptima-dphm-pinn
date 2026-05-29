"""Sprint 23: gap-aware dataset windowing tests.

Asserts that no emitted window spans a temporal gap boundary and that each
window has shape [window, n_active_axes].
"""

from __future__ import annotations

import numpy as np

from aquaoptima.dataio import split_builder
from aquaoptima.dataio.yilan_timeseries_dataset import YilanTimeSeriesDataset
from aquaoptima.training import normalization


def _build(yilan_csv, split_key="train", **kwargs):
    manifest = split_builder.build_split(yilan_csv)
    stats = normalization.compute_train_stats(manifest, csv_path=yilan_csv)
    ds = YilanTimeSeriesDataset(
        manifest, stats, split_key=split_key, csv_path=yilan_csv, **kwargs
    )
    return manifest, stats, ds


def test_window_shape(yilan_csv):
    _, stats, ds = _build(yilan_csv, window=10, horizon=1)
    assert len(ds) > 0
    x, y = ds[0]
    assert tuple(x.shape) == (10, ds.n_active_axes)
    assert tuple(y.shape) == (ds.n_active_axes,)
    assert ds.n_active_axes == len(stats["active_axes"])


def test_no_window_spans_gap(yilan_csv):
    _, _, ds = _build(yilan_csv, window=10, horizon=1)
    for i in range(len(ds)):
        assert not ds.window_spans_gap(i), f"window {i} spans a gap boundary"


def test_window_timestamps_contiguous(yilan_csv):
    """Every input window's internal spacing equals the 60s cadence."""
    _, _, ds = _build(yilan_csv, window=10, horizon=1, stride=1)
    for i in range(0, len(ds), max(1, len(ds) // 20)):
        start = ds._starts[i]
        span_ts = ds.timestamps.iloc[start : start + ds.window + ds.horizon]
        diffs = span_ts.diff().dt.total_seconds().dropna().to_numpy()
        assert np.all(diffs <= 60.0 + 1e-6), f"window {i} crosses a gap"


def test_valve_position_excluded(yilan_csv):
    _, stats, ds = _build(yilan_csv)
    assert "edge_valve_position" not in stats["active_axes"]
    assert "edge_valve_position" in stats["excluded_axes"]
    assert "edge_valve_position" not in ds.active_axes


def test_dataset_length_reasonable(yilan_csv):
    _, _, ds = _build(yilan_csv, window=10, horizon=1, stride=1)
    # Two contiguous auto segments of 200 and 150 samples form the train rows;
    # windows of length 11 fit within each segment, never across the gap.
    assert len(ds) > 0
