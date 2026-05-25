"""Edge package validation contracts (Sprint 45 + Sprint 46 feasibility).

Sprint 45 promotes the **Advantech AMAX-5580** (or equivalent x86_64
PAC-class industrial controller) to the primary Edge target. This
module owns the SDK *shapes* that describe what an Edge instance
declares it can do and the deny-by-default validator that consumes a
Sprint 44 :class:`DeploymentPackageManifest`:

* :class:`EdgeHardwareProfile` — frozen hardware / runtime capability
  metadata. Ships with a canonical AMAX-5580 helper
  (:func:`amax_5580_cpu_profile`).
* :class:`EdgeCapabilityDeclaration` — pairs a
  :class:`CapabilityDeclaration` with an
  :class:`EdgeHardwareProfile`. Ships with a canonical AMAX
  package-validation-only helper
  (:func:`default_amax_edge_capability_declaration`).
* :class:`EdgePackageValidationResult` — deterministic accept / errors
  / warnings result returned by the validator.
* :func:`validate_deployment_package_for_edge` — pure value function
  that consumes a :class:`DeploymentPackageManifest` plus an
  :class:`EdgeCapabilityDeclaration` and returns an
  :class:`EdgePackageValidationResult`.

Sprint 46 adds the AMAX feasibility evidence projection used by the
SKU / OS / runtime decision gate:

* :class:`AMAXSkuProfile` — frozen Advantech AMAX-5580 CPU / RAM SKU
  evidence record.
* :class:`AMAXRuntimeOption` — frozen OS / CODESYS / ML packaging
  evidence record.
* :class:`AMAXFeasibilityDecision` — frozen Sprint 46 recommendation
  record covering recommended SKU, OS / runtime path, packaging
  strategy, ML runtime, evidence gaps still surrogate until real AMAX
  hardware testing, and the next gate.
* :func:`canonical_amax_sku_profiles` /
  :func:`canonical_amax_runtime_options` /
  :func:`default_amax_feasibility_decision` /
  :func:`recommended_amax_hardware_profile` — canonical Sprint 46
  helpers.

The boundary is non-negotiable: no live OT binding, no PLC/PAC/SCADA
write, no command emission, no setpoint output, no control-loop
closure, no HTTP / database / message-broker dependency, no model
loading, no inline model weights, no Edge Runtime daemon code in
this module. Validation and feasibility evidence are pure value
computations over the SDK contract shapes.
"""

from .benchmark import (
    AMAX_BENCHMARK_CADENCE_BUCKETS,
    AMAX_BENCHMARK_FRAMEWORKS,
    AMAX_BENCHMARK_SCENARIO_BRANCH,
    AMAX_BENCHMARK_SCENARIO_PUMP,
    AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP,
    AMAXBenchmarkMetrics,
    AMAXBenchmarkReport,
    AMAXBenchmarkScenario,
    canonical_amax_benchmark_scenarios,
    classify_supervisory_cadence,
)
from .capability_declaration import (
    EdgeCapabilityDeclaration,
    default_amax_edge_capability_declaration,
    default_amax_edge_validation_capabilities,
)
from .feasibility import (
    AMAX_CODESYS_RUNTIMES,
    AMAX_ML_RUNTIME_OPTIONS,
    AMAX_OS_FAMILIES,
    AMAX_PACKAGING_RISK_LEVELS,
    AMAX_RUNTIME_LINUX_CODESYS,
    AMAX_RUNTIME_LINUX_CONTAINER_SIDECAR,
    AMAX_RUNTIME_WINDOWS_CODESYS,
    AMAX_SKU_CELERON_3955U_4GB,
    AMAX_SKU_CORE_I5_6300U_8GB,
    AMAX_SKU_CORE_I7_6600U_8GB,
    AMAX_SKU_RECOMMENDATION_TIERS,
    AMAXFeasibilityDecision,
    AMAXRuntimeOption,
    AMAXSkuProfile,
    canonical_amax_runtime_options,
    canonical_amax_sku_profiles,
    default_amax_feasibility_decision,
    recommended_amax_hardware_profile,
)
from .hardware_profile import (
    AMAX_5580_PROFILE_ID,
    EDGE_REJECTED_ACCELERATOR_TOKENS,
    EDGE_RUNTIME_CLASSES,
    EdgeHardwareProfile,
    amax_5580_cpu_profile,
)
from .package_validator import (
    EdgePackageValidationResult,
    validate_deployment_package_for_edge,
)
from .read_only_integration import (
    ACCESS_MODE_AUDIT_ONLY,
    ACCESS_MODE_READ_ONLY,
    AMAX_READ_ONLY_INTEGRATION_CONTRACT_ID,
    EQUIVALENCE_BLOCKED,
    EQUIVALENCE_COMPATIBLE,
    EQUIVALENCE_NOT_EVALUATED,
    EQUIVALENCE_STATUS_TOKENS,
    MISSING_BEHAVIOR_DROP_FRAME,
    MISSING_BEHAVIOR_FLAG_MISSING,
    MISSING_BEHAVIOR_HOLD_LAST_GOOD,
    MISSING_BEHAVIOR_TOKENS,
    PROTOCOL_CODESYS_SHARED_MEMORY,
    PROTOCOL_CODESYS_SYMBOL,
    PROTOCOL_MODBUS_RTU,
    PROTOCOL_MODBUS_TCP,
    PROTOCOL_MQTT_SPARKPLUG_READ_ONLY,
    PROTOCOL_OPC_UA,
    READ_ONLY_ACCESS_MODES,
    READ_ONLY_INTEGRATION_PROTOCOLS,
    STALE_BEHAVIOR_DROP_FRAME,
    STALE_BEHAVIOR_FLAG_STALE,
    STALE_BEHAVIOR_HOLD_LAST_GOOD,
    STALE_BEHAVIOR_TOKENS,
    ReadOnlyIntegrationContract,
    ReadOnlyIntegrationDiagnostics,
    ReadOnlyIntegrationProtocol,
    ReadOnlyTagBinding,
    ReadOnlyTelemetrySource,
    ReplayToLiveEquivalenceEvidence,
    TelemetryFreshnessPolicy,
    default_amax_read_only_integration_contract,
    default_amax_replay_to_live_equivalence_evidence,
    diagnose_read_only_integration_contract,
)

