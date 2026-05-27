"""Shadow-mode deployment packaging (Sprint 39).

Sprint 39 closes the offline shadow-mode MVP loop opened by Sprints
34-38 with a small, typed, deterministic *export / packaging* surface.
It collects per-artifact metadata (replay datasets, calibration loss
reports, advisory audit decisions, shadow runtime reports) into a
single frozen :class:`ShadowDeploymentManifest` and provides a
stdlib-only JSON writer for the manifest itself.

Sprint 39 is **offline / read-only / no-write / no-control / no live
OT binding / no setpoint output / packaging / audit only**. The
"deployment" in :class:`ShadowDeploymentManifest` refers to a
packaging / audit-evidence bundle for **shadow-mode MVP** artifacts —
**not** to a live OT deployment, **not** to a service runtime,
**not** to a controller, **not** to an advisory emission layer. The
manifest is a value the caller can serialise, hash, diff, and review
offline; it is **never** transformed into a setpoint write here.

This module contains:

* :class:`ShadowDeploymentPackageDiagnostics` — deterministic warnings
  / errors tuples.
* :class:`ShadowDeploymentArtifact` — frozen per-artifact metadata.
* :class:`ShadowDeploymentManifest` — frozen top-level manifest.
* :func:`build_shadow_deployment_manifest` — pure deterministic
  builder; never opens a socket / live OT binding; never writes a
  setpoint.
* :func:`write_shadow_deployment_manifest_json` — stdlib-only JSON
  writer that writes **only** the manifest JSON to a caller-specified
  local path. Never writes other files.

Safety boundary (reaffirmed verbatim per Sprints 23-38):

* no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter is imported, registered, or polled;
* no write / control / setpoint path is exposed;
* no live OT binding is opened;
* no actuator / write surface is offered;
* no setpoint output is emitted, even when summarising accepted
  advisory decisions;
* no automatic setpoint recommendation is produced — Sprint 39 only
  packages **audit evidence** for shadow-mode MVP artifacts;
* no dPHM forward solve is invoked;
* no training loop / optimiser integration is performed;
* no ONNX / TensorRT / Jetson deployment is performed;
* no production savings / control claim is made;
* no credentials, API keys, tokens, passwords, secrets, or connection
  strings are ever read, hashed, or embedded in the manifest;
* the JSON writer is the **only** filesystem write; it writes the
  manifest JSON to the caller-supplied path and nothing else.

Sprint 39 is **not** a live deployment service, **not** a controller,
**not** a container builder, **not** a CI/CD pipeline, and **not** a
training loop. A future advisory / supervised-control deployment
would consume this manifest as offline evidence; that consumption is
out of scope here.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence, Union

from .advisory_contract import (
    ADVISORY_STATUS_ACCEPTED,
    ADVISORY_STATUS_REJECTED,
    AdvisoryContract,
    AdvisoryDecision,
)
from .dpl_calibration import DPLCalibrationLossReport
from .shadow_replay import ShadowReplayDataset
from .shadow_runtime import ShadowRuntimeReport


PathLike = Union[str, "os.PathLike[str]"]


# ---------------------------------------------------------------------------
# Canonical tokens
# ---------------------------------------------------------------------------


# Sprint 39 artifact kinds. Kept deterministic and small.
ARTIFACT_KIND_SHADOW_REPLAY: str = "shadow_replay_dataset"
ARTIFACT_KIND_DPL_LOSS_REPORT: str = "dpl_calibration_loss_report"
ARTIFACT_KIND_ADVISORY_CONTRACT: str = "advisory_contract"
ARTIFACT_KIND_ADVISORY_DECISIONS: str = "advisory_audit_decisions"
ARTIFACT_KIND_SHADOW_RUNTIME_REPORT: str = "shadow_runtime_report"
ARTIFACT_KIND_FILE: str = "file"
ARTIFACT_KIND_BLOB: str = "blob"

SHADOW_DEPLOYMENT_ARTIFACT_KINDS: tuple[str, ...] = (
    ARTIFACT_KIND_SHADOW_REPLAY,
    ARTIFACT_KIND_DPL_LOSS_REPORT,
    ARTIFACT_KIND_ADVISORY_CONTRACT,
    ARTIFACT_KIND_ADVISORY_DECISIONS,
    ARTIFACT_KIND_SHADOW_RUNTIME_REPORT,
    ARTIFACT_KIND_FILE,
    ARTIFACT_KIND_BLOB,
)


# Marker used when the source-tree package version cannot be resolved
# deterministically. The marker is part of the public manifest schema.
UNKNOWN_VERSION_MARKER: str = "unknown"

# Default deterministic timestamp used when the caller does not supply
# one. Chosen as the epoch-style ISO-8601 marker so it never accidentally
# leaks the host clock into a manifest.
DEFAULT_CREATED_AT: str = "1970-01-01T00:00:00Z"

# Safety boundary phrases embedded verbatim in every manifest. The
# tests assert their presence; the writer always emits them.
SAFETY_BOUNDARY_PHRASES: tuple[str, ...] = (
    "offline",
    "read-only",
    "no-write",
    "no-control",
    "no live OT binding",
    "no setpoint output",
    "packaging/audit only",
)


# ---------------------------------------------------------------------------
# Frozen dataclass surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShadowDeploymentPackageDiagnostics:
    """Deterministic warnings / errors tuples for a manifest build.

    Both tuples are empty for a fully-valid input. Warnings are
    non-fatal observations (an artifact whose path does not exist on
    disk in non-strict mode, an artifact with no content / path / id);
    errors are structural problems (a malformed artifact entry in
    non-strict mode, an unsupported summary object in non-strict
    mode).

    In ``strict=True`` mode the builder raises :class:`ValueError`
    instead of returning a populated ``errors`` tuple. Warnings are
    *always* returned through this surface.

    Attributes
    ----------
    warnings
        Deterministic tuple of human-readable warning strings, in
        encounter order.
    errors
        Deterministic tuple of human-readable error strings, in
        encounter order.
    """

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowDeploymentArtifact:
    """Frozen per-artifact metadata entry within a manifest.

    Carries enough metadata for an offline reviewer to identify an
    artifact (kind, name, optional path / id) and verify its content
    (sha256 over the supplied bytes / path content, size in bytes).
    Sprint 39 **never** reads, hashes, or embeds credentials; the
    artifact builder rejects fields that look like credential
    payloads, and the JSON writer only emits the public manifest
    schema.

    Attributes
    ----------
    kind
        One of :data:`SHADOW_DEPLOYMENT_ARTIFACT_KINDS`. Identifies
        the artifact category for downstream review.
    name
        Non-empty deterministic name (e.g. file basename or logical
        identifier). Kept verbatim.
    artifact_id
        Optional logical identifier (e.g. a content-addressed id or a
        Sprint-internal label). ``""`` means "no id".
    path
        Optional caller-supplied path string (relative or absolute).
        Kept verbatim as a string — the manifest never resolves it.
        ``""`` means "no path".
    sha256
        Optional lowercase hex digest of the artifact content. ``""``
        means "no hash was computed".
    size_bytes
        Optional non-negative byte size of the artifact content.
        ``None`` means "size unknown".
    description
        Optional free-form description kept verbatim.
    summary
        Optional ``{key: value}`` mapping carrying scalar summary
        statistics (e.g. ``observation_count``, ``proposal_count``).
        Values must be JSON-scalar (``str``, ``int``, ``float``,
        ``bool``, ``None``). Sequences of scalars are also accepted.
    """

    kind: str
    name: str
    artifact_id: str = ""
    path: str = ""
    sha256: str = ""
    size_bytes: int | None = None
    description: str = ""
    summary: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ShadowDeploymentManifest:
    """Frozen, read-only shadow-mode MVP deployment manifest.

    The "deployment" in this manifest is **packaging / audit
    evidence only** — Sprint 39 does **not** deploy to live OT, does
    **not** spawn a service runtime, does **not** emit setpoints, and
    does **not** open any live binding. The manifest is a value the
    caller can serialise, hash, diff, and review offline.

    Attributes
    ----------
    package_name
        Non-empty deterministic package name (e.g.
        ``"aquaoptima-dphm-shadow-mvp"``).
    package_version
        Optional package version string. ``""`` means "no package
        version supplied".
    build_id
        Optional build identifier (e.g. a CI run id or a content hash
        of the bundle). ``""`` means "no build id".
    created_at
        Caller-supplied deterministic timestamp string. Defaults to
        :data:`DEFAULT_CREATED_AT` so the manifest is reproducible
        from the same inputs regardless of host clock.
    code_version
        Resolved code / package version. When the caller does not
        supply ``code_version`` and the in-tree package version is
        unavailable, the value is :data:`UNKNOWN_VERSION_MARKER`.
    artifacts
        Tuple of :class:`ShadowDeploymentArtifact` entries in
        deterministic builder-input order. Multiple artifacts of the
        same kind are allowed.
    safety_boundary
        Deterministic tuple of safety-boundary phrases embedded in
        the manifest. Always contains every entry of
        :data:`SAFETY_BOUNDARY_PHRASES`.
    safety_flags
        Frozen mapping of boolean safety flags
        (``{"offline": True, ...}``). The set of keys is fixed
        verbatim per build so manifests are diffable across runs.
    references
        Frozen mapping of cross-sprint summary references — e.g.
        ``{"shadow_replay_dataset": {"frame_count": 3}}``. Values are
        JSON-scalar dictionaries.
    notes
        Optional free-form note string kept verbatim.
    diagnostics
        Build-level :class:`ShadowDeploymentPackageDiagnostics`.
    """

    package_name: str = ""
    package_version: str = ""
    build_id: str = ""
    created_at: str = DEFAULT_CREATED_AT
    code_version: str = UNKNOWN_VERSION_MARKER
    artifacts: tuple[ShadowDeploymentArtifact, ...] = ()
    safety_boundary: tuple[str, ...] = SAFETY_BOUNDARY_PHRASES
    safety_flags: Mapping[str, bool] = field(default_factory=dict)
    references: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    notes: str = ""
    diagnostics: ShadowDeploymentPackageDiagnostics = field(
        default_factory=ShadowDeploymentPackageDiagnostics
    )


# ---------------------------------------------------------------------------
# Caller artifact spec
# ---------------------------------------------------------------------------


# Caller-side artifact specification (a mapping). Builder validates
# every field. Recognised keys:
#   kind        (required)  one of SHADOW_DEPLOYMENT_ARTIFACT_KINDS
#   name        (required)  non-empty string
#   artifact_id (optional)  string
#   path        (optional)  PathLike — hashed if `hash=True` and the
#                          path exists; kept verbatim in the manifest
#   content     (optional)  bytes — hashed verbatim; never embedded
#   sha256      (optional)  pre-computed lowercase hex digest
#   size_bytes  (optional)  non-negative int
#   description (optional)  string
#   summary     (optional)  Mapping[str, JSON-scalar]
#   hash        (optional)  bool (default True) — controls path hashing
ArtifactSpec = Mapping[str, object]


# Recognised summary object kinds — used when a caller supplies the
# typed Sprint 35-38 object directly via ``summary_objects``. Each
# entry maps from a public Sprint class to a deterministic summary
# extractor.
_SUMMARY_EXTRACTORS = {
    "ShadowReplayDataset": (
        ShadowReplayDataset,
        ARTIFACT_KIND_SHADOW_REPLAY,
        "shadow_replay_dataset",
        lambda obj: {
            "frame_count": len(obj.frames),
            "diagnostic_warning_count": len(obj.diagnostics.warnings),
            "diagnostic_error_count": len(obj.diagnostics.errors),
        },
    ),
    "DPLCalibrationLossReport": (
        DPLCalibrationLossReport,
        ARTIFACT_KIND_DPL_LOSS_REPORT,
        "dpl_calibration_loss_report",
        lambda obj: {
            "observation_count": obj.observation_count,
            "weighted_mse": float(obj.weighted_mse),
            "axis_count": len(obj.mse_by_axis),
            "diagnostic_warning_count": len(obj.diagnostics.warnings),
            "diagnostic_error_count": len(obj.diagnostics.errors),
        },
    ),
    "AdvisoryContract": (
        AdvisoryContract,
        ARTIFACT_KIND_ADVISORY_CONTRACT,
        "advisory_contract",
        lambda obj: {
            "name": obj.name,
            "allow_rule_count": len(obj.allow_rules),
            "deny_rule_count": len(obj.deny_rules),
            "diagnostic_warning_count": len(obj.diagnostics.warnings),
            "diagnostic_error_count": len(obj.diagnostics.errors),
        },
    ),
    "ShadowRuntimeReport": (
        ShadowRuntimeReport,
        ARTIFACT_KIND_SHADOW_RUNTIME_REPORT,
        "shadow_runtime_report",
        lambda obj: {
            "frame_count": obj.frame_count,
            "observation_count": obj.observation_count,
            "proposal_count": obj.proposal_count,
            "accepted_count": obj.accepted_count,
            "rejected_count": obj.rejected_count,
            "weighted_mse": float(obj.loss_report.weighted_mse),
            "diagnostic_warning_count": len(obj.diagnostics.warnings),
            "diagnostic_error_count": len(obj.diagnostics.errors),
        },
    ),
}


# Forbidden summary-key fragments — guard against accidental
# credential leakage. Tests assert these never appear in a manifest.
_FORBIDDEN_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "connection_string",
    "conn_str",
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _is_json_scalar(value: object) -> bool:
    if isinstance(value, bool):
        return True
    if value is None:
        return True
    if isinstance(value, (int, float, str)):
        return True
    return False


def _validate_summary_mapping(
    summary: object, *, label: str
) -> tuple[dict[str, object] | None, str | None]:
    """Validate a summary mapping. Returns ``(clean, error)``."""
    if summary is None:
        return {}, None
    if not isinstance(summary, Mapping):
        return None, (
            f"{label}: summary must be a Mapping, got "
            f"{type(summary).__name__}"
        )
    clean: dict[str, object] = {}
    for raw_key, value in summary.items():
        if not isinstance(raw_key, str):
            return None, (
                f"{label}: summary keys must be strings, got "
                f"{type(raw_key).__name__}"
            )
        if not raw_key:
            return None, f"{label}: summary keys must be non-empty"
        key_lower = raw_key.lower()
        for fragment in _FORBIDDEN_KEY_FRAGMENTS:
            if fragment in key_lower:
                return None, (
                    f"{label}: summary key {raw_key!r} contains forbidden "
                    f"fragment {fragment!r} (credentials are never embedded)"
                )
        if _is_json_scalar(value):
            clean[raw_key] = value
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                if not _is_json_scalar(item):
                    return None, (
                        f"{label}: summary value for {raw_key!r} contains a "
                        f"non-scalar item of type {type(item).__name__}"
                    )
            clean[raw_key] = list(value)
            continue
        return None, (
            f"{label}: summary value for {raw_key!r} must be a JSON scalar "
            f"or sequence of scalars, got {type(value).__name__}"
        )
    return clean, None


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_of_path(path: Path) -> tuple[str | None, int | None, str | None]:
    """Stream-hash a file. Returns ``(sha256, size, error)``."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, None, f"could not stat {str(path)!r}: {exc}"
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                hasher.update(chunk)
    except OSError as exc:
        return None, None, f"could not read {str(path)!r}: {exc}"
    return hasher.hexdigest(), size, None


