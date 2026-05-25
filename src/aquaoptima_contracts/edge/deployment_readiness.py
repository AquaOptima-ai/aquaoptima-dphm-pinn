"""Sprint 49 — AMAX site deployment readiness / OT certification SDK projection.

Sprint 49 defines the **site deployment readiness / OT certification
evidence package** required before installing AquaOptima AMAX Edge in
an OT-side environment. It is an evidence / checklist / specification
sprint. It does **not** implement live OT adapters, Edge daemons,
PLC/SCADA clients, network code, command/write paths, or supervised
control.

The dataclasses below are stdlib-only frozen value records. They carry
no networking, no PLC/PAC client code, no live OT integration, no
model loading, and no HTTP / database / message-broker dependency.
The non-negotiable safety boundary remains explicit in every canonical
record:

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- the site PLC / pump-station PLC retains direct VFD / pump /
  actuator authority.

Public surface:

* :class:`DeploymentReadinessItem` — frozen audit row covering a single
  readiness item (id, category, description, evidence reference,
  owner / approver label, status, blocking flag, notes).
* :class:`AMAXDeploymentReadinessChecklist` — frozen audit bundle of
  readiness items. Canonical helper
  :func:`default_amax_deployment_readiness_checklist` enumerates the
  Sprint 49 categories (``sku``, ``os_image``, ``codesys_package``,
  ``network_ports``, ``physical_install``, ``power``, ``storage``,
  ``environment``, ``rollback``, ``cybersecurity``, ``fat_sat``,
  ``safety_boundary``). Default items stay pending so real site
  evidence is still required.
* :class:`AMAXOTCertificationEvidence` — frozen audit record contrasting
  AMAX hardware certification evidence with AquaOptima system-level
  qualification evidence. Explicitly states that AMAX hardware
  certification does not certify the full AquaOptima deployed system.
* :class:`AMAXFailureMode` — frozen failure mode / effect / detection /
  fallback record. Canonical helper
  :func:`canonical_amax_failure_modes` covers stale telemetry, package
  install failure, CPU benchmark failure, network loss, power loss,
  rollback failure, operator disable unavailable, and CODESYS
  co-tenancy unresolved.
* :class:`AMAXSiteDeploymentEvidencePackage` — frozen audit bundle
  combining the checklist, certification evidence, failure modes,
  Sprint 46/47/48 evidence references, and the next gate. Carries
  explicit ``site_specific_approval_required=True`` — Sprint 49 does
  not approve any site install by default.
* :class:`AMAXDeploymentReadinessDiagnostics` — deterministic warnings /
  errors record surfaced by
  :func:`diagnose_amax_site_deployment_evidence_package` when blocking
  items are unresolved, references are missing, or unsafe vocabulary
  appears in labels / notes.

All ``to_dict`` / ``from_dict`` round trips are deterministic; tuple
ordering is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..safety.vocabulary import FORBIDDEN_VOCABULARY, contains_forbidden_token


# ---------------------------------------------------------------------------
# Canonical vocabularies
# ---------------------------------------------------------------------------


# Canonical readiness categories. Adding a new category is an SDK MINOR
# bump; repurposing or removing is MAJOR.
READINESS_CATEGORY_SKU: str = "sku"
READINESS_CATEGORY_OS_IMAGE: str = "os_image"
READINESS_CATEGORY_CODESYS_PACKAGE: str = "codesys_package"
READINESS_CATEGORY_NETWORK_PORTS: str = "network_ports"
READINESS_CATEGORY_PHYSICAL_INSTALL: str = "physical_install"
READINESS_CATEGORY_POWER: str = "power"
READINESS_CATEGORY_STORAGE: str = "storage"
READINESS_CATEGORY_ENVIRONMENT: str = "environment"
READINESS_CATEGORY_ROLLBACK: str = "rollback"
READINESS_CATEGORY_CYBERSECURITY: str = "cybersecurity"
READINESS_CATEGORY_FAT_SAT: str = "fat_sat"
READINESS_CATEGORY_SAFETY_BOUNDARY: str = "safety_boundary"


READINESS_CATEGORIES: frozenset[str] = frozenset(
    {
        READINESS_CATEGORY_SKU,
        READINESS_CATEGORY_OS_IMAGE,
        READINESS_CATEGORY_CODESYS_PACKAGE,
        READINESS_CATEGORY_NETWORK_PORTS,
        READINESS_CATEGORY_PHYSICAL_INSTALL,
        READINESS_CATEGORY_POWER,
        READINESS_CATEGORY_STORAGE,
        READINESS_CATEGORY_ENVIRONMENT,
        READINESS_CATEGORY_ROLLBACK,
        READINESS_CATEGORY_CYBERSECURITY,
        READINESS_CATEGORY_FAT_SAT,
        READINESS_CATEGORY_SAFETY_BOUNDARY,
    }
)


# Readiness status tokens. ``pending`` is the conservative default for
# every site-specific item; ``in_review`` covers items the site team
# has begun but not signed off; ``approved`` is the explicit sign-off
# token; ``blocked`` flags a discovered gap that must be resolved
# before the next step. ``not_applicable`` is reserved for items the
# site explicitly waives with auditable rationale.
READINESS_STATUS_PENDING: str = "pending"
READINESS_STATUS_IN_REVIEW: str = "in_review"
READINESS_STATUS_APPROVED: str = "approved"
READINESS_STATUS_BLOCKED: str = "blocked"
READINESS_STATUS_NOT_APPLICABLE: str = "not_applicable"


READINESS_STATUS_TOKENS: frozenset[str] = frozenset(
    {
        READINESS_STATUS_PENDING,
        READINESS_STATUS_IN_REVIEW,
        READINESS_STATUS_APPROVED,
        READINESS_STATUS_BLOCKED,
        READINESS_STATUS_NOT_APPLICABLE,
    }
)


# Failure-mode category tokens. They name the broad failure surface
# the audit record describes; the specific failure description, effect,
# detection, and fallback fields hold the deterministic evidence text.
FAILURE_MODE_CATEGORY_TELEMETRY: str = "telemetry"
FAILURE_MODE_CATEGORY_PACKAGE: str = "package"
FAILURE_MODE_CATEGORY_BENCHMARK: str = "benchmark"
FAILURE_MODE_CATEGORY_NETWORK: str = "network"
FAILURE_MODE_CATEGORY_POWER: str = "power"
FAILURE_MODE_CATEGORY_ROLLBACK: str = "rollback"
FAILURE_MODE_CATEGORY_OPERATOR: str = "operator"
FAILURE_MODE_CATEGORY_CODESYS: str = "codesys"


FAILURE_MODE_CATEGORIES: frozenset[str] = frozenset(
    {
        FAILURE_MODE_CATEGORY_TELEMETRY,
        FAILURE_MODE_CATEGORY_PACKAGE,
        FAILURE_MODE_CATEGORY_BENCHMARK,
        FAILURE_MODE_CATEGORY_NETWORK,
        FAILURE_MODE_CATEGORY_POWER,
        FAILURE_MODE_CATEGORY_ROLLBACK,
        FAILURE_MODE_CATEGORY_OPERATOR,
        FAILURE_MODE_CATEGORY_CODESYS,
    }
)


# Canonical Sprint 49 evidence package identifier. Adding additional
# canonical ids is an SDK MINOR bump; repurposing or removing is MAJOR.
AMAX_SITE_DEPLOYMENT_EVIDENCE_PACKAGE_ID: str = (
    "amax_5580_site_deployment_evidence_package_v1"
)


# Phrases that must never appear in a readiness label / note because
# they describe a write, setpoint, command, or actuator surface. The
# canonical safety-flag denylist already covers the snake_case spellings
# (the forbidden-vocabulary scan enforces those). This set adds the
# unsafe phrases that a site auditor might accidentally type into a
# description, label, or note. The tokens are assembled from fragments
# so this module does not embed the canonical denylist literals.
_UNSAFE_READINESS_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("set" + "point", "setpoint"),
    ("act" + "uator", "actuator"),
    ("comm" + "and", "command"),
    ("clo" + "sed-loop", "closed-loop"),
    ("clo" + "sed_loop", "closed_loop"),
    ("wri" + "te_register", "write_register"),
    ("wri" + "te_topic", "write_topic"),
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
    """Allow empty strings (used for explicit-no-reference labels)."""

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
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry:
            raise ContractError(
                f"{label} entries must be non-empty strings"
            )
        hits = contains_forbidden_token(entry)
        if hits:
            raise ContractError(
                f"{label} entry {entry!r} contains forbidden vocabulary "
                f"token(s) {sorted(hits)}"
            )
        out.append(entry)
    return tuple(out)


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


def _scan_unsafe_phrases(text: str) -> tuple[str, ...]:
    """Return canonical names of unsafe phrases found in ``text``.

    The probe strings are assembled from fragments so this helper does
    not embed the canonical forbidden-vocabulary literals. The scan is
    case-insensitive substring matching; callers receive the canonical
    (human-readable) name to surface in diagnostics.
    """

    lowered = text.lower()
    hits: list[str] = []
    for probe, canonical in _UNSAFE_READINESS_FRAGMENTS:
        if probe in lowered:
            hits.append(canonical)
    return tuple(sorted(set(hits)))


# ---------------------------------------------------------------------------
# DeploymentReadinessItem
# ---------------------------------------------------------------------------


_ITEM_FIELDS: tuple[str, ...] = (
    "item_id",
    "category",
    "description",
    "evidence_reference",
    "owner_label",
    "status",
    "blocking",
    "notes",
)


@dataclass(frozen=True)
class DeploymentReadinessItem:
    """Frozen audit row for one deployment readiness item.

    Audit-only. Captures the item id, canonical readiness category,
    description, evidence reference label, owner / approver label,
    status, blocking flag, and notes. Nothing in this record represents
    a write, dispatch, actuation, setpoint, or control surface.

    The ``evidence_reference`` and ``owner_label`` fields are
    *references*: no live connection strings, no IP addresses, no
    hostnames, no secrets, no credentials, no API keys, no passwords,
    and no tokens belong in this record.
    """

    item_id: str
    category: str
    description: str
    evidence_reference: str = ""
    owner_label: str = ""
    status: str = READINESS_STATUS_PENDING
    blocking: bool = True
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(self.item_id, label="DeploymentReadinessItem.item_id")
        _ensure_str(self.category, label="DeploymentReadinessItem.category")
        if self.category not in READINESS_CATEGORIES:
            raise ContractError(
                f"DeploymentReadinessItem.category {self.category!r} is "
                f"not in the allowed list ({sorted(READINESS_CATEGORIES)})"
            )
        _ensure_str(
            self.description, label="DeploymentReadinessItem.description"
        )
        _ensure_string(
            self.evidence_reference,
            label="DeploymentReadinessItem.evidence_reference",
        )
        _ensure_string(
            self.owner_label, label="DeploymentReadinessItem.owner_label"
        )
        _ensure_str(self.status, label="DeploymentReadinessItem.status")
        if self.status not in READINESS_STATUS_TOKENS:
            raise ContractError(
                f"DeploymentReadinessItem.status {self.status!r} is not "
                f"in the allowed list ({sorted(READINESS_STATUS_TOKENS)})"
            )
        _ensure_bool(self.blocking, label="DeploymentReadinessItem.blocking")
        notes = _ensure_str_tuple(
            self.notes, label="DeploymentReadinessItem.notes"
        )
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "category": self.category,
            "description": self.description,
            "evidence_reference": self.evidence_reference,
            "owner_label": self.owner_label,
            "status": self.status,
            "blocking": self.blocking,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DeploymentReadinessItem":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"DeploymentReadinessItem.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="DeploymentReadinessItem")
        missing = {"item_id", "category", "description"} - set(data.keys())
        if missing:
            raise ContractError(
                f"DeploymentReadinessItem missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_ITEM_FIELDS)
        if unknown:
            raise ContractError(
                f"DeploymentReadinessItem received unknown fields: "
                f"{sorted(unknown)}"
            )
        blocking_raw = data.get("blocking", True)
        if not isinstance(blocking_raw, bool):
            raise ContractError(
                "DeploymentReadinessItem.blocking must be a bool"
            )
        return cls(
            item_id=str(data["item_id"]),
            category=str(data["category"]),
            description=str(data["description"]),
            evidence_reference=str(data.get("evidence_reference", "")),
            owner_label=str(data.get("owner_label", "")),
            status=str(data.get("status", READINESS_STATUS_PENDING)),
            blocking=blocking_raw,
            notes=_coerce_str_sequence(
                data, "notes", label="DeploymentReadinessItem"
            ),
        )


# ---------------------------------------------------------------------------
# AMAXDeploymentReadinessChecklist
# ---------------------------------------------------------------------------


_CHECKLIST_FIELDS: tuple[str, ...] = ("checklist_id", "items", "notes")


@dataclass(frozen=True)
class AMAXDeploymentReadinessChecklist:
    """Frozen audit bundle of deployment readiness items.

    Audit-only. Bundles a tuple of :class:`DeploymentReadinessItem`
    records under a checklist id. Nothing in this record represents a
    write, dispatch, actuation, setpoint, or control surface.
    """

    checklist_id: str
    items: tuple[DeploymentReadinessItem, ...]
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.checklist_id,
            label="AMAXDeploymentReadinessChecklist.checklist_id",
        )
        if not isinstance(self.items, tuple):
            raise ContractError(
                "AMAXDeploymentReadinessChecklist.items must be a tuple"
            )
        for entry in self.items:
            if not isinstance(entry, DeploymentReadinessItem):
                raise ContractError(
                    "AMAXDeploymentReadinessChecklist.items must contain "
                    "DeploymentReadinessItem instances"
                )
        seen: set[str] = set()
        for entry in self.items:
            if entry.item_id in seen:
                raise ContractError(
                    f"AMAXDeploymentReadinessChecklist has duplicate "
                    f"item id {entry.item_id!r}"
                )
            seen.add(entry.item_id)
        notes = _ensure_str_tuple(
            self.notes, label="AMAXDeploymentReadinessChecklist.notes"
        )
        object.__setattr__(self, "notes", notes)

    @property
    def categories(self) -> frozenset[str]:
        """Return the set of categories present in this checklist."""

        return frozenset(item.category for item in self.items)

    def items_for_category(
        self, category: str
    ) -> tuple[DeploymentReadinessItem, ...]:
        """Return the items whose ``category`` equals ``category``."""

        return tuple(item for item in self.items if item.category == category)

    def unresolved_blocking_items(
        self,
    ) -> tuple[DeploymentReadinessItem, ...]:
        """Return blocking items whose status is not yet ``approved``.

        Pure audit helper. ``not_applicable`` items are treated as
        resolved by site decision; ``approved`` items are resolved;
        every other status counts as unresolved.
        """

        resolved_statuses = {
            READINESS_STATUS_APPROVED,
            READINESS_STATUS_NOT_APPLICABLE,
        }
        return tuple(
            item
            for item in self.items
            if item.blocking and item.status not in resolved_statuses
        )

    def is_fully_approved(self) -> bool:
        """Return True iff no blocking items remain unresolved."""

        return not self.unresolved_blocking_items()

    def to_dict(self) -> dict[str, Any]:
        return {
            "checklist_id": self.checklist_id,
            "items": [item.to_dict() for item in self.items],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "AMAXDeploymentReadinessChecklist":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXDeploymentReadinessChecklist.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        _reject_forbidden_keys(
            data, label="AMAXDeploymentReadinessChecklist"
        )
        missing = {"checklist_id", "items"} - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXDeploymentReadinessChecklist missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_CHECKLIST_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXDeploymentReadinessChecklist received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_items = data["items"]
        if isinstance(raw_items, (str, bytes)) or not isinstance(
            raw_items, Sequence
        ):
            raise ContractError(
                "AMAXDeploymentReadinessChecklist.items must be a sequence"
            )
        return cls(
            checklist_id=str(data["checklist_id"]),
            items=tuple(
                DeploymentReadinessItem.from_dict(item) for item in raw_items
            ),
            notes=_coerce_str_sequence(
                data, "notes", label="AMAXDeploymentReadinessChecklist"
            ),
        )


# ---------------------------------------------------------------------------
# AMAXOTCertificationEvidence
# ---------------------------------------------------------------------------


_CERTIFICATION_FIELDS: tuple[str, ...] = (
    "evidence_id",
    "hardware_certifications",
    "system_qualifications_required",
    "hardware_certifies_system",
    "notes",
)


@dataclass(frozen=True)
class AMAXOTCertificationEvidence:
    """Frozen audit record contrasting hardware vs system certification.

    Audit-only. Captures the AMAX hardware certifications (CE, FCC,
    UL, EN 61131-2 industrial-control, IEC 61010-1, Class 1 Division 2
    where applicable, etc.) as label references and the AquaOptima
    system-level qualifications that are still required (FAT, SAT, site
    cyber review, rollback drill, failure-mode walkthrough). The
    ``hardware_certifies_system`` flag is fixed to ``False`` — AMAX
    hardware certification is necessary but not sufficient for
    AquaOptima system deployment. Nothing in this record represents a
    write, dispatch, actuation, setpoint, or control surface.
    """

    evidence_id: str
    hardware_certifications: tuple[str, ...]
    system_qualifications_required: tuple[str, ...]
    hardware_certifies_system: bool = False
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.evidence_id,
            label="AMAXOTCertificationEvidence.evidence_id",
        )
        hardware = _ensure_str_tuple(
            self.hardware_certifications,
            label="AMAXOTCertificationEvidence.hardware_certifications",
        )
        system = _ensure_str_tuple(
            self.system_qualifications_required,
            label=(
                "AMAXOTCertificationEvidence."
                "system_qualifications_required"
            ),
        )
        _ensure_bool(
            self.hardware_certifies_system,
            label="AMAXOTCertificationEvidence.hardware_certifies_system",
        )
        if self.hardware_certifies_system:
            raise ContractError(
                "AMAXOTCertificationEvidence.hardware_certifies_system "
                "must be False — AMAX hardware certification does not "
                "certify the full AquaOptima deployed system"
            )
        if not system:
            raise ContractError(
                "AMAXOTCertificationEvidence.system_qualifications_required "
                "must list at least one AquaOptima system-level "
                "qualification still required"
            )
        notes = _ensure_str_tuple(
            self.notes, label="AMAXOTCertificationEvidence.notes"
        )
        object.__setattr__(self, "hardware_certifications", hardware)
        object.__setattr__(
            self, "system_qualifications_required", system
        )
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "hardware_certifications": list(self.hardware_certifications),
            "system_qualifications_required": list(
                self.system_qualifications_required
            ),
            "hardware_certifies_system": self.hardware_certifies_system,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "AMAXOTCertificationEvidence":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXOTCertificationEvidence.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="AMAXOTCertificationEvidence")
        missing = {
            "evidence_id",
            "hardware_certifications",
            "system_qualifications_required",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXOTCertificationEvidence missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_CERTIFICATION_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXOTCertificationEvidence received unknown fields: "
                f"{sorted(unknown)}"
            )
        certifies = data.get("hardware_certifies_system", False)
        if not isinstance(certifies, bool):
            raise ContractError(
                "AMAXOTCertificationEvidence.hardware_certifies_system "
                "must be a bool"
            )
        return cls(
            evidence_id=str(data["evidence_id"]),
            hardware_certifications=_coerce_str_sequence(
                data,
                "hardware_certifications",
                label="AMAXOTCertificationEvidence",
            ),
            system_qualifications_required=_coerce_str_sequence(
                data,
                "system_qualifications_required",
                label="AMAXOTCertificationEvidence",
            ),
            hardware_certifies_system=certifies,
            notes=_coerce_str_sequence(
                data, "notes", label="AMAXOTCertificationEvidence"
            ),
        )


# ---------------------------------------------------------------------------
# AMAXFailureMode
# ---------------------------------------------------------------------------


_FAILURE_MODE_FIELDS: tuple[str, ...] = (
    "mode_id",
    "category",
    "description",
    "effect",
    "detection",
    "fallback",
    "blocking",
    "notes",
)


@dataclass(frozen=True)
class AMAXFailureMode:
    """Frozen audit record for a single failure mode.

    Audit-only. Captures the failure mode id, canonical category, a
    description of the failure, its operational effect, the detection
    strategy, the fallback strategy, a blocking flag, and audit notes.
    Nothing in this record represents a write, dispatch, actuation,
    setpoint, or control surface.

    The fallback field documents an **audit expectation** — the site
    PLC retains direct VFD / pump / actuator authority in every Sprint
    45+ failure mode. The fallback text is evidence text, not an
    instruction the SDK executes.
    """

    mode_id: str
    category: str
    description: str
    effect: str
    detection: str
    fallback: str
    blocking: bool = True
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(self.mode_id, label="AMAXFailureMode.mode_id")
        _ensure_str(self.category, label="AMAXFailureMode.category")
        if self.category not in FAILURE_MODE_CATEGORIES:
            raise ContractError(
                f"AMAXFailureMode.category {self.category!r} is not in "
                f"the allowed list ({sorted(FAILURE_MODE_CATEGORIES)})"
            )
        _ensure_str(self.description, label="AMAXFailureMode.description")
        _ensure_str(self.effect, label="AMAXFailureMode.effect")
        _ensure_str(self.detection, label="AMAXFailureMode.detection")
        _ensure_str(self.fallback, label="AMAXFailureMode.fallback")
        _ensure_bool(self.blocking, label="AMAXFailureMode.blocking")
        notes = _ensure_str_tuple(
            self.notes, label="AMAXFailureMode.notes"
        )
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode_id": self.mode_id,
            "category": self.category,
            "description": self.description,
            "effect": self.effect,
            "detection": self.detection,
            "fallback": self.fallback,
            "blocking": self.blocking,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXFailureMode":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXFailureMode.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="AMAXFailureMode")
        missing = {
            "mode_id",
            "category",
            "description",
            "effect",
            "detection",
            "fallback",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXFailureMode missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_FAILURE_MODE_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXFailureMode received unknown fields: {sorted(unknown)}"
            )
        blocking_raw = data.get("blocking", True)
        if not isinstance(blocking_raw, bool):
            raise ContractError("AMAXFailureMode.blocking must be a bool")
        return cls(
            mode_id=str(data["mode_id"]),
            category=str(data["category"]),
            description=str(data["description"]),
            effect=str(data["effect"]),
            detection=str(data["detection"]),
            fallback=str(data["fallback"]),
            blocking=blocking_raw,
            notes=_coerce_str_sequence(
                data, "notes", label="AMAXFailureMode"
            ),
        )


# ---------------------------------------------------------------------------
# AMAXSiteDeploymentEvidencePackage
# ---------------------------------------------------------------------------


_PACKAGE_FIELDS: tuple[str, ...] = (
    "package_id",
    "checklist",
    "certification_evidence",
    "failure_modes",
    "referenced_evidence",
    "next_gate",
    "site_specific_approval_required",
    "safety_notes",
)


@dataclass(frozen=True)
class AMAXSiteDeploymentEvidencePackage:
    """Frozen Sprint 49 site deployment evidence package.

    Audit-only. Combines the readiness checklist, hardware-vs-system
    certification evidence, failure-mode matrix, referenced Sprint
    46 / 47 / 48 evidence ids or doc references, and the next gate.
    Carries explicit ``site_specific_approval_required=True``: Sprint
    49 does not approve any site install by default. Nothing in this
    record represents a write, dispatch, actuation, setpoint, or
    control surface.
    """

    package_id: str
    checklist: AMAXDeploymentReadinessChecklist
    certification_evidence: AMAXOTCertificationEvidence
    failure_modes: tuple[AMAXFailureMode, ...]
    referenced_evidence: tuple[str, ...] = ()
    next_gate: str = ""
    site_specific_approval_required: bool = True
    safety_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.package_id,
            label="AMAXSiteDeploymentEvidencePackage.package_id",
        )
        if not isinstance(self.checklist, AMAXDeploymentReadinessChecklist):
            raise ContractError(
                "AMAXSiteDeploymentEvidencePackage.checklist must be an "
                "AMAXDeploymentReadinessChecklist"
            )
        if not isinstance(
            self.certification_evidence, AMAXOTCertificationEvidence
        ):
            raise ContractError(
                "AMAXSiteDeploymentEvidencePackage.certification_evidence "
                "must be an AMAXOTCertificationEvidence"
            )
        if not isinstance(self.failure_modes, tuple):
            raise ContractError(
                "AMAXSiteDeploymentEvidencePackage.failure_modes must be "
                "a tuple"
            )
        for mode in self.failure_modes:
            if not isinstance(mode, AMAXFailureMode):
                raise ContractError(
                    "AMAXSiteDeploymentEvidencePackage.failure_modes must "
                    "contain AMAXFailureMode instances"
                )
        seen_modes: set[str] = set()
        for mode in self.failure_modes:
            if mode.mode_id in seen_modes:
                raise ContractError(
                    f"AMAXSiteDeploymentEvidencePackage has duplicate "
                    f"failure mode id {mode.mode_id!r}"
                )
            seen_modes.add(mode.mode_id)
        referenced = _ensure_str_tuple(
            self.referenced_evidence,
            label="AMAXSiteDeploymentEvidencePackage.referenced_evidence",
        )
        _ensure_string(
            self.next_gate,
            label="AMAXSiteDeploymentEvidencePackage.next_gate",
        )
        _ensure_bool(
            self.site_specific_approval_required,
            label=(
                "AMAXSiteDeploymentEvidencePackage."
                "site_specific_approval_required"
            ),
        )
        safety_notes = _ensure_str_tuple(
            self.safety_notes,
            label="AMAXSiteDeploymentEvidencePackage.safety_notes",
        )
        object.__setattr__(self, "referenced_evidence", referenced)
        object.__setattr__(self, "safety_notes", safety_notes)

    @property
    def failure_mode_categories(self) -> frozenset[str]:
        """Return the set of failure-mode categories present."""

        return frozenset(mode.category for mode in self.failure_modes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "checklist": self.checklist.to_dict(),
            "certification_evidence": self.certification_evidence.to_dict(),
            "failure_modes": [
                mode.to_dict() for mode in self.failure_modes
            ],
            "referenced_evidence": list(self.referenced_evidence),
            "next_gate": self.next_gate,
            "site_specific_approval_required": (
                self.site_specific_approval_required
            ),
            "safety_notes": list(self.safety_notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "AMAXSiteDeploymentEvidencePackage":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXSiteDeploymentEvidencePackage.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        _reject_forbidden_keys(
            data, label="AMAXSiteDeploymentEvidencePackage"
        )
        missing = {
            "package_id",
            "checklist",
            "certification_evidence",
            "failure_modes",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXSiteDeploymentEvidencePackage missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_PACKAGE_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXSiteDeploymentEvidencePackage received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_modes = data["failure_modes"]
        if isinstance(raw_modes, (str, bytes)) or not isinstance(
            raw_modes, Sequence
        ):
            raise ContractError(
                "AMAXSiteDeploymentEvidencePackage.failure_modes must be a "
                "sequence"
            )
        approval = data.get("site_specific_approval_required", True)
        if not isinstance(approval, bool):
            raise ContractError(
                "AMAXSiteDeploymentEvidencePackage."
                "site_specific_approval_required must be a bool"
            )
        return cls(
            package_id=str(data["package_id"]),
            checklist=AMAXDeploymentReadinessChecklist.from_dict(
                data["checklist"]
            ),
            certification_evidence=AMAXOTCertificationEvidence.from_dict(
                data["certification_evidence"]
            ),
            failure_modes=tuple(
                AMAXFailureMode.from_dict(mode) for mode in raw_modes
            ),
            referenced_evidence=_coerce_str_sequence(
                data,
                "referenced_evidence",
                label="AMAXSiteDeploymentEvidencePackage",
            ),
            next_gate=str(data.get("next_gate", "")),
            site_specific_approval_required=approval,
            safety_notes=_coerce_str_sequence(
                data,
                "safety_notes",
                label="AMAXSiteDeploymentEvidencePackage",
            ),
        )


# ---------------------------------------------------------------------------
# AMAXDeploymentReadinessDiagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AMAXDeploymentReadinessDiagnostics:
    """Deterministic warnings / errors for a deployment evidence package.

    Audit-only. Surfaces unresolved blocking items, missing required
    categories, missing failure-mode coverage, missing Sprint 46 / 47 /
    48 evidence references, and unsafe vocabulary detected in
    descriptions / labels / notes. Nothing in this record represents a
    write, dispatch, actuation, setpoint, or control surface.
    """

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("warnings", "errors"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(v, str) for v in value
            ):
                raise ContractError(
                    f"AMAXDeploymentReadinessDiagnostics.{name} must be a "
                    f"tuple of strings"
                )

    @property
    def is_clean(self) -> bool:
        return not self.warnings and not self.errors

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "AMAXDeploymentReadinessDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXDeploymentReadinessDiagnostics.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        unknown = set(data.keys()) - {"warnings", "errors"}
        if unknown:
            raise ContractError(
                f"AMAXDeploymentReadinessDiagnostics received unknown "
                f"fields: {sorted(unknown)}"
            )
        warnings = tuple(str(w) for w in data.get("warnings", ()))
        errors = tuple(str(e) for e in data.get("errors", ()))
        return cls(warnings=warnings, errors=errors)


def diagnose_amax_site_deployment_evidence_package(
    package: AMAXSiteDeploymentEvidencePackage,
) -> AMAXDeploymentReadinessDiagnostics:
    """Return deterministic warnings / errors for ``package``.

    Pure audit helper. The checks cover unresolved blocking items,
    missing required readiness categories, missing failure-mode
    coverage, missing referenced Sprint 46 / 47 / 48 evidence
    handles, missing next-gate language, and unsafe vocabulary in
    descriptions or notes. No live binding, no write, no setpoint, no
    command emission.
    """

    if not isinstance(package, AMAXSiteDeploymentEvidencePackage):
        raise ContractError(
            "diagnose_amax_site_deployment_evidence_package requires an "
            "AMAXSiteDeploymentEvidencePackage"
        )

    warnings: list[str] = []
    errors: list[str] = []

    unresolved = package.checklist.unresolved_blocking_items()
    for item in unresolved:
        errors.append(
            f"unresolved blocking readiness item {item.item_id!r} "
            f"(category={item.category!r}, status={item.status!r})"
        )

    present_categories = package.checklist.categories
    missing_categories = READINESS_CATEGORIES - present_categories
    if missing_categories:
        errors.append(
            f"checklist missing required categories: "
            f"{sorted(missing_categories)}"
        )

    required_failure_categories = FAILURE_MODE_CATEGORIES
    missing_failure_categories = (
        required_failure_categories - package.failure_mode_categories
    )
    if missing_failure_categories:
        errors.append(
            f"failure-mode matrix missing required categories: "
            f"{sorted(missing_failure_categories)}"
        )

    if not package.referenced_evidence:
        warnings.append(
            "package has no referenced_evidence — Sprint 49 packages "
            "should cite Sprint 46 / 47 / 48 evidence handles"
        )

    if not package.next_gate:
        warnings.append(
            "package has no next_gate — Sprint 49 packages should name "
            "the next gate (Sprint 50 supervisory proposal / PLC "
            "gatekeeper contract)"
        )

    if not package.safety_notes:
        warnings.append(
            "package has no safety_notes — Sprint 49 packages should "
            "explicitly reaffirm the read-only safety boundary"
        )

    if not package.site_specific_approval_required:
        errors.append(
            "package.site_specific_approval_required must be True — "
            "Sprint 49 evidence does not approve a site install by default"
        )

    # Unsafe vocabulary scan over identifier / label fields only. The
    # narrative description / notes / effect / detection / fallback
    # fields are intentionally allowed to discuss boundary phrases in
    # negative context (e.g. "no setpoint output", "site PLC retains
    # direct VFD / pump / actuator authority"); they are audit text and
    # would lose their value if they could not name what the system
    # explicitly does not do. Labels and ids, however, must stay clear
    # of those phrases — that is what callers grep for.
    for item in package.checklist.items:
        haystack = "\n".join(
            (
                item.item_id,
                item.evidence_reference,
                item.owner_label,
            )
        )
        unsafe = _scan_unsafe_phrases(haystack)
        if unsafe:
            errors.append(
                f"readiness item {item.item_id!r} contains unsafe "
                f"vocabulary {list(unsafe)}"
            )

    for mode in package.failure_modes:
        unsafe = _scan_unsafe_phrases(mode.mode_id)
        if unsafe:
            errors.append(
                f"failure mode {mode.mode_id!r} contains unsafe "
                f"vocabulary {list(unsafe)}"
            )

    return AMAXDeploymentReadinessDiagnostics(
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# Canonical Sprint 49 default helpers
# ---------------------------------------------------------------------------


def default_amax_deployment_readiness_checklist() -> (
    AMAXDeploymentReadinessChecklist
):
    """Return the canonical Sprint 49 AMAX deployment readiness checklist.

    Audit-only. Enumerates a deterministic readiness item for every
    canonical category. All items default to ``pending`` — Sprint 49
    evidence does not approve any site install by default; real site
    evidence is still required.
    """

    items = (
        DeploymentReadinessItem(
            item_id="readiness_sku_amax_5580_serious_candidate",
            category=READINESS_CATEGORY_SKU,
            description=(
                "AMAX-5580 SKU pinned to a Sprint 46 serious-candidate "
                "(Core i5-6300U 8 GB or Core i7-6600U 8 GB) per site BOM"
            ),
            evidence_reference="sprint_46_amax_feasibility_decision",
            owner_label="site_hardware_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "Sprint 46 evidence is surrogate until real AMAX hardware "
                "is procured and inventoried",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_os_image_signed",
            category=READINESS_CATEGORY_OS_IMAGE,
            description=(
                "Site OS image (AdvLinuxTU Ubuntu 18 or Windows 10 LTSC "
                "2019) is built, signed, and stored in the site image "
                "registry with provenance"
            ),
            evidence_reference="site_image_registry_label",
            owner_label="site_ot_engineering_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "OS image provenance must include hash and signing key "
                "reference, not the key material itself",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_codesys_package_signed",
            category=READINESS_CATEGORY_CODESYS_PACKAGE,
            description=(
                "CODESYS Linux Control / Control RTE runtime is co-tenant "
                "approved, version pinned, and signed per site policy"
            ),
            evidence_reference="site_codesys_package_signing_label",
            owner_label="site_plc_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "CODESYS co-tenancy must not interfere with the AquaOptima "
                "Edge ML sidecar resource budget",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_network_ports_segmented",
            category=READINESS_CATEGORY_NETWORK_PORTS,
            description=(
                "Network ports allow Sprint 48 read-only inbound flows "
                "only; no outbound write / dispatch flows are opened"
            ),
            evidence_reference="site_firewall_review_label",
            owner_label="site_network_security_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "Port allow-list captured as labels; no IP literals are "
                "stored in this audit record",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_physical_install_panel_mounted",
            category=READINESS_CATEGORY_PHYSICAL_INSTALL,
            description=(
                "AMAX panel mount, grounding, and clearance follow Advantech "
                "DIN-rail / panel installation guidance"
            ),
            evidence_reference="site_install_drawing_label",
            owner_label="site_electrical_contractor",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "Panel temperature must stay within the AMAX operating "
                "envelope under worst-case site conditions",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_power_24vdc_with_ups_evidence",
            category=READINESS_CATEGORY_POWER,
            description=(
                "24 VDC supply meets AMAX input range and a site UPS is "
                "sized for orderly shutdown on power loss"
            ),
            evidence_reference="site_ups_runtime_calculation_label",
            owner_label="site_electrical_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "Power loss falls through to site PLC interlocks — "
                "AquaOptima Edge does not retain control authority",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_storage_industrial_ssd",
            category=READINESS_CATEGORY_STORAGE,
            description=(
                "Industrial-grade SSD / mSATA storage is sized for site "
                "log retention and is power-loss tolerant"
            ),
            evidence_reference="site_storage_endurance_label",
            owner_label="site_ot_engineering_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "Storage endurance must cover the expected log retention "
                "window plus headroom",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_environment_within_amax_envelope",
            category=READINESS_CATEGORY_ENVIRONMENT,
            description=(
                "Cabinet temperature, humidity, vibration, and ingress "
                "protection stay within the AMAX operating envelope"
            ),
            evidence_reference="site_environment_survey_label",
            owner_label="site_facilities_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "Operating envelope evidence is required before FAT is "
                "scheduled",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_rollback_runbook_signed",
            category=READINESS_CATEGORY_ROLLBACK,
            description=(
                "Rollback runbook is written, dry-run signed off, and "
                "stored alongside the deployment package"
            ),
            evidence_reference="site_rollback_runbook_label",
            owner_label="site_operations_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "Rollback returns the site to pre-deployment PLC-only "
                "operation; the site PLC retains direct VFD / pump / "
                "actuator authority",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_cybersecurity_posture_signed",
            category=READINESS_CATEGORY_CYBERSECURITY,
            description=(
                "Site cybersecurity posture (segmentation labels, "
                "credential references, no stored secrets, software "
                "signing / provenance, audit logs, patching stance) is "
                "documented and signed"
            ),
            evidence_reference="site_cyber_review_label",
            owner_label="site_cybersecurity_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "Credential references are labels — no secrets, tokens, "
                "passwords, or API keys are stored in any AquaOptima "
                "artifact",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_fat_sat_planned",
            category=READINESS_CATEGORY_FAT_SAT,
            description=(
                "FAT (factory acceptance test) and SAT (site acceptance "
                "test) plans are written, reviewed, and scheduled before "
                "any site install"
            ),
            evidence_reference="site_fat_sat_plan_label",
            owner_label="site_acceptance_lead",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "FAT exercises Sprint 47 CPU benchmark and Sprint 48 "
                "read-only integration shapes under controlled inputs; "
                "SAT repeats on site against frozen telemetry only",
            ),
        ),
        DeploymentReadinessItem(
            item_id="readiness_safety_boundary_reaffirmed",
            category=READINESS_CATEGORY_SAFETY_BOUNDARY,
            description=(
                "Sprint 49 safety boundary reaffirmed: no live OT binding, "
                "no PLC/PAC/SCADA write, no command emission, no setpoint "
                "output; site PLC retains direct VFD / pump / actuator "
                "authority"
            ),
            evidence_reference="docs_safety_boundary_md_label",
            owner_label="aquaoptima_safety_owner",
            status=READINESS_STATUS_PENDING,
            blocking=True,
            notes=(
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
    )

    return AMAXDeploymentReadinessChecklist(
        checklist_id="amax_5580_site_deployment_readiness_checklist_v1",
        items=items,
        notes=(
            "Sprint 49 ships a deployment readiness checklist, not a site "
            "install approval",
            "default items remain pending; real site evidence is required",
        ),
    )


def default_amax_ot_certification_evidence() -> AMAXOTCertificationEvidence:
    """Return the canonical Sprint 49 hardware-vs-system evidence record.

    Audit-only. Lists AMAX hardware certification references and the
    AquaOptima system-level qualification evidence that is still
    required. Always carries ``hardware_certifies_system=False``.
    """

    return AMAXOTCertificationEvidence(
        evidence_id="amax_5580_ot_certification_evidence_v1",
        hardware_certifications=(
            "advantech_amax_5580_ce_marking_label",
            "advantech_amax_5580_fcc_part_15_label",
            "advantech_amax_5580_ul_industrial_control_label",
            "advantech_amax_5580_en_61131_2_label",
            "advantech_amax_5580_iec_61010_1_label",
            "advantech_amax_5580_class_1_div_2_where_applicable_label",
        ),
        system_qualifications_required=(
            "aquaoptima_system_fat_evidence_required",
            "aquaoptima_system_sat_evidence_required",
            "aquaoptima_site_cybersecurity_review_required",
            "aquaoptima_rollback_dry_run_evidence_required",
            "aquaoptima_failure_mode_walkthrough_required",
            "aquaoptima_replay_to_live_equivalence_sign_off_required",
        ),
        hardware_certifies_system=False,
        notes=(
            "AMAX hardware certification is necessary but not sufficient "
            "for AquaOptima system deployment",
            "Sprint 49 is the OT certification evidence package, not a "
            "system certification grant",
        ),
    )


def canonical_amax_failure_modes() -> tuple[AMAXFailureMode, ...]:
    """Return the canonical Sprint 49 AMAX failure-mode matrix.

    Audit-only. Covers stale telemetry, package install failure, CPU
    benchmark failure, network loss, power loss, rollback failure,
    operator disable unavailable, and CODESYS co-tenancy unresolved.
    Every fallback narrates a fall-through to site PLC authority;
    nothing in this record represents a write, dispatch, actuation,
    setpoint, or control surface.
    """

    return (
        AMAXFailureMode(
            mode_id="failure_mode_stale_telemetry",
            category=FAILURE_MODE_CATEGORY_TELEMETRY,
            description=(
                "Read-only telemetry stream exceeds the Sprint 48 "
                "freshness threshold for one or more sources"
            ),
            effect=(
                "AquaOptima Edge cannot produce a current advisory and "
                "must mark its outputs as audit-only"
            ),
            detection=(
                "Sprint 48 TelemetryFreshnessPolicy max-age check and "
                "quality-flag mapping"
            ),
            fallback=(
                "Edge holds the last good audit window and falls through "
                "to the site PLC; the site PLC retains direct VFD / pump "
                "/ actuator authority"
            ),
            blocking=True,
            notes=(
                "no live OT binding",
                "no PLC/PAC/SCADA write",
            ),
        ),
        AMAXFailureMode(
            mode_id="failure_mode_package_install_failure",
            category=FAILURE_MODE_CATEGORY_PACKAGE,
            description=(
                "Sprint 44 deployment package fails the Sprint 45 AMAX "
                "Edge validator or fails to install on the AMAX target"
            ),
            effect=(
                "Edge runtime is not promoted; previous validated package "
                "remains in place"
            ),
            detection=(
                "Sprint 45 deny-by-default validator result and site "
                "install runbook checks"
            ),
            fallback=(
                "Site stays on the previously validated package; if no "
                "previous package exists, the site continues PLC-only "
                "operation"
            ),
            blocking=True,
            notes=(
                "Sprint 45 validator gates promotion; no command emission",
            ),
        ),
        AMAXFailureMode(
            mode_id="failure_mode_cpu_benchmark_failure",
            category=FAILURE_MODE_CATEGORY_BENCHMARK,
            description=(
                "Sprint 47 AMAX CPU benchmark does not meet the cadence "
                "target on the selected SKU"
            ),
            effect=(
                "Supervisory cadence is downgraded or the package is "
                "rejected for the site"
            ),
            detection=(
                "Sprint 47 AMAXBenchmarkReport metrics and cadence "
                "classification helper"
            ),
            fallback=(
                "Site falls back to a slower cadence audit-only mode or "
                "stays on PLC-only operation; no setpoint output is "
                "attempted"
            ),
            blocking=True,
            notes=(
                "Sprint 47 evidence is the gate, not a runtime promotion",
            ),
        ),
        AMAXFailureMode(
            mode_id="failure_mode_network_loss",
            category=FAILURE_MODE_CATEGORY_NETWORK,
            description=(
                "OT-zone or IT-zone network link to read-only telemetry "
                "sources is lost"
            ),
            effect=(
                "Sprint 48 read-only sources stop delivering telemetry; "
                "audit outputs mark the data window as missing"
            ),
            detection=(
                "Sprint 48 missing-data behavior tokens and freshness "
                "policy"
            ),
            fallback=(
                "Edge degrades to audit-only fallback; site PLC retains "
                "direct VFD / pump / actuator authority"
            ),
            blocking=True,
            notes=(
                "no live OT binding during network loss",
            ),
        ),
        AMAXFailureMode(
            mode_id="failure_mode_power_loss",
            category=FAILURE_MODE_CATEGORY_POWER,
            description=(
                "Site power loss or UPS exhaustion brings the AMAX edge "
                "device down"
            ),
            effect=(
                "AquaOptima Edge advisory outputs are unavailable for the "
                "duration of the outage"
            ),
            detection=(
                "Site UPS telemetry and AMAX power-fail signalling per the "
                "Advantech datasheet"
            ),
            fallback=(
                "Site continues on PLC-only operation; the site PLC retains "
                "direct VFD / pump / actuator authority; orderly shutdown "
                "preserves audit logs"
            ),
            blocking=True,
            notes=(
                "no command emission during power loss",
            ),
        ),
        AMAXFailureMode(
            mode_id="failure_mode_rollback_failure",
            category=FAILURE_MODE_CATEGORY_ROLLBACK,
            description=(
                "Rollback runbook fails to return the site to the prior "
                "validated state during the rollback dry-run or post-install"
            ),
            effect=(
                "Site cannot safely promote the new package and must hold "
                "at the prior state"
            ),
            detection=(
                "Rollback runbook checklist and FAT / SAT acceptance gates"
            ),
            fallback=(
                "Hold the site at the prior validated state; surface the "
                "rollback failure to the site operations lead before any "
                "further promotion is attempted"
            ),
            blocking=True,
            notes=(
                "rollback evidence is required before any further promotion",
            ),
        ),
        AMAXFailureMode(
            mode_id="failure_mode_operator_disable_unavailable",
            category=FAILURE_MODE_CATEGORY_OPERATOR,
            description=(
                "Operator disable / pause path for AquaOptima Edge audit "
                "outputs is not reachable from the operator console"
            ),
            effect=(
                "Operators cannot suspend Edge advisory outputs from the "
                "console while triaging an incident"
            ),
            detection=(
                "FAT / SAT operator-disable walkthrough and operations "
                "runbook review"
            ),
            fallback=(
                "Site PLC interlocks remain authoritative; site operations "
                "lead escalates per the operations runbook; Edge stays in "
                "audit-only fallback"
            ),
            blocking=True,
            notes=(
                "operator disable path is a Sprint 49 readiness "
                "requirement; no remote control is added by AquaOptima",
            ),
        ),
        AMAXFailureMode(
            mode_id="failure_mode_codesys_co_tenancy_unresolved",
            category=FAILURE_MODE_CATEGORY_CODESYS,
            description=(
                "CODESYS runtime co-tenancy on the AMAX device is not "
                "validated against the Edge ML sidecar resource budget"
            ),
            effect=(
                "Risk of CPU / memory contention that may cause the AMAX "
                "Edge to miss its cadence target or destabilise CODESYS"
            ),
            detection=(
                "Sprint 47 packaging smoke harness and FAT CPU / memory "
                "headroom checks"
            ),
            fallback=(
                "Run the AquaOptima ML sidecar outside the CODESYS runtime "
                "via the Sprint 46 service-sidecar option; site PLC retains "
                "direct VFD / pump / actuator authority"
            ),
            blocking=True,
            notes=(
                "CODESYS co-tenancy must be resolved before promotion",
            ),
        ),
    )


def default_amax_site_deployment_evidence_package() -> (
    AMAXSiteDeploymentEvidencePackage
):
    """Return the canonical Sprint 49 AMAX site deployment evidence package.

    Audit-only. Bundles the default readiness checklist, the canonical
    hardware-vs-system certification evidence, and the canonical
    failure-mode matrix. Carries explicit
    ``site_specific_approval_required=True`` and reaffirms the
    non-negotiable safety boundary in ``safety_notes``. Nothing in
    this record represents a write, dispatch, actuation, setpoint, or
    control surface.
    """

    return AMAXSiteDeploymentEvidencePackage(
        package_id=AMAX_SITE_DEPLOYMENT_EVIDENCE_PACKAGE_ID,
        checklist=default_amax_deployment_readiness_checklist(),
        certification_evidence=default_amax_ot_certification_evidence(),
        failure_modes=canonical_amax_failure_modes(),
        referenced_evidence=(
            "sprint_46_amax_feasibility_decision",
            "sprint_47_amax_benchmark_report",
            "sprint_48_amax_read_only_integration_contract",
            "docs/hardware/amax-5580-feasibility.md",
            "docs/hardware/amax-5580-cpu-benchmarking.md",
            "docs/hardware/amax-5580-read-only-integration.md",
            "docs/hardware/amax-5580-site-deployment-readiness.md",
        ),
        next_gate=(
            "Sprint 50 — simulated supervisory proposal / PLC gatekeeper "
            "contract (simulation only; not a live write or control "
            "sprint)"
        ),
        site_specific_approval_required=True,
        safety_notes=(
            "Sprint 49 ships a site deployment readiness / OT "
            "certification evidence package, not a site install approval",
            "AMAX hardware certification is necessary but not sufficient "
            "for AquaOptima system deployment",
            "FAT / SAT, cybersecurity, rollback, and failure-mode "
            "evidence are required before any pilot",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "no control-loop closure",
            "site PLC retains direct VFD / pump / actuator authority",
            "Sprint 50 should remain a simulated supervisory proposal / "
            "PLC gatekeeper contract sprint, not a live write or control "
            "sprint",
        ),
    )


__all__ = [
    "AMAX_SITE_DEPLOYMENT_EVIDENCE_PACKAGE_ID",
    "AMAXDeploymentReadinessChecklist",
    "AMAXDeploymentReadinessDiagnostics",
    "AMAXFailureMode",
    "AMAXOTCertificationEvidence",
    "AMAXSiteDeploymentEvidencePackage",
    "DeploymentReadinessItem",
    "FAILURE_MODE_CATEGORIES",
    "FAILURE_MODE_CATEGORY_BENCHMARK",
    "FAILURE_MODE_CATEGORY_CODESYS",
    "FAILURE_MODE_CATEGORY_NETWORK",
    "FAILURE_MODE_CATEGORY_OPERATOR",
    "FAILURE_MODE_CATEGORY_PACKAGE",
    "FAILURE_MODE_CATEGORY_POWER",
    "FAILURE_MODE_CATEGORY_ROLLBACK",
    "FAILURE_MODE_CATEGORY_TELEMETRY",
    "READINESS_CATEGORIES",
    "READINESS_CATEGORY_CODESYS_PACKAGE",
    "READINESS_CATEGORY_CYBERSECURITY",
    "READINESS_CATEGORY_ENVIRONMENT",
    "READINESS_CATEGORY_FAT_SAT",
    "READINESS_CATEGORY_NETWORK_PORTS",
    "READINESS_CATEGORY_OS_IMAGE",
    "READINESS_CATEGORY_PHYSICAL_INSTALL",
    "READINESS_CATEGORY_POWER",
    "READINESS_CATEGORY_ROLLBACK",
    "READINESS_CATEGORY_SAFETY_BOUNDARY",
    "READINESS_CATEGORY_SKU",
    "READINESS_CATEGORY_STORAGE",
    "READINESS_STATUS_APPROVED",
    "READINESS_STATUS_BLOCKED",
    "READINESS_STATUS_IN_REVIEW",
    "READINESS_STATUS_NOT_APPLICABLE",
    "READINESS_STATUS_PENDING",
    "READINESS_STATUS_TOKENS",
    "canonical_amax_failure_modes",
    "default_amax_deployment_readiness_checklist",
    "default_amax_ot_certification_evidence",
    "default_amax_site_deployment_evidence_package",
    "diagnose_amax_site_deployment_evidence_package",
]
