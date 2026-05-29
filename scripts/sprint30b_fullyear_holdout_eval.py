#!/usr/bin/env python3
"""AOPSO Sprint 30b -- Pillar A FULL-YEAR-STRATIFIED locked-March-2026 holdout eval.

Sprint 30 PASSED the pre-registered v2 acceptance gate, but its 30k-row 2025
fit subset collapsed onto a single late-March-2025 slice (the auto-mode rows
sit in non-contiguous blocks across the year, and reading from the head of
the CSV landed inside the first auto block). That made the holdout look like
a same-season March-2025 -> March-2026 comparison, which likely flatters
generalization.

Sprint 30b is the seasonal-confound fix: same locked March-2026 holdout, same
pre-registered v2 gate (imported as-is from main, NOT redefined), but the
detector + baseline are fit on a broad, full-year-stratified 2025 auto-mode
sample so the fit set spans multiple 2025 months instead of one. A FAIL is
acceptable and valuable -- the script reports the REAL verdict and exits 0
on a model FAIL (non-zero only on a true error).

Hard safety boundary (unchanged from Sprint 30)
-----------------------------------------------
* ``evaluation_mode=offline_only``, ``write_path=none`` (scorecard JSON only).
* ``influences_control=False``, ``site_integration_allowed=False``.
* NO ``aquaoptima.edge`` / ``aquaoptima_contracts.edge`` imports. Contracts SDK
  is read-only.
* Strict TDD / seeded. Tests run on small synthetic fixtures, NOT the full CSV.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (_SRC, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Reuse the Sprint-30 plumbing where it already exists -- the only thing that
# really changes is HOW we build the 2025 fit frame.
import sprint30_holdout_eval as s30  # noqa: E402

from aquaoptima.advisory.health_baselines import (  # noqa: E402
    LeakageError,
    fit_health_baseline_suite,
)
from aquaoptima.advisory.health_detector import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_EPOCHS,
    DEFAULT_SEED,
    fit_health_detector,
)
from aquaoptima.advisory.health_gate import (  # noqa: E402
    GATE_V2_AUROC_NONINFERIORITY_TOL,
    GATE_V2_FAR_IMPROVEMENT_FACTOR,
    GATE_V2_LEAD_TIME_TOL,
    GATE_V2_MIN_DETECTOR_AUROC,
    GATE_V2_RULE_TEXT,
    evaluate_detector_vs_baseline,
    health_acceptance_gate_v2,
)
from aquaoptima.advisory.injected_faults import (  # noqa: E402
    DEFAULT_SEED as DEFAULT_FAULT_SEED,
    inject_faults,
)
from aquaoptima.advisory.label_schema import (  # noqa: E402
    MASKED_AXIS,
    active_axes_ordered,
)
from aquaoptima.advisory.schema_validation import (  # noqa: E402
    DEFAULT_MODELING_ROOTS,
    apply_governance_to_verdict,
    build_governance_block,
)
from aquaoptima.dataio.yilan_axis_map import (  # noqa: E402
    CANONICAL_AXIS_TO_COLUMN,
    MODE_AUTO_COLUMN,
    MODE_MANUAL_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_FORMAT,
)


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
DEFAULT_CSV_2025 = s30.DEFAULT_CSV_2025
DEFAULT_CSV_2026 = s30.DEFAULT_CSV_2026
DEFAULT_OUT_PATH = (
    _REPO_ROOT / "data" / "eval" / "pillarA" / "sprint30b_fullyear_holdout_scorecard.json"
)
DEFAULT_SPLIT = s30.DEFAULT_SPLIT
DEFAULT_STATS = s30.DEFAULT_STATS

# Sprint 30 used 30k rows; Sprint 30b targets a broader balanced fit (5x).
DEFAULT_FIT_ROWS = 150_000
DEFAULT_PER_MONTH_FLOOR = 2_000
DEFAULT_MIN_DISTINCT_MONTHS = 5
DEFAULT_MARCH_NROWS = s30.DEFAULT_MARCH_NROWS

SPRINT30B_FIT_ROWS_ENV = "SPRINT30B_FIT_ROWS"
SPRINT30B_FULL_ENV = "SPRINT30B_FULL"
SPRINT30B_MARCH_NROWS_ENV = "SPRINT30B_MARCH_NROWS"

EXIT_OK = 0
EXIT_LEAKAGE = 2
EXIT_NO_DATA = 3
EXIT_RUNTIME = 4


# --------------------------------------------------------------------------- #
# Stratified full-year 2025 auto-mode fit builder (the only real new logic)
# --------------------------------------------------------------------------- #
def _truthy(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin({"true", "1", "1.0"})


def _backing_columns_present(header_cols: list[str]) -> list[str]:
    return [
        col
        for col in CANONICAL_AXIS_TO_COLUMN.values()
        if col is not None and col in header_cols
    ]


def _read_2025_auto_frame(csv_path: Path) -> pd.DataFrame:
    """Read the 2025 CSV, parse timestamps with the underscore format, keep AUTO rows.

    Read with the real ``%Y-%m-%d_%H:%M:%S`` underscore format. Filters to
    rows where the ``auto`` column is truthy (precedence over ``manual``).
    Drops rows where any active backing column is non-finite.
    """
    header = pd.read_csv(csv_path, nrows=0)
    backing = _backing_columns_present(list(header.columns))
    wanted = [TIMESTAMP_COLUMN, MODE_AUTO_COLUMN, MODE_MANUAL_COLUMN, *backing]
    present = [c for c in wanted if c in header.columns]
    if TIMESTAMP_COLUMN not in present:
        raise RuntimeError(
            f"2025 CSV {csv_path} missing required '{TIMESTAMP_COLUMN}' column"
        )

    df = pd.read_csv(csv_path, usecols=present, low_memory=False)
    df[TIMESTAMP_COLUMN] = pd.to_datetime(
        df[TIMESTAMP_COLUMN], format=TIMESTAMP_FORMAT, errors="coerce"
    )
    df = df.dropna(subset=[TIMESTAMP_COLUMN])
    if df[TIMESTAMP_COLUMN].dt.year.eq(2026).any():
        raise LeakageError(
            "2025 training CSV unexpectedly contains 2026 timestamps -- aborting fit"
        )

    # AUTO-mode filter.
    if MODE_AUTO_COLUMN in df.columns:
        df = df[_truthy(df[MODE_AUTO_COLUMN])]
    else:
        raise RuntimeError(
            f"2025 CSV {csv_path} missing required '{MODE_AUTO_COLUMN}' column"
        )

    # Coerce backing columns to numeric and drop non-finite rows.
    for col in backing:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if backing:
        df = df.dropna(subset=backing)

    df = df.sort_values(TIMESTAMP_COLUMN, kind="stable").reset_index(drop=True)
    return df


def _stratified_per_month_sample(
    auto_df: pd.DataFrame,
    *,
    target_rows: int,
    per_month_floor: int,
    seed: int,
) -> tuple[pd.DataFrame, "OrderedDict[str, int]"]:
    """Balanced per-month sampling from a 2025 auto-mode frame.

    Strategy
    --------
    1. Group by calendar month (``YYYY-MM``).
    2. Compute a base per-month quota = ``target_rows // n_months``.
    3. For each month, take ``min(month_size, max(quota, per_month_floor))``
       rows uniformly at random (seeded) WITHOUT replacement. Months smaller
       than the quota contribute everything they have.
    4. Redistribute any shortfall from undersized months to oversized months
       proportionally so the total ends up close to ``target_rows`` without
       letting any single month dominate.

    ``target_rows`` is a soft upper target (we cap, never pad with replacement
    so we never fabricate data). If the caller sets ``target_rows`` larger
    than the total auto rows, the whole auto frame is returned.
    """
    rng = np.random.default_rng(seed)
    if auto_df.empty:
        return auto_df.iloc[0:0].copy(), OrderedDict()

    months = auto_df[TIMESTAMP_COLUMN].dt.strftime("%Y-%m")
    group_index: dict[str, np.ndarray] = {}
    for ym, idx in months.groupby(months).groups.items():
        group_index[str(ym)] = np.asarray(idx, dtype=np.int64)
    distinct_months = sorted(group_index.keys())
    n_months = len(distinct_months)
    if n_months == 0:
        return auto_df.iloc[0:0].copy(), OrderedDict()

    base_quota = max(per_month_floor, target_rows // n_months)

    # Pass 1: take base_quota (or less) from each month.
    take_per_month: dict[str, int] = {}
    leftover_capacity: dict[str, int] = {}
    for ym in distinct_months:
        avail = int(group_index[ym].size)
        take = min(avail, base_quota)
        take_per_month[ym] = take
        leftover_capacity[ym] = max(0, avail - take)

    # Pass 2: redistribute any shortfall (target_rows - sum) to months with
    # remaining capacity, in round-robin so no single month dominates.
    chosen_now = sum(take_per_month.values())
    shortfall = max(0, target_rows - chosen_now)
    # Round-robin until shortfall absorbed or capacity exhausted.
    while shortfall > 0 and any(v > 0 for v in leftover_capacity.values()):
        progressed = False
        for ym in distinct_months:
            if shortfall == 0:
                break
            if leftover_capacity[ym] <= 0:
                continue
            take_per_month[ym] += 1
            leftover_capacity[ym] -= 1
            shortfall -= 1
            progressed = True
        if not progressed:
            break

    # Pass 3: random sample WITHOUT replacement from each month's index.
    chosen_indices: list[np.ndarray] = []
    per_month_rows: "OrderedDict[str, int]" = OrderedDict()
    for ym in distinct_months:
        idxs = group_index[ym]
        n_take = take_per_month[ym]
        per_month_rows[ym] = int(n_take)
        if n_take == 0:
            continue
        if n_take >= idxs.size:
            chosen_indices.append(idxs)
        else:
            picked = rng.choice(idxs, size=n_take, replace=False)
            chosen_indices.append(np.sort(picked))

    if not chosen_indices:
        return auto_df.iloc[0:0].copy(), per_month_rows

    take_idx = np.concatenate(chosen_indices)
    sampled = auto_df.iloc[take_idx].sort_values(
        TIMESTAMP_COLUMN, kind="stable"
    ).reset_index(drop=True)
    return sampled, per_month_rows


def build_stratified_2025_auto_fit(
    *,
    csv_path: Path,
    target_rows: int = DEFAULT_FIT_ROWS,
    per_month_floor: int = DEFAULT_PER_MONTH_FLOOR,
    seed: int = 0,
    min_distinct_months: int = DEFAULT_MIN_DISTINCT_MONTHS,
    full: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build a broad, full-year-stratified 2025 auto-mode fit frame.

    Parameters
    ----------
    csv_path
        Path to ``source1_2025.csv`` (or a tiny fixture with the same schema).
    target_rows
        Soft upper bound on the returned row count (we never pad with
        replacement). With ``full=True`` we ignore this and use every auto row.
    per_month_floor
        Each non-empty AUTO month gets AT LEAST ``min(month_size,
        per_month_floor)`` rows so small months are not crowded out by the
        quota math.
    min_distinct_months
        The fit frame MUST span at least this many distinct 2025 months. If
        the resulting set spans fewer, we raise -- the whole point of the
        sprint is to remove the single-month confound. The downstream Hermes
        verifier reads ``train_meta.per_month_rows`` and HARD-STOPS the
        merge if fewer than 5 distinct months are present.
    full
        If True, return ALL auto rows (no cap) but still record the
        per-month breakdown.

    Returns
    -------
    (fit_df, train_meta)
        ``fit_df`` has CANONICAL axis column names (backing -> canonical
        rename applied) and a stringified ``timestamp`` column suitable for
        the Sprint-27 leakage-key check. ``train_meta`` contains the
        per-month breakdown, distinct-month count, and audit fields.
    """
    auto_df = _read_2025_auto_frame(csv_path)
    n_auto_total = int(len(auto_df))
    if n_auto_total == 0:
        raise RuntimeError(
            f"2025 CSV {csv_path} yielded 0 AUTO-mode rows after filtering"
        )

    if full or target_rows >= n_auto_total:
        sampled = auto_df.copy()
        # per-month tally over the whole auto frame
        per_month_rows: "OrderedDict[str, int]" = OrderedDict(
            sorted(
                {
                    str(ym): int(c)
                    for ym, c in auto_df[TIMESTAMP_COLUMN].dt.strftime("%Y-%m").value_counts().items()
                }.items()
            )
        )
    else:
        sampled, per_month_rows = _stratified_per_month_sample(
            auto_df,
            target_rows=target_rows,
            per_month_floor=per_month_floor,
            seed=seed,
        )

    # Rename backing -> canonical axis names.
    sampled = s30.rename_backing_to_canonical(sampled)

    # Stringify timestamps for the Sprint-27 leakage-key check (prefix match).
    sampled[TIMESTAMP_COLUMN] = sampled[TIMESTAMP_COLUMN].dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Drop the mode columns -- the detector / baseline only score the axes.
    drop_cols = [c for c in (MODE_AUTO_COLUMN, MODE_MANUAL_COLUMN) if c in sampled.columns]
    if drop_cols:
        sampled = sampled.drop(columns=drop_cols)

    distinct_months = int(sum(1 for v in per_month_rows.values() if v > 0))
    if distinct_months < int(min_distinct_months):
        raise RuntimeError(
            "Sprint 30b fit set spans fewer than "
            f"{int(min_distinct_months)} distinct 2025 months "
            f"(actual={distinct_months}, per_month_rows={dict(per_month_rows)}). "
            "Refusing to fit: the whole point of this sprint is to remove the "
            "single-month seasonal confound."
        )

    ts_min = str(sampled[TIMESTAMP_COLUMN].min()) if len(sampled) else None
    ts_max = str(sampled[TIMESTAMP_COLUMN].max()) if len(sampled) else None

    train_meta: dict[str, Any] = {
        "csv_path": str(csv_path),
        "fit_strategy": "full_year_stratified_auto_mode_2025",
        "target_rows": int(target_rows),
        "per_month_floor": int(per_month_floor),
        "min_distinct_months_required": int(min_distinct_months),
        "full_mode": bool(full),
        "n_auto_rows_total_in_csv": int(n_auto_total),
        "n_rows_after_auto_filter": int(len(sampled)),
        "distinct_months": distinct_months,
        "per_month_rows": {k: int(v) for k, v in per_month_rows.items() if v > 0},
        "timestamp_min": ts_min,
        "timestamp_max": ts_max,
        "seed": int(seed),
    }
    return sampled, train_meta


