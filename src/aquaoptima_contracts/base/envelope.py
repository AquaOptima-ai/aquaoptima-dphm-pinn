"""``ContractEnvelope`` schema metadata wrapper and ``ContractError``.

The envelope is composed into every top-level SDK contract. It carries
schema family, schema name, schema version, SDK version, and optional
traceability fields (``created_at``, ``created_by_component``,
``artifact_id``, ``correlation_id``). The envelope itself never carries
control / write / setpoint payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..version import SchemaVersion


class ContractError(ValueError):
    """Raised when a contract envelope or payload fails validation."""


ALLOWED_SCHEMA_FAMILIES: frozenset[str] = frozenset(
    {
        "safety",
        "envelope",
        "telemetry",
        "dpl_calibration",
        "advisory",
        "operator_review",
        "manifest",
        "edge_capability",
        "model_registry",
        "runtime_report",
        "topology_projection",
    }
)


ALLOWED_CREATED_BY_COMPONENTS: frozenset[str] = frozenset(
    {"edge_runtime", "ai_server", "operations_console", "sdk", "test"}
)


_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_family",
    "schema_name",
    "schema_version",
    "sdk_version",
)


_OPTIONAL_FIELDS: tuple[str, ...] = (
    "created_at",
    "created_by_component",
    "artifact_id",
    "correlation_id",
)


@dataclass(frozen=True)
class ContractEnvelope:
    """Frozen, hashable metadata wrapper carried by every SDK contract.

    Sprint 41 deliberately omits ``provenance`` from the data fields;
    that record lands in Sprint 42. The envelope rejects unknown
    ``schema_family`` values and unknown ``created_by_component``
    values.
    """

    schema_family: str
    schema_name: str
    schema_version: SchemaVersion
    sdk_version: SchemaVersion
    created_at: str | None = None
    created_by_component: str | None = None
    artifact_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.schema_family, str) or not self.schema_family:
            raise ContractError("schema_family must be a non-empty string")
        if self.schema_family not in ALLOWED_SCHEMA_FAMILIES:
            raise ContractError(
                f"schema_family {self.schema_family!r} is not in the "
                f"allowed list ({sorted(ALLOWED_SCHEMA_FAMILIES)})"
            )
        if not isinstance(self.schema_name, str) or not self.schema_name:
            raise ContractError("schema_name must be a non-empty string")
        if not isinstance(self.schema_version, SchemaVersion):
            raise ContractError(
                "schema_version must be a SchemaVersion instance"
            )
        if not isinstance(self.sdk_version, SchemaVersion):
            raise ContractError(
                "sdk_version must be a SchemaVersion instance"
            )
        if self.created_at is not None and (
            not isinstance(self.created_at, str) or not self.created_at
        ):
            raise ContractError(
                "created_at, when set, must be a non-empty ISO-8601 string"
            )
        if self.created_by_component is not None:
            if (
                not isinstance(self.created_by_component, str)
                or self.created_by_component not in ALLOWED_CREATED_BY_COMPONENTS
            ):
                raise ContractError(
                    f"created_by_component {self.created_by_component!r} "
                    f"is not in the allowed list "
                    f"({sorted(ALLOWED_CREATED_BY_COMPONENTS)})"
                )
        for name in ("artifact_id", "correlation_id"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value
            ):
                raise ContractError(
                    f"{name}, when set, must be a non-empty string"
                )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dict.

        Optional fields that are ``None`` are omitted entirely.
        """

        out: dict[str, Any] = {
            "schema_family": self.schema_family,
            "schema_name": self.schema_name,
            "schema_version": self.schema_version.render(),
            "sdk_version": self.sdk_version.render(),
        }
        for name in _OPTIONAL_FIELDS:
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContractEnvelope":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ContractEnvelope.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = [name for name in _REQUIRED_FIELDS if name not in data]
        if missing:
            raise ContractError(
                f"ContractEnvelope missing required fields: {missing}"
            )
        unknown = set(data.keys()) - set(_REQUIRED_FIELDS) - set(_OPTIONAL_FIELDS)
        if unknown:
            raise ContractError(
                f"ContractEnvelope received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            schema_family=str(data["schema_family"]),
            schema_name=str(data["schema_name"]),
            schema_version=SchemaVersion.parse(str(data["schema_version"])),
            sdk_version=SchemaVersion.parse(str(data["sdk_version"])),
            created_at=(
                str(data["created_at"]) if data.get("created_at") is not None
                else None
            ),
            created_by_component=(
                str(data["created_by_component"])
                if data.get("created_by_component") is not None
                else None
            ),
            artifact_id=(
                str(data["artifact_id"])
                if data.get("artifact_id") is not None
                else None
            ),
            correlation_id=(
                str(data["correlation_id"])
                if data.get("correlation_id") is not None
                else None
            ),
        )
