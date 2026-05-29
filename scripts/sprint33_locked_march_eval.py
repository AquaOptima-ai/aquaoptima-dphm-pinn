#!/usr/bin/env python3
"""AOPSO Sprint 33 -- Pillar B locked-March-2026 OUT-OF-SAMPLE holdout evaluation.

This is the HONEST out-of-sample run.

Workflow
========
1. Record the SHA-256 of ``efficiency_gate.py`` BEFORE any compute begins
   (pre-registration probe).
2. Load the 2025 source CSV and build the 2025 OperatingPoints catalogue
   that backs the FROZEN matched-condition envelope (Sprint 31 SE engine
   with default :class:`EngineConfig`). 2025 is the envelope; March is NEVER
   used to fit.
3. Load the 2026 source CSV, filter to calendar March-2026, and build the
   March OperatingPoints with the SAME Sprint-31 SE engine.
4. Score every March OperatingPoint against the frozen 2025 envelope, build
   the coverage waterfall + kWh opportunity (p25 + p10), and apply the
   Sprint-33 acceptance gate honestly.
5. Re-record the SHA-256 of ``efficiency_gate.py`` AFTER the run and assert
   it equals the pre-recorded value (HARD STOP on drift).
6. Write the scorecard to
   ``data/eval/pillarB/sprint33_locked_march_scorecard.json``.

Hard safety boundary
--------------------
* Offline, advisory-only, counterfactual offline opportunity only.
* No setpoints, no actuation, no live integration, no edge imports, no
  write path.
* ``efficiency_gate.py`` is read-only. The byte-level hash is verified
  before and after the run.
* A FAIL on the locked holdout is an ACCEPTABLE, VALUABLE outcome. The
  script reports the honest verdict and exits 0 (it exits non-zero only on
  a true error: leakage, missing data, runtime fault, frozen-gate
  tampering).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aquaoptima.advisory.locked_march_holdout import (  # noqa: E402
    DEFAULT_SCORECARD_PATH,
    build_sprint33_scorecard,
    efficiency_gate_module_path,
    read_frozen_gate_file_sha256,
    write_scorecard,
)
from aquaoptima.advisory.specific_energy import (  # noqa: E402
    EngineConfig,
    aggregate_operating_points,
    assert_no_march_2026_in_keys,
    compute_intervals,
)
from aquaoptima.dataio.yilan_axis_map import (  # noqa: E402
    CANONICAL_AXIS_TO_COLUMN,
    MODE_AUTO_COLUMN,
    MODE_MANUAL_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_FORMAT,
)
from aquaoptima.dataio.yilan_profiler import (  # noqa: E402
    DEFAULT_CSV_PATH as DEFAULT_2025_CSV_PATH,
    load_frame,
)
from aquaoptima.training.evaluation import (  # noqa: E402
    DEFAULT_MARCH_CSV,
)

EXIT_OK = 0
EXIT_LEAKAGE = 2
EXIT_NO_DATA = 3
EXIT_RUNTIME = 4
EXIT_FROZEN_GATE_TAMPERED = 5

# Default OperatingPoint aggregation window for the holdout: 30 min, matching
# the catalogue exported in Sprint 31 (operating_points_30min_2025.csv).
DEFAULT_WINDOW_MINUTES = 30


def _load_2025_ops_from_csv(path: Path) -> pd.DataFrame:
    """Load the cached 2025 OperatingPoints CSV (Sprint-31 export)."""
    df = pd.read_csv(path)
    return df


def _build_2025_ops_from_source(
    csv_path: Path, *, window_minutes: int
) -> pd.DataFrame:
    """Fallback: re-build 2025 OperatingPoints from source CSV via the SE engine.

    Used when the cached CSV is absent; produces the identical frame to the
    Sprint-31 export.
    """
    df = load_frame(csv_path)
    df = df.dropna(subset=[TIMESTAMP_COLUMN]).copy()
    df = df[df[TIMESTAMP_COLUMN].dt.year == 2025].reset_index(drop=True)
    cfg = EngineConfig()
    intervals = compute_intervals(df, config=cfg)
    ops = aggregate_operating_points(intervals, window_minutes=window_minutes)
    return pd.DataFrame([op.to_dict() for op in ops])


def _load_march_frame_with_modes(
    csv_path: Path, *, nrows: int | None = None
) -> pd.DataFrame:
    """Load the March-2026 frame INCLUDING the auto/manual mode columns.

    The training-side ``_load_march_frame`` only loads the canonical axis
    backing columns; the Sprint-31 SE engine needs the auto/manual columns
    to classify operating mode. This helper mirrors :func:`load_frame`
    (yilan_profiler) but targets the 2026 CSV.
    """
    backing_cols = [c for c in CANONICAL_AXIS_TO_COLUMN.values() if c is not None]
    wanted = [TIMESTAMP_COLUMN, MODE_AUTO_COLUMN, MODE_MANUAL_COLUMN, *backing_cols]
    header = pd.read_csv(csv_path, nrows=0)
    present = [c for c in wanted if c in header.columns]
    if TIMESTAMP_COLUMN not in present:
        raise ValueError(f"March CSV {csv_path} missing required {TIMESTAMP_COLUMN!r}")
    df = pd.read_csv(csv_path, usecols=present, nrows=nrows, low_memory=False)
    df[TIMESTAMP_COLUMN] = pd.to_datetime(
        df[TIMESTAMP_COLUMN], format=TIMESTAMP_FORMAT, errors="coerce"
    )
    df = df.dropna(subset=[TIMESTAMP_COLUMN])
    df = df.sort_values(TIMESTAMP_COLUMN, kind="stable").reset_index(drop=True)
    march = df[(df[TIMESTAMP_COLUMN].dt.year == 2026) & (df[TIMESTAMP_COLUMN].dt.month == 3)]
    march = march.reset_index(drop=True)
    for col in backing_cols:
        if col in march.columns:
            march[col] = pd.to_numeric(march[col], errors="coerce")
    return march


def _build_march_ops(
    march_csv_path: Path, *, window_minutes: int, nrows: int | None = None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run the Sprint-31 SE engine on the March-2026 filtered source CSV.

    Returns ``(ops_df, holdout_window_meta)``.
    """
    df = _load_march_frame_with_modes(march_csv_path, nrows=nrows)
    if df.empty:
        raise RuntimeError(
            f"March-2026 holdout produced 0 rows from {march_csv_path}"
        )
    # Triple-lock that every input row is March-2026 BEFORE we touch the SE
    # engine. (load_march_frame already filters but we re-assert.)
    ts = pd.to_datetime(df[TIMESTAMP_COLUMN])
    if not bool((ts.dt.year == 2026).all() and (ts.dt.month == 3).all()):
        raise RuntimeError(
            "STOP: March CSV loader returned non-March rows; refusing to "
            f"evaluate ({ts.min()}..{ts.max()})"
        )
    # NOTE: the leakage guard inside the SE engine forbids the 2026-03 PREFIX
    # in its inputs (Sprint 31 contract). We want to RUN the engine on
    # March-2026, so we deliberately call the engine's internals here rather
    # than ``build_sprint31_scorecard``.
    cfg = EngineConfig()
    intervals = compute_intervals(df, config=cfg)
    ops = aggregate_operating_points(intervals, window_minutes=window_minutes)
    ops_df = pd.DataFrame([op.to_dict() for op in ops])
    # The window_start values are ISO strings starting with "2026-03".
    if not ops_df.empty:
        keys = ops_df["window_start"].astype(str).tolist()
        # All must start with "2026-03".
        non_march = [k for k in keys if not k.startswith("2026-03")]
        if non_march:
            raise RuntimeError(
                "STOP: SE-engine produced non-March OperatingPoints from a March-"
                f"filtered frame: {non_march[:5]}"
            )
    holdout_window = {
        "csv_path": str(march_csv_path),
        "first_timestamp": str(ts.min()),
        "last_timestamp": str(ts.max()),
        "all_in_2026_03": True,
        "n_rows": int(len(df)),
        "n_operating_points": int(len(ops_df)),
        "window_minutes": int(window_minutes),
    }
    return ops_df, holdout_window


