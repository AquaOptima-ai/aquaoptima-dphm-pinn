"""AOPSO Sprint 31 -- Pillar B specific-energy engine tests.

Covers the five Sprint 31 acceptance criteria on synthetic fixtures only:

1. Unit confirmation (and the explicit FAIL path).
2. Energy/volume trapezoidal integration on a fixture with a known answer.
3. The exclusion-reason waterfall sums to total intervals.
4. Reproducibility: two runs on the same input produce the same operating-point count.
5. Leakage: any 2026-03 key in the inputs raises before any compute.

NO real CSV is read; the build-bot scorecard runs against the real 2025 CSV
via :func:`run_sprint31_scorecard` in the orchestrator script.
"""

from __future__ import annotations

import pandas as pd
import pytest

from aquaoptima.advisory.specific_energy import (
    CONVERSION_NOTES,
    EXCLUSION_REASONS,
    EXPECTED_UNITS,
    EngineConfig,
    OperatingPoint,
    aggregate_operating_points,
    assert_no_march_2026_in_keys,
    build_sprint31_scorecard,
    compute_intervals,
    confirm_units,
    reproducibility_check,
    validity_waterfall,
)
from aquaoptima.dataio.yilan_axis_map import (
    CANONICAL_AXIS_TO_COLUMN,
    TIMESTAMP_COLUMN,
)
from aquaoptima.dataio.yilan_profiler import (
    MODE_AUTO_COLUMN,
    MODE_MANUAL_COLUMN,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _col(axis: str) -> str:
    col = CANONICAL_AXIS_TO_COLUMN[axis]
    assert col is not None
    return col


def _build_clean_frame(
    *,
    n: int = 32,
    start: str = "2025-06-01_00:00:00",
    cadence_seconds: int = 60,
    power_kw: float = 20.0,
    flow_m3_per_h: float = 60.0,
    speed_hz: float = 50.0,
    demand: float = 40.0,
    level: float = 4.0,
    pressure: float = 25.0,
    status: float = 1.0,
    mode_auto: bool = True,
) -> pd.DataFrame:
    """Build a clean synthetic 2025 frame at 60s cadence with constant signals."""
    ts = pd.date_range(
        pd.Timestamp(start.replace("_", " ")),
        periods=n,
        freq=f"{cadence_seconds}s",
    )
    return pd.DataFrame(
        {
            TIMESTAMP_COLUMN: ts,
            MODE_AUTO_COLUMN: [mode_auto] * n,
            MODE_MANUAL_COLUMN: [not mode_auto] * n,
            _col("edge_power"): [power_kw] * n,
            _col("edge_flow"): [flow_m3_per_h] * n,
            _col("edge_pump_speed"): [speed_hz] * n,
            _col("edge_status"): [status] * n,
            _col("node_demand"): [demand] * n,
            _col("node_level"): [level] * n,
            _col("node_pressure"): [pressure] * n,
        }
    )


# --------------------------------------------------------------------------- #
# Criterion #1: unit confirmation
# --------------------------------------------------------------------------- #
def test_unit_confirmation_passes_on_real_axis_units():
    conf = confirm_units()
    assert conf.confirmed, conf.errors
    assert conf.units["edge_power"] == "kW"
    assert conf.units["edge_flow"] == "m3_per_h"
    # Conversion math is documented in the scorecard.
    assert any("kW * h = kWh" in note for note in CONVERSION_NOTES)
    assert any(
        "specific_energy_kwh_per_m3 = energy_kwh / volume_m3" in note
        for note in CONVERSION_NOTES
    )


def test_unit_confirmation_fails_on_unit_mismatch():
    # Inject a wrong unit; the gate must FAIL explicitly.
    bad_units = dict(EXPECTED_UNITS)
    bad_units["edge_power"] = "watts"  # not kW
    conf = confirm_units(units=bad_units)
    assert not conf.confirmed
    assert any("edge_power" in e and "kW" in e for e in conf.errors)


def test_unit_confirmation_fails_on_missing_unit():
    bad_units = dict(EXPECTED_UNITS)
    del bad_units["edge_flow"]
    conf = confirm_units(units=bad_units)
    assert not conf.confirmed
    assert any("edge_flow" in e for e in conf.errors)


# --------------------------------------------------------------------------- #
# Criterion #2: energy/volume trapezoidal integration -- KNOWN ANSWER
# --------------------------------------------------------------------------- #
def test_energy_volume_trapezoidal_on_known_constant_fixture():
    # 60s cadence, power=20 kW, flow=60 m3/h.
    # For each 60s interval: dt_h = 1/60 h.
    #   energy_kwh per interval = 20 * 1/60 = 0.3333... kWh
    #   volume_m3   per interval = 60 * 1/60 = 1.0 m3
    #   SE = 0.333.../1.0 = 0.333... kWh/m3
    df = _build_clean_frame(n=10, power_kw=20.0, flow_m3_per_h=60.0)
    intervals = compute_intervals(df)
    assert intervals["kept"].all(), (
        intervals.loc[~intervals["kept"], "exclusion_reason"].unique()
    )
    expected_e = 20.0 / 60.0
    expected_v = 60.0 / 60.0  # = 1.0
    assert intervals["energy_kwh"].round(6).eq(round(expected_e, 6)).all()
    assert intervals["volume_m3"].round(6).eq(round(expected_v, 6)).all()
    # SE for the bin aggregate.
    ops_15 = aggregate_operating_points(intervals, window_minutes=15)
    assert ops_15, "expected at least one 15-min operating point"
    se = ops_15[0].specific_energy_kwh_per_m3
    assert se == pytest.approx(expected_e / expected_v, rel=1e-6)


def test_energy_volume_trapezoidal_on_linear_ramp():
    # power ramps from 10 -> 30 kW, flow ramps 30 -> 90 m3/h over 11 samples
    # (10 intervals) at 60s cadence. Trapezoidal mean per interval:
    #   power_i = 10 + 2*i (i = 0..10) -> midpoint between consecutive = 11,13,...,29
    #   total_energy_kwh = sum(mean_power_i) * (1/60)
    n = 11
    cadence = 60
    df = _build_clean_frame(n=n, cadence_seconds=cadence, power_kw=0.0, flow_m3_per_h=0.0)
    df[_col("edge_power")] = [10.0 + 2 * i for i in range(n)]
    df[_col("edge_flow")] = [30.0 + 6 * i for i in range(n)]
    intervals = compute_intervals(df)
    assert intervals["kept"].all()
    dt_h = cadence / 3600.0
    # Sum of midpoints of consecutive samples (linear ramp) ==
    # 0.5*(first + last) * n_intervals.
    expected_total_energy = 0.5 * (10.0 + 30.0) * (n - 1) * dt_h
    expected_total_volume = 0.5 * (30.0 + 90.0) * (n - 1) * dt_h
    assert intervals["energy_kwh"].sum() == pytest.approx(expected_total_energy, rel=1e-6)
    assert intervals["volume_m3"].sum() == pytest.approx(expected_total_volume, rel=1e-6)


# --------------------------------------------------------------------------- #
# Criterion #3: exclusion-reason waterfall sums correctly
# --------------------------------------------------------------------------- #
def test_waterfall_sums_correctly_with_each_reason_present():
    df = _build_clean_frame(n=20)

    # Inject one of each excludable defect at distinct indices.
    df.loc[2, _col("edge_power")] = float("nan")   # nan_input @ interval starting at 2
    df.loc[5, _col("edge_status")] = 0.0           # pump_off @ intervals 4,5
    df.loc[8, _col("edge_flow")] = 0.0             # low_flow @ intervals 7,8
    df.loc[10, MODE_AUTO_COLUMN] = False           # unprofiled_mode_other @ 9,10
    df.loc[10, MODE_MANUAL_COLUMN] = False
    # Introduce a > 5-min gap by jumping the last row's timestamp forward
    # by 10 minutes (gap threshold = 300s).
    df.loc[df.index[-1], TIMESTAMP_COLUMN] = (
        df.loc[df.index[-1], TIMESTAMP_COLUMN] + pd.Timedelta(minutes=10)
    )

    intervals = compute_intervals(df)
    wf = validity_waterfall(intervals)

    assert wf["sums_correctly"], wf
    assert wf["kept"] + wf["excluded_total"] == wf["total_intervals"]

    # All reasons we injected should show up.
    present = {r for r, c in wf["by_reason"].items() if c > 0}
    assert "nan_input" in present
    assert "pump_off" in present
    assert "low_flow" in present
    assert "unprofiled_mode_other" in present
    assert "gap_too_long" in present


def test_waterfall_buckets_are_the_documented_set():
    # The keys in by_reason must exactly equal EXCLUSION_REASONS (so
    # downstream consumers can rely on the schema).
    df = _build_clean_frame(n=4)
    wf = validity_waterfall(compute_intervals(df))
    assert tuple(wf["by_reason"].keys()) == EXCLUSION_REASONS


# --------------------------------------------------------------------------- #
# Criterion #4: reproducibility
# --------------------------------------------------------------------------- #
def test_two_runs_produce_identical_operating_point_counts():
    df = _build_clean_frame(n=64)
    cfg = EngineConfig()
    repro = reproducibility_check(df, config=cfg)
    assert repro["reproducible"]
    assert repro["counts_run_a"] == repro["counts_run_b"]


def test_two_runs_produce_identical_se_values():
    df = _build_clean_frame(n=64, power_kw=22.5, flow_m3_per_h=72.0)
    intervals_a = compute_intervals(df)
    intervals_b = compute_intervals(df)
    ops_a = aggregate_operating_points(intervals_a, window_minutes=15)
    ops_b = aggregate_operating_points(intervals_b, window_minutes=15)
    assert len(ops_a) == len(ops_b)
    for a, b in zip(ops_a, ops_b):
        assert a.specific_energy_kwh_per_m3 == b.specific_energy_kwh_per_m3
        assert a.energy_kwh == b.energy_kwh
        assert a.volume_m3 == b.volume_m3
        assert a.window_start == b.window_start


# --------------------------------------------------------------------------- #
# Criterion #5: leakage guard
# --------------------------------------------------------------------------- #
def test_leakage_guard_raises_on_any_march_2026_key():
    with pytest.raises(ValueError, match="March-2026"):
        assert_no_march_2026_in_keys(["2025-07", "2026-03"])


def test_leakage_guard_passes_when_only_2025_keys():
    # Should not raise.
    assert_no_march_2026_in_keys(["2025-01", "2025-12"])


def test_full_scorecard_pipeline_blocks_march_2026_frame():
    # Inject a single 2026-03 row -> the scorecard build must STOP before
    # any computation runs.
    df = _build_clean_frame(n=4)
    df = df.copy()
    df.loc[df.index[-1], TIMESTAMP_COLUMN] = pd.Timestamp("2026-03-15 12:00:00")
    with pytest.raises(ValueError, match="March-2026"):
        build_sprint31_scorecard(df=df, csv_path="<test>")


# --------------------------------------------------------------------------- #
# Full scorecard shape on a clean fixture (PASS path)
# --------------------------------------------------------------------------- #
def test_full_scorecard_passes_on_clean_2025_fixture():
    df = _build_clean_frame(n=240)  # 4 hours @ 60s
    sc = build_sprint31_scorecard(df=df, csv_path="<test>")
    assert sc["sprint"] == 31
    assert sc["pillar"] == "B"
    assert sc["advisory_only"] is True
    assert sc["evaluation_mode"] == "offline_only"
    assert sc["march_used_for_tuning"] is False
    # All five gate criteria.
    names = [c["name"] for c in sc["acceptance_gate"]["criteria"]]
    assert set(names) == {
        "units_confirmed",
        "se_from_interval_energy_and_volume",
        "exclusion_waterfall_sums_correctly",
        "aggregation_reproducible",
        "march_not_used_for_tuning",
    }
    assert sc["acceptance_gate"]["passed"] is True
    assert sc["verdict"] == "PASS"
    # Waterfall total > 0 and at least some kept intervals.
    assert sc["validity_waterfall"]["total_intervals"] > 0
    assert sc["validity_waterfall"]["kept"] > 0
    # 15-min and 30-min counts both > 0.
    assert sc["aggregation"]["n_operating_points_15"] > 0
    assert sc["aggregation"]["n_operating_points_30"] > 0
    # train_meta carries per_month_rows.
    assert "per_month_rows" in sc["train_meta"]
    assert sc["train_meta"]["distinct_months"], sc["train_meta"]
    # gate_version is namespaced for sprint 31.
    assert sc["acceptance_gate"]["gate_version"].startswith("sprint31.")


def test_operating_point_carries_required_context_for_sprint32():
    df = _build_clean_frame(n=64, demand=33.0, level=2.5, pressure=18.0, speed_hz=45.0)
    intervals = compute_intervals(df)
    ops = aggregate_operating_points(intervals, window_minutes=15)
    assert ops, "expected at least one operating point"
    op: OperatingPoint = ops[0]
    assert op.window_minutes == 15
    assert op.specific_energy_kwh_per_m3 > 0
    assert op.mean_speed_hz == pytest.approx(45.0, abs=1e-3)
    assert op.mean_demand_m3_per_h == pytest.approx(33.0, abs=1e-3)
    assert op.mean_level_m == pytest.approx(2.5, abs=1e-3)
    assert op.mean_pressure_m_head == pytest.approx(18.0, abs=1e-3)
    assert op.advisory_only is True
