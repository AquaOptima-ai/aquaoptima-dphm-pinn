"""Z-score normalization stats over the Yilan TRAIN split (AOPSO Sprint 23).

Computes per-active-axis mean (mu) and standard deviation (sigma) using ONLY
the rows belonging to the ``train`` split of the split manifest, then caches
them to ``data/normalization/yilan_2025_train_stats.json``.

Zero-coverage axes (notably ``edge_valve_position``, which has no backing
column in the Yilan site data) are excluded from the active axis set and are
NOT normalized.

Safety: offline_only, write_path=none, influences_control=false,
site_integration_allowed=false. No edge imports, no training, contracts
read-only. pandas/numpy/stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


def _collect_train_indices(manifest: dict) -> list[int]:
    train = manifest["splits"]["train"]
    indices: list[int] = []
    for start, end in train.get("row_index_ranges", []):
        indices.extend(range(int(start), int(end) + 1))
    return indices


def compute_train_stats(
    manifest: dict,
    *,
    csv_path: str | os.PathLike[str] | None = None,
    nrows: int | None = None,
    split_key: str = "train",
) -> dict:
    """Compute mu/sigma per active axis from the chosen split's rows."""
    # Import here to avoid a hard import cycle at module load.
    from ..dataio.yilan_axis_map import (
        CANONICAL_AXES_ORDERED,
        CANONICAL_AXIS_TO_COLUMN,
    )
    from ..dataio.yilan_profiler import load_frame

    df = load_frame(csv_path, nrows=nrows)

    split = manifest["splits"][split_key]
    indices: list[int] = []
    for start, end in split.get("row_index_ranges", []):
        indices.extend(range(int(start), int(end) + 1))
    # Guard: indices must be valid for this frame.
    indices = [i for i in indices if 0 <= i < len(df)]
    sub = df.iloc[indices] if indices else df.iloc[0:0]

    axes_stats: dict[str, dict] = {}
    active_axes: list[str] = []
    excluded_axes: list[str] = []

    for axis in CANONICAL_AXES_ORDERED:
        col = CANONICAL_AXIS_TO_COLUMN[axis]
        if col is None or col not in df.columns:
            excluded_axes.append(axis)
            continue
        values = pd.to_numeric(sub[col], errors="coerce").dropna().to_numpy(
            dtype=float
        )
        if values.size == 0:
            excluded_axes.append(axis)
            continue
        mu = float(np.mean(values))
        sigma = float(np.std(values))
        if not np.isfinite(mu) or not np.isfinite(sigma) or sigma == 0.0:
            # Zero-variance / non-finite axis cannot be z-scored; exclude.
            excluded_axes.append(axis)
            continue
        axes_stats[axis] = {
            "source_column": col,
            "mu": mu,
            "sigma": sigma,
            "n": int(values.size),
        }
        active_axes.append(axis)

    return {
        "split_version": manifest.get("split_version"),
        "split_key": split_key,
        "computed_on": "train split only (no val/manual/holdout leakage)",
        "n_train_rows_used": int(len(sub)),
        "active_axes": active_axes,
        "excluded_axes": excluded_axes,
        "excluded_reason": (
            "zero coverage / no backing column / zero variance "
            "(e.g. edge_valve_position has no Yilan telemetry column)"
        ),
        "stats": axes_stats,
        "safety": {
            "evaluation_mode": "offline_only",
            "write_path": "none",
            "influences_control": False,
            "site_integration_allowed": False,
        },
    }


def write_stats(stats: dict, output_path: str | os.PathLike[str]) -> str:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, indent=2) + "\n")
    return str(out)


def load_stats(path: str | os.PathLike[str]) -> dict:
    return json.loads(Path(path).read_text())


def apply_normalization(
    values: "np.ndarray", axes: list[str], stats: dict
) -> "np.ndarray":
    """Apply cached z-score to a [.., n_axes] array, columns ordered by ``axes``."""
    mu = np.array([stats["stats"][a]["mu"] for a in axes], dtype=float)
    sigma = np.array([stats["stats"][a]["sigma"] for a in axes], dtype=float)
    return (np.asarray(values, dtype=float) - mu) / sigma


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yilan train normalization stats")
    parser.add_argument(
        "--split-manifest",
        default="data/splits/yilan_2025_split_v1.json",
        help="Split manifest path",
    )
    parser.add_argument("--split-key", default="train", help="Split to use")
    parser.add_argument("--input", default=None, help="CSV path")
    parser.add_argument(
        "--output",
        default="data/normalization/yilan_2025_train_stats.json",
        help="Stats output path",
    )
    parser.add_argument("--nrows", type=int, default=None, help="Row limit")
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest = json.loads(Path(args.split_manifest).read_text())
    stats = compute_train_stats(
        manifest, csv_path=args.input, nrows=args.nrows, split_key=args.split_key
    )
    path = write_stats(stats, args.output)
    print(
        f"Computed mu/sigma for {len(stats['active_axes'])} active axes "
        f"(excluded: {stats['excluded_axes']}) over "
        f"{stats['n_train_rows_used']} train rows"
    )
    print(f"Normalization stats written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
