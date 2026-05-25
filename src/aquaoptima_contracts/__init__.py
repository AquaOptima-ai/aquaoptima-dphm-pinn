"""AquaOptima Shared Contracts / SDK (Sprint 41 MVP).

This package owns versioned schemas, the canonical safety vocabulary,
capability declarations, deterministic JSON helpers, and the golden
fixture harness shared by every deployable (Edge Runtime, AI /
Optimization Server, Operations Console) in Phase 2+.

The Sprint 41 surface is intentionally minimal: ``SchemaVersion``,
``ContractEnvelope``, ``SafetyFlagSet``, ``CapabilityDeclaration``,
``CapabilityRequirement``, ``evaluate_capability_gate``, and the
deterministic JSON helpers. No HTTP, no database, no runtime
evaluation, no live OT binding, no PLC/PAC/SCADA write, no command
emission, no setpoint output, no control-loop closure. The SDK does
not import any ``aquaoptima.*`` module.
"""

from .base.checksum import ALLOWED_CHECKSUM_ALGORITHMS, Checksum
from .base.envelope import (
    ALLOWED_SCHEMA_FAMILIES,
    ALLOWED_CREATED_BY_COMPONENTS,
    ContractEnvelope,
    ContractError,
)
from .base.identifiers import ArtifactReference
from .base.provenance import ALLOWED_PROVENANCE_COMPONENTS, Provenance
from .advisory import (
    AdvisoryContract,
    AdvisoryDecision,
    AdvisoryEvaluation,
    AdvisoryProposal,
    AdvisoryRejectionReason,
    AdvisoryRule,
)
from .calibration import (
    CalibrationLossSummary,
    DPLCalibrationDiagnostics,
    DPLCalibrationLossReport,
    DPLResidual,
)
from .edge import (
    AMAX_5580_PROFILE_ID,
    AMAX_BENCHMARK_CADENCE_BUCKETS,
    AMAX_BENCHMARK_FRAMEWORKS,
    AMAX_BENCHMARK_SCENARIO_BRANCH,
    AMAX_BENCHMARK_SCENARIO_PUMP,
    AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP,
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
    AMAXBenchmarkMetrics,
    AMAXBenchmarkReport,
    AMAXBenchmarkScenario,
    AMAXFeasibilityDecision,
    AMAXRuntimeOption,
    AMAXSkuProfile,
    EDGE_REJECTED_ACCELERATOR_TOKENS,
    EDGE_RUNTIME_CLASSES,
    EdgeCapabilityDeclaration,
    EdgeHardwareProfile,
    EdgePackageValidationResult,
    amax_5580_cpu_profile,
    canonical_amax_benchmark_scenarios,
    canonical_amax_runtime_options,
    canonical_amax_sku_profiles,
    classify_supervisory_cadence,
    default_amax_edge_capability_declaration,
    default_amax_edge_validation_capabilities,
    default_amax_feasibility_decision,
    recommended_amax_hardware_profile,
    validate_deployment_package_for_edge,
)
from .import_quality import (
    EpanetImportDiagnosticsRecord,
    EpanetImportQualityReport,
    EpanetImportQualitySectionReport,
    EpanetImportQualitySurrogateReport,
    ImportQualitySeverity,
    TopologyReference,
)
from .manifest.shadow_deployment import (
    SDK_SHADOW_DEPLOYMENT_ARTIFACT_KINDS,
    ShadowDeploymentArtifact,
    ShadowDeploymentManifest,
    ShadowDeploymentPackageDiagnostics,
)
from .package import (
    PACKAGE_ARTIFACT_ROLES,
    PACKAGE_MODEL_FRAMEWORKS,
    ArtifactBundleRecord,
    ArtifactManifest,
    DeploymentPackageManifest,
    ModelArtifactRecord,
    PackageSafetyDeclaration,
    PackageValidationDiagnostic,
    build_deployment_package_manifest_from_shadow,
)
from .runtime.shadow_report import (
    ShadowRuntimeDiagnostics,
    ShadowRuntimeReport,
    ShadowRuntimeStepReport,
)
from .base.serialization import (
    dump_canonical_json,
    load_canonical_json,
    write_canonical_json,
)
from .base.validation import (
    is_lowercase_snake_case_token,
    validate_token,
)
from .safety.capability_gates import (
    ALLOWED_CAPABILITY_TOKENS,
    FORBIDDEN_CAPABILITY_TOKENS,
    CapabilityDeclaration,
    CapabilityGateResult,
    CapabilityRequirement,
    CapabilityTokenError,
    evaluate_capability_gate,
)
from .safety.flags import (
    CANONICAL_SAFETY_FLAG_TOKENS,
    SafetyFlagError,
    SafetyFlagSet,
)
from .safety.vocabulary import (
    FORBIDDEN_VOCABULARY,
    contains_forbidden_token,
)
from .telemetry.axis import CANONICAL_TELEMETRY_AXES, TelemetryAxis
from .telemetry.replay import (
    ShadowReplayDataset,
    ShadowReplayDiagnostics,
    ShadowReplayFrame,
)
from .telemetry.tag_map import (
    CANONICAL_TELEMETRY_ROLES,
    TelemetryTagMap,
    TelemetryTagMapDiagnostics,
    TelemetryTagSpec,
)
from .telemetry.unit import CANONICAL_UNIT_DIMENSIONS, UnitSpec
from .version import SDK_VERSION, SDK_VERSION_STRING, SchemaVersion

