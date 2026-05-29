"""Leakage-free temporal split builder (AOPSO Sprint 23).

Builds a mode-stratified, temporally-disjoint split manifest from the Yilan
2025 source CSV and writes ``data/splits/yilan_2025_split_v1.json``.

Splits
------
* ``train``           : auto-mode 2025 rows, EXCLUDING the held-out val window.
* ``val``             : a held-out *contiguous* auto-mode window (the most
  recent whole auto-mode month) -- temporally disjoint from train with NO
  calendar-day overlap. This is leakage-free: no train day appears in val.
* ``manual_slice``    : manual-mode 2025 rows (robustness carve-out).
* ``holdout_march2026``: reference ONLY -- a date range pointing at the frozen
  March-2026 holdout. No 2026 rows are read here.

Each split records the actual computed row counts, the set of calendar days it
covers, and (for the row-bearing splits) the row index ranges.

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

import pandas as pd

from . import yilan_profiler as profiler
from .yilan_profiler import (
    MODE_AUTO,
    MODE_MANUAL,
    TIMESTAMP_COLUMN,
    derive_mode,
    load_frame,
)

SPLIT_VERSION = "v1"

# Frozen March-2026 holdout reference (NO rows read in this sprint).
HOLDOUT_MARCH2026_START = "2026-03-01T00:00:00"
HOLDOUT_MARCH2026_END = "2026-03-31T23:59:59"
HOLDOUT_2026_CSV_REFERENCE = "source1_2026.csv"


def _day_set(ts: pd.Series) -> list[str]:
    return sorted({d.isoformat() for d in ts.dt.date.unique()})


def _index_ranges(indices: list[int]) -> list[list[int]]:
    """Compress a sorted index list into [start, end] inclusive runs."""
    if not indices:
        return []
    ranges: list[list[int]] = []
    start = prev = indices[0]
    for idx in indices[1:]:
        if idx == prev + 1:
            prev = idx
            continue
        ranges.append([start, prev])
        start = prev = idx
    ranges.append([start, prev])
    return ranges


def build_split(
    csv_path: str | os.PathLike[str] | None = None,
    *,
    nrows: int | None = None,
) -> dict:
    df = load_frame(csv_path, nrows=nrows)
    mode = derive_mode(df)
    ts = df[TIMESTAMP_COLUMN]

    auto_mask = mode == MODE_AUTO
    manual_mask = mode == MODE_MANUAL

    auto_idx = df.index[auto_mask]
    auto_ts = ts[auto_mask]

    # Choose the validation window = the most-recent whole auto-mode month.
    # This is contiguous and day-disjoint from the rest of auto-mode (train).
    val_days: set = set()
    val_period = None
    if len(auto_ts) > 0:
        periods = auto_ts.dt.to_period("M")
        last_period = periods.max()
        val_period = str(last_period)
        val_window_mask = (mode == MODE_AUTO) & (
            ts.dt.to_period("M") == last_period
        )
        val_days = {d.isoformat() for d in ts[val_window_mask].dt.date.unique()}
    else:
        val_window_mask = pd.Series(False, index=df.index)

    val_idx = df.index[val_window_mask]
    # Train = auto-mode rows NOT in the val window AND not on any val day.
    train_day_mask = ~ts.dt.date.astype(str).isin(val_days)
    train_mask = auto_mask & ~val_window_mask & train_day_mask
    train_idx = df.index[train_mask]

    def _split_record(idx, mask, *, mode_label, description) -> dict:
        sub_ts = ts[mask]
        rec = {
            "description": description,
            "mode": mode_label,
            "row_count": int(len(idx)),
            "row_index_ranges": _index_ranges([int(i) for i in idx]),
        }
        if len(sub_ts) > 0:
            rec["date_range"] = {
                "start": sub_ts.min().isoformat(),
                "end": sub_ts.max().isoformat(),
            }
            rec["days"] = _day_set(sub_ts)
            rec["n_days"] = len(rec["days"])
        else:
            rec["date_range"] = {"start": None, "end": None}
            rec["days"] = []
            rec["n_days"] = 0
        return rec

    train_rec = _split_record(
        train_idx,
        train_mask,
        mode_label=MODE_AUTO,
        description="Auto-mode 2025 training rows (val window excluded).",
    )
    val_rec = _split_record(
        val_idx,
        val_window_mask,
        mode_label=MODE_AUTO,
        description=(
            "Held-out contiguous auto-mode validation window "
            f"(most recent whole auto-mode month: {val_period}); "
            "temporally disjoint from train, no calendar-day overlap."
        ),
    )
    val_rec["val_period"] = val_period
    manual_rec = _split_record(
        df.index[manual_mask],
        manual_mask,
        mode_label=MODE_MANUAL,
        description="Manual-mode 2025 rows (robustness carve-out).",
    )

    holdout_rec = {
        "description": (
            "Frozen March-2026 holdout. REFERENCE ONLY -- no 2026 rows are "
            "read or used to compute stats in this sprint."
        ),
        "mode": "reference",
        "row_count": 0,
        "date_range": {
            "start": HOLDOUT_MARCH2026_START,
            "end": HOLDOUT_MARCH2026_END,
        },
        "source_csv_reference": HOLDOUT_2026_CSV_REFERENCE,
        "days": [],
        "n_days": 0,
    }

    manifest = {
        "split_version": SPLIT_VERSION,
        "source_csv": str(profiler.resolve_csv_path(csv_path)),
        "nrows_limit": nrows,
        "total_rows_scanned": int(len(df)),
        "csv_span": {
            "start": ts.min().isoformat() if len(ts) else None,
            "end": ts.max().isoformat() if len(ts) else None,
        },
        "stratification": {
            "by": "operating mode (auto/manual columns)",
            "note": (
                "DATA-REALITY CORRECTION: stratified on real 'auto'/'manual' "
                "columns, not roadmap-guessed optimizer_enabled/auto_mode_active."
            ),
        },
        "safety": {
            "evaluation_mode": "offline_only",
            "write_path": "none",
            "influences_control": False,
            "site_integration_allowed": False,
        },
        "splits": {
            "train": train_rec,
            "val": val_rec,
            "manual_slice": manual_rec,
            "holdout_march2026": holdout_rec,
        },
    }

    # Leakage self-check: assert no calendar-day overlap between train & val.
    overlap = set(train_rec["days"]) & set(val_rec["days"])
    manifest["leakage_check"] = {
        "train_val_day_overlap": sorted(overlap),
        "train_val_day_disjoint": len(overlap) == 0,
        "march_2026_excluded_from_2025": all(
            not d.startswith("2026-") for d in train_rec["days"] + val_rec["days"]
        ),
    }
    return manifest


def write_split(
    manifest: dict, output_path: str | os.PathLike[str]
) -> str:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    return str(out)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yilan 2025 temporal split builder")
    parser.add_argument("--input", default=None, help="CSV path")
    parser.add_argument(
        "--output",
        default="data/splits/yilan_2025_split_v1.json",
        help="Split manifest output path",
    )
    parser.add_argument("--nrows", type=int, default=None, help="Row limit")
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest = build_split(args.input, nrows=args.nrows)
    path = write_split(manifest, args.output)

    s = manifest["splits"]
    print(
        f"Train: {s['train']['row_count']} rows "
        f"({s['train']['date_range']['start']} .. {s['train']['date_range']['end']})"
    )
    print(
        f"Val:   {s['val']['row_count']} rows (period {s['val']['val_period']}, "
        f"{s['val']['date_range']['start']} .. {s['val']['date_range']['end']})"
    )
    print(f"Manual slice: {s['manual_slice']['row_count']} rows")
    print(
        f"Holdout March 2026: reference only "
        f"({s['holdout_march2026']['date_range']['start']} .. "
        f"{s['holdout_march2026']['date_range']['end']})"
    )
    print(
        f"Leakage check -> day-disjoint: "
        f"{manifest['leakage_check']['train_val_day_disjoint']}"
    )
    print(f"Split manifest written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
