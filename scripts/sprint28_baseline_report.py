#!/usr/bin/env python3
"""Sprint 28 Pillar-A baseline report.

Fits the EWMA/SPC + Mahalanobis + physical-residual baselines on a 2025
auto-mode subset and writes a JSON report to
``data/eval/pillarA/sprint28_baseline_report.json``.

Reads ONLY 2025 data; the Sprint-27 leakage guard runs before any fit and the
script exits non-zero if a March-2026 key is present in the input.

Example::

    python scripts/sprint28_baseline_report.py --subset 50000
    python scripts/sprint28_baseline_report.py --csv path/to/source1_2025.csv

Hard boundary: offline, advisory-only, no edge / OT / write-capable connectors,
no setpoint output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure the local src/ shadows any globally installed copy of aquaoptima.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aquaoptima.advisory.health_baselines import (  # noqa: E402
    DEFAULT_EWMA_LAMBDA,
    DEFAULT_HEALTH_THRESHOLD,
    DEFAULT_MAHA_CALIB_QUANTILE,
    LeakageError,
    fit_health_baseline_suite,
)
from aquaoptima.advisory.label_schema import (  # noqa: E402
    MASKED_AXIS,
    active_axes_ordered,
)
from aquaoptima.dataio.yilan_axis_map import (  # noqa: E402
    CANONICAL_AXIS_TO_COLUMN,
    MODE_AUTO_COLUMN,
    MODE_MANUAL_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_FORMAT,
)

DEFAULT_OUT_PATH = _REPO_ROOT / "data" / "eval" / "pillarA" / "sprint28_baseline_report.json"
DEFAULT_CSV = Path("/home/hunter_lin/projects/yilan-site-model-testing/yearlong_drive/source1_2025.csv")
EXIT_LEAKAGE = 2
EXIT_NO_DATA = 3


def load_auto_mode_frame(csv_path: Path, subset: int | None) -> pd.DataFrame:
    """Read the canonical-axis columns from the 2025 CSV; return auto-mode rows.

    ``subset`` caps the AUTO-MODE rows kept (not raw rows read), so a small
    subset still produces a usable fitting window even when the CSV begins
    with a manual-mode prefix. After auto-filtering, axes with NaN in any
    selected row are dropped row-wise to keep the linear-algebra clean.
    """
    backing = {
        axis: col for axis, col in CANONICAL_AXIS_TO_COLUMN.items() if col is not None
    }
    needed_cols = [TIMESTAMP_COLUMN, MODE_AUTO_COLUMN, MODE_MANUAL_COLUMN, *backing.values()]
    header = pd.read_csv(csv_path, nrows=0)
    present = [c for c in needed_cols if c in header.columns]
    df = pd.read_csv(csv_path, usecols=present, low_memory=False)
    df[TIMESTAMP_COLUMN] = pd.to_datetime(
        df[TIMESTAMP_COLUMN], format=TIMESTAMP_FORMAT, errors="coerce"
    )
    df = df.dropna(subset=[TIMESTAMP_COLUMN]).sort_values(TIMESTAMP_COLUMN, kind="stable")
    # Restrict to auto-mode rows. We don't trust manual or "other" rows for a
    # normal-operation baseline.
    def _truthy(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip().str.lower().isin({"true", "1", "1.0"})

    if MODE_AUTO_COLUMN in df.columns:
        df = df[_truthy(df[MODE_AUTO_COLUMN])].copy()
    # Rename backing columns to canonical axis names so the baselines see the
    # contract-level axis vocabulary.
    inv = {col: axis for axis, col in backing.items() if col in df.columns}
    df = df.rename(columns=inv)
    # Apply subset AFTER auto filter so a small N is still meaningful when the
    # CSV starts with a long manual-mode prefix.
    if subset is not None and len(df) > subset:
        df = df.iloc[:subset]
    # Drop axis NaNs row-wise so EWMA / Mahalanobis see only finite values.
    axis_cols = [a for a in backing.keys() if a in df.columns]
    df = df.dropna(subset=axis_cols)
    df[TIMESTAMP_COLUMN] = df[TIMESTAMP_COLUMN].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df.reset_index(drop=True)


def active_continuous_axes(df: pd.DataFrame) -> list[str]:
    """Active axes for fitting: canonical ordered, masked excluded, present in df."""
    return [a for a in active_axes_ordered() if a != MASKED_AXIS and a in df.columns]


def combined_score_distribution(scored: pd.DataFrame) -> dict[str, float]:
    health = scored["health_score"].to_numpy(dtype=float)
    combined = scored["combined_deviation"].to_numpy(dtype=float)
    return {
        "health_score_mean": float(np.mean(health)),
        "health_score_std": float(np.std(health, ddof=1)) if health.size > 1 else 0.0,
        "health_score_p01": float(np.quantile(health, 0.01)),
        "health_score_p05": float(np.quantile(health, 0.05)),
        "health_score_p50": float(np.quantile(health, 0.50)),
        "health_score_p95": float(np.quantile(health, 0.95)),
        "health_score_p99": float(np.quantile(health, 0.99)),
        "combined_deviation_mean": float(np.mean(combined)),
        "combined_deviation_p95": float(np.quantile(combined, 0.95)),
        "combined_deviation_p99": float(np.quantile(combined, 0.99)),
        "anomaly_flag_rate": float(scored["anomaly_flag"].mean()),
    }


def build_report(df: pd.DataFrame, axes: list[str], args: argparse.Namespace) -> dict:
    suite = fit_health_baseline_suite(
        df,
        axes,
        lam=args.lam,
        calib_quantile=args.calib_quantile,
        health_threshold=args.health_threshold,
    )
    scored = suite.score(df)
    false_alarm = suite.false_alarm_summary(df)
    distribution = combined_score_distribution(scored)
    report = {
        "sprint": 28,
        "pillar": "A_health",
        "advisory_only": True,
        "evaluation_mode": "offline_only",
        "write_path": "none",
        "influences_control": False,
        "site_integration_allowed": False,
        "data": {
            "csv_path": str(args.csv),
            "n_rows_read": int(args.subset) if args.subset is not None else None,
            "n_rows_after_auto_filter": int(len(df)),
            "axes_used": axes,
            "timestamp_min": str(df["timestamp"].min()) if "timestamp" in df.columns else None,
            "timestamp_max": str(df["timestamp"].max()) if "timestamp" in df.columns else None,
        },
        "parameters": {
            "ewma_lambda": float(args.lam),
            "ewma_L_sigma": float(suite.spc.L),
            "mahalanobis_calib_quantile": float(args.calib_quantile),
            "health_threshold": float(args.health_threshold),
        },
        "baselines": suite.to_summary_dict(),
        "false_alarm_summary": false_alarm,
        "combined_score_distribution": distribution,
        "holdout_isolation": {
            "holdout_prefix": "2026-03",
            "asserted_before_fit": True,
            "n_train_val_checked": int(len(df)),
            "isolated": True,
        },
        "gate_artifact_notes": (
            "Sprint 28 BUILDS the bar (false-alarm behaviour of the interpretable "
            "baselines on held-in 2025 normal data); it does NOT need to beat anything. "
            "The 'beat-the-baseline' empirical test belongs to Sprint 29 (the learned "
            "detector) and is a separate human-reviewed gate."
        ),
    }
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sprint 28 Pillar-A baseline report.")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument(
        "--subset",
        type=int,
        default=200_000,
        help="Cap rows read from disk (None disables; default 200k stays fast on CI).",
    )
    p.add_argument("--lam", type=float, default=DEFAULT_EWMA_LAMBDA)
    p.add_argument("--calib-quantile", type=float, default=DEFAULT_MAHA_CALIB_QUANTILE)
    p.add_argument("--health-threshold", type=float, default=DEFAULT_HEALTH_THRESHOLD)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.csv.exists():
        print(f"[sprint28] CSV not found: {args.csv}", file=sys.stderr)
        return EXIT_NO_DATA
    subset = args.subset if args.subset and args.subset > 0 else None
    df = load_auto_mode_frame(args.csv, subset)
    if df.empty:
        print("[sprint28] no auto-mode rows after filtering", file=sys.stderr)
        return EXIT_NO_DATA
    axes = active_continuous_axes(df)
    if len(axes) < 2:
        print(f"[sprint28] insufficient active axes: {axes}", file=sys.stderr)
        return EXIT_NO_DATA
    try:
        report = build_report(df, axes, args)
    except LeakageError as e:
        print(f"[sprint28] LEAKAGE: {e}", file=sys.stderr)
        return EXIT_LEAKAGE
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    print(f"[sprint28] wrote {args.out}")
    print(
        f"[sprint28] held-in normal false-alarm rate: "
        f"{report['false_alarm_summary']['combined_anomaly_flag_rate']:.4%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
