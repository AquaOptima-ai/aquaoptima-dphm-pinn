"""AOPSO Sprint 33 -- Pillar B locked-March-2026 OUT-OF-SAMPLE holdout tests.

These tests exercise the MECHANICS of the Sprint 33 holdout scoring engine on
small, deterministic, synthetic OperatingPoints; they never read the real
March CSV. The HONEST PASS/FAIL verdict on the locked March-2026 holdout is
produced by running ``scripts/sprint33_locked_march_eval.py`` once at the end
of the sprint -- not by these tests.

Coverage
--------
1. Holdout-isolation assert -- a non-March-2026 key in the March input raises
   BEFORE any compute runs.
2. Unsupported intervals produce ZERO savings claims (compile-time contract).
3. The opportunity computation on a fixture with KNOWN answer matches the
   hand-computed kWh.
4. Conservative-quantile robustness flag flips PASS->FAIL when no supported
   interval has a positive opportunity.
5. The scorecard carries every required schema key.
6. The frozen ``efficiency_gate.py`` file hash recorded in the scorecard
   matches the actual on-disk hash. This is the pre-registration integrity
   probe: any change to the file between Sprint 32 ship and Sprint 33 eval is
   a HARD STOP.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from aquaoptima.advisory.efficiency_envelope import (
    SE_COLUMN,
    SPEED_COLUMN,
    WINDOW_START_COLUMN,
)
from aquaoptima.advisory.efficiency_gate import (
    GATE_VERSION,
    MARCH_USED_FOR_TUNING,
    MATCHING_CHANNELS,
    MIN_SUPPORT,
)
from aquaoptima.advisory.locked_march_holdout import (
    AGGRESSIVE_QUANTILE,
    CONSERVATIVE_QUANTILE,
    EXCLUSION_REASON_INSUFFICIENT_SUPPORT,
    EXCLUSION_REASON_INVALID_INPUT,
    EXCLUSION_REASON_NO_EFFICIENT_SPEEDS,
    REPORT_VERSION,
    SPRINT,
    MarchIntervalResult,
    assert_holdout_inputs_are_march_2026,
    build_coverage_waterfall,
    build_sprint33_scorecard,
    compute_opportunity_summary,
    efficiency_gate_module_path,
    read_frozen_gate_file_sha256,
    score_march_against_envelope,
)


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #
def _make_op_2025(
    *,
    window_start: str,
    demand: float = 1500.0,
    level: float = 5.0,
    pressure: float = 1.5,
    flow: float = 1400.0,
    speed: float = 41.0,
    se: float = 0.10,
    window_minutes: int = 30,
) -> dict:
    """One 2025 OperatingPoint row in Sprint-31 schema."""
    start = pd.Timestamp(window_start)
    end = start + pd.Timedelta(minutes=window_minutes)
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
        "mean_power_kw": round(energy, 6),
        "mean_demand_m3_per_h": float(demand),
        "mean_level_m": float(level),
        "mean_pressure_m_head": float(pressure),
        "advisory_only": True,
    }


def _build_2025_envelope_around(
    *,
    n: int = MIN_SUPPORT + 20,
    demand: float = 1500.0,
    level: float = 5.0,
    pressure: float = 1.5,
    flow: float = 1400.0,
    se_base: float = 0.10,
    speed_base: float = 41.0,
    start: str = "2025-06-01T00:00:00",
) -> pd.DataFrame:
    """A 2025 envelope frame clustered around a target condition."""
    rows = []
    for i in range(n):
        ts = pd.Timestamp(start) + pd.Timedelta(minutes=30 * i)
        se = se_base + 0.02 * math.sin(i * 0.7) + 0.005 * i / max(n, 1)
        speed = speed_base + (se - se_base) * 200.0
        rows.append(
            _make_op_2025(
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


def _build_march_ops(
    *,
    n: int = 12,
    demand: float = 1500.0,
    level: float = 5.0,
    pressure: float = 1.5,
    flow: float = 1400.0,
    se: float = 0.20,            # inefficient observed SE so opportunity > 0
    speed: float = 46.0,
    start: str = "2026-03-05T00:00:00",
    window_minutes: int = 30,
) -> pd.DataFrame:
    """A March-2026 OperatingPoint frame in Sprint-31 schema."""
    rows = []
    for i in range(n):
        ts = pd.Timestamp(start) + pd.Timedelta(minutes=window_minutes * i)
        rows.append(
            _make_op_2025(
                window_start=ts.isoformat(),
                demand=demand,
                level=level,
                pressure=pressure,
                flow=flow,
                speed=speed,
                se=se,
                window_minutes=window_minutes,
            )
        )
    return pd.DataFrame(rows)


def _holdout_window(march_df: pd.DataFrame, *, csv_path: str = "<test-march-csv>") -> dict[str, Any]:
    ts = pd.to_datetime(march_df[WINDOW_START_COLUMN])
    return {
        "csv_path": csv_path,
        "first_timestamp": str(ts.min()),
        "last_timestamp": str(ts.max()),
        "all_in_2026_03": bool((ts.dt.year == 2026).all() and (ts.dt.month == 3).all()),
        "n_rows": int(len(march_df)),
    }


# --------------------------------------------------------------------------- #
# 1. Holdout-isolation asserts
# --------------------------------------------------------------------------- #
def test_assert_holdout_inputs_are_march_2026_passes_on_pure_march():
    keys = ["2026-03-01T00:00:00", "2026-03-15T12:00:00", "2026-03-31T23:30:00"]
    assert_holdout_inputs_are_march_2026(keys)  # must not raise


def test_assert_holdout_inputs_raises_on_non_march_2026_key():
    # A 2025 key in the March input is a HARD STOP.
    keys = ["2026-03-01T00:00:00", "2025-12-31T23:59:00"]
    with pytest.raises(ValueError, match="non-March-2026"):
        assert_holdout_inputs_are_march_2026(keys)


def test_score_march_raises_when_march_input_has_2025_row():
    ops_2025 = _build_2025_envelope_around()
    march = _build_march_ops(n=5)
    # Inject one 2025-timestamp row into the "March" input -- this must raise
    # BEFORE any scoring happens.
    march.loc[0, WINDOW_START_COLUMN] = "2025-12-31T23:30:00"
    with pytest.raises(ValueError, match="non-March-2026"):
        score_march_against_envelope(
            operating_points_2025=ops_2025,
            operating_points_2026_03=march,
        )


def test_score_march_raises_when_2025_envelope_has_march_row():
    ops_2025 = _build_2025_envelope_around()
    march = _build_march_ops(n=5)
    # Inject a 2026-03 row into the 2025 envelope -- Sprint-32 guard must fire.
    ops_2025.loc[0, WINDOW_START_COLUMN] = "2026-03-15T00:00:00"
    with pytest.raises(ValueError, match="March-2026"):
        score_march_against_envelope(
            operating_points_2025=ops_2025,
            operating_points_2026_03=march,
        )


# --------------------------------------------------------------------------- #
# 2. Unsupported intervals -> ZERO savings
# --------------------------------------------------------------------------- #
def test_unsupported_intervals_produce_zero_savings():
    # 2025 envelope has only 5 neighbours -- below MIN_SUPPORT (30).
    ops_2025 = _build_2025_envelope_around(n=5)
    march = _build_march_ops(n=4)
    results = score_march_against_envelope(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
    )
    assert len(results) == 4
    for r in results:
        assert r.supported is False
        assert r.reason == EXCLUSION_REASON_INSUFFICIENT_SUPPORT
        assert r.opportunity_kwh_p25 == 0.0
        assert r.opportunity_kwh_p10 == 0.0
        assert r.counterfactual_energy_kwh_p25 == 0.0
        assert r.counterfactual_energy_kwh_p10 == 0.0
    opp = compute_opportunity_summary(results)
    assert opp.kwh_p25 == 0.0
    assert opp.kwh_p10 == 0.0
    assert opp.n_supported_intervals == 0
    assert opp.robust_under_conservative is False


def test_invalid_march_row_is_rejected_with_invalid_input_reason():
    ops_2025 = _build_2025_envelope_around()
    march = _build_march_ops(n=3)
    # Inject NaN into a matching channel -- the row is unscoreable.
    march.loc[0, "mean_demand_m3_per_h"] = float("nan")
    results = score_march_against_envelope(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
    )
    invalid = [r for r in results if r.reason == EXCLUSION_REASON_INVALID_INPUT]
    assert len(invalid) == 1
    inv = invalid[0]
    assert inv.supported is False
    assert inv.opportunity_kwh_p25 == 0.0
    assert inv.opportunity_kwh_p10 == 0.0


# --------------------------------------------------------------------------- #
# 3. Opportunity on a fixture with KNOWN answer
# --------------------------------------------------------------------------- #
def test_opportunity_on_fixture_matches_hand_computed_kwh():
    # Build a tight 2025 envelope where every row has SE = 0.08 (the
    # "efficient" baseline). p25 == p10 == 0.08.
    n = MIN_SUPPORT + 5
    ops_2025 = pd.DataFrame([
        _make_op_2025(
            window_start=(pd.Timestamp("2025-07-01T00:00:00") + pd.Timedelta(minutes=30 * i)).isoformat(),
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=40.0, se=0.08,
        )
        for i in range(n)
    ])

    # March OperatingPoint: same context, volume = 100 m^3, SE_obs = 0.10 ->
    # observed energy = 10.0 kWh.
    # Counterfactual at p25 (0.08) -> 0.08 * 100 = 8.0 kWh; opportunity = 2.0 kWh.
    # Counterfactual at p10 (0.08) -> 0.08 * 100 = 8.0 kWh; opportunity = 2.0 kWh.
    march = pd.DataFrame([
        _make_op_2025(
            window_start="2026-03-05T00:00:00",
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=45.0, se=0.10,
        ),
    ])

    results = score_march_against_envelope(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
    )
    assert len(results) == 1
    r = results[0]
    assert r.supported is True
    assert r.reason is None
    # Hand-computed: SE_obs = 0.10, volume = 100, energy = 10.0 kWh.
    assert r.energy_kwh == pytest.approx(10.0, rel=1e-6)
    # p25 = p10 = 0.08, so counterfactual = 8.0 kWh, opportunity = 2.0 kWh.
    assert r.se_p25 == pytest.approx(0.08, rel=1e-6)
    assert r.se_p10 == pytest.approx(0.08, rel=1e-6)
    assert r.counterfactual_energy_kwh_p25 == pytest.approx(8.0, rel=1e-6)
    assert r.opportunity_kwh_p25 == pytest.approx(2.0, rel=1e-6)
    assert r.opportunity_kwh_p10 == pytest.approx(2.0, rel=1e-6)

    opp = compute_opportunity_summary(results)
    assert opp.kwh_p25 == pytest.approx(2.0, rel=1e-6)
    assert opp.kwh_p10 == pytest.approx(2.0, rel=1e-6)
    assert opp.n_supported_intervals == 1
    assert opp.robust_under_conservative is True
    assert opp.conservative_quantile == CONSERVATIVE_QUANTILE


def test_opportunity_clamped_at_zero_when_march_already_efficient():
    # March operates AT the envelope's p25; opportunity must clamp to 0.
    n = MIN_SUPPORT + 5
    ops_2025 = pd.DataFrame([
        _make_op_2025(
            window_start=(pd.Timestamp("2025-07-01T00:00:00") + pd.Timedelta(minutes=30 * i)).isoformat(),
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=40.0, se=0.08,
        )
        for i in range(n)
    ])
    march = pd.DataFrame([
        # Already efficient: SE = 0.05 (BELOW the envelope's p25 = 0.08).
        _make_op_2025(
            window_start="2026-03-05T00:00:00",
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=38.0, se=0.05,
        ),
    ])
    results = score_march_against_envelope(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
    )
    assert len(results) == 1
    r = results[0]
    assert r.supported is True
    # Observed energy = 0.05 * 100 = 5.0 kWh; counterfactual at p25 = 8.0;
    # opportunity = max(0, 5 - 8) = 0.
    assert r.opportunity_kwh_p25 == 0.0
    assert r.opportunity_kwh_p10 == 0.0


def test_tariff_avoided_cost_only_when_tariff_supplied():
    n = MIN_SUPPORT + 5
    ops_2025 = pd.DataFrame([
        _make_op_2025(
            window_start=(pd.Timestamp("2025-07-01T00:00:00") + pd.Timedelta(minutes=30 * i)).isoformat(),
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=40.0, se=0.08,
        )
        for i in range(n)
    ])
    march = pd.DataFrame([
        _make_op_2025(
            window_start="2026-03-05T00:00:00",
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=45.0, se=0.10,
        ),
    ])
    results = score_march_against_envelope(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
    )
    # No tariff -> avoided_cost = None, tariff_source = None.
    opp_no_tariff = compute_opportunity_summary(results)
    assert opp_no_tariff.avoided_cost is None
    assert opp_no_tariff.tariff_source is None

    # Tariff = 3.0 (per kWh), 2.0 kWh -> avoided_cost = 6.0.
    opp_tariff = compute_opportunity_summary(
        results, tariff_per_kwh=3.0, tariff_source="test_input"
    )
    assert opp_tariff.avoided_cost == pytest.approx(6.0, rel=1e-6)
    assert opp_tariff.tariff_source == "test_input"

    # Tariff without source -> raise (we never invent attribution).
    with pytest.raises(ValueError, match="tariff_source"):
        compute_opportunity_summary(results, tariff_per_kwh=3.0)
    with pytest.raises(ValueError, match="finite, non-negative"):
        compute_opportunity_summary(
            results, tariff_per_kwh=-1.0, tariff_source="bad"
        )


# --------------------------------------------------------------------------- #
# 4. Conservative-quantile robustness flag
# --------------------------------------------------------------------------- #
def test_conservative_quantile_robustness_flag_flips_on_zero_opportunity():
    n = MIN_SUPPORT + 5
    # Envelope at SE = 0.10; March at SE = 0.10 -> opportunity = 0.
    ops_2025 = pd.DataFrame([
        _make_op_2025(
            window_start=(pd.Timestamp("2025-07-01T00:00:00") + pd.Timedelta(minutes=30 * i)).isoformat(),
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=40.0, se=0.10,
        )
        for i in range(n)
    ])
    march = pd.DataFrame([
        _make_op_2025(
            window_start="2026-03-05T00:00:00",
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=40.0, se=0.10,
        ),
    ])
    results = score_march_against_envelope(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
    )
    opp = compute_opportunity_summary(results)
    assert opp.kwh_p25 == pytest.approx(0.0, abs=1e-9)
    # Robustness flag must be FALSE because there's no positive opportunity.
    assert opp.robust_under_conservative is False


# --------------------------------------------------------------------------- #
# 5. Scorecard schema
# --------------------------------------------------------------------------- #
def test_scorecard_has_all_required_schema_keys_and_pass_verdict():
    ops_2025 = _build_2025_envelope_around(n=MIN_SUPPORT + 20)
    # March context inside the envelope cluster; high SE -> positive opportunity.
    march = _build_march_ops(n=6, se=0.20, speed=45.0)
    sc = build_sprint33_scorecard(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
        holdout_window=_holdout_window(march),
        march_csv_path="<test-march-csv>",
        operating_points_2025_csv_path="<test-2025-ops>",
    )
    # Identity + safety contract.
    assert sc["sprint"] == SPRINT
    assert sc["pillar"] == "B"
    assert sc["advisory_only"] is True
    assert sc["evaluation_mode"] == "offline_only"
    assert sc["report_version"] == REPORT_VERSION

    # holdout_window block carries every required key.
    hw = sc["holdout_window"]
    for k in ("csv_path", "first_timestamp", "last_timestamp", "all_in_2026_03", "n_rows"):
        assert k in hw
    assert hw["all_in_2026_03"] is True

    # frozen_gate block.
    fg = sc["frozen_gate"]
    assert fg["gate_version"] == GATE_VERSION
    assert isinstance(fg["gate_file_sha256_at_eval"], str)
    assert len(fg["gate_file_sha256_at_eval"]) == 64
    assert fg["se_quantiles"] == [0.10, 0.25]
    assert fg["min_support"] == int(MIN_SUPPORT)
    assert fg["march_used_for_tuning"] is False

    # coverage_waterfall + explanation.
    wf = sc["coverage_waterfall"]
    for k in ("total", "valid", "supported", "unsupported", "exclusion_reasons"):
        assert k in wf
    assert wf["total"] == len(march)
    assert wf["supported"] + wf["unsupported"] == wf["total"]
    assert isinstance(sc["coverage_explanation"], str) and sc["coverage_explanation"]

    # opportunity.
    opp = sc["opportunity"]
    for k in ("kwh_p25", "kwh_p10", "n_supported_intervals",
              "conservative_quantile", "robust_under_conservative",
              "avoided_cost", "tariff_source"):
        assert k in opp
    assert opp["conservative_quantile"] == CONSERVATIVE_QUANTILE
    # In a positive-opportunity fixture, robust flag is True.
    assert opp["robust_under_conservative"] is True
    # Tariff was not supplied -> None.
    assert opp["avoided_cost"] is None
    assert opp["tariff_source"] is None

    # mvpv1_comparison present (not aligned because no log was supplied).
    mc = sc["mvpv1_comparison"]
    assert mc["available"] is False
    assert mc["valid"] is False

    # leakage_check block.
    lk = sc["leakage_check"]
    assert lk["march_only_input"] is True
    assert lk["isolation_assert_passed"] is True
    assert lk["holdout_prefix"] == "2026-03"
    assert isinstance(lk["frozen_gate_file_sha256_at_eval"], str)

    # out_of_sample_protocol.
    osp = sc["out_of_sample_protocol"]
    assert "description" in osp
    assert "honest_limitations" in osp
    assert len(osp["honest_limitations"]) >= 3

    # acceptance_gate has the five criteria.
    gate = sc["acceptance_gate"]
    names = {c["name"] for c in gate["criteria"]}
    assert names == {
        "coverage_meaningful_or_limitations_explained",
        "positive_opportunity_robust_under_conservative_quantile",
        "no_unsupported_interval_produces_savings",
        "mvpv1_comparison_valid_where_reported",
        "leakage_and_safety_checks_pass",
    }
    assert gate["verdict"] == ("PASS" if gate["passed"] else "FAIL")
    # On this favourable fixture the gate must PASS.
    assert gate["passed"] is True
    assert sc["verdict"] == "PASS"

    # safety block invariants.
    s = sc["safety"]
    assert s["advisory_only"] is True
    assert s["evaluation_mode"] == "offline_only"
    assert s["influences_control"] is False
    assert s["site_integration_allowed"] is False


def test_scorecard_fails_when_no_positive_opportunity():
    """If conservative-quantile opportunity is 0, the gate must FAIL.

    A FAIL on this synthetic fixture proves the gate is applied honestly -- it
    does not auto-pass just because everything else looks clean.
    """
    n = MIN_SUPPORT + 5
    ops_2025 = pd.DataFrame([
        _make_op_2025(
            window_start=(pd.Timestamp("2025-07-01T00:00:00") + pd.Timedelta(minutes=30 * i)).isoformat(),
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=40.0, se=0.10,
        )
        for i in range(n)
    ])
    march = pd.DataFrame([
        # SE = 0.05 below envelope p25 -> opportunity clamped to 0.
        _make_op_2025(
            window_start="2026-03-05T00:00:00",
            demand=1500.0, level=5.0, pressure=1.5, flow=1400.0,
            speed=38.0, se=0.05,
        ),
    ])
    sc = build_sprint33_scorecard(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
        holdout_window=_holdout_window(march),
        march_csv_path="<test-march-csv>",
        operating_points_2025_csv_path="<test-2025-ops>",
    )
    assert sc["opportunity"]["kwh_p25"] == pytest.approx(0.0, abs=1e-9)
    assert sc["opportunity"]["robust_under_conservative"] is False
    # C2 must FAIL.
    c2 = next(
        c for c in sc["acceptance_gate"]["criteria"]
        if c["name"] == "positive_opportunity_robust_under_conservative_quantile"
    )
    assert c2["passed"] is False
    assert sc["acceptance_gate"]["passed"] is False
    assert sc["verdict"] == "FAIL"


# --------------------------------------------------------------------------- #
# 6. Pre-registration integrity: frozen-gate-file SHA-256 round-trip
# --------------------------------------------------------------------------- #
def test_recorded_frozen_gate_sha_matches_actual_on_disk_hash():
    """C5-supporting integrity probe.

    The scorecard's ``frozen_gate.gate_file_sha256_at_eval`` MUST equal the
    SHA-256 of the on-disk ``efficiency_gate.py`` file. If a developer modifies
    the frozen gate file between Sprint 32 ship and Sprint 33 evaluation, the
    pre-registration is broken and this test fails -- the integrity contract.
    """
    gate_path = efficiency_gate_module_path()
    assert gate_path.name == "efficiency_gate.py"
    on_disk = hashlib.sha256(gate_path.read_bytes()).hexdigest()
    # API parity.
    assert read_frozen_gate_file_sha256() == on_disk

    ops_2025 = _build_2025_envelope_around(n=MIN_SUPPORT + 20)
    march = _build_march_ops(n=4, se=0.20, speed=45.0)
    sc = build_sprint33_scorecard(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
        holdout_window=_holdout_window(march),
        march_csv_path="<test-march-csv>",
        operating_points_2025_csv_path="<test-2025-ops>",
    )
    recorded = sc["frozen_gate"]["gate_file_sha256_at_eval"]
    assert recorded == on_disk, (
        "FROZEN gate file hash drift detected -- pre-registration broken. "
        f"on_disk={on_disk!r}, recorded={recorded!r}"
    )
    # Same hash appears in leakage_check.
    assert sc["leakage_check"]["frozen_gate_file_sha256_at_eval"] == on_disk


# --------------------------------------------------------------------------- #
# 7. Coverage waterfall accounting invariants
# --------------------------------------------------------------------------- #
def test_coverage_waterfall_accounting_invariants():
    ops_2025 = _build_2025_envelope_around(n=MIN_SUPPORT + 10)
    march = _build_march_ops(n=5, se=0.20)
    # Inject one OOD row + one invalid row.
    march.loc[1, "mean_demand_m3_per_h"] = 99_999.0  # OOD
    march.loc[2, "mean_level_m"] = float("nan")     # invalid
    results = score_march_against_envelope(
        operating_points_2025=ops_2025,
        operating_points_2026_03=march,
    )
    waterfall = build_coverage_waterfall(results)
    assert waterfall.total == len(march)
    # total == supported + unsupported.
    assert waterfall.supported + waterfall.unsupported == waterfall.total
    # invalid input is captured by name.
    assert EXCLUSION_REASON_INVALID_INPUT in waterfall.exclusion_reasons
    # at least one OOD row rejected with insufficient_support.
    assert (
        waterfall.exclusion_reasons.get(EXCLUSION_REASON_INSUFFICIENT_SUPPORT, 0) >= 1
    )
    # invalid != valid: valid = total - invalid_inputs.
    assert waterfall.valid <= waterfall.total
