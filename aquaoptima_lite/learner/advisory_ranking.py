"""Advisory-only learned pump/combo ranking evidence.

Sprint 8 uses the Sprint 7 shadow performance model to rank observed
pump/combo candidates against the MVP baseline reference.  The output is
operator/audit evidence only: it never mutates ControlIntent and always
reports ``influences_control=False``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional, Tuple

from ..baseline.interface import BaselineRecommendation
from .performance_model import (
    READINESS_INSUFFICIENT_DATA,
    READINESS_READY,
    PerformanceModelResult,
    StatisticalPerformanceModel,
)
from .shadow import LearnerSample


@dataclass(frozen=True)
class AdvisoryCandidate:
    combo_key: str
    rank: int
    readiness: str
    score: float
    confidence: float
    reason_codes: Tuple[str, ...]
    estimated_specific_energy_kwh_per_m3: Optional[float] = None
    estimated_flow_m3h: Optional[float] = None
    estimated_head_m: Optional[float] = None
    estimated_power_kw: Optional[float] = None
    influences_control: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "influences_control", False)
        if self.rank < 1:
            raise ValueError("rank must be positive")
        if self.readiness not in (READINESS_READY, READINESS_INSUFFICIENT_DATA):
            raise ValueError(f"unsupported readiness: {self.readiness!r}")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [0, 1], got {self.score}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdvisoryRankingResult:
    readiness: str
    baseline_combo_key: Optional[str]
    candidates: Tuple[AdvisoryCandidate, ...] = field(default_factory=tuple)
    top_candidate: Optional[AdvisoryCandidate] = None
    baseline_rank: Optional[int] = None
    delta_vs_baseline_specific_energy_kwh_per_m3: Optional[float] = None
    reason_codes: Tuple[str, ...] = field(default_factory=tuple)
    influences_control: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "influences_control", False)
        if self.readiness not in (READINESS_READY, READINESS_INSUFFICIENT_DATA):
            raise ValueError(f"unsupported readiness: {self.readiness!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdvisoryRankingService:
    """Rank learned combo evidence while preserving baseline authority."""

    def __init__(self, *, min_samples_per_combo: int = 3) -> None:
        self.model = StatisticalPerformanceModel(min_samples_per_combo=min_samples_per_combo)

    def rank(
        self,
        samples: Iterable[LearnerSample],
        *,
        baseline: BaselineRecommendation,
    ) -> AdvisoryRankingResult:
        materialized = list(samples)
        baseline_combo = self._baseline_combo_key(baseline)
        combo_keys = sorted({sample.combo_key for sample in materialized if sample.combo_key})
        candidates: list[AdvisoryCandidate] = []
        for combo_key in combo_keys:
            estimate = self.model.fit_predict(materialized, combo_key=combo_key)
            if estimate.readiness != READINESS_READY:
                continue
            candidates.append(self._candidate_from_estimate(estimate))

        if not candidates:
            return AdvisoryRankingResult(
                readiness=READINESS_INSUFFICIENT_DATA,
                baseline_combo_key=baseline_combo,
                reason_codes=("no_ready_candidates",),
            )

        ranked = tuple(
            AdvisoryCandidate(
                combo_key=candidate.combo_key,
                rank=index + 1,
                readiness=candidate.readiness,
                score=candidate.score,
                confidence=candidate.confidence,
                reason_codes=candidate.reason_codes,
                estimated_specific_energy_kwh_per_m3=candidate.estimated_specific_energy_kwh_per_m3,
                estimated_flow_m3h=candidate.estimated_flow_m3h,
                estimated_head_m=candidate.estimated_head_m,
                estimated_power_kw=candidate.estimated_power_kw,
            )
            for index, candidate in enumerate(
                sorted(
                    candidates,
                    key=lambda item: (
                        item.estimated_specific_energy_kwh_per_m3
                        if item.estimated_specific_energy_kwh_per_m3 is not None
                        else float("inf"),
                        item.combo_key,
                    ),
                )
            )
        )
        top = ranked[0]
        baseline_candidate = next((c for c in ranked if c.combo_key == baseline_combo), None)
        reasons = ["advisory_ranking_ready"]
        delta = None
        if baseline_candidate is None:
            reasons.append("baseline_combo_not_ranked")
        else:
            if top.combo_key == baseline_candidate.combo_key:
                reasons.append("top_candidate_matches_baseline")
            else:
                reasons.append("top_candidate_differs_from_baseline")
            if (
                top.estimated_specific_energy_kwh_per_m3 is not None
                and baseline_candidate.estimated_specific_energy_kwh_per_m3 is not None
            ):
                delta = (
                    top.estimated_specific_energy_kwh_per_m3
                    - baseline_candidate.estimated_specific_energy_kwh_per_m3
                )

        return AdvisoryRankingResult(
            readiness=READINESS_READY,
            baseline_combo_key=baseline_combo,
            candidates=ranked,
            top_candidate=top,
            baseline_rank=None if baseline_candidate is None else baseline_candidate.rank,
            delta_vs_baseline_specific_energy_kwh_per_m3=delta,
            reason_codes=tuple(reasons),
        )

    def _candidate_from_estimate(self, estimate: PerformanceModelResult) -> AdvisoryCandidate:
        specific_energy = estimate.estimated_specific_energy_kwh_per_m3
        score = 0.0 if specific_energy is None or specific_energy <= 0 else 1.0 / (1.0 + specific_energy)
        return AdvisoryCandidate(
            combo_key=str(estimate.combo_key),
            rank=1,
            readiness=estimate.readiness,
            score=score,
            confidence=estimate.confidence,
            reason_codes=("lower_specific_energy",),
            estimated_specific_energy_kwh_per_m3=specific_energy,
            estimated_flow_m3h=estimate.estimated_flow_m3h,
            estimated_head_m=estimate.estimated_head_m,
            estimated_power_kw=estimate.estimated_power_kw,
        )

    def _baseline_combo_key(self, baseline: BaselineRecommendation) -> Optional[str]:
        running = tuple(sp.pump_id for sp in baseline.pump_setpoints if sp.on)
        if not running:
            return None
        return "+".join(running)
