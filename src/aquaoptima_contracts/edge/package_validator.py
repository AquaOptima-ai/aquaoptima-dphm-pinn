"""``EdgePackageValidationResult`` + ``validate_deployment_package_for_edge``.

Pure value function that consumes a Sprint 44
:class:`DeploymentPackageManifest` and a Sprint 45
:class:`EdgeCapabilityDeclaration` and returns a deterministic
:class:`EdgePackageValidationResult`. Default AMAX rejection covers
CUDA / TensorRT / Jetson / Orin / ARM64 acceleration, runtime model
loading via unsupported frameworks, and any package whose capability
requirements are not satisfied by the Edge declaration.

The non-negotiable boundary is enforced upstream by the package
contract (:mod:`aquaoptima_contracts.package`) and the canonical
denylist (:mod:`aquaoptima_contracts.safety.vocabulary`): no live OT
binding, no PLC/PAC/SCADA write, no command emission, no setpoint
output, and no control-loop closure can appear in a manifest at all.
This validator additionally refuses default-edge packages that imply
accelerator dependencies the AMAX profile does not advertise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..base.envelope import ContractError
from ..package.package_manifest import (
    ArtifactManifest,
    ArtifactBundleRecord,
    DeploymentPackageManifest,
    ModelArtifactRecord,
)
from ..safety.capability_gates import (
    CapabilityRequirement,
    evaluate_capability_gate,
)
from .capability_declaration import EdgeCapabilityDeclaration
from .hardware_profile import EDGE_REJECTED_ACCELERATOR_TOKENS


_RESULT_FIELDS: tuple[str, ...] = (
    "accepted",
    "errors",
    "warnings",
    "profile_id",
    "package_id",
    "missing_capabilities",
    "rejected_accelerator_tokens",
    "rejected_frameworks",
)


# ---------------------------------------------------------------------------
# EdgePackageValidationResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgePackageValidationResult:
    """Deterministic accept / errors / warnings bundle.

    The validator records the canonical evidence it considered:
    ``profile_id`` (the Edge profile evaluated), ``package_id`` (the
    manifest evaluated), ``missing_capabilities`` (output of the
    capability gate), ``rejected_accelerator_tokens`` (which AMAX
    rejection substrings were found in the manifest), and
    ``rejected_frameworks`` (any model framework outside the Edge
    profile's supported list).
    """

    accepted: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    profile_id: str | None = None
    package_id: str | None = None
    missing_capabilities: tuple[str, ...] = ()
    rejected_accelerator_tokens: tuple[str, ...] = ()
    rejected_frameworks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise ContractError(
                "EdgePackageValidationResult.accepted must be a bool"
            )
        for name in (
            "errors",
            "warnings",
            "missing_capabilities",
            "rejected_accelerator_tokens",
            "rejected_frameworks",
        ):
            value = getattr(self, name)
            if isinstance(value, (str, bytes)) or not isinstance(value, tuple):
                raise ContractError(
                    f"EdgePackageValidationResult.{name} must be a tuple"
                )
            for entry in value:
                if not isinstance(entry, str):
                    raise ContractError(
                        f"EdgePackageValidationResult.{name} entries must "
                        f"be strings"
                    )
        for name in ("profile_id", "package_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ContractError(
                    f"EdgePackageValidationResult.{name}, when set, must be "
                    f"a non-empty string"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "profile_id": self.profile_id,
            "package_id": self.package_id,
            "missing_capabilities": list(self.missing_capabilities),
            "rejected_accelerator_tokens": list(
                self.rejected_accelerator_tokens
            ),
            "rejected_frameworks": list(self.rejected_frameworks),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "EdgePackageValidationResult":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"EdgePackageValidationResult.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_RESULT_FIELDS)
        if unknown:
            raise ContractError(
                f"EdgePackageValidationResult received unknown fields: "
                f"{sorted(unknown)}"
            )
        if "accepted" not in data:
            raise ContractError(
                "EdgePackageValidationResult missing required field 'accepted'"
            )

        def _coerce_seq(name: str) -> tuple[str, ...]:
            raw = data.get(name, ()) or ()
            if isinstance(raw, (str, bytes)):
                raise ContractError(
                    f"EdgePackageValidationResult.{name} must be a sequence"
                )
            if not isinstance(raw, Sequence):
                raise ContractError(
                    f"EdgePackageValidationResult.{name} must be a sequence"
                )
            return tuple(str(item) for item in raw)

        profile_id_raw = data.get("profile_id")
        package_id_raw = data.get("package_id")
        return cls(
            accepted=bool(data["accepted"]),
            errors=_coerce_seq("errors"),
            warnings=_coerce_seq("warnings"),
            profile_id=(
                str(profile_id_raw) if profile_id_raw is not None else None
            ),
            package_id=(
                str(package_id_raw) if package_id_raw is not None else None
            ),
            missing_capabilities=_coerce_seq("missing_capabilities"),
            rejected_accelerator_tokens=_coerce_seq(
                "rejected_accelerator_tokens"
            ),
            rejected_frameworks=_coerce_seq("rejected_frameworks"),
        )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def _scanned_text_blocks(
    manifest: DeploymentPackageManifest,
) -> Iterable[tuple[str, str]]:
    """Yield ``(source_label, text)`` pairs the validator scans for the
    AMAX accelerator-token denylist.

    Includes manifest- / declaration-level notes, every artifact's
    description and stringified summary values, every model artifact's
    description and stringified summary values, and every bundle's
    description and nested artifact descriptions.
    """
    if manifest.notes:
        yield "manifest.notes", manifest.notes
    if manifest.safety_declaration.notes:
        yield (
            "safety_declaration.notes",
            manifest.safety_declaration.notes,
        )

    def _walk_summary(label: str, summary: Mapping[str, Any]) -> Iterable[
        tuple[str, str]
    ]:
        for key, value in summary.items():
            if isinstance(value, str):
                yield f"{label}[{key!r}]", value
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    if isinstance(item, str):
                        yield f"{label}[{key!r}][{index}]", item

    def _walk_artifact(label: str, art: ArtifactManifest) -> Iterable[
        tuple[str, str]
    ]:
        if art.description:
            yield f"{label}.description", art.description
        yield from _walk_summary(f"{label}.summary", art.summary)

    def _walk_model_record(
        label: str, record: ModelArtifactRecord
    ) -> Iterable[tuple[str, str]]:
        if record.description:
            yield f"{label}.description", record.description
        yield from _walk_summary(f"{label}.summary", record.summary)

    def _walk_bundle(
        label: str, bundle: ArtifactBundleRecord
    ) -> Iterable[tuple[str, str]]:
        if bundle.description:
            yield f"{label}.description", bundle.description
        for index, art in enumerate(bundle.artifacts):
            yield from _walk_artifact(f"{label}.artifacts[{index}]", art)

    for index, art in enumerate(manifest.artifacts):
        yield from _walk_artifact(f"artifacts[{index}]", art)
    for index, record in enumerate(manifest.model_artifacts):
        yield from _walk_model_record(
            f"model_artifacts[{index}]", record
        )
    for index, bundle in enumerate(manifest.bundles):
        yield from _walk_bundle(f"bundles[{index}]", bundle)


def _scan_for_rejected_accelerator_tokens(
    manifest: DeploymentPackageManifest,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Scan manifest text blocks for the AMAX rejection denylist.

    Returns ``(sorted_unique_tokens, diagnostics)``.
    """
    hits: dict[str, list[str]] = {}
    for label, text in _scanned_text_blocks(manifest):
        lowered = text.lower()
        for token in EDGE_REJECTED_ACCELERATOR_TOKENS:
            if token in lowered:
                hits.setdefault(token, []).append(label)
    if not hits:
        return (), ()
    tokens = tuple(sorted(hits.keys()))
    diagnostics = tuple(
        f"manifest field {label!r} mentions rejected accelerator token "
        f"{token!r}"
        for token in tokens
        for label in sorted(hits[token])
    )
    return tokens, diagnostics


def _scan_for_rejected_model_frameworks(
    manifest: DeploymentPackageManifest,
    supported: frozenset[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return frameworks declared in model artifacts that the Edge
    profile does not advertise, plus diagnostic messages."""
    rejected: dict[str, list[str]] = {}
    for index, record in enumerate(manifest.model_artifacts):
        if record.framework not in supported:
            rejected.setdefault(record.framework, []).append(
                f"model_artifacts[{index}] ({record.model_id})"
            )
    if not rejected:
        return (), ()
    frameworks = tuple(sorted(rejected.keys()))
    diagnostics = tuple(
        f"{label} declares unsupported model framework {fw!r}"
        for fw in frameworks
        for label in sorted(rejected[fw])
    )
    return frameworks, diagnostics


def _scan_for_architecture_mismatch(
    manifest: DeploymentPackageManifest,
    edge_architecture: str,
) -> tuple[str, ...]:
    """Return diagnostics when any artifact summary advertises an
    architecture or accelerator token that the Edge profile does not
    advertise."""
    diagnostics: list[str] = []
    edge_arch_lower = edge_architecture.lower()
    architecture_keys = {"architecture", "arch", "target_arch"}

    def _walk(label: str, summary: Mapping[str, Any]) -> None:
        for key, value in summary.items():
            if key.lower() in architecture_keys and isinstance(value, str):
                if value.lower() != edge_arch_lower:
                    diagnostics.append(
                        f"{label}[{key!r}]={value!r} does not match edge "
                        f"architecture {edge_architecture!r}"
                    )

    for index, art in enumerate(manifest.artifacts):
        _walk(f"artifacts[{index}].summary", art.summary)
    for index, record in enumerate(manifest.model_artifacts):
        _walk(f"model_artifacts[{index}].summary", record.summary)
    return tuple(diagnostics)


def _combined_capability_requirement(
    manifest: DeploymentPackageManifest,
) -> CapabilityRequirement:
    """Merge manifest-level + model-artifact capability requirements
    into a single :class:`CapabilityRequirement` for gate evaluation.

    The merged ``package_id`` is the manifest's own; model-artifact
    requirements add capability tokens only.
    """
    required: set[str] = set(manifest.capability_requirement.required)
    for record in manifest.model_artifacts:
        required.update(record.capability_requirement.required)
    return CapabilityRequirement(
        package_id=manifest.package_id,
        required=frozenset(required),
        sdk_version=manifest.capability_requirement.sdk_version,
    )


def validate_deployment_package_for_edge(
    manifest: DeploymentPackageManifest,
    edge: EdgeCapabilityDeclaration,
) -> EdgePackageValidationResult:
    """Validate a Sprint 44 package against a Sprint 45 Edge declaration.

    Deny-by-default semantics:

    * the capability requirement (manifest- and model-artifact-level)
      is evaluated via :func:`evaluate_capability_gate`; any missing
      capability is an error;
    * any AMAX rejection substring (``cuda``, ``tensorrt``, ``jetson``,
      ``orin``, ``arm64``, ``aarch64``) found in a notes / description /
      summary field is an error, unless the Edge profile explicitly
      advertises that token as an accelerator;
    * any model artifact whose framework is not in the Edge profile's
      ``supported_model_frameworks`` is an error;
    * any artifact / model artifact summary advertising an
      architecture that does not match the Edge profile's architecture
      is an error.

    The non-negotiable safety boundary is upstream: the manifest
    contract already forbids live OT binding, PLC/PAC/SCADA write,
    command emission, setpoint output, and control-loop closure
    vocabulary anywhere in its fields. This validator only adds
    target-fit checks for the AMAX-5580 default profile and is pure
    value computation; no IO, no model loading, no live OT binding,
    no PLC/PAC/SCADA write, no command emission, no setpoint output,
    and no control-loop closure happens here.
    """
    if not isinstance(manifest, DeploymentPackageManifest):
        raise ContractError(
            "validate_deployment_package_for_edge requires a "
            "DeploymentPackageManifest"
        )
    if not isinstance(edge, EdgeCapabilityDeclaration):
        raise ContractError(
            "validate_deployment_package_for_edge requires an "
            "EdgeCapabilityDeclaration"
        )

    errors: list[str] = []
    warnings: list[str] = []

    # 1. Capability gate.
    merged_requirement = _combined_capability_requirement(manifest)
    gate = evaluate_capability_gate(
        edge.capability_declaration, merged_requirement
    )
    missing = tuple(sorted(gate.missing))
    if not gate.allowed:
        errors.append(
            f"capability gate denied: missing capability token(s) "
            f"{list(missing)}"
        )

    # 2. AMAX accelerator-token denylist.
    accelerator_allowlist = {
        a.lower() for a in edge.hardware_profile.accelerators
    }
    rejected_tokens, accel_diagnostics = (
        _scan_for_rejected_accelerator_tokens(manifest)
    )
    filtered_rejected_tokens = tuple(
        token for token in rejected_tokens
        if token not in accelerator_allowlist
    )
    for diagnostic in accel_diagnostics:
        # Diagnostic strings already embed the token name; we filter
        # using the same allowlist so accelerator-aware profiles that
        # legitimately advertise (say) ``tensorrt`` see warnings only.
        token_match = next(
            (
                token for token in EDGE_REJECTED_ACCELERATOR_TOKENS
                if f"{token!r}" in diagnostic
            ),
            None,
        )
        if token_match is None or token_match not in accelerator_allowlist:
            errors.append(diagnostic)
        else:
            warnings.append(diagnostic)

    # 3. Model framework support.
    supported_frameworks = frozenset(
        edge.hardware_profile.supported_model_frameworks
    )
    rejected_frameworks, framework_diagnostics = (
        _scan_for_rejected_model_frameworks(manifest, supported_frameworks)
    )
    errors.extend(framework_diagnostics)

    # 4. Architecture sanity.
    arch_diagnostics = _scan_for_architecture_mismatch(
        manifest, edge.hardware_profile.architecture
    )
    errors.extend(arch_diagnostics)

    accepted = not errors
    return EdgePackageValidationResult(
        accepted=accepted,
        errors=tuple(errors),
        warnings=tuple(warnings),
        profile_id=edge.hardware_profile.profile_id,
        package_id=manifest.package_id,
        missing_capabilities=missing,
        rejected_accelerator_tokens=filtered_rejected_tokens,
        rejected_frameworks=rejected_frameworks,
    )
