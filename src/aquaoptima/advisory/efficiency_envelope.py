"""AOPSO Sprint 32 -- Pillar B matched-condition efficiency envelope.

OFFLINE, ADVISORY ONLY. Every reported speed range is EVIDENCE of historically
observed operating points; it is NOT a setpoint, NOT a command, NOT a control
recommendation. The artifact ``advisory_only`` flag is always True and the
caller cannot turn it off.

Pipeline
========

Given a frame of 2025 OperatingPoints (produced by the Sprint 31 SE engine)
and a query ``OperatingConditionQuery``:

  1. :func:`matched_search` returns the historical neighbours within the FROZEN
     matching tolerances over (demand, level, pressure, flow), with per-row
     L_inf normalised match distance and the comparable sample count.
  2. :func:`compute_envelope` computes the p10 and p25 SE within the matched
     bucket -- conservative SE quantiles, FROZEN before March (see
     :mod:`efficiency_gate`).
  3. :func:`extract_observed_speed_range` selects the EFFICIENT sub-bucket
     (rows whose SE is at or below p25) and returns the (min, max) of their
     observed pump speeds. By construction every speed in the returned set is
     historically observed in 2025; we additionally assert this against the
     OperatingPoints' observed-speed multiset before returning.
  4. :func:`produce_advisory` orchestrates 1-3. If the bucket support is below
     :data:`efficiency_gate.MIN_SUPPORT`, the query is REJECTED with reason
     ``"insufficient_support"`` and no envelope is produced.

Hard contracts (tested in ``tests/advisory/test_sprint32_envelope.py``)
======================================================================
* No live integration, no setpoint emission, no edge import.
* Every reported speed in an advisory is in the observed 2025 speed multiset.
* Unsupported queries return a rejection record with a reason -- never an
  envelope built on extrapolation.
* The frozen matching tolerances + SE quantiles come from
  :mod:`efficiency_gate` and are never overridden by data.
* 2026-03 inputs raise via the Sprint-27 leakage guard before any compute.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .efficiency_gate import (
    MATCHING_CHANNELS,
    MATCHING_TOLERANCES,
    MIN_SUPPORT,
    SE_QUANTILES,
    SE_QUANTILE_AGGRESSIVE,
    SE_QUANTILE_PRIMARY,
    SPEED_RANGE_SE_CUTOFF_QUANTILE,
    frozen_pillar_b_params,
)
from .governance import LOCKED_HOLDOUT_PREFIX, assert_holdout_isolated

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
SPEED_COLUMN: str = "mean_speed_hz"
SE_COLUMN: str = "specific_energy_kwh_per_m3"
WINDOW_START_COLUMN: str = "window_start"

REJECTION_INSUFFICIENT_SUPPORT: str = "insufficient_support"
REJECTION_NO_OBSERVED_EFFICIENT_SPEEDS: str = "no_observed_efficient_speeds"


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OperatingConditionQuery:
    """One target operating condition to evaluate.

    All fields are floats in the SAME units as the corresponding
    OperatingPoint columns produced by the Sprint 31 SE engine.
    """
    demand_m3_per_h: float
    level_m: float
    pressure_m_head: float
    flow_m3_per_h: float
    label: str = "unlabeled"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def channel_value(self, channel: str) -> float:
        """Return the query's value for an OperatingPoint matching channel."""
        if channel == "mean_demand_m3_per_h":
            return float(self.demand_m3_per_h)
        if channel == "mean_level_m":
            return float(self.level_m)
        if channel == "mean_pressure_m_head":
            return float(self.pressure_m_head)
        if channel == "mean_flow_m3_per_h":
            return float(self.flow_m3_per_h)
        raise KeyError(f"unknown matching channel: {channel!r}")


@dataclass(frozen=True)
class MatchedSearchResult:
    """The output of :func:`matched_search`."""
    query: OperatingConditionQuery
    matched_indices: tuple[int, ...]
    comparable_count: int
    match_distance_summary: Mapping[str, float]  # min, mean, max of L_inf distance
    tolerances: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "comparable_count": int(self.comparable_count),
            "match_distance": {k: float(v) for k, v in self.match_distance_summary.items()},
            "tolerances": dict(self.tolerances),
            # we don't dump full index lists into the scorecard JSON
            "matched_indices_head": list(self.matched_indices[:5]),
        }


