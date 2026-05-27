"""Convenience constructors for SDK tests.

These helpers exist so test files can stay focused on the assertion
under inspection rather than re-spelling every canonical field.
"""

from __future__ import annotations

from typing import Iterable

from ..base.envelope import ContractEnvelope
from ..safety.capability_gates import (
    ALLOWED_CAPABILITY_TOKENS,
    CapabilityDeclaration,
    CapabilityRequirement,
)
from ..safety.flags import SafetyFlagSet, default_safety_flag_set
from ..version import SDK_VERSION, SchemaVersion


def make_default_safety_flag_set() -> SafetyFlagSet:
    """Return the canonical Sprint 41 safety flag set."""

    return default_safety_flag_set()


def make_envelope(
    *,
    schema_family: str = "safety",
    schema_name: str = "SafetyFlagSet",
    schema_version: SchemaVersion | None = None,
    sdk_version: SchemaVersion | None = None,
    created_at: str | None = None,
    created_by_component: str | None = None,
    artifact_id: str | None = None,
    correlation_id: str | None = None,
) -> ContractEnvelope:
    return ContractEnvelope(
        schema_family=schema_family,
        schema_name=schema_name,
        schema_version=schema_version or SchemaVersion(1, 0, 0),
        sdk_version=sdk_version or SDK_VERSION,
        created_at=created_at,
        created_by_component=created_by_component,
        artifact_id=artifact_id,
        correlation_id=correlation_id,
    )


def make_capability_declaration(
    *,
    component: str = "edge_runtime",
    declared: Iterable[str] | None = None,
    sdk_version: SchemaVersion | None = None,
) -> CapabilityDeclaration:
    return CapabilityDeclaration(
        component=component,
        declared=frozenset(declared if declared is not None else ALLOWED_CAPABILITY_TOKENS),
        sdk_version=sdk_version or SDK_VERSION,
    )


def make_capability_requirement(
    *,
    package_id: str = "test-package",
    required: Iterable[str] | None = None,
    sdk_version: SchemaVersion | None = None,
) -> CapabilityRequirement:
    return CapabilityRequirement(
        package_id=package_id,
        required=frozenset(required if required is not None else ()),
        sdk_version=sdk_version or SDK_VERSION,
    )
