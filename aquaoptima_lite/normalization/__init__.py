"""Normalization layer: raw tag dicts -> canonical :class:`StationSnapshot`.

The layer has three pieces:

- :mod:`tag_mapper` maps legacy and MVP-style tag names into canonical
  field names plus per-pump sub-fields;
- :mod:`units` provides a small extensible unit-conversion table;
- :mod:`snapshot_builder` assembles a :class:`StationSnapshot` from the
  mapped, unit-normalized values and the :class:`SiteConfig`.
"""

from .snapshot_builder import SnapshotBuilder, build_snapshot
from .tag_mapper import (
    LEGACY_PUMP_PREFIXES,
    LEGACY_STATION_ALIASES,
    MappedTags,
    map_tags,
)
from .units import normalize_unit, supported_units

__all__ = [
    "LEGACY_PUMP_PREFIXES",
    "LEGACY_STATION_ALIASES",
    "MappedTags",
    "SnapshotBuilder",
    "build_snapshot",
    "map_tags",
    "normalize_unit",
    "supported_units",
]
