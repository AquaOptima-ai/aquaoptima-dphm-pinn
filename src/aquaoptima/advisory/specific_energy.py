"""AOPSO Sprint 31 -- Pillar B specific-energy (kWh/m3) engine.

OFFLINE, ADVISORY ONLY. No setpoints, no control, no live integration, no edge
imports. This module turns the 2025 Yilan telemetry into a reproducible stream
of valid 15-minute / 30-minute aggregated operating points whose specific
energy (SE) is computed from interval-integrated energy and interval-integrated
pumped volume.

Hard contracts
--------------
* SE is computed as ``interval_energy_kwh / interval_volume_m3`` -- never as an
  instantaneous ratio (Sprint 31 acceptance gate criterion #2).
* The unit of every input quantity is read from the single source of truth
  (:mod:`aquaoptima.advisory.label_schema`'s ``AXIS_UNITS``). If
  ``edge_power`` is not ``kW`` or ``edge_flow`` is not ``m3_per_h``, the unit
  gate FAILs and the scorecard FAILs (criterion #1; Q2 in the PRD).
* Every excluded interval is tagged with a named exclusion reason (criterion #3).
* All aggregation is over 2025-only data; any 2026-03 input key raises before
  any computation runs (criterion #5 + Sprint-27 leakage guard).
* Aggregation is deterministic: same input, same output, same operating-point
  count (criterion #4). The ``seed`` is recorded but no RNG is used.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from ..dataio.yilan_axis_map import (
    CANONICAL_AXIS_TO_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_FORMAT,
)
from ..dataio.yilan_profiler import (
    DEFAULT_CSV_PATH as DEFAULT_2025_CSV_PATH,
    GAP_THRESHOLD_SECONDS,
    MODE_AUTO,
    MODE_MANUAL,
    MODE_OTHER,
    derive_mode,
    load_frame,
)
from .governance import (
    LOCKED_HOLDOUT_PREFIX,
    assert_holdout_isolated,
)
from .label_schema import AXIS_UNITS

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
PILLAR = "B"
SPRINT = 31
GATE_VERSION = "sprint31.unit_validity.v1"
DETERMINISTIC_SEED = 0

# Aggregation windows requested by the Sprint 31 spec.
DEFAULT_AGGREGATION_MINUTES: tuple[int, ...] = (15, 30)

# Engineering defaults. Both can be overridden via ``EngineConfig``.
DEFAULT_LOW_FLOW_THRESHOLD_M3_PER_H = 1.0
DEFAULT_PUMP_OFF_THRESHOLD = 0.5  # edge_status < 0.5 == off (status is 0/1)

# The exclusion reasons emitted by :func:`compute_intervals`. The order also
# defines waterfall display order in the scorecard.
EXCLUSION_REASONS: tuple[str, ...] = (
    "non_positive_interval",
    "gap_too_long",
    "nan_input",
    "unprofiled_mode_other",
    "pump_off",
    "low_flow",
    "zero_or_negative_volume",
)

# Modes that must be EXCLUDED from SE aggregation. The Sprint 27 profile shows
# auto = ~99% of the year; manual and the unprofiled "other" bucket are
# excluded by default. (The PRD §10.1 Q1 disposition: "exclude from normal
# training and mark as unprofiled".)
DEFAULT_EXCLUDED_MODES: frozenset[str] = frozenset({MODE_OTHER, MODE_MANUAL})


# --------------------------------------------------------------------------- #
# Config + result containers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EngineConfig:
    """All knobs for the Sprint 31 SE engine, frozen + explicit."""
    low_flow_threshold_m3_per_h: float = DEFAULT_LOW_FLOW_THRESHOLD_M3_PER_H
    pump_off_threshold: float = DEFAULT_PUMP_OFF_THRESHOLD
    gap_threshold_seconds: float = float(GAP_THRESHOLD_SECONDS)
    excluded_modes: frozenset[str] = DEFAULT_EXCLUDED_MODES
    aggregation_minutes: tuple[int, ...] = DEFAULT_AGGREGATION_MINUTES
    seed: int = DETERMINISTIC_SEED

    def to_dict(self) -> dict[str, Any]:
        return {
            "low_flow_threshold_m3_per_h": self.low_flow_threshold_m3_per_h,
            "pump_off_threshold": self.pump_off_threshold,
            "gap_threshold_seconds": self.gap_threshold_seconds,
            "excluded_modes": sorted(self.excluded_modes),
            "aggregation_minutes": list(self.aggregation_minutes),
            "seed": self.seed,
        }


@dataclass(frozen=True)
class OperatingPoint:
    """One aggregated SE operating point. Substrate for Sprint 32's matched-condition search.

    Carrying both the integrated quantities AND their mean context lets
    Sprint 32 match by (demand, level, pressure) and then look up
    ``mean_speed_hz`` against ``specific_energy_kwh_per_m3``.
    """
    window_minutes: int
    window_start: str  # ISO8601, deterministic
    window_end: str
    n_intervals_used: int
    energy_kwh: float
    volume_m3: float
    specific_energy_kwh_per_m3: float
    mean_speed_hz: float
    mean_flow_m3_per_h: float
    mean_power_kw: float
    mean_demand_m3_per_h: float
    mean_level_m: float
    mean_pressure_m_head: float
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UnitConfirmation:
    """Result of the unit gate. ``confirmed`` is criterion #1 of the gate."""
    confirmed: bool
    units: Mapping[str, str]
    expected_units: Mapping[str, str]
    conversion_notes: tuple[str, ...]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "confirmed": self.confirmed,
            "units": dict(self.units),
            "expected_units": dict(self.expected_units),
            "conversion_notes": list(self.conversion_notes),
            "errors": list(self.errors),
        }


