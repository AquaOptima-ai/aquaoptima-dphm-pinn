"""Projections from Phase 1 telemetry JSON documents into SDK shapes.

These helpers translate between the operator-facing Phase 1 fixture
schema (``{"tag", "target_type", "target_id", "measurement", "unit",
"role", "description"}``) and the canonical Sprint 42 SDK shapes.

The Sprint 42 SDK does NOT absorb the Phase 1 runtime validators —
it only computes the canonical axis token for downstream consumers
that do not have a runtime ``Network`` in scope. Invalid inputs raise
:class:`ContractError`; the runtime continues to be the authority for
in-network validation.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..base.envelope import ContractError
from .tag_map import TelemetryTagMap, TelemetryTagMapDiagnostics, TelemetryTagSpec


# (target_type, measurement) -> canonical axis token. Mirrors the
# Phase 1 ``_AXIS_TABLE`` in ``aquaoptima.dphm.telemetry_tag_map``,
# but the SDK only needs the projection — the runtime keeps the
# authoritative table.
_PHASE1_AXIS_TABLE: Mapping[tuple[str, str], str] = {
    ("NODE", "pressure"): "node_pressure",
    ("NODE", "demand"): "node_demand",
    ("NODE", "level"): "node_level",
    ("NODE", "status"): "node_status",
    ("EDGE", "flow"): "edge_flow",
    ("EDGE", "pump_speed"): "edge_pump_speed",
    ("EDGE", "status"): "edge_status",
    ("EDGE", "power"): "edge_power",
    ("EDGE", "valve_position"): "edge_valve_position",
}


def project_phase1_tag_map_document(
    document: Any,
) -> TelemetryTagMap:
    """Project a Phase 1 tag-map JSON document into an SDK
    :class:`TelemetryTagMap`.

    The document must be a mapping with a ``"tags"`` list (the Phase 1
    fixture shape). Bare-list documents are not accepted at the SDK
    boundary — the SDK projection deliberately keeps the contract
    narrower than the Phase 1 loader.
    """

    if not isinstance(document, Mapping):
        raise ContractError(
            f"project_phase1_tag_map_document requires a mapping, got "
            f"{type(document).__name__}"
        )
    if "tags" not in document:
        raise ContractError(
            "project_phase1_tag_map_document: document must contain 'tags'"
        )
    raw_tags = document["tags"]
    if not isinstance(raw_tags, list):
        raise ContractError(
            "project_phase1_tag_map_document: 'tags' must be a list"
        )

    specs: list[TelemetryTagSpec] = []
    for index, row in enumerate(raw_tags):
        if not isinstance(row, Mapping):
            raise ContractError(
                f"project_phase1_tag_map_document: tags[{index}] must be a "
                f"mapping, got {type(row).__name__}"
            )
        required = {"tag", "target_type", "target_id", "measurement", "unit"}
        missing = required - set(row.keys())
        if missing:
            raise ContractError(
                f"project_phase1_tag_map_document: tags[{index}] missing "
                f"fields {sorted(missing)}"
            )
        target_type = str(row["target_type"]).strip().upper()
        measurement = str(row["measurement"]).strip().lower()
        axis = _PHASE1_AXIS_TABLE.get((target_type, measurement))
        if axis is None:
            raise ContractError(
                f"project_phase1_tag_map_document: tags[{index}] "
                f"(target_type={target_type!r}, measurement={measurement!r}) "
                f"does not map to a canonical SDK axis"
            )
        role = str(row.get("role", "observed")).strip().lower()
        spec = TelemetryTagSpec(
            tag=str(row["tag"]),
            axis=axis,
            target_id=int(row["target_id"]),
            unit=str(row["unit"]).strip(),
            role=role,
            description=str(row.get("description", "")),
        )
        specs.append(spec)

    return TelemetryTagMap(
        tags=tuple(specs),
        diagnostics=TelemetryTagMapDiagnostics(),
    )
