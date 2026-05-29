"""AOPSO Sprint 32 -- Pillar B FROZEN matched-condition envelope gate.

OFFLINE, ADVISORY ONLY. Speed ranges are EVIDENCE, not executable
recommendations. Nothing in this module loads, trains, writes, actuates, or
emits a setpoint.

This module is the analogue of :mod:`aquaoptima.advisory.health_gate` for
Pillar B. It exposes a *frozen, hash-stable, self-contained* set of constants
that govern the Pillar B matched-condition efficiency envelope:

* the matching tolerances over (demand, level, pressure, flow);
* the SE quantiles used to define the conservative efficient envelope;
* the minimum historical support required to produce an advisory;
* the alignment-diagnostic threshold for MVPv1 control-log comparison.

These constants are DECLARED here (in source) BEFORE the locked March-2026
holdout is touched. Sprint 33 will pre-register the SHA-256 of this module's
``frozen_pillar_b_params()`` dict and integrity-check it before running the
holdout. Do not mutate any constant in this file once Sprint 32 has shipped;
re-tune via a new file (e.g. ``efficiency_gate_v2.py``) so the audit trail is
preserved exactly like Pillar A's v1/v2 gate split.

NON-NEGOTIABLE invariants tested in
``tests/advisory/test_sprint32_envelope.py``:

  G1. SE_QUANTILES == (0.10, 0.25) -- the conservative efficient envelope.
  G2. MIN_SUPPORT is a small positive integer (frozen, not data-derived).
  G3. MATCHING_TOLERANCES contains all four context channels with non-negative
      finite tolerances and stable channel order.
  G4. PILLAR == "B", SPRINT == 32, GATE_VERSION starts with "sprint32.".
  G5. ``frozen_pillar_b_params()`` is JSON-serialisable, deterministic, and
      produces the same SHA-256 digest on every call.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #
PILLAR: str = "B"
SPRINT: int = 32
GATE_VERSION: str = "sprint32.envelope.v1"
FROZEN: bool = True

# --------------------------------------------------------------------------- #
# G1. SE quantiles -- conservative efficient envelope
# --------------------------------------------------------------------------- #
# We use 25th- AND 10th-percentile SE within each matched-condition bucket as
# the "efficient envelope". The 25th percentile is the primary conservative
# envelope; the 10th percentile is reported as the aggressive lower bound for
# transparency. Both are FROZEN before any holdout evaluation.
SE_QUANTILES: tuple[float, ...] = (0.10, 0.25)
SE_QUANTILE_PRIMARY: float = 0.25     # used to define the "efficient" sub-bucket
SE_QUANTILE_AGGRESSIVE: float = 0.10  # reported but not used to extract speed

# --------------------------------------------------------------------------- #
# G2. Minimum historical support
# --------------------------------------------------------------------------- #
# A matched-condition bucket must contain at least this many historical
# OperatingPoints to produce an advisory. Below this, the query is REJECTED
# with reason ``"insufficient_support"`` -- we never extrapolate. 30 is the
# smallest sample size at which p25 is materially stable on a univariate
# empirical distribution (the order statistic at rank 7-8 out of 30 has a
# narrower bootstrap SE than at rank 3 out of 10). Chosen BEFORE looking at any
# matched-bucket counts; recorded here to lock the bar.
MIN_SUPPORT: int = 30

# --------------------------------------------------------------------------- #
# G3. Matching tolerances over (demand, level, pressure, flow)
# --------------------------------------------------------------------------- #
# Absolute tolerances per context channel. A historical OperatingPoint is
# considered "matched" to a query iff the per-channel absolute difference is
# within the corresponding tolerance for every required channel. The L_inf
# normalised distance is reported alongside.
#
# These tolerances were picked from engineering judgement on the Yilan site's
# typical operating ranges (see Sprint 27/28 profiler scorecards):
#
#   * demand m^3/h ~ O(10^3) -> tol 50 m^3/h  (~3-5% of typical scale)
#   * level m     ~ O(1-6)   -> tol 0.25 m
#   * pressure m  ~ O(1-3)   -> tol 0.50 m_head
#   * flow m^3/h  ~ O(10^3)  -> tol 50 m^3/h
#
# They are FROZEN: changing any value here must be done in a new file with a
# new GATE_VERSION, never by editing this module.
MATCHING_TOLERANCES: Mapping[str, float] = {
    "mean_demand_m3_per_h": 50.0,
    "mean_level_m":         0.25,
    "mean_pressure_m_head": 0.50,
    "mean_flow_m3_per_h":   50.0,
}

# The canonical channel order for distance computations + scorecard reporting.
MATCHING_CHANNELS: tuple[str, ...] = tuple(MATCHING_TOLERANCES.keys())

# --------------------------------------------------------------------------- #
# G3'. Speed-range "efficient" cutoff
# --------------------------------------------------------------------------- #
# Within a matched-condition bucket, the "efficient" sub-bucket is the subset
# of historical OperatingPoints whose SE is <= the bucket's p25. Their observed
# speeds define the reported efficient speed range. Every speed in the range
# is, by construction, a historically observed 2025 speed (criterion #2 of the
# Sprint 32 gate). The SE cutoff QUANTILE is frozen here -- the bucket-level
# threshold value is derived from each bucket's empirical distribution.
SPEED_RANGE_SE_CUTOFF_QUANTILE: float = SE_QUANTILE_PRIMARY  # = 0.25

# --------------------------------------------------------------------------- #
# G4. MVPv1 alignment diagnostic threshold
# --------------------------------------------------------------------------- #
# Minimum fraction of MVPv1 log rows that must align (timestamp-window match
# + context-signal agreement) with the 2025 OperatingPoints for a comparison
# to be produced at all. Below this, the comparison is REJECTED with reason
# ``"alignment_below_threshold"`` -- we never produce a misaligned comparator.
MVPV1_MIN_OVERLAP_FRACTION: float = 0.80
# Maximum allowed median |delta| between the MVPv1 log's reported demand and
# the matched 2025 OperatingPoint's mean_demand_m3_per_h. A larger median delta
# indicates the logs and 2025 telemetry are not describing the same site state.
MVPV1_MAX_DEMAND_DISAGREEMENT_M3_PER_H: float = 100.0

# --------------------------------------------------------------------------- #
# March-2026 lock (criterion #5)
# --------------------------------------------------------------------------- #
MARCH_USED_FOR_TUNING: bool = False  # locked: this module must declare False.

# --------------------------------------------------------------------------- #
# Frozen-params record + hash
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FrozenPillarBParams:
    """Hash-stable record of the Sprint 32 frozen Pillar B knobs."""
    pillar: str
    sprint: int
    gate_version: str
    se_quantiles: tuple[float, ...]
    se_quantile_primary: float
    se_quantile_aggressive: float
    min_support: int
    matching_tolerances: Mapping[str, float]
    matching_channels: tuple[str, ...]
    speed_range_se_cutoff_quantile: float
    mvpv1_min_overlap_fraction: float
    mvpv1_max_demand_disagreement_m3_per_h: float
    march_used_for_tuning: bool
    frozen: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "pillar": self.pillar,
            "sprint": self.sprint,
            "gate_version": self.gate_version,
            "se_quantiles": list(self.se_quantiles),
            "se_quantile_primary": self.se_quantile_primary,
            "se_quantile_aggressive": self.se_quantile_aggressive,
            "min_support": self.min_support,
            "matching_tolerances": dict(self.matching_tolerances),
            "matching_channels": list(self.matching_channels),
            "speed_range_se_cutoff_quantile": self.speed_range_se_cutoff_quantile,
            "mvpv1_min_overlap_fraction": self.mvpv1_min_overlap_fraction,
            "mvpv1_max_demand_disagreement_m3_per_h":
                self.mvpv1_max_demand_disagreement_m3_per_h,
            "march_used_for_tuning": self.march_used_for_tuning,
            "frozen": self.frozen,
        }


def frozen_pillar_b_params() -> FrozenPillarBParams:
    """Return the FROZEN Pillar B knobs as a hash-stable record.

    Callers MUST NOT mutate the returned record. The same call produces the
    same SHA-256 digest on every interpreter run (see :func:`frozen_params_sha256`).
    """
    return FrozenPillarBParams(
        pillar=PILLAR,
        sprint=SPRINT,
        gate_version=GATE_VERSION,
        se_quantiles=SE_QUANTILES,
        se_quantile_primary=SE_QUANTILE_PRIMARY,
        se_quantile_aggressive=SE_QUANTILE_AGGRESSIVE,
        min_support=MIN_SUPPORT,
        matching_tolerances=dict(MATCHING_TOLERANCES),
        matching_channels=MATCHING_CHANNELS,
        speed_range_se_cutoff_quantile=SPEED_RANGE_SE_CUTOFF_QUANTILE,
        mvpv1_min_overlap_fraction=MVPV1_MIN_OVERLAP_FRACTION,
        mvpv1_max_demand_disagreement_m3_per_h=
            MVPV1_MAX_DEMAND_DISAGREEMENT_M3_PER_H,
        march_used_for_tuning=MARCH_USED_FOR_TUNING,
        frozen=FROZEN,
    )


def frozen_params_canonical_json() -> str:
    """Canonical, sorted-key JSON form of the frozen params (no whitespace)."""
    return json.dumps(
        frozen_pillar_b_params().to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    )


def frozen_params_sha256() -> str:
    """SHA-256 hex digest of :func:`frozen_params_canonical_json`.

    Sprint 33 will pre-register this digest and integrity-check it before the
    March-2026 holdout is touched.
    """
    return hashlib.sha256(frozen_params_canonical_json().encode("utf-8")).hexdigest()


__all__ = [
    "PILLAR",
    "SPRINT",
    "GATE_VERSION",
    "FROZEN",
    "SE_QUANTILES",
    "SE_QUANTILE_PRIMARY",
    "SE_QUANTILE_AGGRESSIVE",
    "MIN_SUPPORT",
    "MATCHING_TOLERANCES",
    "MATCHING_CHANNELS",
    "SPEED_RANGE_SE_CUTOFF_QUANTILE",
    "MVPV1_MIN_OVERLAP_FRACTION",
    "MVPV1_MAX_DEMAND_DISAGREEMENT_M3_PER_H",
    "MARCH_USED_FOR_TUNING",
    "FrozenPillarBParams",
    "frozen_pillar_b_params",
    "frozen_params_canonical_json",
    "frozen_params_sha256",
]
