#!/usr/bin/env python3
"""AOPSO Sprint 30 -- Pillar A locked-March-2026 OUT-OF-SAMPLE evaluation.

This is the real out-of-sample confirmation. The detector + interpretable baseline
are fit on 2025 auto-mode normal data ONLY (the Sprint-27 leakage guard fires
hard if any March-2026 key sneaks into the fit input), and then scored against:

  1. A frozen-seed injected-fault evaluation set BUILT ON THE LOCKED MARCH-2026
     NORMAL FRAMES. The faults are synthetic but the underlying normal operating
     data is the real, unseen March distribution -- so this stresses whether the
     2025-fit detector generalises to genuinely out-of-sample normal behaviour.
     This is the labelled metric (AUROC, lead-time, false-alarm).

  2. The detector's and baseline's alarm/flag rate on the RAW (un-faulted) March
     normal data -- the most honest unsupervised number on truly unseen data
     (no labels needed). This is reported as ``raw_march_flag_rates``.

The acceptance gate is the FROZEN pre-registered v2 from Sprint 29b
(:func:`aquaoptima.advisory.health_gate.health_acceptance_gate_v2`); it is
imported and applied as-is. A FAIL on the locked holdout is an ACCEPTABLE,
VALUABLE outcome -- the script reports the real verdict and exits 0 (it exits
non-zero ONLY on a true error: leakage, missing data, runtime fault).

Hard safety boundary
--------------------
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Repo-root sys.path so this CLI runs without an editable install.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

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
from aquaoptima.training.evaluation import _load_march_frame  # noqa: E402


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
DEFAULT_CSV_2025 = Path(
    "/home/hunter_lin/projects/yilan-site-model-testing/yearlong_drive/source1_2025.csv"
)
DEFAULT_CSV_2026 = Path(
    "/home/hunter_lin/projects/yilan-site-model-testing/yearlong_drive/source1_2026.csv"
)
DEFAULT_OUT_PATH = (
    _REPO_ROOT / "data" / "eval" / "pillarA" / "sprint30_holdout_scorecard.json"
)
DEFAULT_SPLIT = _REPO_ROOT / "data" / "splits" / "yilan_2025_split_v1.json"
DEFAULT_STATS = _REPO_ROOT / "data" / "normalization" / "yilan_2025_train_stats.json"

# Modest defaults so the script runs in reasonable time on CPU. The full
# locked-holdout run is gated behind SPRINT30_FULL=1.
DEFAULT_SUBSET_2025 = 30_000
DEFAULT_MARCH_NROWS = 50_000          # ~all of March at 60s cadence
SPRINT30_MARCH_NROWS_ENV = "SPRINT30_MARCH_NROWS"
SPRINT30_FULL_ENV = "SPRINT30_FULL"

EXIT_OK = 0
EXIT_LEAKAGE = 2
EXIT_NO_DATA = 3
EXIT_RUNTIME = 4


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #
def _backing_to_canonical() -> dict[str, str]:
    """``backing_column -> canonical_axis`` for every axis with a real backing column."""
    return {
        col: axis
        for axis, col in CANONICAL_AXIS_TO_COLUMN.items()
        if col is not None
    }


def rename_backing_to_canonical(df: pd.DataFrame) -> pd.DataFrame:
    """Rename Yilan backing columns to canonical axis names.

    The detector / baseline / injected-fault harness all score frames whose
    columns are canonical axis names (``edge_flow``, ``node_pressure``, ...).
    The March holdout loader returns BACKING column names (``system_flow_rate``,
    ``system_pressure``, ...), so this is the bridge.

    The masked axis (``edge_valve_position``) has no backing column at Yilan and
    is intentionally absent. The ``timestamp`` column is preserved.
    """
    mapping = _backing_to_canonical()
    rename = {col: axis for col, axis in mapping.items() if col in df.columns}
    return df.rename(columns=rename)


def load_2025_auto_train(csv_path: Path, subset: int | None) -> pd.DataFrame:
    """Read the 2025 CSV, keep auto-mode rows, rename to canonical axes."""
    backing = {
        axis: col for axis, col in CANONICAL_AXIS_TO_COLUMN.items() if col is not None
    }
    needed_cols = [
        TIMESTAMP_COLUMN, MODE_AUTO_COLUMN, MODE_MANUAL_COLUMN, *backing.values()
    ]
    header = pd.read_csv(csv_path, nrows=0)
    present = [c for c in needed_cols if c in header.columns]
    df = pd.read_csv(csv_path, usecols=present, low_memory=False)
    df[TIMESTAMP_COLUMN] = pd.to_datetime(
        df[TIMESTAMP_COLUMN], format=TIMESTAMP_FORMAT, errors="coerce"
    )
    df = df.dropna(subset=[TIMESTAMP_COLUMN]).sort_values(
        TIMESTAMP_COLUMN, kind="stable"
    )
    if df[TIMESTAMP_COLUMN].dt.year.eq(2026).any():
        raise LeakageError(
            "2025 training CSV unexpectedly contains 2026 timestamps -- aborting fit"
        )

    def _truthy(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip().str.lower().isin({"true", "1", "1.0"})

    if MODE_AUTO_COLUMN in df.columns:
        df = df[_truthy(df[MODE_AUTO_COLUMN])].copy()
    inv = {col: axis for axis, col in backing.items() if col in df.columns}
    df = df.rename(columns=inv)
    if subset is not None and len(df) > subset:
        df = df.iloc[:subset]
    axis_cols = [a for a in backing.keys() if a in df.columns]
    df = df.dropna(subset=axis_cols)
    # Stringify timestamps for the Sprint-27 leakage-key check (key prefix match).
    df[TIMESTAMP_COLUMN] = df[TIMESTAMP_COLUMN].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df.reset_index(drop=True)


def load_march_canonical(
    csv_path: Path, march_row_cap: int | None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the LOCKED March-2026 holdout, rename to canonical axes, and prove isolation.

    Reads the full 2026 CSV (only the needed columns), filters to calendar
    month March, then optionally caps to ``march_row_cap`` rows (kept from the
    BEGINNING of March so the subset is contiguous and time-ordered). Returns
    ``(df, window_meta)`` where ``window_meta`` confirms every timestamp falls
    inside ``2026-03``. The frame's ``timestamp`` column is kept as a pandas
    datetime; downstream callers stringify if they need leakage keys.
    """
    raw = _load_march_frame(csv_path, nrows=None)
    if raw.empty:
        raise RuntimeError(
            f"March-2026 holdout produced 0 rows from {csv_path} (filter month==3)"
        )
    df = rename_backing_to_canonical(raw)
    # Drop rows where ANY of the required canonical axes are NaN, to mirror
    # the detector / baseline preconditions (they expect finite values).
    axis_cols = [
        a for a in CANONICAL_AXIS_TO_COLUMN
        if CANONICAL_AXIS_TO_COLUMN[a] is not None and a in df.columns
    ]
    df = df.dropna(subset=axis_cols).reset_index(drop=True)
    n_march_total = int(len(df))
    capped = False
    if march_row_cap is not None and n_march_total > march_row_cap:
        df = df.iloc[: int(march_row_cap)].reset_index(drop=True)
        capped = True
    ts = pd.to_datetime(df[TIMESTAMP_COLUMN])
    all_march = bool((ts.dt.year == 2026).all() and (ts.dt.month == 3).all())
    window_meta = {
        "all_in_2026_03": all_march,
        "first_timestamp": str(ts.min()),
        "last_timestamp": str(ts.max()),
        "n_rows": int(len(df)),
        "n_march_rows_total_before_cap": n_march_total,
        "row_cap_applied": capped,
        "row_cap": int(march_row_cap) if march_row_cap is not None else None,
        "csv_path": str(csv_path),
        "month_filter": "2026-03 (calendar month March)",
    }
    if not all_march:
        # Hard refusal: if any timestamp falls outside March-2026, the holdout
        # is contaminated and we DO NOT proceed.
        raise RuntimeError(
            "STOP: March-2026 holdout contains non-March-2026 timestamps "
            f"({ts.min()}..{ts.max()}); refusing to evaluate"
        )
    return df, window_meta