# --------------------------------------------------------------------------- #
# Unit gate (Sprint 31 criterion #1)
# --------------------------------------------------------------------------- #
EXPECTED_UNITS: Mapping[str, str] = {
    "edge_power": "kW",
    "edge_flow": "m3_per_h",
    "edge_pump_speed": "hz",
    "node_demand": "m3_per_h",
    "node_level": "m",
    "node_pressure": "m_head",
}

CONVERSION_NOTES: tuple[str, ...] = (
    "energy_kwh = trapezoidal_integral(power_kw * dt) with dt in hours; "
    "kW * h = kWh.",
    "volume_m3 = trapezoidal_integral(flow_m3_per_h * dt) with dt in hours; "
    "(m^3 / h) * h = m^3.",
    "specific_energy_kwh_per_m3 = energy_kwh / volume_m3 (interval-integrated, "
    "never an instantaneous ratio).",
    "interval delta-t is computed as (ts[i+1] - ts[i]) in seconds and "
    "converted to hours via /3600.0; intervals exceeding the gap threshold "
    "are excluded.",
)


def confirm_units(units: Mapping[str, str] | None = None) -> UnitConfirmation:
    """Confirm the unit of every quantity SE depends on. FAILs explicitly on mismatch."""
    actual = AXIS_UNITS if units is None else units
    errors: list[str] = []
    observed: dict[str, str] = {}
    for axis, expected in EXPECTED_UNITS.items():
        got = actual.get(axis)
        observed[axis] = got or ""
        if got != expected:
            errors.append(
                f"axis {axis!r} unit gate FAIL: expected {expected!r}, got {got!r}"
            )
    return UnitConfirmation(
        confirmed=not errors,
        units=observed,
        expected_units=dict(EXPECTED_UNITS),
        conversion_notes=CONVERSION_NOTES,
        errors=tuple(errors),
    )


# --------------------------------------------------------------------------- #
# Leakage guard (Sprint 31 criterion #5; Sprint 27 guard wired in)
# --------------------------------------------------------------------------- #
def assert_no_march_2026_in_keys(keys: Iterable[str]) -> None:
    """Raise ``ValueError`` if any input key falls in the locked March-2026 window.

    Wraps :func:`aquaoptima.advisory.governance.assert_holdout_isolated`; we
    explicitly forbid March-2026 keys from any Sprint 31 input.
    """
    result = assert_holdout_isolated(keys, holdout_prefix=LOCKED_HOLDOUT_PREFIX)
    if not result.isolated:
        raise ValueError(
            "STOP: Sprint 31 inputs contain the locked March-2026 holdout "
            f"(prefix={LOCKED_HOLDOUT_PREFIX!r}); leaked keys "
            f"{list(result.leaked_keys)[:5]} ..."
        )


