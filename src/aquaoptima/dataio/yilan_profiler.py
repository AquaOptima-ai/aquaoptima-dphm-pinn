"""Yilan 2025 data profiler (AOPSO Sprint 23).

Read-only profiling of the year-long Yilan source CSV. Produces four
reproducible artifacts under ``data/profiling/``:

1. ``mode_coverage_2025.json``  -- auto / manual / other / total row counts
   plus a per-month breakdown. Operating mode is derived from the real
   ``auto`` and ``manual`` columns (DATA-REALITY CORRECTION: the roadmap
   guessed ``optimizer_enabled`` / ``auto_mode_active``).
2. ``axis_coverage_2025.csv``   -- per canonical axis, per operating mode
   non-null coverage %.
3. ``extreme_data_log_2025.csv`` -- rows/values flagged by the 3-sigma and
   p99 rules, per active axis.
4. ``gap_intervals_2025.json``  -- temporal gaps where the inter-sample
   spacing exceeds 5 minutes (start / end / seconds).

Safety boundary: evaluation_mode=offline_only, write_path=none (we only
write profiling artifacts, never control), influences_control=false,
site_integration_allowed=false. No imports from ``aquaoptima.edge``; no
model training; ``aquaoptima_contracts`` is read-only. pandas / numpy /
stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .yilan_axis_map import (
    CANONICAL_AXES_ORDERED,
    CANONICAL_AXIS_TO_COLUMN,
    MODE_AUTO_COLUMN,
    MODE_MANUAL_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_FORMAT,
)

# Default location of the real year-long CSV. Overridable via env var so we
# never hard-code or copy the file into the repo.
DEFAULT_CSV_PATH = (
    "/home/hunter_lin/projects/yilan-site-model-testing/"
    "yearlong_drive/source1_2025.csv"
)
YILAN_2025_CSV_ENV = "YILAN_2025_CSV"

# Temporal gap threshold: more than 5 minutes between consecutive samples.
GAP_THRESHOLD_SECONDS = 5 * 60

# Operating-mode labels.
MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODE_OTHER = "other"
MODE_TOTAL = "total"
ACTIVE_MODES = (MODE_AUTO, MODE_MANUAL, MODE_OTHER)


def resolve_csv_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the CSV path: explicit arg > env var > default."""
    if path is not None:
        return Path(path)
    return Path(os.environ.get(YILAN_2025_CSV_ENV, DEFAULT_CSV_PATH))


def _truthy_flag(series: pd.Series) -> pd.Series:
    """Interpret a boolean/float/string flag column as boolean.

    Accepts ``True``/``1``/``1.0`` (any case) as truthy; everything else
    (including NaN, ``False``, ``0``) is falsy.
    """
    s = series.astype(str).str.strip().str.lower()
    return s.isin({"true", "1", "1.0"})


def load_frame(
    csv_path: str | os.PathLike[str] | None = None,
    *,
    nrows: int | None = None,
) -> pd.DataFrame:
    """Load the needed columns from the Yilan CSV.

    Only the timestamp, the two mode columns, and the backing columns for
    the canonical axes are read, keeping memory bounded. ``nrows`` (or the
    ``YILAN_PROFILER_NROWS`` env var) limits rows so tests run on a subset.
    """
    path = resolve_csv_path(csv_path)
    if nrows is None:
        env_nrows = os.environ.get("YILAN_PROFILER_NROWS")
        if env_nrows:
            nrows = int(env_nrows)

    backing_cols = [
        col for col in CANONICAL_AXIS_TO_COLUMN.values() if col is not None
    ]
    wanted = [TIMESTAMP_COLUMN, MODE_AUTO_COLUMN, MODE_MANUAL_COLUMN, *backing_cols]
    # Some optional columns might be absent in a tiny test fixture; tolerate.
    header = pd.read_csv(path, nrows=0)
    present = [c for c in wanted if c in header.columns]

    df = pd.read_csv(path, usecols=present, nrows=nrows, low_memory=False)

    df[TIMESTAMP_COLUMN] = pd.to_datetime(
        df[TIMESTAMP_COLUMN], format=TIMESTAMP_FORMAT, errors="coerce"
    )
    df = df.dropna(subset=[TIMESTAMP_COLUMN]).reset_index(drop=True)
    df = df.sort_values(TIMESTAMP_COLUMN, kind="stable").reset_index(drop=True)

    # Coerce backing axis columns to numeric (status flags etc. may be bool).
    for col in backing_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def derive_mode(df: pd.DataFrame) -> pd.Series:
    """Derive a per-row operating-mode label from the real flag columns.

    DATA REALITY: ``auto`` and ``manual`` are NOT strict complements. Rows
    that are neither auto-truthy nor manual-truthy are labelled ``other``
    (idle / unlabelled). Auto takes precedence if both were ever set.
    """
    auto = (
        _truthy_flag(df[MODE_AUTO_COLUMN])
        if MODE_AUTO_COLUMN in df.columns
        else pd.Series(False, index=df.index)
    )
    manual = (
        _truthy_flag(df[MODE_MANUAL_COLUMN])
        if MODE_MANUAL_COLUMN in df.columns
        else pd.Series(False, index=df.index)
    )
    mode = pd.Series(MODE_OTHER, index=df.index, dtype=object)
    mode[manual] = MODE_MANUAL
    mode[auto] = MODE_AUTO  # auto precedence
    return mode