def _load_mvpv1_march_log(path: Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    if not path.exists():
        return None
    return pd.read_csv(path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="AOPSO Sprint 33 -- Pillar B locked-March-2026 holdout eval",
    )
    p.add_argument(
        "--csv-2025",
        default=os.environ.get("YILAN_2025_CSV", str(DEFAULT_2025_CSV_PATH)),
        help="2025 source CSV (used to rebuild the 2025 ops if cache absent).",
    )
    p.add_argument(
        "--csv-2026",
        default=os.environ.get("YILAN_2026_CSV", DEFAULT_MARCH_CSV),
        help="2026 source CSV (March-2026 holdout source).",
    )
    p.add_argument(
        "--cached-2025-ops",
        default=str(_REPO_ROOT / "data/eval/pillarB/operating_points_30min_2025.csv"),
        help="Cached Sprint-31 2025 OperatingPoints CSV (preferred).",
    )
    p.add_argument(
        "--window-minutes", type=int, default=DEFAULT_WINDOW_MINUTES,
        help="OperatingPoint aggregation window (matches Sprint-31 catalogue).",
    )
    p.add_argument(
        "--tariff-per-kwh", type=float, default=None,
        help="OPTIONAL offline tariff per kWh. Without this, kWh-only is reported.",
    )
    p.add_argument(
        "--tariff-source", default=None,
        help="OPTIONAL: human label describing where the tariff came from.",
    )
    p.add_argument(
        "--mvpv1-march-log", default=None,
        help="OPTIONAL: path to an MVPv1 March control log CSV.",
    )
    p.add_argument(
        "--output", default=str(_REPO_ROOT / DEFAULT_SCORECARD_PATH),
        help="Output scorecard JSON path.",
    )
    p.add_argument(
        "--march-nrows", type=int, default=None,
        help="OPTIONAL row cap on the March CSV (debug only).",
    )
    args = p.parse_args(argv)

    # 1. Pre-registration probe: record on-disk frozen-gate hash BEFORE any work.
    frozen_gate_path = efficiency_gate_module_path()
    sha_before = read_frozen_gate_file_sha256()
    print(f"[sprint33] frozen gate file: {frozen_gate_path}")
    print(f"[sprint33] frozen gate sha256 (pre-eval) : {sha_before}")

    # 2. Load 2025 OperatingPoints (cache preferred; otherwise rebuild).
    cached_2025 = Path(args.cached_2025_ops)
    try:
        if cached_2025.exists():
            print(f"[sprint33] loading cached 2025 OperatingPoints: {cached_2025}")
            ops_2025 = _load_2025_ops_from_csv(cached_2025)
        else:
            print(
                f"[sprint33] cached 2025 ops not found; rebuilding from "
                f"{args.csv_2025}"
            )
            ops_2025 = _build_2025_ops_from_source(
                Path(args.csv_2025), window_minutes=int(args.window_minutes)
            )
        if ops_2025.empty:
            print("STOP: 2025 OperatingPoints frame is empty", file=sys.stderr)
            return EXIT_NO_DATA
        # Defensive: assert no 2026-03 keys in the envelope source.
        assert_no_march_2026_in_keys(
            sorted({k[:7] for k in ops_2025["window_start"].astype(str).tolist()})
        )
    except Exception as exc:  # pragma: no cover - hard runtime guard
        print(f"STOP: failed to load 2025 OperatingPoints: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    # 3. Build March-2026 OperatingPoints from the locked source CSV.
    march_csv_path = Path(args.csv_2026)
    if not march_csv_path.exists():
        print(f"STOP: March-2026 CSV not found at {march_csv_path}", file=sys.stderr)
        return EXIT_NO_DATA
    try:
        march_ops, holdout_window = _build_march_ops(
            march_csv_path,
            window_minutes=int(args.window_minutes),
            nrows=args.march_nrows,
        )
    except Exception as exc:
        print(f"STOP: failed to build March-2026 OperatingPoints: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    print(
        f"[sprint33] 2025 envelope ops: {len(ops_2025)}; "
        f"march-2026 ops: {len(march_ops)} (rows={holdout_window['n_rows']})"
    )

    # 4. Load optional MVPv1 March log.
    mvpv1_log_path = Path(args.mvpv1_march_log) if args.mvpv1_march_log else None
    mvpv1_log = _load_mvpv1_march_log(mvpv1_log_path)

    # 5. Build scorecard.
    try:
        scorecard = build_sprint33_scorecard(
            operating_points_2025=ops_2025,
            operating_points_2026_03=march_ops,
            holdout_window=holdout_window,
            march_csv_path=str(march_csv_path),
            operating_points_2025_csv_path=str(cached_2025 if cached_2025.exists() else args.csv_2025),
            tariff_per_kwh=args.tariff_per_kwh,
            tariff_source=args.tariff_source,
            mvpv1_march_log=mvpv1_log,
            frozen_gate_sha256_at_eval=sha_before,
        )
    except ValueError as exc:
        # Leakage guards raise ValueError -- this is a HARD STOP.
        print(f"STOP: leakage guard fired: {exc}", file=sys.stderr)
        return EXIT_LEAKAGE
    except Exception as exc:  # pragma: no cover - hard runtime guard
        print(f"STOP: scorecard build failed: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    # 6. POST-eval integrity probe: frozen-gate file must be byte-identical.
    sha_after = read_frozen_gate_file_sha256()
    if sha_after != sha_before:
        print(
            f"STOP: efficiency_gate.py was modified during evaluation "
            f"(pre={sha_before!r}, post={sha_after!r})",
            file=sys.stderr,
        )
        return EXIT_FROZEN_GATE_TAMPERED
    scorecard["frozen_gate"]["gate_file_sha256_post_eval"] = sha_after
    scorecard["frozen_gate"]["pre_eq_post"] = True

    # 7. Write scorecard.
    out_path = write_scorecard(scorecard, output_path=args.output)
    print(f"[sprint33] scorecard written to {out_path}")
    print(f"[sprint33] verdict: {scorecard['verdict']}")
    print(
        f"[sprint33] coverage: total={scorecard['coverage_waterfall']['total']}, "
        f"supported={scorecard['coverage_waterfall']['supported']}, "
        f"unsupported={scorecard['coverage_waterfall']['unsupported']}"
    )
    print(
        f"[sprint33] opportunity: p25={scorecard['opportunity']['kwh_p25']:.3f} kWh, "
        f"p10={scorecard['opportunity']['kwh_p10']:.3f} kWh, "
        f"robust_under_conservative={scorecard['opportunity']['robust_under_conservative']}"
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
