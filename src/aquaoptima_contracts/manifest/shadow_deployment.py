"""``ShadowDeploymentManifest`` SDK projection (Sprint 42).

These types capture the *shape* of the Phase 1 Sprint 39 manifest.
The Phase 1 runtime module ``aquaoptima.dphm.shadow_deployment``
continues to own the builder, the hashing path, and the JSON writer.
The SDK projection here keeps the public schema compatible so any
deployable can deserialize and inspect a Phase 1 manifest.

The manifest is packaging / audit-evidence only. The SDK never
introduces a setpoint, write, command, or control field — the
forbidden vocabulary scan and the schema validation here both
enforce that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..safety.flags import SafetyFlagSet
from ..version import SDK_VERSION, SchemaVersion


# Canonical SDK shadow deployment artifact kinds. Sprint 42 mirrors
# the Phase 1 Sprint 39 token list so a manifest written by the
# runtime is readable by the SDK projection and vice versa.
SDK_SHADOW_DEPLOYMENT_ARTIFACT_KINDS: frozenset[str] = frozenset(
    {
        "shadow_replay_dataset",
        "dpl_calibration_loss_report",
        "advisory_contract",
        "advisory_audit_decisions",
        "shadow_runtime_report",
        "file",
        "blob",
    }
)


_ARTIFACT_FIELDS: tuple[str, ...] = (
    "kind",
    "name",
    "artifact_id",
    "path",
    "sha256",
    "size_bytes",
    "description",
    "summary",
)


_MANIFEST_FIELDS: tuple[str, ...] = (
    "package_name",
    "package_version",
    "build_id",
    "created_at",
    "code_version",
    "sdk_version",
    "safety_flag_set",
    "artifacts",
    "notes",
    "diagnostics",
)


@dataclass(frozen=True)
class ShadowDeploymentPackageDiagnostics:
    """Deterministic warnings / errors tuples for the SDK manifest."""

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("warnings", "errors"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(v, str) for v in value
            ):
                raise ContractError(
                    f"ShadowDeploymentPackageDiagnostics.{name} must be a "
                    f"tuple of strings"
                )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "ShadowDeploymentPackageDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ShadowDeploymentPackageDiagnostics.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        unknown = set(data.keys()) - {"warnings", "errors"}
        if unknown:
            raise ContractError(
                f"ShadowDeploymentPackageDiagnostics received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            warnings=tuple(str(w) for w in data.get("warnings", ())),
            errors=tuple(str(e) for e in data.get("errors", ())),
        )


def _validate_summary_value(value: Any, *, label: str) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        out: list[Any] = []
        for item in value:
            if not (
                isinstance(item, bool)
                or item is None
                or isinstance(item, (int, float, str))
            ):
                raise ContractError(
                    f"{label}: summary list value contains non-scalar item "
                    f"of type {type(item).__name__}"
                )
            out.append(item)
        return out
    raise ContractError(
        f"{label}: summary value must be scalar or list of scalars, got "
        f"{type(value).__name__}"
    )


@dataclass(frozen=True)
class ShadowDeploymentArtifact:
    """Per-artifact entry within a shadow deployment manifest."""

    kind: str
    name: str
    artifact_id: str = ""
    path: str = ""
    sha256: str = ""
    size_bytes: int | None = None
    description: str = ""
    summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kind, str)
            or self.kind not in SDK_SHADOW_DEPLOYMENT_ARTIFACT_KINDS
        ):
            raise ContractError(
                f"ShadowDeploymentArtifact.kind {self.kind!r} is not in the "
                f"allowed list ({sorted(SDK_SHADOW_DEPLOYMENT_ARTIFACT_KINDS)})"
            )
        if not isinstance(self.name, str) or not self.name:
            raise ContractError(
                "ShadowDeploymentArtifact.name must be a non-empty string"
            )
        for opt in ("artifact_id", "path", "sha256", "description"):
            value = getattr(self, opt)
            if not isinstance(value, str):
                raise ContractError(
                    f"ShadowDeploymentArtifact.{opt} must be a string"
                )
        if self.size_bytes is not None:
            if isinstance(self.size_bytes, bool) or not isinstance(
                self.size_bytes, int
            ):
                raise ContractError(
                    "ShadowDeploymentArtifact.size_bytes must be int or None"
                )
            if self.size_bytes < 0:
                raise ContractError(
                    "ShadowDeploymentArtifact.size_bytes must be non-negative"
                )
        if not isinstance(self.summary, Mapping):
            raise ContractError(
                "ShadowDeploymentArtifact.summary must be a mapping"
            )
        clean_summary: dict[str, Any] = {}
        for key, value in self.summary.items():
            if not isinstance(key, str) or not key:
                raise ContractError(
                    "ShadowDeploymentArtifact.summary keys must be non-empty "
                    "strings"
                )
            clean_summary[key] = _validate_summary_value(
                value,
                label=f"ShadowDeploymentArtifact.summary[{key!r}]",
            )
        object.__setattr__(self, "summary", clean_summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "artifact_id": self.artifact_id,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "description": self.description,
            "summary": dict(self.summary),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShadowDeploymentArtifact":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ShadowDeploymentArtifact.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {"kind", "name"} - set(data.keys())
        if missing:
            raise ContractError(
                f"ShadowDeploymentArtifact missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_ARTIFACT_FIELDS)
        if unknown:
            raise ContractError(
                f"ShadowDeploymentArtifact received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            kind=str(data["kind"]),
            name=str(data["name"]),
            artifact_id=str(data.get("artifact_id", "")),
            path=str(data.get("path", "")),
            sha256=str(data.get("sha256", "")),
            size_bytes=(
                int(data["size_bytes"])
                if data.get("size_bytes") is not None
                else None
            ),
            description=str(data.get("description", "")),
            summary=dict(data.get("summary", {}) or {}),
        )


@dataclass(frozen=True)
class ShadowDeploymentManifest:
    """Frozen SDK projection of a Phase 1 shadow deployment manifest."""

    package_name: str
    safety_flag_set: SafetyFlagSet
    package_version: str = ""
    build_id: str = ""
    created_at: str = "1970-01-01T00:00:00Z"
    code_version: str = "unknown"
    sdk_version: SchemaVersion = SDK_VERSION
    artifacts: tuple[ShadowDeploymentArtifact, ...] = ()
    notes: str = ""
    diagnostics: ShadowDeploymentPackageDiagnostics = field(
        default_factory=ShadowDeploymentPackageDiagnostics
    )

    def __post_init__(self) -> None:
        if not isinstance(self.package_name, str) or not self.package_name:
            raise ContractError(
                "ShadowDeploymentManifest.package_name must be a non-empty string"
            )
        for opt in ("package_version", "build_id", "created_at", "code_version", "notes"):
            value = getattr(self, opt)
            if not isinstance(value, str):
                raise ContractError(
                    f"ShadowDeploymentManifest.{opt} must be a string"
                )
        if not isinstance(self.safety_flag_set, SafetyFlagSet):
            raise ContractError(
                "ShadowDeploymentManifest.safety_flag_set must be a "
                "SafetyFlagSet instance"
            )
        if not isinstance(self.sdk_version, SchemaVersion):
            raise ContractError(
                "ShadowDeploymentManifest.sdk_version must be a SchemaVersion"
            )
        if not isinstance(self.artifacts, tuple):
            raise ContractError(
                "ShadowDeploymentManifest.artifacts must be a tuple"
            )
        for artifact in self.artifacts:
            if not isinstance(artifact, ShadowDeploymentArtifact):
                raise ContractError(
                    "ShadowDeploymentManifest.artifacts entries must be "
                    "ShadowDeploymentArtifact instances"
                )
        if not isinstance(self.diagnostics, ShadowDeploymentPackageDiagnostics):
            raise ContractError(
                "ShadowDeploymentManifest.diagnostics must be a "
                "ShadowDeploymentPackageDiagnostics instance"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_name": self.package_name,
            "package_version": self.package_version,
            "build_id": self.build_id,
            "created_at": self.created_at,
            "code_version": self.code_version,
            "sdk_version": self.sdk_version.render(),
            "safety_flag_set": self.safety_flag_set.to_dict(),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "notes": self.notes,
            "diagnostics": self.diagnostics.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShadowDeploymentManifest":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ShadowDeploymentManifest.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {"package_name", "safety_flag_set"} - set(data.keys())
        if missing:
            raise ContractError(
                f"ShadowDeploymentManifest missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_MANIFEST_FIELDS)
        if unknown:
            raise ContractError(
                f"ShadowDeploymentManifest received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_artifacts = data.get("artifacts", ())
        if not isinstance(raw_artifacts, Sequence) or isinstance(
            raw_artifacts, (str, bytes)
        ):
            raise ContractError(
                "ShadowDeploymentManifest.artifacts must be a sequence"
            )
        sdk_version_raw = data.get("sdk_version")
        sdk_version = (
            SchemaVersion.parse(str(sdk_version_raw))
            if sdk_version_raw is not None
            else SDK_VERSION
        )
        return cls(
            package_name=str(data["package_name"]),
            safety_flag_set=SafetyFlagSet.from_dict(data["safety_flag_set"]),
            package_version=str(data.get("package_version", "")),
            build_id=str(data.get("build_id", "")),
            created_at=str(data.get("created_at", "1970-01-01T00:00:00Z")),
            code_version=str(data.get("code_version", "unknown")),
            sdk_version=sdk_version,
            artifacts=tuple(
                ShadowDeploymentArtifact.from_dict(a) for a in raw_artifacts
            ),
            notes=str(data.get("notes", "")),
            diagnostics=ShadowDeploymentPackageDiagnostics.from_dict(
                data.get("diagnostics", {})
            ),
        )
