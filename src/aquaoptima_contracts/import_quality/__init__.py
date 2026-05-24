"""EPANET import-quality / diagnostics SDK projections (Sprint 43).

Consumer-facing projections of the Phase 1 Sprint 33
import-quality report and Sprint 23-32 diagnostics surface. The
Phase 1 modules ``aquaoptima.dphm.inp_io`` and
``aquaoptima.dphm.inp_import_quality_report`` continue to own the
parser, the WNTR import, and the dPHM ``Network`` construction.

The SDK projection here is audit-only:

* :class:`ImportQualitySeverity` — canonical severity vocabulary.
* :class:`TopologyReference` — id / version / checksum reference to
  a topology stored on the AI server (the AI side owns the network
  bytes; the SDK only models the reference shape).
* :class:`EpanetImportQualitySectionReport` — per-section entry.
* :class:`EpanetImportQualitySurrogateReport` — per-surrogate entry.
* :class:`EpanetImportDiagnosticsRecord` — slim
  Console-friendly projection of a single diagnostics row.
* :class:`EpanetImportQualityReport` — top-level report.
"""

from .quality_report import (
    IMPORT_QUALITY_PARSERS,
    IMPORT_QUALITY_SEVERITIES,
    EpanetImportDiagnosticsRecord,
    EpanetImportQualityReport,
    EpanetImportQualitySectionReport,
    EpanetImportQualitySurrogateReport,
    ImportQualitySeverity,
    TopologyReference,
    project_phase1_import_quality_report,
)

__all__ = [
    "EpanetImportDiagnosticsRecord",
    "EpanetImportQualityReport",
    "EpanetImportQualitySectionReport",
    "EpanetImportQualitySurrogateReport",
    "IMPORT_QUALITY_PARSERS",
    "IMPORT_QUALITY_SEVERITIES",
    "ImportQualitySeverity",
    "TopologyReference",
    "project_phase1_import_quality_report",
]
