"""Deployment package manifest contract projections (Sprint 44).

Sprint 44 adds the full SDK contract *shapes* for deployment package
manifests and model / artifact registry records named in
``docs/architecture/contracts-inventory.md``:

* :class:`PackageValidationDiagnostic` — warnings / errors tuples
  emitted by validators that ingest a package manifest.
* :class:`PackageSafetyDeclaration` — mandatory ``SafetyFlagSet`` plus
  capability requirement bundle for every package.
* :class:`ArtifactManifest` — a single role-tagged artifact entry
  composed from :class:`ArtifactReference` and :class:`Provenance`.
* :class:`ArtifactBundleRecord` — optional grouping of related
  artifact manifests used inside larger packages.
* :class:`ModelArtifactRecord` — model / artifact registry projection
  (no inline weights; carries :class:`ArtifactReference`,
  :class:`Checksum`, :class:`Provenance`, capability requirements,
  and the canonical safety flag set).
* :class:`DeploymentPackageManifest` — top-level audit-evidence
  manifest used by the Edge validator (Sprint 45). The SDK projection
  here owns *shape* and deterministic JSON only.

The SDK projection is audit / packaging evidence only:

* no live OT binding;
* no PLC/PAC/SCADA write;
* no command emission;
* no setpoint output;
* no control-loop closure;
* no HTTP / database / message-broker dependency;
* no inline model weights, no filesystem writes outside tests.

Construction validators reject any forbidden vocabulary token used as
a field value (substring scan) and any unknown / setpoint-shaped
field in :meth:`from_dict`.
"""

from .package_manifest import (
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