__all__ = [
    "ACCESS_MODE_AUDIT_ONLY",
    "ACCESS_MODE_READ_ONLY",
    "AMAX_5580_PROFILE_ID",
    "AMAX_BENCHMARK_CADENCE_BUCKETS",
    "AMAX_BENCHMARK_FRAMEWORKS",
    "AMAX_BENCHMARK_SCENARIO_BRANCH",
    "AMAX_BENCHMARK_SCENARIO_PUMP",
    "AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP",
    "AMAX_CODESYS_RUNTIMES",
    "AMAX_ML_RUNTIME_OPTIONS",
    "AMAX_OS_FAMILIES",
    "AMAX_PACKAGING_RISK_LEVELS",
    "AMAX_READ_ONLY_INTEGRATION_CONTRACT_ID",
    "AMAX_RUNTIME_LINUX_CODESYS",
    "AMAX_RUNTIME_LINUX_CONTAINER_SIDECAR",
    "AMAX_RUNTIME_WINDOWS_CODESYS",
    "AMAX_SKU_CELERON_3955U_4GB",
    "AMAX_SKU_CORE_I5_6300U_8GB",
    "AMAX_SKU_CORE_I7_6600U_8GB",
    "AMAX_SKU_RECOMMENDATION_TIERS",
    "AMAXBenchmarkMetrics",
    "AMAXBenchmarkReport",
    "AMAXBenchmarkScenario",
    "AMAXFeasibilityDecision",
    "AMAXRuntimeOption",
    "AMAXSkuProfile",
    "EDGE_REJECTED_ACCELERATOR_TOKENS",
    "EDGE_RUNTIME_CLASSES",
    "EQUIVALENCE_BLOCKED",
    "EQUIVALENCE_COMPATIBLE",
    "EQUIVALENCE_NOT_EVALUATED",
    "EQUIVALENCE_STATUS_TOKENS",
    "EdgeCapabilityDeclaration",
    "EdgeHardwareProfile",
    "EdgePackageValidationResult",
    "MISSING_BEHAVIOR_DROP_FRAME",
    "MISSING_BEHAVIOR_FLAG_MISSING",
    "MISSING_BEHAVIOR_HOLD_LAST_GOOD",
    "MISSING_BEHAVIOR_TOKENS",
    "PROTOCOL_CODESYS_SHARED_MEMORY",
    "PROTOCOL_CODESYS_SYMBOL",
    "PROTOCOL_MODBUS_RTU",
    "PROTOCOL_MODBUS_TCP",
    "PROTOCOL_MQTT_SPARKPLUG_READ_ONLY",
    "PROTOCOL_OPC_UA",
    "READ_ONLY_ACCESS_MODES",
    "READ_ONLY_INTEGRATION_PROTOCOLS",
    "ReadOnlyIntegrationContract",
    "ReadOnlyIntegrationDiagnostics",
    "ReadOnlyIntegrationProtocol",
    "ReadOnlyTagBinding",
    "ReadOnlyTelemetrySource",
    "ReplayToLiveEquivalenceEvidence",
    "STALE_BEHAVIOR_DROP_FRAME",
    "STALE_BEHAVIOR_FLAG_STALE",
    "STALE_BEHAVIOR_HOLD_LAST_GOOD",
    "STALE_BEHAVIOR_TOKENS",
    "TelemetryFreshnessPolicy",
    "amax_5580_cpu_profile",
    "canonical_amax_benchmark_scenarios",
    "canonical_amax_runtime_options",
    "canonical_amax_sku_profiles",
    "classify_supervisory_cadence",
    "default_amax_edge_capability_declaration",
    "default_amax_edge_validation_capabilities",
    "default_amax_feasibility_decision",
    "default_amax_read_only_integration_contract",
    "default_amax_replay_to_live_equivalence_evidence",
    "diagnose_read_only_integration_contract",
    "recommended_amax_hardware_profile",
    "validate_deployment_package_for_edge",
]
