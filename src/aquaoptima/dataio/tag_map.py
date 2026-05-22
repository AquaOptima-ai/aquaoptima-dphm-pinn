"""PLC / PAC / SCADA tag-map foundation.

A :class:`SiteTagMap` is the static contract between AquaOptima and a
single field site: which named tags the site exposes, what each tag
measures, how it ties back to the network topology (which node, edge,
or pump), and whether AquaOptima is allowed to write it.

Sprint 4.5 only ships the data model and its validation rules. The
*adapter* implementations (Modbus, OPC-UA, MQTT, historian REST, CSV)
land in later sprints. Until then, only the synthetic source is wired
end-to-end. See ``docs/telemetry-abstraction.md`` for the full source
strategy and ``docs/safety-boundary.md`` for the write-path rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SourceType(str, Enum):
    """Origin of a telemetry stream.

    ``SYNTHETIC`` is the only fully wired source as of Sprint 4.5. The
    rest are reserved values that adapter implementations will claim
    in later sprints.
    """

    SYNTHETIC = "synthetic"
    CSV = "csv"
    PLC = "plc"
    PAC = "pac"
    SCADA = "scada"
    HISTORIAN = "historian"
    MQTT = "mqtt"


class TagKind(str, Enum):
    """Physical quantity a tag represents.

    The kind drives downstream validation (e.g. a ``PRESSURE`` tag must
    reference a network node) and how the value flows into the dPHM
    state vector. ``COMMAND`` is unique in that it represents an
    *output* AquaOptima could write to a controller — see
    :attr:`TagDefinition.writable`.
    """

    PRESSURE = "pressure"
    FLOW = "flow"
    PUMP_SPEED = "pump_speed"
    PUMP_STATUS = "pump_status"
    POWER = "power"
    COMMAND = "command"
    ALARM = "alarm"


_PUMP_RELATED = frozenset(
    {TagKind.PUMP_SPEED, TagKind.PUMP_STATUS, TagKind.POWER, TagKind.COMMAND}
)


@dataclass(frozen=True)
class TagDefinition:
    """A single named tag exposed by a telemetry source.

    Attributes
    ----------
    name
        Site-unique tag name. Used as the dictionary key in any
        telemetry frame.
    kind
        Physical quantity (see :class:`TagKind`).
    source_address
        Adapter-specific address (Modbus register, OPC-UA node-id, MQTT
        topic, CSV column header, etc.). Opaque to AquaOptima core.
    unit
        Engineering unit string. Used for documentation and to drive
        adapter-side conversion; core code assumes m / m^3/s / mWC /
        dimensionless once telemetry reaches :class:`TelemetrySeries`.
    node_id
        Network node identifier this tag is tied to. Required for
        :attr:`TagKind.PRESSURE`.
    edge_id
        Network edge identifier this tag is tied to. Required for
        :attr:`TagKind.FLOW`.
    pump_id
        Pump identifier this tag is tied to. Required for
        :attr:`TagKind.PUMP_SPEED`, :attr:`TagKind.PUMP_STATUS`,
        :attr:`TagKind.POWER`, and :attr:`TagKind.COMMAND`.
    writable
        Whether AquaOptima is permitted to write this tag back to the
        source. Defaults to ``False`` because every safe-by-default
        commissioning step should require an *explicit* opt-in for
        commands. See ``docs/safety-boundary.md``.
    """

    name: str
    kind: TagKind
    source_address: str
    unit: str
    node_id: Optional[str] = None
    edge_id: Optional[str] = None
    pump_id: Optional[str] = None
    writable: bool = False


@dataclass(frozen=True)
class SiteTagMap:
    """All tags exposed by a single field site, with source metadata.

    Validation is strict at construction time: every tag must declare
    the topology pointer required by its :class:`TagKind`, names must
    be unique within the site, and the sampling interval must be
    positive. Downstream adapters can therefore trust invariants
    without re-checking them on every poll.
    """

    site_id: str
    source_type: SourceType
    sampling_interval_sec: int
    tags: tuple[TagDefinition, ...]

    def __post_init__(self) -> None:
        if self.sampling_interval_sec <= 0:
            raise ValueError(
                "sampling_interval_sec must be positive, got "
                f"{self.sampling_interval_sec}"
            )

        seen: set[str] = set()
        for tag in self.tags:
            if tag.name in seen:
                raise ValueError(
                    f"duplicate tag name {tag.name!r} in site {self.site_id!r}"
                )
            seen.add(tag.name)

            if tag.kind is TagKind.PRESSURE and tag.node_id is None:
                raise ValueError(
                    f"PRESSURE tag {tag.name!r} must declare node_id"
                )
            if tag.kind is TagKind.FLOW and tag.edge_id is None:
                raise ValueError(
                    f"FLOW tag {tag.name!r} must declare edge_id"
                )
            if tag.kind in _PUMP_RELATED and tag.pump_id is None:
                raise ValueError(
                    f"{tag.kind.value!r} tag {tag.name!r} must declare pump_id"
                )


__all__ = [
    "SourceType",
    "TagKind",
    "TagDefinition",
    "SiteTagMap",
]
