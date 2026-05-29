"""AOPSO Sprint 32 -- Pillar B matched-condition envelope tests.

Covers the five Sprint 32 acceptance criteria on synthetic fixtures only:

  C1. Advisories require minimum historical support (frozen MIN_SUPPORT).
  C2. All reported speed ranges are historically observed (no extrapolation).
  C3. Unsupported intervals are rejected with reasons.
  C4. MVPv1 comparison produced ONLY where alignment is valid; a deliberately
      misaligned fixture must be REJECTED by the diagnostic.
  C5. Matching tolerances + SE quantiles are FROZEN before March; the
      ``efficiency_gate`` constants are importable and hash-stable; any 2026-03
      OperatingPoint window-start raises before any compute.

No real CSV is read; the bot scorecard runs against the real 2025
OperatingPoints CSV via :func:`run_sprint32_scorecard`.
"""

from __future__ import annotations

import math
import json

import numpy as np
import pandas as pd
import pytest

from aquaoptima.advisory.efficiency_envelope import (
    EnvelopeAdvisory,
    EnvelopeRejection,
    OperatingConditionQuery,
    REJECTION_INSUFFICIENT_SUPPORT,
    REJECTION_NO_OBSERVED_EFFICIENT_SPEEDS,
    SE_COLUMN,
    SPEED_COLUMN,
    WINDOW_START_COLUMN,
    assert_operating_points_no_march_2026,
    compute_envelope,
    evaluate_query_batch,
    extract_observed_speed_range,
    matched_search,
    produce_advisory,
)
from aquaoptima.advisory.efficiency_gate import (
    FROZEN,
    GATE_VERSION,
    MARCH_USED_FOR_TUNING,
    MATCHING_CHANNELS,
    MATCHING_TOLERANCES,
    MIN_SUPPORT,
    MVPV1_MAX_DEMAND_DISAGREEMENT_M3_PER_H,
    MVPV1_MIN_OVERLAP_FRACTION,
    PILLAR,
    SE_QUANTILES,
    SPEED_RANGE_SE_CUTOFF_QUANTILE,
    SPRINT,
    frozen_pillar_b_params,
    frozen_params_canonical_json,
    frozen_params_sha256,
)
from aquaoptima.advisory.efficiency_mvpv1_alignment import (
    ALIGNMENT_REJECTION_BELOW_THRESHOLD,
    ALIGNMENT_REJECTION_EMPTY_LOG,
    ALIGNMENT_REJECTION_MISSING_COLUMNS,
    ALIGNMENT_REJECTION_NO_LOG,
    diagnose_mvpv1_alignment,
)
from aquaoptima.advisory.sprint32_envelope import (
    build_sprint32_scorecard,
    default_example_queries,
)


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #
def _make_op(
    *,
    window_start: str,
    window_minutes: int = 30,
    demand: float,
    level: float,
    pressure: float,
    flow: float,
    speed: float,
    se: float,
) -> dict:
    """Build a single OperatingPoint-shaped row."""
    start = pd.Timestamp(window_start)
    end = start + pd.Timedelta(minutes=window_minutes)
    # We derive energy + volume from SE * volume so the schema is self-consistent.
    volume = 100.0
    energy = se * volume
    return {
        "window_minutes": int(window_minutes),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "n_intervals_used": 28,
        "energy_kwh": round(energy, 6),
        "volume_m3": round(volume, 6),
        "specific_energy_kwh_per_m3": round(float(se), 6),
        "mean_speed_hz": float(speed),
        "mean_flow_m3_per_h": float(flow),
        "mean_power_kw": round(energy, 6),  # placeholder
        "mean_demand_m3_per_h": float(demand),
        "mean_level_m": float(level),
        "mean_pressure_m_head": float(pressure),
        "advisory_only": True,
    }