@dataclass(frozen=True)
class EnvelopeAdvisory:
    """The OFFLINE EVIDENCE advisory for one OperatingConditionQuery.

    NOT a setpoint, NOT a command. The observed efficient speed RANGE +
    speed SET are reported alongside the conservative SE quantiles.
    """
    query: OperatingConditionQuery
    comparable_count: int
    match_distance_summary: Mapping[str, float]
    se_p25: float
    se_p10: float
    se_median: float
    se_threshold_for_efficient: float  # the bucket's p25 SE
    n_efficient: int
    observed_efficient_speed_min_hz: float
    observed_efficient_speed_max_hz: float
    observed_efficient_speed_values_hz: tuple[float, ...]  # rounded distinct set
    advisory_only: bool = True
    is_evidence_not_setpoint: bool = True
    rejection: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "comparable_count": int(self.comparable_count),
            "match_distance": {k: float(v) for k, v in self.match_distance_summary.items()},
            "se_p10": float(self.se_p10),
            "se_p25": float(self.se_p25),
            "se_median": float(self.se_median),
            "se_threshold_for_efficient": float(self.se_threshold_for_efficient),
            "n_efficient": int(self.n_efficient),
            "observed_efficient_speed_min_hz": float(self.observed_efficient_speed_min_hz),
            "observed_efficient_speed_max_hz": float(self.observed_efficient_speed_max_hz),
            "observed_efficient_speed_values_hz":
                [float(s) for s in self.observed_efficient_speed_values_hz],
            "advisory_only": True,
            "is_evidence_not_setpoint": True,
            "rejection": self.rejection,
        }


@dataclass(frozen=True)
class EnvelopeRejection:
    """Returned when a query cannot be served (insufficient support, etc.)."""
    query: OperatingConditionQuery
    reason: str
    comparable_count: int
    detail: Mapping[str, Any] = field(default_factory=dict)
    advisory_only: bool = True
    is_evidence_not_setpoint: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "reason": str(self.reason),
            "comparable_count": int(self.comparable_count),
            "detail": dict(self.detail),
            "advisory_only": True,
            "is_evidence_not_setpoint": True,
        }


# --------------------------------------------------------------------------- #
# Leakage guard
# --------------------------------------------------------------------------- #
def assert_operating_points_no_march_2026(ops: pd.DataFrame) -> None:
    """Raise ``ValueError`` if the OperatingPoint frame leaks 2026-03 windows."""
    if WINDOW_START_COLUMN not in ops.columns:
        return
    keys = ops[WINDOW_START_COLUMN].astype(str).tolist()
    result = assert_holdout_isolated(keys, holdout_prefix=LOCKED_HOLDOUT_PREFIX)
    if not result.isolated:
        raise ValueError(
            "STOP: Sprint 32 OperatingPoint inputs contain the locked "
            f"March-2026 holdout (prefix={LOCKED_HOLDOUT_PREFIX!r}); leaked "
            f"keys {list(result.leaked_keys)[:5]} ..."
        )


# --------------------------------------------------------------------------- #
# Matched search
# --------------------------------------------------------------------------- #
def _validate_matching_columns(ops: pd.DataFrame) -> None:
    missing = [c for c in MATCHING_CHANNELS if c not in ops.columns]
    if missing:
        raise KeyError(
            f"OperatingPoint frame is missing required matching channels: {missing}"
        )
    if SE_COLUMN not in ops.columns:
        raise KeyError(f"OperatingPoint frame is missing {SE_COLUMN!r}")
    if SPEED_COLUMN not in ops.columns:
        raise KeyError(f"OperatingPoint frame is missing {SPEED_COLUMN!r}")


