"""Canonical reason codes for quality and authority gate decisions.

Reason codes are stable strings that flow into audit logs, console
indicators, and downstream learners.  Code that emits a reason MUST use
these constants so the surface stays consistent.
"""

from __future__ import annotations

from enum import Enum


class ReasonCode(str, Enum):
    MANUAL_MODE_ACTIVE = "manual_mode_active"
    AUTO_MODE_REQUIRED = "auto_mode_required"
    PUMP_TRIP_ACTIVE = "pump_trip_active"
    PUMP_ALARM_ACTIVE = "pump_alarm_active"
    MISSING_REQUIRED_TAG = "missing_required_tag"
    MISSING_PRESSURE_OR_HEAD = "missing_pressure_or_head"
    MISSING_PUMP_FREQUENCY = "missing_pump_frequency"
    STALE_REQUIRED_TAG = "stale_required_tag"
    FLOW_MISSING_LEARNING_LIMITED = "flow_missing_learning_limited"
    POWER_MISSING_SAVINGS_UNVERIFIED = "power_missing_savings_unverified"
    SOURCE_NOT_ALLOWED_IN_MODE = "source_not_allowed_in_mode"
    FUTURE_CONTROL_DISABLED = "future_control_disabled"
    FREQUENCY_OUT_OF_BOUNDS = "frequency_out_of_bounds"
    BASELINE_CONTROL_DISABLED = "baseline_control_disabled"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(r.value for r in cls)