def _validate_artifact_spec(
    spec: object, index: int
) -> tuple[ShadowDeploymentArtifact | None, list[str], str | None]:
    """Validate one caller-supplied artifact spec.

    Returns ``(artifact, warnings, error)``. ``error`` is non-``None``
    when the spec is unrecoverable (the artifact is dropped in
    non-strict mode and the builder raises in strict mode).
    """
    label = f"artifacts[{index}]"
    warnings: list[str] = []
    if not isinstance(spec, Mapping):
        return None, warnings, (
            f"{label}: artifact spec must be a Mapping, got "
            f"{type(spec).__name__}"
        )
    kind = spec.get("kind")
    if not isinstance(kind, str) or not kind:
        return None, warnings, (
            f"{label}: 'kind' must be a non-empty string, got {kind!r}"
        )
    if kind not in SHADOW_DEPLOYMENT_ARTIFACT_KINDS:
        return None, warnings, (
            f"{label}: unsupported artifact kind {kind!r}; expected one of "
            f"{list(SHADOW_DEPLOYMENT_ARTIFACT_KINDS)!r}"
        )
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        return None, warnings, (
            f"{label}: 'name' must be a non-empty string, got {name!r}"
        )

    artifact_id = spec.get("artifact_id", "")
    if not isinstance(artifact_id, str):
        return None, warnings, (
            f"{label}: 'artifact_id' must be a string, got "
            f"{type(artifact_id).__name__}"
        )

    raw_path = spec.get("path", "")
    if raw_path is None:
        path_str = ""
    elif isinstance(raw_path, str):
        path_str = raw_path
    elif isinstance(raw_path, os.PathLike):
        path_str = os.fspath(raw_path)
    else:
        return None, warnings, (
            f"{label}: 'path' must be a string / PathLike or omitted, got "
            f"{type(raw_path).__name__}"
        )

    description = spec.get("description", "")
    if not isinstance(description, str):
        return None, warnings, (
            f"{label}: 'description' must be a string, got "
            f"{type(description).__name__}"
        )

    summary_clean, summary_err = _validate_summary_mapping(
        spec.get("summary"), label=label
    )
    if summary_err is not None:
        return None, warnings, summary_err

    pre_sha = spec.get("sha256", "")
    if pre_sha is None:
        pre_sha = ""
    if not isinstance(pre_sha, str):
        return None, warnings, (
            f"{label}: 'sha256' must be a string when supplied, got "
            f"{type(pre_sha).__name__}"
        )
    if pre_sha:
        pre_sha_lower = pre_sha.lower()
        try:
            int(pre_sha_lower, 16)
            valid_hex = True
        except ValueError:
            valid_hex = False
        if len(pre_sha_lower) != 64 or not valid_hex:
            return None, warnings, (
                f"{label}: 'sha256' must be a 64-character lowercase hex "
                f"digest when supplied"
            )

    raw_size = spec.get("size_bytes")
    if raw_size is None:
        size_bytes: int | None = None
    elif isinstance(raw_size, bool) or not isinstance(raw_size, int):
        return None, warnings, (
            f"{label}: 'size_bytes' must be a non-negative int or omitted, "
            f"got {type(raw_size).__name__}"
        )
    elif raw_size < 0:
        return None, warnings, (
            f"{label}: 'size_bytes' must be non-negative, got {raw_size}"
        )
    else:
        size_bytes = int(raw_size)

    content = spec.get("content")
    if content is not None and not isinstance(content, (bytes, bytearray)):
        return None, warnings, (
            f"{label}: 'content' must be bytes when supplied, got "
            f"{type(content).__name__}"
        )

    hash_flag = spec.get("hash", True)
    if not isinstance(hash_flag, bool):
        return None, warnings, (
            f"{label}: 'hash' must be a bool when supplied, got "
            f"{type(hash_flag).__name__}"
        )

    sha256 = pre_sha.lower() if pre_sha else ""

    # Content takes precedence over path for hashing — bytes are
    # always deterministic; paths may not exist.
    if hash_flag and content is not None:
        data = bytes(content)
        computed = _sha256_of_bytes(data)
        if sha256 and sha256 != computed:
            return None, warnings, (
                f"{label}: supplied 'sha256' does not match the sha256 of "
                f"'content'"
            )
        sha256 = computed
        if size_bytes is None:
            size_bytes = len(data)
        elif size_bytes != len(data):
            return None, warnings, (
                f"{label}: supplied 'size_bytes' does not match the length "
                f"of 'content'"
            )
    elif hash_flag and path_str:
        path_obj = Path(path_str)
        if path_obj.exists() and path_obj.is_file():
            digest, file_size, hash_err = _sha256_of_path(path_obj)
            if hash_err is not None:
                warnings.append(f"{label}: {hash_err}")
            else:
                if sha256 and sha256 != digest:
                    return None, warnings, (
                        f"{label}: supplied 'sha256' does not match the "
                        f"sha256 of the file at {path_str!r}"
                    )
                sha256 = digest or sha256
                if size_bytes is None and file_size is not None:
                    size_bytes = file_size
        else:
            warnings.append(
                f"{label}: path {path_str!r} does not exist or is not a "
                f"regular file; sha256 / size were not computed from it"
            )

    artifact = ShadowDeploymentArtifact(
        kind=kind,
        name=name,
        artifact_id=artifact_id,
        path=path_str,
        sha256=sha256,
        size_bytes=size_bytes,
        description=description,
        summary=dict(summary_clean or {}),
    )
    return artifact, warnings, None


