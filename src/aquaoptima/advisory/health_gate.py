"""Sprint 29 evaluation harness + FROZEN acceptance gate.

Compares the Sprint-29 learned detector
(:class:`aquaoptima.advisory.health_detector.FittedHealthDetector`) against the
Sprint-28 interpretable baseline suite
(:class:`aquaoptima.advisory.health_baselines.HealthBaselineSuite`) on a
synthetic injected-fault evaluation set produced by
:func:`aquaoptima.advisory.injected_faults.inject_faults`.

The acceptance rule is **FROZEN before evaluation**. It is intentionally written
to make a FAIL verdict the default outcome whenever the learned model fails to
clear the bar. We do NOT adjust this rule based on what the detector happens to
score; the rule is part of the sprint deliverable, the metrics are not.

Frozen rule (all three sub-clauses MUST hold for ``verdict == 'PASS'``):

    R1.  detector_auroc >= baseline_auroc + 0.02
    R2.  detector_false_alarm_rate <= baseline_false_alarm_rate
    R3.  detector_auroc >= 0.70

If governance reports FAIL, ``apply_governance_to_verdict`` forces the verdict
to FAIL regardless of metrics (the Sprint-27 contract).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .health_baselines import HealthBaselineSuite
from .health_detector import FittedHealthDetector
from .injected_faults import FaultEpisode, InjectedFaultResult


# --------------------------------------------------------------------------- #
# Frozen gate constants -- DO NOT MUTATE BASED ON EVALUATION OUTCOMES
# --------------------------------------------------------------------------- #
FROZEN_AUROC_MARGIN = 0.02
FROZEN_DETECTOR_MIN_AUROC = 0.70
FROZEN_GATE_RULE_TEXT = (
    "detector_auroc >= baseline_auroc + 0.02 "
    "AND detector_false_alarm_rate <= baseline_false_alarm_rate "
    "AND detector_auroc >= 0.70"
)


# --------------------------------------------------------------------------- #
# Metric helpers
# --------------------------------------------------------------------------- #
def _auroc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Pure-numpy AUROC via the Mann-Whitney U statistic.

    Returns 0.5 if either class is empty (so a degenerate eval set never
    fabricates a passing AUROC for either detector).
    """
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    pos = scores[labels == 1]
    neg = scores[labels == 0]
    n_pos = pos.size
    n_neg = neg.size
    if n_pos == 0 or n_neg == 0:
        return 0.5
    # Rank-based U statistic: ranks of pos minus min-rank correction.
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(scores.size, dtype=np.float64)
    ranks[order] = np.arange(1, scores.size + 1, dtype=np.float64)
    # Handle ties by averaging ranks within tied groups.
    if scores.size > 1:
        sorted_scores = scores[order]
        i = 0
        while i < sorted_scores.size:
            j = i
            while j + 1 < sorted_scores.size and sorted_scores[j + 1] == sorted_scores[i]:
                j += 1
            if j > i:
                mean_rank = float(np.mean(ranks[order[i : j + 1]]))
                ranks[order[i : j + 1]] = mean_rank
            i = j + 1
    sum_ranks_pos = float(np.sum(ranks[labels == 1]))
    u = sum_ranks_pos - n_pos * (n_pos + 1) / 2.0
    return float(u / (n_pos * n_neg))


def _first_alarm_after(
    flags: np.ndarray, onset: int, end: int
) -> int | None:
    """Return the index of the first ``flag == 1`` within ``[onset, end)`` or None."""
    seg = flags[onset:end]
    hits = np.where(seg == 1)[0]
    if hits.size == 0:
        return None
    return int(onset + int(hits[0]))


