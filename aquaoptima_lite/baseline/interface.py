"""Canonical baseline-recommendation contracts.

The baseline subsystem produces a :class:`BaselineRecommendation` per
cycle.  The recommendation is then handed to the authority gate which
decides whether the proposal may be written to the PLC/PAC.  Nothing in
this module performs a write; it defines the data shape only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, Tuple, runtime_checkable

from ..runtime.models import AuthorityGateDecision, StationSnapshot


# ---------------------------------------------------------------------------
# Demand target


@dataclass(frozen=True)
class DemandTarget:
    """Operating set-point envelope handed to the baseline engine.

    Sprint 2's ``SiteConfig`` does not yet carry demand information, so
    until the schema is extended the cycle driver must supply a
    :class:`DemandTarget` (production code reads it from the SCADA
    set-point block; tests and demos use :func:`default_demand_target`).
    """

    target_head_m: float
    flow_min_m3h: float
    flow_max_m3h: float

    def __post_init__(self) -> None:
        if self.flow_min_m3h > self.flow_max_m3h:
            raise ValueError(
                f"DemandTarget.flow_min_m3h ({self.flow_min_m3h}) must be <= "
                f"flow_max_m3h ({self.flow_max_m3h})"
            )
        if self.target_head_m < 0:
            raise ValueError(
                f"DemandTarget.target_head_m must be >= 0, got {self.target_head_m}"
            )


def default_demand_target() -> DemandTarget:
    """Demo defaults that match the legacy_station_001 example config."""

    return DemandTarget(target_head_m=40.0, flow_min_m3h=80.0, flow_max_m3h=320.0)


# ---------------------------------------------------------------------------
# Per-pump setpoint


@dataclass(frozen=True)
class PumpSetpoint:
    pump_id: str
    on: bool
    target_frequency_hz: Optional[float] = None

    def __post_init__(self) -> None:
        if self.on and self.target_frequency_hz is None:
            raise ValueError(
                f"PumpSetpoint(on=True) for {self.pump_id!r} requires a "
                f"target_frequency_hz"
            )


# ---------------------------------------------------------------------------
# Recommendation


@dataclass(frozen=True)
class BaselineRecommendation:
    """A single baseline cycle's output, before the authority gate.

    Attributes:
        source: ``"baseline_mvp"`` for the real wrapper, or
            ``"baseline_fallback"`` when the MVP engine is unavailable.
        mode: The runtime mode observed when the recommendation was
            built (mirrors :class:`StationSnapshot.mode`).
        pump_setpoints: One :class:`PumpSetpoint` per pump on the station.
        reason_codes: Stable reason strings that describe why the engine
            picked these setpoints.
        confidence: Engine self-assessed confidence in ``[0, 1]``.
        write_intent: ``True`` if the engine would *want* to write these
            setpoints to the PLC.  The authority gate may still refuse.
        future_flag: ``True`` if the recommendation targets the future
            supervisory-control path.  Baseline MVP always sets this to
            ``False``; learner sources may set it to ``True``.
        authority_decision: Filled in by the cycle driver after the
            authority gate runs.  ``None`` until then.
    """

    source: str
    mode: str
    pump_setpoints: Tuple[PumpSetpoint, ...]
    reason_codes: Tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 1.0
    write_intent: bool = False
    future_flag: bool = False
    authority_decision: Optional[AuthorityGateDecision] = None

    def __post_init__(self) -> None:
        if self.source not in ("baseline_mvp", "baseline_fallback"):
            raise ValueError(
                f"BaselineRecommendation.source must be baseline_mvp|"
                f"baseline_fallback, got {self.source!r}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"BaselineRecommendation.confidence must be in [0, 1], "
                f"got {self.confidence}"
            )

    def with_authority(self, decision: AuthorityGateDecision) -> "BaselineRecommendation":
        return BaselineRecommendation(
            source=self.source,
            mode=self.mode,
            pump_setpoints=self.pump_setpoints,
            reason_codes=self.reason_codes,
            confidence=self.confidence,
            write_intent=self.write_intent,
            future_flag=self.future_flag,
            authority_decision=decision,
        )


# ---------------------------------------------------------------------------
# Engine protocol


@runtime_checkable
class BaselineEngine(Protocol):
    """Anything that turns a :class:`StationSnapshot` + demand into a rec.

    The wrapper around the legacy MVP ``PumpController`` and the
    :class:`FallbackBaselineEngine` both satisfy this protocol, as do
    any test doubles a unit test cares to inject.
    """

    def recommend(
        self,
        snapshot: StationSnapshot,
        demand: DemandTarget,
    ) -> BaselineRecommendation: ...


# ---------------------------------------------------------------------------
# Raw MVP I/O alias


MvpInput = Mapping[str, Any]
MvpOutput = Mapping[str, Any]
