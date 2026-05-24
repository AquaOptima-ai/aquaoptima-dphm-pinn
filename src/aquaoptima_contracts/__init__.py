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
    "AdvisoryContract",
    "AdvisoryDecision",
    "AdvisoryEvaluation",
    "AdvisoryProposal",
    "AdvisoryRejectionReason",
    "AdvisoryRule",
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
    "EpanetImportDiagnosticsRecord",
    "EpanetImportQualityReport",
    "EpanetImportQualitySectionReport",
    "EpanetImportQualitySurrogateReport",
    "ImportQualitySeverity",
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
    "contains_forbidden_token",
    "dump_canonical_json",
    "evaluate_capability_gate",
    "is_lowercase_snake_case_token",
    "load_canonical_json",
    "validate_token",
    "write_canonical_json",
]