def _summarise_object(
    obj: object, index: int
) -> tuple[ShadowDeploymentArtifact | None, str | None]:
    """Build an artifact from a recognised typed Sprint 35-38 object."""
    label = f"summary_objects[{index}]"
    for _, (cls, kind, default_name, extractor) in _SUMMARY_EXTRACTORS.items():
        if isinstance(obj, cls):
            try:
                summary = extractor(obj)
            except Exception as exc:  # noqa: BLE001 - deterministic surface
                return None, (
                    f"{label}: extractor for {cls.__name__} raised "
                    f"{type(exc).__name__}: {exc}"
                )
            summary_clean, err = _validate_summary_mapping(
                summary, label=label
            )
            if err is not None:
                return None, err
            return (
                ShadowDeploymentArtifact(
                    kind=kind,
                    name=default_name,
                    description=(
                        f"summary of {cls.__name__} "
                        f"(packaging/audit only, no setpoint output)"
                    ),
                    summary=dict(summary_clean or {}),
                ),
                None,
            )
    return None, (
        f"{label}: unsupported summary object type {type(obj).__name__}; "
        f"expected one of "
        f"{[cls.__name__ for _, (cls, *_rest) in _SUMMARY_EXTRACTORS.items()]}"
    )


def _resolve_code_version(supplied: str | None) -> str:
    if supplied is not None:
        if not isinstance(supplied, str):
            raise ValueError(
                f"code_version must be a string when supplied, got "
                f"{type(supplied).__name__}"
            )
        return supplied or UNKNOWN_VERSION_MARKER
    # Best-effort introspection of the installed package version. Pure
    # stdlib; never opens a network connection.
    try:
        from importlib.metadata import (  # type: ignore[no-redef]
            PackageNotFoundError,
            version as _version,
        )

        return _version("aquaoptima-dphm-pinn")
    except Exception:  # noqa: BLE001 - any failure → unknown marker
        return UNKNOWN_VERSION_MARKER


