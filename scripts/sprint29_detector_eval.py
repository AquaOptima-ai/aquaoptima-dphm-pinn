#!/usr/bin/env python3
"""AOPSO Sprint 29 - learned detector vs interpretable baseline scorecard.

Fits the Sprint-29 autoencoder detector and the Sprint-28 interpretable baseline
suite on a 2025 auto-mode subset of the Yilan CSV, generates a FROZEN-seed
injected-fault evaluation set, evaluates BOTH on AUROC / lead-time / false-alarm,
applies the FROZEN acceptance gate, and writes the scorecard JSON to
``data/eval/pillarA/sprint29_detector_scorecard.json``.

A FAIL verdict is an ACCEPTABLE, VALUABLE outcome. This script exits non-zero
ONLY on a true error (leakage, missing data, etc.); a model-gate FAIL exits 0
because the scorecard is the deliverable.

Hard boundary
-------------
Offline-only. The Sprint-27 leakage guard runs before any fit. No edge / OT /
write-capable connectors. Reads only the 2025 CSV; never March-2026.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
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
    FROZEN_AUROC_MARGIN,
    FROZEN_DETECTOR_MIN_AUROC,
    FROZEN_GATE_RULE_TEXT,
    evaluate_detector_vs_baseline,
    health_acceptance_gate,
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

DEFAULT_CSV = Path(
    "/home/hunter_lin/projects/yilan-site-model-testing/yearlong_drive/source1_2025.csv"
)
DEFAULT_OUT_PATH = (
    _REPO_ROOT / "data" / "eval" / "pillarA" / "sprint29_detector_scorecard.json"
)
DEFAULT_SPLIT = _REPO_ROOT / "data" / "splits" / "yilan_2025_split_v1.json"
DEFAULT_STATS = _REPO_ROOT / "data" / "normalization" / "yilan_2025_train_stats.json"
DEFAULT_SUBSET = 30000
DEFAULT_FAULT_SPLIT_FRACTION = 0.5  # half of the subset goes to the eval pool

EXIT_OK = 0
EXIT_LEAKAGE = 2
EXIT_NO_DATA = 3
EXIT_RUNTIME = 4


def load_auto_mode_frame(csv_path: Path, subset: int | None) -> pd.DataFrame:
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
    df[TIMESTAMP_COLUMN] = df[TIMESTAMP_COLUMN].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df.reset_index(drop=True)


def active_continuous_axes(df: pd.DataFrame) -> list[str]:
    return [a for a in active_axes_ordered() if a != MASKED_AXIS and a in df.columns]


def split_train_eval_pool(
    df: pd.DataFrame, fault_pool_fraction: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use the earlier half for fitting, later half as the normal pool we inject faults into."""
    n = len(df)
    n_pool = max(800, int(n * float(fault_pool_fraction)))
    n_pool = min(n_pool, n // 2 if n >= 1600 else n - 100)
    n_pool = max(200, n_pool)
    n_train = n - n_pool
    if n_train < 200:
        # Tiny subset: just split 70/30.
        n_train = int(n * 0.7)
        n_pool = n - n_train
    train = df.iloc[:n_train].reset_index(drop=True)
    pool = df.iloc[n_train:].reset_index(drop=True)
    return train, pool


def build_scorecard(args: argparse.Namespace) -> dict[str, Any]:
    if not args.csv.exists():
        raise FileNotFoundError(f"CSV not found: {args.csv}")
    df = load_auto_mode_frame(args.csv, args.subset)
    if df.empty:
        raise RuntimeError("no auto-mode rows after filtering")
    axes = active_continuous_axes(df)
    if len(axes) < 2:
        raise RuntimeError(f"insufficient active axes: {axes}")

    train_df, eval_pool = split_train_eval_pool(df, args.fault_pool_fraction)
    if len(eval_pool) < 600:
        raise RuntimeError(
            f"eval pool too small: {len(eval_pool)} rows; need at least 600"
        )

    detector = fit_health_detector(
        train_df,
        axes=axes,
        seed=args.detector_seed,
        epochs=args.epochs,
        batch_size=args.batch_size,
        norm_stats_path=args.stats if args.stats.exists() else None,
    )
    suite = fit_health_baseline_suite(train_df, axes=axes)

    injected = inject_faults(
        eval_pool,
        seed=args.fault_seed,
        n_episodes_per_kind=args.episodes_per_kind,
        drift_window=args.drift_window,
        stuck_window=args.stuck_window,
        envelope_window=args.envelope_window,
    )

    eval_dict = evaluate_detector_vs_baseline(
        detector=detector, baseline_suite=suite, injected=injected
    )
    gate = health_acceptance_gate(eval_dict)

    governance_block: dict[str, Any] | None = None
    governance_status = "SKIPPED"
    if args.split.exists() and args.stats.exists():
        try:
            governance_block = build_governance_block(
                split_manifest=args.split,
                modeling_roots=[
                    _REPO_ROOT / p for p in DEFAULT_MODELING_ROOTS
                ],
                normalization_stats=args.stats,
            )
            gate = apply_governance_to_verdict(gate, governance_block)
            governance_status = governance_block["governance_status"]
        except Exception as exc:  # pragma: no cover - defensive
            governance_block = {"governance_status": "ERROR", "error": str(exc)}
            governance_status = "ERROR"

    scorecard = {
        "sprint": 29,
        "pillar": "A_health",
        "advisory_only": True,
        "evaluation_mode": "offline_only",
        "write_path": "none",
        "influences_control": False,
        "site_integration_allowed": False,
        "data": {
            "csv_path": str(args.csv),
            "n_rows_after_auto_filter": int(len(df)),
            "n_train_rows": int(len(train_df)),
            "n_eval_pool_rows": int(len(eval_pool)),
            "n_eval_rows_total": int(len(injected.frames)),
            "axes_used": axes,
            "timestamp_min_train": str(train_df["timestamp"].min()) if "timestamp" in train_df.columns else None,
            "timestamp_max_train": str(train_df["timestamp"].max()) if "timestamp" in train_df.columns else None,
        },
        "detector": detector.to_summary_dict(),
        "baseline": suite.to_summary_dict(),
        "injected_faults": injected.to_summary_dict(),
        "evaluation": eval_dict,
        "acceptance_gate": gate,
        "frozen_gate": {
            "rule_text": FROZEN_GATE_RULE_TEXT,
            "auroc_margin": FROZEN_AUROC_MARGIN,
            "min_detector_auroc": FROZEN_DETECTOR_MIN_AUROC,
            "preregistered_before_evaluation": True,
            "tuned_to_outcome": False,
        },
        "safety": {
            "evaluation_mode": "offline_only",
            "write_path": "none",
            "influences_control": False,
            "site_integration_allowed": False,
            "governance_status": governance_status,
            "governance": governance_block,
        },
        "holdout_isolation": {
            "holdout_prefix": "2026-03",
            "asserted_before_fit": True,
        },
        "verdict": gate.get("verdict", "FAIL"),
    }
    return scorecard


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sprint 29 detector vs baseline scorecard.")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--subset", type=int, default=DEFAULT_SUBSET)
    p.add_argument("--detector-seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--fault-seed", type=int, default=DEFAULT_FAULT_SEED)
    p.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--episodes-per-kind", type=int, default=8)
    p.add_argument("--drift-window", type=int, default=120)
    p.add_argument("--stuck-window", type=int, default=80)
    p.add_argument("--envelope-window", type=int, default=60)
    p.add_argument("--fault-pool-fraction", type=float, default=DEFAULT_FAULT_SPLIT_FRACTION)
    p.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    p.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.csv.exists():
        print(f"[sprint29] CSV not found: {args.csv}", file=sys.stderr)
        return EXIT_NO_DATA
    try:
        scorecard = build_scorecard(args)
    except LeakageError as exc:
        print(f"[sprint29] LEAKAGE: {exc}", file=sys.stderr)
        return EXIT_LEAKAGE
    except FileNotFoundError as exc:
        print(f"[sprint29] missing data: {exc}", file=sys.stderr)
        return EXIT_NO_DATA
    except RuntimeError as exc:
        print(f"[sprint29] runtime: {exc}", file=sys.stderr)
        return EXIT_RUNTIME
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        json.dump(scorecard, f, indent=2, sort_keys=True, default=str)
    print(f"[sprint29] wrote {args.out}")
    print(
        f"[sprint29] detector_auroc={scorecard['evaluation']['detector']['auroc']:.4f} "
        f"baseline_auroc={scorecard['evaluation']['baseline']['auroc']:.4f} "
        f"verdict={scorecard['verdict']}"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
