"""SDK package version and ``SchemaVersion`` SemVer helper."""

from __future__ import annotations

import re
from dataclasses import dataclass

SDK_VERSION_STRING: str = "0.1.0"


_SEMVER_RE: re.Pattern[str] = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$"
)


@dataclass(frozen=True, order=True)
class SchemaVersion:
    """SemVer ``MAJOR.MINOR.PATCH`` triple used by every SDK contract.

    Sprint 41 only models the three core integers. Pre-release labels
    and build metadata are intentionally rejected: every shipped
    contract uses a clean ``X.Y.Z`` version, and Sprint 42+ adds the
    deprecation overlap window for major bumps.
    """

    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        for name in ("major", "minor", "patch"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(
                    f"SchemaVersion.{name} must be an int, got "
                    f"{type(value).__name__}"
                )
            if value < 0:
                raise ValueError(
                    f"SchemaVersion.{name} must be non-negative, got {value}"
                )

    @classmethod
    def parse(cls, raw: str) -> "SchemaVersion":
        if not isinstance(raw, str):
            raise ValueError(
                f"SchemaVersion.parse requires str, got {type(raw).__name__}"
            )
        match = _SEMVER_RE.match(raw)
        if match is None:
            raise ValueError(
                f"malformed SemVer string {raw!r}; expected MAJOR.MINOR.PATCH"
            )
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
        )

    def render(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def is_compatible_reader(self, other: "SchemaVersion") -> bool:
        """Return whether ``self`` (a reader) can read documents written
        at version ``other``.

        Sprint 41 reader rule: same-major versions are compatible
        regardless of minor / patch. Different-major versions are
        rejected. Sprint 42+ may add a deprecation overlap window.
        """
        if not isinstance(other, SchemaVersion):
            raise TypeError(
                "is_compatible_reader requires a SchemaVersion, got "
                f"{type(other).__name__}"
            )
        return self.major == other.major


SDK_VERSION: SchemaVersion = SchemaVersion.parse(SDK_VERSION_STRING)
