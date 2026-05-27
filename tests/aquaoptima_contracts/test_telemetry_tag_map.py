"""TDD — telemetry tag-map SDK projections (Sprint 42).

Acceptance: the SDK ``TelemetryTagSpec`` / ``TelemetryTagMap`` /
``TelemetryTagMapDiagnostics`` types capture the *shape* of the
Phase 1 tag-map artifact. The Sprint 42 SDK does NOT absorb the
Network-dimension validator or the unit-conversion table; the
runtime keeps that. The projection helper from a Phase 1 tag-map
JSON document round-trips through ``dump_canonical_json``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aquaoptima_contracts import (
    ContractError,
    TelemetryTagMap,
    TelemetryTagMapDiagnostics,
    TelemetryTagSpec,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.telemetry.adapters import (
    project_phase1_tag_map_document,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_FIXTURE = (
    REPO_ROOT
    / "src"
    / "aquaoptima_contracts"
    / "fixtures"
    / "phase1_shadow"
    / "tag_map.json"
)


def test_minimal_tag_spec_round_trip() -> None:
    spec = TelemetryTagSpec(
        tag="PT_J1",
        axis="node_pressure",
        target_id=0,
        unit="m",
        role="observed",
    )
    raw = dump_canonical_json(spec)
    decoded = load_canonical_json(raw)
    assert decoded["tag"] == "PT_J1"
    assert decoded["axis"] == "node_pressure"
    assert decoded["target_id"] == 0
    restored = TelemetryTagSpec.from_dict(decoded)
    assert restored == spec


def test_tag_spec_description_default_empty() -> None:
    spec = TelemetryTagSpec(
        tag="PT_J2",
        axis="node_pressure",
        target_id=1,
        unit="m",
        role="observed",
    )
    decoded = load_canonical_json(dump_canonical_json(spec))
    assert decoded["description"] == ""


def test_tag_spec_rejects_unknown_axis() -> None:
    with pytest.raises(ContractError):
        TelemetryTagSpec(
            tag="X",
            axis="not_an_axis",
            target_id=0,
            unit="m",
            role="observed",
        )


def test_tag_spec_rejects_negative_target_id() -> None:
    with pytest.raises(ContractError):
        TelemetryTagSpec(
            tag="X",
            axis="node_pressure",
            target_id=-1,
            unit="m",
            role="observed",
        )


def test_tag_spec_rejects_empty_tag() -> None:
    with pytest.raises(ContractError):
        TelemetryTagSpec(
            tag="",
            axis="node_pressure",
            target_id=0,
            unit="m",
            role="observed",
        )


def test_tag_spec_rejects_unknown_role() -> None:
    with pytest.raises(ContractError):
        TelemetryTagSpec(
            tag="X",
            axis="node_pressure",
            target_id=0,
            unit="m",
            role="control_target",
        )


def test_telemetry_tag_map_default_empty() -> None:
    diagnostics = TelemetryTagMapDiagnostics()
    tag_map = TelemetryTagMap(tags=(), diagnostics=diagnostics)
    decoded = load_canonical_json(dump_canonical_json(tag_map))
    assert decoded == {
        "tags": [],
        "diagnostics": {"warnings": [], "errors": []},
    }


def test_telemetry_tag_map_round_trips_with_diagnostics() -> None:
    spec = TelemetryTagSpec(
        tag="FT_P1",
        axis="edge_flow",
        target_id=0,
        unit="m3/s",
        role="observed",
    )
    diagnostics = TelemetryTagMapDiagnostics(
        warnings=("tag count is small",),
        errors=(),
    )
    tag_map = TelemetryTagMap(tags=(spec,), diagnostics=diagnostics)
    raw = dump_canonical_json(tag_map)
    decoded = load_canonical_json(raw)
    restored = TelemetryTagMap.from_dict(decoded)
    assert restored == tag_map


def test_project_phase1_tag_map_document_matches_sdk_fixture() -> None:
    raw_text = SDK_FIXTURE.read_text(encoding="utf-8")
    document = load_canonical_json(raw_text)
    tag_map = project_phase1_tag_map_document(document)
    assert {spec.tag for spec in tag_map.tags} == {
        "PT_J1",
        "PT_J2",
        "FT_P1",
        "FT_P2",
    }
    for spec in tag_map.tags:
        assert spec.role == "observed"
    # The projection helper does not own the unit-conversion table — it
    # only verifies the canonical axis tokens.
    axis_by_tag = {spec.tag: spec.axis for spec in tag_map.tags}
    assert axis_by_tag["PT_J1"] == "node_pressure"
    assert axis_by_tag["FT_P1"] == "edge_flow"


def test_project_phase1_tag_map_document_rejects_non_mapping() -> None:
    with pytest.raises(ContractError):
        project_phase1_tag_map_document([])  # type: ignore[arg-type]


def test_project_phase1_tag_map_document_rejects_missing_tags() -> None:
    with pytest.raises(ContractError):
        project_phase1_tag_map_document({"something_else": []})
