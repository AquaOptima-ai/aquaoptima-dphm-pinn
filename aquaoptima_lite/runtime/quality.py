"""Quality engine: rule-based assessment of a :class:`StationSnapshot`.

The quality engine decides whether the current snapshot is healthy
enough for:

- learner training (``blocked_for_learning``)
- console / advisory output (``blocked_for_advisory``)
- the future supervisory-control path (``blocked_for_future_control``)

It does **not** decide who is allowed to write — that is the authority
gate's job.  The quality engine only reports observable issues with the
data and the plant.
"""

from __future__ import annotations

from typing import List

from ..config.models import SiteConfig
from .models import QualityDecision, StationSnapshot
from .reason_codes import ReasonCode


def evaluate_quality(snapshot: StationSnapshot, config: SiteConfig) -> QualityDecision:
    """Return a :class:`QualityDecision` for ``snapshot`` under ``config``."""

    reasons: List[str] = []
    blocked_for_advisory = False
    blocked_for_learning = False
    blocked_for_future_control = False
    confidence_penalty = 0.0

    if snapshot.manual_mode:
        reasons.append(ReasonCode.MANUAL_MODE_ACTIVE.value)
        blocked_for_advisory = True
        blocked_for_future_control = True
        blocked_for_learning = True

    if config.safety.require_auto_mode and not snapshot.auto_mode:
        reasons.append(ReasonCode.AUTO_MODE_REQUIRED.value)
        blocked_for_advisory = True
        blocked_for_future_control = True

    if config.safety.block_on_any_trip and any(p.trip_active for p in snapshot.pumps):
        reasons.append(ReasonCode.PUMP_TRIP_ACTIVE.value)
        blocked_for_advisory = True
        blocked_for_future_control = True
        blocked_for_learning = True

    if config.safety.block_on_any_alarm and any(p.alarm_active for p in snapshot.pumps):
        reasons.append(ReasonCode.PUMP_ALARM_ACTIVE.value)
        blocked_for_advisory = True
        blocked_for_future_control = True

    if snapshot.discharge_pressure_bar is None and snapshot.head_m is None:
        reasons.append(ReasonCode.MISSING_PRESSURE_OR_HEAD.value)
        blocked_for_advisory = True
        blocked_for_future_control = True
        blocked_for_learning = True

    if any(p.running and p.frequency_hz is None for p in snapshot.pumps):
        reasons.append(ReasonCode.MISSING_PUMP_FREQUENCY.value)
        blocked_for_advisory = True
        blocked_for_future_control = True
        blocked_for_learning = True

    if snapshot.flow_m3h is None:
        reasons.append(ReasonCode.FLOW_MISSING_LEARNING_LIMITED.value)
        blocked_for_learning = True
        confidence_penalty += 0.2

    if snapshot.pumps and all(
        p.power_kw is None and p.current_a is None for p in snapshot.pumps
    ):
        reasons.append(ReasonCode.POWER_MISSING_SAVINGS_UNVERIFIED.value)
        confidence_penalty += 0.1

    if blocked_for_advisory or blocked_for_future_control:
        status = "block"
    elif reasons:
        status = "warn"
    else:
        status = "pass"

    if confidence_penalty > 1.0:
        confidence_penalty = 1.0

    return QualityDecision(
        status=status,
        reason_codes=tuple(reasons),
        blocked_for_advisory=blocked_for_advisory,
        blocked_for_learning=blocked_for_learning,
        blocked_for_future_control=blocked_for_future_control,
        confidence_penalty=confidence_penalty,
    )
