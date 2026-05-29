"""AOPSO Sprint 27 — isolation + profile report CLI.

Re-runs the Yilan profiler (subset-capable via ``YILAN_PROFILER_NROWS``) and the
Sprint 27 governance block against the real
``data/splits/yilan_2025_split_v1.json`` split + the cached
``data/normalization/yilan_2025_train_stats.json``, then writes a single combined
report to ``data/profiling/sprint27_isolation_report.json``.

The report summarises:

* mode-coverage counts (auto / manual / OTHER), incl. the ~31.6% ``other`` bucket
  that surfaced in Sprint 23 (real ``auto``/``manual`` columns, not the roadmap's
  guessed flags),
* the March-2026 LOCKED holdout isolation check over the train/val keys,
* the axis-taxonomy validator,
* the normalization-coverage validator,
* the modeling-source import / connector scan.

Process exit code: 0 on governance PASS, 1 on FAIL. CI gates on the exit code so a
governance regression blocks the artifact contract.

Safety
------
Offline only. Reads CSV + JSON. Writes ONLY the report JSON (no model, no setpoint,
no edge import, no contract write). The full year-long CSV scan is only run when
``YILAN_PROFILER_FULL=1`` is set; otherwise we honour ``YILAN_PROFILER_NROWS`` (or
the profiler default) so the CLI stays fast and unit-testable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable

# Repo-root sys.path fix so the script works when invoked as
# ``python scripts/sprint27_profile_report.py`` from the repo root without
# requiring an editable install.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aquaoptima.advisory.schema_validation import (  # noqa: E402
    DEFAULT_MODELING_ROOTS,
    build_governance_block,
)
from aquaoptima.dataio.yilan_profiler import profile  # noqa: E402

DEFAULT_SPLIT = "data/splits/yilan_2025_split_v1.json"
DEFAULT_STATS = "data/normalization/yilan_2025_train_stats.json"
DEFAULT_OUTPUT = "data/profiling/sprint27_isolation_report.json"

FULL_CSV_ENV = "YILAN_PROFILER_FULL"
NROWS_ENV = "YILAN_PROFILER_NROWS"


def _summarise_mode_coverage(mode_cov: dict) -> dict:
    """Compact mode-coverage summary safe for the report (no per-month detail)."""
    counts = mode_cov.get("counts", {})
    percents = mode_cov.get("percentages", {})
    return {
        "total_rows": mode_cov.get("total_rows", 0),
        "auto": {
            "rows": counts.get("auto", 0),
            "pct": percents.get("auto", 0.0),
        },
        "manual": {
            "rows": counts.get("manual", 0),
            "pct": percents.get("manual", 0.0),
        },
        "other": {
            "rows": counts.get("other", 0),
            "pct": percents.get("other", 0.0),
        },
        "csv_span_start": mode_cov.get("csv_span_start"),
        "csv_span_end": mode_cov.get("csv_span_end"),
        "note": mode_cov.get("note"),
    }


def build_report(
    *,
    split_manifest: str | os.PathLike[str] = DEFAULT_SPLIT,
    norm_stats: str | os.PathLike[str] = DEFAULT_STATS,
    csv_path: str | os.PathLike[str] | None = None,
    nrows: int | None = None,
    run_profile: bool = True,
    modeling_roots: Iterable[Path | str] = DEFAULT_MODELING_ROOTS,
) -> dict:
    """Assemble the Sprint 27 combined report dict (no IO of its own).

    ``run_profile=False`` skips the CSV read entirely (used in unit tests so the
    full 489K-row file is never opened).
    """
    governance = build_governance_block(
        split_manifest=str(split_manifest),
        modeling_roots=tuple(modeling_roots),
        normalization_stats=str(norm_stats),
    )

    profile_summary: dict | None = None
    if run_profile:
        result = profile(csv_path, nrows=nrows)
        profile_summary = {
            "total_rows": result.total_rows,
            "mode_coverage": _summarise_mode_coverage(result.mode_coverage),
            "gap_count": len(result.gap_intervals),
            "axis_coverage_rows": result.axis_coverage_rows,
            "extreme_count": len(result.extreme_rows),
        }

    return {
        "sprint": "AOPSO Sprint 27",
        "advisory_only": True,
        "split_manifest": str(split_manifest),
        "norm_stats": str(norm_stats),
        "profile_subset_rows": nrows,
        "profile": profile_summary,
        "governance": governance,
        "safety": {
            "evaluation_mode": "offline_only",
            "write_path": "report_json_only",
            "influences_control": False,
            "site_integration_allowed": False,
        },
    }


def _resolve_nrows(explicit: int | None) -> int | None:
    if explicit is not None:
        return explicit
    env_nrows = os.environ.get(NROWS_ENV)
    if env_nrows:
        return int(env_nrows)
    # Default to a small subset so a stray invocation never opens the full CSV.
    if os.environ.get(FULL_CSV_ENV) == "1":
        return None
    return 50_000


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AOPSO Sprint 27 isolation + profile report"
    )
    parser.add_argument("--split-manifest", default=DEFAULT_SPLIT)
    parser.add_argument("--norm-stats", default=DEFAULT_STATS)
    parser.add_argument("--csv-path", default=None)
    parser.add_argument(
        "--nrows",
        type=int,
        default=None,
        help=(
            f"Row limit for the profiler. Falls back to ${NROWS_ENV} or a "
            f"50,000-row safety cap; set ${FULL_CSV_ENV}=1 for the full scan."
        ),
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--skip-profile",
        action="store_true",
        help="Skip the CSV profile pass; emit governance + safety blocks only.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    nrows = _resolve_nrows(args.nrows)
    report = build_report(
        split_manifest=args.split_manifest,
        norm_stats=args.norm_stats,
        csv_path=args.csv_path,
        nrows=nrows,
        run_profile=not args.skip_profile,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")

    status = report["governance"]["governance_status"]
    print(f"governance_status: {status}")
    if report["profile"]:
        mc = report["profile"]["mode_coverage"]
        print(
            f"profile: rows={report['profile']['total_rows']} "
            f"auto={mc['auto']['pct']}% manual={mc['manual']['pct']}% "
            f"other={mc['other']['pct']}% gaps={report['profile']['gap_count']}"
        )
    print(f"report -> {out}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