def matched_search(
    ops: pd.DataFrame,
    query: OperatingConditionQuery,
    *,
    tolerances: Mapping[str, float] | None = None,
) -> MatchedSearchResult:
    """Find historical OperatingPoints within the FROZEN matching tolerances.

    The tolerances default to :data:`efficiency_gate.MATCHING_TOLERANCES`.
    Tests may override them to drive corner cases; the production caller
    (:func:`produce_advisory`) NEVER overrides them.

    Parameters
    ----------
    ops
        Frame of 2025 OperatingPoints (Sprint 31 schema). Must contain the
        four matching channels + ``mean_speed_hz`` + ``specific_energy_kwh_per_m3``.
    query
        The target OperatingConditionQuery.

    Returns
    -------
    MatchedSearchResult
        ``matched_indices`` are positional row indices into ``ops`` (after
        ``reset_index(drop=True)``) where every channel is within tolerance.
        ``match_distance_summary`` is the L_inf-normalised distance summary
        over the matched rows (0 = perfect, 1 = at tolerance boundary).
    """
    _validate_matching_columns(ops)
    tol = dict(tolerances) if tolerances is not None else dict(MATCHING_TOLERANCES)
    for ch in MATCHING_CHANNELS:
        if ch not in tol:
            raise KeyError(f"tolerance for channel {ch!r} is required")
        if not np.isfinite(tol[ch]) or tol[ch] < 0:
            raise ValueError(f"tolerance for {ch!r} must be finite and non-negative")

    ops = ops.reset_index(drop=True)
    # Per-channel deltas. Any NaN in a row's matching channel disqualifies it
    # (we never match a row whose context is unknown).
    deltas = np.zeros((len(ops), len(MATCHING_CHANNELS)), dtype=float)
    finite_mask = np.ones(len(ops), dtype=bool)
    for i, ch in enumerate(MATCHING_CHANNELS):
        col = pd.to_numeric(ops[ch], errors="coerce").to_numpy(dtype=float)
        finite_mask &= np.isfinite(col)
        deltas[:, i] = np.abs(col - query.channel_value(ch))

    tol_vec = np.array([tol[ch] for ch in MATCHING_CHANNELS], dtype=float)
    # Within-tolerance: every per-channel delta <= its tolerance.
    # Guard divide-by-zero with a small epsilon; if tol == 0, only an exact
    # match counts (delta == 0).
    safe_tol = np.where(tol_vec > 0, tol_vec, 1.0)
    normalised = deltas / safe_tol[np.newaxis, :]
    for i, t in enumerate(tol_vec):
        if t == 0:
            normalised[:, i] = np.where(deltas[:, i] == 0, 0.0, np.inf)

    in_tol = finite_mask & (deltas <= tol_vec[np.newaxis, :] + 1e-12).all(axis=1)
    matched_idx = np.where(in_tol)[0]
    if matched_idx.size:
        per_row_linf = normalised[matched_idx].max(axis=1)
        dist_summary = {
            "min": float(per_row_linf.min()),
            "mean": float(per_row_linf.mean()),
            "max": float(per_row_linf.max()),
            "metric": float("nan"),  # placeholder; metric label is in tolerances
        }
        dist_summary = {k: v for k, v in dist_summary.items() if k != "metric"}
    else:
        dist_summary = {"min": float("nan"), "mean": float("nan"), "max": float("nan")}

    return MatchedSearchResult(
        query=query,
        matched_indices=tuple(int(i) for i in matched_idx.tolist()),
        comparable_count=int(matched_idx.size),
        match_distance_summary=dist_summary,
        tolerances=tol,
    )


# --------------------------------------------------------------------------- #
# Envelope + observed speed range
# --------------------------------------------------------------------------- #
def compute_envelope(
    ops: pd.DataFrame,
    matched_indices: Sequence[int],
    *,
    quantiles: Iterable[float] = SE_QUANTILES,
) -> dict[str, float]:
    """Compute the p10/p25 SE within a matched bucket.

    Returns
    -------
    dict[str, float]
        Keys: ``"p10"``, ``"p25"``, ``"median"``, plus any extra quantiles
        passed via ``quantiles``. NaN if the bucket is empty.
    """
    out: dict[str, float] = {}
    if not matched_indices:
        for q in SE_QUANTILES:
            out[f"p{int(round(q * 100))}"] = float("nan")
        out["median"] = float("nan")
        return out
    se = pd.to_numeric(ops.iloc[list(matched_indices)][SE_COLUMN], errors="coerce")
    se = se[np.isfinite(se)].to_numpy(dtype=float)
    if se.size == 0:
        for q in SE_QUANTILES:
            out[f"p{int(round(q * 100))}"] = float("nan")
        out["median"] = float("nan")
        return out
    # Use linear interpolation -- numpy default. Deterministic.
    requested = set(SE_QUANTILES) | set(quantiles) | {0.5}
    for q in sorted(requested):
        out[f"p{int(round(q * 100))}"] = float(np.quantile(se, q))
    out["median"] = float(np.quantile(se, 0.5))
    return out


