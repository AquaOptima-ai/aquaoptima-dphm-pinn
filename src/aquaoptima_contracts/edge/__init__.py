"""Edge package validation contracts (Sprint 45).

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

The boundary is non-negotiable: no live OT binding, no PLC/PAC/SCADA
write, no command emission, no setpoint output, no control-loop
closure, no HTTP / database / message-broker dependency, no model
loading, no inline model weights, no Edge Runtime daemon code in
this module. Validation is a pure value computation over the SDK
contract shapes.
"""

from .capability_declaration import (
    EdgeCapabilityDeclaration,
    default_amax_edge_capability_declaration,
    default_amax_edge_validation_capabilities,
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

__all__ = [
    "AMAX_5580_PROFILE_ID",
    "EDGE_REJECTED_ACCELERATOR_TOKENS",
    "EDGE_RUNTIME_CLASSES",
    "EdgeCapabilityDeclaration",
    "EdgeHardwareProfile",
    "EdgePackageValidationResult",
    "amax_5580_cpu_profile",
    "default_amax_edge_capability_declaration",
    "default_amax_edge_validation_capabilities",
    "validate_deployment_package_for_edge",
]