@dataclass
class ProfileResult:
    total_rows: int
    mode_coverage: dict
    axis_coverage_rows: list[dict] = field(default_factory=list)
    extreme_rows: list[dict] = field(default_factory=list)
    gap_intervals: list[dict] = field(default_factory=list)


def compute_mode_coverage(df: pd.DataFrame, mode: pd.Series) -> dict:
    """auto/manual/other/total row counts + percentages + per-month breakdown."""
    total = int(len(df))
    counts = mode.value_counts().to_dict()
    summary = {
        "total_rows": total,
        "csv_span_start": df[TIMESTAMP_COLUMN].min().isoformat(),
        "csv_span_end": df[TIMESTAMP_COLUMN].max().isoformat(),
        "mode_columns": {"auto": MODE_AUTO_COLUMN, "manual": MODE_MANUAL_COLUMN},
        "counts": {},
        "percentages": {},
        "by_month": {},
        "note": (
            "auto/manual are real CSV boolean columns and are NOT strict "
            "complements; rows that are neither are labelled 'other' "
            "(idle/unlabelled)."
        ),
    }
    for m in ACTIVE_MODES:
        c = int(counts.get(m, 0))
        summary["counts"][m] = c
        summary["percentages"][m] = round(100.0 * c / total, 4) if total else 0.0
    summary["counts"][MODE_TOTAL] = total
    summary["percentages"][MODE_TOTAL] = 100.0 if total else 0.0

    months = df[TIMESTAMP_COLUMN].dt.month
    for month in range(1, 13):
        mask = months == month
        n = int(mask.sum())
        if n == 0:
            continue
        month_modes = mode[mask].value_counts().to_dict()
        entry = {m: int(month_modes.get(m, 0)) for m in ACTIVE_MODES}
        entry["total"] = n
        entry["auto_pct"] = round(100.0 * entry[MODE_AUTO] / n, 2)
        summary["by_month"][str(month)] = entry
    return summary


def compute_axis_coverage(df: pd.DataFrame, mode: pd.Series) -> list[dict]:
    """Per canonical axis, per mode (and overall) non-null coverage %."""
    rows: list[dict] = []
    total = len(df)
    for axis in CANONICAL_AXES_ORDERED:
        col = CANONICAL_AXIS_TO_COLUMN[axis]
        present = col is not None and col in df.columns
        record: dict = {
            "axis": axis,
            "source_column": col if col is not None else "",
            "active": present,
        }
        if present:
            nonnull = df[col].notna()
            record["coverage_pct_total"] = (
                round(100.0 * nonnull.mean(), 4) if total else 0.0
            )
            for m in ACTIVE_MODES:
                mask = mode == m
                n = int(mask.sum())
                cov = (
                    round(100.0 * (nonnull & mask).sum() / n, 4) if n else 0.0
                )
                record[f"coverage_pct_{m}"] = cov
        else:
            record["coverage_pct_total"] = 0.0
            for m in ACTIVE_MODES:
                record[f"coverage_pct_{m}"] = 0.0
        # An axis is active iff it has a backing column with >0 coverage.
        record["active"] = bool(present and record["coverage_pct_total"] > 0.0)
        rows.append(record)
    return rows


def compute_extreme_data(
    df: pd.DataFrame, axis_coverage: list[dict]
) -> list[dict]:
    """Tag extreme values per active axis via 3-sigma and p99 rules.

    For each active axis we record the count of values beyond mean +/- 3*std
    and beyond the p99 threshold, with the actual numeric thresholds. One row
    per active axis (a compact, deterministic log).
    """
    rows: list[dict] = []
    active = {r["axis"] for r in axis_coverage if r["active"]}
    for axis in CANONICAL_AXES_ORDERED:
        if axis not in active:
            continue
        col = CANONICAL_AXIS_TO_COLUMN[axis]
        values = df[col].dropna().to_numpy(dtype=float)
        if values.size == 0:
            continue
        mu = float(np.mean(values))
        sigma = float(np.std(values))
        p99 = float(np.percentile(values, 99))
        if sigma > 0:
            lower = mu - 3 * sigma
            upper = mu + 3 * sigma
            n_3sigma = int(np.count_nonzero((values < lower) | (values > upper)))
        else:
            lower = upper = mu
            n_3sigma = 0
        n_p99 = int(np.count_nonzero(values > p99))
        rows.append(
            {
                "axis": axis,
                "source_column": col,
                "n_values": int(values.size),
                "mean": round(mu, 6),
                "std": round(sigma, 6),
                "sigma3_lower": round(lower, 6),
                "sigma3_upper": round(upper, 6),
                "n_beyond_3sigma": n_3sigma,
                "pct_beyond_3sigma": round(100.0 * n_3sigma / values.size, 4),
                "p99_threshold": round(p99, 6),
                "n_beyond_p99": n_p99,
                "pct_beyond_p99": round(100.0 * n_p99 / values.size, 4),
            }
        )
    return rows