def _resolve_safety_flags(
    overrides: Mapping[str, bool] | None,
) -> dict[str, bool]:
    """Return the deterministic safety-flag dict.

    The default set documents that the bundle is offline / read-only /
    no-write / no-control / no live OT binding / no setpoint output /
    packaging / audit only. Overrides may *only* relax to ``True``;
    flipping any safety flag to ``False`` is a programmer error and
    raises (Sprint 39 does not produce manifests that claim a live or
    write-capable bundle).
    """
    flags: dict[str, bool] = {
        "offline": True,
        "read_only": True,
        "no_write": True,
        "no_control": True,
        "no_live_ot_binding": True,
        "no_setpoint_output": True,
        "packaging_audit_only": True,
    }
    if overrides is None:
        return flags
    if not isinstance(overrides, Mapping):
        raise ValueError(
            f"safety_flags must be a Mapping when supplied, got "
            f"{type(overrides).__name__}"
        )
    for key, value in overrides.items():
        if key not in flags:
            raise ValueError(
                f"safety_flags: unknown safety flag {key!r}; expected one "
                f"of {sorted(flags)!r}"
            )
        if not isinstance(value, bool):
            raise ValueError(
                f"safety_flags: flag {key!r} must be a bool, got "
                f"{type(value).__name__}"
            )
        if value is False:
            raise ValueError(
                f"safety_flags: flag {key!r} must remain True — Sprint 39 "
                f"manifests are offline / read-only / no-write / no-control "
                f"/ no live OT binding / no setpoint output / packaging "
                f"audit only"
            )
        flags[key] = value
    return flags


