"""Sprint 52 — AMAX vendor PAC software inventory / integration boundary.

Sprint 52 is a concrete artifact sprint, not a replan-only sprint. It
turns the AMAX-5580 user manual, AMAX-5000 I/O manual, and AMAX5580
Linux driver package into deterministic SDK records that define what
AMAX / CODESYS already provides and where AquaOptima must stay as a
sidecar advisory / evidence layer.

The core architecture boundary is intentionally explicit:

* AMAX / CODESYS is the PAC / control substrate.
* AMAX-5000 EtherCAT slice I/O belongs to the CODESYS / PAC layer.
* AquaOptima owns model inference, validation, dry-run proposals,
  advisory evidence, and read-only health/status records.
* AquaOptima does not build a competing PAC runtime, Python EtherCAT
  master, CODESYS project generator, or live protocol client here.

The non-negotiable safety boundary stays explicit:

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- the site PLC / AMAX CODESYS PAC retains direct VFD / pump /
  actuator authority.

All dataclasses are frozen, stdlib-only, deterministic value records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..safety.vocabulary import FORBIDDEN_VOCABULARY, contains_forbidden_token


AMAX_VENDOR_PAC_INVENTORY_ID: str = "amax_5580_vendor_pac_inventory_v1"

SOURCE_KIND_MANUAL: str = "manual"
SOURCE_KIND_DRIVER_PACKAGE: str = "driver_package"
SOURCE_KIND_FINDINGS_NOTE: str = "findings_note"
SOURCE_KINDS: frozenset[str] = frozenset(
    {SOURCE_KIND_MANUAL, SOURCE_KIND_DRIVER_PACKAGE, SOURCE_KIND_FINDINGS_NOTE}
)

PRODUCT_CATEGORY_CONTROL_IPC_BAREBONE: str = "control_ipc_barebone"
PRODUCT_CATEGORY_CODESYS_READY_PAC: str = "codesys_ready_pac"
PRODUCT_CATEGORIES: frozenset[str] = frozenset(
    {PRODUCT_CATEGORY_CONTROL_IPC_BAREBONE, PRODUCT_CATEGORY_CODESYS_READY_PAC}
)

VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL: str = "confirmed_by_manual"
VENDOR_CONFIRMATION_REQUIRED: str = "vendor_confirmation_required"
VENDOR_CONFIRMATION_NOT_PROVEN_BY_DRIVER_PACKAGE: str = (
    "not_proven_by_driver_package"
)
VENDOR_CONFIRMATION_STATUSES: frozenset[str] = frozenset(
    {
        VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL,
        VENDOR_CONFIRMATION_REQUIRED,
        VENDOR_CONFIRMATION_NOT_PROVEN_BY_DRIVER_PACKAGE,
    }
)

OWNER_AMAX_CODESYS_PAC: str = "amax_codesys_pac"
OWNER_SITE_PLC: str = "site_plc"
OWNER_AQUAOPTIMA_SIDECAR: str = "aquaoptima_sidecar"
OWNER_OPERATOR_HMI: str = "operator_hmi"
BOUNDARY_OWNERS: frozenset[str] = frozenset(
    {
        OWNER_AMAX_CODESYS_PAC,
        OWNER_SITE_PLC,
        OWNER_AQUAOPTIMA_SIDECAR,
        OWNER_OPERATOR_HMI,
    }
)

AQUAOPTIMA_MODE_REUSE: str = "reuse"
AQUAOPTIMA_MODE_READ_ONLY_OBSERVE: str = "read_only_observe"
AQUAOPTIMA_MODE_ADVISORY: str = "advisory"
AQUAOPTIMA_MODE_DRY_RUN_EVIDENCE: str = "dry_run_evidence"
AQUAOPTIMA_MODE_OUT_OF_SCOPE: str = "out_of_scope"
AQUAOPTIMA_MODES: frozenset[str] = frozenset(
    {
        AQUAOPTIMA_MODE_REUSE,
        AQUAOPTIMA_MODE_READ_ONLY_OBSERVE,
        AQUAOPTIMA_MODE_ADVISORY,
        AQUAOPTIMA_MODE_DRY_RUN_EVIDENCE,
        AQUAOPTIMA_MODE_OUT_OF_SCOPE,
    }
)

IO_FAMILY_POWER_COUPLER: str = "power_coupler"
IO_FAMILY_ANALOG_IO: str = "analog_io"
IO_FAMILY_DIGITAL_IO: str = "digital_io"
IO_FAMILY_RELAY: str = "relay"
IO_FAMILY_COUNTER_ENCODER: str = "counter_encoder"
IO_FAMILY_TIMESTAMP_IO: str = "timestamp_io"
REQUIRED_IO_FAMILIES: frozenset[str] = frozenset(
    {
        IO_FAMILY_POWER_COUPLER,
        IO_FAMILY_ANALOG_IO,
        IO_FAMILY_DIGITAL_IO,
        IO_FAMILY_RELAY,
        IO_FAMILY_COUNTER_ENCODER,
        IO_FAMILY_TIMESTAMP_IO,
    }
)

REQUIRED_DRIVER_CAPABILITIES: frozenset[str] = frozenset(
    {"watchdog", "hwmon", "led", "gpio", "eeprom"}
)

REQUIRED_BOUNDARY_AREAS: frozenset[str] = frozenset(
    {
        "hard_real_time_control",
        "ethercat_field_io",
        "hmi_visu",
        "interlocks_permissives",
        "actuator_authority",
        "model_inference",
        "validation",
        "dry_run_proposals",
        "advisory_evidence_records",
        "read_only_health_status",
    }
)

_UNSAFE_AQUAOPTIMA_ACTIONS: tuple[str, ...] = (
    "live write",
    "live control",
    "direct actuator",
    "ethercat master",
    "codesys project generation",
    "protocol client write",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ensure_str(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(
            f"{label} must be a non-empty string, got {type(value).__name__}"
        )
    hits = contains_forbidden_token(value)
    if hits:
        raise ContractError(
            f"{label} value contains forbidden vocabulary token(s) "
            f"{sorted(hits)}"
        )
    return value


def _ensure_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(
            f"{label} must be a string, got {type(value).__name__}"
        )
    hits = contains_forbidden_token(value)
    if hits:
        raise ContractError(
            f"{label} value contains forbidden vocabulary token(s) "
            f"{sorted(hits)}"
        )
    return value


def _ensure_str_tuple(value: Any, *, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ContractError(
            f"{label} must be a tuple of strings, got a bare string"
        )
    if not isinstance(value, tuple):
        raise ContractError(
            f"{label} must be a tuple, got {type(value).__name__}"
        )
    coerced: list[str] = []
    for item in value:
        coerced.append(_ensure_string(item, label=f"{label} item"))
    return tuple(coerced)


def _ensure_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(
            f"{label} must be a bool, got {type(value).__name__}"
        )
    return value


def _coerce_str_sequence(
    data: Mapping[str, Any], name: str, *, label: str
) -> tuple[str, ...]:
    raw = data.get(name, ()) or ()
    if isinstance(raw, (str, bytes)):
        raise ContractError(
            f"{label}.{name} must be a sequence of strings, got a bare string"
        )
    if not isinstance(raw, Sequence):
        raise ContractError(f"{label}.{name} must be a sequence")
    return tuple(str(item) for item in raw)


def _reject_forbidden_keys(data: Mapping[str, Any], *, label: str) -> None:
    forbidden_hits = set(data.keys()) & FORBIDDEN_VOCABULARY
    if forbidden_hits:
        raise ContractError(
            f"{label} received forbidden vocabulary field name(s): "
            f"{sorted(forbidden_hits)}"
        )


def _mapping_get_str(data: Mapping[str, Any], name: str, default: str = "") -> str:
    return str(data.get(name, default))


# ---------------------------------------------------------------------------
# source records
# ---------------------------------------------------------------------------


_SOURCE_FIELDS: tuple[str, ...] = (
    "document_id",
    "title",
    "edition_or_version",
    "source_kind",
    "reference",
    "checksum",
    "notes",
)


@dataclass(frozen=True)
class AMAXVendorEvidenceSource:
    """Frozen source record for one AMAX vendor evidence artifact."""

    document_id: str
    title: str
    edition_or_version: str
    source_kind: str
    reference: str
    checksum: str = ""
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(self.document_id, label="AMAXVendorEvidenceSource.document_id")
        _ensure_str(self.title, label="AMAXVendorEvidenceSource.title")
        _ensure_str(
            self.edition_or_version,
            label="AMAXVendorEvidenceSource.edition_or_version",
        )
        _ensure_str(self.source_kind, label="AMAXVendorEvidenceSource.source_kind")
        if self.source_kind not in SOURCE_KINDS:
            raise ContractError(
                f"AMAXVendorEvidenceSource.source_kind {self.source_kind!r} "
                f"is not allowed"
            )
        _ensure_str(self.reference, label="AMAXVendorEvidenceSource.reference")
        _ensure_string(self.checksum, label="AMAXVendorEvidenceSource.checksum")
        object.__setattr__(
            self,
            "notes",
            _ensure_str_tuple(self.notes, label="AMAXVendorEvidenceSource.notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "edition_or_version": self.edition_or_version,
            "source_kind": self.source_kind,
            "reference": self.reference,
            "checksum": self.checksum,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXVendorEvidenceSource":
        if not isinstance(data, Mapping):
            raise ContractError("AMAXVendorEvidenceSource.from_dict requires mapping")
        _reject_forbidden_keys(data, label="AMAXVendorEvidenceSource")
        unknown = set(data.keys()) - set(_SOURCE_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXVendorEvidenceSource received unknown fields: {sorted(unknown)}"
            )
        missing = {"document_id", "title", "edition_or_version", "source_kind", "reference"} - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXVendorEvidenceSource missing fields: {sorted(missing)}"
            )
        return cls(
            document_id=str(data["document_id"]),
            title=str(data["title"]),
            edition_or_version=str(data["edition_or_version"]),
            source_kind=str(data["source_kind"]),
            reference=str(data["reference"]),
            checksum=str(data.get("checksum", "")),
            notes=_coerce_str_sequence(data, "notes", label="AMAXVendorEvidenceSource"),
        )


# ---------------------------------------------------------------------------
# product offering records
# ---------------------------------------------------------------------------


_PRODUCT_FIELDS: tuple[str, ...] = (
    "offering_id",
    "category",
    "part_numbers",
    "cpu_ram_storage",
    "os",
    "nvram_mram",
    "software_bundle",
    "source_evidence_ids",
    "vendor_confirmation_status",
    "notes",
)


@dataclass(frozen=True)
class AMAXProductOffering:
    """Frozen AMAX product-offering row from the vendor manual."""

    offering_id: str
    category: str
    part_numbers: tuple[str, ...]
    cpu_ram_storage: str
    os: str
    nvram_mram: str
    software_bundle: str
    source_evidence_ids: tuple[str, ...] = ()
    vendor_confirmation_status: str = VENDOR_CONFIRMATION_REQUIRED
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(self.offering_id, label="AMAXProductOffering.offering_id")
        _ensure_str(self.category, label="AMAXProductOffering.category")
        if self.category not in PRODUCT_CATEGORIES:
            raise ContractError(
                f"AMAXProductOffering.category {self.category!r} is not allowed"
            )
        object.__setattr__(
            self,
            "part_numbers",
            _ensure_str_tuple(self.part_numbers, label="AMAXProductOffering.part_numbers"),
        )
        _ensure_str(self.cpu_ram_storage, label="AMAXProductOffering.cpu_ram_storage")
        _ensure_str(self.os, label="AMAXProductOffering.os")
        _ensure_string(self.nvram_mram, label="AMAXProductOffering.nvram_mram")
        _ensure_string(self.software_bundle, label="AMAXProductOffering.software_bundle")
        object.__setattr__(
            self,
            "source_evidence_ids",
            _ensure_str_tuple(
                self.source_evidence_ids,
                label="AMAXProductOffering.source_evidence_ids",
            ),
        )
        _ensure_str(
            self.vendor_confirmation_status,
            label="AMAXProductOffering.vendor_confirmation_status",
        )
        if self.vendor_confirmation_status not in VENDOR_CONFIRMATION_STATUSES:
            raise ContractError(
                "AMAXProductOffering.vendor_confirmation_status is not allowed"
            )
        object.__setattr__(
            self,
            "notes",
            _ensure_str_tuple(self.notes, label="AMAXProductOffering.notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "offering_id": self.offering_id,
            "category": self.category,
            "part_numbers": list(self.part_numbers),
            "cpu_ram_storage": self.cpu_ram_storage,
            "os": self.os,
            "nvram_mram": self.nvram_mram,
            "software_bundle": self.software_bundle,
            "source_evidence_ids": list(self.source_evidence_ids),
            "vendor_confirmation_status": self.vendor_confirmation_status,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXProductOffering":
        if not isinstance(data, Mapping):
            raise ContractError("AMAXProductOffering.from_dict requires mapping")
        _reject_forbidden_keys(data, label="AMAXProductOffering")
        unknown = set(data.keys()) - set(_PRODUCT_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXProductOffering received unknown fields: {sorted(unknown)}"
            )
        missing = {
            "offering_id",
            "category",
            "part_numbers",
            "cpu_ram_storage",
            "os",
            "nvram_mram",
            "software_bundle",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXProductOffering missing fields: {sorted(missing)}"
            )
        return cls(
            offering_id=str(data["offering_id"]),
            category=str(data["category"]),
            part_numbers=_coerce_str_sequence(data, "part_numbers", label="AMAXProductOffering"),
            cpu_ram_storage=str(data["cpu_ram_storage"]),
            os=str(data["os"]),
            nvram_mram=str(data["nvram_mram"]),
            software_bundle=str(data["software_bundle"]),
            source_evidence_ids=_coerce_str_sequence(
                data, "source_evidence_ids", label="AMAXProductOffering"
            ),
            vendor_confirmation_status=str(
                data.get("vendor_confirmation_status", VENDOR_CONFIRMATION_REQUIRED)
            ),
            notes=_coerce_str_sequence(data, "notes", label="AMAXProductOffering"),
        )


# ---------------------------------------------------------------------------
# platform capabilities
# ---------------------------------------------------------------------------


_PLATFORM_FIELDS: tuple[str, ...] = (
    "capability_id",
    "domain",
    "provided_by",
    "access_mode",
    "safety_posture",
    "source_evidence_ids",
    "vendor_confirmation_status",
    "notes",
)


@dataclass(frozen=True)
class AMAXPlatformCapability:
    """Frozen capability row for AMAX platform / driver / CODESYS features."""

    capability_id: str
    domain: str
    provided_by: str
    access_mode: str
    safety_posture: str
    source_evidence_ids: tuple[str, ...] = ()
    vendor_confirmation_status: str = VENDOR_CONFIRMATION_REQUIRED
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for attr in (
            "capability_id",
            "domain",
            "provided_by",
            "access_mode",
            "safety_posture",
            "vendor_confirmation_status",
        ):
            _ensure_str(getattr(self, attr), label=f"AMAXPlatformCapability.{attr}")
        if self.vendor_confirmation_status not in VENDOR_CONFIRMATION_STATUSES:
            raise ContractError(
                "AMAXPlatformCapability.vendor_confirmation_status is not allowed"
            )
        object.__setattr__(
            self,
            "source_evidence_ids",
            _ensure_str_tuple(
                self.source_evidence_ids,
                label="AMAXPlatformCapability.source_evidence_ids",
            ),
        )
        object.__setattr__(
            self,
            "notes",
            _ensure_str_tuple(self.notes, label="AMAXPlatformCapability.notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "domain": self.domain,
            "provided_by": self.provided_by,
            "access_mode": self.access_mode,
            "safety_posture": self.safety_posture,
            "source_evidence_ids": list(self.source_evidence_ids),
            "vendor_confirmation_status": self.vendor_confirmation_status,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXPlatformCapability":
        if not isinstance(data, Mapping):
            raise ContractError("AMAXPlatformCapability.from_dict requires mapping")
        _reject_forbidden_keys(data, label="AMAXPlatformCapability")
        unknown = set(data.keys()) - set(_PLATFORM_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXPlatformCapability received unknown fields: {sorted(unknown)}"
            )
        missing = {"capability_id", "domain", "provided_by", "access_mode", "safety_posture"} - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXPlatformCapability missing fields: {sorted(missing)}"
            )
        return cls(
            capability_id=str(data["capability_id"]),
            domain=str(data["domain"]),
            provided_by=str(data["provided_by"]),
            access_mode=str(data["access_mode"]),
            safety_posture=str(data["safety_posture"]),
            source_evidence_ids=_coerce_str_sequence(
                data, "source_evidence_ids", label="AMAXPlatformCapability"
            ),
            vendor_confirmation_status=str(
                data.get("vendor_confirmation_status", VENDOR_CONFIRMATION_REQUIRED)
            ),
            notes=_coerce_str_sequence(data, "notes", label="AMAXPlatformCapability"),
        )


# ---------------------------------------------------------------------------
# I/O capabilities
# ---------------------------------------------------------------------------


_IO_FIELDS: tuple[str, ...] = (
    "module_family",
    "representative_module_ids",
    "function",
    "signal_type",
    "deterministic_control_relevance",
    "codesys_ethercat_owner",
    "source_evidence_ids",
    "notes",
)


@dataclass(frozen=True)
class AMAX5000IOCapability:
    """Frozen AMAX-5000 EtherCAT slice-I/O capability row."""

    module_family: str
    representative_module_ids: tuple[str, ...]
    function: str
    signal_type: str
    deterministic_control_relevance: str
    codesys_ethercat_owner: str
    source_evidence_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for attr in (
            "module_family",
            "function",
            "signal_type",
            "deterministic_control_relevance",
            "codesys_ethercat_owner",
        ):
            _ensure_str(getattr(self, attr), label=f"AMAX5000IOCapability.{attr}")
        object.__setattr__(
            self,
            "representative_module_ids",
            _ensure_str_tuple(
                self.representative_module_ids,
                label="AMAX5000IOCapability.representative_module_ids",
            ),
        )
        object.__setattr__(
            self,
            "source_evidence_ids",
            _ensure_str_tuple(
                self.source_evidence_ids,
                label="AMAX5000IOCapability.source_evidence_ids",
            ),
        )
        object.__setattr__(
            self,
            "notes",
            _ensure_str_tuple(self.notes, label="AMAX5000IOCapability.notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_family": self.module_family,
            "representative_module_ids": list(self.representative_module_ids),
            "function": self.function,
            "signal_type": self.signal_type,
            "deterministic_control_relevance": self.deterministic_control_relevance,
            "codesys_ethercat_owner": self.codesys_ethercat_owner,
            "source_evidence_ids": list(self.source_evidence_ids),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAX5000IOCapability":
        if not isinstance(data, Mapping):
            raise ContractError("AMAX5000IOCapability.from_dict requires mapping")
        _reject_forbidden_keys(data, label="AMAX5000IOCapability")
        unknown = set(data.keys()) - set(_IO_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAX5000IOCapability received unknown fields: {sorted(unknown)}"
            )
        missing = {
            "module_family",
            "representative_module_ids",
            "function",
            "signal_type",
            "deterministic_control_relevance",
            "codesys_ethercat_owner",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAX5000IOCapability missing fields: {sorted(missing)}"
            )
        return cls(
            module_family=str(data["module_family"]),
            representative_module_ids=_coerce_str_sequence(
                data, "representative_module_ids", label="AMAX5000IOCapability"
            ),
            function=str(data["function"]),
            signal_type=str(data["signal_type"]),
            deterministic_control_relevance=str(data["deterministic_control_relevance"]),
            codesys_ethercat_owner=str(data["codesys_ethercat_owner"]),
            source_evidence_ids=_coerce_str_sequence(
                data, "source_evidence_ids", label="AMAX5000IOCapability"
            ),
            notes=_coerce_str_sequence(data, "notes", label="AMAX5000IOCapability"),
        )


# ---------------------------------------------------------------------------
# integration boundary
# ---------------------------------------------------------------------------


_BOUNDARY_FIELDS: tuple[str, ...] = (
    "responsibility_id",
    "capability_area",
    "owner",
    "aquaoptima_mode",
    "allowed_actions",
    "forbidden_actions",
    "source_evidence_ids",
    "notes",
)


@dataclass(frozen=True)
class AquaOptimaIntegrationBoundary:
    """Frozen reuse-vs-build responsibility row for AquaOptima on AMAX."""

    responsibility_id: str
    capability_area: str
    owner: str
    aquaoptima_mode: str
    allowed_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for attr in (
            "responsibility_id",
            "capability_area",
            "owner",
            "aquaoptima_mode",
        ):
            _ensure_str(getattr(self, attr), label=f"AquaOptimaIntegrationBoundary.{attr}")
        if self.owner not in BOUNDARY_OWNERS:
            raise ContractError("AquaOptimaIntegrationBoundary.owner is not allowed")
        if self.aquaoptima_mode not in AQUAOPTIMA_MODES:
            raise ContractError("AquaOptimaIntegrationBoundary.aquaoptima_mode is not allowed")
        for attr in ("allowed_actions", "forbidden_actions", "source_evidence_ids", "notes"):
            object.__setattr__(
                self,
                attr,
                _ensure_str_tuple(
                    getattr(self, attr), label=f"AquaOptimaIntegrationBoundary.{attr}"
                ),
            )
        if self.owner == OWNER_AQUAOPTIMA_SIDECAR:
            lowered = " ".join(self.allowed_actions).lower()
            for phrase in _UNSAFE_AQUAOPTIMA_ACTIONS:
                if phrase in lowered:
                    raise ContractError(
                        "AquaOptima sidecar allowed_actions include unsafe authority "
                        f"phrase {phrase!r}"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "responsibility_id": self.responsibility_id,
            "capability_area": self.capability_area,
            "owner": self.owner,
            "aquaoptima_mode": self.aquaoptima_mode,
            "allowed_actions": list(self.allowed_actions),
            "forbidden_actions": list(self.forbidden_actions),
            "source_evidence_ids": list(self.source_evidence_ids),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AquaOptimaIntegrationBoundary":
        if not isinstance(data, Mapping):
            raise ContractError("AquaOptimaIntegrationBoundary.from_dict requires mapping")
        _reject_forbidden_keys(data, label="AquaOptimaIntegrationBoundary")
        unknown = set(data.keys()) - set(_BOUNDARY_FIELDS)
        if unknown:
            raise ContractError(
                "AquaOptimaIntegrationBoundary received unknown fields: "
                f"{sorted(unknown)}"
            )
        missing = {"responsibility_id", "capability_area", "owner", "aquaoptima_mode"} - set(data.keys())
        if missing:
            raise ContractError(
                f"AquaOptimaIntegrationBoundary missing fields: {sorted(missing)}"
            )
        return cls(
            responsibility_id=str(data["responsibility_id"]),
            capability_area=str(data["capability_area"]),
            owner=str(data["owner"]),
            aquaoptima_mode=str(data["aquaoptima_mode"]),
            allowed_actions=_coerce_str_sequence(
                data, "allowed_actions", label="AquaOptimaIntegrationBoundary"
            ),
            forbidden_actions=_coerce_str_sequence(
                data, "forbidden_actions", label="AquaOptimaIntegrationBoundary"
            ),
            source_evidence_ids=_coerce_str_sequence(
                data, "source_evidence_ids", label="AquaOptimaIntegrationBoundary"
            ),
            notes=_coerce_str_sequence(data, "notes", label="AquaOptimaIntegrationBoundary"),
        )


# ---------------------------------------------------------------------------
# aggregate + diagnostics
# ---------------------------------------------------------------------------


_INVENTORY_FIELDS: tuple[str, ...] = (
    "inventory_id",
    "sources",
    "product_offerings",
    "platform_capabilities",
    "io_capabilities",
    "integration_boundaries",
    "safety_notes",
)


@dataclass(frozen=True)
class AMAXVendorPACInventory:
    """Frozen Sprint 52 AMAX vendor PAC inventory aggregate."""

    inventory_id: str
    sources: tuple[AMAXVendorEvidenceSource, ...]
    product_offerings: tuple[AMAXProductOffering, ...]
    platform_capabilities: tuple[AMAXPlatformCapability, ...]
    io_capabilities: tuple[AMAX5000IOCapability, ...]
    integration_boundaries: tuple[AquaOptimaIntegrationBoundary, ...]
    safety_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(self.inventory_id, label="AMAXVendorPACInventory.inventory_id")
        _ensure_typed_tuple(self.sources, AMAXVendorEvidenceSource, "AMAXVendorPACInventory.sources")
        _ensure_typed_tuple(self.product_offerings, AMAXProductOffering, "AMAXVendorPACInventory.product_offerings")
        _ensure_typed_tuple(self.platform_capabilities, AMAXPlatformCapability, "AMAXVendorPACInventory.platform_capabilities")
        _ensure_typed_tuple(self.io_capabilities, AMAX5000IOCapability, "AMAXVendorPACInventory.io_capabilities")
        _ensure_typed_tuple(self.integration_boundaries, AquaOptimaIntegrationBoundary, "AMAXVendorPACInventory.integration_boundaries")
        object.__setattr__(
            self,
            "safety_notes",
            _ensure_str_tuple(self.safety_notes, label="AMAXVendorPACInventory.safety_notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "inventory_id": self.inventory_id,
            "sources": [entry.to_dict() for entry in self.sources],
            "product_offerings": [entry.to_dict() for entry in self.product_offerings],
            "platform_capabilities": [entry.to_dict() for entry in self.platform_capabilities],
            "io_capabilities": [entry.to_dict() for entry in self.io_capabilities],
            "integration_boundaries": [entry.to_dict() for entry in self.integration_boundaries],
            "safety_notes": list(self.safety_notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXVendorPACInventory":
        if not isinstance(data, Mapping):
            raise ContractError("AMAXVendorPACInventory.from_dict requires mapping")
        _reject_forbidden_keys(data, label="AMAXVendorPACInventory")
        unknown = set(data.keys()) - set(_INVENTORY_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXVendorPACInventory received unknown fields: {sorted(unknown)}"
            )
        missing = {
            "inventory_id",
            "sources",
            "product_offerings",
            "platform_capabilities",
            "io_capabilities",
            "integration_boundaries",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXVendorPACInventory missing fields: {sorted(missing)}"
            )
        return cls(
            inventory_id=str(data["inventory_id"]),
            sources=tuple(
                AMAXVendorEvidenceSource.from_dict(entry)
                for entry in data.get("sources", ())
            ),
            product_offerings=tuple(
                AMAXProductOffering.from_dict(entry)
                for entry in data.get("product_offerings", ())
            ),
            platform_capabilities=tuple(
                AMAXPlatformCapability.from_dict(entry)
                for entry in data.get("platform_capabilities", ())
            ),
            io_capabilities=tuple(
                AMAX5000IOCapability.from_dict(entry)
                for entry in data.get("io_capabilities", ())
            ),
            integration_boundaries=tuple(
                AquaOptimaIntegrationBoundary.from_dict(entry)
                for entry in data.get("integration_boundaries", ())
            ),
            safety_notes=_coerce_str_sequence(data, "safety_notes", label="AMAXVendorPACInventory"),
        )


@dataclass(frozen=True)
class AMAXVendorPACInventoryDiagnostics:
    """Warnings / errors for the Sprint 52 vendor PAC inventory."""

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "warnings",
            _ensure_str_tuple(self.warnings, label="AMAXVendorPACInventoryDiagnostics.warnings"),
        )
        object.__setattr__(
            self,
            "errors",
            _ensure_str_tuple(self.errors, label="AMAXVendorPACInventoryDiagnostics.errors"),
        )

    @property
    def is_clean(self) -> bool:
        return not self.warnings and not self.errors

    def to_dict(self) -> dict[str, list[str]]:
        return {"warnings": list(self.warnings), "errors": list(self.errors)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXVendorPACInventoryDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                "AMAXVendorPACInventoryDiagnostics.from_dict requires mapping"
            )
        _reject_forbidden_keys(data, label="AMAXVendorPACInventoryDiagnostics")
        return cls(
            warnings=_coerce_str_sequence(
                data, "warnings", label="AMAXVendorPACInventoryDiagnostics"
            ),
            errors=_coerce_str_sequence(
                data, "errors", label="AMAXVendorPACInventoryDiagnostics"
            ),
        )


def _ensure_typed_tuple(value: Any, typ: type, label: str) -> None:
    if not isinstance(value, tuple):
        raise ContractError(f"{label} must be a tuple")
    for entry in value:
        if not isinstance(entry, typ):
            raise ContractError(f"{label} contains non-{typ.__name__} entry")


# ---------------------------------------------------------------------------
# canonical defaults
# ---------------------------------------------------------------------------


def _default_sources() -> tuple[AMAXVendorEvidenceSource, ...]:
    return (
        AMAXVendorEvidenceSource(
            document_id="amax_5580_user_manual_ed2",
            title="AMAX-5580 User Manual",
            edition_or_version="Ed.2 FINAL",
            source_kind=SOURCE_KIND_MANUAL,
            reference="AMAX-5580_User_Manual_Ed.2-FINAL.pdf",
            checksum="88c1c1bf5bea54283190c284dcc7b32c68cb3d3a52bc19d1afe5e2c3d9f981de",
            notes=(
                "Manual evidence for Control IPC Barebone and CODESYS Ready PAC product offerings.",
            ),
        ),
        AMAXVendorEvidenceSource(
            document_id="amax_5000_io_manual_ed5",
            title="AMAX-5000 Series EtherCAT Slice I/O Modules User Manual",
            edition_or_version="Ed.5 FINAL",
            source_kind=SOURCE_KIND_MANUAL,
            reference="AMAX-5000_User_Manual_Ed.5_FINAL.pdf",
            checksum="115fd1e2d3763b93b9c534a4452dceec034b41d36cc1ad36658fa70c3327b509",
            notes=(
                "Manual evidence for AMAX-5000 EtherCAT slice I/O families and CODESYS interface examples.",
            ),
        ),
        AMAXVendorEvidenceSource(
            document_id="amax_5580_linux_driver_v2_24_1",
            title="AMAX5580 Linux driver package",
            edition_or_version="v2.24-1",
            source_kind=SOURCE_KIND_DRIVER_PACKAGE,
            reference="AMAX5580 Linux driver.zip",
            checksum="a8d89973d97c3004f384be864cfc94582547fc588bf8c48fc6707db69341d220",
            notes=(
                "EC/platform driver package for brightness, GPIO, LED, common, hwmon, WDT, and EEPROM.",
                "Linux driver package does not prove CODESYS Linux availability or licensing.",
            ),
        ),
    )


def _default_product_offerings() -> tuple[AMAXProductOffering, ...]:
    return (
        AMAXProductOffering(
            offering_id="amax_5580_control_ipc_barebone",
            category=PRODUCT_CATEGORY_CONTROL_IPC_BAREBONE,
            part_numbers=("AMAX-5580-C3000A", "AMAX-5580-54000A", "AMAX-5580-74000A"),
            cpu_ram_storage="Celeron 3955U 4 GB, Core i5-6300U 8 GB, or Core i7-6600U 8 GB; user-configured M.2 storage",
            os="Windows 7/10 support noted by manual; embedded OS can be ordered from Advantech",
            nvram_mram="Optional 2 MB MRAM/NVRAM in internal PCIe-mini slot",
            software_bundle="Control IPC barebone; CODESYS bundle not implied by this offering",
            source_evidence_ids=("amax_5580_user_manual_ed2",),
            vendor_confirmation_status=VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL,
        ),
        AMAXProductOffering(
            offering_id="amax_5580_codesys_ready_pac",
            category=PRODUCT_CATEGORY_CODESYS_READY_PAC,
            part_numbers=("AMAX-658-6CCW00A", "AMAX-658-65CW00A", "AMAX-658-67CW00A"),
            cpu_ram_storage="Celeron 3955U 4 GB or Core i5/i7 8 GB; 128 GB M.2",
            os="Windows 10 LTSC 64-bit",
            nvram_mram="2 MB NVRAM",
            software_bundle="CODESYS V3 Pure Control with Visu(HMI)",
            source_evidence_ids=("amax_5580_user_manual_ed2",),
            vendor_confirmation_status=VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL,
            notes=(
                "Manual-confirmed ready PAC path; package licensing details still need vendor confirmation.",
            ),
        ),
    )


def _default_platform_capabilities() -> tuple[AMAXPlatformCapability, ...]:
    manual = "amax_5580_user_manual_ed2"
    driver = "amax_5580_linux_driver_v2_24_1"
    return (
        AMAXPlatformCapability("watchdog", "watchdog", "AMAX hardware / Advantech EC driver", "platform health observe", "read-only evidence or vendor-managed watchdog", (manual, driver), VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL),
        AMAXPlatformCapability("hwmon", "hwmon", "Advantech EC driver", "platform health observe", "read-only hardware monitor evidence", (driver,), VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL),
        AMAXPlatformCapability("led", "led", "Advantech EC driver", "status indication", "AquaOptima may describe status mapping only; no control authority", (driver,), VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL),
        AMAXPlatformCapability("gpio", "gpio", "Advantech EC driver", "platform GPIO access", "out of scope for AquaOptima default sidecar", (driver,), VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL),
        AMAXPlatformCapability("eeprom", "eeprom", "Advantech EC driver", "device identity / platform metadata", "read-only evidence where available", (driver,), VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL),
        AMAXPlatformCapability("serial", "serial", "AMAX hardware", "RS-232/422/485 physical interface", "site integration only; no live client in SDK", (manual,), VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL),
        AMAXPlatformCapability("dual_power", "power", "AMAX hardware", "main/backup 24 VDC with alarm output", "read-only evidence / deployment checklist input", (manual,), VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL),
        AMAXPlatformCapability("nvram_mram", "storage", "AMAX hardware option / CODESYS Ready PAC", "retain/persistence memory", "PAC/CODESYS persistence; AquaOptima sidecar evidence only", (manual,), VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL),
        AMAXPlatformCapability("intel_i210_gbe_timing", "networking", "AMAX hardware", "Intel i210 GbE with timing features", "network capability evidence; no protocol client implementation", (manual,), VENDOR_CONFIRMATION_CONFIRMED_BY_MANUAL),
        AMAXPlatformCapability("codesys_linux_availability", "codesys_linux", "vendor to confirm", "unknown", "Linux driver package does not prove CODESYS Linux availability", (driver,), VENDOR_CONFIRMATION_NOT_PROVEN_BY_DRIVER_PACKAGE),
    )


def _default_io_capabilities() -> tuple[AMAX5000IOCapability, ...]:
    evidence = ("amax_5000_io_manual_ed5",)
    owner = "AMAX/CODESYS EtherCAT owner"
    return (
        AMAX5000IOCapability(IO_FAMILY_POWER_COUPLER, ("AMAX-5001", "AMAX-5074", "AMAX-5079"), "power input, EtherCAT coupler, and EtherCAT extension", "power and EtherCAT backbone", "required for deterministic I/O topology", owner, evidence),
        AMAX5000IOCapability(IO_FAMILY_ANALOG_IO, ("AMAX-5015", "AMAX-5017C", "AMAX-5017V", "AMAX-5017H", "AMAX-5018", "AMAX-5024"), "RTD, current, voltage, high-speed analog, thermocouple, and analog output", "analog", "field I/O belongs to AMAX/CODESYS", owner, evidence),
        AMAX5000IOCapability(IO_FAMILY_DIGITAL_IO, ("AMAX-5051", "AMAX-5052", "AMAX-5056", "AMAX-5056SO", "AMAX-5057", "AMAX-5057SO"), "isolated digital input and digital output", "digital", "field I/O belongs to AMAX/CODESYS", owner, evidence),
        AMAX5000IOCapability(IO_FAMILY_RELAY, ("AMAX-5060",), "relay with digital input", "relay", "actuation authority remains outside AquaOptima", owner, evidence),
        AMAX5000IOCapability(IO_FAMILY_COUNTER_ENCODER, ("AMAX-5080", "AMAX-5081", "AMAX-5082"), "counter and encoder input", "counter_encoder", "motion and fast counting belong to AMAX/CODESYS", owner, evidence),
        AMAX5000IOCapability(IO_FAMILY_TIMESTAMP_IO, ("AMAX-5051T", "AMAX-5056T"), "timestamp digital input and timestamp digital output", "timestamp", "EtherCAT distributed-clock evidence; AquaOptima consumes audit records only", owner, evidence),
    )


def _default_boundaries() -> tuple[AquaOptimaIntegrationBoundary, ...]:
    evidence = ("amax_5580_user_manual_ed2", "amax_5000_io_manual_ed5")
    forbidden = (
        "no live OT binding",
        "no PLC/PAC/SCADA write",
        "no command emission",
        "no setpoint output",
        "no control-loop closure",
    )
    return (
        AquaOptimaIntegrationBoundary("hard_real_time_control", "hard_real_time_control", OWNER_AMAX_CODESYS_PAC, AQUAOPTIMA_MODE_OUT_OF_SCOPE, ("use AMAX/CODESYS PAC for deterministic control",), forbidden, evidence),
        AquaOptimaIntegrationBoundary("ethercat_field_io", "ethercat_field_io", OWNER_AMAX_CODESYS_PAC, AQUAOPTIMA_MODE_REUSE, ("reuse AMAX-5000 EtherCAT slice I/O through PAC evidence",), forbidden, evidence),
        AquaOptimaIntegrationBoundary("hmi_visu", "hmi_visu", OWNER_OPERATOR_HMI, AQUAOPTIMA_MODE_REUSE, ("reuse CODESYS Visu/HMI or site HMI for operator authority",), forbidden, evidence),
        AquaOptimaIntegrationBoundary("interlocks_permissives", "interlocks_permissives", OWNER_SITE_PLC, AQUAOPTIMA_MODE_OUT_OF_SCOPE, ("site PLC/PAC retains interlocks and permissives",), forbidden, evidence),
        AquaOptimaIntegrationBoundary("actuator_authority", "actuator_authority", OWNER_SITE_PLC, AQUAOPTIMA_MODE_OUT_OF_SCOPE, ("site PLC/PAC retains final VFD pump actuator authority",), forbidden, evidence),
        AquaOptimaIntegrationBoundary("model_inference", "model_inference", OWNER_AQUAOPTIMA_SIDECAR, AQUAOPTIMA_MODE_ADVISORY, ("run dPHM/dPHM-PINN inference as sidecar evidence",), forbidden, evidence),
        AquaOptimaIntegrationBoundary("validation", "validation", OWNER_AQUAOPTIMA_SIDECAR, AQUAOPTIMA_MODE_ADVISORY, ("validate hydraulic consistency and package evidence",), forbidden, evidence),
        AquaOptimaIntegrationBoundary("dry_run_proposals", "dry_run_proposals", OWNER_AQUAOPTIMA_SIDECAR, AQUAOPTIMA_MODE_DRY_RUN_EVIDENCE, ("produce dry-run proposal records for review",), forbidden, evidence),
        AquaOptimaIntegrationBoundary("advisory_evidence_records", "advisory_evidence_records", OWNER_AQUAOPTIMA_SIDECAR, AQUAOPTIMA_MODE_ADVISORY, ("store advisory and audit evidence records",), forbidden, evidence),
        AquaOptimaIntegrationBoundary("read_only_health_status", "read_only_health_status", OWNER_AQUAOPTIMA_SIDECAR, AQUAOPTIMA_MODE_READ_ONLY_OBSERVE, ("observe platform health/status evidence when exposed by approved site interfaces",), forbidden, ("amax_5580_linux_driver_v2_24_1",)),
    )


def default_amax_vendor_pac_inventory() -> AMAXVendorPACInventory:
    """Return the canonical Sprint 52 AMAX vendor PAC inventory."""

    return AMAXVendorPACInventory(
        inventory_id=AMAX_VENDOR_PAC_INVENTORY_ID,
        sources=_default_sources(),
        product_offerings=_default_product_offerings(),
        platform_capabilities=_default_platform_capabilities(),
        io_capabilities=_default_io_capabilities(),
        integration_boundaries=_default_boundaries(),
        safety_notes=(
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "no control-loop closure",
            "AMAX/CODESYS is the PAC/control substrate; AquaOptima is a sidecar advisory/evidence layer.",
        ),
    )


def diagnose_amax_vendor_pac_inventory(
    inventory: AMAXVendorPACInventory,
) -> AMAXVendorPACInventoryDiagnostics:
    """Diagnose required Sprint 52 vendor PAC inventory coverage."""

    if not isinstance(inventory, AMAXVendorPACInventory):
        raise ContractError("diagnose_amax_vendor_pac_inventory requires AMAXVendorPACInventory")
    warnings: list[str] = []
    errors: list[str] = []

    source_ids = {entry.document_id for entry in inventory.sources}
    for required in {
        "amax_5580_user_manual_ed2",
        "amax_5000_io_manual_ed5",
        "amax_5580_linux_driver_v2_24_1",
    }:
        if required not in source_ids:
            errors.append(f"missing required evidence source {required}")

    if not any(
        entry.category == PRODUCT_CATEGORY_CODESYS_READY_PAC
        for entry in inventory.product_offerings
    ):
        errors.append("missing CODESYS Ready PAC product offering")
    if not any(
        entry.category == PRODUCT_CATEGORY_CONTROL_IPC_BAREBONE
        for entry in inventory.product_offerings
    ):
        errors.append("missing Control IPC Barebone product offering")

    driver_domains = {entry.domain for entry in inventory.platform_capabilities}
    for domain in sorted(REQUIRED_DRIVER_CAPABILITIES):
        if domain not in driver_domains:
            errors.append(f"missing Linux driver capability {domain}")
    if not any(
        entry.vendor_confirmation_status == VENDOR_CONFIRMATION_NOT_PROVEN_BY_DRIVER_PACKAGE
        and "CODESYS Linux" in " ".join(entry.notes + (entry.safety_posture,))
        for entry in inventory.platform_capabilities
    ):
        errors.append(
            "missing Linux driver caveat: Linux driver package does not prove CODESYS Linux availability"
        )

    io_families = {entry.module_family for entry in inventory.io_capabilities}
    for family in sorted(REQUIRED_IO_FAMILIES):
        if family not in io_families:
            errors.append(f"missing AMAX-5000 I/O family {family}")

    boundary_areas = {entry.capability_area for entry in inventory.integration_boundaries}
    for area in sorted(REQUIRED_BOUNDARY_AREAS):
        if area not in boundary_areas:
            errors.append(f"missing integration boundary area {area}")
    for entry in inventory.integration_boundaries:
        if entry.owner == OWNER_AQUAOPTIMA_SIDECAR:
            lowered = " ".join(entry.allowed_actions).lower()
            for phrase in _UNSAFE_AQUAOPTIMA_ACTIONS:
                if phrase in lowered:
                    errors.append(
                        f"AquaOptima sidecar boundary {entry.responsibility_id} "
                        f"contains unsafe authority phrase {phrase}"
                    )
        if entry.capability_area in {
            "hard_real_time_control",
            "ethercat_field_io",
            "hmi_visu",
            "interlocks_permissives",
            "actuator_authority",
        } and entry.owner == OWNER_AQUAOPTIMA_SIDECAR:
            errors.append(
                f"AquaOptima incorrectly owns PAC/control area {entry.capability_area}"
            )

    safety_text = "\n".join(inventory.safety_notes).lower()
    for phrase in (
        "no live ot binding",
        "no plc/pac/scada write",
        "no command emission",
        "no setpoint output",
    ):
        if phrase not in safety_text:
            warnings.append(f"missing safety phrase {phrase}")

    return AMAXVendorPACInventoryDiagnostics(
        warnings=tuple(warnings), errors=tuple(errors)
    )
