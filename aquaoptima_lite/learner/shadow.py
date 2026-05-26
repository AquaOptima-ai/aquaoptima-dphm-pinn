"""Shadow-only pump/combo learning evidence.

Sprint 5 intentionally does not build a learned controller.  It only
collects clean operating samples and publishes confidence/limitation
evidence that the Operations Console can display.  The evidence is never
used to request PLC/PAC writes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Tuple

from ..baseline.interface import DemandTarget
from ..runtime.models import QualityDecision, StationSnapshot


@dataclass(frozen=True)
class LearnerSample:
    timestamp: str
    site_id: str
    combo_key: str
    target_head_m: float
    flow_min_m3h: float
    flow_max_m3h: float
    observed_head_m: float
    total_flow_m3h: float
    total_power_kw: float
    avg_frequency_hz: float
    running_pump_count: int
    specific_energy_kwh_per_m3: float


@dataclass(frozen=True)
class LearnerSampleDecision:
    accepted: bool
    reason_codes: Tuple[str, ...]
    sample: Optional[LearnerSample] = None


@dataclass(frozen=True)
class LearnerSummary:
    accepted_samples: int
    rejected_samples: int
    combo_count: int
    min_samples_for_shadow: int


@dataclass(frozen=True)
class ComboStats:
    combo_key: str
    sample_count: int
    avg_flow_m3h: float
    avg_head_m: float
    avg_power_kw: float
    avg_specific_energy_kwh_per_m3: float


@dataclass(frozen=True)
class LearnerEvidence:
    mode: str
    status: str
    influences_control: bool
    confidence: float
    data_limitations: Tuple[str, ...]
    summary: LearnerSummary
    combo_stats: Mapping[str, ComboStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LearnerSampleCollector:
    """Collect clean pump/combo samples for future learned advisory work."""

    def __init__(self, *, min_samples_for_shadow: int = 10) -> None:
        if min_samples_for_shadow <= 0:
            raise ValueError("min_samples_for_shadow must be positive")
        self.min_samples_for_shadow = int(min_samples_for_shadow)
        self._samples: list[LearnerSample] = []
        self._rejections: list[Tuple[str, ...]] = []

    @property
    def samples(self) -> Tuple[LearnerSample, ...]:
        return tuple(self._samples)

    def collect(
        self,
        snapshot: StationSnapshot,
        quality: QualityDecision,
        demand: DemandTarget,
    ) -> LearnerSampleDecision:
        reasons = list(self._rejection_reasons(snapshot, quality))
        if reasons:
            reason_tuple = tuple(reasons)
            self._rejections.append(reason_tuple)
            return LearnerSampleDecision(accepted=False, reason_codes=reason_tuple)

        running = tuple(p for p in snapshot.pumps if p.running)
        total_power = sum(float(p.power_kw or 0.0) for p in running)
        total_flow = float(snapshot.flow_m3h or 0.0)
        avg_frequency = sum(float(p.frequency_hz or 0.0) for p in running) / len(running)
        specific_energy = total_power / total_flow if total_flow > 0 else 0.0
        combo_key = "+".join(p.pump_id for p in running)
        sample = LearnerSample(
            timestamp=snapshot.timestamp,
            site_id=snapshot.site_id,
            combo_key=combo_key,
            target_head_m=demand.target_head_m,
            flow_min_m3h=demand.flow_min_m3h,
            flow_max_m3h=demand.flow_max_m3h,
            observed_head_m=float(snapshot.head_m or 0.0),
            total_flow_m3h=total_flow,
            total_power_kw=total_power,
            avg_frequency_hz=avg_frequency,
            running_pump_count=len(running),
            specific_energy_kwh_per_m3=specific_energy,
        )
        self._samples.append(sample)
        return LearnerSampleDecision(accepted=True, reason_codes=("sample_accepted",), sample=sample)

    def _rejection_reasons(
        self,
        snapshot: StationSnapshot,
        quality: QualityDecision,
    ) -> Tuple[str, ...]:
        reasons: list[str] = []
        if quality.status != "pass" or quality.blocked_for_learning:
            reasons.append("quality_not_clean")
        if snapshot.manual_mode or not snapshot.auto_mode:
            reasons.append("not_auto_mode")
        if snapshot.head_m is None:
            reasons.append("missing_head")
        if snapshot.flow_m3h is None or snapshot.flow_m3h <= 0:
            reasons.append("missing_or_nonpositive_flow")
        running = tuple(p for p in snapshot.pumps if p.running)
        if not running:
            reasons.append("no_running_pump")
        if any(p.trip_active or p.alarm_active or not p.available for p in snapshot.pumps):
            reasons.append("pump_unavailable_or_faulted")
        if any(p.frequency_hz is None for p in running):
            reasons.append("missing_running_frequency")
        if any(p.power_kw is None or p.power_kw <= 0 for p in running):
            reasons.append("missing_or_nonpositive_power")
        return tuple(dict.fromkeys(reasons))

    def summary(self) -> LearnerSummary:
        combos = {sample.combo_key for sample in self._samples}
        return LearnerSummary(
            accepted_samples=len(self._samples),
            rejected_samples=len(self._rejections),
            combo_count=len(combos),
            min_samples_for_shadow=self.min_samples_for_shadow,
        )

    def combo_stats(self) -> Mapping[str, ComboStats]:
        grouped: dict[str, list[LearnerSample]] = {}
        for sample in self._samples:
            grouped.setdefault(sample.combo_key, []).append(sample)
        stats: dict[str, ComboStats] = {}
        for combo_key, samples in grouped.items():
            count = len(samples)
            stats[combo_key] = ComboStats(
                combo_key=combo_key,
                sample_count=count,
                avg_flow_m3h=sum(s.total_flow_m3h for s in samples) / count,
                avg_head_m=sum(s.observed_head_m for s in samples) / count,
                avg_power_kw=sum(s.total_power_kw for s in samples) / count,
                avg_specific_energy_kwh_per_m3=sum(
                    s.specific_energy_kwh_per_m3 for s in samples
                )
                / count,
            )
        return stats


class LearnerShadowService:
    """Build control-safe learner evidence from collected samples."""

    def __init__(self, collector: LearnerSampleCollector) -> None:
        self.collector = collector

    def build_evidence(self) -> LearnerEvidence:
        summary = self.collector.summary()
        limitations: list[str] = []
        if summary.accepted_samples < summary.min_samples_for_shadow:
            limitations.append("min_samples_not_met")
        if summary.combo_count < 2:
            limitations.append("single_or_no_combo_observed")
        if summary.rejected_samples:
            limitations.append("rejected_samples_present")
        status = "ready_for_shadow_review" if not limitations else "insufficient_data"
        confidence = min(1.0, summary.accepted_samples / summary.min_samples_for_shadow)
        return LearnerEvidence(
            mode="shadow_only",
            status=status,
            influences_control=False,
            confidence=confidence,
            data_limitations=tuple(limitations),
            summary=summary,
            combo_stats=self.collector.combo_stats(),
        )
