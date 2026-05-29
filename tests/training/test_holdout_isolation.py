"""Holdout-isolation tests (AOPSO Sprint 25).

Asserts the March 2026 holdout window does not intersect any train/val split
window. Uses the REAL committed split manifest (re-check) plus synthetic
leak/non-leak manifests to exercise the guard both ways.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aquaoptima.training.evaluation import assert_holdout_isolated

REPO = Path(__file__).resolve().parents[2]
REAL_MANIFEST = REPO / "data" / "splits" / "yilan_2025_split_v1.json"


def test_real_manifest_march2026_holdout_is_isolated():
    manifest = json.loads(REAL_MANIFEST.read_text())
    result = assert_holdout_isolated(manifest, holdout_key="holdout_march2026")
    assert result["isolated"] is True
    assert result["train_val_intersection"] == {}
    # Sanity: the committed manifest's train/val are all 2025 days, holdout 2026-03.
    assert result["holdout_window"]["start"].startswith("2026-03")


def test_synthetic_leak_is_detected():
    # A manifest where a 'train' day falls inside the March-2026 holdout window.
    manifest = {
        "splits": {
            "train": {
                "days": ["2025-06-01", "2026-03-15"],  # <- leaked 2026-03 day
                "date_range": {"start": "2025-06-01T00:00:00", "end": "2026-03-15T00:00:00"},
            },
            "val": {"days": ["2025-07-01"], "date_range": {}},
            "holdout_march2026": {
                "date_range": {"start": "2026-03-01T00:00:00", "end": "2026-03-31T23:59:59"},
            },
        }
    }
    with pytest.raises(ValueError, match="data leakage"):
        assert_holdout_isolated(manifest, holdout_key="holdout_march2026")


def test_synthetic_clean_manifest_passes():
    manifest = {
        "splits": {
            "train": {
                "days": ["2025-06-01", "2025-11-30"],
                "date_range": {"start": "2025-06-01T00:00:00", "end": "2025-11-30T23:59:59"},
            },
            "val": {
                "days": ["2025-12-01"],
                "date_range": {"start": "2025-12-01T00:00:00", "end": "2025-12-28T00:00:00"},
            },
            "holdout_march2026": {
                "date_range": {"start": "2026-03-01T00:00:00", "end": "2026-03-31T23:59:59"},
            },
        }
    }
    result = assert_holdout_isolated(manifest, holdout_key="holdout_march2026")
    assert result["isolated"] is True


def test_holdout_must_be_march_2026():
    manifest = {
        "splits": {
            "train": {"days": [], "date_range": {}},
            "holdout_march2026": {
                "date_range": {"start": "2025-03-01T00:00:00", "end": "2025-03-31T23:59:59"},
            },
        }
    }
    with pytest.raises(ValueError, match="not the March-2026 benchmark"):
        assert_holdout_isolated(manifest, holdout_key="holdout_march2026")


def test_missing_date_range_raises():
    manifest = {"splits": {"holdout_march2026": {}}}
    with pytest.raises(ValueError, match="no date_range"):
        assert_holdout_isolated(manifest, holdout_key="holdout_march2026")
