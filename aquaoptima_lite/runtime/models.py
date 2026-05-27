"""Runtime dataclasses: pump state, station snapshot, decisions, intents.

These types form the immutable record that flows from the data plane
through the quality engine and into the authority gate.  Every dataclass
here is ``frozen=True`` so a snapshot cannot be mutated after the gate
has audited it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Pump and station observation


@dataclass(frozen=True)
class PumpState:
    pump_id: str
    running: bool
    available: bool
    frequency_hz: Optional[float]
    trip_active: bool
    alarm_active: bool
    flow_m3h: Optional[float] = None
    power_kw: Optional[float] = None
    current_a: Optional[float] = None


@dataclass(frozen=True)
class StationSnapshot:
    timestamp: str
    site_id: str
    mode: str
    pumps: Tuple[PumpState, ...]
    discharge_pressure_bar: Optional[float]
    head_m: Optional[float]
    flow_m3h: Optional[float]
    manual_mode: bool
    auto_mode: bool
    quality_flags: Tuple[str, ...]
    config_hash: str


# ---------------------------------------------------------------------------
# Decisions and proposals


@dataclass(frozen=True)
class QualityDecision:
    status: str  # "pass" | "warn" | "block"
    reason_codes: Tuple[str, ...] = field(default_factory=tuple)
    blocked_for_advisory: bool = False
    blocked_for_learning: bool = False
    blocked_for_future_control: bool = False
    confidence_penalty: float = 0.0

    def __post_init__(self) -> None:
        if self.status not in ("pass", "warn", "block"):
            raise ValueError(
                f"QualityDecision.status must be pass|warn|block, got {self.status!r}"
            )


@dataclass(frozen=True)
class ControlIntent:
    """A proposed setpoint from some authority source.

    ``write_requested=False`` means the source is publishing intent for
    observation only (e.g. shadow comparisons); ``True`` means the source
    is asking the authority gate to permit an actual setpoint write.
    """

    source: str  # "baseline_mvp" | "learner" | "console" | "none"
    pump_id: Optional[str] = None
    target_frequency_hz: Optional[float] = None
    confidence: Optional[float] = None
    write_requested: bool = False

    def __post_init__(self) -> None:
        if self.source not in ("baseline_mvp", "learner", "console", "none"):
            raise ValueError(
                f"ControlIntent.source must be baseline_mvp|learner|console|none, "
                f"got {self.source!r}"
            )


@dataclass(frozen=True)
class AuthorityGateDecision:
    decision: str  # "allow" | "block" | "observe_only"
    reason_codes: Tuple[str, ...]
    source: str
    write_allowed: bool

    def __post_init__(self) -> None:
        if self.decision not in ("allow", "block", "observe_only"):
            raise ValueError(
                f"AuthorityGateDecision.decision must be allow|block|observe_only, "
                f"got {self.decision!r}"
            )
        if self.decision == "allow" and not self.write_allowed:
            raise ValueError("AuthorityGateDecision.allow requires write_allowed=True")
        if self.decision != "allow" and self.write_allowed:
            raise ValueError(
                "AuthorityGateDecision.write_allowed=True is only valid with decision=allow"
            )


# ---------------------------------------------------------------------------
# Snapshot deserialization helper


def _pump_from_dict(raw: Mapping[str, Any]) -> PumpState:
    return PumpState(
        pump_id=str(raw["pump_id"]),
        running=bool(raw["running"]),
        available=bool(raw["available"]),
        frequency_hz=(
            None if raw.get("frequency_hz") is None else float(raw["frequency_hz"])
        ),
        trip_active=bool(raw["trip_active"]),
        alarm_active=bool(raw["alarm_active"]),
        flow_m3h=None if raw.get("flow_m3h") is None else float(raw["flow_m3h"]),
        power_kw=None if raw.get("power_kw") is None else float(raw["power_kw"]),
        current_a=None if raw.get("current_a") is None else float(raw["current_a"]),
    )


def snapshot_from_dict(raw: Mapping[str, Any]) -> StationSnapshot:
    """Build a :class:`StationSnapshot` from a JSON-like mapping."""

    required = (
        "timestamp",
        "site_id",
        "mode",
        "pumps",
        "manual_mode",
        "auto_mode",
        "config_hash",
    )
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError(f"snapshot missing required fields: {missing!r}")

    pumps = tuple(_pump_from_dict(p) for p in raw["pumps"])
    return StationSnapshot(
        timestamp=str(raw["timestamp"]),
        site_id=str(raw["site_id"]),
        mode=str(raw["mode"]),
        pumps=pumps,
        discharge_pressure_bar=(
            None
            if raw.get("discharge_pressure_bar") is None
            else float(raw["discharge_pressure_bar"])
        ),
        head_m=None if raw.get("head_m") is None else float(raw["head_m"]),
        flow_m3h=None if raw.get("flow_m3h") is None else float(raw["flow_m3h"]),
        manual_mode=bool(raw["manual_mode"]),
        auto_mode=bool(raw["auto_mode"]),
        quality_flags=tuple(str(x) for x in raw.get("quality_flags", ()) or ()),
        config_hash=str(raw["config_hash"]),
    )