def _validate_references(
    references: Mapping[str, Mapping[str, object]] | None,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Validate a caller-supplied references mapping."""
    warnings: list[str] = []
    if references is None:
        return {}, warnings
    if not isinstance(references, Mapping):
        raise ValueError(
            f"references must be a Mapping when supplied, got "
            f"{type(references).__name__}"
        )
    cleaned: dict[str, dict[str, object]] = {}
    for key, value in references.items():
        if not isinstance(key, str) or not key:
            raise ValueError(
                f"references: keys must be non-empty strings, got {key!r}"
            )
        clean, err = _validate_summary_mapping(
            value, label=f"references[{key!r}]"
        )
        if err is not None:
            raise ValueError(err)
        cleaned[key] = dict(clean or {})
    return cleaned, warnings


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_shadow_deployment_manifest(
    package_name: str,
    *,
    package_version: str = "",
    build_id: str = "",
    created_at: str | None = None,
    code_version: str | None = None,
    artifacts: Sequence[ArtifactSpec] | None = None,
    summary_objects: Sequence[object] | None = None,
    safety_flags: Mapping[str, bool] | None = None,
    references: Mapping[str, Mapping[str, object]] | None = None,
    notes: str = "",
    strict: bool = True,
) -> ShadowDeploymentManifest:
    """Build a deterministic shadow-mode MVP deployment manifest.

    The manifest is **packaging / audit evidence only**:

    * never opens a socket / process / live OT binding;
    * never invokes the dPHM forward solver;
    * never produces a setpoint / write / control output;
    * never reads, hashes, or embeds credentials.

    Parameters
    ----------
    package_name
        Non-empty package / bundle name (e.g.
        ``"aquaoptima-dphm-shadow-mvp"``).
    package_version
        Optional package version string. Kept verbatim.
    build_id
        Optional build identifier kept verbatim.
    created_at
        Optional deterministic timestamp string. When omitted, the
        manifest carries :data:`DEFAULT_CREATED_AT` so the manifest is
        reproducible from the same inputs regardless of host clock.
    code_version
        Optional code / package version. When ``None``, the builder
        attempts ``importlib.metadata.version`` for the installed
        package and falls back to :data:`UNKNOWN_VERSION_MARKER` if
        the package is not installed.
    artifacts
        Optional sequence of artifact specifications (Mapping). Each
        spec is validated; ``content`` bytes are hashed verbatim, and
        ``path`` strings are hashed when the file exists. See the
        module docstring for the schema.
    summary_objects
        Optional sequence of typed Sprint 35-38 objects
        (:class:`ShadowReplayDataset`, :class:`DPLCalibrationLossReport`,
        :class:`AdvisoryContract`, :class:`ShadowRuntimeReport`). Each
        recognised object is converted into a summary artifact with
        deterministic scalar fields.
    safety_flags
        Optional override mapping. Only the recognised keys may be
        overridden, and only to ``True`` (Sprint 39 never claims a
        live or write-capable bundle).
    references
        Optional ``{name: {key: scalar}}`` cross-reference mapping
        kept verbatim (e.g. linking to upstream sprint summary
        stats).
    notes
        Optional free-form note string kept verbatim.
    strict
        When ``True`` (default), malformed artifact specs / unknown
        summary objects raise :class:`ValueError`. When ``False``,
        the offending entry is recorded as a deterministic error
        string on
        :attr:`ShadowDeploymentManifest.diagnostics.errors` and the
        entry is omitted from the manifest.

    Returns
    -------
    ShadowDeploymentManifest
        Frozen manifest in deterministic input order. Calling this
        function twice on the same inputs returns equal manifests.

    Raises
    ------
    ValueError
        See ``strict``. Programmer errors (non-string
        ``package_name``, invalid ``safety_flags`` override, invalid
        ``references``) always raise.
    """
    if not isinstance(package_name, str) or not package_name:
        raise ValueError(
            f"package_name must be a non-empty string, got {package_name!r}"
        )
    if not isinstance(package_version, str):
        raise ValueError(
            f"package_version must be a string, got "
            f"{type(package_version).__name__}"
        )
    if not isinstance(build_id, str):
        raise ValueError(
            f"build_id must be a string, got {type(build_id).__name__}"
        )
    if created_at is None:
        ts = DEFAULT_CREATED_AT
    elif not isinstance(created_at, str) or not created_at:
        raise ValueError(
            f"created_at must be a non-empty string when supplied, got "
            f"{created_at!r}"
        )
    else:
        ts = created_at
    if not isinstance(notes, str):
        raise ValueError(
            f"notes must be a string, got {type(notes).__name__}"
        )

    resolved_code_version = _resolve_code_version(code_version)
    flags = _resolve_safety_flags(safety_flags)
    cleaned_refs, ref_warnings = _validate_references(references)

    warnings: list[str] = list(ref_warnings)
    errors: list[str] = []

    out_artifacts: list[ShadowDeploymentArtifact] = []

    # Recognised typed objects come first, in caller order, so they
    # appear deterministically before file artifacts.
    if summary_objects is not None:
        if isinstance(summary_objects, (str, bytes)):
            raise ValueError(
                "summary_objects must be a Sequence, not a string"
            )
        if not isinstance(summary_objects, Sequence):
            raise ValueError(
                f"summary_objects must be a Sequence when supplied, got "
                f"{type(summary_objects).__name__}"
            )
        for index, obj in enumerate(summary_objects):
            artifact, err = _summarise_object(obj, index)
            if err is not None:
                if strict:
                    raise ValueError(err)
                errors.append(err)
                continue
            assert artifact is not None
            out_artifacts.append(artifact)

    if artifacts is not None:
        if isinstance(artifacts, (str, bytes)):
            raise ValueError("artifacts must be a Sequence, not a string")
        if not isinstance(artifacts, Sequence):
            raise ValueError(
                f"artifacts must be a Sequence when supplied, got "
                f"{type(artifacts).__name__}"
            )
        for index, spec in enumerate(artifacts):
            artifact, spec_warnings, err = _validate_artifact_spec(
                spec, index
            )
            warnings.extend(spec_warnings)
            if err is not None:
                if strict:
                    raise ValueError(err)
                errors.append(err)
                continue
            assert artifact is not None
            out_artifacts.append(artifact)

    diagnostics = ShadowDeploymentPackageDiagnostics(
        warnings=tuple(warnings),
        errors=tuple(errors),
    )

    return ShadowDeploymentManifest(
        package_name=package_name,
        package_version=package_version,
        build_id=build_id,
        created_at=ts,
        code_version=resolved_code_version,
        artifacts=tuple(out_artifacts),
        safety_boundary=SAFETY_BOUNDARY_PHRASES,
        safety_flags=dict(flags),
        references=cleaned_refs,
        notes=notes,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------


def _artifact_to_dict(artifact: ShadowDeploymentArtifact) -> dict[str, object]:
    return {
        "kind": artifact.kind,
        "name": artifact.name,
        "artifact_id": artifact.artifact_id,
        "path": artifact.path,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "description": artifact.description,
        "summary": dict(artifact.summary),
    }


def _manifest_to_dict(
    manifest: ShadowDeploymentManifest,
) -> dict[str, object]:
    """Convert a manifest to a JSON-ready dict with stable key order."""
    return {
        "schema": "aquaoptima.dphm.shadow_deployment_manifest/v1",
        "package_name": manifest.package_name,
        "package_version": manifest.package_version,
        "build_id": manifest.build_id,
        "created_at": manifest.created_at,
        "code_version": manifest.code_version,
        "safety_boundary": list(manifest.safety_boundary),
        "safety_flags": dict(manifest.safety_flags),
        "references": {
            key: dict(value) for key, value in manifest.references.items()
        },
        "notes": manifest.notes,
        "artifacts": [
            _artifact_to_dict(artifact) for artifact in manifest.artifacts
        ],
        "diagnostics": {
            "warnings": list(manifest.diagnostics.warnings),
            "errors": list(manifest.diagnostics.errors),
        },
    }


def write_shadow_deployment_manifest_json(
    manifest: ShadowDeploymentManifest, path: PathLike
) -> Path:
    """Write the manifest JSON to ``path``.

    The writer is **deterministic** (sorted keys at every level,
    fixed two-space indent, trailing newline) and **only** writes the
    manifest JSON. No sidecar files, no logs, no metadata files, no
    network IO.

    Parent directories of ``path`` are created if necessary.

    Parameters
    ----------
    manifest
        :class:`ShadowDeploymentManifest` instance to serialise.
    path
        Caller-specified local path. Must be a string / PathLike.
        The file is overwritten if it exists.

    Returns
    -------
    pathlib.Path
        The resolved path that was written.

    Raises
    ------
    ValueError
        On a non-:class:`ShadowDeploymentManifest` ``manifest`` or a
        non-PathLike ``path``.
    OSError
        On filesystem errors.
    """
    if not isinstance(manifest, ShadowDeploymentManifest):
        raise ValueError(
            f"manifest must be a ShadowDeploymentManifest, got "
            f"{type(manifest).__name__}"
        )
    if isinstance(path, (str, os.PathLike)):
        out_path = Path(os.fspath(path))
    else:
        raise ValueError(
            f"path must be a string or PathLike, got {type(path).__name__}"
        )
    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = _manifest_to_dict(manifest)
    # ``sort_keys=True`` enforces stable key order, ``indent=2`` keeps
    # the output diff-friendly, trailing newline keeps the file POSIX-
    # textual.
    rendered = json.dumps(
        payload,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        separators=(",", ": "),
    )
    out_path.write_text(rendered + "\n", encoding="utf-8")
    return out_path


__all__ = [
    "ARTIFACT_KIND_ADVISORY_CONTRACT",
    "ARTIFACT_KIND_ADVISORY_DECISIONS",
    "ARTIFACT_KIND_BLOB",
    "ARTIFACT_KIND_DPL_LOSS_REPORT",
    "ARTIFACT_KIND_FILE",
    "ARTIFACT_KIND_SHADOW_REPLAY",
    "ARTIFACT_KIND_SHADOW_RUNTIME_REPORT",
    "DEFAULT_CREATED_AT",
    "SAFETY_BOUNDARY_PHRASES",
    "SHADOW_DEPLOYMENT_ARTIFACT_KINDS",
    "ShadowDeploymentArtifact",
    "ShadowDeploymentManifest",
    "ShadowDeploymentPackageDiagnostics",
    "UNKNOWN_VERSION_MARKER",
    "build_shadow_deployment_manifest",
    "write_shadow_deployment_manifest_json",
]
