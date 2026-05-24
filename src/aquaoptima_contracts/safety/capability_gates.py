"""Capability declaration / requirement types and the deny-by-default gate.

Sprint 41 ships:

* ``ALLOWED_CAPABILITY_TOKENS`` — the thirteen Sprint 41 capabilities
  named in ``docs/safety/capability-model-and-safety-gates.md``;
* ``FORBIDDEN_CAPABILITY_TOKENS`` — alias for the canonical denylist
  in :mod:`aquaoptima_contracts.safety.vocabulary`;
* ``CapabilityDeclaration`` — what an Edge instance advertises;
* ``CapabilityRequirement`` — what a deployment package needs;
* ``evaluate_capability_gate`` — deny-by-default gate that returns the
  set of unmet requirements.

No Edge enforcement code lives here. The gate is a pure value
function; Edge enforcement is Sprint 45 work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ..base.validation import is_lowercase_snake_case_token
from ..version import SchemaVersion
from .vocabulary import FORBIDDEN_VOCABULARY


class CapabilityTokenError(ValueError):
    """Raised when a capability token is unknown or forbidden."""


# Sprint 41 allowed Edge capability tokens. Adding to this list is an
# SDK MINOR bump; repurposing or removing is MAJOR (see
# ``docs/safety/capability-model-and-safety-gates.md``).
ALLOWED_CAPABILITY_TOKENS: frozenset[str] = frozenset(
    {
        "load_signed_or_hashed_package",
        "validate_manifest",
        "validate_checksums",
        "validate_schema_versions",
        "validate_safety_flags",
        "validate_tag_map",
        "run_shadow_replay",
        "run_mock_read",
        "evaluate_advisory_contract",
        "produce_shadow_runtime_report",
        "upload_health_report",
        "upload_audit_event",
        "serve_read_only_status",
    }
)


# Identical to the canonical denylist; named here for capability-side
# clarity. Both sides validate against this set.
FORBIDDEN_CAPABILITY_TOKENS: frozenset[str] = FORBIDDEN_VOCABULARY


_ALLOWED_COMPONENTS: frozenset[str] = frozenset(
    {"edge_runtime", "ai_server", "operations_console", "sdk", "test"}
)


def _validate_capability_tokens(
    tokens: Iterable[str], *, field: str
) -> frozenset[str]:
    if isinstance(tokens, str):
        raise CapabilityTokenError(
            f"{field} must be an iterable of tokens, got a bare string"
        )
    seen: set[str] = set()
    for raw in tokens:
        if not isinstance(raw, str):
            raise CapabilityTokenError(
                f"{field} contains a non-string entry {raw!r}"
            )
        if not is_lowercase_snake_case_token(raw):
            raise CapabilityTokenError(
                f"{field} token {raw!r} is not a lowercase snake_case token"
            )
        if raw in FORBIDDEN_CAPABILITY_TOKENS:
            raise CapabilityTokenError(
                f"{field} token {raw!r} is in the forbidden capability list"
            )
        if raw not in ALLOWED_CAPABILITY_TOKENS:
            raise CapabilityTokenError(
                f"{field} token {raw!r} is not in the allowed capability list"
            )
        seen.add(raw)
    return frozenset(seen)


@dataclass(frozen=True)
class CapabilityDeclaration:
    """What an Edge / component advertises it is allowed to do."""

    component: str
    declared: frozenset[str]
    sdk_version: SchemaVersion

    def __post_init__(self) -> None:
        if not isinstance(self.component, str) or not self.component:
            raise CapabilityTokenError(
                "CapabilityDeclaration.component must be a non-empty string"
            )
        if self.component not in _ALLOWED_COMPONENTS:
            raise CapabilityTokenError(
                f"CapabilityDeclaration.component {self.component!r} is "
                f"not in the allowed list ({sorted(_ALLOWED_COMPONENTS)})"
            )
        if not isinstance(self.sdk_version, SchemaVersion):
            raise CapabilityTokenError(
                "CapabilityDeclaration.sdk_version must be a SchemaVersion"
            )
        normalized = _validate_capability_tokens(
            self.declared, field="CapabilityDeclaration.declared"
        )
        # Reassign through ``object.__setattr__`` because the dataclass
        # is frozen but normalization to a fresh frozenset is harmless
        # and ensures ``frozenset({"a", "b"}) == frozenset({"b", "a"})``
        # hashing semantics.
        object.__setattr__(self, "declared", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "declared": sorted(self.declared),
            "sdk_version": self.sdk_version.render(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityDeclaration":
        if not isinstance(data, Mapping):
            raise CapabilityTokenError(
                "CapabilityDeclaration.from_dict requires a mapping"
            )
        return cls(
            component=str(data["component"]),
            declared=frozenset(str(t) for t in data.get("declared", ())),
            sdk_version=SchemaVersion.parse(str(data["sdk_version"])),
        )


@dataclass(frozen=True)
class CapabilityRequirement:
    """What a deployment package needs to run."""

    package_id: str
    required: frozenset[str]
    sdk_version: SchemaVersion

    def __post_init__(self) -> None:
        if not isinstance(self.package_id, str) or not self.package_id:
            raise CapabilityTokenError(
                "CapabilityRequirement.package_id must be a non-empty string"
            )
        if not isinstance(self.sdk_version, SchemaVersion):
            raise CapabilityTokenError(
                "CapabilityRequirement.sdk_version must be a SchemaVersion"
            )
        normalized = _validate_capability_tokens(
            self.required, field="CapabilityRequirement.required"
        )
        object.__setattr__(self, "required", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "required": sorted(self.required),
            "sdk_version": self.sdk_version.render(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityRequirement":
        if not isinstance(data, Mapping):
            raise CapabilityTokenError(
                "CapabilityRequirement.from_dict requires a mapping"
            )
        return cls(
            package_id=str(data["package_id"]),
            required=frozenset(str(t) for t in data.get("required", ())),
            sdk_version=SchemaVersion.parse(str(data["sdk_version"])),
        )


@dataclass(frozen=True)
class CapabilityGateResult:
    """Pure value returned by :func:`evaluate_capability_gate`.

    Sprint 41 only models the missing-requirement case. Sprint 45 will
    add structured rejection reasons (unknown package, stale SDK
    version, declared / required mismatch beyond a single missing
    capability, etc.).
    """

    allowed: bool
    missing: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise CapabilityTokenError(
                "CapabilityGateResult.allowed must be bool"
            )
        if not isinstance(self.missing, frozenset):
            object.__setattr__(self, "missing", frozenset(self.missing))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "missing": sorted(self.missing),
        }


def evaluate_capability_gate(
    declaration: CapabilityDeclaration,
    requirement: CapabilityRequirement,
) -> CapabilityGateResult:
    """Deny-by-default capability gate.

    Returns a result with ``allowed=True`` only when every required
    capability is in the declaration's declared set. Sprint 41 does
    not check SDK version compatibility on the gate; that is added in
    Sprint 45 once Edge enforcement lands.
    """

    if not isinstance(declaration, CapabilityDeclaration):
        raise TypeError(
            "evaluate_capability_gate: declaration must be a "
            "CapabilityDeclaration"
        )
    if not isinstance(requirement, CapabilityRequirement):
        raise TypeError(
            "evaluate_capability_gate: requirement must be a "
            "CapabilityRequirement"
        )
    missing = frozenset(requirement.required) - frozenset(declaration.declared)
    return CapabilityGateResult(allowed=(len(missing) == 0), missing=missing)