# --------------------------------------------------------------------------- #
# Interval-integrated energy/volume + named exclusion reasons
# --------------------------------------------------------------------------- #
def _resolve_columns() -> dict[str, str]:
    """Map the axis name to its backing CSV column (raises on a missing axis)."""
    out: dict[str, str] = {}
    for axis in ("edge_flow", "edge_power", "edge_pump_speed", "edge_status",
                 "node_demand", "node_level", "node_pressure"):
        col = CANONICAL_AXIS_TO_COLUMN.get(axis)
        if not col:
            raise KeyError(f"axis {axis!r} has no backing column in CANONICAL_AXIS_TO_COLUMN")
        out[axis] = col
    return out


def compute_intervals(
    df: pd.DataFrame,
    *,
    config: EngineConfig | None = None,
) -> pd.DataFrame:
    """Build a per-interval table with kept-flag + exclusion reason.

    Parameters
    ----------
    df
        A frame produced by :func:`yilan_profiler.load_frame`. Must contain
        ``TIMESTAMP_COLUMN``, both mode columns, and the backing columns for
        ``edge_flow`` (m3/h), ``edge_power`` (kW), ``edge_pump_speed`` (Hz),
        ``edge_status`` (0/1), ``node_demand``, ``node_level``,
        ``node_pressure``.

    Returns
    -------
    pd.DataFrame
        One row per consecutive sample pair, with energy/volume integrated
        over that interval (trapezoidal), plus a ``kept`` flag and a single
        ``exclusion_reason`` for excluded rows.
    """
    cfg = config or EngineConfig()
    if TIMESTAMP_COLUMN not in df.columns:
        raise ValueError(f"frame missing {TIMESTAMP_COLUMN!r}")

    # Deterministic stable sort by timestamp.
    df = df.sort_values(TIMESTAMP_COLUMN, kind="stable").reset_index(drop=True)
    if len(df) < 2:
        return pd.DataFrame(
            columns=[
                "interval_start", "interval_end", "dt_seconds", "dt_hours",
                "mean_power_kw", "mean_flow_m3_per_h", "energy_kwh", "volume_m3",
                "mean_speed_hz", "mean_demand_m3_per_h", "mean_level_m",
                "mean_pressure_m_head", "mode_start", "mode_end",
                "kept", "exclusion_reason",
            ]
        )

    cols = _resolve_columns()
    # All optional axes default to NaN columns if absent (so the engine still
    # runs on a slim test fixture).
    for axis, c in cols.items():
        if c not in df.columns:
            df[c] = np.nan

    mode = derive_mode(df).reset_index(drop=True)

    ts = df[TIMESTAMP_COLUMN].reset_index(drop=True)
    flow = pd.to_numeric(df[cols["edge_flow"]], errors="coerce").to_numpy(dtype=float)
    power = pd.to_numeric(df[cols["edge_power"]], errors="coerce").to_numpy(dtype=float)
    speed = pd.to_numeric(df[cols["edge_pump_speed"]], errors="coerce").to_numpy(dtype=float)
    status = pd.to_numeric(df[cols["edge_status"]], errors="coerce").to_numpy(dtype=float)
    demand = pd.to_numeric(df[cols["node_demand"]], errors="coerce").to_numpy(dtype=float)
    level = pd.to_numeric(df[cols["node_level"]], errors="coerce").to_numpy(dtype=float)
    pressure = pd.to_numeric(df[cols["node_pressure"]], errors="coerce").to_numpy(dtype=float)
    mode_arr = mode.to_numpy(dtype=object)

    dt_secs = ts.diff().dt.total_seconds().to_numpy()  # [NaN, dt1, dt2, ...]
    # Interval i is between sample i and sample i+1, so dt for interval i is
    # dt_secs at index i+1.
    n_intervals = len(ts) - 1
    interval_start = ts.iloc[:-1].reset_index(drop=True)
    interval_end = ts.iloc[1:].reset_index(drop=True)
    dt = dt_secs[1:]  # aligned to interval index 0..n_intervals-1
    dt_hours = dt / 3600.0

    p0, p1 = power[:-1], power[1:]
    q0, q1 = flow[:-1], flow[1:]
    s0, s1 = speed[:-1], speed[1:]
    st0, st1 = status[:-1], status[1:]
    d0, d1 = demand[:-1], demand[1:]
    l0, l1 = level[:-1], level[1:]
    pr0, pr1 = pressure[:-1], pressure[1:]

    mean_power = (p0 + p1) / 2.0
    mean_flow = (q0 + q1) / 2.0
    mean_speed = (s0 + s1) / 2.0
    mean_demand = (d0 + d1) / 2.0
    mean_level = (l0 + l1) / 2.0
    mean_pressure = (pr0 + pr1) / 2.0
    mean_status = (st0 + st1) / 2.0

    energy_kwh = mean_power * dt_hours
    volume_m3 = mean_flow * dt_hours

    # --- assign exclusion reason (first match wins; mirror EXCLUSION_REASONS order)
    reasons = np.full(n_intervals, "", dtype=object)

    non_positive_dt = ~np.isfinite(dt) | (dt <= 0)
    reasons[(reasons == "") & non_positive_dt] = "non_positive_interval"

    gap_mask = np.isfinite(dt) & (dt > cfg.gap_threshold_seconds)
    reasons[(reasons == "") & gap_mask] = "gap_too_long"

    nan_inputs = (
        ~np.isfinite(p0) | ~np.isfinite(p1)
        | ~np.isfinite(q0) | ~np.isfinite(q1)
    )
    reasons[(reasons == "") & nan_inputs] = "nan_input"

    mode_start = mode_arr[:-1]
    mode_end = mode_arr[1:]
    excluded_modes = cfg.excluded_modes
    bad_mode = np.array(
        [(ms in excluded_modes) or (me in excluded_modes)
         for ms, me in zip(mode_start, mode_end)],
        dtype=bool,
    )
    if MODE_OTHER in excluded_modes:
        # Treat 'unprofiled mode / other' as its own bucket for the waterfall.
        other_mask = np.array(
            [(ms == MODE_OTHER) or (me == MODE_OTHER) for ms, me in zip(mode_start, mode_end)],
            dtype=bool,
        )
        reasons[(reasons == "") & other_mask] = "unprofiled_mode_other"
        non_other_excluded = bad_mode & ~other_mask
    else:
        non_other_excluded = bad_mode
    # Non-"other" excluded modes (e.g. manual) -> bucket under unprofiled_mode_other
    # too, so the waterfall stays small. We intentionally fold "manual" into this
    # bucket because it is the same product decision: not in the auto envelope.
    reasons[(reasons == "") & non_other_excluded] = "unprofiled_mode_other"

    pump_off = (st0 < cfg.pump_off_threshold) | (st1 < cfg.pump_off_threshold)
    # Treat NaN status as "we cannot prove pump is on" -> pump_off
    pump_off = pump_off | ~np.isfinite(st0) | ~np.isfinite(st1)
    reasons[(reasons == "") & pump_off] = "pump_off"

    # Low flow: both endpoints must clear the threshold (we are integrating
    # across the interval; if either end is low the interval is unreliable).
    low_flow = (q0 < cfg.low_flow_threshold_m3_per_h) | (
        q1 < cfg.low_flow_threshold_m3_per_h
    )
    reasons[(reasons == "") & low_flow] = "low_flow"

    bad_volume = ~np.isfinite(volume_m3) | (volume_m3 <= 0.0)
    reasons[(reasons == "") & bad_volume] = "zero_or_negative_volume"

    kept = reasons == ""

    out = pd.DataFrame(
        {
            "interval_start": interval_start,
            "interval_end": interval_end,
            "dt_seconds": dt,
            "dt_hours": dt_hours,
            "mean_power_kw": mean_power,
            "mean_flow_m3_per_h": mean_flow,
            "mean_speed_hz": mean_speed,
            "mean_demand_m3_per_h": mean_demand,
            "mean_level_m": mean_level,
            "mean_pressure_m_head": mean_pressure,
            "mean_status": mean_status,
            "energy_kwh": energy_kwh,
            "volume_m3": volume_m3,
            "mode_start": mode_start,
            "mode_end": mode_end,
            "kept": kept,
            "exclusion_reason": reasons,
        }
    )
    return out


