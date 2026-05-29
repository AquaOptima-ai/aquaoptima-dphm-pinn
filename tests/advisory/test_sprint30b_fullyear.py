"""AOPSO Sprint 30b -- full-year stratified 2025 fit-data builder tests.

These tests cover the *mechanics* of the broader, full-year-stratified
fit-data builder used by ``scripts/sprint30b_fullyear_holdout_eval.py``.
They run on tiny synthetic multi-month 2025 fixtures only; the real
489 K-row CSV is never read here. The honest holdout verdict on the locked
March-2026 holdout is produced by running the script against the real CSVs
in a one-off run -- not by these unit tests.

Coverage:
  * stratified per-month fit-builder returns a set spanning multiple 2025
    months with roughly balanced per-month counts;
  * underscore timestamp format (``%Y-%m-%d_%H:%M:%S``) parses correctly;
  * leakage tripwire: a 2026-03 timestamp in the fit input raises
    :class:`LeakageError` BEFORE any fit work happens;
  * the eval pipeline (using the broad fit-builder output) yields a
    v2-shaped verdict dict (shape only; we deliberately do NOT assert
    PASS/FAIL on synthetic data).

All subset/fixture-based, fully deterministic.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import sprint30b_fullyear_holdout_eval as s30b  # noqa: E402

from aquaoptima.advisory.health_baselines import LeakageError  # noqa: E402
from aquaoptima.advisory.health_detector import fit_health_detector  # noqa: E402
from aquaoptima.advisory.label_schema import active_axes_ordered  # noqa: E402
from aquaoptima.dataio.yilan_axis_map import (  # noqa: E402
    CANONICAL_AXIS_TO_COLUMN,
    MODE_AUTO_COLUMN,
    MODE_MANUAL_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_FORMAT,
)


_ACTIVE_AXES = tuple(
    a
    for a in active_axes_ordered()
    if a in CANONICAL_AXIS_TO_COLUMN and CANONICAL_AXIS_TO_COLUMN[a] is not None
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _multi_month_2025_csv(
    months: list[int],
    per_month: int = 80,
    *,
    seed: int = 7,
) -> str:
    """Build a tiny multi-month 2025 CSV string using REAL backing column names.

    All rows are AUTO mode (``auto=True``, ``manual=False``). Timestamps use
    the production ``%Y-%m-%d_%H:%M:%S`` underscore format. Returned as a
    string so callers can wrap with ``StringIO``.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for month in months:
        start = pd.Timestamp(year=2025, month=month, day=2, hour=0, minute=0, second=0)
        ts = pd.date_range(start, periods=per_month, freq="60s")
        flow = rng.normal(loc=1500.0, scale=80.0, size=per_month)
        speed = rng.normal(loc=42.0, scale=1.5, size=per_month)
        power = 0.05 * flow + 1.5 * speed + rng.normal(0.0, 2.0, size=per_month)
        pressure = rng.normal(loc=1.56, scale=0.05, size=per_month)
        level = rng.normal(loc=4.57, scale=0.10, size=per_month)
        demand = rng.normal(loc=1520.0, scale=65.0, size=per_month)
        head = rng.normal(loc=18.3, scale=0.5, size=per_month)
        status = np.clip(rng.normal(0.9999, 0.005, size=per_month), 0.0, 1.0)
        for i in range(per_month):
            rows.append(
                {
                    TIMESTAMP_COLUMN: ts[i].strftime(TIMESTAMP_FORMAT),
                    MODE_AUTO_COLUMN: "True",
                    MODE_MANUAL_COLUMN: "False",
                    "system_pressure": pressure[i],
                    "tank_level": level[i],
                    "tb_system_predicted_flow_rate": demand[i],
                    "tb_system_head": head[i],
                    "system_flow_rate": flow[i],
                    "P_1531A_frequency": speed[i],
                    "P_1531A_status": status[i],
                    "tb_system_real_power": power[i],
                }
            )
    df = pd.DataFrame(rows)
    buf = StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def _march_canonical_frame(n: int = 1200, seed: int = 11) -> pd.DataFrame:
    """A tiny March-2026 frame, canonical-axis-named, with stringified timestamps."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-03-05 00:00:00", periods=n, freq="60s").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    flow = rng.normal(loc=1500.0, scale=70.0, size=n)
    speed = rng.normal(loc=42.0, scale=1.5, size=n)
    power = 0.05 * flow + 1.5 * speed + rng.normal(0.0, 2.0, size=n)
    pressure = rng.normal(loc=1.56, scale=0.05, size=n)
    level = rng.normal(loc=4.57, scale=0.10, size=n)
    demand = rng.normal(loc=1520.0, scale=65.0, size=n)
    head = rng.normal(loc=18.3, scale=0.5, size=n)
    status = np.clip(rng.normal(0.9999, 0.005, size=n), 0.0, 1.0)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "edge_flow": flow,
            "edge_power": power,
            "edge_pump_speed": speed,
            "edge_status": status,
            "node_demand": demand,
            "node_level": level,
            "node_pressure": pressure,
            "node_status": head,
        }
    )


# --------------------------------------------------------------------------- #
# 1) Underscore timestamp format parses correctly
# --------------------------------------------------------------------------- #
def test_underscore_timestamp_format_parses(tmp_path: Path) -> None:
    csv = _multi_month_2025_csv([3, 4, 5], per_month=10)
    p = tmp_path / "tiny_2025.csv"
    p.write_text(csv)

    # Direct round-trip through pandas to prove the format token is right.
    raw = pd.read_csv(p)
    parsed = pd.to_datetime(
        raw[TIMESTAMP_COLUMN], format=TIMESTAMP_FORMAT, errors="coerce"
    )
    assert parsed.notna().all(), "underscore format must parse every fixture row"
    assert TIMESTAMP_FORMAT == "%Y-%m-%d_%H:%M:%S"


# --------------------------------------------------------------------------- #
# 2) Stratified fit-builder spans multiple months with balanced quotas
# --------------------------------------------------------------------------- #
def test_stratified_fit_spans_multiple_months_with_balanced_counts(
    tmp_path: Path,
) -> None:
    months = [3, 4, 5, 6, 7]
    csv = _multi_month_2025_csv(months, per_month=200)
    p = tmp_path / "tiny_2025_5months.csv"
    p.write_text(csv)

    fit_df, train_meta = s30b.build_stratified_2025_auto_fit(
        csv_path=p,
        target_rows=400,            # 5 months × 80 per month
        per_month_floor=10,
        seed=0,
        min_distinct_months=5,
    )

    # Spans the expected months (5 of them).
    per_month = train_meta["per_month_rows"]
    assert set(per_month.keys()) == {f"2025-0{m}" for m in months}
    assert all(v > 0 for v in per_month.values())
    assert train_meta["distinct_months"] >= 5

    # Roughly balanced -- no single month carries >50% of the fit set
    # (with equal source quotas + balanced sampling).
    total = sum(per_month.values())
    assert total == len(fit_df)
    assert max(per_month.values()) <= 0.5 * total + 5

    # Canonical axis columns are present (the rename happened).
    for axis in _ACTIVE_AXES:
        assert axis in fit_df.columns, f"missing canonical axis {axis!r}"

    # Timestamps are stringified (for the leakage-guard key check) and entirely 2025.
    ts = pd.to_datetime(fit_df["timestamp"])
    assert ts.dt.year.eq(2025).all()


def test_stratified_fit_raises_when_fewer_than_min_months_present(
    tmp_path: Path,
) -> None:
    csv = _multi_month_2025_csv([3, 4], per_month=120)
    p = tmp_path / "tiny_2025_2months.csv"
    p.write_text(csv)
    with pytest.raises(RuntimeError, match=r"fewer than 5 distinct 2025 months"):
        s30b.build_stratified_2025_auto_fit(
            csv_path=p,
            target_rows=200,
            per_month_floor=10,
            seed=0,
            min_distinct_months=5,
        )


# --------------------------------------------------------------------------- #
# 3) Leakage tripwire: a 2026-03 key in fit input must raise
# --------------------------------------------------------------------------- #
def test_fit_detector_rejects_march_2026_keys_from_builder_output(
    tmp_path: Path,
) -> None:
    csv = _multi_month_2025_csv([3, 4, 5, 6, 7], per_month=120)
    p = tmp_path / "tiny_2025_for_leakage.csv"
    p.write_text(csv)
    fit_df, _ = s30b.build_stratified_2025_auto_fit(
        csv_path=p,
        target_rows=400,
        per_month_floor=10,
        seed=0,
        min_distinct_months=5,
    )

    # Stamp one row with a March-2026 timestamp -> fit_health_detector must raise.
    leaked = fit_df.copy()
    leaked.loc[leaked.index[0], "timestamp"] = "2026-03-15 12:00:00"
    with pytest.raises(LeakageError):
        fit_health_detector(leaked, axes=list(_ACTIVE_AXES), seed=0, epochs=2)


# --------------------------------------------------------------------------- #
# 4) End-to-end pipeline emits a v2-shaped verdict dict on tiny fixtures
# --------------------------------------------------------------------------- #
def test_eval_pipeline_emits_v2_verdict_dict(tmp_path: Path) -> None:
    csv = _multi_month_2025_csv([3, 4, 5, 6, 7], per_month=300)
    p = tmp_path / "tiny_2025_eval.csv"
    p.write_text(csv)

    fit_df, train_meta = s30b.build_stratified_2025_auto_fit(
        csv_path=p,
        target_rows=1000,
        per_month_floor=20,
        seed=0,
        min_distinct_months=5,
    )

    march_df = _march_canonical_frame(n=1500)

    sc = s30b.build_sprint30b_scorecard(
        train_df=fit_df,
        march_df=march_df,
        axes=list(_ACTIVE_AXES),
        detector_seed=0,
        fault_seed=29,
        epochs=4,
        n_episodes_per_kind=2,
        drift_window=80,
        stuck_window=60,
        envelope_window=40,
        run_governance=False,
        train_meta=train_meta,
    )

    # Top-level shape contract.
    assert sc["sprint"] == "30b"
    assert sc["pillar"] == "A_health"
    assert sc["safety"]["evaluation_mode"] == "offline_only"
    assert sc["safety"]["write_path"] == "none"
    assert sc["safety"]["influences_control"] is False
    assert sc["safety"]["site_integration_allowed"] is False
    assert sc["holdout_window"]["all_in_2026_03"] is True

    # The broad fit-meta MUST surface per-month breakdown + distinct-month count.
    tm = sc["train_meta"]
    assert "per_month_rows" in tm and isinstance(tm["per_month_rows"], dict)
    assert tm["distinct_months"] >= 5
    assert tm["timestamp_min"].startswith("2025-")
    assert tm["timestamp_max"].startswith("2025-")

    # Gate v2 contract: verdict / gate_version / four criteria / metrics keys.
    gate = sc["acceptance_gate"]
    assert gate["gate_version"] == "v2"
    assert gate["verdict"] in {"PASS", "FAIL"}
    assert isinstance(gate["criteria"], list) and len(gate["criteria"]) == 4
    metrics = gate["metrics"]
    for key in (
        "detector_auroc",
        "baseline_auroc",
        "detector_false_alarm_rate",
        "baseline_false_alarm_rate",
        "detector_mean_lead_time",
        "baseline_mean_lead_time",
    ):
        assert key in metrics

    # Pre-registration metadata preserved verbatim.
    assert sc["frozen_gate_v2"]["preregistered_before_evaluation"] is True
    assert sc["frozen_gate_v2"]["tuned_to_outcome"] is False
    assert sc["gate_version"] == "v2"

    # Unsupervised raw-March flag rates in [0, 1].
    raw = sc["raw_march_flag_rates"]
    for key in ("detector_flag_rate", "baseline_flag_rate"):
        assert key in raw and 0.0 <= raw[key] <= 1.0
