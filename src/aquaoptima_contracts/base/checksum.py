"""``Checksum`` envelope-identity contract (Sprint 42).

A frozen ``(algorithm, hex_digest, size_bytes)`` record. Validation
rejects unknown algorithms, malformed hex digests, and negative
sizes. The Sprint 42 SDK does not compute checksums here — the
record only carries a pre-computed digest. The Phase 1 runtime
modules continue to compute sha256 digests via stdlib ``hashlib``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .envelope import ContractError


ALLOWED_CHECKSUM_ALGORITHMS: frozenset[str] = frozenset({"sha256", "sha512"})

_ALGORITHM_DIGEST_LENGTH: Mapping[str, int] = {"sha256": 64, "sha512": 128}

_LOWERCASE_HEX_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]+$")


_REQUIRED_FIELDS: tuple[str, ...] = ("algorithm", "hex_digest", "size_bytes")


@dataclass(frozen=True)
class Checksum:
    """Frozen, hashable checksum record.

    Attributes
    ----------
    algorithm
        Lowercase identifier from :data:`ALLOWED_CHECKSUM_ALGORITHMS`.
    hex_digest
        Lowercase hex digest of the matching length for ``algorithm``.
    size_bytes
        Non-negative byte length of the artifact the digest was
        computed over.
    """

    algorithm: str
    hex_digest: str
    size_bytes: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.algorithm, str)
            or self.algorithm not in ALLOWED_CHECKSUM_ALGORITHMS
        ):
            raise ContractError(
                f"Checksum.algorithm must be one of "
                f"{sorted(ALLOWED_CHECKSUM_ALGORITHMS)}, got "
                f"{self.algorithm!r}"
            )
        if not isinstance(self.hex_digest, str) or not self.hex_digest:
            raise ContractError("Checksum.hex_digest must be a non-empty string")
        expected_len = _ALGORITHM_DIGEST_LENGTH[self.algorithm]
        if len(self.hex_digest) != expected_len:
            raise ContractError(
                f"Checksum.hex_digest length {len(self.hex_digest)} does not "
                f"match expected length {expected_len} for {self.algorithm!r}"
            )
        if _LOWERCASE_HEX_RE.match(self.hex_digest) is None:
            raise ContractError(
                "Checksum.hex_digest must be a lowercase hex string"
            )
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise ContractError(
                f"Checksum.size_bytes must be int, got "
                f"{type(self.size_bytes).__name__}"
            )
        if self.size_bytes < 0:
            raise ContractError(
                f"Checksum.size_bytes must be non-negative, got "
                f"{self.size_bytes}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "hex_digest": self.hex_digest,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Checksum":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"Checksum.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = [name for name in _REQUIRED_FIELDS if name not in data]
        if missing:
            raise ContractError(
                f"Checksum missing required fields: {missing}"
            )
        unknown = set(data.keys()) - set(_REQUIRED_FIELDS)
        if unknown:
            raise ContractError(
                f"Checksum received unknown fields: {sorted(unknown)}"
            )
        return cls(
            algorithm=str(data["algorithm"]),
            hex_digest=str(data["hex_digest"]),
            size_bytes=int(data["size_bytes"]),
        )