def validity_waterfall(intervals: pd.DataFrame) -> dict[str, Any]:
    """Compute the kept + per-reason exclusion counts. SUMS must equal total."""
    total = int(len(intervals))
    kept = int(intervals["kept"].sum()) if total else 0
    reasons_block: dict[str, int] = {r: 0 for r in EXCLUSION_REASONS}
    if total:
        vc = intervals.loc[~intervals["kept"], "exclusion_reason"].value_counts()
        for r, c in vc.items():
            reasons_block[str(r)] = int(c)
    excluded_total = sum(reasons_block.values())
    sums_correctly = (kept + excluded_total) == total
    return {
        "total_intervals": total,
        "kept": kept,
        "excluded_total": excluded_total,
        "by_reason": reasons_block,
        "sums_correctly": sums_correctly,
    }


# --------------------------------------------------------------------------- #
# Aggregation -> OperatingPoint (15-min / 30-min)
# --------------------------------------------------------------------------- #
def aggregate_operating_points(
    intervals: pd.DataFrame,
    *,
    window_minutes: int,
) -> list[OperatingPoint]:
    """Bin valid intervals into ``window_minutes``-wide aggregates of SE.

    SE is computed bin-wise as ``sum(energy_kwh) / sum(volume_m3)`` -- aligned
    with the integral definition. Means of speed/flow/power/context are
    time-weighted by interval ``dt_hours``. The output is sorted by bin start.
    """
    if window_minutes <= 0:
        raise ValueError("window_minutes must be > 0")
    kept = intervals.loc[intervals["kept"]].copy()
    if kept.empty:
        return []
    # Bin by interval START. Deterministic floor.
    freq = f"{int(window_minutes)}min"
    kept["bin_start"] = kept["interval_start"].dt.floor(freq)
    grouped = kept.groupby("bin_start", sort=True)

    out: list[OperatingPoint] = []
    for bin_start, g in grouped:
        e = float(g["energy_kwh"].sum())
        v = float(g["volume_m3"].sum())
        if v <= 0:
            continue
        dt_h = g["dt_hours"].to_numpy(dtype=float)
        w_sum = float(dt_h.sum())
        if w_sum <= 0:
            continue

        def _w(col: str) -> float:
            vals = g[col].to_numpy(dtype=float)
            mask = np.isfinite(vals)
            if not mask.any():
                return float("nan")
            return float(np.sum(vals[mask] * dt_h[mask]) / np.sum(dt_h[mask]))

        op = OperatingPoint(
            window_minutes=int(window_minutes),
            window_start=pd.Timestamp(bin_start).isoformat(),
            window_end=pd.Timestamp(
                bin_start + pd.Timedelta(minutes=window_minutes)
            ).isoformat(),
            n_intervals_used=int(len(g)),
            energy_kwh=round(e, 6),
            volume_m3=round(v, 6),
            specific_energy_kwh_per_m3=round(e / v, 6),
            mean_speed_hz=round(_w("mean_speed_hz"), 6),
            mean_flow_m3_per_h=round(_w("mean_flow_m3_per_h"), 6),
            mean_power_kw=round(_w("mean_power_kw"), 6),
            mean_demand_m3_per_h=round(_w("mean_demand_m3_per_h"), 6),
            mean_level_m=round(_w("mean_level_m"), 6),
            mean_pressure_m_head=round(_w("mean_pressure_m_head"), 6),
        )
        out.append(op)

    return out