__all__ = [
    "ALLOWED_CAPABILITY_TOKENS",
    "ALLOWED_CHECKSUM_ALGORITHMS",
    "ALLOWED_CREATED_BY_COMPONENTS",
    "ALLOWED_PROVENANCE_COMPONENTS",
    "ALLOWED_SCHEMA_FAMILIES",
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
    "AdvisoryContract",
    "AdvisoryDecision",
    "AdvisoryEvaluation",
    "AdvisoryProposal",
    "AdvisoryRejectionReason",
    "AdvisoryRule",
    "ArtifactBundleRecord",
    "ArtifactManifest",
    "ArtifactReference",
    "CANONICAL_SAFETY_FLAG_TOKENS",
    "CANONICAL_TELEMETRY_AXES",
    "CANONICAL_TELEMETRY_ROLES",
    "CANONICAL_UNIT_DIMENSIONS",
    "CalibrationLossSummary",
    "CapabilityDeclaration",
    "CapabilityGateResult",
    "CapabilityRequirement",
    "CapabilityTokenError",
    "Checksum",
    "ContractEnvelope",
    "ContractError",
    "DPLCalibrationDiagnostics",
    "DPLCalibrationLossReport",
    "DPLResidual",
    "DeploymentPackageManifest",
    "EDGE_REJECTED_ACCELERATOR_TOKENS",
    "EDGE_RUNTIME_CLASSES",
    "EdgeCapabilityDeclaration",
    "EdgeHardwareProfile",
    "EdgePackageValidationResult",
    "EpanetImportDiagnosticsRecord",
    "EpanetImportQualityReport",
    "EpanetImportQualitySectionReport",
    "EpanetImportQualitySurrogateReport",
    "ImportQualitySeverity",
    "ModelArtifactRecord",
    "PACKAGE_ARTIFACT_ROLES",
    "PACKAGE_MODEL_FRAMEWORKS",
    "PackageSafetyDeclaration",
    "PackageValidationDiagnostic",
    "TopologyReference",
    "FORBIDDEN_CAPABILITY_TOKENS",
    "FORBIDDEN_VOCABULARY",
    "Provenance",
    "SDK_SHADOW_DEPLOYMENT_ARTIFACT_KINDS",
    "SDK_VERSION",
    "SDK_VERSION_STRING",
    "SafetyFlagError",
    "SafetyFlagSet",
    "SchemaVersion",
    "ShadowDeploymentArtifact",
    "ShadowDeploymentManifest",
    "ShadowDeploymentPackageDiagnostics",
    "ShadowReplayDataset",
    "ShadowReplayDiagnostics",
    "ShadowReplayFrame",
    "ShadowRuntimeDiagnostics",
    "ShadowRuntimeReport",
    "ShadowRuntimeStepReport",
    "TelemetryAxis",
    "TelemetryTagMap",
    "TelemetryTagMapDiagnostics",
    "TelemetryTagSpec",
    "UnitSpec",
    "amax_5580_cpu_profile",
    "build_deployment_package_manifest_from_shadow",
    "canonical_amax_benchmark_scenarios",
    "canonical_amax_runtime_options",
    "canonical_amax_sku_profiles",
    "classify_supervisory_cadence",
    "contains_forbidden_token",
    "default_amax_edge_capability_declaration",
    "default_amax_edge_validation_capabilities",
    "default_amax_feasibility_decision",
    "dump_canonical_json",
    "evaluate_capability_gate",
    "is_lowercase_snake_case_token",
    "load_canonical_json",
    "recommended_amax_hardware_profile",
    "validate_deployment_package_for_edge",
    "validate_token",
    "write_canonical_json",
]
