"""Build StationSnapshot objects from raw replay/ingestion frames."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..config import SiteConfig, compute_config_hash
from ..ingestion.base import RawFrame
from ..runtime import PumpState, StationSnapshot
from .tag_mapper import MappedTags, map_tags
from .units import normalize_unit


@dataclass(frozen=True)
class SnapshotBuilder:
    config: SiteConfig

    @property
    def config_hash(self) -> str:
        return compute_config_hash(self.config)

    def build(self, frame: RawFrame | Mapping[str, Any]) -> StationSnapshot:
        if isinstance(frame, RawFrame):
            timestamp = frame.timestamp
            raw_tags = dict(frame.tags)
        else:
            timestamp = str(frame.get("timestamp", ""))
            raw_tags = dict(frame)
        mapped = map_tags(raw_tags)
        if not timestamp:
            timestamp = str(mapped.station.get("timestamp", ""))
        if not timestamp:
            raise ValueError("snapshot frame missing timestamp")
        return _snapshot_from_mapped(timestamp, self.config, self.config_hash, mapped)


def _station_float(mapped: MappedTags, key: str) -> float | None:
    return normalize_unit(mapped.station.get(key), None)


def _pump_float(fields: Mapping[str, Any], key: str) -> float | None:
    return normalize_unit(fields.get(key), None)


def _snapshot_from_mapped(
    timestamp: str,
    config: SiteConfig,
    config_hash: str,
    mapped: MappedTags,
) -> StationSnapshot:
    pumps: list[PumpState] = []
    for pump_cfg in config.pumps:
        fields = mapped.pumps.get(pump_cfg.pump_id, {})
        running = bool(fields.get("running", False))
        trip = bool(fields.get("trip_active", False))
        alarm = bool(fields.get("alarm_active", False))
        pumps.append(
            PumpState(
                pump_id=pump_cfg.pump_id,
                running=running,
                available=not trip,
                frequency_hz=_pump_float(fields, "frequency_hz"),
                trip_active=trip,
                alarm_active=alarm,
                flow_m3h=_pump_float(fields, "flow_m3h"),
                power_kw=_pump_float(fields, "power_kw"),
                current_a=_pump_float(fields, "current_a"),
            )
        )
    manual_mode = bool(mapped.station.get("manual_mode", False))
    auto_mode = bool(mapped.station.get("auto_mode", not manual_mode))
    return StationSnapshot(
        timestamp=timestamp,
        site_id=config.site_id,
        mode=config.runtime.default_mode,
        pumps=tuple(pumps),
        discharge_pressure_bar=_station_float(mapped, "discharge_pressure_bar"),
        head_m=_station_float(mapped, "head_m"),
        flow_m3h=_station_float(mapped, "flow_m3h"),
        manual_mode=manual_mode,
        auto_mode=auto_mode,
        quality_flags=(),
        config_hash=config_hash,
    )


def build_snapshot(frame: RawFrame | Mapping[str, Any], config: SiteConfig) -> StationSnapshot:
    return SnapshotBuilder(config).build(frame)
