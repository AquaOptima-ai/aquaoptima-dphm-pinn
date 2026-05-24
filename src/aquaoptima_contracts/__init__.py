"""AquaOptima Shared Contracts / SDK (Sprint 41 MVP).

This package owns versioned schemas, the canonical safety vocabulary,
capability declarations, deterministic JSON helpers, and the golden
fixture harness shared by every deployable (Edge Runtime, AI /
Optimization Server, Operations Console) in Phase 2+.

The Sprint 41 surface is intentionally minimal: ``SchemaVersion``,
``ContractEnvelope``, ``SafetyFlagSet``, ``CapabilityDeclaration``,
``CapabilityRequirement``, ``evaluate_capability_gate``, and the
deterministic JSON helpers. No HTTP, no database, no runtime
evaluation, no live OT binding, no PLC/PAC/SCADA write, no command
emission, no setpoint output, no control-loop closure. The SDK does
not import any ``aquaoptima.*`` module.
"""

from .base.envelope import (
    ALLOWED_SCHEMA_FAMILIES,
    ALLOWED_CREATED_BY_COMPONENTS,
    ContractEnvelope,
    ContractError,
)
from .base.identifiers import ArtifactReference
from .base.serialization import (
    dump_canonical_json,
    load_canonical_json,
    write_canonical_json,
)
from .base.validation import (
    is_lowercase_snake_case_token,
    validate_token,
)
from .safety.capability_gates import (
    ALLOWED_CAPABILITY_TOKENS,
    FORBIDDEN_CAPABILITY_TOKENS,
    CapabilityDeclaration,
    CapabilityGateResult,
    CapabilityRequirement,
    CapabilityTokenError,
    evaluate_capability_gate,
)
from .safety.flags import (
    CANONICAL_SAFETY_FLAG_TOKENS,
    SafetyFlagError,
    SafetyFlagSet,
)
from .safety.vocabulary import (
    FORBIDDEN_VOCABULARY,
    contains_forbidden_token,
)
from .version import SDK_VERSION, SDK_VERSION_STRING, SchemaVersion

__all__ = [
    "ALLOWED_CAPABILITY_TOKENS",
    "ALLOWED_CREATED_BY_COMPONENTS",
    "ALLOWED_SCHEMA_FAMILIES",
    "ArtifactReference",
    "CANONICAL_SAFETY_FLAG_TOKENS",
    "CapabilityDeclaration",
    "CapabilityGateResult",
    "CapabilityRequirement",
    "CapabilityTokenError",
    "ContractEnvelope",
    "ContractError",
    "FORBIDDEN_CAPABILITY_TOKENS",
    "FORBIDDEN_VOCABULARY",
    "SDK_VERSION",
    "SDK_VERSION_STRING",
    "SafetyFlagError",
    "SafetyFlagSet",
    "SchemaVersion",
    "contains_forbidden_token",
    "dump_canonical_json",
    "evaluate_capability_gate",
    "is_lowercase_snake_case_token",
    "load_canonical_json",
    "validate_token",
    "write_canonical_json",
]
