"""``TelemetryTagSpec`` / ``TelemetryTagMap`` SDK projections (Sprint 42).

These types capture the *shape* of the Phase 1 tag-map artifact. The
Phase 1 runtime module ``aquaoptima.dphm.telemetry_tag_map`` continues
to own the Network-dimension validator and the unit-conversion
tables. The SDK projection only validates the canonical axis / role
tokens and basic structural fields so that any deployable can read
the artifact without a runtime ``Network`` instance in scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from .axis import CANONICAL_TELEMETRY_AXES


CANONICAL_TELEMETRY_ROLES: frozenset[str] = frozenset(
    {"observed", "control_input", "derived", "quality"}
)


_TAG_SPEC_FIELDS: tuple[str, ...] = (
    "tag",
    "axis",
    "target_id",
    "unit",
    "role",
    "description",
)


@dataclass(frozen=True)
class TelemetryTagSpec:
    """Single tag entry: operator-facing tag, canonical axis, target id.

    Attributes
    ----------
    tag
        Operator-facing tag identifier (e.g. ``"PT_J1"``).
    axis
        Canonical axis token from :data:`CANONICAL_TELEMETRY_AXES`.
    target_id
        Non-negative dPHM node / edge identifier.
    unit
        Unit string used for this tag in source data. The SDK does
        not perform conversion; the Phase 1 runtime owns that.
    role
        Canonical role token from :data:`CANONICAL_TELEMETRY_ROLES`.
    description
        Free-form description; defaults to ``""``.
    """

    tag: str
    axis: str
    target_id: int
    unit: str
    role: str
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.tag, str) or not self.tag:
            raise ContractError("TelemetryTagSpec.tag must be a non-empty string")
        if self.axis not in CANONICAL_TELEMETRY_AXES:
            raise ContractError(
                f"TelemetryTagSpec.axis {self.axis!r} is not a canonical "
                f"telemetry axis"
            )
        if (
            isinstance(self.target_id, bool)
            or not isinstance(self.target_id, int)
        ):
            raise ContractError(
                "TelemetryTagSpec.target_id must be an int"
            )
        if self.target_id < 0:
            raise ContractError(
                f"TelemetryTagSpec.target_id must be non-negative, got "
                f"{self.target_id}"
            )
        if not isinstance(self.unit, str) or not self.unit:
            raise ContractError("TelemetryTagSpec.unit must be a non-empty string")
        if self.role not in CANONICAL_TELEMETRY_ROLES:
            raise ContractError(
                f"TelemetryTagSpec.role {self.role!r} is not a canonical "
                f"telemetry role; allowed: {sorted(CANONICAL_TELEMETRY_ROLES)}"
            )
        if not isinstance(self.description, str):
            raise ContractError("TelemetryTagSpec.description must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "axis": self.axis,
            "target_id": self.target_id,
            "unit": self.unit,
            "role": self.role,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TelemetryTagSpec":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"TelemetryTagSpec.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = [
            name
            for name in ("tag", "axis", "target_id", "unit", "role")
            if name not in data
        ]
        if missing:
            raise ContractError(
                f"TelemetryTagSpec missing required fields: {missing}"
            )
        unknown = set(data.keys()) - set(_TAG_SPEC_FIELDS)
        if unknown:
            raise ContractError(
                f"TelemetryTagSpec received unknown fields: {sorted(unknown)}"
            )
        return cls(
            tag=str(data["tag"]),
            axis=str(data["axis"]),
            target_id=int(data["target_id"]),
            unit=str(data["unit"]),
            role=str(data["role"]),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True)
class TelemetryTagMapDiagnostics:
    """Deterministic warnings / errors tuples for an SDK tag-map.

    The SDK projection does NOT re-run the Phase 1 Network-dimension
    validator. Callers building a Phase 1-derived tag-map can copy the
    Phase 1 diagnostics into this record verbatim.
    """

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("warnings", "errors"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(v, str) for v in value
            ):
                raise ContractError(
                    f"TelemetryTagMapDiagnostics.{name} must be a tuple of strings"
                )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TelemetryTagMapDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"TelemetryTagMapDiagnostics.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        unknown = set(data.keys()) - {"warnings", "errors"}
        if unknown:
            raise ContractError(
                f"TelemetryTagMapDiagnostics received unknown fields: "
                f"{sorted(unknown)}"
            )
        warnings = tuple(str(w) for w in data.get("warnings", ()))
        errors = tuple(str(e) for e in data.get("errors", ()))
        return cls(warnings=warnings, errors=errors)


@dataclass(frozen=True)
class TelemetryTagMap:
    """Frozen SDK projection of a Phase 1 tag-map artifact."""

    tags: tuple[TelemetryTagSpec, ...] = ()
    diagnostics: TelemetryTagMapDiagnostics = field(
        default_factory=TelemetryTagMapDiagnostics
    )

    def __post_init__(self) -> None:
        if not isinstance(self.tags, tuple):
            raise ContractError("TelemetryTagMap.tags must be a tuple")
        for spec in self.tags:
            if not isinstance(spec, TelemetryTagSpec):
                raise ContractError(
                    f"TelemetryTagMap.tags must contain TelemetryTagSpec "
                    f"instances, got {type(spec).__name__}"
                )
        if not isinstance(self.diagnostics, TelemetryTagMapDiagnostics):
            raise ContractError(
                "TelemetryTagMap.diagnostics must be a "
                "TelemetryTagMapDiagnostics instance"
            )
        seen: set[str] = set()
        for spec in self.tags:
            if spec.tag in seen:
                raise ContractError(
                    f"TelemetryTagMap.tags contains duplicate tag {spec.tag!r}"
                )
            seen.add(spec.tag)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tags": [spec.to_dict() for spec in self.tags],
            "diagnostics": self.diagnostics.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TelemetryTagMap":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"TelemetryTagMap.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - {"tags", "diagnostics"}
        if unknown:
            raise ContractError(
                f"TelemetryTagMap received unknown fields: {sorted(unknown)}"
            )
        raw_tags = data.get("tags", ())
        if not isinstance(raw_tags, Sequence) or isinstance(raw_tags, (str, bytes)):
            raise ContractError("TelemetryTagMap.tags must be a sequence")
        tags = tuple(TelemetryTagSpec.from_dict(t) for t in raw_tags)
        diagnostics = TelemetryTagMapDiagnostics.from_dict(
            data.get("diagnostics", {})
        )
        return cls(tags=tags, diagnostics=diagnostics)