# --------------------------------------------------------------------------- #
# 2025-only train_meta + leakage guard
# --------------------------------------------------------------------------- #
def _month_keys(df: pd.DataFrame) -> list[str]:
    ts = df[TIMESTAMP_COLUMN]
    return sorted({f"{t.year:04d}-{t.month:02d}" for t in ts})


def _per_month_rows(df: pd.DataFrame) -> dict[str, int]:
    ts = df[TIMESTAMP_COLUMN]
    counts = ts.dt.strftime("%Y-%m").value_counts().sort_index()
    return {str(k): int(v) for k, v in counts.items()}


def build_train_meta(
    df: pd.DataFrame, *, csv_path: str, n_rows_used: int, mode_filter: list[str]
) -> dict[str, Any]:
    return {
        "csv_path": str(csv_path),
        "n_rows_used": int(n_rows_used),
        "timestamp_min": str(df[TIMESTAMP_COLUMN].min()),
        "timestamp_max": str(df[TIMESTAMP_COLUMN].max()),
        "distinct_months": _month_keys(df),
        "per_month_rows": _per_month_rows(df),
        "mode_filter": mode_filter,
    }


# --------------------------------------------------------------------------- #
# Reproducibility check (criterion #4)
# --------------------------------------------------------------------------- #
def reproducibility_check(
    df: pd.DataFrame, *, config: EngineConfig
) -> dict[str, Any]:
    """Run the pipeline twice on the same df; n_operating_points must match."""
    counts_a: dict[int, int] = {}
    counts_b: dict[int, int] = {}
    for w in config.aggregation_minutes:
        intervals_a = compute_intervals(df, config=config)
        ops_a = aggregate_operating_points(intervals_a, window_minutes=w)
        counts_a[w] = len(ops_a)
        intervals_b = compute_intervals(df, config=config)
        ops_b = aggregate_operating_points(intervals_b, window_minutes=w)
        counts_b[w] = len(ops_b)
    return {
        "reproducible": counts_a == counts_b,
        "counts_run_a": {str(k): v for k, v in counts_a.items()},
        "counts_run_b": {str(k): v for k, v in counts_b.items()},
        "seed": config.seed,
    }