# --------------------------------------------------------------------------- #
# Active-axis selection
# --------------------------------------------------------------------------- #
def active_continuous_axes(df: pd.DataFrame) -> list[str]:
    """Active axes (masked axis dropped) that are actually present in ``df``."""
    return [a for a in active_axes_ordered() if a != MASKED_AXIS and a in df.columns]


# --------------------------------------------------------------------------- #
# Unsupervised raw-March flag rates
# --------------------------------------------------------------------------- #
def _unsupervised_flag_rates(
    detector, baseline_suite, march_df: pd.DataFrame
) -> dict[str, float | int]:
    """Detector + baseline alarm rates on the RAW (un-faulted) March normal data.

    No labels needed; this is the most honest single number on truly unseen
    data. Returned values are in ``[0, 1]``. A high rate on raw March = the
    detector cries wolf on real-world normal operation; a low rate is the
    baseline non-disagreement bound for alarm fatigue.
    """
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
# Core builder
# --------------------------------------------------------------------------- #
def build_sprint30_scorecard(
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
    """Run the full Sprint-30 holdout protocol and return a scorecard dict.

    Parameters
    ----------
    train_df
        2025 auto-mode normal frame with canonical axis columns. Must contain a
        ``timestamp`` column whose keys do NOT fall in March-2026 (the Sprint-27
        leakage guard fires inside :func:`fit_health_detector`).
    march_df
        LOCKED March-2026 holdout with canonical axis columns. Used ONLY as
        scoring input -- never fit on.
    axes
        Active axis list to fit / score (the masked axis is excluded by caller).
    run_governance
        If True, compose the Sprint-27 governance block over the modeling
        source + split + norm stats and apply it to the v2 verdict.
    """
    if not axes:
        raise RuntimeError("no active axes selected")
    if march_df.empty:
        raise RuntimeError("March-2026 holdout frame is empty")
    if train_df.empty:
        raise RuntimeError("2025 training frame is empty")

    # Compute holdout-window meta from march_df if not already supplied, so the
    # scorecard's holdout_window.all_in_2026_03 proof is always present.
    if march_window_meta is None:
        ts = pd.to_datetime(march_df["timestamp"]) if "timestamp" in march_df.columns else None
        if ts is not None and len(ts):
            all_march = bool((ts.dt.year == 2026).all() and (ts.dt.month == 3).all())
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

    # --- 1) Fit detector + baseline on 2025 auto-mode normal ONLY.
    # The leakage guard inside fit_health_detector / fit_health_baseline_suite
    # raises LeakageError on any 2026-03 key.
    detector = fit_health_detector(
        train_df,
        axes=axes,
        seed=detector_seed,
        epochs=epochs,
        batch_size=batch_size,
        norm_stats_path=norm_stats_path,
    )
    baseline_suite = fit_health_baseline_suite(train_df, axes=axes)

    # --- 2) Build the injected-fault set on the March-2026 NORMAL frame.
    # inject_faults does NOT call the leakage guard itself (it would defeat
    # itself on the faulted values it just wrote) -- but we already proved
    # `march_df` is real March-2026 in `load_march_canonical` above.
    injected = inject_faults(
        march_df.reset_index(drop=True),
        seed=fault_seed,
        n_episodes_per_kind=n_episodes_per_kind,
        drift_window=drift_window,
        stuck_window=stuck_window,
        envelope_window=envelope_window,
    )

    # --- 3) Evaluate detector vs baseline on the injected-on-March set.
    eval_dict = evaluate_detector_vs_baseline(
        detector=detector, baseline_suite=baseline_suite, injected=injected
    )

    # --- 4) Apply the FROZEN pre-registered v2 acceptance gate.
    # Imported as-is from main; we do NOT redefine or retune it here.
    gate = health_acceptance_gate_v2(eval_dict)

    # --- 5) Compose governance (Sprint-27) and force-FAIL on violation.
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
        "sprint": 30,
        "pillar": "A_health",
        "benchmark": "LOCKED March 2026 holdout (out-of-sample)",
        "advisory_only": True,
        "out_of_sample_protocol": {
            "detector_baseline_fit_on": "2025 auto-mode normal data ONLY",
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
    """Resolve the March-2026 row cap. Env > CLI > default. SPRINT30_FULL=1 = no cap."""
    if os.environ.get(SPRINT30_FULL_ENV, "").strip() == "1":
        return None
    if args.march_nrows is not None:
        return int(args.march_nrows)
    env = os.environ.get(SPRINT30_MARCH_NROWS_ENV)
    if env:
        return int(env)
    return DEFAULT_MARCH_NROWS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "AOPSO Sprint 30 -- Pillar A locked-March-2026 out-of-sample evaluation. "
            "Fit on 2025, score on March-2026; apply pre-registered v2 gate."
        )
    )
    p.add_argument("--csv-2025", type=Path, default=DEFAULT_CSV_2025)
    p.add_argument("--csv-2026", type=Path, default=DEFAULT_CSV_2026)
    p.add_argument("--subset-2025", type=int, default=DEFAULT_SUBSET_2025)
    p.add_argument(
        "--march-nrows",
        type=int,
        default=None,
        help=(
            "Row cap APPLIED TO MARCH-2026 ROWS after the calendar-month filter. "
            f"Overrides ${SPRINT30_MARCH_NROWS_ENV}. Pass ${SPRINT30_FULL_ENV}=1 in "
            "the environment to keep every March row (no cap)."
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
        print(f"[sprint30] 2025 CSV not found: {args.csv_2025}", file=sys.stderr)
        return EXIT_NO_DATA
    if not args.csv_2026.exists():
        print(f"[sprint30] 2026 CSV not found: {args.csv_2026}", file=sys.stderr)
        return EXIT_NO_DATA

    march_row_cap = _resolve_march_nrows(args)
    try:
        train_df = load_2025_auto_train(args.csv_2025, args.subset_2025)
        march_df, march_meta = load_march_canonical(args.csv_2026, march_row_cap)
        axes = active_continuous_axes(train_df)
        # March may be missing the same axis if its backing column is missing -- intersect.
        axes = [a for a in axes if a in march_df.columns]
        train_meta = {
            "csv_path": str(args.csv_2025),
            "subset_cap": int(args.subset_2025) if args.subset_2025 else None,
            "n_rows_after_auto_filter": int(len(train_df)),
            "timestamp_min": str(train_df["timestamp"].min()) if len(train_df) else None,
            "timestamp_max": str(train_df["timestamp"].max()) if len(train_df) else None,
            "axes_used": axes,
        }
        scorecard = build_sprint30_scorecard(
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
        print(f"[sprint30] LEAKAGE: {exc}", file=sys.stderr)
        return EXIT_LEAKAGE
    except FileNotFoundError as exc:
        print(f"[sprint30] missing data: {exc}", file=sys.stderr)
        return EXIT_NO_DATA
    except RuntimeError as exc:
        print(f"[sprint30] runtime: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        json.dump(scorecard, f, indent=2, sort_keys=True, default=str)

    ev = scorecard["evaluation"]
    raw = scorecard["raw_march_flag_rates"]
    print(f"[sprint30] wrote {args.out}")
    print(
        f"[sprint30] detector_auroc={ev['detector']['auroc']:.4f} "
        f"baseline_auroc={ev['baseline']['auroc']:.4f}  "
        f"detector_FAR(injected)={ev['detector']['false_alarm_rate']:.4f} "
        f"baseline_FAR(injected)={ev['baseline']['false_alarm_rate']:.4f}"
    )
    print(
        f"[sprint30] raw-March alarm-rate: detector={raw['detector_flag_rate']:.4f} "
        f"baseline={raw['baseline_flag_rate']:.4f}"
    )
    print(
        f"[sprint30] gate_v2 verdict={scorecard['verdict']} "
        f"governance_status={scorecard['safety']['governance_status']}"
    )
    # Model-gate FAIL is a valid outcome -- exit 0. Non-zero only on ERROR.
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
