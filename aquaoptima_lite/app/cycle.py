"""One-cycle orchestration for Optimizer Lite.

Sprint 3 wires the canonical contracts together:
StationSnapshot -> quality -> baseline recommendation -> authority gate -> audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any, Optional

from ..baseline import BaselineEngine, DemandTarget, FallbackBaselineEngine, default_demand_target
from ..config.models import SiteConfig
from ..runtime import ControlIntent, StationSnapshot, evaluate_authority, evaluate_quality
from ..runtime.models import AuthorityGateDecision, QualityDecision
from ..baseline.interface import BaselineRecommendation
from ..storage import SQLiteAuditStore


@dataclass(frozen=True)
class RuntimeCycleResult:
    snapshot: StationSnapshot
    quality: QualityDecision
    recommendation: BaselineRecommendation
    authority: AuthorityGateDecision
    audit_id: int

    def latest_state(self) -> Mapping[str, Any]:
        return {
            "status": {
                "service": "optimizer_lite",
                "healthy": True,
                "has_cycle": True,
                "site_id": self.snapshot.site_id,
                "runtime_mode": self.snapshot.mode,
                "config_hash": self.snapshot.config_hash,
            },
            "snapshot": self.snapshot,
            "quality": self.quality,
            "recommendation": self.recommendation,
        }


class RuntimeCycle:
    def __init__(
        self,
        *,
        config: SiteConfig,
        baseline: Optional[BaselineEngine] = None,
        audit_store: Optional[SQLiteAuditStore] = None,
        demand: Optional[DemandTarget] = None,
    ) -> None:
        self.config = config
        self.baseline = baseline or FallbackBaselineEngine(
            min_frequency_hz=config.safety.min_frequency_hz,
            max_frequency_hz=config.safety.max_frequency_hz,
        )
        self.audit_store = audit_store or SQLiteAuditStore()
        self.demand = demand or default_demand_target()
        self._latest: Optional[RuntimeCycleResult] = None

    def run(self, snapshot: StationSnapshot) -> RuntimeCycleResult:
        quality = evaluate_quality(snapshot, self.config)
        recommendation = self.baseline.recommend(snapshot, self.demand)
        first_setpoint = recommendation.pump_setpoints[0] if recommendation.pump_setpoints else None
        intent = ControlIntent(
            source="baseline_mvp" if recommendation.source == "baseline_mvp" else "none",
            pump_id=None if first_setpoint is None else first_setpoint.pump_id,
            target_frequency_hz=None if first_setpoint is None else first_setpoint.target_frequency_hz,
            confidence=recommendation.confidence,
            write_requested=recommendation.write_intent,
        )
        authority = evaluate_authority(snapshot, quality, intent, self.config)
        recommendation = recommendation.with_authority(authority)
        audit_id = self.audit_store.record_cycle(
            site_id=snapshot.site_id,
            runtime_mode=snapshot.mode,
            config_hash=snapshot.config_hash,
            snapshot=snapshot,
            quality=quality,
            recommendation=recommendation,
            authority=authority,
        )
        self._latest = RuntimeCycleResult(
            snapshot=snapshot,
            quality=quality,
            recommendation=recommendation,
            authority=authority,
            audit_id=audit_id,
        )
        return self._latest

    def latest_state(self) -> Mapping[str, Any]:
        if self._latest is None:
            return {
                "status": {"service": "optimizer_lite", "healthy": True, "has_cycle": False},
                "snapshot": None,
                "quality": None,
                "recommendation": None,
            }
        return self._latest.latest_state()
