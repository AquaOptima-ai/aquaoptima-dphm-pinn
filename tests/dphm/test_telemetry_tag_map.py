"""Sprint 34 — telemetry tag-map adapter with canonical telemetry schema.

Sprint 34 adds the first read-only shadow-mode plumbing layer between
operator-facing telemetry tags (sensor IDs, SCADA / historian point
names, control-input setpoints) and the canonical dPHM
:class:`Network` topology imported by Sprints 11-33.

These tests cover, in order:

1. Frozen dataclass surfaces.
2. Empty spec list returns an empty map with empty diagnostics.
3. Dataclass and dict inputs are both accepted.
4. Valid node pressure tag maps to the canonical axis / unit.
5. Valid edge flow tag maps to the canonical axis / unit.
6. Pump speed percent / fraction canonicalisation.
7. Status boolean canonicalisation.
8. Duplicate tag error in strict and non-strict modes.
9. Empty tag error.
10. Unknown target type error.
11. Out-of-range node id error.
12. Out-of-range edge id error.
13. Unknown measurement error.
14. Unknown unit error.
15. Unknown role error.
16. Read-only: input specs and network unchanged.
17. Deterministic ordering of tags and errors.
18. JSON loader list shape.
19. JSON loader object-with-tags shape.
20. JSON loader rejects malformed shape.
21. No SCADA / PLC / PAC write / control path exposed.
22. (Existing test suite passes — verified out-of-band via pytest.)
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    CanonicalTelemetryTag,
    Network,
    TELEMETRY_AXES,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_AXIS_NODE_STATUS,
    TELEMETRY_MEASUREMENTS,
    TELEMETRY_MEASUREMENT_FLOW,
    TELEMETRY_MEASUREMENT_PRESSURE,
    TELEMETRY_MEASUREMENT_PUMP_SPEED,
    TELEMETRY_MEASUREMENT_STATUS,
    TELEMETRY_ROLES,
    TELEMETRY_ROLE_CONTROL_INPUT,
    TELEMETRY_ROLE_OBSERVED,
    TELEMETRY_TARGET_EDGE,
    TELEMETRY_TARGET_NODE,
    TELEMETRY_TARGET_TYPES,
    TelemetryTagMap,
    TelemetryTagMapDiagnostics,
    TelemetryTagSpec,
    build_telemetry_tag_map,
    load_telemetry_tag_map_json,
    make_branch_network,
    make_pump_network,
)
import aquaoptima.dphm as dphm
import aquaoptima.dphm.telemetry_tag_map as telemetry_tag_map_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pressure_spec(tag: str = "PT1", target_id: int = 1) -> TelemetryTagSpec:
    return TelemetryTagSpec(
        tag=tag,
        target_type=TELEMETRY_TARGET_NODE,
        target_id=target_id,
        measurement="pressure",
        unit="m",
    )


def _flow_spec(tag: str = "FT1", target_id: int = 0) -> TelemetryTagSpec:
    return TelemetryTagSpec(
        tag=tag,
        target_type=TELEMETRY_TARGET_EDGE,
        target_id=target_id,
        measurement="flow",
        unit="m3/s",
    )


# ---------------------------------------------------------------------------
# 1. Frozen dataclass surfaces
# ---------------------------------------------------------------------------


def test_dataclasses_are_frozen_and_immutable() -> None:
    spec = _pressure_spec()
    network = make_branch_network()
    tag_map = build_telemetry_tag_map([spec], network)

    canonical = tag_map.tags[0]
    diagnostics = tag_map.diagnostics

    # Every published dataclass must be frozen.
    for instance in (spec, canonical, diagnostics, tag_map):
        cls = type(instance)
        assert dataclasses.is_dataclass(cls)
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen is True, f"{cls.__name__} must be frozen"

    # Assignment to a frozen field raises FrozenInstanceError.
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.tag = "OTHER"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        canonical.tag = "OTHER"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        diagnostics.warnings = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        tag_map.tags = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Empty spec list returns an empty map
# ---------------------------------------------------------------------------


def test_empty_specs_returns_empty_map_with_empty_diagnostics() -> None:
    network = make_branch_network()
    tag_map = build_telemetry_tag_map([], network)
    assert tag_map.tags == ()
    assert tag_map.diagnostics.warnings == ()
    assert tag_map.diagnostics.errors == ()


# ---------------------------------------------------------------------------
# 3. Dataclass and dict inputs both accepted
# ---------------------------------------------------------------------------


def test_dataclass_and_dict_inputs_both_accepted() -> None:
    network = make_branch_network()
    specs = [
        _pressure_spec(tag="PT_DC", target_id=1),
        {
            "tag": "FT_PUMP",
            "target_type": "EDGE",
            "target_id": 0,
            "measurement": "flow",
            "unit": "m3/s",
        },
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    assert tag_map.diagnostics.errors == ()
    assert len(tag_map.tags) == 2
    assert tag_map.tags[0].tag == "PT_DC"
    assert tag_map.tags[1].tag == "FT_PUMP"
    assert tag_map.tags[1].target_type == TELEMETRY_TARGET_EDGE


def test_dict_input_with_unknown_key_is_rejected() -> None:
    network = make_branch_network()
    with pytest.raises(ValueError, match="unknown field"):
        build_telemetry_tag_map(
            [
                {
                    "tag": "PT1",
                    "target_type": "NODE",
                    "target_id": 1,
                    "measurement": "pressure",
                    "unit": "m",
                    "color": "red",
                }
            ],
            network,
        )


def test_dict_input_missing_required_key_is_rejected() -> None:
    network = make_branch_network()
    with pytest.raises(ValueError, match="missing required field"):
        build_telemetry_tag_map(
            [
                {
                    "tag": "PT1",
                    "target_type": "NODE",
                    "target_id": 1,
                    "measurement": "pressure",
                    # 'unit' missing
                }
            ],
            network,
        )


# ---------------------------------------------------------------------------
# 4. Valid node pressure tag → canonical axis / unit
# ---------------------------------------------------------------------------


def test_node_pressure_tag_canonical_axis_and_unit() -> None:
    network = make_branch_network()
    tag_map = build_telemetry_tag_map([_pressure_spec("PT_DC", 1)], network)
    assert len(tag_map.tags) == 1
    canonical = tag_map.tags[0]
    assert canonical.tag == "PT_DC"
    assert canonical.target_type == TELEMETRY_TARGET_NODE
    assert canonical.target_id == 1
    assert canonical.measurement == TELEMETRY_MEASUREMENT_PRESSURE
    assert canonical.unit == "m"
    assert canonical.canonical_unit == "m"
    assert canonical.role == TELEMETRY_ROLE_OBSERVED
    assert canonical.axis == TELEMETRY_AXIS_NODE_PRESSURE


def test_node_pressure_alternate_units_canonicalise_to_m() -> None:
    network = make_branch_network()
    specs = [
        TelemetryTagSpec("PT_BAR", TELEMETRY_TARGET_NODE, 1, "pressure", "bar"),
        TelemetryTagSpec("PT_PSI", TELEMETRY_TARGET_NODE, 2, "pressure", "psi"),
        TelemetryTagSpec("PT_KPA", TELEMETRY_TARGET_NODE, 3, "pressure", "kpa"),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    assert [t.canonical_unit for t in tag_map.tags] == ["m", "m", "m"]


# ---------------------------------------------------------------------------
# 5. Valid edge flow tag → canonical axis / unit
# ---------------------------------------------------------------------------


def test_edge_flow_tag_canonical_axis_and_unit() -> None:
    network = make_branch_network()
    tag_map = build_telemetry_tag_map([_flow_spec("FT_PUMP", 0)], network)
    canonical = tag_map.tags[0]
    assert canonical.target_type == TELEMETRY_TARGET_EDGE
    assert canonical.target_id == 0
    assert canonical.measurement == TELEMETRY_MEASUREMENT_FLOW
    assert canonical.canonical_unit == "m3/s"
    assert canonical.axis == TELEMETRY_AXIS_EDGE_FLOW


def test_edge_flow_alternate_units_canonicalise_to_m3_s() -> None:
    network = make_branch_network()
    specs = [
        TelemetryTagSpec("FT_LPS", TELEMETRY_TARGET_EDGE, 0, "flow", "l/s"),
        TelemetryTagSpec("FT_GPM", TELEMETRY_TARGET_EDGE, 1, "flow", "gpm"),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    assert [t.canonical_unit for t in tag_map.tags] == ["m3/s", "m3/s"]


# ---------------------------------------------------------------------------
# 6. Pump speed percent / fraction canonicalisation
# ---------------------------------------------------------------------------


def test_pump_speed_percent_and_fraction_canonicalise_to_fraction() -> None:
    network = make_pump_network()
    specs = [
        TelemetryTagSpec(
            "PUMP_FRAC",
            TELEMETRY_TARGET_EDGE,
            0,
            "pump_speed",
            "fraction",
            role=TELEMETRY_ROLE_CONTROL_INPUT,
        ),
        TelemetryTagSpec(
            "PUMP_PCT",
            TELEMETRY_TARGET_EDGE,
            0,
            "pump_speed",
            "percent",
            role=TELEMETRY_ROLE_OBSERVED,
        ),
    ]
    # Duplicate target_id is permitted; only tag uniqueness is enforced.
    tag_map = build_telemetry_tag_map(specs, network, strict=False)
    assert tag_map.diagnostics.errors == ()
    canonical_units = [t.canonical_unit for t in tag_map.tags]
    axes = [t.axis for t in tag_map.tags]
    assert canonical_units == ["fraction", "fraction"]
    assert axes == [TELEMETRY_AXIS_EDGE_PUMP_SPEED, TELEMETRY_AXIS_EDGE_PUMP_SPEED]


def test_pump_speed_rpm_canonicalises_to_fraction_unit_only() -> None:
    network = make_pump_network()
    tag_map = build_telemetry_tag_map(
        [TelemetryTagSpec("PUMP_RPM", TELEMETRY_TARGET_EDGE, 0, "pump_speed", "rpm")],
        network,
    )
    canonical = tag_map.tags[0]
    assert canonical.canonical_unit == "fraction"
    assert canonical.unit == "rpm"


# ---------------------------------------------------------------------------
# 7. Status boolean canonicalisation
# ---------------------------------------------------------------------------


def test_status_boolean_canonicalisation() -> None:
    network = make_pump_network()
    specs = [
        TelemetryTagSpec("STAT_BOOL", TELEMETRY_TARGET_EDGE, 0, "status", "boolean"),
        TelemetryTagSpec("STAT_BOOL2", TELEMETRY_TARGET_EDGE, 1, "status", "bool"),
        TelemetryTagSpec("STAT_01", TELEMETRY_TARGET_EDGE, 0, "status", "0/1"),
        TelemetryTagSpec("STAT_NODE", TELEMETRY_TARGET_NODE, 0, "status", "boolean"),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    assert [t.canonical_unit for t in tag_map.tags] == ["boolean", "boolean", "boolean", "boolean"]
    assert tag_map.tags[-1].axis == TELEMETRY_AXIS_NODE_STATUS


# ---------------------------------------------------------------------------
# 8. Duplicate tag error in strict and non-strict modes
# ---------------------------------------------------------------------------


def test_duplicate_tag_raises_in_strict_mode() -> None:
    network = make_branch_network()
    specs = [_pressure_spec("PT1", 1), _pressure_spec("PT1", 2)]
    with pytest.raises(ValueError, match="duplicate tag"):
        build_telemetry_tag_map(specs, network, strict=True)


def test_duplicate_tag_records_error_in_non_strict_mode() -> None:
    network = make_branch_network()
    specs = [_pressure_spec("PT1", 1), _pressure_spec("PT1", 2)]
    tag_map = build_telemetry_tag_map(specs, network, strict=False)
    assert len(tag_map.tags) == 1
    assert tag_map.tags[0].target_id == 1
    assert len(tag_map.diagnostics.errors) == 1
    assert "duplicate tag" in tag_map.diagnostics.errors[0]


# ---------------------------------------------------------------------------
# 9. Empty tag error
# ---------------------------------------------------------------------------


def test_empty_tag_rejected() -> None:
    network = make_branch_network()
    for empty in ("", "   "):
        with pytest.raises(ValueError, match="tag is empty"):
            build_telemetry_tag_map(
                [TelemetryTagSpec(empty, TELEMETRY_TARGET_NODE, 1, "pressure", "m")],
                network,
            )


# ---------------------------------------------------------------------------
# 10. Unknown target type error
# ---------------------------------------------------------------------------


def test_unknown_target_type_rejected() -> None:
    network = make_branch_network()
    with pytest.raises(ValueError, match="unknown target_type"):
        build_telemetry_tag_map(
            [TelemetryTagSpec("PT1", "WALRUS", 1, "pressure", "m")],
            network,
        )


# ---------------------------------------------------------------------------
# 11. Out-of-range node id error
# ---------------------------------------------------------------------------


def test_out_of_range_node_id_rejected() -> None:
    network = make_branch_network()
    with pytest.raises(ValueError, match="node target_id"):
        build_telemetry_tag_map([_pressure_spec("PT1", network.num_nodes)], network)
    with pytest.raises(ValueError, match="node target_id"):
        build_telemetry_tag_map([_pressure_spec("PT1", -1)], network)


# ---------------------------------------------------------------------------
# 12. Out-of-range edge id error
# ---------------------------------------------------------------------------


def test_out_of_range_edge_id_rejected() -> None:
    network = make_branch_network()
    n_edges = int(network.edge_index.shape[1])
    with pytest.raises(ValueError, match="edge target_id"):
        build_telemetry_tag_map([_flow_spec("FT1", n_edges)], network)
    with pytest.raises(ValueError, match="edge target_id"):
        build_telemetry_tag_map([_flow_spec("FT1", -1)], network)


# ---------------------------------------------------------------------------
# 13. Unknown measurement error
# ---------------------------------------------------------------------------


def test_unknown_measurement_rejected() -> None:
    network = make_branch_network()
    with pytest.raises(ValueError, match="unknown measurement"):
        build_telemetry_tag_map(
            [TelemetryTagSpec("PT1", TELEMETRY_TARGET_NODE, 1, "vibration", "g")],
            network,
        )


def test_measurement_target_type_mismatch_rejected() -> None:
    # pressure is node-only; declaring it on an edge must fail.
    network = make_branch_network()
    with pytest.raises(ValueError, match="not valid for target_type"):
        build_telemetry_tag_map(
            [TelemetryTagSpec("PT1", TELEMETRY_TARGET_EDGE, 0, "pressure", "m")],
            network,
        )
    # flow is edge-only; declaring it on a node must fail.
    with pytest.raises(ValueError, match="not valid for target_type"):
        build_telemetry_tag_map(
            [TelemetryTagSpec("FT1", TELEMETRY_TARGET_NODE, 1, "flow", "m3/s")],
            network,
        )


# ---------------------------------------------------------------------------
# 14. Unknown unit error
# ---------------------------------------------------------------------------


def test_unknown_unit_rejected() -> None:
    network = make_branch_network()
    with pytest.raises(ValueError, match="unit"):
        build_telemetry_tag_map(
            [TelemetryTagSpec("PT1", TELEMETRY_TARGET_NODE, 1, "pressure", "furlong")],
            network,
        )


def test_empty_unit_rejected() -> None:
    network = make_branch_network()
    with pytest.raises(ValueError, match="unit"):
        build_telemetry_tag_map(
            [TelemetryTagSpec("PT1", TELEMETRY_TARGET_NODE, 1, "pressure", "  ")],
            network,
        )


# ---------------------------------------------------------------------------
# 15. Unknown role error
# ---------------------------------------------------------------------------


def test_unknown_role_rejected() -> None:
    network = make_branch_network()
    with pytest.raises(ValueError, match="unknown role"):
        build_telemetry_tag_map(
            [
                TelemetryTagSpec(
                    "PT1",
                    TELEMETRY_TARGET_NODE,
                    1,
                    "pressure",
                    "m",
                    role="overlord",
                )
            ],
            network,
        )


# ---------------------------------------------------------------------------
# 16. Read-only: input specs and network unchanged
# ---------------------------------------------------------------------------


def test_builder_does_not_mutate_inputs() -> None:
    network = make_branch_network()
    edge_index_before = network.edge_index.clone()
    demands_before = network.demands.clone()
    num_nodes_before = network.num_nodes

    specs = [
        _pressure_spec("PT1", 1),
        _flow_spec("FT1", 0),
        TelemetryTagSpec(
            "PUMP_SPEED",
            TELEMETRY_TARGET_EDGE,
            0,
            "pump_speed",
            "fraction",
            role=TELEMETRY_ROLE_CONTROL_INPUT,
        ),
    ]
    specs_copy = copy.deepcopy(specs)

    tag_map = build_telemetry_tag_map(specs, network)
    assert len(tag_map.tags) == 3

    # Specs unchanged (frozen dataclasses cannot be mutated; check equality
    # against the deep-copied snapshot anyway to make the contract explicit).
    assert specs == specs_copy

    # Network tensors and dimensions unchanged.
    assert torch.equal(network.edge_index, edge_index_before)
    assert torch.equal(network.demands, demands_before)
    assert network.num_nodes == num_nodes_before


# ---------------------------------------------------------------------------
# 17. Deterministic ordering of tags and errors
# ---------------------------------------------------------------------------


def test_deterministic_ordering_of_valid_and_invalid_specs() -> None:
    network = make_branch_network()
    specs = [
        _pressure_spec("PT1", 1),
        TelemetryTagSpec("BAD_TYPE", "ZONK", 1, "pressure", "m"),
        _flow_spec("FT1", 0),
        TelemetryTagSpec("BAD_UNIT", TELEMETRY_TARGET_NODE, 1, "pressure", "furlong"),
        _pressure_spec("PT2", 2),
    ]

    tag_map_a = build_telemetry_tag_map(specs, network, strict=False)
    tag_map_b = build_telemetry_tag_map(specs, network, strict=False)
    assert tag_map_a == tag_map_b
    assert [t.tag for t in tag_map_a.tags] == ["PT1", "FT1", "PT2"]
    assert len(tag_map_a.diagnostics.errors) == 2
    assert "BAD_TYPE" in tag_map_a.diagnostics.errors[0]
    assert "BAD_UNIT" in tag_map_a.diagnostics.errors[1]


# ---------------------------------------------------------------------------
# 18-20. JSON loader
# ---------------------------------------------------------------------------


def test_load_telemetry_tag_map_json_list_shape(tmp_path: Path) -> None:
    network = make_branch_network()
    rows = [
        {
            "tag": "PT_DC_01",
            "target_type": "NODE",
            "target_id": 1,
            "measurement": "pressure",
            "unit": "m",
        },
        {
            "tag": "FT_PUMP_01",
            "target_type": "EDGE",
            "target_id": 0,
            "measurement": "flow",
            "unit": "l/s",
        },
    ]
    path = tmp_path / "tags_list.json"
    path.write_text(json.dumps(rows))
    tag_map = load_telemetry_tag_map_json(path, network)
    assert [t.tag for t in tag_map.tags] == ["PT_DC_01", "FT_PUMP_01"]
    assert tag_map.tags[1].canonical_unit == "m3/s"


def test_load_telemetry_tag_map_json_object_shape(tmp_path: Path) -> None:
    network = make_branch_network()
    payload = {
        "tags": [
            {
                "tag": "PT_DC_01",
                "target_type": "NODE",
                "target_id": 1,
                "measurement": "pressure",
                "unit": "bar",
                "role": "observed",
            }
        ]
    }
    path = tmp_path / "tags_object.json"
    path.write_text(json.dumps(payload))
    tag_map = load_telemetry_tag_map_json(path, network)
    assert len(tag_map.tags) == 1
    assert tag_map.tags[0].canonical_unit == "m"


def test_load_telemetry_tag_map_json_rejects_malformed_shapes(tmp_path: Path) -> None:
    network = make_branch_network()

    scalar_path = tmp_path / "scalar.json"
    scalar_path.write_text(json.dumps(42))
    with pytest.raises(ValueError, match="top-level JSON"):
        load_telemetry_tag_map_json(scalar_path, network)

    object_without_tags_path = tmp_path / "no_tags.json"
    object_without_tags_path.write_text(json.dumps({"items": []}))
    with pytest.raises(ValueError, match="must contain a 'tags' key"):
        load_telemetry_tag_map_json(object_without_tags_path, network)

    bad_tags_path = tmp_path / "tags_not_list.json"
    bad_tags_path.write_text(json.dumps({"tags": "not-a-list"}))
    with pytest.raises(ValueError, match="'tags' must be a list"):
        load_telemetry_tag_map_json(bad_tags_path, network)

    bad_row_path = tmp_path / "bad_row.json"
    bad_row_path.write_text(json.dumps(["not-an-object"]))
    with pytest.raises(ValueError, match="must be an object"):
        load_telemetry_tag_map_json(bad_row_path, network)


def test_load_telemetry_tag_map_json_non_strict_propagates_errors(
    tmp_path: Path,
) -> None:
    network = make_branch_network()
    rows = [
        {
            "tag": "PT_OK",
            "target_type": "NODE",
            "target_id": 1,
            "measurement": "pressure",
            "unit": "m",
        },
        {
            "tag": "PT_BAD",
            "target_type": "NODE",
            "target_id": 1,
            "measurement": "pressure",
            "unit": "furlong",
        },
    ]
    path = tmp_path / "tags.json"
    path.write_text(json.dumps(rows))
    tag_map = load_telemetry_tag_map_json(path, network, strict=False)
    assert [t.tag for t in tag_map.tags] == ["PT_OK"]
    assert any("furlong" in e for e in tag_map.diagnostics.errors)


# ---------------------------------------------------------------------------
# 21. No SCADA / PLC / PAC write / control path exposed
# ---------------------------------------------------------------------------


def test_no_write_or_control_path_exposed() -> None:
    """Sprint 34 is read-only.

    The module must not expose any *callable* whose name suggests live
    ingestion, a control surface, a setpoint write, or a historian
    binding. The Sprint 4.5 telemetry abstraction lives in
    :mod:`aquaoptima.dataio`; the Sprint 34 dPHM-side adapter is
    explicitly *not* a live binding.

    Descriptive metadata strings such as
    :data:`TELEMETRY_ROLE_CONTROL_INPUT` are *labels* a caller may
    attach to a read-only tag spec (e.g. to mark that a pump-speed
    setpoint *would be* a control input under a future live binding);
    they are not callable surfaces and do not constitute a write
    path. The test therefore filters to functions and methods only.
    """
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
    for name in telemetry_tag_map_module.__all__:
        symbol = getattr(telemetry_tag_map_module, name)
        if not callable(symbol):
            continue
        # Dataclass classes are callable (they are constructors). The
        # Sprint 34 dataclasses are passive containers and not write
        # paths; the substring screen is meant for I/O-style helpers.
        if isinstance(symbol, type):
            continue
        lname = name.lower()
        for needle in forbidden_substrings:
            assert needle not in lname, (
                f"telemetry_tag_map exposes callable {name!r} which "
                f"contains forbidden substring {needle!r}"
            )

    # The dPHM package-level re-exports for Sprint 34 must agree.
    for name in (
        "build_telemetry_tag_map",
        "load_telemetry_tag_map_json",
        "TelemetryTagSpec",
        "CanonicalTelemetryTag",
        "TelemetryTagMap",
        "TelemetryTagMapDiagnostics",
    ):
        assert name in dphm.__all__

    # The module must not import any networking / live-ingestion
    # stdlib modules. (Sprint 34 only uses ``json`` + ``pathlib`` +
    # the local ``Network`` dataclass.)
    import sys

    for forbidden_module in (
        "socket",
        "asyncio",
        "ssl",
        "urllib.request",
        "http.client",
        "smtplib",
    ):
        attr = forbidden_module.split(".")[0]
        # The module under test only exposes ``json`` and ``Path``;
        # asserting absence of a forbidden attribute on the module is
        # the strongest read-only signal we can give without
        # introspecting every transitive import.
        assert not hasattr(telemetry_tag_map_module, attr) or attr in {"json"}, (
            f"telemetry_tag_map unexpectedly references stdlib module {forbidden_module!r}"
        )
    # Sanity: every public name in __all__ is actually present on the module.
    for name in telemetry_tag_map_module.__all__:
        assert hasattr(telemetry_tag_map_module, name)


# ---------------------------------------------------------------------------
# Extra coverage: canonical sets surface and equality of repeated builds.
# ---------------------------------------------------------------------------


def test_canonical_constants_are_stable_strings() -> None:
    assert set(TELEMETRY_TARGET_TYPES) == {"NODE", "EDGE"}
    assert TELEMETRY_MEASUREMENT_PRESSURE in TELEMETRY_MEASUREMENTS
    assert TELEMETRY_MEASUREMENT_FLOW in TELEMETRY_MEASUREMENTS
    assert TELEMETRY_MEASUREMENT_PUMP_SPEED in TELEMETRY_MEASUREMENTS
    assert TELEMETRY_MEASUREMENT_STATUS in TELEMETRY_MEASUREMENTS
    assert TELEMETRY_ROLE_OBSERVED in TELEMETRY_ROLES
    assert TELEMETRY_ROLE_CONTROL_INPUT in TELEMETRY_ROLES
    # Every (target_type, measurement) pair must produce an axis from
    # TELEMETRY_AXES.
    network = make_pump_network()
    valid_pairs = [
        (TELEMETRY_TARGET_NODE, "pressure", "m"),
        (TELEMETRY_TARGET_NODE, "demand", "l/s"),
        (TELEMETRY_TARGET_NODE, "level", "m"),
        (TELEMETRY_TARGET_NODE, "status", "boolean"),
        (TELEMETRY_TARGET_EDGE, "flow", "m3/s"),
        (TELEMETRY_TARGET_EDGE, "pump_speed", "percent"),
        (TELEMETRY_TARGET_EDGE, "status", "0/1"),
        (TELEMETRY_TARGET_EDGE, "power", "kw"),
        (TELEMETRY_TARGET_EDGE, "valve_position", "percent"),
    ]
    for i, (target_type, measurement, unit) in enumerate(valid_pairs):
        target_id = 0 if target_type == TELEMETRY_TARGET_EDGE else min(i, network.num_nodes - 1)
        spec = TelemetryTagSpec(
            f"TAG_{i}",
            target_type,
            target_id,
            measurement,
            unit,
        )
        tag_map = build_telemetry_tag_map([spec], network)
        assert tag_map.tags[0].axis in TELEMETRY_AXES


def test_repeat_build_returns_equal_map() -> None:
    network = make_branch_network()
    specs = [_pressure_spec("PT1", 1), _flow_spec("FT1", 0)]
    a = build_telemetry_tag_map(specs, network)
    b = build_telemetry_tag_map(specs, network)
    assert a == b
    assert a.tags == b.tags
    assert a.diagnostics == b.diagnostics


def test_default_tag_map_diagnostics_is_empty() -> None:
    tag_map = TelemetryTagMap()
    assert tag_map.tags == ()
    assert tag_map.diagnostics == TelemetryTagMapDiagnostics()
    assert tag_map.diagnostics.warnings == ()
    assert tag_map.diagnostics.errors == ()


def test_canonical_tag_field_set() -> None:
    fields = {f.name for f in dataclasses.fields(CanonicalTelemetryTag)}
    assert fields == {
        "tag",
        "target_type",
        "target_id",
        "measurement",
        "unit",
        "canonical_unit",
        "role",
        "axis",
        "description",
    }