def compute_gaps(df: pd.DataFrame) -> list[dict]:
    """Detect temporal gaps where spacing exceeds GAP_THRESHOLD_SECONDS."""
    ts = df[TIMESTAMP_COLUMN].reset_index(drop=True)
    if len(ts) < 2:
        return []
    deltas = ts.diff().dt.total_seconds()
    gaps: list[dict] = []
    for i in range(1, len(ts)):
        secs = deltas.iloc[i]
        if pd.notna(secs) and secs > GAP_THRESHOLD_SECONDS:
            gaps.append(
                {
                    "index_before": int(i - 1),
                    "index_after": int(i),
                    "start": ts.iloc[i - 1].isoformat(),
                    "end": ts.iloc[i].isoformat(),
                    "seconds": float(secs),
                }
            )
    return gaps


def profile(
    csv_path: str | os.PathLike[str] | None = None,
    *,
    nrows: int | None = None,
) -> ProfileResult:
    df = load_frame(csv_path, nrows=nrows)
    mode = derive_mode(df)
    mode_cov = compute_mode_coverage(df, mode)
    axis_cov = compute_axis_coverage(df, mode)
    extreme = compute_extreme_data(df, axis_cov)
    gaps = compute_gaps(df)
    mode_cov["gap_count"] = len(gaps)
    return ProfileResult(
        total_rows=len(df),
        mode_coverage=mode_cov,
        axis_coverage_rows=axis_cov,
        extreme_rows=extreme,
        gap_intervals=gaps,
    )


def write_artifacts(result: ProfileResult, output_dir: str | os.PathLike[str]) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    mode_path = out / "mode_coverage_2025.json"
    axis_path = out / "axis_coverage_2025.csv"
    extreme_path = out / "extreme_data_log_2025.csv"
    gap_path = out / "gap_intervals_2025.json"

    mode_path.write_text(json.dumps(result.mode_coverage, indent=2) + "\n")

    axis_cols = [
        "axis",
        "source_column",
        "active",
        "coverage_pct_total",
        f"coverage_pct_{MODE_AUTO}",
        f"coverage_pct_{MODE_MANUAL}",
        f"coverage_pct_{MODE_OTHER}",
    ]
    pd.DataFrame(result.axis_coverage_rows, columns=axis_cols).to_csv(
        axis_path, index=False
    )

    extreme_cols = [
        "axis",
        "source_column",
        "n_values",
        "mean",
        "std",
        "sigma3_lower",
        "sigma3_upper",
        "n_beyond_3sigma",
        "pct_beyond_3sigma",
        "p99_threshold",
        "n_beyond_p99",
        "pct_beyond_p99",
    ]
    pd.DataFrame(result.extreme_rows, columns=extreme_cols).to_csv(
        extreme_path, index=False
    )

    gap_payload = {
        "gap_threshold_seconds": GAP_THRESHOLD_SECONDS,
        "gap_count": len(result.gap_intervals),
        "gaps": result.gap_intervals,
    }
    gap_path.write_text(json.dumps(gap_payload, indent=2) + "\n")

    return {
        "mode_coverage": str(mode_path),
        "axis_coverage": str(axis_path),
        "extreme_data_log": str(extreme_path),
        "gap_intervals": str(gap_path),
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yilan 2025 data profiler")
    parser.add_argument(
        "--input", default=None, help="CSV path (default: $YILAN_2025_CSV or built-in)"
    )
    parser.add_argument(
        "--output-dir", default="data/profiling", help="Artifact output directory"
    )
    parser.add_argument(
        "--nrows", type=int, default=None, help="Row limit (testing subset)"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = profile(args.input, nrows=args.nrows)
    paths = write_artifacts(result, args.output_dir)

    cov = result.mode_coverage
    auto_c = cov["counts"][MODE_AUTO]
    manual_c = cov["counts"][MODE_MANUAL]
    other_c = cov["counts"][MODE_OTHER]
    auto_p = cov["percentages"][MODE_AUTO]
    manual_p = cov["percentages"][MODE_MANUAL]
    print(
        f"Mode coverage: auto={auto_p}% ({auto_c} rows), "
        f"manual={manual_p}% ({manual_c} rows), other={other_c} rows; "
        f"total={cov['total_rows']} rows"
    )
    print(f"Gaps detected: {len(result.gap_intervals)} intervals > 5 min")
    print(f"Artifacts written: {json.dumps(paths, indent=2)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