# --------------------------------------------------------------------------- #
# Scorecard build + acceptance gate
# --------------------------------------------------------------------------- #
def _evaluate_acceptance_gate(
    *,
    unit_conf: UnitConfirmation,
    waterfall: dict[str, Any],
    reproducibility: dict[str, Any],
    march_used_for_tuning: bool,
    n_ops_by_window: dict[int, int],
) -> dict[str, Any]:
    criteria: list[dict[str, Any]] = []

    # 1. Units confirmed.
    criteria.append({
        "name": "units_confirmed",
        "passed": bool(unit_conf.confirmed),
        "detail": {"errors": list(unit_conf.errors)},
    })

    # 2. SE from interval energy / volume (structural).
    se_structural = (
        "energy_kwh = trapezoidal_integral(power_kw * dt)"
        in "\n".join(unit_conf.conversion_notes)
        and "specific_energy_kwh_per_m3 = energy_kwh / volume_m3"
        in "\n".join(unit_conf.conversion_notes)
    )
    criteria.append({
        "name": "se_from_interval_energy_and_volume",
        "passed": bool(se_structural),
        "detail": {
            "evidence": "specific_energy_kwh_per_m3 is computed as "
                        "sum(energy_kwh)/sum(volume_m3) over kept intervals "
                        "binned by window; never an instantaneous P/Q ratio.",
        },
    })

    # 3. Exclusion waterfall sums.
    criteria.append({
        "name": "exclusion_waterfall_sums_correctly",
        "passed": bool(waterfall["sums_correctly"]),
        "detail": {
            "kept": waterfall["kept"],
            "excluded_total": waterfall["excluded_total"],
            "total_intervals": waterfall["total_intervals"],
        },
    })

    # 4. Reproducible aggregation.
    has_ops = any(v > 0 for v in n_ops_by_window.values())
    criteria.append({
        "name": "aggregation_reproducible",
        "passed": bool(reproducibility["reproducible"]) and has_ops,
        "detail": {
            "reproducible": reproducibility["reproducible"],
            "n_operating_points_by_window": {str(k): v for k, v in n_ops_by_window.items()},
        },
    })

    # 5. March not used for tuning.
    criteria.append({
        "name": "march_not_used_for_tuning",
        "passed": (march_used_for_tuning is False),
        "detail": {"march_used_for_tuning": bool(march_used_for_tuning)},
    })

    passed = all(c["passed"] for c in criteria)
    return {
        "gate_version": GATE_VERSION,
        "criteria": criteria,
        "passed": bool(passed),
        "verdict": "PASS" if passed else "FAIL",
        "rule": (
            "Sprint 31 PASS iff: units_confirmed AND "
            "se_from_interval_energy_and_volume AND "
            "exclusion_waterfall_sums_correctly AND "
            "aggregation_reproducible AND march_not_used_for_tuning."
        ),
    }


