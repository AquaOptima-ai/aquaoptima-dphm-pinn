"""``EpanetImportQualityReport`` SDK projection (Sprint 43).

Consumer-facing projections of the Phase 1 Sprint 33
:class:`aquaoptima.dphm.inp_import_quality_report.EpanetImportQualityReport`
and Sprint 23-32 diagnostics surface. The SDK projection here is
audit-only: it never represents a parser, a WNTR import, or a dPHM
``Network`` construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError


IMPORT_QUALITY_SEVERITIES: frozenset[str] = frozenset(
    {"INFO", "WARNING", "LIMITATION"}
)


IMPORT_QUALITY_PARSERS: frozenset[str] = frozenset({"fallback", "wntr"})


_HEX_64_RE: re.Pattern[str] = re.compile(r"^[0-9a-fA-F]{64}$")


_SEVERITY_FIELDS: tuple[str, ...] = ("value",)


_TOPOLOGY_REFERENCE_FIELDS: tuple[str, ...] = (
    "topology_id",
    "version",
    "sha256",
    "node_count",
    "edge_count",
)


_SECTION_FIELDS: tuple[str, ...] = (
    "section",
    "row_count",
    "ignored_present",
    "message",
)


_SURROGATE_FIELDS: tuple[str, ...] = (
    "edge_index",
    "link_id",
    "link_type",
    "surrogate_kind",
    "severity",
    "message",
    "limitations",
)


_RECORD_FIELDS: tuple[str, ...] = (
    "section",
    "severity",
    "row_count",
    "message",
)


_REPORT_FIELDS: tuple[str, ...] = (
    "parser",
    "total_diagnostic_rows",
    "ignored_section_count",
    "row_count_by_section",
    "ignored_sections",
    "sections",
    "surrogates",
    "surrogate_count_by_kind",
    "diagnostics_records",
    "topology_reference",
    "warnings",
    "limitations",
)


def _ensure_non_negative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{label} must be int, got {type(value).__name__}")
    if value < 0:
        raise ContractError(f"{label} must be non-negative, got {value}")
    return value


def _ensure_str_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if isinstance(value, str) or isinstance(value, bytes):
        raise ContractError(f"{label} must be a tuple of strings")
    if not isinstance(value, tuple):
        raise ContractError(f"{label} must be a tuple of strings")
    for item in value:
        if not isinstance(item, str):
            raise ContractError(f"{label} entries must be strings")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class ImportQualitySeverity:
    """Canonical severity token wrapper."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise ContractError(
                "ImportQualitySeverity.value must be a string"
            )
        if self.value not in IMPORT_QUALITY_SEVERITIES:
            raise ContractError(
                f"ImportQualitySeverity.value {self.value!r} is not in the "
                f"canonical severity vocabulary; allowed: "
                f"{sorted(IMPORT_QUALITY_SEVERITIES)}"
            )

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ImportQualitySeverity":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ImportQualitySeverity.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        if "value" not in data:
            raise ContractError(
                "ImportQualitySeverity missing required field 'value'"
            )
        unknown = set(data.keys()) - set(_SEVERITY_FIELDS)
        if unknown:
            raise ContractError(
                f"ImportQualitySeverity received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(value=str(data["value"]))


@dataclass(frozen=True)
class TopologyReference:
    """Reference to a topology stored on the AI server."""

    topology_id: str
    version: str
    sha256: str
    node_count: int
    edge_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.topology_id, str) or not self.topology_id:
            raise ContractError(
                "TopologyReference.topology_id must be a non-empty string"
            )
        if not isinstance(self.version, str) or not self.version:
            raise ContractError(
                "TopologyReference.version must be a non-empty string"
            )
        if not isinstance(self.sha256, str) or not _HEX_64_RE.match(self.sha256):
            raise ContractError(
                "TopologyReference.sha256 must be a 64-character hex string"
            )
        _ensure_non_negative_int(
            self.node_count, label="TopologyReference.node_count"
        )
        _ensure_non_negative_int(
            self.edge_count, label="TopologyReference.edge_count"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology_id": self.topology_id,
            "version": self.version,
            "sha256": self.sha256,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TopologyReference":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"TopologyReference.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {
            "topology_id",
            "version",
            "sha256",
            "node_count",
            "edge_count",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"TopologyReference missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_TOPOLOGY_REFERENCE_FIELDS)
        if unknown:
            raise ContractError(
                f"TopologyReference received unknown fields: {sorted(unknown)}"
            )
        return cls(
            topology_id=str(data["topology_id"]),
            version=str(data["version"]),
            sha256=str(data["sha256"]),
            node_count=int(data["node_count"]),
            edge_count=int(data["edge_count"]),
        )


@dataclass(frozen=True)
class EpanetImportQualitySectionReport:
    """SDK per-section entry inside an :class:`EpanetImportQualityReport`."""

    section: str
    row_count: int
    ignored_present: bool
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.section, str) or not self.section:
            raise ContractError(
                "EpanetImportQualitySectionReport.section must be a non-empty string"
            )
        _ensure_non_negative_int(
            self.row_count,
            label="EpanetImportQualitySectionReport.row_count",
        )
        if not isinstance(self.ignored_present, bool):
            raise ContractError(
                "EpanetImportQualitySectionReport.ignored_present must be bool"
            )
        if not isinstance(self.message, str):
            raise ContractError(
                "EpanetImportQualitySectionReport.message must be a string"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "row_count": self.row_count,
            "ignored_present": self.ignored_present,
            "message": self.message,
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "EpanetImportQualitySectionReport":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"EpanetImportQualitySectionReport.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        missing = {"section", "row_count", "ignored_present", "message"} - set(
            data.keys()
        )
        if missing:
            raise ContractError(
                f"EpanetImportQualitySectionReport missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_SECTION_FIELDS)
        if unknown:
            raise ContractError(
                f"EpanetImportQualitySectionReport received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            section=str(data["section"]),
            row_count=int(data["row_count"]),
            ignored_present=bool(data["ignored_present"]),
            message=str(data["message"]),
        )


@dataclass(frozen=True)
class EpanetImportQualitySurrogateReport:
    """SDK per-edge surrogate entry inside an :class:`EpanetImportQualityReport`."""

    edge_index: int
    link_id: str
    link_type: str
    surrogate_kind: str
    severity: str
    message: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_non_negative_int(
            self.edge_index,
            label="EpanetImportQualitySurrogateReport.edge_index",
        )
        for name in ("link_id", "link_type", "surrogate_kind", "message"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ContractError(
                    f"EpanetImportQualitySurrogateReport.{name} must be a string"
                )
        if self.severity not in IMPORT_QUALITY_SEVERITIES:
            raise ContractError(
                f"EpanetImportQualitySurrogateReport.severity {self.severity!r} "
                f"is not in {sorted(IMPORT_QUALITY_SEVERITIES)}"
            )
        _ensure_str_tuple(
            self.limitations,
            label="EpanetImportQualitySurrogateReport.limitations",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_index": self.edge_index,
            "link_id": self.link_id,
            "link_type": self.link_type,
            "surrogate_kind": self.surrogate_kind,
            "severity": self.severity,
            "message": self.message,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "EpanetImportQualitySurrogateReport":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"EpanetImportQualitySurrogateReport.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        missing = {
            "edge_index",
            "link_id",
            "link_type",
            "surrogate_kind",
            "severity",
            "message",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"EpanetImportQualitySurrogateReport missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_SURROGATE_FIELDS)
        if unknown:
            raise ContractError(
                f"EpanetImportQualitySurrogateReport received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_lims = data.get("limitations", ())
        if not isinstance(raw_lims, Sequence) or isinstance(
            raw_lims, (str, bytes)
        ):
            raise ContractError(
                "EpanetImportQualitySurrogateReport.limitations must be a "
                "sequence of strings"
            )
        return cls(
            edge_index=int(data["edge_index"]),
            link_id=str(data["link_id"]),
            link_type=str(data["link_type"]),
            surrogate_kind=str(data["surrogate_kind"]),
            severity=str(data["severity"]),
            message=str(data["message"]),
            limitations=tuple(str(s) for s in raw_lims),
        )


@dataclass(frozen=True)
class EpanetImportDiagnosticsRecord:
    """Slim Console-friendly projection of a single diagnostics row.

    Carries the canonical section name, severity, row count, and a
    short human-readable message — every other Phase 1 diagnostic
    field (row payload, line number, …) stays on the AI side.
    """

    section: str
    severity: str
    row_count: int
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.section, str) or not self.section:
            raise ContractError(
                "EpanetImportDiagnosticsRecord.section must be a non-empty string"
            )
        if self.severity not in IMPORT_QUALITY_SEVERITIES:
            raise ContractError(
                f"EpanetImportDiagnosticsRecord.severity {self.severity!r} "
                f"is not in {sorted(IMPORT_QUALITY_SEVERITIES)}"
            )
        _ensure_non_negative_int(
            self.row_count,
            label="EpanetImportDiagnosticsRecord.row_count",
        )
        if not isinstance(self.message, str):
            raise ContractError(
                "EpanetImportDiagnosticsRecord.message must be a string"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "severity": self.severity,
            "row_count": self.row_count,
            "message": self.message,
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "EpanetImportDiagnosticsRecord":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"EpanetImportDiagnosticsRecord.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        missing = {"section", "severity", "row_count", "message"} - set(
            data.keys()
        )
        if missing:
            raise ContractError(
                f"EpanetImportDiagnosticsRecord missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_RECORD_FIELDS)
        if unknown:
            raise ContractError(
                f"EpanetImportDiagnosticsRecord received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            section=str(data["section"]),
            severity=str(data["severity"]),
            row_count=int(data["row_count"]),
            message=str(data["message"]),
        )


@dataclass(frozen=True)
class EpanetImportQualityReport:
    """SDK projection of a Phase 1 EPANET import-quality report."""

    parser: str
    total_diagnostic_rows: int
    ignored_section_count: int
    row_count_by_section: Mapping[str, int] = field(default_factory=dict)
    ignored_sections: tuple[str, ...] = ()
    sections: tuple[EpanetImportQualitySectionReport, ...] = ()
    surrogates: tuple[EpanetImportQualitySurrogateReport, ...] = ()
    surrogate_count_by_kind: Mapping[str, int] = field(default_factory=dict)
    diagnostics_records: tuple[EpanetImportDiagnosticsRecord, ...] = ()
    topology_reference: TopologyReference | None = None
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.parser, str)
            or self.parser not in IMPORT_QUALITY_PARSERS
        ):
            raise ContractError(
                f"EpanetImportQualityReport.parser {self.parser!r} is not in "
                f"{sorted(IMPORT_QUALITY_PARSERS)}"
            )
        _ensure_non_negative_int(
            self.total_diagnostic_rows,
            label="EpanetImportQualityReport.total_diagnostic_rows",
        )
        _ensure_non_negative_int(
            self.ignored_section_count,
            label="EpanetImportQualityReport.ignored_section_count",
        )
        if not isinstance(self.row_count_by_section, Mapping):
            raise ContractError(
                "EpanetImportQualityReport.row_count_by_section must be a mapping"
            )
        clean_counts: dict[str, int] = {}
        for key, value in self.row_count_by_section.items():
            if not isinstance(key, str) or not key:
                raise ContractError(
                    "EpanetImportQualityReport.row_count_by_section keys must "
                    "be non-empty strings"
                )
            clean_counts[key] = _ensure_non_negative_int(
                value,
                label=(
                    "EpanetImportQualityReport.row_count_by_section"
                    f"[{key!r}]"
                ),
            )
        object.__setattr__(self, "row_count_by_section", clean_counts)
        _ensure_str_tuple(
            self.ignored_sections,
            label="EpanetImportQualityReport.ignored_sections",
        )
        if not isinstance(self.sections, tuple):
            raise ContractError(
                "EpanetImportQualityReport.sections must be a tuple"
            )
        for s in self.sections:
            if not isinstance(s, EpanetImportQualitySectionReport):
                raise ContractError(
                    "EpanetImportQualityReport.sections entries must be "
                    "EpanetImportQualitySectionReport instances"
                )
        if not isinstance(self.surrogates, tuple):
            raise ContractError(
                "EpanetImportQualityReport.surrogates must be a tuple"
            )
        for s in self.surrogates:
            if not isinstance(s, EpanetImportQualitySurrogateReport):
                raise ContractError(
                    "EpanetImportQualityReport.surrogates entries must be "
                    "EpanetImportQualitySurrogateReport instances"
                )
        if not isinstance(self.surrogate_count_by_kind, Mapping):
            raise ContractError(
                "EpanetImportQualityReport.surrogate_count_by_kind must be a "
                "mapping"
            )
        clean_surrogate: dict[str, int] = {}
        for key, value in self.surrogate_count_by_kind.items():
            if not isinstance(key, str) or not key:
                raise ContractError(
                    "EpanetImportQualityReport.surrogate_count_by_kind keys "
                    "must be non-empty strings"
                )
            clean_surrogate[key] = _ensure_non_negative_int(
                value,
                label=(
                    "EpanetImportQualityReport.surrogate_count_by_kind"
                    f"[{key!r}]"
                ),
            )
        object.__setattr__(self, "surrogate_count_by_kind", clean_surrogate)
        if not isinstance(self.diagnostics_records, tuple):
            raise ContractError(
                "EpanetImportQualityReport.diagnostics_records must be a tuple"
            )
        for r in self.diagnostics_records:
            if not isinstance(r, EpanetImportDiagnosticsRecord):
                raise ContractError(
                    "EpanetImportQualityReport.diagnostics_records entries "
                    "must be EpanetImportDiagnosticsRecord instances"
                )
        if self.topology_reference is not None and not isinstance(
            self.topology_reference, TopologyReference
        ):
            raise ContractError(
                "EpanetImportQualityReport.topology_reference must be a "
                "TopologyReference or None"
            )
        _ensure_str_tuple(
            self.warnings, label="EpanetImportQualityReport.warnings"
        )
        _ensure_str_tuple(
            self.limitations,
            label="EpanetImportQualityReport.limitations",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "parser": self.parser,
            "total_diagnostic_rows": self.total_diagnostic_rows,
            "ignored_section_count": self.ignored_section_count,
            "row_count_by_section": dict(self.row_count_by_section),
            "ignored_sections": list(self.ignored_sections),
            "sections": [s.to_dict() for s in self.sections],
            "surrogates": [s.to_dict() for s in self.surrogates],
            "surrogate_count_by_kind": dict(self.surrogate_count_by_kind),
            "diagnostics_records": [
                r.to_dict() for r in self.diagnostics_records
            ],
            "topology_reference": (
                self.topology_reference.to_dict()
                if self.topology_reference is not None
                else None
            ),
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EpanetImportQualityReport":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"EpanetImportQualityReport.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {
            "parser",
            "total_diagnostic_rows",
            "ignored_section_count",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"EpanetImportQualityReport missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_REPORT_FIELDS)
        if unknown:
            raise ContractError(
                f"EpanetImportQualityReport received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_sections = data.get("sections", ()) or ()
        if not isinstance(raw_sections, Sequence) or isinstance(
            raw_sections, (str, bytes)
        ):
            raise ContractError(
                "EpanetImportQualityReport.sections must be a sequence"
            )
        raw_surrogates = data.get("surrogates", ()) or ()
        if not isinstance(raw_surrogates, Sequence) or isinstance(
            raw_surrogates, (str, bytes)
        ):
            raise ContractError(
                "EpanetImportQualityReport.surrogates must be a sequence"
            )
        raw_records = data.get("diagnostics_records", ()) or ()
        if not isinstance(raw_records, Sequence) or isinstance(
            raw_records, (str, bytes)
        ):
            raise ContractError(
                "EpanetImportQualityReport.diagnostics_records must be a sequence"
            )
        topology_raw = data.get("topology_reference")
        topology_reference: TopologyReference | None
        if topology_raw is None:
            topology_reference = None
        else:
            topology_reference = TopologyReference.from_dict(topology_raw)
        return cls(
            parser=str(data["parser"]),
            total_diagnostic_rows=int(data["total_diagnostic_rows"]),
            ignored_section_count=int(data["ignored_section_count"]),
            row_count_by_section=dict(data.get("row_count_by_section", {}) or {}),
            ignored_sections=tuple(
                str(s) for s in data.get("ignored_sections", ()) or ()
            ),
            sections=tuple(
                EpanetImportQualitySectionReport.from_dict(s)
                for s in raw_sections
            ),
            surrogates=tuple(
                EpanetImportQualitySurrogateReport.from_dict(s)
                for s in raw_surrogates
            ),
            surrogate_count_by_kind=dict(
                data.get("surrogate_count_by_kind", {}) or {}
            ),
            diagnostics_records=tuple(
                EpanetImportDiagnosticsRecord.from_dict(r) for r in raw_records
            ),
            topology_reference=topology_reference,
            warnings=tuple(str(w) for w in data.get("warnings", ()) or ()),
            limitations=tuple(
                str(s) for s in data.get("limitations", ()) or ()
            ),
        )


# ---------------------------------------------------------------------------
# Phase 1 projection adapter
# ---------------------------------------------------------------------------


def project_phase1_import_quality_report(
    phase1_report: Any,
    *,
    topology_reference: TopologyReference | None = None,
) -> EpanetImportQualityReport:
    """Project a Phase 1 EPANET import-quality report into the SDK shape.

    Duck-typed: the adapter reads the documented attributes of the
    Phase 1 report (``parser``, ``total_diagnostic_rows``,
    ``ignored_section_count``, ``row_count_by_section``,
    ``ignored_sections``, ``sections``, ``surrogates``,
    ``surrogate_count_by_kind``, ``warnings``, ``limitations``)
    and does not import ``aquaoptima.*`` from inside SDK package
    code, preserving the no-runtime-dependency boundary.

    The supplied object is never mutated. The SDK report's
    deterministic JSON shape is the only output surface.
    """
    sections = tuple(
        EpanetImportQualitySectionReport(
            section=str(getattr(s, "section")),
            row_count=int(getattr(s, "row_count")),
            ignored_present=bool(getattr(s, "ignored_present")),
            message=str(getattr(s, "message")),
        )
        for s in getattr(phase1_report, "sections", ())
    )
    surrogates = tuple(
        EpanetImportQualitySurrogateReport(
            edge_index=int(getattr(s, "edge_index")),
            link_id=str(getattr(s, "link_id")),
            link_type=str(getattr(s, "link_type")),
            surrogate_kind=str(getattr(s, "surrogate_kind")),
            severity=str(getattr(s, "severity")),
            message=str(getattr(s, "message")),
            limitations=tuple(
                str(x) for x in getattr(s, "limitations", ())
            ),
        )
        for s in getattr(phase1_report, "surrogates", ())
    )
    return EpanetImportQualityReport(
        parser=str(getattr(phase1_report, "parser")),
        total_diagnostic_rows=int(
            getattr(phase1_report, "total_diagnostic_rows")
        ),
        ignored_section_count=int(
            getattr(phase1_report, "ignored_section_count")
        ),
        row_count_by_section={
            str(k): int(v)
            for k, v in (
                getattr(phase1_report, "row_count_by_section", {}) or {}
            ).items()
        },
        ignored_sections=tuple(
            str(s) for s in getattr(phase1_report, "ignored_sections", ())
        ),
        sections=sections,
        surrogates=surrogates,
        surrogate_count_by_kind={
            str(k): int(v)
            for k, v in (
                getattr(phase1_report, "surrogate_count_by_kind", {}) or {}
            ).items()
        },
        diagnostics_records=(),
        topology_reference=topology_reference,
        warnings=tuple(
            str(w) for w in getattr(phase1_report, "warnings", ())
        ),
        limitations=tuple(
            str(s) for s in getattr(phase1_report, "limitations", ())
        ),
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
