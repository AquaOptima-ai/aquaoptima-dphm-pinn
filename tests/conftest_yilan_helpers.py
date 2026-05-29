"""Shared fixture: a tiny synthetic Yilan-shaped CSV for fast Sprint 23 tests.

Builds a CSV with the real column names (timestamp, auto, manual, the backing
axis columns) including: multiple months with differing auto/manual mix, two
injected temporal gaps (> 5 min), and a zero-coverage edge_valve_position
(absent column). This keeps tests deterministic and fast (no 489k-row read).
"""

from __future__ import annotations

from pathlib import Path

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

# Three intentional gaps -> profiler must detect exactly 3:
#   (1) 30-min gap within March auto, (2) March->April transition,
#   (3) April->May transition.
EXPECTED_GAP_COUNT = 3


def _build_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    # Segment plan: (month-day, n_samples, auto, manual)
    # Three contiguous segments separated by gaps; mix of modes per month.
    # Month 3 (auto), gap, more of month 3 (auto), big gap into month 4 manual.
    base = pd.Timestamp("2025-03-01 00:00:00")
    cadence = pd.Timedelta(seconds=60)

    def emit(start_ts, n, auto, manual):
        ts = start_ts
        for _ in range(n):
            rows.append((ts, auto, manual))
            ts = ts + cadence
        return ts  # next contiguous ts

    # Segment A: auto-mode March, 200 contiguous samples.
    next_ts = emit(base, 200, True, False)
    # GAP 1: skip 30 minutes (still within March, auto-mode -> train).
    next_ts = next_ts + pd.Timedelta(minutes=30)
    # Segment B: auto-mode March still, 150 contiguous samples (train).
    next_ts = emit(next_ts, 150, True, False)
    # GAP 2: jump to April manual-mode (large gap, different month/mode).
    apr = pd.Timestamp("2025-04-10 00:00:00")
    # Segment C: manual-mode April, 120 contiguous samples (manual_slice).
    emit(apr, 120, False, True)
    # Segment D: auto-mode MAY, 180 contiguous samples. This is the most
    # recent whole auto-mode month -> becomes the held-out validation window,
    # temporally disjoint (different month) from the March train rows.
    may = pd.Timestamp("2025-05-05 00:00:00")
    emit(may, 180, True, False)

    df = pd.DataFrame(rows, columns=[TIMESTAMP_COLUMN, MODE_AUTO_COLUMN, MODE_MANUAL_COLUMN])
    df[TIMESTAMP_COLUMN] = df[TIMESTAMP_COLUMN].dt.strftime(TIMESTAMP_FORMAT)

    n = len(df)
    # Populate backing axis columns (all axes that have a column) with signal.
    for axis, col in CANONICAL_AXIS_TO_COLUMN.items():
        if col is None:
            continue  # edge_valve_position -> intentionally absent (0% coverage)
        df[col] = rng.normal(loc=10.0 + hash(axis) % 5, scale=2.0, size=n)
    return df


@pytest.fixture(scope="session")
def yilan_csv(tmp_path_factory) -> str:
    df = _build_dataframe()
    path = tmp_path_factory.mktemp("yilan_data") / "source1_2025_subset.csv"
    df.to_csv(path, index=False)
    return str(path)