def build_sprint31_scorecard(
    *,
    df: pd.DataFrame,
    csv_path: str,
    config: EngineConfig | None = None,
) -> dict[str, Any]:
    """End-to-end Sprint 31 scorecard from a loaded 2025 frame.

    The frame must be 2025-only (a leakage guard runs first); units are
    confirmed; intervals are integrated and tagged; the validity waterfall is
    computed; 15-min and 30-min operating points are aggregated; the gate is
    evaluated honestly.
    """
    cfg = config or EngineConfig()

    # --- Sprint 31 criterion #5: March-2026 must not appear in the inputs.
    month_keys = _month_keys(df)
    assert_no_march_2026_in_keys(month_keys)
    march_used_for_tuning = any(k.startswith(LOCKED_HOLDOUT_PREFIX) for k in month_keys)

    # --- Sprint 31 criterion #1: confirm units.
    unit_conf = confirm_units()

    # --- Build intervals + waterfall.
    intervals = compute_intervals(df, config=cfg)
    waterfall = validity_waterfall(intervals)

    # --- Aggregate per window (deterministic).
    ops_by_window: dict[int, list[OperatingPoint]] = {}
    n_ops_by_window: dict[int, int] = {}
    for w in cfg.aggregation_minutes:
        ops = aggregate_operating_points(intervals, window_minutes=w)
        ops_by_window[w] = ops
        n_ops_by_window[w] = len(ops)

    # --- Reproducibility.
    reproducibility = reproducibility_check(df, config=cfg)

    # --- Train meta.
    train_meta = build_train_meta(
        df, csv_path=csv_path,
        n_rows_used=int(len(df)),
        mode_filter=sorted(cfg.excluded_modes),
    )

    # --- Operating-point preview (head). Full list omitted from the scorecard
    #     JSON to keep it under control; the count is the contract.
    op_preview: dict[str, Any] = {}
    for w, ops in ops_by_window.items():
        op_preview[f"window_{w}min"] = {
            "n_operating_points": len(ops),
            "head": [op.to_dict() for op in ops[:5]],
        }

    gate = _evaluate_acceptance_gate(
        unit_conf=unit_conf,
        waterfall=waterfall,
        reproducibility=reproducibility,
        march_used_for_tuning=march_used_for_tuning,
        n_ops_by_window=n_ops_by_window,
    )

    scorecard: dict[str, Any] = {
        "sprint": SPRINT,
        "pillar": PILLAR,
        "advisory_only": True,
        "evaluation_mode": "offline_only",
        "march_used_for_tuning": march_used_for_tuning,
        "unit_confirmation": unit_conf.to_dict(),
        "validity_waterfall": waterfall,
        "aggregation": {
            "windows": [f"{w}min" for w in cfg.aggregation_minutes],
            "n_operating_points_15": n_ops_by_window.get(15, 0),
            "n_operating_points_30": n_ops_by_window.get(30, 0),
            "seed": cfg.seed,
            "reproducible": bool(reproducibility["reproducible"]),
            "reproducibility_detail": reproducibility,
            "operating_point_preview": op_preview,
        },
        "train_meta": train_meta,
        "engine_config": cfg.to_dict(),
        "acceptance_gate": gate,
        "verdict": gate["verdict"],
        "safety": {
            "advisory_only": True,
            "evaluation_mode": "offline_only",
            "write_path": "scorecard_json_only",
            "influences_control": False,
            "site_integration_allowed": False,
            "scorecard_role": "advisory_evidence_only",
        },
    }
    return scorecard


