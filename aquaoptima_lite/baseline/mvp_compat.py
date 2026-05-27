"""Translate :class:`StationSnapshot` to/from the MVP v1 dict shape.

The legacy MVP ``PumpController`` consumes a dict that looks roughly
like::

    {
        "system_mode": "auto",
        "sensor_data": {
            "measured_head": 42.8,
            "measured_flow": 180.5,
            "pumpa_on": 1,
            "pumpa_freq": 45.0,
            "pumpa_flow": 180.5,
            "pumpa_efficiency": 0.78,
            ...
        },
        "demand_info": {
            "target_head": 40.0,
            "flow_min": 80.0,
            "flow_max": 320.0,
        },
    }

The pumps are identified by suffix: ``pumpa``, ``pumpb``, ``pumpc`` …
The wrapper maps the first pump in :class:`StationSnapshot.pumps` to
``pumpa``, the second to ``pumpb``, etc.  Each pump contributes four
keys to ``sensor_data``: ``_on``, ``_freq``, ``_flow`` and
``_efficiency``.

This module performs no PLC I/O — it is pure data translation.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from ..runtime.models import StationSnapshot
from .interface import (
    BaselineRecommendation,
    DemandTarget,
    PumpSetpoint,
)


_PUMP_SUFFIXES = ("pumpa", "pumpb", "pumpc", "pumpd", "pumpe")


def _system_mode(snapshot: StationSnapshot) -> str:
    """Pick the MVP ``system_mode`` token from a snapshot."""

    if snapshot.manual_mode:
        return "manual"
    if snapshot.auto_mode:
        return "auto"
    return "unknown"


def _pump_efficiency(power_kw: float | None, flow_m3h: float | None) -> float:
    """Crude proxy efficiency for MVP compatibility.

    The legacy MVP code only needs a relative indicator, so we return
    flow/power (m^3 per kWh-second) normalised into ``[0, 1]`` via a
    simple cap.  When inputs are missing we report 0 so the MVP engine
    treats the channel as "no efficiency info".
    """

    if power_kw is None or flow_m3h is None or power_kw <= 0.0:
        return 0.0
    raw = float(flow_m3h) / (float(power_kw) * 60.0)
    if raw < 0.0:
        return 0.0
    if raw > 1.0:
        return 1.0
    return raw


def mvp_input_from_snapshot(
    snapshot: StationSnapshot,
    demand: DemandTarget,
) -> Dict[str, Any]:
    """Build an MVP-shaped input dict from a snapshot and demand target."""

    sensor_data: Dict[str, Any] = {
        "measured_head": snapshot.head_m,
        "measured_flow": snapshot.flow_m3h,
    }

    pump_id_to_suffix: Dict[str, str] = {}
    for index, pump in enumerate(snapshot.pumps):
        if index >= len(_PUMP_SUFFIXES):
            # MVP shape only knows about a handful of pumps; anything
            # beyond what we have a suffix for is ignored at this layer.
            break
        suffix = _PUMP_SUFFIXES[index]
        pump_id_to_suffix[pump.pump_id] = suffix
        sensor_data[f"{suffix}_on"] = 1 if pump.running else 0
        sensor_data[f"{suffix}_freq"] = (
            0.0 if pump.frequency_hz is None else float(pump.frequency_hz)
        )
        sensor_data[f"{suffix}_flow"] = (
            0.0 if pump.flow_m3h is None else float(pump.flow_m3h)
        )
        sensor_data[f"{suffix}_efficiency"] = _pump_efficiency(
            pump.power_kw, pump.flow_m3h
        )

    return {
        "system_mode": _system_mode(snapshot),
        "sensor_data": sensor_data,
        "demand_info": {
            "target_head": demand.target_head_m,
            "flow_min": demand.flow_min_m3h,
            "flow_max": demand.flow_max_m3h,
        },
        "_pump_suffix_map": pump_id_to_suffix,
    }


def _setpoints_from_mvp_output(
    snapshot: StationSnapshot,
    mvp_output: Mapping[str, Any],
) -> Tuple[PumpSetpoint, ...]:
    setpoints = []
    for index, pump in enumerate(snapshot.pumps):
        if index >= len(_PUMP_SUFFIXES):
            break
        suffix = _PUMP_SUFFIXES[index]
        on_key = f"{suffix}_on"
        freq_key = f"{suffix}_freq"
        raw_on = mvp_output.get(on_key)
        raw_freq = mvp_output.get(freq_key)
        on = bool(raw_on) if raw_on is not None else pump.running
        freq = (
            None
            if raw_freq is None
            else float(raw_freq)
        )
        if on and freq is None:
            freq = (
                pump.frequency_hz
                if pump.frequency_hz is not None
                else 0.0
            )
        setpoints.append(
            PumpSetpoint(pump_id=pump.pump_id, on=on, target_frequency_hz=freq)
        )
    return tuple(setpoints)


def recommendation_from_mvp_output(
    snapshot: StationSnapshot,
    mvp_output: Mapping[str, Any],
    *,
    source: str = "baseline_mvp",
) -> BaselineRecommendation:
    """Translate an MVP-shaped output dict into a canonical recommendation."""

    reasons = tuple(str(x) for x in mvp_output.get("reason_codes", ()) or ())
    confidence_raw = mvp_output.get("confidence", 1.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 1.0
    confidence = max(0.0, min(1.0, confidence))
    write_intent = bool(mvp_output.get("write_intent", True))

    return BaselineRecommendation(
        source=source,
        mode=snapshot.mode,
        pump_setpoints=_setpoints_from_mvp_output(snapshot, mvp_output),
        reason_codes=reasons,
        confidence=confidence,
        write_intent=write_intent,
        future_flag=False,
    )
