"""``EdgeCapabilityDeclaration`` (Sprint 45).

Pairs a Sprint 41 :class:`CapabilityDeclaration` with an
:class:`EdgeHardwareProfile`. The Sprint 41 capability vocabulary is
already audit-only — direct write / control / setpoint capabilities
live in the canonical forbidden vocabulary and cannot be declared.
The default AMAX edge declaration ships package-validation-only
capabilities (load + validate + checksum + safety-flag review) and
nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..base.envelope import ContractError
from ..safety.capability_gates import (
    CapabilityDeclaration,
    CapabilityTokenError,
)
from ..version import SDK_VERSION, SchemaVersion
from .hardware_profile import EdgeHardwareProfile, amax_5580_cpu_profile


_DECLARATION_FIELDS: tuple[str, ...] = (
    "capability_declaration",
    "hardware_profile",
    "notes",
)


# Canonical AMAX package-validation-only capability token bundle. The
# helper :func:`default_amax_edge_capability_declaration` returns an
# :class:`EdgeCapabilityDeclaration` declaring exactly these tokens —
# no write, no control, no setpoint, no actuation. (Direct
# write/control vocabulary is impossible to declare at all because
# the underlying ``CapabilityDeclaration`` rejects any forbidden
# token at construction.)
_AMAX_PACKAGE_VALIDATION_CAPABILITIES: frozenset[str] = frozenset(
    {
        "load_signed_or_hashed_package",
        "validate_manifest",
        "validate_checksums",
        "validate_schema_versions",
        "validate_safety_flags",
        "validate_tag_map",
    }
)


def default_amax_edge_validation_capabilities() -> frozenset[str]:
    """Return the canonical AMAX package-validation-only capability set.

    The set is intentionally narrow: every token corresponds to a
    Sprint 41 capability used by the deny-by-default package
    validator. No token in this set carries a write / control /
    setpoint / actuation meaning (and the underlying allowed-token
    list cannot include any forbidden vocabulary anyway).
    """
    return _AMAX_PACKAGE_VALIDATION_CAPABILITIES


@dataclass(frozen=True)
class EdgeCapabilityDeclaration:
    """What the AMAX Edge declares it can do, plus the hardware profile.

    Sprint 45 composes the Sprint 41 :class:`CapabilityDeclaration`
    (capability tokens an Edge advertises) with an
    :class:`EdgeHardwareProfile` (architecture / runtime / model
    framework metadata). The dataclass is audit-only; nothing in it
    represents a write, dispatch, actuation, setpoint, or
    control-loop closure surface.

    The non-negotiable boundary stays explicit: the default AMAX
    declaration covers package validation only — no live OT binding,
    no PLC/PAC/SCADA write, no command emission, no setpoint output,
    and no control-loop closure are declared.
    """

    capability_declaration: CapabilityDeclaration
    hardware_profile: EdgeHardwareProfile
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.capability_declaration, CapabilityDeclaration):
            raise ContractError(
                "EdgeCapabilityDeclaration.capability_declaration must be a "
                "CapabilityDeclaration instance"
            )
        if not isinstance(self.hardware_profile, EdgeHardwareProfile):
            raise ContractError(
                "EdgeCapabilityDeclaration.hardware_profile must be an "
                "EdgeHardwareProfile instance"
            )
        if isinstance(self.notes, (str, bytes)):
            raise ContractError(
                "EdgeCapabilityDeclaration.notes must be a tuple of strings"
            )
        if not isinstance(self.notes, tuple):
            raise ContractError(
                "EdgeCapabilityDeclaration.notes must be a tuple"
            )
        for entry in self.notes:
            if not isinstance(entry, str):
                raise ContractError(
                    "EdgeCapabilityDeclaration.notes entries must be strings"
                )

    @property
    def profile_id(self) -> str:
        return self.hardware_profile.profile_id

    @property
    def declared_capabilities(self) -> frozenset[str]:
        return self.capability_declaration.declared

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_declaration": self.capability_declaration.to_dict(),
            "hardware_profile": self.hardware_profile.to_dict(),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "EdgeCapabilityDeclaration":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"EdgeCapabilityDeclaration.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        missing = {"capability_declaration", "hardware_profile"} - set(
            data.keys()
        )
        if missing:
            raise ContractError(
                f"EdgeCapabilityDeclaration missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_DECLARATION_FIELDS)
        if unknown:
            raise ContractError(
                f"EdgeCapabilityDeclaration received unknown fields: "
                f"{sorted(unknown)}"
            )
        cap_raw = data["capability_declaration"]
        if not isinstance(cap_raw, Mapping):
            raise ContractError(
                "EdgeCapabilityDeclaration.capability_declaration must be a "
                "mapping"
            )
        try:
            cap = CapabilityDeclaration.from_dict(cap_raw)
        except CapabilityTokenError as exc:
            raise ContractError(str(exc)) from exc
        profile_raw = data["hardware_profile"]
        if not isinstance(profile_raw, Mapping):
            raise ContractError(
                "EdgeCapabilityDeclaration.hardware_profile must be a mapping"
            )
        profile = EdgeHardwareProfile.from_dict(profile_raw)
        raw_notes = data.get("notes", ()) or ()
        if isinstance(raw_notes, (str, bytes)):
            raise ContractError(
                "EdgeCapabilityDeclaration.notes must be a sequence of strings"
            )
        return cls(
            capability_declaration=cap,
            hardware_profile=profile,
            notes=tuple(str(n) for n in raw_notes),
        )


def default_amax_edge_capability_declaration(
    *,
    sdk_version: SchemaVersion | None = None,
) -> EdgeCapabilityDeclaration:
    """Return the canonical AMAX package-validation-only declaration.

    The declaration pairs the canonical AMAX-5580 CPU profile with
    exactly the package-validation capability bundle returned by
    :func:`default_amax_edge_validation_capabilities`. No write /
    control / setpoint / actuation capability is included; the
    declaration is audit-only.
    """
    version = sdk_version if sdk_version is not None else SDK_VERSION
    capability_declaration = CapabilityDeclaration(
        component="edge_runtime",
        declared=default_amax_edge_validation_capabilities(),
        sdk_version=version,
    )
    return EdgeCapabilityDeclaration(
        capability_declaration=capability_declaration,
        hardware_profile=amax_5580_cpu_profile(),
        notes=(
            "default AMAX-5580 package-validation-only declaration",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "site PLC retains direct VFD / pump / actuator authority",
        ),
    )