def _per_episode_lead_times(
    flags: np.ndarray, episodes: Sequence[FaultEpisode]
) -> dict[str, Any]:
    """Compute per-episode and per-kind detection lead-time stats.

    Lead time = (first-alarm-index) - onset_index, in row steps. Episodes never
    detected are reported as ``misses``; mean lead-time is computed over detected
    episodes only.
    """
    per_episode: list[dict[str, Any]] = []
    per_kind: dict[str, list[int]] = {}
    misses_per_kind: dict[str, int] = {}
    for ep in episodes:
        first = _first_alarm_after(flags, ep.onset_index, ep.end_index)
        if first is None:
            per_episode.append({
                "kind": ep.kind,
                "axis": ep.axis,
                "onset_index": int(ep.onset_index),
                "detected": False,
                "lead_time": None,
            })
            misses_per_kind[ep.kind] = misses_per_kind.get(ep.kind, 0) + 1
        else:
            lt = int(first - ep.onset_index)
            per_episode.append({
                "kind": ep.kind,
                "axis": ep.axis,
                "onset_index": int(ep.onset_index),
                "detected": True,
                "lead_time": lt,
            })
            per_kind.setdefault(ep.kind, []).append(lt)
    detected = [r for r in per_episode if r["detected"]]
    mean_lt = float(np.mean([r["lead_time"] for r in detected])) if detected else float("nan")
    return {
        "n_episodes": len(episodes),
        "n_detected": int(len(detected)),
        "n_missed": int(len(episodes) - len(detected)),
        "mean_lead_time": mean_lt,
        "per_kind_mean_lead_time": {
            k: float(np.mean(v)) for k, v in per_kind.items()
        },
        "per_kind_misses": dict(misses_per_kind),
        "per_episode": per_episode,
    }


def _false_alarm_rate(flags: np.ndarray, labels: np.ndarray) -> float:
    """Fraction of normal (label==0) rows that were flagged."""
    flags = np.asarray(flags, dtype=np.int64)
    labels = np.asarray(labels, dtype=np.int64)
    normal_mask = labels == 0
    if not normal_mask.any():
        return 0.0
    return float(flags[normal_mask].mean())


# --------------------------------------------------------------------------- #
# Public evaluation
# --------------------------------------------------------------------------- #
def evaluate_detector_vs_baseline(
    *,
    detector: FittedHealthDetector,
    baseline_suite: HealthBaselineSuite,
    injected: InjectedFaultResult,
    detector_score_column: str = "detector_anomaly_score",
    detector_flag_column: str = "detector_flag",
    baseline_score_column: str = "combined_deviation",
    baseline_flag_column: str = "anomaly_flag",
) -> dict[str, Any]:
    """Score both the learned detector and the interpretable baseline on the
    injected-fault set and report AUROC, mean lead-time, and false-alarm rate.
    """
    frames = injected.frames
    labels = np.asarray(injected.labels, dtype=np.int64)
    if frames.shape[0] != labels.shape[0]:
        raise ValueError(
            f"frames/labels length mismatch: {frames.shape[0]} vs {labels.shape[0]}"
        )

    detector_scored = detector.score(frames)
    baseline_scored = baseline_suite.score(frames)

    detector_score = detector_scored[detector_score_column].to_numpy(dtype=float)
    detector_flag = detector_scored[detector_flag_column].to_numpy(dtype=int)
    baseline_score = baseline_scored[baseline_score_column].to_numpy(dtype=float)
    baseline_flag = baseline_scored[baseline_flag_column].to_numpy(dtype=int)

    detector_auroc = _auroc(detector_score, labels)
    baseline_auroc = _auroc(baseline_score, labels)

    detector_far = _false_alarm_rate(detector_flag, labels)
    baseline_far = _false_alarm_rate(baseline_flag, labels)

    detector_lead = _per_episode_lead_times(detector_flag, injected.episodes)
    baseline_lead = _per_episode_lead_times(baseline_flag, injected.episodes)

    return {
        "n_rows": int(frames.shape[0]),
        "n_positive": int(labels.sum()),
        "n_negative": int((labels == 0).sum()),
        "n_episodes": int(len(injected.episodes)),
        "detector": {
            "auroc": float(detector_auroc),
            "false_alarm_rate": float(detector_far),
            "mean_lead_time": float(detector_lead["mean_lead_time"]),
            "lead_time_summary": detector_lead,
            "score_column": detector_score_column,
            "flag_column": detector_flag_column,
        },
        "baseline": {
            "auroc": float(baseline_auroc),
            "false_alarm_rate": float(baseline_far),
            "mean_lead_time": float(baseline_lead["mean_lead_time"]),
            "lead_time_summary": baseline_lead,
            "score_column": baseline_score_column,
            "flag_column": baseline_flag_column,
        },
        "delta": {
            "auroc": float(detector_auroc - baseline_auroc),
            "false_alarm_rate": float(detector_far - baseline_far),
        },
    }