# --------------------------------------------------------------------------- #
# Active-axis selection (mirrors Sprint 30)
# --------------------------------------------------------------------------- #
def active_continuous_axes(df: pd.DataFrame) -> list[str]:
    return [a for a in active_axes_ordered() if a != MASKED_AXIS and a in df.columns]


# --------------------------------------------------------------------------- #
# Unsupervised raw-March flag rates -- same shape as Sprint 30 for cross-check
# --------------------------------------------------------------------------- #
def _unsupervised_flag_rates(
    detector, baseline_suite, march_df: pd.DataFrame
) -> dict[str, float | int]:
    det_scored = detector.score(march_df)
    base_scored = baseline_suite.score(march_df)
    det_flag = det_scored["detector_flag"].to_numpy(dtype=int)
    base_flag = base_scored["anomaly_flag"].to_numpy(dtype=int)
    return {
        "n_rows": int(len(march_df)),
        "detector_flag_rate": float(det_flag.mean()) if det_flag.size else 0.0,
        "baseline_flag_rate": float(base_flag.mean()) if base_flag.size else 0.0,
        "detector_score_mean": float(
            det_scored["detector_anomaly_score"].to_numpy().mean()
        )
        if len(det_scored)
        else 0.0,
        "baseline_combined_deviation_mean": float(
            base_scored["combined_deviation"].to_numpy().mean()
        )
        if len(base_scored)
        else 0.0,
    }


