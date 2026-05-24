"""Envelope-identity reference types.

Sprint 41 shipped the minimal ``kind`` / ``id`` / ``version`` triple
for :class:`ArtifactReference`. Sprint 42 adds the optional
``checksum`` (:class:`Checksum`) and ``uri`` fields described in
``docs/architecture/contracts-inventory.md``. The Sprint 42 surface
remains read-only schema — no filesystem or network IO is performed
when constructing a reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .checksum import Checksum
from .envelope import ContractError


_REQUIRED_FIELDS: tuple[str, ...] = ("kind", "id", "version")
_OPTIONAL_FIELDS: tuple[str, ...] = ("checksum", "uri")


@dataclass(frozen=True)
class ArtifactReference:
    """Reference to an artifact stored outside the contract envelope.

    Attributes
    ----------
    kind
        Non-empty artifact kind token (e.g. ``"shadow_replay_dataset"``,
        ``"file"``). Sprint 42 keeps this free-form; the deployment-
        manifest projection narrows it to the canonical kinds.
    id
        Non-empty logical identifier.
    version
        Non-empty version string.
    checksum
        Optional :class:`Checksum` record. ``None`` is omitted from
        canonical JSON.
    uri
        Optional URI string. ``None`` is omitted from canonical JSON.
    """

    kind: str
    id: str
    version: str
    checksum: Checksum | None = None
    uri: str | None = None

    def __post_init__(self) -> None:
        for name in ("kind", "id", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"ArtifactReference.{name} must be a non-empty string"
                )
        if self.checksum is not None and not isinstance(self.checksum, Checksum):
            raise ValueError(
                "ArtifactReference.checksum, when set, must be a Checksum instance"
            )
        if self.uri is not None and (
            not isinstance(self.uri, str) or not self.uri
        ):
            raise ValueError(
                "ArtifactReference.uri, when set, must be a non-empty string"
            )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "version": self.version,
        }
        if self.checksum is not None:
            out["checksum"] = self.checksum.to_dict()
        if self.uri is not None:
            out["uri"] = self.uri
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactReference":
        if not isinstance(data, Mapping):
            raise ValueError(
                f"ArtifactReference.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {"kind", "id", "version"} - set(data.keys())
        if missing:
            raise ValueError(
                f"ArtifactReference missing fields: {sorted(missing)}"
            )
        unknown = (
            set(data.keys()) - set(_REQUIRED_FIELDS) - set(_OPTIONAL_FIELDS)
        )
        if unknown:
            raise ValueError(
                f"ArtifactReference received unknown fields: {sorted(unknown)}"
            )
        raw_checksum = data.get("checksum")
        checksum: Checksum | None = None
        if raw_checksum is not None:
            if not isinstance(raw_checksum, Mapping):
                raise ValueError(
                    "ArtifactReference.checksum, when present, must be a mapping"
                )
            try:
                checksum = Checksum.from_dict(raw_checksum)
            except ContractError as exc:
                raise ValueError(str(exc)) from exc
        raw_uri = data.get("uri")
        uri = str(raw_uri) if raw_uri is not None else None
        return cls(
            kind=str(data["kind"]),
            id=str(data["id"]),
            version=str(data["version"]),
            checksum=checksum,
            uri=uri,
        )