# --------------------------------------------------------------------------- #
# Frozen acceptance gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HealthAcceptanceCriterion:
    name: str
    passed: bool
    detail: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": bool(self.passed),
            "detail": {k: float(v) for k, v in self.detail.items()},
        }


def health_acceptance_gate(
    eval_dict: Mapping[str, Any],
    *,
    auroc_margin: float = FROZEN_AUROC_MARGIN,
    min_detector_auroc: float = FROZEN_DETECTOR_MIN_AUROC,
) -> dict[str, Any]:
    """Apply the FROZEN gate rule to an evaluation dict.

    The rule is fixed by sprint deliverable (:data:`FROZEN_GATE_RULE_TEXT`):

      R1. detector_auroc >= baseline_auroc + auroc_margin (default 0.02)
      R2. detector_false_alarm_rate <= baseline_false_alarm_rate
      R3. detector_auroc >= min_detector_auroc (default 0.70)

    The default arguments are exposed for tests only -- the production script
    uses the frozen defaults. Returns a dict shaped like the existing scorecard
    acceptance gate so :func:`apply_governance_to_verdict` slots in unchanged.
    """
    detector = eval_dict.get("detector", {})
    baseline = eval_dict.get("baseline", {})

    d_auroc = float(detector.get("auroc", 0.0))
    b_auroc = float(baseline.get("auroc", 0.0))
    d_far = float(detector.get("false_alarm_rate", 1.0))
    b_far = float(baseline.get("false_alarm_rate", 1.0))

    criteria: list[HealthAcceptanceCriterion] = [
        HealthAcceptanceCriterion(
            name="detector_auroc_beats_baseline_by_margin",
            passed=d_auroc >= b_auroc + float(auroc_margin),
            detail={
                "detector_auroc": d_auroc,
                "baseline_auroc": b_auroc,
                "required_margin": float(auroc_margin),
                "delta": d_auroc - b_auroc,
            },
        ),
        HealthAcceptanceCriterion(
            name="detector_false_alarm_at_or_below_baseline",
            passed=d_far <= b_far,
            detail={
                "detector_false_alarm_rate": d_far,
                "baseline_false_alarm_rate": b_far,
                "delta": d_far - b_far,
            },
        ),
        HealthAcceptanceCriterion(
            name="detector_auroc_minimum",
            passed=d_auroc >= float(min_detector_auroc),
            detail={
                "detector_auroc": d_auroc,
                "required_minimum": float(min_detector_auroc),
            },
        ),
    ]
    all_passed = all(c.passed for c in criteria)
    return {
        "verdict": "PASS" if all_passed else "FAIL",
        "passed": bool(all_passed),
        "rule": FROZEN_GATE_RULE_TEXT,
        "rule_parameters": {
            "auroc_margin": float(auroc_margin),
            "min_detector_auroc": float(min_detector_auroc),
        },
        "criteria": [c.to_dict() for c in criteria],
        "metrics": {
            "detector_auroc": d_auroc,
            "baseline_auroc": b_auroc,
            "detector_false_alarm_rate": d_far,
            "baseline_false_alarm_rate": b_far,
            "detector_mean_lead_time": float(detector.get("mean_lead_time", float("nan"))),
            "baseline_mean_lead_time": float(baseline.get("mean_lead_time", float("nan"))),
        },
    }


__all__ = [
    "FROZEN_AUROC_MARGIN",
    "FROZEN_DETECTOR_MIN_AUROC",
    "FROZEN_GATE_RULE_TEXT",
    "HealthAcceptanceCriterion",
    "evaluate_detector_vs_baseline",
    "health_acceptance_gate",
]
