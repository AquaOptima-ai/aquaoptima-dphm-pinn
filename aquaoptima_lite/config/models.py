"""Typed configuration models for Optimizer Lite.

These dataclasses mirror the on-disk YAML configuration for a single
legacy pump station.  They are frozen so that a loaded :class:`SiteConfig`
can be hashed deterministically and treated as immutable runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class RuntimeConfig:
    default_mode: str
    cycle_seconds: float
    stale_after_seconds: float


@dataclass(frozen=True)
class SafetyConfig:
    require_auto_mode: bool
    block_on_any_trip: bool
    block_on_any_alarm: bool
    baseline_control_enabled: bool
    future_control_enabled: bool
    min_frequency_hz: float
    max_frequency_hz: float
    max_step_hz: float
    min_pressure_bar: float
    max_pressure_bar: float
    min_flow_m3h: float
    max_flow_m3h: float
    min_model_confidence_for_advisory: float


@dataclass(frozen=True)
class DataRequirements:
    required: Tuple[str, ...] = field(default_factory=tuple)
    strongly_preferred: Tuple[str, ...] = field(default_factory=tuple)
    optional: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PumpConfig:
    pump_id: str
    display_name: str
    role: str
    min_frequency_hz: float
    max_frequency_hz: float
    rated_power_kw: Optional[float] = None


@dataclass(frozen=True)
class TagConfig:
    canonical: str
    source: str
    address: str
    unit: str
    scale: float = 1.0
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None
    stale_after_seconds: Optional[float] = None
    required: bool = False


@dataclass(frozen=True)
class SiteConfig:
    site_id: str
    site_name: str
    timezone: str
    runtime: RuntimeConfig
    safety: SafetyConfig
    data_requirements: DataRequirements
    pumps: Tuple[PumpConfig, ...]
    tags: Tuple[TagConfig, ...]

    def pump_by_id(self, pump_id: str) -> Optional[PumpConfig]:
        for pump in self.pumps:
            if pump.pump_id == pump_id:
                return pump
        return None

    def tag_by_canonical(self, canonical: str) -> Optional[TagConfig]:
        for tag in self.tags:
            if tag.canonical == canonical:
                return tag
        return None
