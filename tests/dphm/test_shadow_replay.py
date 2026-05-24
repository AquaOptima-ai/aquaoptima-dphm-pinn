"""Sprint 35 — Cold-start replay / shadow dataset builder.

Sprint 35 turns offline telemetry rows into typed replay frames keyed
by canonical dPHM axis and id, on top of the Sprint 34
:class:`TelemetryTagMap`. These tests cover, in order:

1. Frozen dataclass surfaces.
2. Empty row list returns an empty dataset with empty diagnostics.
3. Valid node-pressure row populates ``node_pressure``.
4. Valid edge-flow row populates ``edge_flow``.
5. Pump-speed percent converts to fraction.
6. Pressure conversions: ``bar`` / ``kpa`` / ``psi`` → m.
7. Flow conversions: ``l/s`` / ``gpm`` → m3/s.
8. Level conversion: ``ft`` → m.
9. Power conversion: ``w`` → kw.
10. Status parsing: ``bool``, ``0`` / ``1``, common strings.
11. Missing-timestamp handling in strict / non-strict mode.
12. Missing-tag-value handling in strict / non-strict mode.
13. Invalid-numeric handling in strict / non-strict mode.
14. ``rpm`` pump-speed handled conservatively (warning + omitted in
    non-strict; raised in strict).
15. Deterministic frame ordering.
16. Read-only: input rows and tag_map unchanged.
17. CSV loader happy path.
18. CSV loader malformed shape (no header, missing timestamp column).
19. Sprint 34 :func:`build_telemetry_tag_map` output is consumed
    verbatim.
20. No live adapter / write / control surface exposed.
21. ``max_stale_seconds`` warnings on inter-row gaps.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as _datetime
import math
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    ShadowReplayDataset,
    ShadowReplayDiagnostics,
    ShadowReplayFrame,
    TELEMETRY_ROLE_CONTROL_INPUT,
    TELEMETRY_TARGET_EDGE,
    TELEMETRY_TARGET_NODE,
    TelemetryTagMap,
    TelemetryTagSpec,
    build_shadow_replay_dataset,
    build_telemetry_tag_map,
    load_shadow_replay_csv,
    make_branch_network,
    make_pump_network,
)
import aquaoptima.dphm as dphm
import aquaoptima.dphm.shadow_replay as shadow_replay_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pressure_map(
    network: Network | None = None, *, tag: str = "PT1", target_id: int = 1, unit: str = "m"
) -> TelemetryTagMap:
    if network is None:
        network = make_branch_network()
    spec = TelemetryTagSpec(tag, TELEMETRY_TARGET_NODE, target_id, "pressure", unit)
    return build_telemetry_tag_map([spec], network)


def _flow_map(
    network: Network | None = None, *, tag: str = "FT1", target_id: int = 0, unit: str = "m3/s"
) -> TelemetryTagMap:
    if network is None:
        network = make_branch_network()
    spec = TelemetryTagSpec(tag, TELEMETRY_TARGET_EDGE, target_id, "flow", unit)
    return build_telemetry_tag_map([spec], network)


def _pump_speed_map(
    network: Network | None = None, *, tag: str = "PUMP_SPEED", unit: str = "percent"
) -> TelemetryTagMap:
    if network is None:
        network = make_pump_network()
    spec = TelemetryTagSpec(
        tag,
        TELEMETRY_TARGET_EDGE,
        0,
        "pump_speed",
        unit,
        role=TELEMETRY_ROLE_CONTROL_INPUT,
    )
    return build_telemetry_tag_map([spec], network)


# ---------------------------------------------------------------------------
# 1. Frozen dataclass surfaces
# ---------------------------------------------------------------------------


def test_shadow_replay_dataclasses_are_frozen() -> None:
    tag_map = _pressure_map()
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PT1": 12.5}], tag_map
    )
    frame = dataset.frames[0]
    diagnostics = dataset.diagnostics

    for instance in (frame, diagnostics, dataset):
        cls = type(instance)
        assert dataclasses.is_dataclass(cls)
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen is True, f"{cls.__name__} must be frozen"

    with pytest.raises(dataclasses.FrozenInstanceError):
        frame.timestamp = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        diagnostics.warnings = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        dataset.frames = ()  # type: ignore[misc]


def test_default_shadow_replay_dataset_has_empty_surfaces() -> None:
    dataset = ShadowReplayDataset()
    assert dataset.frames == ()
    assert dataset.tag_map == TelemetryTagMap()
    assert dataset.diagnostics == ShadowReplayDiagnostics()


# ---------------------------------------------------------------------------
# 2. Empty rows produce empty dataset
# ---------------------------------------------------------------------------


def test_empty_rows_returns_empty_dataset() -> None:
    tag_map = _pressure_map()
    dataset = build_shadow_replay_dataset([], tag_map)
    assert dataset.frames == ()
    assert dataset.diagnostics.warnings == ()
    assert dataset.diagnostics.errors == ()
    assert dataset.tag_map is tag_map


# ---------------------------------------------------------------------------
# 3. Valid node pressure row populates frame
# ---------------------------------------------------------------------------


def test_node_pressure_row_populates_node_pressure() -> None:
    tag_map = _pressure_map(target_id=2)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": "2026-05-23T00:00:00Z", "PT1": 30.5}], tag_map
    )
    assert len(dataset.frames) == 1
    frame = dataset.frames[0]
    assert frame.timestamp == "2026-05-23T00:00:00Z"
    assert frame.node_pressure == {2: 30.5}
    # Other axes stay empty.
    assert frame.edge_flow == {}
    assert frame.node_demand == {}
    assert frame.diagnostics.errors == ()


# ---------------------------------------------------------------------------
# 4. Valid edge flow row populates frame
# ---------------------------------------------------------------------------


def test_edge_flow_row_populates_edge_flow() -> None:
    tag_map = _flow_map(target_id=1)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "FT1": 0.025}], tag_map
    )
    assert dataset.frames[0].edge_flow == {1: 0.025}


# ---------------------------------------------------------------------------
# 5. Pump speed percent → fraction
# ---------------------------------------------------------------------------


def test_pump_speed_percent_converts_to_fraction() -> None:
    tag_map = _pump_speed_map(unit="percent")
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PUMP_SPEED": 75.0}], tag_map
    )
    frame = dataset.frames[0]
    assert frame.edge_pump_speed == {0: pytest.approx(0.75)}


def test_pump_speed_fraction_is_identity() -> None:
    tag_map = _pump_speed_map(unit="fraction")
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PUMP_SPEED": 0.42}], tag_map
    )
    assert dataset.frames[0].edge_pump_speed == {0: pytest.approx(0.42)}


# ---------------------------------------------------------------------------
# 6. Pressure conversions
# ---------------------------------------------------------------------------


def test_pressure_conversions_to_meters() -> None:
    network = make_branch_network()
    specs = [
        TelemetryTagSpec("PT_BAR", TELEMETRY_TARGET_NODE, 1, "pressure", "bar"),
        TelemetryTagSpec("PT_KPA", TELEMETRY_TARGET_NODE, 2, "pressure", "kpa"),
        TelemetryTagSpec("PT_PSI", TELEMETRY_TARGET_NODE, 3, "pressure", "psi"),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    dataset = build_shadow_replay_dataset(
        [
            {
                "timestamp": 0.0,
                "PT_BAR": 1.0,
                "PT_KPA": 100.0,
                "PT_PSI": 1.0,
            }
        ],
        tag_map,
    )
    frame = dataset.frames[0]
    # 1 bar ≈ 10.197 m H2O.
    assert frame.node_pressure[1] == pytest.approx(10.197162129779283)
    # 100 kPa ≈ 10.197 m H2O (same as 1 bar).
    assert frame.node_pressure[2] == pytest.approx(10.197162129779283, rel=1e-6)
    # 1 psi ≈ 0.7032 m H2O (per the Sprint 35 conversion table).
    assert frame.node_pressure[3] == pytest.approx(0.703249614902)


def test_pressure_meter_alias_is_identity() -> None:
    network = make_branch_network()
    specs = [
        TelemetryTagSpec("PT_M", TELEMETRY_TARGET_NODE, 1, "pressure", "m"),
        TelemetryTagSpec("PT_METER", TELEMETRY_TARGET_NODE, 2, "pressure", "meter"),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PT_M": 12.0, "PT_METER": 5.5}], tag_map
    )
    frame = dataset.frames[0]
    assert frame.node_pressure[1] == pytest.approx(12.0)
    assert frame.node_pressure[2] == pytest.approx(5.5)


# ---------------------------------------------------------------------------
# 7. Flow conversions
# ---------------------------------------------------------------------------


def test_flow_conversions_to_m3_s() -> None:
    network = make_branch_network()
    specs = [
        TelemetryTagSpec("FT_LPS", TELEMETRY_TARGET_EDGE, 0, "flow", "l/s"),
        TelemetryTagSpec("FT_GPM", TELEMETRY_TARGET_EDGE, 1, "flow", "gpm"),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "FT_LPS": 25.0, "FT_GPM": 100.0}],
        tag_map,
    )
    frame = dataset.frames[0]
    # 25 L/s = 0.025 m3/s
    assert frame.edge_flow[0] == pytest.approx(0.025)
    # 100 gpm ≈ 0.00630902 m3/s
    assert frame.edge_flow[1] == pytest.approx(6.309019640343866e-3)


# ---------------------------------------------------------------------------
# 8. Level conversion
# ---------------------------------------------------------------------------


def test_level_ft_converts_to_meters() -> None:
    network = make_branch_network()
    spec = TelemetryTagSpec("LT_TANK", TELEMETRY_TARGET_NODE, 0, "level", "ft")
    tag_map = build_telemetry_tag_map([spec], network)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "LT_TANK": 10.0}], tag_map
    )
    assert dataset.frames[0].node_level[0] == pytest.approx(3.048)


# ---------------------------------------------------------------------------
# 9. Power conversion
# ---------------------------------------------------------------------------


def test_power_watt_converts_to_kw() -> None:
    network = make_pump_network()
    spec = TelemetryTagSpec("KW_PUMP", TELEMETRY_TARGET_EDGE, 0, "power", "w")
    tag_map = build_telemetry_tag_map([spec], network)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "KW_PUMP": 1500.0}], tag_map
    )
    assert dataset.frames[0].edge_power[0] == pytest.approx(1.5)


def test_power_kw_is_identity() -> None:
    network = make_pump_network()
    spec = TelemetryTagSpec("KW_PUMP", TELEMETRY_TARGET_EDGE, 0, "power", "kw")
    tag_map = build_telemetry_tag_map([spec], network)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "KW_PUMP": 3.14}], tag_map
    )
    assert dataset.frames[0].edge_power[0] == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# 10. Status parsing
# ---------------------------------------------------------------------------


def test_status_parsing_accepts_bool_int_and_strings() -> None:
    network = make_pump_network()
    specs = [
        TelemetryTagSpec("STAT_BOOL", TELEMETRY_TARGET_EDGE, 0, "status", "boolean"),
        TelemetryTagSpec("STAT_INT", TELEMETRY_TARGET_EDGE, 1, "status", "0/1"),
        TelemetryTagSpec("STAT_STR", TELEMETRY_TARGET_NODE, 0, "status", "boolean"),
    ]
    tag_map = build_telemetry_tag_map(specs, network)

    rows = [
        {"timestamp": 0.0, "STAT_BOOL": True, "STAT_INT": 1, "STAT_STR": "on"},
        {"timestamp": 1.0, "STAT_BOOL": False, "STAT_INT": 0, "STAT_STR": "off"},
        {"timestamp": 2.0, "STAT_BOOL": True, "STAT_INT": 1, "STAT_STR": "running"},
        {
            "timestamp": 3.0,
            "STAT_BOOL": False,
            "STAT_INT": 0,
            "STAT_STR": "closed",
        },
    ]
    dataset = build_shadow_replay_dataset(rows, tag_map)
    assert dataset.diagnostics.errors == ()
    assert dataset.frames[0].edge_status == {0: True, 1: True}
    assert dataset.frames[0].node_status == {0: True}
    assert dataset.frames[1].edge_status == {0: False, 1: False}
    assert dataset.frames[1].node_status == {0: False}
    assert dataset.frames[2].node_status == {0: True}
    assert dataset.frames[3].node_status == {0: False}


def test_status_unknown_string_rejected_strict() -> None:
    network = make_pump_network()
    spec = TelemetryTagSpec(
        "STAT", TELEMETRY_TARGET_EDGE, 0, "status", "boolean"
    )
    tag_map = build_telemetry_tag_map([spec], network)
    with pytest.raises(ValueError, match="unrecognised status"):
        build_shadow_replay_dataset(
            [{"timestamp": 0.0, "STAT": "WALRUS"}], tag_map, strict=True
        )


def test_status_unknown_string_omitted_non_strict() -> None:
    network = make_pump_network()
    spec = TelemetryTagSpec(
        "STAT", TELEMETRY_TARGET_EDGE, 0, "status", "boolean"
    )
    tag_map = build_telemetry_tag_map([spec], network)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "STAT": "WALRUS"}], tag_map, strict=False
    )
    assert len(dataset.frames) == 1
    assert dataset.frames[0].edge_status == {}
    assert any("WALRUS" in e for e in dataset.diagnostics.errors)


# ---------------------------------------------------------------------------
# 11. Missing timestamp handling
# ---------------------------------------------------------------------------


def test_missing_timestamp_raises_in_strict_mode() -> None:
    tag_map = _pressure_map()
    with pytest.raises(ValueError, match="missing timestamp key"):
        build_shadow_replay_dataset(
            [{"PT1": 12.5}], tag_map, strict=True
        )


def test_missing_timestamp_records_error_in_non_strict_mode() -> None:
    tag_map = _pressure_map()
    dataset = build_shadow_replay_dataset(
        [
            {"timestamp": 0.0, "PT1": 12.0},
            {"PT1": 13.0},
            {"timestamp": 1.0, "PT1": 14.0},
        ],
        tag_map,
        strict=False,
    )
    assert [f.timestamp for f in dataset.frames] == [0.0, 1.0]
    assert any("missing timestamp" in e for e in dataset.diagnostics.errors)


def test_none_timestamp_rejected_strict() -> None:
    tag_map = _pressure_map()
    with pytest.raises(ValueError, match="timestamp value is None"):
        build_shadow_replay_dataset(
            [{"timestamp": None, "PT1": 12.5}], tag_map, strict=True
        )


# ---------------------------------------------------------------------------
# 12. Missing tag value handling
# ---------------------------------------------------------------------------


def test_missing_tag_value_records_warning_not_error() -> None:
    tag_map = _pressure_map(target_id=1)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0}], tag_map, strict=True
    )
    # Missing tag is a warning, *not* an error — strict=True should
    # still succeed.
    assert dataset.frames[0].node_pressure == {}
    assert dataset.frames[0].diagnostics.errors == ()
    assert any("not present" in w for w in dataset.frames[0].diagnostics.warnings)
    assert any("not present" in w for w in dataset.diagnostics.warnings)


def test_none_tag_value_records_warning_not_error() -> None:
    tag_map = _pressure_map(target_id=1)
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PT1": None}], tag_map, strict=True
    )
    assert dataset.frames[0].node_pressure == {}
    assert any("is None" in w for w in dataset.frames[0].diagnostics.warnings)


# ---------------------------------------------------------------------------
# 13. Invalid numeric handling
# ---------------------------------------------------------------------------


def test_invalid_numeric_raises_in_strict_mode() -> None:
    tag_map = _pressure_map()
    with pytest.raises(ValueError, match="could not parse"):
        build_shadow_replay_dataset(
            [{"timestamp": 0.0, "PT1": "not-a-number"}], tag_map, strict=True
        )


def test_invalid_numeric_omitted_in_non_strict_mode() -> None:
    tag_map = _pressure_map()
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PT1": "not-a-number"}], tag_map, strict=False
    )
    assert dataset.frames[0].node_pressure == {}
    assert any("could not parse" in e for e in dataset.diagnostics.errors)


def test_bool_for_numeric_axis_rejected() -> None:
    tag_map = _pressure_map()
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PT1": True}], tag_map, strict=False
    )
    assert dataset.frames[0].node_pressure == {}
    assert any("boolean" in e for e in dataset.diagnostics.errors)


def test_nan_numeric_rejected() -> None:
    tag_map = _pressure_map()
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PT1": float("nan")}], tag_map, strict=False
    )
    assert dataset.frames[0].node_pressure == {}
    assert any("non-finite" in e for e in dataset.diagnostics.errors)


def test_numeric_string_with_whitespace_accepted() -> None:
    tag_map = _pressure_map()
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PT1": "  12.5  "}], tag_map
    )
    assert dataset.frames[0].node_pressure[1] == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# 14. RPM pump speed handled conservatively
# ---------------------------------------------------------------------------


def test_rpm_pump_speed_warns_and_omits_in_non_strict() -> None:
    tag_map = _pump_speed_map(unit="rpm")
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PUMP_SPEED": 1750.0}], tag_map, strict=False
    )
    frame = dataset.frames[0]
    assert frame.edge_pump_speed == {}
    assert any("rpm" in w for w in frame.diagnostics.warnings)


# Strict mode still tolerates rpm because the conservative behaviour
# is a *warning*, not an error. Document the contract explicitly.
def test_rpm_pump_speed_strict_does_not_raise_only_warns() -> None:
    tag_map = _pump_speed_map(unit="rpm")
    dataset = build_shadow_replay_dataset(
        [{"timestamp": 0.0, "PUMP_SPEED": 1750.0}], tag_map, strict=True
    )
    frame = dataset.frames[0]
    assert frame.edge_pump_speed == {}
    assert any("rpm" in w for w in frame.diagnostics.warnings)


# ---------------------------------------------------------------------------
# 15. Deterministic frame ordering
# ---------------------------------------------------------------------------


def test_frames_preserve_input_row_order() -> None:
    tag_map = _pressure_map(target_id=1)
    rows = [
        {"timestamp": "t0", "PT1": 1.0},
        {"timestamp": "t1", "PT1": 2.0},
        {"timestamp": "t2", "PT1": 3.0},
    ]
    dataset_a = build_shadow_replay_dataset(rows, tag_map)
    dataset_b = build_shadow_replay_dataset(rows, tag_map)
    assert [f.timestamp for f in dataset_a.frames] == ["t0", "t1", "t2"]
    assert [f.timestamp for f in dataset_b.frames] == ["t0", "t1", "t2"]
    assert dataset_a.frames == dataset_b.frames


# ---------------------------------------------------------------------------
# 16. Read-only: input rows and tag_map unchanged
# ---------------------------------------------------------------------------


def test_builder_does_not_mutate_inputs() -> None:
    network = make_pump_network()
    specs = [
        TelemetryTagSpec("PT", TELEMETRY_TARGET_NODE, 1, "pressure", "bar"),
        TelemetryTagSpec("FT", TELEMETRY_TARGET_EDGE, 1, "flow", "l/s"),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    tag_map_snapshot = copy.deepcopy(tag_map)

    rows = [
        {"timestamp": 0.0, "PT": 1.0, "FT": 25.0},
        {"timestamp": 1.0, "PT": 2.0, "FT": 30.0},
    ]
    rows_snapshot = copy.deepcopy(rows)

    dataset = build_shadow_replay_dataset(rows, tag_map)
    assert len(dataset.frames) == 2

    assert rows == rows_snapshot
    assert tag_map == tag_map_snapshot
    # Identity preserved.
    assert dataset.tag_map is tag_map


# ---------------------------------------------------------------------------
# 17. CSV loader happy path
# ---------------------------------------------------------------------------


def test_csv_loader_happy_path(tmp_path: Path) -> None:
    network = make_branch_network()
    specs = [
        TelemetryTagSpec("PT_BAR", TELEMETRY_TARGET_NODE, 1, "pressure", "bar"),
        TelemetryTagSpec("FT_LPS", TELEMETRY_TARGET_EDGE, 0, "flow", "l/s"),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    csv_text = (
        "timestamp,PT_BAR,FT_LPS\n"
        "2026-05-23T00:00:00Z,1.0,25.0\n"
        "2026-05-23T00:01:00Z,1.05,26.5\n"
    )
    path = tmp_path / "telemetry.csv"
    path.write_text(csv_text)
    dataset = load_shadow_replay_csv(path, tag_map)
    assert len(dataset.frames) == 2
    assert dataset.frames[0].node_pressure[1] == pytest.approx(
        10.197162129779283
    )
    assert dataset.frames[0].edge_flow[0] == pytest.approx(0.025)
    # Empty cells get treated as missing — exercise via second loader test.


def test_csv_loader_empty_cells_treated_as_missing(tmp_path: Path) -> None:
    network = make_branch_network()
    spec = TelemetryTagSpec("PT", TELEMETRY_TARGET_NODE, 1, "pressure", "m")
    tag_map = build_telemetry_tag_map([spec], network)
    csv_text = "timestamp,PT\n0,\n1,12.5\n"
    path = tmp_path / "tel.csv"
    path.write_text(csv_text)
    dataset = load_shadow_replay_csv(path, tag_map)
    # First frame: missing PT → warning, no error.
    assert dataset.frames[0].node_pressure == {}
    assert dataset.frames[1].node_pressure[1] == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# 18. CSV loader malformed shape / missing column
# ---------------------------------------------------------------------------


def test_csv_loader_no_header_raises(tmp_path: Path) -> None:
    network = make_branch_network()
    spec = TelemetryTagSpec("PT", TELEMETRY_TARGET_NODE, 1, "pressure", "m")
    tag_map = build_telemetry_tag_map([spec], network)
    path = tmp_path / "empty.csv"
    path.write_text("")
    with pytest.raises(ValueError, match="no header row"):
        load_shadow_replay_csv(path, tag_map)


def test_csv_loader_missing_timestamp_column_raises(tmp_path: Path) -> None:
    network = make_branch_network()
    spec = TelemetryTagSpec("PT", TELEMETRY_TARGET_NODE, 1, "pressure", "m")
    tag_map = build_telemetry_tag_map([spec], network)
    csv_text = "tstamp,PT\n0,12.5\n"
    path = tmp_path / "bad.csv"
    path.write_text(csv_text)
    with pytest.raises(ValueError, match="timestamp column"):
        load_shadow_replay_csv(path, tag_map)


def test_csv_loader_custom_timestamp_key(tmp_path: Path) -> None:
    network = make_branch_network()
    spec = TelemetryTagSpec("PT", TELEMETRY_TARGET_NODE, 1, "pressure", "m")
    tag_map = build_telemetry_tag_map([spec], network)
    csv_text = "ts,PT\n2026-05-23,12.5\n"
    path = tmp_path / "alt.csv"
    path.write_text(csv_text)
    dataset = load_shadow_replay_csv(path, tag_map, timestamp_key="ts")
    assert dataset.frames[0].timestamp == "2026-05-23"
    assert dataset.frames[0].node_pressure[1] == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# 19. Sprint 34 compatibility
# ---------------------------------------------------------------------------


def test_consumes_sprint_34_tag_map_verbatim() -> None:
    network = make_pump_network()
    specs = [
        TelemetryTagSpec("PT_DC", TELEMETRY_TARGET_NODE, 1, "pressure", "bar"),
        TelemetryTagSpec("FT_OUT", TELEMETRY_TARGET_EDGE, 1, "flow", "m3/s"),
        TelemetryTagSpec(
            "PUMP_S",
            TELEMETRY_TARGET_EDGE,
            0,
            "pump_speed",
            "percent",
            role=TELEMETRY_ROLE_CONTROL_INPUT,
        ),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    rows = [
        {
            "timestamp": 0.0,
            "PT_DC": 1.0,
            "FT_OUT": 0.02,
            "PUMP_S": 80.0,
        }
    ]
    dataset = build_shadow_replay_dataset(rows, tag_map)
    frame = dataset.frames[0]
    assert frame.node_pressure[1] == pytest.approx(10.197162129779283)
    assert frame.edge_flow[1] == pytest.approx(0.02)
    assert frame.edge_pump_speed[0] == pytest.approx(0.8)
    # The dataset retains the originating tag_map verbatim.
    assert dataset.tag_map is tag_map


def test_empty_tag_map_yields_empty_axis_maps_per_frame() -> None:
    tag_map = TelemetryTagMap()
    rows = [{"timestamp": 0.0, "PT1": 1.0}, {"timestamp": 1.0, "PT1": 2.0}]
    dataset = build_shadow_replay_dataset(rows, tag_map)
    assert len(dataset.frames) == 2
    for frame in dataset.frames:
        assert frame.node_pressure == {}
        assert frame.edge_flow == {}
        assert frame.diagnostics.errors == ()
        # No declared tag means there's no warning either.
        assert frame.diagnostics.warnings == ()


# ---------------------------------------------------------------------------
# 20. No live adapter / write / control surface exposed
# ---------------------------------------------------------------------------


def test_no_write_or_control_path_exposed() -> None:
    forbidden_substrings = (
        "write",
        "send",
        "publish",
        "subscribe",
        "poll",
        "actuate",
        "open_socket",
        "open_connection",
        "mqtt",
        "opcua",
        "scada",
        "historian",
        "http",
    )
    for name in shadow_replay_module.__all__:
        symbol = getattr(shadow_replay_module, name)
        if not callable(symbol):
            continue
        if isinstance(symbol, type):
            continue
        lname = name.lower()
        for needle in forbidden_substrings:
            assert needle not in lname, (
                f"shadow_replay exposes callable {name!r} containing "
                f"forbidden substring {needle!r}"
            )

    for name in (
        "build_shadow_replay_dataset",
        "load_shadow_replay_csv",
        "ShadowReplayDataset",
        "ShadowReplayDiagnostics",
        "ShadowReplayFrame",
    ):
        assert name in dphm.__all__

    # The module must not pull in any live-ingestion / network stdlib
    # modules; ``csv`` and ``pathlib`` are read-only file I/O.
    for forbidden in ("socket", "asyncio", "ssl", "urllib", "smtplib"):
        attr = forbidden.split(".")[0]
        assert not hasattr(shadow_replay_module, attr), (
            f"shadow_replay unexpectedly references {forbidden!r}"
        )


# ---------------------------------------------------------------------------
# 21. max_stale_seconds gap warnings
# ---------------------------------------------------------------------------


def test_max_stale_seconds_emits_gap_warning() -> None:
    tag_map = _pressure_map(target_id=1)
    rows = [
        {"timestamp": 0.0, "PT1": 1.0},
        {"timestamp": 5.0, "PT1": 2.0},
        {"timestamp": 60.0, "PT1": 3.0},  # 55 s gap
    ]
    dataset = build_shadow_replay_dataset(
        rows, tag_map, max_stale_seconds=30.0
    )
    assert any("max_stale_seconds" in w for w in dataset.diagnostics.warnings)


def test_max_stale_seconds_works_with_datetime_timestamps() -> None:
    tag_map = _pressure_map(target_id=1)
    t0 = _datetime.datetime(2026, 5, 23, 0, 0, 0)
    t1 = _datetime.datetime(2026, 5, 23, 0, 0, 10)
    t2 = _datetime.datetime(2026, 5, 23, 0, 1, 30)  # 80 s gap from t1
    rows = [
        {"timestamp": t0, "PT1": 1.0},
        {"timestamp": t1, "PT1": 1.1},
        {"timestamp": t2, "PT1": 1.2},
    ]
    dataset = build_shadow_replay_dataset(
        rows, tag_map, max_stale_seconds=30.0
    )
    assert any("max_stale_seconds" in w for w in dataset.diagnostics.warnings)


def test_max_stale_seconds_skipped_for_unsubtractable_timestamps() -> None:
    tag_map = _pressure_map(target_id=1)
    rows = [
        {"timestamp": "t0", "PT1": 1.0},
        {"timestamp": "t1", "PT1": 2.0},
    ]
    dataset = build_shadow_replay_dataset(
        rows, tag_map, max_stale_seconds=0.001
    )
    # No subtraction possible between strings: builder must not emit
    # a spurious gap warning.
    assert all(
        "max_stale_seconds" not in w for w in dataset.diagnostics.warnings
    )


def test_max_stale_seconds_must_be_positive() -> None:
    tag_map = _pressure_map()
    with pytest.raises(ValueError, match="max_stale_seconds"):
        build_shadow_replay_dataset([], tag_map, max_stale_seconds=0.0)
    with pytest.raises(ValueError, match="max_stale_seconds"):
        build_shadow_replay_dataset([], tag_map, max_stale_seconds=-1.0)


# ---------------------------------------------------------------------------
# Extra: row shape errors
# ---------------------------------------------------------------------------


def test_non_mapping_row_rejected_strict() -> None:
    tag_map = _pressure_map()
    with pytest.raises(ValueError, match="expected mapping"):
        build_shadow_replay_dataset([("not", "a", "mapping")], tag_map)  # type: ignore[list-item]


def test_non_mapping_row_recorded_non_strict() -> None:
    tag_map = _pressure_map()
    dataset = build_shadow_replay_dataset(
        [("not", "a", "mapping")], tag_map, strict=False  # type: ignore[list-item]
    )
    assert dataset.frames == ()
    assert any("expected mapping" in e for e in dataset.diagnostics.errors)


def test_repeat_build_returns_equal_dataset() -> None:
    tag_map = _pressure_map(target_id=1)
    rows = [
        {"timestamp": 0.0, "PT1": 1.5},
        {"timestamp": 1.0, "PT1": 1.7},
    ]
    a = build_shadow_replay_dataset(rows, tag_map)
    b = build_shadow_replay_dataset(rows, tag_map)
    assert a == b


def test_dataset_frames_are_independent_after_input_mutation() -> None:
    tag_map = _pressure_map(target_id=1)
    rows = [{"timestamp": 0.0, "PT1": 1.5}]
    dataset = build_shadow_replay_dataset(rows, tag_map)
    # Mutate the source row after build; the dataset must remain
    # unaffected (the builder copies axis dicts and the row sequence
    # is iterated only once).
    rows[0]["PT1"] = 999.0
    assert dataset.frames[0].node_pressure[1] == pytest.approx(1.5)