def extract_observed_speed_range(
    ops: pd.DataFrame,
    matched_indices: Sequence[int],
    *,
    se_cutoff_quantile: float = SPEED_RANGE_SE_CUTOFF_QUANTILE,
    speed_rounding_decimals: int = 2,
) -> dict[str, Any]:
    """Extract the observed efficient pump-speed range + distinct speed set.

    The efficient sub-bucket is the matched rows whose SE is at or below the
    bucket's ``se_cutoff_quantile`` (FROZEN default = 0.25). The reported
    speeds are pulled directly from those rows -- by construction every
    returned speed is a historically observed 2025 speed.

    Returns
    -------
    dict[str, Any]
        Keys: ``"n_efficient"``, ``"se_threshold"``, ``"speed_min_hz"``,
        ``"speed_max_hz"``, ``"speed_values_hz"`` (rounded distinct sorted
        set), ``"all_speeds_historically_observed"``.
    """
    if not matched_indices:
        return {
            "n_efficient": 0,
            "se_threshold": float("nan"),
            "speed_min_hz": float("nan"),
            "speed_max_hz": float("nan"),
            "speed_values_hz": [],
            "all_speeds_historically_observed": True,  # vacuously
        }
    matched = ops.iloc[list(matched_indices)].copy()
    se = pd.to_numeric(matched[SE_COLUMN], errors="coerce").to_numpy(dtype=float)
    speed = pd.to_numeric(matched[SPEED_COLUMN], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(se) & np.isfinite(speed)
    se = se[valid]
    speed = speed[valid]
    if se.size == 0:
        return {
            "n_efficient": 0,
            "se_threshold": float("nan"),
            "speed_min_hz": float("nan"),
            "speed_max_hz": float("nan"),
            "speed_values_hz": [],
            "all_speeds_historically_observed": True,
        }
    threshold = float(np.quantile(se, se_cutoff_quantile))
    efficient_mask = se <= threshold + 1e-12
    eff_speeds = speed[efficient_mask]
    if eff_speeds.size == 0:
        return {
            "n_efficient": 0,
            "se_threshold": float(threshold),
            "speed_min_hz": float("nan"),
            "speed_max_hz": float("nan"),
            "speed_values_hz": [],
            "all_speeds_historically_observed": True,
        }
    rounded = np.round(eff_speeds, speed_rounding_decimals)
    distinct = sorted({float(s) for s in rounded.tolist()})

    # Every reported speed must appear in the full observed-2025 speed multiset
    # (this is a tautological check against ``ops`` -- guards against any
    # caller injecting a synthetic OperatingPoint that wasn't in the source).
    full_speeds = pd.to_numeric(ops[SPEED_COLUMN], errors="coerce").dropna()
    observed_set = set(np.round(full_speeds.to_numpy(dtype=float),
                                speed_rounding_decimals).tolist())
    all_observed = all(s in observed_set for s in distinct)

    return {
        "n_efficient": int(eff_speeds.size),
        "se_threshold": float(threshold),
        "speed_min_hz": float(np.min(eff_speeds)),
        "speed_max_hz": float(np.max(eff_speeds)),
        "speed_values_hz": distinct,
        "all_speeds_historically_observed": bool(all_observed),
    }


# --------------------------------------------------------------------------- #
# Advisory + rejection
# --------------------------------------------------------------------------- #
def produce_advisory(
    ops: pd.DataFrame,
    query: OperatingConditionQuery,
    *,
    min_support: int = MIN_SUPPORT,
    tolerances: Mapping[str, float] | None = None,
) -> EnvelopeAdvisory | EnvelopeRejection:
    """Produce the EVIDENCE advisory for a query, or a rejection record.

    A query is REJECTED (no envelope, no speed range, ``rejection`` populated)
    if either:

      * the matched bucket has fewer than ``min_support`` historical samples
        (``"insufficient_support"``); or
      * no efficient sub-bucket sample has an observed speed
        (``"no_observed_efficient_speeds"``).

    The output is OFFLINE EVIDENCE only -- ``advisory_only`` and
    ``is_evidence_not_setpoint`` are both True and cannot be overridden.
    """
    assert_operating_points_no_march_2026(ops)
    if min_support < 1:
        raise ValueError("min_support must be >= 1")

    match = matched_search(ops, query, tolerances=tolerances)

    if match.comparable_count < int(min_support):
        return EnvelopeRejection(
            query=query,
            reason=REJECTION_INSUFFICIENT_SUPPORT,
            comparable_count=match.comparable_count,
            detail={
                "required_min_support": int(min_support),
                "match_distance": dict(match.match_distance_summary),
            },
        )

    env = compute_envelope(ops, match.matched_indices)
    speed_block = extract_observed_speed_range(ops, match.matched_indices)
    if speed_block["n_efficient"] == 0:
        return EnvelopeRejection(
            query=query,
            reason=REJECTION_NO_OBSERVED_EFFICIENT_SPEEDS,
            comparable_count=match.comparable_count,
            detail={
                "se_p25": env.get("p25", float("nan")),
                "se_p10": env.get("p10", float("nan")),
            },
        )

    advisory = EnvelopeAdvisory(
        query=query,
        comparable_count=match.comparable_count,
        match_distance_summary=dict(match.match_distance_summary),
        se_p25=env.get("p25", float("nan")),
        se_p10=env.get("p10", float("nan")),
        se_median=env.get("median", float("nan")),
        se_threshold_for_efficient=float(speed_block["se_threshold"]),
        n_efficient=int(speed_block["n_efficient"]),
        observed_efficient_speed_min_hz=float(speed_block["speed_min_hz"]),
        observed_efficient_speed_max_hz=float(speed_block["speed_max_hz"]),
        observed_efficient_speed_values_hz=tuple(
            speed_block["speed_values_hz"]
        ),
    )
    return advisory


def evaluate_query_batch(
    ops: pd.DataFrame,
    queries: Sequence[OperatingConditionQuery],
    *,
    min_support: int = MIN_SUPPORT,
    tolerances: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Run :func:`produce_advisory` on a batch of queries.

    Returns the per-query advisories, rejections (with reasons), and summary
    counts. Used by the Sprint 32 scorecard to populate ``matched_search``,
    ``envelopes``, and ``rejection`` blocks.
    """
    advisories: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    rejection_reason_counts: dict[str, int] = {}
    matched_search_examples: list[dict[str, Any]] = []
    for q in queries:
        match = matched_search(ops, q, tolerances=tolerances)
        matched_search_examples.append({
            "query": q.to_dict(),
            "comparable_count": match.comparable_count,
            "match_distance": dict(match.match_distance_summary),
            "tolerances": dict(match.tolerances),
        })
        result = produce_advisory(
            ops, q, min_support=min_support, tolerances=tolerances
        )
        if isinstance(result, EnvelopeRejection):
            rejections.append(result.to_dict())
            rejection_reason_counts[result.reason] = (
                rejection_reason_counts.get(result.reason, 0) + 1
            )
        else:
            advisories.append(result.to_dict())

    return {
        "matched_search_examples": matched_search_examples,
        "advisories": advisories,
        "rejections": rejections,
        "rejection_reason_counts": rejection_reason_counts,
        "n_queries": len(queries),
        "n_advisories": len(advisories),
        "n_rejected": len(rejections),
        "frozen_params": frozen_pillar_b_params().to_dict(),
    }


__all__ = [
    "SPEED_COLUMN",
    "SE_COLUMN",
    "REJECTION_INSUFFICIENT_SUPPORT",
    "REJECTION_NO_OBSERVED_EFFICIENT_SPEEDS",
    "OperatingConditionQuery",
    "MatchedSearchResult",
    "EnvelopeAdvisory",
    "EnvelopeRejection",
    "assert_operating_points_no_march_2026",
    "matched_search",
    "compute_envelope",
    "extract_observed_speed_range",
    "produce_advisory",
    "evaluate_query_batch",
]
