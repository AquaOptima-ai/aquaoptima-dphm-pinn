"""``DeploymentPackageManifest`` SDK projections (Sprint 44).

Audit-only contract shapes for deployment packages, artifact
manifests, and the model / artifact registry record described in
``docs/architecture/contracts-inventory.md``. The Phase 1 runtime
modules continue to own all packaging behavior (hashing, fixture
loading, JSON writing). The SDK projection here owns *shape*,
deterministic JSON, and deny-by-default validation only.

Boundary reminder: nothing in this module represents a write,
dispatch, actuation, setpoint, or control payload. Every field is
audit / packaging evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..base.checksum import Checksum
from ..base.envelope import ContractError, ContractEnvelope
from ..base.identifiers import ArtifactReference
from ..base.provenance import Provenance
from ..manifest.shadow_deployment import ShadowDeploymentManifest
from ..safety.capability_gates import CapabilityRequirement
from ..safety.flags import SafetyFlagSet
from ..safety.vocabulary import FORBIDDEN_VOCABULARY, contains_forbidden_token
from ..version import SDK_VERSION


# ---------------------------------------------------------------------------
# Canonical vocabularies
# ---------------------------------------------------------------------------


# Canonical roles a packaged artifact can play. These mirror the
# Phase 1 shadow deployment artifact kinds and the contracts-inventory
# entries (calibration / advisory / import-quality / model weights /
# safety acknowledgement). Forbidden vocabulary tokens are explicitly
# excluded; tests assert this invariant.
PACKAGE_ARTIFACT_ROLES: frozenset[str] = frozenset(
    {
        "shadow_replay_dataset",
        "telemetry_tag_map",
        "dpl_calibration_loss_report",
        "advisory_contract",
        "advisory_audit_decisions",
        "shadow_runtime_report",
        "epanet_import_quality_report",
        "topology_snapshot",
        "model_weights",
        "safety_acknowledgement",
        "audit_evidence",
    }
)


# Canonical model frameworks the SDK projection understands. The SDK
# never loads model weights; "audit_only" is the default and means the
# record carries an ArtifactReference + Checksum only.
PACKAGE_MODEL_FRAMEWORKS: frozenset[str] = frozenset(
    {
        "pytorch",
        "onnx",
        "tensorrt",
        "tflite",
        "audit_only",
    }
)


# Field names that look like command / setpoint / write payloads. The
# from_dict path rejects any of these even if the caller supplies them
# alongside otherwise-valid manifest fields — they have no place in an
# audit-only deployment package manifest.
_REJECTED_PAYLOAD_FIELDS: frozenset[str] = frozenset(
    {
        "setpoint",
        "command",
        "control",
        "actuate",
        "write",
        "dispatch",
        "weights",
        "binary",
        "raw",
    }
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ensure_string_tuple(value: Any, *, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, tuple):
        raise ContractError(f"{label} must be a tuple of strings")
    for item in value:
        if not isinstance(item, str):
            raise ContractError(f"{label} entries must be strings")
    return value  # type: ignore[return-value]


def _ensure_string_field(
    value: Any,
    *,
    label: str,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string, got {type(value).__name__}")
    if not allow_empty and not value:
        raise ContractError(f"{label} must be a non-empty string")
    hits = contains_forbidden_token(value)
    if hits:
        raise ContractError(
            f"{label} value contains forbidden vocabulary token(s) "
            f"{sorted(hits)}"
        )
    return value


def _ensure_summary_value(value: Any, *, label: str) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        if isinstance(value, str):
            hits = contains_forbidden_token(value)
            if hits:
                raise ContractError(
                    f"{label}: summary string contains forbidden token(s) "
                    f"{sorted(hits)}"
                )
        return value
    if isinstance(value, (list, tuple)):
        out: list[Any] = []
        for item in value:
            if isinstance(item, (list, tuple, dict, Mapping)):
                raise ContractError(
                    f"{label}: summary list value contains non-scalar item"
                )
            out.append(_ensure_summary_value(item, label=label))
        return out
    raise ContractError(
        f"{label}: summary value must be scalar or list of scalars, got "
        f"{type(value).__name__}"
    )


def _ensure_summary_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be a mapping")
    out: dict[str, Any] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key:
            raise ContractError(f"{label} keys must be non-empty strings")
        if key in FORBIDDEN_VOCABULARY:
            raise ContractError(
                f"{label} key {key!r} is in the forbidden vocabulary"
            )
        out[key] = _ensure_summary_value(raw, label=f"{label}[{key!r}]")
    return out


def _reject_forbidden_field_names(
    data: Mapping[str, Any], *, label: str
) -> None:
    keys = set(data.keys())
    payload_hits = keys & _REJECTED_PAYLOAD_FIELDS
    if payload_hits:
        raise ContractError(
            f"{label} received forbidden payload field(s): "
            f"{sorted(payload_hits)}"
        )
    vocab_hits = keys & FORBIDDEN_VOCABULARY
    if vocab_hits:
        raise ContractError(
            f"{label} received forbidden vocabulary field name(s): "
            f"{sorted(vocab_hits)}"
        )


# ---------------------------------------------------------------------------
# PackageValidationDiagnostic
# ---------------------------------------------------------------------------


_DIAGNOSTIC_FIELDS: tuple[str, ...] = ("warnings", "errors")


@dataclass(frozen=True)
class PackageValidationDiagnostic:
    """Deterministic warnings / errors tuples for package validation."""

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in _DIAGNOSTIC_FIELDS:
            _ensure_string_tuple(
                getattr(self, name),
                label=f"PackageValidationDiagnostic.{name}",
            )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PackageValidationDiagnostic":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"PackageValidationDiagnostic.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_DIAGNOSTIC_FIELDS)
        if unknown:
            raise ContractError(
                f"PackageValidationDiagnostic received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            warnings=tuple(str(w) for w in data.get("warnings", ())),
            errors=tuple(str(e) for e in data.get("errors", ())),
        )


# ---------------------------------------------------------------------------
# PackageSafetyDeclaration
# ---------------------------------------------------------------------------


_SAFETY_DECLARATION_FIELDS: tuple[str, ...] = (
    "package_id",
    "package_version",
    "safety_flag_set",
    "capability_requirement",
    "acknowledged_at",
    "notes",
)


@dataclass(frozen=True)
class PackageSafetyDeclaration:
    """Mandatory safety bundle attached to every deployment package.

    Pairs the canonical :class:`SafetyFlagSet` with a
    :class:`CapabilityRequirement` so a validator can refuse a package
    that asks for capabilities the Edge has not declared. The
    declaration itself is audit evidence; nothing in this dataclass
    represents a write or actuation payload.
    """

    package_id: str
    package_version: str
    safety_flag_set: SafetyFlagSet
    capability_requirement: CapabilityRequirement
    acknowledged_at: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        _ensure_string_field(
            self.package_id, label="PackageSafetyDeclaration.package_id"
        )
        _ensure_string_field(
            self.package_version,
            label="PackageSafetyDeclaration.package_version",
        )
        if not isinstance(self.safety_flag_set, SafetyFlagSet):
            raise ContractError(
                "PackageSafetyDeclaration.safety_flag_set must be a "
                "SafetyFlagSet instance"
            )
        if not isinstance(self.capability_requirement, CapabilityRequirement):
            raise ContractError(
                "PackageSafetyDeclaration.capability_requirement must be a "
                "CapabilityRequirement instance"
            )
        _ensure_string_field(
            self.acknowledged_at,
            label="PackageSafetyDeclaration.acknowledged_at",
            allow_empty=True,
        )
        _ensure_string_field(
            self.notes,
            label="PackageSafetyDeclaration.notes",
            allow_empty=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "package_version": self.package_version,
            "safety_flag_set": self.safety_flag_set.to_dict(),
            "capability_requirement": self.capability_requirement.to_dict(),
            "acknowledged_at": self.acknowledged_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PackageSafetyDeclaration":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"PackageSafetyDeclaration.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_field_names(
            data, label="PackageSafetyDeclaration"
        )
        missing = {
            "package_id",
            "package_version",
            "safety_flag_set",
            "capability_requirement",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"PackageSafetyDeclaration missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_SAFETY_DECLARATION_FIELDS)
        if unknown:
            raise ContractError(
                f"PackageSafetyDeclaration received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            package_id=str(data["package_id"]),
            package_version=str(data["package_version"]),
            safety_flag_set=SafetyFlagSet.from_dict(data["safety_flag_set"]),
            capability_requirement=CapabilityRequirement.from_dict(
                data["capability_requirement"]
            ),
            acknowledged_at=str(data.get("acknowledged_at", "")),
            notes=str(data.get("notes", "")),
        )


# ---------------------------------------------------------------------------
# ArtifactManifest
# ---------------------------------------------------------------------------


_ARTIFACT_MANIFEST_FIELDS: tuple[str, ...] = (
    "role",
    "artifact_reference",
    "provenance",
    "description",
    "summary",
)


@dataclass(frozen=True)
class ArtifactManifest:
    """Per-artifact entry inside a deployment package manifest.

    Composes :class:`ArtifactReference` (identity + optional
    :class:`Checksum` and ``uri``) with :class:`Provenance` and a
    canonical role token drawn from :data:`PACKAGE_ARTIFACT_ROLES`.
    """

    role: str
    artifact_reference: ArtifactReference
    provenance: Provenance
    description: str = ""
    summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or not self.role:
            raise ContractError(
                "ArtifactManifest.role must be a non-empty string"
            )
        if self.role in FORBIDDEN_VOCABULARY:
            raise ContractError(
                f"ArtifactManifest.role {self.role!r} is in the forbidden "
                "vocabulary"
            )
        if self.role not in PACKAGE_ARTIFACT_ROLES:
            raise ContractError(
                f"ArtifactManifest.role {self.role!r} is not in the "
                f"allowed list ({sorted(PACKAGE_ARTIFACT_ROLES)})"
            )
        if not isinstance(self.artifact_reference, ArtifactReference):
            raise ContractError(
                "ArtifactManifest.artifact_reference must be an "
                "ArtifactReference instance"
            )
        if not isinstance(self.provenance, Provenance):
            raise ContractError(
                "ArtifactManifest.provenance must be a Provenance instance"
            )
        _ensure_string_field(
            self.description,
            label="ArtifactManifest.description",
            allow_empty=True,
        )
        clean_summary = _ensure_summary_mapping(
            self.summary, label="ArtifactManifest.summary"
        )
        object.__setattr__(self, "summary", clean_summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "artifact_reference": self.artifact_reference.to_dict(),
            "provenance": self.provenance.to_dict(),
            "description": self.description,
            "summary": dict(self.summary),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactManifest":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ArtifactManifest.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_field_names(data, label="ArtifactManifest")
        missing = {"role", "artifact_reference", "provenance"} - set(
            data.keys()
        )
        if missing:
            raise ContractError(
                f"ArtifactManifest missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_ARTIFACT_MANIFEST_FIELDS)
        if unknown:
            raise ContractError(
                f"ArtifactManifest received unknown fields: "
                f"{sorted(unknown)}"
            )
        artifact_reference_raw = data["artifact_reference"]
        if not isinstance(artifact_reference_raw, Mapping):
            raise ContractError(
                "ArtifactManifest.artifact_reference must be a mapping"
            )
        try:
            artifact_reference = ArtifactReference.from_dict(
                artifact_reference_raw
            )
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        provenance_raw = data["provenance"]
        if not isinstance(provenance_raw, Mapping):
            raise ContractError(
                "ArtifactManifest.provenance must be a mapping"
            )
        provenance = Provenance.from_dict(provenance_raw)
        return cls(
            role=str(data["role"]),
            artifact_reference=artifact_reference,
            provenance=provenance,
            description=str(data.get("description", "")),
            summary=dict(data.get("summary", {}) or {}),
        )


# ---------------------------------------------------------------------------
# ArtifactBundleRecord
# ---------------------------------------------------------------------------


_BUNDLE_FIELDS: tuple[str, ...] = (
    "bundle_id",
    "bundle_version",
    "artifacts",
    "description",
)


@dataclass(frozen=True)
class ArtifactBundleRecord:
    """Optional grouping of related artifact manifests.

    Useful when a deployment package ships several artifacts that
    belong together (e.g. a calibration report plus its replay
    dataset plus its tag map). The bundle is metadata only; no
    runtime behavior is implied.
    """

    bundle_id: str
    bundle_version: str
    artifacts: tuple[ArtifactManifest, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        _ensure_string_field(
            self.bundle_id, label="ArtifactBundleRecord.bundle_id"
        )
        _ensure_string_field(
            self.bundle_version,
            label="ArtifactBundleRecord.bundle_version",
        )
        if not isinstance(self.artifacts, tuple):
            raise ContractError(
                "ArtifactBundleRecord.artifacts must be a tuple"
            )
        for entry in self.artifacts:
            if not isinstance(entry, ArtifactManifest):
                raise ContractError(
                    "ArtifactBundleRecord.artifacts entries must be "
                    "ArtifactManifest instances"
                )
        _ensure_string_field(
            self.description,
            label="ArtifactBundleRecord.description",
            allow_empty=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "bundle_version": self.bundle_version,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactBundleRecord":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ArtifactBundleRecord.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_field_names(data, label="ArtifactBundleRecord")
        missing = {"bundle_id", "bundle_version"} - set(data.keys())
        if missing:
            raise ContractError(
                f"ArtifactBundleRecord missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_BUNDLE_FIELDS)
        if unknown:
            raise ContractError(
                f"ArtifactBundleRecord received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_artifacts = data.get("artifacts", ()) or ()
        if not isinstance(raw_artifacts, Sequence) or isinstance(
            raw_artifacts, (str, bytes)
        ):
            raise ContractError(
                "ArtifactBundleRecord.artifacts must be a sequence"
            )
        return cls(
            bundle_id=str(data["bundle_id"]),
            bundle_version=str(data["bundle_version"]),
            artifacts=tuple(
                ArtifactManifest.from_dict(a) for a in raw_artifacts
            ),
            description=str(data.get("description", "")),
        )


# ---------------------------------------------------------------------------
# ModelArtifactRecord
# ---------------------------------------------------------------------------


_MODEL_RECORD_FIELDS: tuple[str, ...] = (
    "model_id",
    "model_version",
    "framework",
    "artifact_reference",
    "provenance",
    "safety_flag_set",
    "capability_requirement",
    "description",
    "summary",
)


@dataclass(frozen=True)
class ModelArtifactRecord:
    """Audit-only model / artifact registry projection.

    Carries a :class:`ArtifactReference` (with a mandatory
    :class:`Checksum`), :class:`Provenance`, capability requirement,
    and the canonical :class:`SafetyFlagSet`. No inline weights, no
    filesystem writes, no runtime loading — the SDK never opens a
    model file.
    """

    model_id: str
    model_version: str
    framework: str
    artifact_reference: ArtifactReference
    provenance: Provenance
    safety_flag_set: SafetyFlagSet
    capability_requirement: CapabilityRequirement
    description: str = ""
    summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_string_field(
            self.model_id, label="ModelArtifactRecord.model_id"
        )
        _ensure_string_field(
            self.model_version, label="ModelArtifactRecord.model_version"
        )
        if not isinstance(self.framework, str) or not self.framework:
            raise ContractError(
                "ModelArtifactRecord.framework must be a non-empty string"
            )
        if self.framework not in PACKAGE_MODEL_FRAMEWORKS:
            raise ContractError(
                f"ModelArtifactRecord.framework {self.framework!r} is not "
                f"in the allowed list ({sorted(PACKAGE_MODEL_FRAMEWORKS)})"
            )
        if not isinstance(self.artifact_reference, ArtifactReference):
            raise ContractError(
                "ModelArtifactRecord.artifact_reference must be an "
                "ArtifactReference instance"
            )
        if self.artifact_reference.checksum is None:
            raise ContractError(
                "ModelArtifactRecord.artifact_reference.checksum is required"
            )
        if not isinstance(self.provenance, Provenance):
            raise ContractError(
                "ModelArtifactRecord.provenance must be a Provenance instance"
            )
        if not isinstance(self.safety_flag_set, SafetyFlagSet):
            raise ContractError(
                "ModelArtifactRecord.safety_flag_set must be a SafetyFlagSet "
                "instance"
            )
        if not isinstance(self.capability_requirement, CapabilityRequirement):
            raise ContractError(
                "ModelArtifactRecord.capability_requirement must be a "
                "CapabilityRequirement instance"
            )
        _ensure_string_field(
            self.description,
            label="ModelArtifactRecord.description",
            allow_empty=True,
        )
        clean_summary = _ensure_summary_mapping(
            self.summary, label="ModelArtifactRecord.summary"
        )
        object.__setattr__(self, "summary", clean_summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "framework": self.framework,
            "artifact_reference": self.artifact_reference.to_dict(),
            "provenance": self.provenance.to_dict(),
            "safety_flag_set": self.safety_flag_set.to_dict(),
            "capability_requirement": self.capability_requirement.to_dict(),
            "description": self.description,
            "summary": dict(self.summary),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelArtifactRecord":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ModelArtifactRecord.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_field_names(data, label="ModelArtifactRecord")
        missing = {
            "model_id",
            "model_version",
            "framework",
            "artifact_reference",
            "provenance",
            "safety_flag_set",
            "capability_requirement",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"ModelArtifactRecord missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_MODEL_RECORD_FIELDS)
        if unknown:
            raise ContractError(
                f"ModelArtifactRecord received unknown fields: "
                f"{sorted(unknown)}"
            )
        artifact_reference_raw = data["artifact_reference"]
        if not isinstance(artifact_reference_raw, Mapping):
            raise ContractError(
                "ModelArtifactRecord.artifact_reference must be a mapping"
            )
        try:
            artifact_reference = ArtifactReference.from_dict(
                artifact_reference_raw
            )
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        provenance_raw = data["provenance"]
        if not isinstance(provenance_raw, Mapping):
            raise ContractError(
                "ModelArtifactRecord.provenance must be a mapping"
            )
        provenance = Provenance.from_dict(provenance_raw)
        safety_flag_set = SafetyFlagSet.from_dict(data["safety_flag_set"])
        capability_requirement = CapabilityRequirement.from_dict(
            data["capability_requirement"]
        )
        return cls(
            model_id=str(data["model_id"]),
            model_version=str(data["model_version"]),
            framework=str(data["framework"]),
            artifact_reference=artifact_reference,
            provenance=provenance,
            safety_flag_set=safety_flag_set,
            capability_requirement=capability_requirement,
            description=str(data.get("description", "")),
            summary=dict(data.get("summary", {}) or {}),
        )


# ---------------------------------------------------------------------------
# DeploymentPackageManifest
# ---------------------------------------------------------------------------


_MANIFEST_FIELDS: tuple[str, ...] = (
    "envelope",
    "package_id",
    "package_version",
    "safety_declaration",
    "capability_requirement",
    "provenance",
    "artifacts",
    "model_artifacts",
    "bundles",
    "diagnostics",
    "notes",
)


@dataclass(frozen=True)
class DeploymentPackageManifest:
    """Top-level audit-evidence deployment package manifest.

    Composed from:

    * :class:`ContractEnvelope` (schema family must be ``"manifest"``);
    * a :class:`PackageSafetyDeclaration` whose ``package_id`` matches
      the manifest's own;
    * a :class:`CapabilityRequirement` whose ``package_id`` also
      matches;
    * a :class:`Provenance` record;
    * tuples of :class:`ArtifactManifest`, :class:`ModelArtifactRecord`,
      and :class:`ArtifactBundleRecord`;
    * a :class:`PackageValidationDiagnostic` for warnings / errors.

    This is the SDK shape the Sprint 45 Edge package validator will
    consume. Nothing in this dataclass represents a write, dispatch,
    actuation, setpoint, or control surface.
    """

    envelope: ContractEnvelope
    package_id: str
    package_version: str
    safety_declaration: PackageSafetyDeclaration
    capability_requirement: CapabilityRequirement
    provenance: Provenance
    artifacts: tuple[ArtifactManifest, ...] = ()
    model_artifacts: tuple[ModelArtifactRecord, ...] = ()
    bundles: tuple[ArtifactBundleRecord, ...] = ()
    diagnostics: PackageValidationDiagnostic = field(
        default_factory=PackageValidationDiagnostic
    )
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, ContractEnvelope):
            raise ContractError(
                "DeploymentPackageManifest.envelope must be a "
                "ContractEnvelope instance"
            )
        if self.envelope.schema_family != "manifest":
            raise ContractError(
                f"DeploymentPackageManifest.envelope.schema_family must be "
                f"'manifest', got {self.envelope.schema_family!r}"
            )
        _ensure_string_field(
            self.package_id, label="DeploymentPackageManifest.package_id"
        )
        _ensure_string_field(
            self.package_version,
            label="DeploymentPackageManifest.package_version",
        )
        if not isinstance(self.safety_declaration, PackageSafetyDeclaration):
            raise ContractError(
                "DeploymentPackageManifest.safety_declaration must be a "
                "PackageSafetyDeclaration instance"
            )
        if self.safety_declaration.package_id != self.package_id:
            raise ContractError(
                "DeploymentPackageManifest.safety_declaration.package_id "
                f"{self.safety_declaration.package_id!r} does not match "
                f"manifest package_id {self.package_id!r}"
            )
        if not isinstance(self.capability_requirement, CapabilityRequirement):
            raise ContractError(
                "DeploymentPackageManifest.capability_requirement must be a "
                "CapabilityRequirement instance"
            )
        if self.capability_requirement.package_id != self.package_id:
            raise ContractError(
                "DeploymentPackageManifest.capability_requirement.package_id "
                f"{self.capability_requirement.package_id!r} does not match "
                f"manifest package_id {self.package_id!r}"
            )
        if not isinstance(self.provenance, Provenance):
            raise ContractError(
                "DeploymentPackageManifest.provenance must be a Provenance "
                "instance"
            )
        for field_name, expected_type in (
            ("artifacts", ArtifactManifest),
            ("model_artifacts", ModelArtifactRecord),
            ("bundles", ArtifactBundleRecord),
        ):
            raw = getattr(self, field_name)
            if not isinstance(raw, tuple):
                raise ContractError(
                    f"DeploymentPackageManifest.{field_name} must be a tuple"
                )
            for entry in raw:
                if not isinstance(entry, expected_type):
                    raise ContractError(
                        f"DeploymentPackageManifest.{field_name} entries "
                        f"must be {expected_type.__name__} instances"
                    )
        if not isinstance(self.diagnostics, PackageValidationDiagnostic):
            raise ContractError(
                "DeploymentPackageManifest.diagnostics must be a "
                "PackageValidationDiagnostic instance"
            )
        _ensure_string_field(
            self.notes,
            label="DeploymentPackageManifest.notes",
            allow_empty=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope": self.envelope.to_dict(),
            "package_id": self.package_id,
            "package_version": self.package_version,
            "safety_declaration": self.safety_declaration.to_dict(),
            "capability_requirement": self.capability_requirement.to_dict(),
            "provenance": self.provenance.to_dict(),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "model_artifacts": [m.to_dict() for m in self.model_artifacts],
            "bundles": [b.to_dict() for b in self.bundles],
            "diagnostics": self.diagnostics.to_dict(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DeploymentPackageManifest":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"DeploymentPackageManifest.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        _reject_forbidden_field_names(
            data, label="DeploymentPackageManifest"
        )
        missing = {
            "envelope",
            "package_id",
            "package_version",
            "safety_declaration",
            "capability_requirement",
            "provenance",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"DeploymentPackageManifest missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_MANIFEST_FIELDS)
        if unknown:
            raise ContractError(
                f"DeploymentPackageManifest received unknown fields: "
                f"{sorted(unknown)}"
            )
        envelope_raw = data["envelope"]
        if not isinstance(envelope_raw, Mapping):
            raise ContractError(
                "DeploymentPackageManifest.envelope must be a mapping"
            )
        envelope = ContractEnvelope.from_dict(envelope_raw)
        provenance_raw = data["provenance"]
        if not isinstance(provenance_raw, Mapping):
            raise ContractError(
                "DeploymentPackageManifest.provenance must be a mapping"
            )
        provenance = Provenance.from_dict(provenance_raw)
        safety_declaration = PackageSafetyDeclaration.from_dict(
            data["safety_declaration"]
        )
        capability_requirement = CapabilityRequirement.from_dict(
            data["capability_requirement"]
        )
        for seq_name in ("artifacts", "model_artifacts", "bundles"):
            raw = data.get(seq_name, ()) or ()
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                raise ContractError(
                    f"DeploymentPackageManifest.{seq_name} must be a sequence"
                )
        artifacts = tuple(
            ArtifactManifest.from_dict(a)
            for a in (data.get("artifacts", ()) or ())
        )
        model_artifacts = tuple(
            ModelArtifactRecord.from_dict(m)
            for m in (data.get("model_artifacts", ()) or ())
        )
        bundles = tuple(
            ArtifactBundleRecord.from_dict(b)
            for b in (data.get("bundles", ()) or ())
        )
        diagnostics_raw = data.get("diagnostics")
        diagnostics = (
            PackageValidationDiagnostic.from_dict(diagnostics_raw)
            if isinstance(diagnostics_raw, Mapping)
            else PackageValidationDiagnostic()
        )
        return cls(
            envelope=envelope,
            package_id=str(data["package_id"]),
            package_version=str(data["package_version"]),
            safety_declaration=safety_declaration,
            capability_requirement=capability_requirement,
            provenance=provenance,
            artifacts=artifacts,
            model_artifacts=model_artifacts,
            bundles=bundles,
            diagnostics=diagnostics,
            notes=str(data.get("notes", "")),
        )


# ---------------------------------------------------------------------------
# Builders / projections from existing SDK contracts
# ---------------------------------------------------------------------------


def _shadow_artifact_role(kind: str) -> str:
    """Map a Sprint 42 shadow deployment artifact kind to a Sprint 44 role.

    Only the canonical SDK shadow kinds map cleanly into the Sprint
    44 role vocabulary. ``file`` and ``blob`` fall through to
    ``"audit_evidence"`` because they are deliberately under-specified
    on the Sprint 42 side.
    """
    if kind in PACKAGE_ARTIFACT_ROLES:
        return kind
    return "audit_evidence"


def build_deployment_package_manifest_from_shadow(
    shadow: ShadowDeploymentManifest,
    *,
    capability_requirement: CapabilityRequirement,
    provenance: Provenance,
    schema_version: str = "1.0.0",
    created_at: str | None = None,
    created_by_component: str | None = "ai_server",
) -> DeploymentPackageManifest:
    """Project a Sprint 42 ``ShadowDeploymentManifest`` into the Sprint 44
    ``DeploymentPackageManifest`` shape.

    The Sprint 42 shadow manifest is the lightest SDK projection we
    have today; this builder lets a packager promote one into the
    fuller Sprint 44 audit-evidence shape without depending on Phase
    1 runtime code.

    Parameters
    ----------
    shadow
        Frozen Sprint 42 shadow deployment manifest.
    capability_requirement
        Required capability bundle for the resulting package. Its
        ``package_id`` must match ``shadow.package_name``.
    provenance
        Producing component / version metadata for the new manifest.
    schema_version, created_at, created_by_component
        Optional envelope fields. ``schema_version`` defaults to
        ``"1.0.0"``; the rest default to the shadow manifest's
        ``created_at`` and to ``"ai_server"``.
    """
    if not isinstance(shadow, ShadowDeploymentManifest):
        raise ContractError(
            "build_deployment_package_manifest_from_shadow requires a "
            "ShadowDeploymentManifest instance"
        )
    if not isinstance(capability_requirement, CapabilityRequirement):
        raise ContractError(
            "build_deployment_package_manifest_from_shadow requires a "
            "CapabilityRequirement instance"
        )
    if capability_requirement.package_id != shadow.package_name:
        raise ContractError(
            "capability_requirement.package_id "
            f"{capability_requirement.package_id!r} does not match shadow "
            f"package_name {shadow.package_name!r}"
        )
    if not isinstance(provenance, Provenance):
        raise ContractError(
            "build_deployment_package_manifest_from_shadow requires a "
            "Provenance instance"
        )
    envelope = ContractEnvelope(
        schema_family="manifest",
        schema_name="deployment_package_manifest",
        schema_version=type(shadow.sdk_version).parse(schema_version),
        sdk_version=SDK_VERSION,
        created_at=created_at if created_at is not None else (
            shadow.created_at or None
        ),
        created_by_component=created_by_component,
    )
    safety_declaration = PackageSafetyDeclaration(
        package_id=shadow.package_name,
        package_version=shadow.package_version or "0.0.0",
        safety_flag_set=shadow.safety_flag_set,
        capability_requirement=capability_requirement,
        acknowledged_at="",
        notes="",
    )
    artifacts: tuple[ArtifactManifest, ...] = tuple(
        ArtifactManifest(
            role=_shadow_artifact_role(entry.kind),
            artifact_reference=ArtifactReference(
                kind=entry.kind,
                id=entry.artifact_id or entry.name,
                version=shadow.package_version or "0.0.0",
                checksum=(
                    Checksum(
                        algorithm="sha256",
                        hex_digest=entry.sha256,
                        size_bytes=(
                            entry.size_bytes if entry.size_bytes is not None
                            else 0
                        ),
                    )
                    if entry.sha256 and len(entry.sha256) == 64
                    else None
                ),
            ),
            provenance=provenance,
            description=entry.description,
            summary=dict(entry.summary),
        )
        for entry in shadow.artifacts
    )
    diagnostics = PackageValidationDiagnostic(
        warnings=shadow.diagnostics.warnings,
        errors=shadow.diagnostics.errors,
    )
    return DeploymentPackageManifest(
        envelope=envelope,
        package_id=shadow.package_name,
        package_version=shadow.package_version or "0.0.0",
        safety_declaration=safety_declaration,
        capability_requirement=capability_requirement,
        provenance=provenance,
        artifacts=artifacts,
        diagnostics=diagnostics,
        notes=shadow.notes,
    )


__all__ = [
    "ArtifactBundleRecord",
    "ArtifactManifest",
    "DeploymentPackageManifest",
    "ModelArtifactRecord",
    "PACKAGE_ARTIFACT_ROLES",
    "PACKAGE_MODEL_FRAMEWORKS",
    "PackageSafetyDeclaration",
    "PackageValidationDiagnostic",
    "build_deployment_package_manifest_from_shadow",
]