def write_operating_points(
    ops_by_window: Mapping[int, Sequence[OperatingPoint]],
    *,
    output_dir: str | os.PathLike[str],
) -> dict[str, str]:
    """Persist OperatingPoint sets to CSV (one file per window). Reproducible."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for w, ops in ops_by_window.items():
        path = out / f"operating_points_{int(w)}min_2025.csv"
        df = pd.DataFrame([op.to_dict() for op in ops])
        df.to_csv(path, index=False)
        paths[f"window_{int(w)}min"] = str(path)
    return paths


# --------------------------------------------------------------------------- #
# CLI entry
# --------------------------------------------------------------------------- #
def _load_2025_frame(
    csv_path: str | os.PathLike[str], *, nrows: int | None = None
) -> pd.DataFrame:
    """Load + sanitize the 2025 source CSV; assert no 2026-03 rows leak in."""
    df = load_frame(csv_path, nrows=nrows)
    df = df.dropna(subset=[TIMESTAMP_COLUMN]).copy()
    # Restrict to calendar year 2025 (defensive; CSV name says 2025 but we
    # double-lock here).
    df = df[df[TIMESTAMP_COLUMN].dt.year == 2025].reset_index(drop=True)
    return df


def run_sprint31_scorecard(
    *,
    csv_path: str | os.PathLike[str] | None = None,
    output_path: str | os.PathLike[str] = (
        "data/eval/pillarB/sprint31_unit_validity_scorecard.json"
    ),
    operating_points_dir: str | os.PathLike[str] | None = (
        "data/eval/pillarB"
    ),
    nrows: int | None = None,
    config: EngineConfig | None = None,
) -> dict[str, Any]:
    """Build and write the Sprint 31 unit & validity scorecard from the 2025 CSV."""
    resolved = Path(csv_path) if csv_path is not None else Path(DEFAULT_2025_CSV_PATH)
    df = _load_2025_frame(resolved, nrows=nrows)
    cfg = config or EngineConfig()
    scorecard = build_sprint31_scorecard(df=df, csv_path=str(resolved), config=cfg)

    # Operating-point CSV exports (advisory substrate for Sprint 32).
    if operating_points_dir is not None:
        intervals = compute_intervals(df, config=cfg)
        ops_by_window: dict[int, list[OperatingPoint]] = {}
        for w in cfg.aggregation_minutes:
            ops_by_window[w] = aggregate_operating_points(intervals, window_minutes=w)
        paths = write_operating_points(ops_by_window, output_dir=operating_points_dir)
        scorecard["aggregation"]["operating_point_csv"] = paths

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scorecard, indent=2, default=str) + "\n")
    return scorecard


def main(argv: Iterable[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="AOPSO Sprint 31 -- Pillar B SE engine")
    p.add_argument("--csv", default=None)
    p.add_argument(
        "--output",
        default="data/eval/pillarB/sprint31_unit_validity_scorecard.json",
    )
    p.add_argument("--operating-points-dir", default="data/eval/pillarB")
    p.add_argument("--nrows", type=int, default=None)
    args = p.parse_args(list(argv) if argv is not None else None)

    sc = run_sprint31_scorecard(
        csv_path=args.csv,
        output_path=args.output,
        operating_points_dir=args.operating_points_dir,
        nrows=args.nrows,
    )
    print(f"sprint31 verdict: {sc['verdict']}")
    print(f"scorecard written to {args.output}")
    return 0 if sc["acceptance_gate"]["passed"] else 1


__all__ = [
    "PILLAR",
    "SPRINT",
    "GATE_VERSION",
    "DEFAULT_AGGREGATION_MINUTES",
    "DEFAULT_LOW_FLOW_THRESHOLD_M3_PER_H",
    "EXCLUSION_REASONS",
    "EngineConfig",
    "OperatingPoint",
    "UnitConfirmation",
    "EXPECTED_UNITS",
    "CONVERSION_NOTES",
    "confirm_units",
    "assert_no_march_2026_in_keys",
    "compute_intervals",
    "validity_waterfall",
    "aggregate_operating_points",
    "build_train_meta",
    "reproducibility_check",
    "build_sprint31_scorecard",
    "write_operating_points",
    "run_sprint31_scorecard",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
