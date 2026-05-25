"""Sprint 46 — AMAX-5580 feasibility evidence SDK projection.

Sprint 46 is an evidence and decision-gate sprint, not an Edge Runtime
implementation sprint. This module turns the AMAX-5580 datasheet facts
and the Sprint 45 SDK assumptions into deterministic, audit-only
*shapes* the product owner can pin a SKU / OS / runtime path to before
deeper Edge implementation begins.

The dataclasses below are stdlib-only frozen value records. They carry
no networking, no PLC/PAC client code, no live OT integration, no
model loading, and no HTTP / database / message-broker dependency.
The non-negotiable safety boundary remains explicit in every
canonical record:

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- the site PLC / pump-station PLC retains direct VFD / pump /
  actuator authority.

Public surface:

* :class:`AMAXSkuProfile` — frozen Advantech AMAX-5580 CPU / RAM SKU
  evidence record. Canonical helper :func:`canonical_amax_sku_profiles`
  enumerates the Celeron 3955U 4 GB constrained-fallback profile and
  the Core i5-6300U 8 GB / Core i7-6600U 8 GB serious-candidate
  profiles.
* :class:`AMAXRuntimeOption` — frozen OS / CODESYS runtime / ML
  packaging evidence record. Canonical helper
  :func:`canonical_amax_runtime_options` enumerates the Linux
  AdvLinuxTU + CODESYS Linux Control and Windows 10 LTSC 2019 +
  CODESYS Control RTE options.
* :class:`AMAXFeasibilityDecision` — frozen recommendation record
  carrying the recommended SKU profile id, OS / runtime
  recommendation, packaging strategy, ML runtime recommendation,
  evidence gaps still surrogate until real AMAX hardware testing, and
  the next gate. Canonical helper
  :func:`default_amax_feasibility_decision` returns the Sprint 46
  recommended decision.
* :func:`recommended_amax_hardware_profile` — bridge to the Sprint 45
  :func:`amax_5580_cpu_profile` helper that enriches the audit-only
  notes with Sprint 46 evidence-gap language without breaking the
  Sprint 45 default profile contract.

All ``to_dict`` / ``from_dict`` round trips are deterministic; tuple
ordering is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..safety.vocabulary import FORBIDDEN_VOCABULARY, contains_forbidden_token
from .hardware_profile import (
    AMAX_5580_PROFILE_ID,
    EdgeHardwareProfile,
    amax_5580_cpu_profile,
)


# ---------------------------------------------------------------------------
# Canonical vocabularies
# ---------------------------------------------------------------------------


# Recommendation tiers for AMAX SKU profiles. ``constrained_fallback``
# is the Celeron 3955U / 4 GB SKU — kept as evidence but not the Sprint
# 46 primary target. ``serious_candidate`` covers the Core i5-6300U /
# 8 GB and Core i7-6600U / 8 GB SKUs that the feasibility decision
# recommends for Sprint 47 CPU inference benchmarking.
AMAX_SKU_RECOMMENDATION_TIERS: frozenset[str] = frozenset(
    {
        "constrained_fallback",
        "serious_candidate",
        "recommended_candidate",
    }
)


# OS families recognised by the Sprint 46 feasibility module.
# ``linux_advlinuxtu_ubuntu18`` is Advantech's Ubuntu 18 based real-
# time Linux distribution; ``windows10_ltsc_2019`` is the Windows
# build supported by CODESYS Control RTE V3.5 SP20.
AMAX_OS_FAMILIES: frozenset[str] = frozenset(
    {
        "linux_advlinuxtu_ubuntu18",
        "windows10_ltsc_2019",
    }
)


# CODESYS runtime identifiers. ``none`` is reserved for an option
# that intentionally runs the AquaOptima ML sidecar outside the
# CODESYS runtime to keep packaging risk low.
AMAX_CODESYS_RUNTIMES: frozenset[str] = frozenset(
    {
        "codesys_control_rte_v3_5_sp20",
        "codesys_linux_control_v3_sp20",
        "none",
    }
)


# Python packaging risk levels for the OS / runtime evidence record.
AMAX_PACKAGING_RISK_LEVELS: frozenset[str] = frozenset(
    {"low", "moderate", "high"},
)


# ML runtime options the feasibility note compares. The Sprint 47
# benchmarking harness will measure CPU inference latency / memory /
# thread policy for the chosen option; the canonical recommendation
# is ``pytorch_cpu`` first, then ``onnx_runtime_cpu`` and
# ``openvino`` as benchmarking follow-ups.
AMAX_ML_RUNTIME_OPTIONS: frozenset[str] = frozenset(
    {
        "pytorch_cpu",
        "onnx_runtime_cpu",
        "openvino",
        "container_sidecar",
        "service_sidecar_outside_codesys",
    }
)


_SKU_FIELDS: tuple[str, ...] = (
    "sku_id",
    "sku_name",
    "cpu_family",
    "cpu_model",
    "cpu_clock_ghz",
    "cpu_cores",
    "ram_gb",
    "recommendation_tier",
    "notes",
)


_RUNTIME_FIELDS: tuple[str, ...] = (
    "option_id",
    "os_family",
    "codesys_runtime",
    "python_packaging_risk",
    "ml_runtime_option",
    "integration_notes",
    "recommendation",
)


_DECISION_FIELDS: tuple[str, ...] = (
    "recommended_sku_profile_id",
    "os_runtime_recommendation",
    "packaging_strategy",
    "ml_runtime_recommendation",
    "evidence_gaps",
    "next_gate",
    "notes",
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


def _coerce_sequence(data: Mapping[str, Any], name: str, *, label: str) -> tuple[str, ...]:
    raw = data.get(name, ()) or ()
    if isinstance(raw, (str, bytes)):
        raise ContractError(
            f"{label}.{name} must be a sequence of strings, got a bare string"
        )
    if not isinstance(raw, Sequence):
        raise ContractError(
            f"{label}.{name} must be a sequence"
        )
    return tuple(str(item) for item in raw)


def _reject_forbidden_keys(data: Mapping[str, Any], *, label: str) -> None:
    forbidden_hits = set(data.keys()) & FORBIDDEN_VOCABULARY
    if forbidden_hits:
        raise ContractError(
            f"{label} received forbidden vocabulary field name(s): "
            f"{sorted(forbidden_hits)}"
        )


# ---------------------------------------------------------------------------
# AMAXSkuProfile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AMAXSkuProfile:
    """Frozen AMAX-5580 CPU / RAM SKU evidence record.

    Audit-only. Captures the Advantech datasheet SKU evidence that
    informs the Sprint 46 feasibility decision. Nothing in this record
    represents a write, dispatch, actuation, setpoint, or control
    surface.
    """

    sku_id: str
    sku_name: str
    cpu_family: str
    cpu_model: str
    cpu_clock_ghz: float
    cpu_cores: int
    ram_gb: int
    recommendation_tier: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(self.sku_id, label="AMAXSkuProfile.sku_id")
        _ensure_str(self.sku_name, label="AMAXSkuProfile.sku_name")
        _ensure_str(self.cpu_family, label="AMAXSkuProfile.cpu_family")
        _ensure_str(self.cpu_model, label="AMAXSkuProfile.cpu_model")
        if not isinstance(self.cpu_clock_ghz, (int, float)) or isinstance(
            self.cpu_clock_ghz, bool
        ):
            raise ContractError(
                "AMAXSkuProfile.cpu_clock_ghz must be a real number"
            )
        if self.cpu_clock_ghz <= 0:
            raise ContractError(
                "AMAXSkuProfile.cpu_clock_ghz must be positive"
            )
        if not isinstance(self.cpu_cores, int) or isinstance(
            self.cpu_cores, bool
        ):
            raise ContractError(
                "AMAXSkuProfile.cpu_cores must be an int"
            )
        if self.cpu_cores <= 0:
            raise ContractError(
                "AMAXSkuProfile.cpu_cores must be positive"
            )
        if not isinstance(self.ram_gb, int) or isinstance(self.ram_gb, bool):
            raise ContractError(
                "AMAXSkuProfile.ram_gb must be an int"
            )
        if self.ram_gb <= 0:
            raise ContractError(
                "AMAXSkuProfile.ram_gb must be positive"
            )
        _ensure_str(
            self.recommendation_tier,
            label="AMAXSkuProfile.recommendation_tier",
        )
        if self.recommendation_tier not in AMAX_SKU_RECOMMENDATION_TIERS:
            raise ContractError(
                f"AMAXSkuProfile.recommendation_tier "
                f"{self.recommendation_tier!r} is not in the allowed list "
                f"({sorted(AMAX_SKU_RECOMMENDATION_TIERS)})"
            )
        notes = _ensure_str_tuple(self.notes, label="AMAXSkuProfile.notes")
        object.__setattr__(self, "notes", notes)
        object.__setattr__(self, "cpu_clock_ghz", float(self.cpu_clock_ghz))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku_id": self.sku_id,
            "sku_name": self.sku_name,
            "cpu_family": self.cpu_family,
            "cpu_model": self.cpu_model,
            "cpu_clock_ghz": self.cpu_clock_ghz,
            "cpu_cores": self.cpu_cores,
            "ram_gb": self.ram_gb,
            "recommendation_tier": self.recommendation_tier,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXSkuProfile":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXSkuProfile.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="AMAXSkuProfile")
        missing = {
            "sku_id",
            "sku_name",
            "cpu_family",
            "cpu_model",
            "cpu_clock_ghz",
            "cpu_cores",
            "ram_gb",
            "recommendation_tier",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXSkuProfile missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_SKU_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXSkuProfile received unknown fields: {sorted(unknown)}"
            )
        return cls(
            sku_id=str(data["sku_id"]),
            sku_name=str(data["sku_name"]),
            cpu_family=str(data["cpu_family"]),
            cpu_model=str(data["cpu_model"]),
            cpu_clock_ghz=float(data["cpu_clock_ghz"]),
            cpu_cores=int(data["cpu_cores"]),
            ram_gb=int(data["ram_gb"]),
            recommendation_tier=str(data["recommendation_tier"]),
            notes=_coerce_sequence(data, "notes", label="AMAXSkuProfile"),
        )


# ---------------------------------------------------------------------------
# AMAXRuntimeOption
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AMAXRuntimeOption:
    """Frozen OS / CODESYS / ML packaging evidence record.

    Audit-only. Captures how a given AMAX-5580 OS + CODESYS runtime
    combination scores against the Sprint 46 packaging risk model and
    which ML runtime option the feasibility note recommends pairing
    with it. Nothing in this record represents a write, dispatch,
    actuation, setpoint, or control surface.
    """

    option_id: str
    os_family: str
    codesys_runtime: str
    python_packaging_risk: str
    ml_runtime_option: str
    integration_notes: tuple[str, ...] = ()
    recommendation: str = ""

    def __post_init__(self) -> None:
        _ensure_str(self.option_id, label="AMAXRuntimeOption.option_id")
        _ensure_str(self.os_family, label="AMAXRuntimeOption.os_family")
        if self.os_family not in AMAX_OS_FAMILIES:
            raise ContractError(
                f"AMAXRuntimeOption.os_family {self.os_family!r} is not in "
                f"the allowed list ({sorted(AMAX_OS_FAMILIES)})"
            )
        _ensure_str(
            self.codesys_runtime, label="AMAXRuntimeOption.codesys_runtime"
        )
        if self.codesys_runtime not in AMAX_CODESYS_RUNTIMES:
            raise ContractError(
                f"AMAXRuntimeOption.codesys_runtime "
                f"{self.codesys_runtime!r} is not in the allowed list "
                f"({sorted(AMAX_CODESYS_RUNTIMES)})"
            )
        _ensure_str(
            self.python_packaging_risk,
            label="AMAXRuntimeOption.python_packaging_risk",
        )
        if self.python_packaging_risk not in AMAX_PACKAGING_RISK_LEVELS:
            raise ContractError(
                f"AMAXRuntimeOption.python_packaging_risk "
                f"{self.python_packaging_risk!r} is not in the allowed "
                f"list ({sorted(AMAX_PACKAGING_RISK_LEVELS)})"
            )
        _ensure_str(
            self.ml_runtime_option,
            label="AMAXRuntimeOption.ml_runtime_option",
        )
        if self.ml_runtime_option not in AMAX_ML_RUNTIME_OPTIONS:
            raise ContractError(
                f"AMAXRuntimeOption.ml_runtime_option "
                f"{self.ml_runtime_option!r} is not in the allowed list "
                f"({sorted(AMAX_ML_RUNTIME_OPTIONS)})"
            )
        integration_notes = _ensure_str_tuple(
            self.integration_notes,
            label="AMAXRuntimeOption.integration_notes",
        )
        if not isinstance(self.recommendation, str):
            raise ContractError(
                "AMAXRuntimeOption.recommendation must be a string"
            )
        hits = contains_forbidden_token(self.recommendation)
        if hits:
            raise ContractError(
                f"AMAXRuntimeOption.recommendation contains forbidden "
                f"vocabulary token(s) {sorted(hits)}"
            )
        object.__setattr__(self, "integration_notes", integration_notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "os_family": self.os_family,
            "codesys_runtime": self.codesys_runtime,
            "python_packaging_risk": self.python_packaging_risk,
            "ml_runtime_option": self.ml_runtime_option,
            "integration_notes": list(self.integration_notes),
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXRuntimeOption":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXRuntimeOption.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="AMAXRuntimeOption")
        missing = {
            "option_id",
            "os_family",
            "codesys_runtime",
            "python_packaging_risk",
            "ml_runtime_option",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXRuntimeOption missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_RUNTIME_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXRuntimeOption received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            option_id=str(data["option_id"]),
            os_family=str(data["os_family"]),
            codesys_runtime=str(data["codesys_runtime"]),
            python_packaging_risk=str(data["python_packaging_risk"]),
            ml_runtime_option=str(data["ml_runtime_option"]),
            integration_notes=_coerce_sequence(
                data, "integration_notes", label="AMAXRuntimeOption"
            ),
            recommendation=str(data.get("recommendation", "")),
        )


# ---------------------------------------------------------------------------
# AMAXFeasibilityDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AMAXFeasibilityDecision:
    """Frozen Sprint 46 feasibility decision record.

    Audit-only. Carries the recommended AMAX-5580 SKU profile id, the
    OS / CODESYS runtime recommendation, the packaging strategy, the
    ML runtime recommendation, the evidence gaps that remain
    surrogate until real AMAX hardware is tested, and the next gate.
    Nothing in this record represents a write, dispatch, actuation,
    setpoint, or control surface.
    """

    recommended_sku_profile_id: str
    os_runtime_recommendation: str
    packaging_strategy: str
    ml_runtime_recommendation: str
    evidence_gaps: tuple[str, ...] = ()
    next_gate: str = ""
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.recommended_sku_profile_id,
            label="AMAXFeasibilityDecision.recommended_sku_profile_id",
        )
        _ensure_str(
            self.os_runtime_recommendation,
            label="AMAXFeasibilityDecision.os_runtime_recommendation",
        )
        _ensure_str(
            self.packaging_strategy,
            label="AMAXFeasibilityDecision.packaging_strategy",
        )
        _ensure_str(
            self.ml_runtime_recommendation,
            label="AMAXFeasibilityDecision.ml_runtime_recommendation",
        )
        evidence_gaps = _ensure_str_tuple(
            self.evidence_gaps,
            label="AMAXFeasibilityDecision.evidence_gaps",
        )
        if not isinstance(self.next_gate, str):
            raise ContractError(
                "AMAXFeasibilityDecision.next_gate must be a string"
            )
        hits = contains_forbidden_token(self.next_gate)
        if hits:
            raise ContractError(
                f"AMAXFeasibilityDecision.next_gate contains forbidden "
                f"vocabulary token(s) {sorted(hits)}"
            )
        notes = _ensure_str_tuple(
            self.notes, label="AMAXFeasibilityDecision.notes"
        )
        object.__setattr__(self, "evidence_gaps", evidence_gaps)
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_sku_profile_id": self.recommended_sku_profile_id,
            "os_runtime_recommendation": self.os_runtime_recommendation,
            "packaging_strategy": self.packaging_strategy,
            "ml_runtime_recommendation": self.ml_runtime_recommendation,
            "evidence_gaps": list(self.evidence_gaps),
            "next_gate": self.next_gate,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "AMAXFeasibilityDecision":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXFeasibilityDecision.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="AMAXFeasibilityDecision")
        missing = {
            "recommended_sku_profile_id",
            "os_runtime_recommendation",
            "packaging_strategy",
            "ml_runtime_recommendation",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXFeasibilityDecision missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_DECISION_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXFeasibilityDecision received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            recommended_sku_profile_id=str(data["recommended_sku_profile_id"]),
            os_runtime_recommendation=str(data["os_runtime_recommendation"]),
            packaging_strategy=str(data["packaging_strategy"]),
            ml_runtime_recommendation=str(data["ml_runtime_recommendation"]),
            evidence_gaps=_coerce_sequence(
                data, "evidence_gaps", label="AMAXFeasibilityDecision"
            ),
            next_gate=str(data.get("next_gate", "")),
            notes=_coerce_sequence(
                data, "notes", label="AMAXFeasibilityDecision"
            ),
        )


# ---------------------------------------------------------------------------
# Canonical Sprint 46 evidence
# ---------------------------------------------------------------------------


# Canonical AMAX SKU profile identifiers. Adding additional canonical
# SKU ids is an SDK MINOR bump; repurposing or removing is MAJOR.
AMAX_SKU_CELERON_3955U_4GB: str = "advantech_amax_5580_celeron_3955u_4gb"
AMAX_SKU_CORE_I5_6300U_8GB: str = "advantech_amax_5580_core_i5_6300u_8gb"
AMAX_SKU_CORE_I7_6600U_8GB: str = "advantech_amax_5580_core_i7_6600u_8gb"


# Canonical AMAX runtime option identifiers.
AMAX_RUNTIME_LINUX_CODESYS: str = (
    "advlinuxtu_ubuntu18_codesys_linux_control_v3_sp20_pytorch_cpu"
)
AMAX_RUNTIME_WINDOWS_CODESYS: str = (
    "windows10_ltsc_2019_codesys_control_rte_v3_5_sp20_pytorch_cpu"
)
AMAX_RUNTIME_LINUX_CONTAINER_SIDECAR: str = (
    "advlinuxtu_ubuntu18_container_sidecar_pytorch_cpu"
)


def canonical_amax_sku_profiles() -> tuple[AMAXSkuProfile, ...]:
    """Return the canonical Sprint 46 AMAX-5580 SKU evidence tuple.

    Tuple order is stable: Celeron 3955U / 4 GB constrained fallback
    first, Core i5-6300U / 8 GB serious candidate second, Core
    i7-6600U / 8 GB recommended candidate third. Every record carries
    audit-only notes that reaffirm the non-negotiable safety
    boundary: no live OT binding, no PLC/PAC/SCADA write, no command
    emission, no setpoint output.
    """
    return (
        AMAXSkuProfile(
            sku_id=AMAX_SKU_CELERON_3955U_4GB,
            sku_name="AMAX-5580 Celeron 3955U 4 GB",
            cpu_family="intel_celeron",
            cpu_model="celeron_3955u",
            cpu_clock_ghz=2.0,
            cpu_cores=2,
            ram_gb=4,
            recommendation_tier="constrained_fallback",
            notes=(
                "Celeron 3955U dual core at 2.0 GHz with 4 GB RAM",
                "constrained fallback only — not the Sprint 46 primary target",
                "PyTorch CPU inference headroom marginal at 4 GB RAM",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
        AMAXSkuProfile(
            sku_id=AMAX_SKU_CORE_I5_6300U_8GB,
            sku_name="AMAX-5580 Core i5-6300U 8 GB",
            cpu_family="intel_core",
            cpu_model="core_i5_6300u",
            cpu_clock_ghz=2.4,
            cpu_cores=2,
            ram_gb=8,
            recommendation_tier="serious_candidate",
            notes=(
                "Core i5-6300U dual core at 2.4 GHz with 8 GB RAM",
                "serious candidate for dPHM-PINN Edge evaluation",
                "8 GB RAM provides PyTorch CPU inference headroom",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
        AMAXSkuProfile(
            sku_id=AMAX_SKU_CORE_I7_6600U_8GB,
            sku_name="AMAX-5580 Core i7-6600U 8 GB",
            cpu_family="intel_core",
            cpu_model="core_i7_6600u",
            cpu_clock_ghz=2.6,
            cpu_cores=2,
            ram_gb=8,
            recommendation_tier="recommended_candidate",
            notes=(
                "Core i7-6600U dual core at 2.6 GHz with 8 GB RAM",
                "recommended candidate for Sprint 47 CPU inference benchmarking",
                "highest clock among AMAX-5580 SKUs in scope",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
    )


def canonical_amax_runtime_options() -> tuple[AMAXRuntimeOption, ...]:
    """Return the canonical Sprint 46 AMAX runtime evidence tuple.

    Tuple order is stable: Linux AdvLinuxTU + CODESYS Linux Control
    first (Ubuntu 18 base — moderate Python packaging risk for
    >= 3.10), Windows 10 LTSC 2019 + CODESYS Control RTE next
    (site-friendly but Python / ML packaging less mature on
    Windows), Linux container sidecar third (lowest packaging risk
    once container infrastructure is available).
    """
    return (
        AMAXRuntimeOption(
            option_id=AMAX_RUNTIME_LINUX_CODESYS,
            os_family="linux_advlinuxtu_ubuntu18",
            codesys_runtime="codesys_linux_control_v3_sp20",
            python_packaging_risk="moderate",
            ml_runtime_option="pytorch_cpu",
            integration_notes=(
                "AdvLinuxTU v2.0.5.4 64-bit Ubuntu 18 base",
                "Python >= 3.10 wheels limited on Ubuntu 18 — pyenv or vendored interpreter likely required",
                "modern PyTorch CPU wheels target glibc newer than Ubuntu 18 default — verify on real AMAX hardware",
                "OPC UA Server / Modbus TCP / EtherCAT MainDevice available via CODESYS Linux Control packages",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
            recommendation=(
                "primary feasibility candidate; benchmark CPU inference on i5/i7 8 GB SKU in Sprint 47"
            ),
        ),
        AMAXRuntimeOption(
            option_id=AMAX_RUNTIME_WINDOWS_CODESYS,
            os_family="windows10_ltsc_2019",
            codesys_runtime="codesys_control_rte_v3_5_sp20",
            python_packaging_risk="moderate",
            ml_runtime_option="pytorch_cpu",
            integration_notes=(
                "Windows 10 LTSC 2019 64-bit with CODESYS Control RTE V3.5 SP20",
                "site-friendly when CODESYS Windows runtime is already standardised",
                "Python / PyTorch / ML packaging on Windows is less mature than Linux — verify wheels and venv layout",
                "MQTT / Sparkplug and ODBC packages available via Advantech CODESYS bundle",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
            recommendation=(
                "viable when site explicitly requires Windows CODESYS; otherwise prefer Linux path"
            ),
        ),
        AMAXRuntimeOption(
            option_id=AMAX_RUNTIME_LINUX_CONTAINER_SIDECAR,
            os_family="linux_advlinuxtu_ubuntu18",
            codesys_runtime="none",
            python_packaging_risk="low",
            ml_runtime_option="container_sidecar",
            integration_notes=(
                "AdvLinuxTU host runs CODESYS; AquaOptima ML sidecar runs in a container",
                "decouples Python / PyTorch packaging from the host glibc and OS image",
                "container sidecar exchanges audit-only telemetry with the CODESYS runtime; no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
            recommendation=(
                "low-risk packaging fallback when direct host install is blocked"
            ),
        ),
    )


def default_amax_feasibility_decision() -> AMAXFeasibilityDecision:
    """Return the Sprint 46 recommended AMAX feasibility decision.

    The recommendation is the Core i5-6300U or Core i7-6600U 8 GB
    AMAX-5580 SKU, AdvLinuxTU v2.0.5.4 (Ubuntu 18 based) with
    CODESYS Linux Control V3 SP20, direct PyTorch CPU packaging as
    the Sprint 47 benchmark baseline (with ONNX Runtime CPU and
    OpenVINO queued as follow-ups), and a Windows + CODESYS Control
    RTE V3.5 SP20 fallback only when site requirements demand it.

    The evidence remains surrogate until real AMAX-5580 hardware is
    tested — the ``evidence_gaps`` tuple records that explicitly. The
    canonical record also reaffirms the non-negotiable safety
    boundary: no live OT binding, no PLC/PAC/SCADA write, no command
    emission, no setpoint output.
    """
    return AMAXFeasibilityDecision(
        recommended_sku_profile_id=AMAX_SKU_CORE_I5_6300U_8GB,
        os_runtime_recommendation=(
            "advantech-amax-5580-i5-or-i7-8gb-linux-codesys-cpu-first"
        ),
        packaging_strategy=(
            "direct pytorch cpu install on AdvLinuxTU; container sidecar as low-risk fallback"
        ),
        ml_runtime_recommendation=(
            "pytorch_cpu first; onnx_runtime_cpu and openvino queued for Sprint 47 benchmarking"
        ),
        evidence_gaps=(
            "surrogate evidence only until real AMAX-5580 hardware is in hand",
            "Python >= 3.10 wheel availability on Ubuntu 18 not yet verified on AdvLinuxTU",
            "modern PyTorch CPU wheel glibc requirement not yet verified on AdvLinuxTU",
            "CPU inference latency / memory / thread policy not yet measured on real AMAX hardware",
            "CODESYS Linux Control V3 SP20 co-tenancy with PyTorch process not yet observed",
            "site-specific OT integration posture (OPC UA vs Modbus vs shared memory) still open",
        ),
        next_gate=(
            "Sprint 47 CPU inference benchmark and packaging smoke harness only after Sprint 46 evidence is accepted"
        ),
        notes=(
            "primary AMAX feasibility recommendation",
            "site PLC retains direct VFD / pump / actuator authority",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "no control-loop closure",
        ),
    )


def recommended_amax_hardware_profile() -> EdgeHardwareProfile:
    """Bridge the Sprint 46 feasibility decision to a Sprint 45 profile.

    Returns an :class:`EdgeHardwareProfile` whose identifier matches the
    canonical Sprint 45 :func:`amax_5580_cpu_profile` and whose
    ``notes`` are enriched with the Sprint 46 evidence-gap language.
    The bridge does **not** change the Sprint 45 default profile
    contract; calling :func:`amax_5580_cpu_profile` keeps returning
    the original Sprint 45 value. Downstream code that wants the
    Sprint 46 evidence-aware variant calls this helper explicitly.
    """
    base = amax_5580_cpu_profile()
    enriched_notes = base.notes + (
        "Sprint 46 feasibility evidence profile (surrogate)",
        "recommended SKU tier: serious_candidate or recommended_candidate (i5/i7 8 GB)",
        "evidence gap: real AMAX hardware testing pending",
    )
    return EdgeHardwareProfile(
        profile_id=base.profile_id,
        vendor=base.vendor,
        model=base.model,
        architecture=base.architecture,
        os_family=base.os_family,
        runtime_class=base.runtime_class,
        accelerators=base.accelerators,
        supported_model_frameworks=base.supported_model_frameworks,
        python_versions=base.python_versions,
        notes=enriched_notes,
    )


__all__ = [
    "AMAXFeasibilityDecision",
    "AMAXRuntimeOption",
    "AMAXSkuProfile",
    "AMAX_CODESYS_RUNTIMES",
    "AMAX_ML_RUNTIME_OPTIONS",
    "AMAX_OS_FAMILIES",
    "AMAX_PACKAGING_RISK_LEVELS",
    "AMAX_RUNTIME_LINUX_CODESYS",
    "AMAX_RUNTIME_LINUX_CONTAINER_SIDECAR",
    "AMAX_RUNTIME_WINDOWS_CODESYS",
    "AMAX_SKU_CELERON_3955U_4GB",
    "AMAX_SKU_CORE_I5_6300U_8GB",
    "AMAX_SKU_CORE_I7_6600U_8GB",
    "AMAX_SKU_RECOMMENDATION_TIERS",
    "canonical_amax_runtime_options",
    "canonical_amax_sku_profiles",
    "default_amax_feasibility_decision",
    "recommended_amax_hardware_profile",
]


# AMAX_5580_PROFILE_ID is re-exported for convenience: callers that
# only import from this module can reach the canonical Sprint 45
# profile identifier without a second import path.
_ = AMAX_5580_PROFILE_ID
