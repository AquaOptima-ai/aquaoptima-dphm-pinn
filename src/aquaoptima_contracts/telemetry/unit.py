"""``UnitSpec`` canonical unit/dimension contract (Sprint 42).

Sprint 42 carries explicit ``name`` + ``dimension`` metadata: no
runtime conversion table lives here, only the bounded canonical
dimension vocabulary that downstream consumers can read off the
``TelemetryTagSpec``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..base.envelope import ContractError


CANONICAL_UNIT_DIMENSIONS: frozenset[str] = frozenset(
    {
        "length",
        "flow",
        "fraction",
        "power",
        "boolean",
        "rate",
        "dimensionless",
    }
)


_REQUIRED_FIELDS: tuple[str, ...] = ("name", "dimension")


@dataclass(frozen=True)
class UnitSpec:
    """Canonical unit + dimension record.

    Attributes
    ----------
    name
        Non-empty unit identifier (e.g. ``"m"``, ``"m3/s"``,
        ``"fraction"``).
    dimension
        Canonical dimension token from
        :data:`CANONICAL_UNIT_DIMENSIONS`.
    """

    name: str
    dimension: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ContractError("UnitSpec.name must be a non-empty string")
        if (
            not isinstance(self.dimension, str)
            or self.dimension not in CANONICAL_UNIT_DIMENSIONS
        ):
            raise ContractError(
                f"UnitSpec.dimension {self.dimension!r} is not in the "
                f"canonical list ({sorted(CANONICAL_UNIT_DIMENSIONS)})"
            )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "dimension": self.dimension}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UnitSpec":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"UnitSpec.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = [name for name in _REQUIRED_FIELDS if name not in data]
        if missing:
            raise ContractError(f"UnitSpec missing required fields: {missing}")
        unknown = set(data.keys()) - set(_REQUIRED_FIELDS)
        if unknown:
            raise ContractError(
                f"UnitSpec received unknown fields: {sorted(unknown)}"
            )
        return cls(name=str(data["name"]), dimension=str(data["dimension"]))