def _build_ops_around(
    *,
    n: int = 60,
    demand: float = 1500.0,
    level: float = 5.0,
    pressure: float = 1.5,
    flow: float = 1400.0,
    se_base: float = 0.10,
    speed_base: float = 41.0,
    start: str = "2025-06-01T00:00:00",
) -> pd.DataFrame:
    """Build n OperatingPoints clustered around a target condition.

    SE varies in a slight sinusoidal pattern so quantiles are non-degenerate;
    speeds vary 38-46 Hz in lockstep with SE so the efficient sub-bucket has
    a clear lower-speed signature.
    """
    rows = []
    for i in range(n):
        ts = pd.Timestamp(start) + pd.Timedelta(minutes=30 * i)
        se = se_base + 0.02 * math.sin(i * 0.7) + 0.005 * i / n
        # higher SE -> higher speed (so efficient = lower speed)
        speed = speed_base + (se - se_base) * 200.0
        rows.append(
            _make_op(
                window_start=ts.isoformat(),
                demand=demand + 5.0 * math.cos(i * 0.3),
                level=level + 0.05 * math.sin(i * 0.4),
                pressure=pressure + 0.05 * math.cos(i * 0.2),
                flow=flow + 4.0 * math.sin(i * 0.5),
                speed=speed,
                se=se,
            )
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# G-class: efficiency_gate constants are importable + stable + frozen
# --------------------------------------------------------------------------- #
def test_efficiency_gate_constants_are_importable_and_frozen():
    assert PILLAR == "B"
    assert SPRINT == 32
    assert GATE_VERSION.startswith("sprint32."), GATE_VERSION
    assert FROZEN is True
    assert MARCH_USED_FOR_TUNING is False
    assert SE_QUANTILES == (0.10, 0.25)
    assert isinstance(MIN_SUPPORT, int) and MIN_SUPPORT > 0
    # SPEED_RANGE_SE_CUTOFF_QUANTILE must be in (0, 1].
    assert 0.0 < SPEED_RANGE_SE_CUTOFF_QUANTILE <= 1.0
    # MVPv1 thresholds within sensible range.
    assert 0.0 < MVPV1_MIN_OVERLAP_FRACTION <= 1.0
    assert MVPV1_MAX_DEMAND_DISAGREEMENT_M3_PER_H > 0
    # All matching channels are present + finite + non-negative.
    for ch in MATCHING_CHANNELS:
        assert ch in MATCHING_TOLERANCES
        tol = MATCHING_TOLERANCES[ch]
        assert math.isfinite(tol) and tol >= 0


def test_frozen_params_record_is_hash_stable():
    a = frozen_pillar_b_params().to_dict()
    b = frozen_pillar_b_params().to_dict()
    assert a == b
    # Canonical JSON identical between calls.
    assert frozen_params_canonical_json() == frozen_params_canonical_json()
    # SHA-256 stable.
    assert frozen_params_sha256() == frozen_params_sha256()
    # And the SHA matches the SHA of the canonical JSON.
    import hashlib
    expected = hashlib.sha256(frozen_params_canonical_json().encode("utf-8")).hexdigest()
    assert frozen_params_sha256() == expected
    # Round-trips through json.
    parsed = json.loads(frozen_params_canonical_json())
    assert parsed["pillar"] == "B"
    assert parsed["sprint"] == 32
    assert parsed["frozen"] is True
    assert parsed["march_used_for_tuning"] is False


# --------------------------------------------------------------------------- #
# C1 + matched-search: tolerance-window neighbours
# --------------------------------------------------------------------------- #
def test_matched_search_returns_correct_neighbours_on_fixture():
    # Three rows: two inside tolerances (1, 2) and one far outside (3).
    rows = [
        _make_op(window_start="2025-06-01T00:00:00", demand=1500.0, level=5.0,
                 pressure=1.5, flow=1400.0, speed=40.0, se=0.10),
        _make_op(window_start="2025-06-01T00:30:00", demand=1520.0, level=5.1,
                 pressure=1.6, flow=1410.0, speed=41.0, se=0.11),
        _make_op(window_start="2025-06-01T01:00:00", demand=3000.0, level=5.0,
                 pressure=1.5, flow=2800.0, speed=50.0, se=0.20),
    ]
    ops = pd.DataFrame(rows)
    q = OperatingConditionQuery(
        demand_m3_per_h=1500.0, level_m=5.0,
        pressure_m_head=1.5, flow_m3_per_h=1400.0,
        label="q",
    )
    res = matched_search(ops, q)
    assert res.comparable_count == 2
    assert set(res.matched_indices) == {0, 1}
    # L_inf normalised distance is well-defined.
    assert res.match_distance_summary["min"] >= 0.0
    assert res.match_distance_summary["max"] <= 1.0  # both rows within tolerance
    # Out-of-distribution query -> zero matches.
    q_ood = OperatingConditionQuery(
        demand_m3_per_h=10_000.0, level_m=5.0,
        pressure_m_head=1.5, flow_m3_per_h=1400.0,
        label="ood",
    )
    res_ood = matched_search(ops, q_ood)
    assert res_ood.comparable_count == 0
    assert res_ood.matched_indices == ()


def test_matched_search_rejects_nan_context():
    rows = [
        _make_op(window_start="2025-06-01T00:00:00", demand=1500.0, level=5.0,
                 pressure=1.5, flow=1400.0, speed=40.0, se=0.10),
    ]
    ops = pd.DataFrame(rows)
    # Inject NaN level in the only candidate row.
    ops.loc[0, "mean_level_m"] = float("nan")
    q = OperatingConditionQuery(
        demand_m3_per_h=1500.0, level_m=5.0,
        pressure_m_head=1.5, flow_m3_per_h=1400.0,
    )
    res = matched_search(ops, q)
    assert res.comparable_count == 0


# --------------------------------------------------------------------------- #
# Envelope math: p10/p25 quantiles
# --------------------------------------------------------------------------- #
def test_compute_envelope_p10_and_p25_known_distribution():
    # Build a bucket with SE = 0..99 (100 rows).
    rows = []
    for i in range(100):
        rows.append(
            _make_op(
                window_start=(pd.Timestamp("2025-07-01T00:00:00")
                              + pd.Timedelta(minutes=30 * i)).isoformat(),
                demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
                speed=40.0 + i * 0.01, se=float(i),
            )
        )
    ops = pd.DataFrame(rows)
    matched = list(range(len(ops)))
    env = compute_envelope(ops, matched)
    # numpy default linear interp on 0..99 -> p10 = 9.9, p25 = 24.75, median = 49.5.
    assert env["p10"] == pytest.approx(9.9, rel=1e-6)
    assert env["p25"] == pytest.approx(24.75, rel=1e-6)
    assert env["median"] == pytest.approx(49.5, rel=1e-6)


def test_compute_envelope_empty_bucket():
    ops = pd.DataFrame(columns=[
        "mean_demand_m3_per_h", "mean_level_m", "mean_pressure_m_head",
        "mean_flow_m3_per_h", SE_COLUMN, SPEED_COLUMN, WINDOW_START_COLUMN,
    ])
    env = compute_envelope(ops, [])
    assert math.isnan(env["p10"])
    assert math.isnan(env["p25"])
    assert math.isnan(env["median"])


# --------------------------------------------------------------------------- #
# C2: observed speed range -- every reported speed is in the 2025 observed set
# --------------------------------------------------------------------------- #
def test_speed_range_is_subset_of_observed_2025_speeds():
    ops = _build_ops_around(n=60)
    # All-rows bucket.
    matched = list(range(len(ops)))
    block = extract_observed_speed_range(ops, matched)
    observed_set = set(np.round(
        pd.to_numeric(ops[SPEED_COLUMN], errors="coerce").to_numpy(dtype=float), 2
    ).tolist())
    for s in block["speed_values_hz"]:
        assert s in observed_set
    assert block["all_speeds_historically_observed"] is True
    # The reported min/max must fall within the data's observed speed range.
    assert block["speed_min_hz"] >= ops[SPEED_COLUMN].min() - 1e-9
    assert block["speed_max_hz"] <= ops[SPEED_COLUMN].max() + 1e-9


def test_efficient_sub_bucket_is_lower_se_than_full_bucket():
    ops = _build_ops_around(n=80)
    matched = list(range(len(ops)))
    block = extract_observed_speed_range(ops, matched)
    # The efficient subset's SE must all be <= the bucket's p25.
    se = pd.to_numeric(ops[SE_COLUMN], errors="coerce").to_numpy()
    p25 = float(np.quantile(se, 0.25))
    assert block["se_threshold"] == pytest.approx(p25, rel=1e-6)


# --------------------------------------------------------------------------- #
# C3: rejection when support < MIN_SUPPORT
# --------------------------------------------------------------------------- #
def test_rejection_when_support_below_min():
    # Only 5 rows in the matched bucket -- below MIN_SUPPORT (>= 30 by design).
    ops = _build_ops_around(n=5)
    q = OperatingConditionQuery(
        demand_m3_per_h=1500.0, level_m=5.0,
        pressure_m_head=1.5, flow_m3_per_h=1400.0,
    )
    result = produce_advisory(ops, q)
    assert isinstance(result, EnvelopeRejection)
    assert result.reason == REJECTION_INSUFFICIENT_SUPPORT
    assert result.comparable_count < MIN_SUPPORT
    assert "required_min_support" in result.detail


def test_advisory_when_support_meets_min():
    ops = _build_ops_around(n=MIN_SUPPORT + 5)
    q = OperatingConditionQuery(
        demand_m3_per_h=1500.0, level_m=5.0,
        pressure_m_head=1.5, flow_m3_per_h=1400.0,
        label="good",
    )
    result = produce_advisory(ops, q)
    assert isinstance(result, EnvelopeAdvisory)
    assert result.comparable_count >= MIN_SUPPORT
    assert result.advisory_only is True
    assert result.is_evidence_not_setpoint is True
    assert result.observed_efficient_speed_min_hz <= result.observed_efficient_speed_max_hz
    assert result.se_p10 <= result.se_p25 <= result.se_median


# --------------------------------------------------------------------------- #
# C4: MVPv1 alignment diagnostic
# --------------------------------------------------------------------------- #
def _make_mvpv1_log(ops: pd.DataFrame, *, demand_offset: float = 0.0) -> pd.DataFrame:
    """Build an MVPv1 log whose timestamps fall inside the OperatingPoints' windows."""
    rows = []
    for _, op in ops.iterrows():
        start = pd.Timestamp(op["window_start"])
        end = pd.Timestamp(op["window_end"])
        mid = start + (end - start) / 2
        rows.append({
            "timestamp": mid,
            "mvpv1_demand_m3_per_h": float(op["mean_demand_m3_per_h"]) + demand_offset,
            "mvpv1_speed_hz": float(op["mean_speed_hz"]),
        })
    return pd.DataFrame(rows)


def test_mvpv1_alignment_passes_on_clean_overlap():
    ops = _build_ops_around(n=40)
    log = _make_mvpv1_log(ops)
    report = diagnose_mvpv1_alignment(log, ops)
    assert report.diagnostic_passed is True
    assert report.coverage >= MVPV1_MIN_OVERLAP_FRACTION
    assert report.n_aligned == len(log)
    assert report.rejection_reason is None


def test_mvpv1_alignment_rejects_misaligned_fixture():
    ops = _build_ops_around(n=40)
    log = _make_mvpv1_log(ops)
    # Shift every timestamp far outside any window (e.g. +10 days).
    log["timestamp"] = log["timestamp"] + pd.Timedelta(days=10)
    report = diagnose_mvpv1_alignment(log, ops)
    assert report.diagnostic_passed is False
    assert report.coverage < MVPV1_MIN_OVERLAP_FRACTION
    assert report.rejection_reason == ALIGNMENT_REJECTION_BELOW_THRESHOLD


def test_mvpv1_alignment_rejects_demand_disagreement():
    ops = _build_ops_around(n=40)
    # Push every MVPv1 demand far above the OperatingPoint demand.
    log = _make_mvpv1_log(
        ops,
        demand_offset=MVPV1_MAX_DEMAND_DISAGREEMENT_M3_PER_H * 5,
    )
    report = diagnose_mvpv1_alignment(log, ops)
    assert report.diagnostic_passed is False
    assert report.rejection_reason == ALIGNMENT_REJECTION_BELOW_THRESHOLD


def test_mvpv1_alignment_handles_no_log():
    ops = _build_ops_around(n=40)
    report = diagnose_mvpv1_alignment(None, ops)
    assert report.diagnostic_passed is False
    assert report.rejection_reason == ALIGNMENT_REJECTION_NO_LOG
    assert report.n_log_rows == 0


def test_mvpv1_alignment_handles_empty_log():
    ops = _build_ops_around(n=40)
    empty = pd.DataFrame(columns=["timestamp", "mvpv1_demand_m3_per_h", "mvpv1_speed_hz"])
    report = diagnose_mvpv1_alignment(empty, ops)
    assert report.diagnostic_passed is False
    assert report.rejection_reason == ALIGNMENT_REJECTION_EMPTY_LOG


def test_mvpv1_alignment_rejects_missing_columns():
    ops = _build_ops_around(n=40)
    bad = pd.DataFrame({"timestamp": [pd.Timestamp("2025-06-01")]})
    report = diagnose_mvpv1_alignment(bad, ops)
    assert report.diagnostic_passed is False
    assert report.rejection_reason == ALIGNMENT_REJECTION_MISSING_COLUMNS


# --------------------------------------------------------------------------- #
# C5: leakage guard -- 2026-03 in OperatingPoints raises BEFORE any compute
# --------------------------------------------------------------------------- #
def test_leakage_guard_raises_on_march_2026_window_start():
    ops = _build_ops_around(n=5)
    # Replace one row's window_start with a 2026-03 timestamp.
    ops.loc[0, "window_start"] = "2026-03-15T00:00:00"
    with pytest.raises(ValueError, match="March-2026"):
        assert_operating_points_no_march_2026(ops)
    # And via the produce_advisory entry-point.
    q = OperatingConditionQuery(
        demand_m3_per_h=1500.0, level_m=5.0,
        pressure_m_head=1.5, flow_m3_per_h=1400.0,
    )
    with pytest.raises(ValueError, match="March-2026"):
        produce_advisory(ops, q)


def test_leakage_guard_passes_on_pure_2025():
    ops = _build_ops_around(n=5)
    # Must not raise.
    assert_operating_points_no_march_2026(ops)


# --------------------------------------------------------------------------- #
# Scorecard end-to-end on a clean fixture
# --------------------------------------------------------------------------- #
def test_full_scorecard_passes_on_clean_2025_fixture():
    ops = _build_ops_around(n=200)
    sc = build_sprint32_scorecard(
        operating_points=ops,
        operating_points_csv_path="<test>",
        queries=None,         # default example queries derived from data
        mvpv1_log=None,       # alignment diagnostic gracefully reports no-log
    )
    assert sc["sprint"] == 32
    assert sc["pillar"] == "B"
    assert sc["advisory_only"] is True
    assert sc["evaluation_mode"] == "offline_only"
    assert sc["march_used_for_tuning"] is False
    # Frozen params block carries every required key.
    fp = sc["frozen_params"]
    assert fp["frozen"] is True
    assert fp["se_quantiles"] == [0.10, 0.25]
    assert fp["min_support"] == MIN_SUPPORT
    assert "matching_tolerances" in fp
    assert "frozen_params_sha256" in fp
    # The scorecard must list five gate criteria with these names.
    names = [c["name"] for c in sc["acceptance_gate"]["criteria"]]
    assert set(names) == {
        "advisories_require_minimum_historical_support",
        "all_reported_speed_ranges_historically_observed",
        "unsupported_intervals_rejected_with_reasons",
        "mvpv1_comparison_only_where_alignment_is_valid",
        "matching_tolerances_and_quantiles_frozen_before_march",
    }
    # Rejection block + at least one rejection (the far-OOD query).
    assert sc["rejection"]["n_rejected"] >= 1
    assert any(r in sc["rejection"]["reasons"] for r in (
        REJECTION_INSUFFICIENT_SUPPORT, REJECTION_NO_OBSERVED_EFFICIENT_SPEEDS,
    ))
    # mvpv1_alignment block carries the contract keys.
    align = sc["mvpv1_alignment"]
    assert "coverage" in align
    assert "n_aligned" in align
    assert "n_rejected" in align
    assert "diagnostic_passed" in align
    # train_meta carries per_month_rows.
    assert "per_month_rows" in sc["train_meta"]
    # March must NOT appear in distinct_months.
    assert all(not m.startswith("2026-03") for m in sc["train_meta"]["distinct_months"])


def test_scorecard_fails_when_speed_outside_observed_set_is_injected(monkeypatch):
    """C2 must FAIL if any advisory reports a speed not in the 2025 observed set."""
    ops = _build_ops_around(n=200)

    # Patch extract_observed_speed_range used inside produce_advisory to inject
    # an unobserved speed into the result. This simulates a bug where the
    # speed-range extraction yields an extrapolated value -- the scorecard
    # gate MUST catch it and FAIL.
    import aquaoptima.advisory.efficiency_envelope as ee
    original = ee.extract_observed_speed_range

    def faulty(ops_df, idx, **kw):
        block = original(ops_df, idx, **kw)
        block = dict(block)
        block["speed_values_hz"] = list(block["speed_values_hz"]) + [999.99]
        block["speed_max_hz"] = 999.99
        block["all_speeds_historically_observed"] = False
        return block

    monkeypatch.setattr(ee, "extract_observed_speed_range", faulty)

    sc = build_sprint32_scorecard(
        operating_points=ops,
        operating_points_csv_path="<test>",
        queries=None,
        mvpv1_log=None,
    )
    # C2 must FAIL.
    c2 = next(
        c for c in sc["acceptance_gate"]["criteria"]
        if c["name"] == "all_reported_speed_ranges_historically_observed"
    )
    assert c2["passed"] is False
    assert sc["acceptance_gate"]["passed"] is False
    assert sc["verdict"] == "FAIL"


# --------------------------------------------------------------------------- #
# Batch evaluation API
# --------------------------------------------------------------------------- #
def test_evaluate_query_batch_produces_advisories_and_rejections():
    ops = _build_ops_around(n=100)
    queries = default_example_queries(ops)
    batch = evaluate_query_batch(ops, queries)
    assert batch["n_queries"] == len(queries)
    assert batch["n_advisories"] + batch["n_rejected"] == batch["n_queries"]
    # Every rejection has a recognised reason.
    for r in batch["rejections"]:
        assert r["reason"] in (
            REJECTION_INSUFFICIENT_SUPPORT,
            REJECTION_NO_OBSERVED_EFFICIENT_SPEEDS,
        )
    # Every advisory's reported speeds appear in the observed-2025 multiset.
    observed = set(np.round(
        pd.to_numeric(ops[SPEED_COLUMN], errors="coerce").to_numpy(dtype=float), 2
    ).tolist())
    for adv in batch["advisories"]:
        for s in adv["observed_efficient_speed_values_hz"]:
            assert s in observed
