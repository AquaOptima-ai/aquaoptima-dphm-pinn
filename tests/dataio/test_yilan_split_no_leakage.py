"""Sprint 23: leakage-free split tests.

Asserts train/val date ranges are day-disjoint, March 2026 is excluded from
the 2025 splits, and the gap count recorded by the profiler matches the
synthetic fixture's injected gaps.
"""

from __future__ import annotations

from aquaoptima.dataio import split_builder
from aquaoptima.dataio import yilan_profiler
from tests.conftest_yilan_helpers import EXPECTED_GAP_COUNT


def test_train_val_day_disjoint(yilan_csv):
    manifest = split_builder.build_split(yilan_csv)
    train_days = set(manifest["splits"]["train"]["days"])
    val_days = set(manifest["splits"]["val"]["days"])
    assert train_days, "train split must contain days"
    assert val_days, "val split must contain days"
    assert train_days.isdisjoint(val_days), (
        f"train/val calendar-day overlap: {sorted(train_days & val_days)}"
    )
    assert manifest["leakage_check"]["train_val_day_disjoint"] is True


def test_train_val_date_ranges_disjoint(yilan_csv):
    manifest = split_builder.build_split(yilan_csv)
    tr = manifest["splits"]["train"]["date_range"]
    va = manifest["splits"]["val"]["date_range"]
    # Ranges must not interleave on calendar days (val is most-recent month).
    assert tr["end"] is not None and va["start"] is not None
    assert tr["end"][:10] < va["start"][:10] or va["end"][:10] < tr["start"][:10]


def test_march_2026_excluded_from_2025_splits(yilan_csv):
    manifest = split_builder.build_split(yilan_csv)
    for key in ("train", "val", "manual_slice"):
        for day in manifest["splits"][key]["days"]:
            assert not day.startswith("2026-"), f"{key} contains 2026 day {day}"
    # Holdout is reference-only with zero rows and a 2026 date range.
    holdout = manifest["splits"]["holdout_march2026"]
    assert holdout["row_count"] == 0
    assert holdout["date_range"]["start"].startswith("2026-03")
    assert manifest["leakage_check"]["march_2026_excluded_from_2025"] is True


def test_gap_count_matches_profiler(yilan_csv):
    profile = yilan_profiler.profile(yilan_csv)
    assert len(profile.gap_intervals) == EXPECTED_GAP_COUNT
    assert profile.mode_coverage["gap_count"] == EXPECTED_GAP_COUNT


def test_manual_slice_is_manual_mode(yilan_csv):
    manifest = split_builder.build_split(yilan_csv)
    manual = manifest["splits"]["manual_slice"]
    assert manual["mode"] == "manual"
    assert manual["row_count"] > 0


def test_train_is_auto_mode(yilan_csv):
    manifest = split_builder.build_split(yilan_csv)
    assert manifest["splits"]["train"]["mode"] == "auto"
    assert manifest["splits"]["train"]["row_count"] > 0
