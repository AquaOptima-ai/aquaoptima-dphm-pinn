"""Telemetry data model, windowing utilities, and source metadata.

SCADA is treated as one of several possible telemetry sources (PLC,
PAC, historian, MQTT, CSV, synthetic). The canonical container is
:class:`TelemetrySeries`; the older ``ScadaSeries`` symbol is kept as
a backward-compatible alias for Sprint 1-4 callers.
"""

from .quality import QualityFlag, is_usable
from .tag_map import SiteTagMap, SourceType, TagDefinition, TagKind
from .telemetry import (
    ScadaSeries,
    TelemetrySeries,
    generate_synthetic_scada,
    generate_synthetic_telemetry,
)
from .window_dataset import NODE_FEATURE_DIM, WindowDataset

__all__ = [
    "NODE_FEATURE_DIM",
    "QualityFlag",
    "ScadaSeries",
    "SiteTagMap",
    "SourceType",
    "TagDefinition",
    "TagKind",
    "TelemetrySeries",
    "WindowDataset",
    "generate_synthetic_scada",
    "generate_synthetic_telemetry",
    "is_usable",
]
