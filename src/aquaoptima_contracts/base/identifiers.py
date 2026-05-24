"""Skeleton identifier types. Full implementation lands in Sprint 42."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactReference:
    """Reference to an artifact stored outside the contract envelope.

    Sprint 41 ships only the minimal ``kind`` / ``id`` / ``version``
    triple. Sprint 42 adds ``checksum`` and the optional ``uri`` field
    described in ``docs/architecture/contracts-inventory.md``.
    """

    kind: str
    id: str
    version: str

    def __post_init__(self) -> None:
        for name in ("kind", "id", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"ArtifactReference.{name} must be a non-empty string"
                )

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.id, "version": self.version}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactReference":
        if not isinstance(data, dict):
            raise ValueError(
                f"ArtifactReference.from_dict requires dict, got "
                f"{type(data).__name__}"
            )
        missing = {"kind", "id", "version"} - set(data.keys())
        if missing:
            raise ValueError(
                f"ArtifactReference missing fields: {sorted(missing)}"
            )
        return cls(
            kind=str(data["kind"]),
            id=str(data["id"]),
            version=str(data["version"]),
        )