# --------------------------------------------------------------------------- #
# Core builder (mirrors Sprint 30 with sprint label = "30b")
# --------------------------------------------------------------------------- #
def build_sprint30b_scorecard(
    *,
    train_df: pd.DataFrame,
    march_df: pd.DataFrame,
    axes: list[str],
    detector_seed: int = DEFAULT_SEED,
    fault_seed: int = DEFAULT_FAULT_SEED,
    epochs: int = DEFAULT_EPOCHS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    n_episodes_per_kind: int = 8,
    drift_window: int = 120,
    stuck_window: int = 80,
    envelope_window: int = 60,
    norm_stats_path: Path | None = None,
    run_governance: bool = True,
    split_path: Path | None = None,
    modeling_roots: list[Path] | None = None,
    march_window_meta: dict[str, Any] | None = None,
    train_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the Sprint-30b protocol and return a scorecard dict.

    Same shape and same FROZEN gate as Sprint 30; only the fit frame is
    broader. The Sprint-27 leakage guards inside ``fit_health_detector`` /
    ``fit_health_baseline_suite`` raise on any 2026-03 key BEFORE fit.
    """
    if not axes:
        raise RuntimeError("no active axes selected")
    if march_df.empty:
        raise RuntimeError("March-2026 holdout frame is empty")
    if train_df.empty:
        raise RuntimeError("2025 training frame is empty")

    if march_window_meta is None:
        ts = pd.to_datetime(march_df["timestamp"]) if "timestamp" in march_df.columns else None
        if ts is not None and len(ts):
            all_march = bool(
                (ts.dt.year == 2026).all() and (ts.dt.month == 3).all()
            )
            march_window_meta = {
                "all_in_2026_03": all_march,
                "first_timestamp": str(ts.min()),
                "last_timestamp": str(ts.max()),
                "n_rows": int(len(march_df)),
                "source": "in-memory frame (no csv_path)",
            }
        else:
            march_window_meta = {
                "all_in_2026_03": False,
                "n_rows": int(len(march_df)),
                "source": "in-memory frame (no timestamp column)",
            }

    # --- 1) Fit detector + baseline on the STRATIFIED 2025 auto-mode normal frame.
    detector = fit_health_detector(
        train_df,
        axes=axes,
        seed=detector_seed,
        epochs=epochs,
        batch_size=batch_size,
        norm_stats_path=norm_stats_path,
    )
    baseline_suite = fit_health_baseline_suite(train_df, axes=axes)

    # --- 2) Build the frozen-seed injected-fault set on LOCKED March-2026 normal.
    injected = inject_faults(
        march_df.reset_index(drop=True),
        seed=fault_seed,
        n_episodes_per_kind=n_episodes_per_kind,
        drift_window=drift_window,
        stuck_window=stuck_window,
        envelope_window=envelope_window,
    )

    # --- 3) Evaluate detector vs baseline.
    eval_dict = evaluate_detector_vs_baseline(
        detector=detector, baseline_suite=baseline_suite, injected=injected
    )

    # --- 4) Apply the FROZEN pre-registered v2 gate (imported as-is).
    gate = health_acceptance_gate_v2(eval_dict)

    # --- 5) Governance (force-FAIL on violation).
    governance_block: dict[str, Any] | None = None
    governance_status = "SKIPPED"
    if run_governance:
        try:
            governance_block = build_governance_block(
                split_manifest=split_path,
                modeling_roots=modeling_roots
                or [_REPO_ROOT / p for p in DEFAULT_MODELING_ROOTS],
                normalization_stats=norm_stats_path,
            )
            gate = apply_governance_to_verdict(gate, governance_block)
            governance_status = governance_block.get("governance_status", "UNKNOWN")
        except Exception as exc:  # pragma: no cover - defensive
            governance_block = {"governance_status": "ERROR", "error": str(exc)}
            governance_status = "ERROR"

    # --- 6) Unsupervised raw-March flag rates (no labels needed).
    raw_rates = _unsupervised_flag_rates(detector, baseline_suite, march_df)

    # --- 7) Assemble the scorecard.
    scorecard: dict[str, Any] = {
        "sprint": "30b",
        "pillar": "A_health",
        "benchmark": (
            "LOCKED March 2026 holdout (out-of-sample), broad full-year 2025 fit"
        ),
        "advisory_only": True,
        "out_of_sample_protocol": {
            "detector_baseline_fit_on": (
                "full-year-stratified 2025 auto-mode normal data (multi-month)"
            ),
            "labeled_eval_set": (
                "synthetic frozen-seed faults injected on REAL March-2026 normal frames "
                "(faults synthetic, underlying normal is the genuinely unseen distribution)"
            ),
            "labeled_eval_limitation": (
                "the injected faults are SYNTHETIC -- AUROC / lead-time / false-alarm "
                "measure how the 2025-fit detector responds to canonical faults on top "
                "of unseen March normal data, NOT how it would score real March faults "
                "(March 2026 has no ground-truth labels)."
            ),
            "unsupervised_eval_set": (
                "raw un-faulted March-2026 normal frames -- detector / baseline "
                "alarm rate on truly unseen data, no labels needed."
            ),
            "leakage_isolation": (
                "fit_health_detector + fit_health_baseline_suite both call the "
                "Sprint-27 assert_holdout_isolated guard on input keys; any "
                "March-2026 key in the fit input raises LeakageError BEFORE fit."
            ),
            "seasonal_confound_fix": (
                "Sprint 30 fit collapsed onto late-March 2025 (head-of-CSV cap landed "
                "in the first auto block). Sprint 30b stratified-samples across ALL "
                "2025 auto-mode months so the fit set spans >= "
                f"{DEFAULT_MIN_DISTINCT_MONTHS} distinct months."
            ),
        },
        "holdout_window": march_window_meta or {},
        "train_meta": train_meta or {},
        "axes_used": list(axes),
        "detector": detector.to_summary_dict(),
        "baseline": baseline_suite.to_summary_dict(),
        "injected_faults": injected.to_summary_dict(),
        "evaluation": eval_dict,
        "acceptance_gate": gate,
        "raw_march_flag_rates": raw_rates,
        "frozen_gate_v2": {
            "rule_text": GATE_V2_RULE_TEXT,
            "auroc_noninferiority_tol": GATE_V2_AUROC_NONINFERIORITY_TOL,
            "far_improvement_factor": GATE_V2_FAR_IMPROVEMENT_FACTOR,
            "min_detector_auroc": GATE_V2_MIN_DETECTOR_AUROC,
            "lead_time_tol": GATE_V2_LEAD_TIME_TOL,
            "preregistered_before_evaluation": True,
            "tuned_to_outcome": False,
            "imported_from": "aquaoptima.advisory.health_gate.health_acceptance_gate_v2",
        },
        "safety": {
            "evaluation_mode": "offline_only",
            "write_path": "none",
            "influences_control": False,
            "site_integration_allowed": False,
            "scorecard_role": "advisory_evidence_only",
            "governance_status": governance_status,
            "governance": governance_block,
        },
        "verdict": gate.get("verdict", "FAIL"),
        "gate_version": "v2",
    }
    return scorecard


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _resolve_march_nrows(args: argparse.Namespace) -> int | None:
    if os.environ.get(SPRINT30B_FULL_ENV, "").strip() == "1":
        return None
    if args.march_nrows is not None:
        return int(args.march_nrows)
    env = os.environ.get(SPRINT30B_MARCH_NROWS_ENV)
    if env:
        return int(env)
    return DEFAULT_MARCH_NROWS


def _resolve_fit_rows(args: argparse.Namespace) -> tuple[int, bool]:
    """Return (target_rows, full_mode)."""
    if os.environ.get(SPRINT30B_FULL_ENV, "").strip() == "1":
        return DEFAULT_FIT_ROWS, True
    if args.fit_rows is not None:
        return int(args.fit_rows), False
    env = os.environ.get(SPRINT30B_FIT_ROWS_ENV)
    if env:
        return int(env), False
    return DEFAULT_FIT_ROWS, False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "AOPSO Sprint 30b -- Pillar A locked-March-2026 holdout eval with a "
            "broad, full-year-stratified 2025 auto-mode fit (removes the Sprint-30 "
            "single-month seasonal confound). Pre-registered v2 gate imported as-is."
        )
    )
    p.add_argument("--csv-2025", type=Path, default=DEFAULT_CSV_2025)
    p.add_argument("--csv-2026", type=Path, default=DEFAULT_CSV_2026)
    p.add_argument(
        "--fit-rows",
        type=int,
        default=None,
        help=(
            f"Soft target for the stratified 2025 fit-frame size. "
            f"Overrides ${SPRINT30B_FIT_ROWS_ENV}. ${SPRINT30B_FULL_ENV}=1 uses "
            f"every AUTO row instead. Default {DEFAULT_FIT_ROWS}."
        ),
    )
    p.add_argument("--per-month-floor", type=int, default=DEFAULT_PER_MONTH_FLOOR)
    p.add_argument(
        "--min-distinct-months", type=int, default=DEFAULT_MIN_DISTINCT_MONTHS
    )
    p.add_argument(
        "--march-nrows",
        type=int,
        default=None,
        help=(
            "Row cap APPLIED TO MARCH-2026 ROWS after the calendar-month filter. "
            f"Overrides ${SPRINT30B_MARCH_NROWS_ENV}. ${SPRINT30B_FULL_ENV}=1 uses every March row."
        ),
    )
    p.add_argument("--detector-seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--fault-seed", type=int, default=DEFAULT_FAULT_SEED)
    p.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--episodes-per-kind", type=int, default=8)
    p.add_argument("--drift-window", type=int, default=120)
    p.add_argument("--stuck-window", type=int, default=80)
    p.add_argument("--envelope-window", type=int, default=60)
    p.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    p.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.csv_2025.exists():
        print(f"[sprint30b] 2025 CSV not found: {args.csv_2025}", file=sys.stderr)
        return EXIT_NO_DATA
    if not args.csv_2026.exists():
        print(f"[sprint30b] 2026 CSV not found: {args.csv_2026}", file=sys.stderr)
        return EXIT_NO_DATA

    fit_rows, full_mode = _resolve_fit_rows(args)
    march_row_cap = _resolve_march_nrows(args)
    try:
        train_df, train_meta = build_stratified_2025_auto_fit(
            csv_path=args.csv_2025,
            target_rows=fit_rows,
            per_month_floor=args.per_month_floor,
            seed=args.detector_seed,
            min_distinct_months=args.min_distinct_months,
            full=full_mode,
        )
        march_df, march_meta = s30.load_march_canonical(args.csv_2026, march_row_cap)

        axes = active_continuous_axes(train_df)
        axes = [a for a in axes if a in march_df.columns]
        train_meta["axes_used"] = axes

        scorecard = build_sprint30b_scorecard(
            train_df=train_df,
            march_df=march_df,
            axes=axes,
            detector_seed=args.detector_seed,
            fault_seed=args.fault_seed,
            epochs=args.epochs,
            batch_size=args.batch_size,
            n_episodes_per_kind=args.episodes_per_kind,
            drift_window=args.drift_window,
            stuck_window=args.stuck_window,
            envelope_window=args.envelope_window,
            norm_stats_path=args.stats if args.stats.exists() else None,
            run_governance=True,
            split_path=args.split,
            modeling_roots=[_REPO_ROOT / p for p in DEFAULT_MODELING_ROOTS],
            march_window_meta=march_meta,
            train_meta=train_meta,
        )
    except LeakageError as exc:
        print(f"[sprint30b] LEAKAGE: {exc}", file=sys.stderr)
        return EXIT_LEAKAGE
    except FileNotFoundError as exc:
        print(f"[sprint30b] missing data: {exc}", file=sys.stderr)
        return EXIT_NO_DATA
    except RuntimeError as exc:
        print(f"[sprint30b] runtime: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        json.dump(scorecard, f, indent=2, sort_keys=True, default=str)

    ev = scorecard["evaluation"]
    raw = scorecard["raw_march_flag_rates"]
    tm = scorecard["train_meta"]
    print(f"[sprint30b] wrote {args.out}")
    print(
        f"[sprint30b] fit_rows={tm.get('n_rows_after_auto_filter')} "
        f"distinct_months={tm.get('distinct_months')} "
        f"per_month_rows={tm.get('per_month_rows')}"
    )
    print(
        f"[sprint30b] detector_auroc={ev['detector']['auroc']:.4f} "
        f"baseline_auroc={ev['baseline']['auroc']:.4f}  "
        f"detector_FAR(injected)={ev['detector']['false_alarm_rate']:.4f} "
        f"baseline_FAR(injected)={ev['baseline']['false_alarm_rate']:.4f}"
    )
    print(
        f"[sprint30b] raw-March alarm-rate: detector={raw['detector_flag_rate']:.4f} "
        f"baseline={raw['baseline_flag_rate']:.4f}"
    )
    print(
        f"[sprint30b] gate_v2 verdict={scorecard['verdict']} "
        f"governance_status={scorecard['safety']['governance_status']}"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
