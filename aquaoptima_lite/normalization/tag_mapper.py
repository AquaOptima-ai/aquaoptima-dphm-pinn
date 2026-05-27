"""Map legacy/MVP-style raw tags into canonical station fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

LEGACY_PUMP_PREFIXES = {
    "pumpa": "pump_1",
    "pumpb": "pump_2",
    "pumpc": "pump_3",
    "pumpd": "pump_4",
}

LEGACY_STATION_ALIASES = {
    "measured_head": "head_m",
    "head_m": "head_m",
    "measured_flow": "flow_m3h",
    "station_flow_m3h": "flow_m3h",
    "flow_m3h": "flow_m3h",
    "discharge_pressure_bar": "discharge_pressure_bar",
    "system_mode": "system_mode",
    "manual_mode": "manual_mode",
    "auto_mode": "auto_mode",
    "station_manual_mode": "manual_mode",
    "station_auto_mode": "auto_mode",
}

PUMP_FIELD_ALIASES = {
    "on": "running",
    "running": "running",
    "freq": "frequency_hz",
    "frequency_hz": "frequency_hz",
    "flow": "flow_m3h",
    "flow_m3h": "flow_m3h",
    "power_kw": "power_kw",
    "current_a": "current_a",
    "trip": "trip_active",
    "trip_active": "trip_active",
    "alarm": "alarm_active",
    "alarm_active": "alarm_active",
    "efficiency": "efficiency",
}


@dataclass(frozen=True)
class MappedTags:
    station: Mapping[str, Any] = field(default_factory=dict)
    pumps: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "auto", "manual", "running"}
    return bool(value)


def _map_pump_key(key: str) -> tuple[str, str] | None:
    lower = key.lower()
    for prefix, pump_id in LEGACY_PUMP_PREFIXES.items():
        if not lower.startswith(prefix + "_"):
            continue
        suffix = lower[len(prefix) + 1 :]
        field = PUMP_FIELD_ALIASES.get(suffix)
        if field:
            return pump_id, field
    # canonical style: pump_1_frequency_hz etc.
    parts = lower.split("_")
    if len(parts) >= 3 and parts[0] == "pump" and parts[1].isdigit():
        pump_id = f"pump_{parts[1]}"
        suffix = "_".join(parts[2:])
        field = PUMP_FIELD_ALIASES.get(suffix)
        if field:
            return pump_id, field
    return None


def map_tags(raw: Mapping[str, Any]) -> MappedTags:
    station: dict[str, Any] = {}
    pumps: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        lower = str(key).lower()
        if lower == "timestamp":
            station["timestamp"] = value
            continue
        mapped_station = LEGACY_STATION_ALIASES.get(lower)
        if mapped_station:
            station[mapped_station] = value
            continue
        pump_key = _map_pump_key(lower)
        if pump_key is not None:
            pump_id, field = pump_key
            pumps.setdefault(pump_id, {})[field] = value
            continue
    # Infer manual/auto from system_mode if explicit booleans absent.
    mode = str(station.get("system_mode", "")).lower()
    if "manual_mode" not in station and mode:
        station["manual_mode"] = mode == "manual"
    if "auto_mode" not in station and mode:
        station["auto_mode"] = mode == "auto"
    # Normalize explicit booleans that may come as ints/strings.
    for bool_key in ("manual_mode", "auto_mode"):
        if bool_key in station:
            station[bool_key] = _boolish(station[bool_key])
    for pump_fields in pumps.values():
        for bool_key in ("running", "trip_active", "alarm_active"):
            if bool_key in pump_fields:
                pump_fields[bool_key] = _boolish(pump_fields[bool_key])
    return MappedTags(station=station, pumps=pumps)
