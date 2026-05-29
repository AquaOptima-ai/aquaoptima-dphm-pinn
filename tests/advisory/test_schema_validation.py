"""Sprint 27 schema / unit validator tests.

Covers :func:`validate_axis_taxonomy` and :func:`validate_normalization_coverage`:

* taxonomy passes on the real label-schema (the eight expected active axes,
  every axis has a unit and a backing column, masked axis maps to ``None``);
* removing a unit (via the ``units`` injection parameter -- no module mutation)
  fails the taxonomy;
* an extra / missing active axis fails the taxonomy;
* normalization coverage passes on a synthetic stats payload covering exactly the
  eight axes with finite mu/sigma and sigma>0;
* normalization fails on a missing axis, an extra axis, or sigma<=0.
"""

from __future__ import annotations

import copy
import json

import pytest

from aquaoptima.advisory.label_schema import AXIS_UNITS
from aquaoptima.advisory.schema_validation import (
    EXPECTED_ACTIVE_AXES,
    AxisTaxonomyResult,
    NormalizationCoverageResult,
    validate_axis_taxonomy,
    validate_normalization_coverage,
)


# --- axis taxonomy ---------------------------------------------------------

def test_axis_taxonomy_passes_on_real_label_schema():
    res = validate_axis_taxonomy()
    assert isinstance(res, AxisTaxonomyResult)
    assert res.ok is True
    assert res.errors == ()
    assert set(res.active_axes) == set(EXPECTED_ACTIVE_AXES)
    assert res.masked_axis == "edge_valve_position"
    payload = res.to_dict()
    assert payload["ok"] is True
    assert payload["errors"] == []
    assert set(payload["active_axes"]) == set(EXPECTED_ACTIVE_AXES)


def test_axis_taxonomy_fails_when_unit_missing():
    # Inject a units map missing one axis -- never touch the real AXIS_UNITS.
    missing_unit = dict(AXIS_UNITS)
    del missing_unit["edge_power"]
    res = validate_axis_taxonomy(units=missing_unit)
    assert res.ok is False
    assert any("edge_power" in e and "no unit" in e for e in res.errors)


def test_axis_taxonomy_fails_when_active_axis_missing_column_mapping():
    # Drop the backing column for one active axis via injected map.
    bad_map = {axis: "col_" + axis for axis in EXPECTED_ACTIVE_AXES}
    bad_map["edge_flow"] = None  # active axis lost its backing column
    bad_map["edge_valve_position"] = None
    res = validate_axis_taxonomy(axis_to_column=bad_map)
    assert res.ok is False
    assert any("edge_flow" in e and "no backing column" in e for e in res.errors)


def test_axis_taxonomy_fails_when_expected_set_disagrees():
    # Pretend we expected nine axes -- the active set must match exactly.
    expanded = (*EXPECTED_ACTIVE_AXES, "phantom_axis")
    res = validate_axis_taxonomy(expected_axes=expanded)
    assert res.ok is False
    assert any("phantom_axis" in e for e in res.errors)


# --- normalization coverage -----------------------------------------------

def _synthetic_stats() -> dict:
    """Synthetic stats payload covering exactly the eight expected axes."""
    return {
        "split_version": "synthetic",
        "active_axes": list(EXPECTED_ACTIVE_AXES),
        "stats": {
            axis: {"source_column": f"col_{axis}", "mu": float(i), "sigma": 1.0 + i}
            for i, axis in enumerate(EXPECTED_ACTIVE_AXES)
        },
    }


def test_normalization_coverage_passes_on_complete_payload():
    res = validate_normalization_coverage(_synthetic_stats())
    assert isinstance(res, NormalizationCoverageResult)
    assert res.ok is True
    assert res.errors == ()
    assert set(res.covered_axes) == set(EXPECTED_ACTIVE_AXES)
    assert res.missing_axes == ()
    assert res.extra_axes == ()
    payload = res.to_dict()
    assert payload["ok"] is True
    assert payload["missing_axes"] == []


def test_normalization_coverage_passes_on_real_cached_stats(tmp_path):
    # The cached production stats file must satisfy coverage.
    res = validate_normalization_coverage("data/normalization/yilan_2025_train_stats.json")
    assert res.ok is True, res.errors


def test_normalization_coverage_fails_on_missing_axis():
    bad = _synthetic_stats()
    del bad["stats"]["edge_power"]
    bad["active_axes"].remove("edge_power")
    res = validate_normalization_coverage(bad)
    assert res.ok is False
    assert "edge_power" in res.missing_axes
    assert any("missing axes" in e for e in res.errors)


def test_normalization_coverage_fails_on_extra_axis():
    bad = _synthetic_stats()
    bad["stats"]["phantom_axis"] = {"mu": 0.0, "sigma": 1.0}
    bad["active_axes"].append("phantom_axis")
    res = validate_normalization_coverage(bad)
    assert res.ok is False
    assert "phantom_axis" in res.extra_axes
    assert any("unexpected axes" in e for e in res.errors)


def test_normalization_coverage_fails_on_nonpositive_sigma():
    bad = _synthetic_stats()
    bad["stats"]["node_level"]["sigma"] = 0.0
    res = validate_normalization_coverage(bad)
    assert res.ok is False
    assert any("node_level" in e and "sigma" in e for e in res.errors)


def test_normalization_coverage_fails_on_non_finite_mu():
    bad = _synthetic_stats()
    bad["stats"]["edge_flow"]["mu"] = float("nan")
    res = validate_normalization_coverage(bad)
    assert res.ok is False
    assert any("edge_flow" in e and "mu" in e for e in res.errors)


def test_normalization_coverage_accepts_path_argument(tmp_path):
    stats = _synthetic_stats()
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(stats))
    res = validate_normalization_coverage(path)
    assert res.ok is True
    assert res.stats_path == str(path)
