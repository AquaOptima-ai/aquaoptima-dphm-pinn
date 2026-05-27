"""Deterministic fallback baseline engine.

Used when the legacy MVP ``PumpController`` cannot be imported (the
canonical pilot import path is brittle: it lives in a separate vendor
package that not every deployment ships).  The fallback keeps every
running pump at its current frequency and proposes the minimum
configured frequency for any pump that is off but available.  It never
escalates speed on its own — the goal is observable, conservative
continuity, not optimisation.
"""

from __future__ import annotations

from typing import Tuple

from ..runtime.models import StationSnapshot
from .interface import (
    BaselineRecommendation,
    DemandTarget,
    PumpSetpoint,
)


class FallbackBaselineEngine:
    """A safe-by-default :class:`BaselineEngine` for unit tests and demos."""

    def __init__(
        self,
        *,
        min_frequency_hz: float = 25.0,
        max_frequency_hz: float = 55.0,
    ) -> None:
        if min_frequency_hz < 0:
            raise ValueError("min_frequency_hz must be >= 0")
        if max_frequency_hz < min_frequency_hz:
            raise ValueError("max_frequency_hz must be >= min_frequency_hz")
        self._min = float(min_frequency_hz)
        self._max = float(max_frequency_hz)

    def _setpoint_for(self, pump_id: str, running: bool, freq: float | None) -> PumpSetpoint:
        if running:
            target = freq if freq is not None else self._min
            target = max(self._min, min(self._max, float(target)))
            return PumpSetpoint(pump_id=pump_id, on=True, target_frequency_hz=target)
        return PumpSetpoint(pump_id=pump_id, on=False, target_frequency_hz=None)

    def recommend(
        self,
        snapshot: StationSnapshot,
        demand: DemandTarget,
    ) -> BaselineRecommendation:
        setpoints: Tuple[PumpSetpoint, ...] = tuple(
            self._setpoint_for(p.pump_id, p.running, p.frequency_hz)
            for p in snapshot.pumps
        )
        # Note: ``demand`` is accepted to honour the BaselineEngine
        # protocol; the fallback intentionally ignores it because it
        # never tries to optimise — it only preserves continuity.
        del demand
        return BaselineRecommendation(
            source="baseline_fallback",
            mode=snapshot.mode,
            pump_setpoints=setpoints,
            reason_codes=("baseline_mvp_unavailable",),
            confidence=0.5,
            write_intent=False,
            future_flag=False,
        )
