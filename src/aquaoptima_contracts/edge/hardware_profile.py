"""``EdgeHardwareProfile`` and the canonical AMAX-5580 helper.

Audit-only contract shape that describes what an Edge instance is
running on. Sprint 45 ships the canonical AMAX-5580 profile and the
``EDGE_REJECTED_ACCELERATOR_TOKENS`` denylist that the package
validator uses to refuse default-edge packages requiring CUDA,
TensorRT, Jetson, Orin, or ARM64 acceleration. Nothing in this
module performs hardware probing, model loading, or live OT
binding. The dataclass is a frozen value used by the deny-by-default
validator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..package.package_manifest import PACKAGE_MODEL_FRAMEWORKS
from ..safety.vocabulary import FORBIDDEN_VOCABULARY, contains_forbidden_token


# ---------------------------------------------------------------------------
# Canonical vocabularies
# ---------------------------------------------------------------------------


# Canonical AMAX profile identifier. Adding additional canonical
# profile IDs is an SDK MINOR bump; repurposing or removing is MAJOR.
AMAX_5580_PROFILE_ID: str = "advantech_amax_5580"


# Allowed runtime classes for an Edge profile. ``industrial_pac``
# covers the AMAX-5580 / PAC-class controllers. ``edge_x86_generic``
# covers other x86_64 industrial / supervisory CPUs.
EDGE_RUNTIME_CLASSES: frozenset[str] = frozenset(
    {
        "industrial_pac",
        "edge_x86_generic",
        "edge_gpu_optional",
    }
)


# Substring tokens the AMAX validator refuses by default. The
# validator scans architecture / accelerator / framework / description
# / summary fields for any of these and rejects the package. Adding
# tokens is an SDK MINOR bump; repurposing or removing is MAJOR.
EDGE_REJECTED_ACCELERATOR_TOKENS: tuple[str, ...] = (
    "aarch64",
    "arm64",
    "cuda",
    "jetson",
    "orin",
    "tensorrt",
)


_ALLOWED_OS_FAMILIES: frozenset[str] = frozenset(
    {"linux", "windows", "rt_linux"}
)


_ALLOWED_ARCHITECTURES: frozenset[str] = frozenset(
    {"x86_64", "aarch64", "arm64"}
)


_HARDWARE_FIELDS: tuple[str, ...] = (
    "profile_id",
    "vendor",
    "model",
    "architecture",
    "os_family",
    "runtime_class",
    "accelerators",
    "supported_model_frameworks",
    "python_versions",
    "notes",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ensure_str_field(value: Any, *, label: str) -> str:
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


# ---------------------------------------------------------------------------
# EdgeHardwareProfile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeHardwareProfile:
    """Frozen hardware / runtime capability metadata.

    Describes the architecture, OS family, runtime class, accelerators,
    supported model frameworks, and supported Python versions of an
    Edge target. The dataclass carries audit-only metadata; nothing in
    its fields represents a write, dispatch, actuation, setpoint, or
    control surface.
    """

    profile_id: str
    vendor: str
    model: str
    architecture: str
    os_family: str
    runtime_class: str
    accelerators: tuple[str, ...] = ()
    supported_model_frameworks: tuple[str, ...] = ()
    python_versions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str_field(self.profile_id, label="EdgeHardwareProfile.profile_id")
        _ensure_str_field(self.vendor, label="EdgeHardwareProfile.vendor")
        _ensure_str_field(self.model, label="EdgeHardwareProfile.model")
        _ensure_str_field(
            self.architecture, label="EdgeHardwareProfile.architecture"
        )
        if self.architecture not in _ALLOWED_ARCHITECTURES:
            raise ContractError(
                f"EdgeHardwareProfile.architecture {self.architecture!r} "
                f"is not in the allowed list "
                f"({sorted(_ALLOWED_ARCHITECTURES)})"
            )
        _ensure_str_field(self.os_family, label="EdgeHardwareProfile.os_family")
        if self.os_family not in _ALLOWED_OS_FAMILIES:
            raise ContractError(
                f"EdgeHardwareProfile.os_family {self.os_family!r} is not "
                f"in the allowed list ({sorted(_ALLOWED_OS_FAMILIES)})"
            )
        _ensure_str_field(
            self.runtime_class, label="EdgeHardwareProfile.runtime_class"
        )
        if self.runtime_class not in EDGE_RUNTIME_CLASSES:
            raise ContractError(
                f"EdgeHardwareProfile.runtime_class {self.runtime_class!r} "
                f"is not in the allowed list "
                f"({sorted(EDGE_RUNTIME_CLASSES)})"
            )
        accelerators = _ensure_str_tuple(
            self.accelerators, label="EdgeHardwareProfile.accelerators"
        )
        frameworks = _ensure_str_tuple(
            self.supported_model_frameworks,
            label="EdgeHardwareProfile.supported_model_frameworks",
        )
        for fw in frameworks:
            if fw not in PACKAGE_MODEL_FRAMEWORKS:
                raise ContractError(
                    f"EdgeHardwareProfile.supported_model_frameworks "
                    f"entry {fw!r} is not in the canonical "
                    f"PACKAGE_MODEL_FRAMEWORKS list "
                    f"({sorted(PACKAGE_MODEL_FRAMEWORKS)})"
                )
        python_versions = _ensure_str_tuple(
            self.python_versions,
            label="EdgeHardwareProfile.python_versions",
        )
        notes = _ensure_str_tuple(
            self.notes, label="EdgeHardwareProfile.notes"
        )
        object.__setattr__(self, "accelerators", accelerators)
        object.__setattr__(self, "supported_model_frameworks", frameworks)
        object.__setattr__(self, "python_versions", python_versions)
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "vendor": self.vendor,
            "model": self.model,
            "architecture": self.architecture,
            "os_family": self.os_family,
            "runtime_class": self.runtime_class,
            "accelerators": list(self.accelerators),
            "supported_model_frameworks": list(self.supported_model_frameworks),
            "python_versions": list(self.python_versions),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EdgeHardwareProfile":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"EdgeHardwareProfile.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        keys = set(data.keys())
        forbidden_hits = keys & FORBIDDEN_VOCABULARY
        if forbidden_hits:
            raise ContractError(
                f"EdgeHardwareProfile received forbidden vocabulary field "
                f"name(s): {sorted(forbidden_hits)}"
            )
        missing = {
            "profile_id",
            "vendor",
            "model",
            "architecture",
            "os_family",
            "runtime_class",
        } - keys
        if missing:
            raise ContractError(
                f"EdgeHardwareProfile missing fields: {sorted(missing)}"
            )
        unknown = keys - set(_HARDWARE_FIELDS)
        if unknown:
            raise ContractError(
                f"EdgeHardwareProfile received unknown fields: "
                f"{sorted(unknown)}"
            )

        def _coerce_sequence(name: str) -> tuple[str, ...]:
            raw = data.get(name, ()) or ()
            if isinstance(raw, (str, bytes)):
                raise ContractError(
                    f"EdgeHardwareProfile.{name} must be a sequence of strings"
                )
            if not isinstance(raw, Sequence):
                raise ContractError(
                    f"EdgeHardwareProfile.{name} must be a sequence"
                )
            return tuple(str(item) for item in raw)

        return cls(
            profile_id=str(data["profile_id"]),
            vendor=str(data["vendor"]),
            model=str(data["model"]),
            architecture=str(data["architecture"]),
            os_family=str(data["os_family"]),
            runtime_class=str(data["runtime_class"]),
            accelerators=_coerce_sequence("accelerators"),
            supported_model_frameworks=_coerce_sequence(
                "supported_model_frameworks"
            ),
            python_versions=_coerce_sequence("python_versions"),
            notes=_coerce_sequence("notes"),
        )


# ---------------------------------------------------------------------------
# Canonical AMAX-5580 helper
# ---------------------------------------------------------------------------


def amax_5580_cpu_profile() -> EdgeHardwareProfile:
    """Return the canonical AMAX-5580 CPU-first profile.

    The AMAX-5580 is an Advantech PAC-class x86_64 industrial
    controller. The default profile declares CPU-first PyTorch /
    ONNX / TFLite / audit-only frameworks and **no** CUDA / TensorRT /
    Jetson / Orin acceleration. The canonical profile must be safe to
    pass to :func:`validate_deployment_package_for_edge` for any
    default AMAX deployment.

    The audit-only notes record the non-negotiable boundary:
    no live OT binding, no PLC/PAC/SCADA write, no command emission,
    no setpoint output, and no control-loop closure from the Edge.
    The site PLC remains the direct VFD / pump / actuator authority.
    """
    return EdgeHardwareProfile(
        profile_id=AMAX_5580_PROFILE_ID,
        vendor="advantech",
        model="amax_5580",
        architecture="x86_64",
        os_family="linux",
        runtime_class="industrial_pac",
        accelerators=(),
        supported_model_frameworks=(
            "audit_only",
            "onnx",
            "pytorch",
            "tflite",
        ),
        python_versions=("3.10", "3.11"),
        notes=(
            "primary AMAX-5580 CPU-first profile",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "site PLC retains direct VFD / pump / actuator authority",
        ),
    )
