"""TDD — EPANET import-quality SDK projections (Sprint 43).

Acceptance: the SDK ``EpanetImportQualityReport``,
``EpanetImportDiagnosticsRecord``, ``ImportQualitySeverity``, and
``TopologyReference`` types capture the *consumer-facing* shape of
the Phase 1 Sprint 33 import-quality report. The SDK projection is
audit-only and never represents a parser, a WNTR import, or a
network construction.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    ContractError,
    EpanetImportDiagnosticsRecord,
    EpanetImportQualityReport,
    EpanetImportQualitySectionReport,
    EpanetImportQualitySurrogateReport,
    ImportQualitySeverity,
    TopologyReference,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.import_quality import (
    IMPORT_QUALITY_SEVERITIES,
    IMPORT_QUALITY_PARSERS,
    project_phase1_import_quality_report,
)


def test_severity_round_trip() -> None:
    severity = ImportQualitySeverity(value="WARNING")
    decoded = load_canonical_json(dump_canonical_json(severity))
    restored = ImportQualitySeverity.from_dict(decoded)
    assert restored == severity


def test_severity_rejects_unknown_value() -> None:
    with pytest.raises(ContractError):
        ImportQualitySeverity(value="catastrophic")


def test_severity_canonical_set_is_stable() -> None:
    assert IMPORT_QUALITY_SEVERITIES == frozenset(
        {"INFO", "WARNING", "LIMITATION"}
    )


def test_topology_reference_round_trip() -> None:
    ref = TopologyReference(
        topology_id="net-001",
        version="1.0.0",
        sha256="ab" * 32,
        node_count=10,
        edge_count=12,
    )
    decoded = load_canonical_json(dump_canonical_json(ref))
    restored = TopologyReference.from_dict(decoded)
    assert restored == ref


def test_topology_reference_rejects_negative_counts() -> None:
    with pytest.raises(ContractError):
        TopologyReference(
            topology_id="net-001",
            version="1.0.0",
            sha256="ab" * 32,
            node_count=-1,
            edge_count=0,
        )


def test_topology_reference_rejects_empty_id() -> None:
    with pytest.raises(ContractError):
        TopologyReference(
            topology_id="",
            version="1.0.0",
            sha256="ab" * 32,
            node_count=0,
            edge_count=0,
        )


def test_topology_reference_rejects_malformed_sha256() -> None:
    with pytest.raises(ContractError):
        TopologyReference(
            topology_id="net-001",
            version="1.0.0",
            sha256="not-hex",
            node_count=0,
            edge_count=0,
        )


def test_section_report_round_trip() -> None:
    section = EpanetImportQualitySectionReport(
        section="STATUS",
        row_count=3,
        ignored_present=False,
        message="Section present.",
    )
    decoded = load_canonical_json(dump_canonical_json(section))
    restored = EpanetImportQualitySectionReport.from_dict(decoded)
    assert restored == section


def test_section_report_rejects_negative_row_count() -> None:
    with pytest.raises(ContractError):
        EpanetImportQualitySectionReport(
            section="STATUS",
            row_count=-1,
            ignored_present=False,
            message="x",
        )


def test_section_report_rejects_empty_section() -> None:
    with pytest.raises(ContractError):
        EpanetImportQualitySectionReport(
            section="",
            row_count=0,
            ignored_present=False,
            message="x",
        )


def test_surrogate_report_round_trip() -> None:
    surrogate = EpanetImportQualitySurrogateReport(
        edge_index=4,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind="PRV_FIXED_HEAD_SURROGATE",
        severity="LIMITATION",
        message="PRV approximated as fixed-head surrogate",
        limitations=("PRV head curve omitted",),
    )
    decoded = load_canonical_json(dump_canonical_json(surrogate))
    restored = EpanetImportQualitySurrogateReport.from_dict(decoded)
    assert restored == surrogate


def test_surrogate_report_rejects_negative_edge_index() -> None:
    with pytest.raises(ContractError):
        EpanetImportQualitySurrogateReport(
            edge_index=-1,
            link_id="V1",
            link_type="VALVE",
            surrogate_kind="PRV_FIXED_HEAD_SURROGATE",
            severity="WARNING",
            message="x",
            limitations=(),
        )


def test_surrogate_report_rejects_unknown_severity() -> None:
    with pytest.raises(ContractError):
        EpanetImportQualitySurrogateReport(
            edge_index=0,
            link_id="V1",
            link_type="VALVE",
            surrogate_kind="PRV_FIXED_HEAD_SURROGATE",
            severity="catastrophic",
            message="x",
            limitations=(),
        )


def test_diagnostics_record_round_trip() -> None:
    record = EpanetImportDiagnosticsRecord(
        section="STATUS",
        severity="WARNING",
        row_count=3,
        message="status rows preserved",
    )
    decoded = load_canonical_json(dump_canonical_json(record))
    restored = EpanetImportDiagnosticsRecord.from_dict(decoded)
    assert restored == record


def test_diagnostics_record_rejects_negative_row_count() -> None:
    with pytest.raises(ContractError):
        EpanetImportDiagnosticsRecord(
            section="STATUS",
            severity="WARNING",
            row_count=-1,
            message="x",
        )


def test_report_minimal_round_trip() -> None:
    report = EpanetImportQualityReport(
        parser="fallback",
        total_diagnostic_rows=0,
        ignored_section_count=0,
    )
    decoded = load_canonical_json(dump_canonical_json(report))
    restored = EpanetImportQualityReport.from_dict(decoded)
    assert restored == report


def test_report_rejects_unknown_parser() -> None:
    with pytest.raises(ContractError):
        EpanetImportQualityReport(
            parser="exotic",
            total_diagnostic_rows=0,
            ignored_section_count=0,
        )


def test_report_rejects_negative_counts() -> None:
    with pytest.raises(ContractError):
        EpanetImportQualityReport(
            parser="fallback",
            total_diagnostic_rows=-1,
            ignored_section_count=0,
        )


def test_report_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ContractError):
        EpanetImportQualityReport.from_dict(
            {
                "parser": "fallback",
                "total_diagnostic_rows": 0,
                "ignored_section_count": 0,
                "actuator_setpoint": "1.0",
            }
        )


def test_report_canonical_parsers_are_stable() -> None:
    assert IMPORT_QUALITY_PARSERS == frozenset({"fallback", "wntr"})


def test_report_to_dict_carries_no_actuation_field() -> None:
    report = EpanetImportQualityReport(
        parser="fallback",
        total_diagnostic_rows=0,
        ignored_section_count=0,
    )
    decoded = load_canonical_json(dump_canonical_json(report))
    for key in decoded:
        assert "setpoint" not in key
        assert "write" not in key
        assert "control" not in key
        assert "command" not in key
        assert "actuate" not in key


def test_report_with_sections_and_surrogates_round_trip() -> None:
    report = EpanetImportQualityReport(
        parser="fallback",
        total_diagnostic_rows=3,
        ignored_section_count=1,
        row_count_by_section={"STATUS": 3},
        ignored_sections=("CONTROLS",),
        sections=(
            EpanetImportQualitySectionReport(
                section="STATUS",
                row_count=3,
                ignored_present=False,
                message="rows",
            ),
            EpanetImportQualitySectionReport(
                section="CONTROLS",
                row_count=0,
                ignored_present=True,
                message="ignored",
            ),
        ),
        surrogates=(
            EpanetImportQualitySurrogateReport(
                edge_index=4,
                link_id="V1",
                link_type="VALVE",
                surrogate_kind="PRV_FIXED_HEAD_SURROGATE",
                severity="LIMITATION",
                message="surrogate",
                limitations=("PRV omitted",),
            ),
        ),
        surrogate_count_by_kind={"PRV_FIXED_HEAD_SURROGATE": 1},
        warnings=("note",),
        limitations=("limit",),
    )
    decoded = load_canonical_json(dump_canonical_json(report))
    restored = EpanetImportQualityReport.from_dict(decoded)
    assert restored == report


def test_phase1_projection_round_trips_minimal_report() -> None:
    """Project an empty Phase 1 import-quality report into the SDK
    shape. The SDK projection adapter must not import EPANET parser
    code from inside SDK package code; this test builds a Phase 1
    report externally and projects it.
    """
    from aquaoptima.dphm.inp_io import EpanetImportDiagnostics
    from aquaoptima.dphm.inp_import_quality_report import (
        build_import_quality_report,
    )

    phase1_report = build_import_quality_report(
        EpanetImportDiagnostics(), network=None, parser="fallback"
    )
    sdk_report = project_phase1_import_quality_report(phase1_report)
    assert isinstance(sdk_report, EpanetImportQualityReport)
    assert sdk_report.parser == "fallback"
    assert sdk_report.total_diagnostic_rows == 0
    decoded = load_canonical_json(dump_canonical_json(sdk_report))
    restored = EpanetImportQualityReport.from_dict(decoded)
    assert restored == sdk_report
