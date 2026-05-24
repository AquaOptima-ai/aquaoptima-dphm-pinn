"""``TelemetryAxis`` canonical axis token vocabulary (Sprint 42).

The Phase 1 telemetry tag-map adapter (``aquaoptima.dphm.telemetry_tag_map``)
already defines the nine canonical axis tokens used to key
observations and predictions in the dPL calibration loss report and
the shadow runtime harness. The SDK projection here owns *only* the
token vocabulary — no Network-dimension validation, no unit
conversion, no per-spec validation. Those remain in the Phase 1
runtime module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..base.envelope import ContractError


CANONICAL_TELEMETRY_AXES: frozenset[str] = frozenset(
    {
        "node_pressure",
        "node_demand",
        "node_level",
        "node_status",
        "edge_flow",
        "edge_pump_speed",
        "edge_status",
        "edge_power",
        "edge_valve_position",
    }
)


@dataclass(frozen=True)
class TelemetryAxis:
    """Frozen wrapper around a canonical axis token.

    The wrapper exists so consumers can reason about ``TelemetryAxis``
    as a named contract value with a deterministic JSON shape rather
    than a bare string literal. Construction rejects unknown tokens.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise ContractError(
                f"TelemetryAxis.value must be a string, got "
                f"{type(self.value).__name__}"
            )
        if self.value not in CANONICAL_TELEMETRY_AXES:
            raise ContractError(
                f"TelemetryAxis.value {self.value!r} is not a canonical "
                f"telemetry axis token; allowed tokens: "
                f"{sorted(CANONICAL_TELEMETRY_AXES)}"
            )

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TelemetryAxis":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"TelemetryAxis.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        if "value" not in data:
            raise ContractError(
                "TelemetryAxis.from_dict missing required field 'value'"
            )
        unknown = set(data.keys()) - {"value"}
        if unknown:
            raise ContractError(
                f"TelemetryAxis received unknown fields: {sorted(unknown)}"
            )
        return cls(value=str(data["value"]))
