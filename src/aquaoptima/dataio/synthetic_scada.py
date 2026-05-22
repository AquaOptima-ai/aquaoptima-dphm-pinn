"""Deprecated module path — kept for backward compatibility.

The implementation moved to :mod:`aquaoptima.dataio.telemetry` as part
of the Sprint 4.5 telemetry-abstraction work. SCADA is treated as one
of several possible telemetry sources (PLC, PAC, historian, CSV, MQTT,
SCADA) so the canonical names are ``TelemetrySeries`` and
``generate_synthetic_telemetry``.

Existing call sites importing from ``aquaoptima.dataio.synthetic_scada``
continue to work — every symbol below is a thin re-export.
"""

from __future__ import annotations

from .telemetry import (
    ScadaSeries,
    TelemetrySeries,
    generate_synthetic_scada,
    generate_synthetic_telemetry,
)

__all__ = [
    "ScadaSeries",
    "TelemetrySeries",
    "generate_synthetic_scada",
    "generate_synthetic_telemetry",
]
