"""Shadow-only learned pump/combo performance model.

Sprint 7 keeps the first model deliberately small and explainable:
accepted learner samples are converted into feature rows, then grouped by
pump/combo key and summarized with deterministic averages.  The output is
operator/audit evidence only and always reports ``influences_control=False``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional, Tuple

from .shadow import LearnerSample

READINESS_READY = "ready"
READINESS_INSUFFICIENT_DATA = "insufficient_data"
READINESS_MISSING_REQUIRED_TAGS = "missing_required_tags"
READINESS_INVALID_QUALITY = "invalid_quality"


@dataclass(frozen=True)
class PerformanceFeature:
    timestamp: str
    site_id: str
    combo_key: str
    observed_head_m: float
    total_flow_m3h: float
    total_power_kw: float
    avg_frequency_hz: float
    running_pump_count: int
    specific_energy_kwh_per_m3: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PerformanceFeatureSet:
    readiness: str
    reason_codes: Tuple[str, ...]
    features: Tuple[PerformanceFeature, ...] = field(default_factory=tuple)
    influences_control: bool = False

    @property
    def feature_count(self) -> int:
        return len(self.features)

    def __post_init__(self) -> None:
        object.__setattr__(self, "influences_control", False)
        if self.readiness not in (
            READINESS_READY,
            READINESS_INSUFFICIENT_DATA,
            READINESS_MISSING_REQUIRED_TAGS,
            READINESS_INVALID_QUALITY,
        ):
            raise ValueError(f"unsupported readiness: {self.readiness!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PerformanceModelResult:
    model_id: str
    model_version: str
    readiness: str
    combo_key: Optional[str]
    training_sample_count: int
    confidence: float
    reason_codes: Tuple[str, ...]
    estimated_flow_m3h: Optional[float] = None
    estimated_head_m: Optional[float] = None
    estimated_power_kw: Optional[float] = None
    estimated_specific_energy_kwh_per_m3: Optional[float] = None
    influences_control: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "influences_control", False)
        if self.readiness not in (
            READINESS_READY,
            READINESS_INSUFFICIENT_DATA,
            READINESS_MISSING_REQUIRED_TAGS,
            READINESS_INVALID_QUALITY,
        ):
            raise ValueError(f"unsupported readiness: {self.readiness!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if self.training_sample_count < 0:
            raise ValueError("training_sample_count must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PerformanceFeatureBuilder:
    """Build deterministic model features from accepted learner samples."""

    def from_samples(self, samples: Iterable[LearnerSample]) -> PerformanceFeatureSet:
        features: list[PerformanceFeature] = []
        for sample in samples:
            missing = self._missing_required(sample)
            if missing:
                return PerformanceFeatureSet(
                    readiness=READINESS_MISSING_REQUIRED_TAGS,
                    reason_codes=tuple(missing),
                    features=tuple(features),
                )
            features.append(
                PerformanceFeature(
                    timestamp=sample.timestamp,
                    site_id=sample.site_id,
                    combo_key=sample.combo_key,
                    observed_head_m=float(sample.observed_head_m),
                    total_flow_m3h=float(sample.total_flow_m3h),
                    total_power_kw=float(sample.total_power_kw),
                    avg_frequency_hz=float(sample.avg_frequency_hz),
                    running_pump_count=int(sample.running_pump_count),
                    specific_energy_kwh_per_m3=float(sample.specific_energy_kwh_per_m3),
                )
            )
        if not features:
            return PerformanceFeatureSet(
                readiness=READINESS_INSUFFICIENT_DATA,
                reason_codes=("no_accepted_samples",),
            )
        return PerformanceFeatureSet(
            readiness=READINESS_READY,
            reason_codes=("features_ready",),
            features=tuple(features),
        )

    def _missing_required(self, sample: LearnerSample) -> Tuple[str, ...]:
        missing: list[str] = []
        if not sample.timestamp:
            missing.append("missing_timestamp")
        if not sample.site_id:
            missing.append("missing_site_id")
        if not sample.combo_key:
            missing.append("missing_combo_key")
        if sample.total_flow_m3h <= 0:
            missing.append("missing_required_flow")
        if sample.total_power_kw <= 0:
            missing.append("missing_required_power")
        if sample.running_pump_count <= 0:
            missing.append("missing_running_pump")
        return tuple(missing)


class StatisticalPerformanceModel:
    """Local deterministic per-combo estimator.

    The estimator is intentionally conservative: it returns insufficient
    data until enough accepted samples exist for the requested combo.  It
    uses simple arithmetic means so operators can understand and audit the
    evidence.
    """

    model_id = "local_statistical_performance_v1"
    model_version = "0.1.0"

    def __init__(self, *, min_samples_per_combo: int = 3) -> None:
        if min_samples_per_combo <= 0:
            raise ValueError("min_samples_per_combo must be positive")
        self.min_samples_per_combo = int(min_samples_per_combo)
        self.feature_builder = PerformanceFeatureBuilder()

    def fit_predict(
        self,
        samples: Iterable[LearnerSample],
        *,
        combo_key: Optional[str] = None,
    ) -> PerformanceModelResult:
        feature_set = self.feature_builder.from_samples(samples)
        if feature_set.readiness != READINESS_READY:
            return PerformanceModelResult(
                model_id=self.model_id,
                model_version=self.model_version,
                readiness=feature_set.readiness,
                combo_key=combo_key,
                training_sample_count=feature_set.feature_count,
                confidence=0.0,
                reason_codes=feature_set.reason_codes,
            )

        grouped: dict[str, list[PerformanceFeature]] = {}
        for feature in feature_set.features:
            grouped.setdefault(feature.combo_key, []).append(feature)

        selected_combo = combo_key or sorted(grouped)[0]
        selected = grouped.get(selected_combo, [])
        if not selected:
            return PerformanceModelResult(
                model_id=self.model_id,
                model_version=self.model_version,
                readiness=READINESS_INSUFFICIENT_DATA,
                combo_key=selected_combo,
                training_sample_count=0,
                confidence=0.0,
                reason_codes=("unsupported_combo",),
            )
        if len(selected) < self.min_samples_per_combo:
            return PerformanceModelResult(
                model_id=self.model_id,
                model_version=self.model_version,
                readiness=READINESS_INSUFFICIENT_DATA,
                combo_key=selected_combo,
                training_sample_count=len(selected),
                confidence=min(1.0, len(selected) / self.min_samples_per_combo),
                reason_codes=("too_few_samples",),
            )

        count = len(selected)
        return PerformanceModelResult(
            model_id=self.model_id,
            model_version=self.model_version,
            readiness=READINESS_READY,
            combo_key=selected_combo,
            training_sample_count=count,
            confidence=min(1.0, count / self.min_samples_per_combo),
            reason_codes=("ready",),
            estimated_flow_m3h=self._avg(f.total_flow_m3h for f in selected),
            estimated_head_m=self._avg(f.observed_head_m for f in selected),
            estimated_power_kw=self._avg(f.total_power_kw for f in selected),
            estimated_specific_energy_kwh_per_m3=self._avg(
                f.specific_energy_kwh_per_m3 for f in selected
            ),
        )

    def evaluate(self, samples: Iterable[LearnerSample]) -> PerformanceModelResult:
        materialized = list(samples)
        combo = self._most_observed_combo(materialized)
        return self.fit_predict(materialized, combo_key=combo)

    def _most_observed_combo(self, samples: Iterable[LearnerSample]) -> Optional[str]:
        counts: dict[str, int] = {}
        for sample in samples:
            counts[sample.combo_key] = counts.get(sample.combo_key, 0) + 1
        if not counts:
            return None
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _avg(self, values: Iterable[float]) -> float:
        items = [float(v) for v in values]
        if not items:
            return 0.0
        return sum(items) / len(items)
