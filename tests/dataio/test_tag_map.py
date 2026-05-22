"""Tests for the PLC/PAC/SCADA tag-map foundation.

A ``SiteTagMap`` describes how a single site exposes its telemetry —
which named tags are available, which physical kind they measure, how
they map to network nodes/edges/pumps, and whether they are writable.
The structure is validated strictly at construction time so downstream
adapters can trust invariants without re-checking them.
"""

from __future__ import annotations

import pytest

from aquaoptima.dataio import (
    SiteTagMap,
    SourceType,
    TagDefinition,
    TagKind,
)


def _pressure_tag(name: str = "P_J1", node_id: str = "J1") -> TagDefinition:
    return TagDefinition(
        name=name,
        kind=TagKind.PRESSURE,
        source_address="DB1.DBD0",
        unit="bar",
        node_id=node_id,
    )


def _flow_tag(name: str = "Q_E1", edge_id: str = "E1") -> TagDefinition:
    return TagDefinition(
        name=name,
        kind=TagKind.FLOW,
        source_address="DB1.DBD4",
        unit="m3/s",
        edge_id=edge_id,
    )


def _pump_speed_tag(name: str = "S_P1", pump_id: str = "P1") -> TagDefinition:
    return TagDefinition(
        name=name,
        kind=TagKind.PUMP_SPEED,
        source_address="DB1.DBD8",
        unit="rpm",
        pump_id=pump_id,
    )


def test_source_type_enum_members() -> None:
    expected = {
        "SYNTHETIC", "CSV", "PLC", "PAC", "SCADA", "HISTORIAN", "MQTT",
    }
    actual = {m.name for m in SourceType}
    assert expected.issubset(actual)


def test_tag_kind_enum_members() -> None:
    expected = {
        "PRESSURE", "FLOW", "PUMP_SPEED", "PUMP_STATUS",
        "POWER", "COMMAND", "ALARM",
    }
    actual = {m.name for m in TagKind}
    assert expected.issubset(actual)


def test_site_tag_map_accepts_well_formed_tags() -> None:
    site = SiteTagMap(
        site_id="WTP-01",
        source_type=SourceType.PLC,
        sampling_interval_sec=5,
        tags=(_pressure_tag(), _flow_tag(), _pump_speed_tag()),
    )
    assert site.site_id == "WTP-01"
    assert site.source_type is SourceType.PLC
    assert len(site.tags) == 3


def test_site_tag_map_rejects_non_positive_sampling_interval() -> None:
    with pytest.raises(ValueError):
        SiteTagMap(
            site_id="X",
            source_type=SourceType.PLC,
            sampling_interval_sec=0,
            tags=(_pressure_tag(),),
        )
    with pytest.raises(ValueError):
        SiteTagMap(
            site_id="X",
            source_type=SourceType.PLC,
            sampling_interval_sec=-1,
            tags=(_pressure_tag(),),
        )


def test_site_tag_map_rejects_duplicate_tag_names() -> None:
    with pytest.raises(ValueError):
        SiteTagMap(
            site_id="X",
            source_type=SourceType.PLC,
            sampling_interval_sec=5,
            tags=(_pressure_tag(name="DUP"), _flow_tag(name="DUP")),
        )


def test_pressure_tag_requires_node_id() -> None:
    bad = TagDefinition(
        name="P_X",
        kind=TagKind.PRESSURE,
        source_address="DB1.DBD0",
        unit="bar",
        node_id=None,
    )
    with pytest.raises(ValueError):
        SiteTagMap(
            site_id="X",
            source_type=SourceType.PLC,
            sampling_interval_sec=5,
            tags=(bad,),
        )


def test_flow_tag_requires_edge_id() -> None:
    bad = TagDefinition(
        name="Q_X",
        kind=TagKind.FLOW,
        source_address="DB1.DBD4",
        unit="m3/s",
        edge_id=None,
    )
    with pytest.raises(ValueError):
        SiteTagMap(
            site_id="X",
            source_type=SourceType.PLC,
            sampling_interval_sec=5,
            tags=(bad,),
        )


@pytest.mark.parametrize(
    "kind",
    [TagKind.PUMP_SPEED, TagKind.PUMP_STATUS, TagKind.POWER, TagKind.COMMAND],
)
def test_pump_related_tag_requires_pump_id(kind: TagKind) -> None:
    bad = TagDefinition(
        name=f"X_{kind.value}",
        kind=kind,
        source_address="DB1.DBD8",
        unit="x",
        pump_id=None,
    )
    with pytest.raises(ValueError):
        SiteTagMap(
            site_id="X",
            source_type=SourceType.PLC,
            sampling_interval_sec=5,
            tags=(bad,),
        )


def test_command_tag_is_not_writable_by_default() -> None:
    cmd = TagDefinition(
        name="CMD_P1",
        kind=TagKind.COMMAND,
        source_address="DB2.DBD0",
        unit="bool",
        pump_id="P1",
    )
    assert cmd.writable is False


def test_command_tag_can_be_marked_writable_explicitly() -> None:
    cmd = TagDefinition(
        name="CMD_P1",
        kind=TagKind.COMMAND,
        source_address="DB2.DBD0",
        unit="bool",
        pump_id="P1",
        writable=True,
    )
    assert cmd.writable is True


def test_site_tag_map_is_frozen() -> None:
    site = SiteTagMap(
        site_id="WTP-01",
        source_type=SourceType.SCADA,
        sampling_interval_sec=5,
        tags=(_pressure_tag(),),
    )
    with pytest.raises(Exception):
        site.site_id = "MUTATED"  # type: ignore[misc]
