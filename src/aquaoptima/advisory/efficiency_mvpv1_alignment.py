"""AOPSO Sprint 32 -- Pillar B MVPv1 control-log alignment diagnostic.

OFFLINE, ADVISORY ONLY. This module never reads control endpoints, never opens
a network connection, and never emits a setpoint. It only diagnoses whether an
offline MVPv1 control log can be SAFELY compared to the 2025 OperatingPoints.

PRD Q5 (docs/product/aopso-health-efficiency-ab/03-prd.md §10.1):

    Q5. How reliable are MVPv1 control logs?
    Risk: Misaligned logs could create false conclusions about advisory value
    versus prior operation.
    Required next step:
      - Build alignment diagnostics.
      - Report comparison only where quality is sufficient.

This file implements those alignment diagnostics. The diagnostic is FROZEN
via :mod:`efficiency_gate` constants
(``MVPV1_MIN_OVERLAP_FRACTION``, ``MVPV1_MAX_DEMAND_DISAGREEMENT_M3_PER_H``).

Contract
========
A valid MVPv1 log is a ``pandas.DataFrame`` with at minimum:

  * ``timestamp``                -- ``pd.Timestamp``, parseable by pandas.
  * ``mvpv1_demand_m3_per_h``    -- float, the demand reported by MVPv1.
  * ``mvpv1_speed_hz``           -- float, the pump speed commanded/observed by MVPv1.

Optional:
  * ``mvpv1_specific_energy_kwh_per_m3`` -- float, MVPv1 SE if available.

Alignment criteria
==================
A log row is ALIGNED to a 2025 OperatingPoint iff:

  1. Its timestamp falls inside the OperatingPoint's [window_start, window_end).
  2. |mvpv1_demand - op.mean_demand_m3_per_h| <= MVPV1_MAX_DEMAND_DISAGREEMENT.

The overall log is COMPARABLE iff the fraction of aligned rows is at least
``MVPV1_MIN_OVERLAP_FRACTION``. Otherwise the comparison is REJECTED with
reason ``"alignment_below_threshold"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .efficiency_gate import (
    MVPV1_MAX_DEMAND_DISAGREEMENT_M3_PER_H,
    MVPV1_MIN_OVERLAP_FRACTION,
)

# --------------------------------------------------------------------------- #
# Column conventions
# --------------------------------------------------------------------------- #
MVPV1_TIMESTAMP_COLUMN: str = "timestamp"
MVPV1_DEMAND_COLUMN: str = "mvpv1_demand_m3_per_h"
MVPV1_SPEED_COLUMN: str = "mvpv1_speed_hz"
MVPV1_SE_COLUMN: str = "mvpv1_specific_energy_kwh_per_m3"

OP_WINDOW_START_COLUMN: str = "window_start"
OP_WINDOW_END_COLUMN: str = "window_end"
OP_DEMAND_COLUMN: str = "mean_demand_m3_per_h"

ALIGNMENT_REJECTION_NO_LOG: str = "no_mvpv1_log_provided"
ALIGNMENT_REJECTION_BELOW_THRESHOLD: str = "alignment_below_threshold"
ALIGNMENT_REJECTION_EMPTY_LOG: str = "empty_mvpv1_log"
ALIGNMENT_REJECTION_MISSING_COLUMNS: str = "mvpv1_log_missing_required_columns"


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MvpV1AlignmentReport:
    """Result of aligning an MVPv1 control log to the 2025 OperatingPoints."""
    n_log_rows: int
    n_aligned: int
    n_rejected: int
    coverage: float                         # n_aligned / n_log_rows
    median_demand_disagreement: float        # median |mvpv1_demand - op_demand|
    diagnostic_passed: bool
    rejection_reason: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_log_rows": int(self.n_log_rows),
            "n_aligned": int(self.n_aligned),
            "n_rejected": int(self.n_rejected),
            "coverage": float(self.coverage),
            "median_demand_disagreement": float(self.median_demand_disagreement),
            "diagnostic_passed": bool(self.diagnostic_passed),
            "rejection_reason": self.rejection_reason,
            "detail": dict(self.detail),
        }


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
REQUIRED_LOG_COLUMNS: tuple[str, ...] = (
    MVPV1_TIMESTAMP_COLUMN,
    MVPV1_DEMAND_COLUMN,
    MVPV1_SPEED_COLUMN,
)


def _empty_report(
    *,
    n_log_rows: int,
    reason: str,
    detail: Mapping[str, Any] | None = None,
) -> MvpV1AlignmentReport:
    return MvpV1AlignmentReport(
        n_log_rows=int(n_log_rows),
        n_aligned=0,
        n_rejected=int(n_log_rows),
        coverage=0.0,
        median_demand_disagreement=float("nan"),
        diagnostic_passed=False,
        rejection_reason=reason,
        detail=dict(detail or {}),
    )


def diagnose_mvpv1_alignment(
    mvpv1_log: pd.DataFrame | None,
    operating_points: pd.DataFrame,
    *,
    min_overlap_fraction: float = MVPV1_MIN_OVERLAP_FRACTION,
    max_demand_disagreement: float = MVPV1_MAX_DEMAND_DISAGREEMENT_M3_PER_H,
) -> MvpV1AlignmentReport:
    """Diagnose how well an MVPv1 control log aligns to the 2025 OperatingPoints.

    The diagnostic PASSES iff:

      ``coverage = n_aligned / n_log_rows >= min_overlap_fraction``  AND
      ``median(|mvpv1_demand - op.demand|) <= max_demand_disagreement``  on aligned rows.

    A row is aligned iff its timestamp falls within at least one OperatingPoint
    window AND the absolute demand disagreement is within tolerance.

    Parameters
    ----------
    mvpv1_log
        The MVPv1 control log (offline file). If ``None`` or empty, the report
        is automatically REJECTED with the appropriate reason and a comparison
        will not be produced -- this is the safe default for Q5.
    operating_points
        The 2025 OperatingPoints frame (Sprint 31 output).
    min_overlap_fraction, max_demand_disagreement
        FROZEN thresholds from :mod:`efficiency_gate`. Override only in tests.

    Returns
    -------
    MvpV1AlignmentReport
    """
    if mvpv1_log is None:
        return _empty_report(n_log_rows=0, reason=ALIGNMENT_REJECTION_NO_LOG)
    if not isinstance(mvpv1_log, pd.DataFrame):
        raise TypeError("mvpv1_log must be a pandas DataFrame or None")

    if len(mvpv1_log) == 0:
        return _empty_report(n_log_rows=0, reason=ALIGNMENT_REJECTION_EMPTY_LOG)

    missing = [c for c in REQUIRED_LOG_COLUMNS if c not in mvpv1_log.columns]
    if missing:
        return _empty_report(
            n_log_rows=len(mvpv1_log),
            reason=ALIGNMENT_REJECTION_MISSING_COLUMNS,
            detail={"missing_columns": missing},
        )

    if (
        OP_WINDOW_START_COLUMN not in operating_points.columns
        or OP_WINDOW_END_COLUMN not in operating_points.columns
        or OP_DEMAND_COLUMN not in operating_points.columns
    ):
        raise KeyError(
            "operating_points frame must contain window_start, window_end, "
            "and mean_demand_m3_per_h columns"
        )

    log = mvpv1_log.copy()
    log[MVPV1_TIMESTAMP_COLUMN] = pd.to_datetime(
        log[MVPV1_TIMESTAMP_COLUMN], errors="coerce"
    )
    # Drop rows with unparseable timestamps -- they cannot be aligned.
    n_unparseable = int(log[MVPV1_TIMESTAMP_COLUMN].isna().sum())
    log = log.dropna(subset=[MVPV1_TIMESTAMP_COLUMN])

    ops = operating_points.copy().reset_index(drop=True)
    ops[OP_WINDOW_START_COLUMN] = pd.to_datetime(
        ops[OP_WINDOW_START_COLUMN], errors="coerce"
    )
    ops[OP_WINDOW_END_COLUMN] = pd.to_datetime(
        ops[OP_WINDOW_END_COLUMN], errors="coerce"
    )
    ops = ops.dropna(subset=[OP_WINDOW_START_COLUMN, OP_WINDOW_END_COLUMN])
    ops = ops.sort_values(OP_WINDOW_START_COLUMN, kind="stable").reset_index(drop=True)

    # Vectorised alignment: for each log row, find the OperatingPoint whose
    # window contains its timestamp via ``searchsorted`` on window_start.
    log_ts = log[MVPV1_TIMESTAMP_COLUMN].to_numpy()
    op_starts = ops[OP_WINDOW_START_COLUMN].to_numpy()
    op_ends = ops[OP_WINDOW_END_COLUMN].to_numpy()
    op_demands = pd.to_numeric(ops[OP_DEMAND_COLUMN], errors="coerce").to_numpy(dtype=float)

    # searchsorted with side="right" gives the insertion index; the candidate
    # window is at index-1.
    insert = np.searchsorted(op_starts, log_ts, side="right") - 1
    valid_idx = (insert >= 0) & (insert < len(ops))
    candidates = np.where(valid_idx, insert, 0)
    in_window = (
        valid_idx
        & (log_ts >= op_starts[candidates])
        & (log_ts < op_ends[candidates])
    )

    log_demand = pd.to_numeric(log[MVPV1_DEMAND_COLUMN], errors="coerce").to_numpy(
        dtype=float
    )
    op_demand_per_row = op_demands[candidates]
    demand_delta = np.abs(log_demand - op_demand_per_row)
    demand_ok = np.isfinite(log_demand) & np.isfinite(op_demand_per_row) & (
        demand_delta <= float(max_demand_disagreement)
    )

    aligned = in_window & demand_ok

    n_log_rows = int(len(log))
    n_aligned = int(aligned.sum())
    n_rejected = int(n_log_rows - n_aligned)
    coverage = float(n_aligned / n_log_rows) if n_log_rows > 0 else 0.0

    aligned_deltas = demand_delta[aligned & np.isfinite(demand_delta)]
    median_disagreement = (
        float(np.median(aligned_deltas)) if aligned_deltas.size else float("nan")
    )

    coverage_ok = coverage >= float(min_overlap_fraction)
    # If we have no aligned rows the median is NaN; treat that as a fail.
    disagreement_ok = (
        np.isfinite(median_disagreement)
        and median_disagreement <= float(max_demand_disagreement)
    )
    diagnostic_passed = bool(coverage_ok and disagreement_ok)

    rejection_reason: str | None = None
    if not diagnostic_passed:
        rejection_reason = ALIGNMENT_REJECTION_BELOW_THRESHOLD

    detail: dict[str, Any] = {
        "min_overlap_fraction": float(min_overlap_fraction),
        "max_demand_disagreement_m3_per_h": float(max_demand_disagreement),
        "coverage_ok": bool(coverage_ok),
        "disagreement_ok": bool(disagreement_ok),
        "n_unparseable_timestamps": int(n_unparseable),
        "n_in_window": int(in_window.sum()),
    }

    return MvpV1AlignmentReport(
        n_log_rows=n_log_rows,
        n_aligned=n_aligned,
        n_rejected=n_rejected,
        coverage=coverage,
        median_demand_disagreement=median_disagreement,
        diagnostic_passed=diagnostic_passed,
        rejection_reason=rejection_reason,
        detail=detail,
    )


__all__ = [
    "MVPV1_TIMESTAMP_COLUMN",
    "MVPV1_DEMAND_COLUMN",
    "MVPV1_SPEED_COLUMN",
    "MVPV1_SE_COLUMN",
    "REQUIRED_LOG_COLUMNS",
    "ALIGNMENT_REJECTION_NO_LOG",
    "ALIGNMENT_REJECTION_BELOW_THRESHOLD",
    "ALIGNMENT_REJECTION_EMPTY_LOG",
    "ALIGNMENT_REJECTION_MISSING_COLUMNS",
    "MvpV1AlignmentReport",
    "diagnose_mvpv1_alignment",
]
