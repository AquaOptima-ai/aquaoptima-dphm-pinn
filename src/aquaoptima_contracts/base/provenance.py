"""``Provenance`` envelope-identity contract (Sprint 42).

Carries the component that produced an artifact, the component
version, an optional build identifier, and an optional signer
identity string. Sprint 42 stores the signer identity as a string
only; signature verification is out of scope and lands in a later
sprint alongside the Edge package validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .envelope import ContractError


ALLOWED_PROVENANCE_COMPONENTS: frozenset[str] = frozenset(
    {"edge_runtime", "ai_server", "operations_console", "sdk", "test"}
)


_REQUIRED_FIELDS: tuple[str, ...] = ("component", "version")
_OPTIONAL_FIELDS: tuple[str, ...] = ("build_id", "signer_identity")


@dataclass(frozen=True)
class Provenance:
    """Frozen record of the producing component and its version.

    Attributes
    ----------
    component
        Producing component identifier. Must be in
        :data:`ALLOWED_PROVENANCE_COMPONENTS`.
    version
        Non-empty version string for the producing component.
    build_id
        Optional build / CI run identifier. ``None`` is omitted from
        the canonical JSON projection.
    signer_identity
        Optional string identifier for the signer. Sprint 42 stores
        only the identity; signature verification lands later. ``None``
        is omitted from the canonical JSON projection.
    """

    component: str
    version: str
    build_id: str | None = None
    signer_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.component, str) or not self.component:
            raise ContractError("Provenance.component must be a non-empty string")
        if self.component not in ALLOWED_PROVENANCE_COMPONENTS:
            raise ContractError(
                f"Provenance.component {self.component!r} is not in the "
                f"allowed list ({sorted(ALLOWED_PROVENANCE_COMPONENTS)})"
            )
        if not isinstance(self.version, str) or not self.version:
            raise ContractError("Provenance.version must be a non-empty string")
        for name in _OPTIONAL_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                raise ContractError(
                    f"Provenance.{name}, when set, must be a non-empty string"
                )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "component": self.component,
            "version": self.version,
        }
        for name in _OPTIONAL_FIELDS:
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Provenance":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"Provenance.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = [name for name in _REQUIRED_FIELDS if name not in data]
        if missing:
            raise ContractError(
                f"Provenance missing required fields: {missing}"
            )
        unknown = (
            set(data.keys()) - set(_REQUIRED_FIELDS) - set(_OPTIONAL_FIELDS)
        )
        if unknown:
            raise ContractError(
                f"Provenance received unknown fields: {sorted(unknown)}"
            )
        return cls(
            component=str(data["component"]),
            version=str(data["version"]),
            build_id=(
                str(data["build_id"])
                if data.get("build_id") is not None
                else None
            ),
            signer_identity=(
                str(data["signer_identity"])
                if data.get("signer_identity") is not None
                else None
            ),
        )
