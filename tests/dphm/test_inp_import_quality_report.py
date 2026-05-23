"""Sprint 33 — EPANET ``.inp`` import-quality report composition.

Sprint 33 composes the Sprint 23-32 ``EpanetImportDiagnostics`` surfaces
(``status_rows``, ``ignored_sections``, ``control_rule_rows``,
``pattern_energy_rows``, ``emitter_demand_rows``, ``water_quality_rows``,
``edge_surrogates``, plus the Sprint 30/31/32 helpers) into a single
typed, immutable import-quality report.

These tests cover:

* the frozen :class:`EpanetImportQualityReport` /
  :class:`EpanetImportQualitySectionReport` /
  :class:`EpanetImportQualitySurrogateReport` dataclass shapes;
* empty diagnostics produce an empty / minimal report;
* row counts mirror ``summary()`` / ``row_count_by_section()``;
* ignored-section presence mirrors ``ignored_section_names()``;
* per-section entries surface row-only, ignored-only, and both;
* row diagnostics and ignored-section presence never double-count;
* edge surrogates are surfaced verbatim from Sprint 32;
* ``surrogate_count_by_kind`` mirrors the Sprint 32 helper;
* supplying a :class:`Network` validates surrogate edge indexes and
  surfaces a deterministic warning for out-of-range indexes, without
  raising or mutating the diagnostics or the network;
* the builder is pure / deterministic — calling it twice on the same
  inputs yields equal reports;
* the convenience loader agrees with the explicit
  ``load_network_from_inp(..., return_diagnostics=True)`` +
  ``build_import_quality_report`` pair;
* default ``load_network_from_inp(path)`` remains unchanged
  (Sprint 11 contract);
* the optional WNTR back-end produces an empty / minimal report with
  a documented asymmetry limitation; the test is gated on
  ``importorskip("wntr")``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    EDGE_SURROGATE_KIND_PRV_FIXED_HEAD,
    EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
    EDGE_SURROGATE_SEVERITY_LIMITATION,
    EpanetControlRuleDiagnostic,
    EpanetEdgeSurrogateDiagnostic,
    EpanetEmitterDemandDiagnostic,
    EpanetIgnoredSectionDiagnostic,
    EpanetImportDiagnostics,
    EpanetImportQualityReport,
    EpanetImportQualitySectionReport,
    EpanetImportQualitySurrogateReport,
    EpanetPatternEnergyDiagnostic,
    EpanetStatusDiagnostic,
    EpanetWaterQualityDiagnostic,
    Network,
    build_import_quality_report,
    load_inp_diagnostics,
    load_inp_import_quality_report,
    load_network_from_inp,
)


# ---------------------------------------------------------------------------
# Inline INP fixture helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def _baseline_inp(extra: str = "") -> str:
    """Minimal solvable network: 4 junctions, 1 reservoir, 5 pipes."""
    return (
        "[TITLE]\n"
        "Sprint 33 import-quality report fixture\n"
        "[JUNCTIONS]\n"
        " J1   0.0   10.0\n"
        " J2   0.0   15.0\n"
        " J3   0.0   12.0\n"
        " J4   0.0    8.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   R1   J1   300.0   250.0   130.0   0.0   OPEN\n"
        " P2   J1   J2   250.0   200.0   130.0   0.0   OPEN\n"
        " P3   J2   J3   220.0   150.0   130.0   0.0   OPEN\n"
        " P4   J3   J4   200.0   150.0   130.0   0.0   OPEN\n"
        " P5   J1   J4   280.0   150.0   130.0   0.0   OPEN\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{extra}"
        "[END]\n"
    )


def _all_channels_inp() -> str:
    """Baseline plus every diagnostic-emitting section (no [VALVES])."""
    extra = (
        "[STATUS]\n"
        " P1 OPEN\n"
        " P2 OPEN\n"
        "[CONTROLS]\n"
        " LINK P1 OPEN IF NODE J1 BELOW 5\n"
        " LINK P2 CLOSED IF NODE J1 ABOVE 30\n"
        "[RULES]\n"
        " RULE R1\n"
        " IF NODE J1 BELOW 5\n"
        " THEN LINK P1 OPEN\n"
        "[PATTERNS]\n"
        " PAT1 1.0 1.1 1.2 1.3\n"
        "[ENERGY]\n"
        " GLOBAL PRICE 0.10\n"
        "[EMITTERS]\n"
        " J1 0.5\n"
        "[DEMANDS]\n"
        " J1 1.0 PAT1 cat1\n"
        "[QUALITY]\n"
        " J1 0.5\n"
        "[SOURCES]\n"
        " J1 CONCEN 1.0 PAT1\n"
        "[REACTIONS]\n"
        " ORDER BULK 1\n"
        "[MIXING]\n"
        " T1 MIXED\n"
    )
    return _baseline_inp(extra)


def _valves_inp() -> str:
    """Baseline-shape topology with one PRV and one TCV (Sprint 32 surrogates)."""
    return (
        "[JUNCTIONS]\n"
        " J1   0.0    0.0\n"
        " J2   0.0   10.0\n"
        " J3   0.0    5.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   J2   J3   200   150   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   R1   J1   150   PRV   30.0   0\n"
        " V2   J1   J2   150   TCV   2.5   0\n"
        "[OPTIONS]\n"
        " Units    LPS\n"
        " Headloss H-W\n"
        "[END]\n"
    )


# ---------------------------------------------------------------------------
# Public dataclass shape (1) — frozen / typed / immutable
# ---------------------------------------------------------------------------


def test_section_report_is_frozen() -> None:
    rep = EpanetImportQualitySectionReport(
        section="STATUS", row_count=2, ignored_present=False, message="msg"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rep.row_count = 5  # type: ignore[misc]


def test_surrogate_report_is_frozen() -> None:
    rep = EpanetImportQualitySurrogateReport(
        edge_index=0,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_PRV_FIXED_HEAD,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
        limitations=("a",),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rep.edge_index = 7  # type: ignore[misc]


def test_quality_report_is_frozen() -> None:
    rep = build_import_quality_report(EpanetImportDiagnostics())
    with pytest.raises(dataclasses.FrozenInstanceError):
        rep.parser = "wntr"  # type: ignore[misc]


def test_quality_report_collections_are_immutable_types() -> None:
    rep = build_import_quality_report(EpanetImportDiagnostics())
    assert isinstance(rep.row_count_by_section, dict)
    assert isinstance(rep.ignored_sections, tuple)
    assert isinstance(rep.sections, tuple)
    assert isinstance(rep.surrogates, tuple)
    assert isinstance(rep.surrogate_count_by_kind, dict)
    assert isinstance(rep.warnings, tuple)
    assert isinstance(rep.limitations, tuple)


# ---------------------------------------------------------------------------
# (1) Empty diagnostics produce a zero-count report
# ---------------------------------------------------------------------------


def test_empty_diagnostics_produce_zero_count_report() -> None:
    rep = build_import_quality_report(EpanetImportDiagnostics())
    assert rep.parser == "fallback"
    assert rep.total_diagnostic_rows == 0
    assert rep.ignored_section_count == 0
    assert rep.row_count_by_section == {}
    assert rep.ignored_sections == ()
    assert rep.sections == ()
    assert rep.surrogates == ()
    assert rep.surrogate_count_by_kind == {}
    # The report still carries the structural limitations every fallback
    # report does (STATUS open-only, ignored-sections-dropped).
    assert rep.limitations  # non-empty
    assert rep.warnings == ()


# ---------------------------------------------------------------------------
# (2) Row counts mirror summary()
# ---------------------------------------------------------------------------


def test_report_row_counts_match_summary(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    summary = diagnostics.summary()
    assert rep.total_diagnostic_rows == summary.total_diagnostic_rows
    assert rep.row_count_by_section == diagnostics.row_count_by_section()
    # And the row count sum equals the section totals.
    assert sum(rep.row_count_by_section.values()) == rep.total_diagnostic_rows


# ---------------------------------------------------------------------------
# (3) Ignored-section presence mirrors ignored_section_names()
# ---------------------------------------------------------------------------


def test_report_ignored_sections_match_diagnostics(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    assert rep.ignored_sections == diagnostics.ignored_section_names()
    assert rep.ignored_section_count == len(diagnostics.ignored_sections)


# ---------------------------------------------------------------------------
# (4) Per-section entries cover row-bearing and ignored-only sections
# ---------------------------------------------------------------------------


def test_report_sections_include_row_and_ignored_only(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    section_names = {s.section for s in rep.sections}
    # Row-bearing sections must be present.
    for name in (
        "STATUS",
        "CONTROLS",
        "RULES",
        "PATTERNS",
        "ENERGY",
        "EMITTERS",
        "DEMANDS",
        "QUALITY",
        "SOURCES",
        "REACTIONS",
        "MIXING",
    ):
        assert name in section_names, name
    # Layout-only ignored sections must be present too (TITLE / END).
    for name in ("TITLE", "END"):
        assert name in section_names, name


def test_report_section_row_count_matches_diagnostics(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    row_counts = diagnostics.row_count_by_section()
    for entry in rep.sections:
        assert entry.row_count == int(row_counts.get(entry.section, 0))


def test_status_section_marked_row_only_not_ignored(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    status_entry = next(s for s in rep.sections if s.section == "STATUS")
    assert status_entry.row_count == 2
    assert status_entry.ignored_present is False


def test_layout_only_section_marked_ignored_only(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    title_entry = next(s for s in rep.sections if s.section == "TITLE")
    assert title_entry.row_count == 0
    assert title_entry.ignored_present is True


def test_row_bearing_ignored_section_marked_both(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    # CONTROLS has both row diagnostics (2 rows) and ignored-section
    # presence (because [CONTROLS] is a member of IGNORED_SECTIONS).
    controls_entry = next(s for s in rep.sections if s.section == "CONTROLS")
    assert controls_entry.row_count == 2
    assert controls_entry.ignored_present is True


# ---------------------------------------------------------------------------
# (5) No double counting
# ---------------------------------------------------------------------------


def test_total_diagnostic_rows_does_not_include_ignored_presence(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    # row_count_by_section is row-channel only — ignored-section presence
    # contributes only to ignored_section_count / ignored_present.
    assert rep.total_diagnostic_rows == sum(rep.row_count_by_section.values())
    # No SECTION entry contributes to both row_count and ignored_present
    # in a way that inflates total_diagnostic_rows.
    summed = 0
    for entry in rep.sections:
        summed += entry.row_count
    assert summed == rep.total_diagnostic_rows


def test_each_section_appears_at_most_once(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    names = [s.section for s in rep.sections]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# (6) Sprint 32 edge surrogate records flow through
# ---------------------------------------------------------------------------


def test_report_surfaces_edge_surrogates(tmp_path: Path) -> None:
    path = _write(tmp_path, "valves.inp", _valves_inp())
    network, diagnostics = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    rep = build_import_quality_report(diagnostics, network)

    kinds = [s.surrogate_kind for s in rep.surrogates]
    # PRV and TCV both present, exactly once each.
    assert kinds.count(EDGE_SURROGATE_KIND_PRV_FIXED_HEAD) == 1
    assert kinds.count(EDGE_SURROGATE_KIND_TCV_MINOR_LOSS) == 1


def test_surrogate_fields_match_source_diagnostic(tmp_path: Path) -> None:
    path = _write(tmp_path, "valves.inp", _valves_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    assert len(rep.surrogates) == len(diagnostics.edge_surrogates)
    for source, mirrored in zip(diagnostics.edge_surrogates, rep.surrogates):
        assert source.edge_index == mirrored.edge_index
        assert source.link_id == mirrored.link_id
        assert source.link_type == mirrored.link_type
        assert source.surrogate_kind == mirrored.surrogate_kind
        assert source.severity == mirrored.severity
        assert source.message == mirrored.message
        assert tuple(source.limitations) == mirrored.limitations


# ---------------------------------------------------------------------------
# (7) surrogate_count_by_kind mirrors the helper
# ---------------------------------------------------------------------------


def test_report_surrogate_count_by_kind_matches_helper(tmp_path: Path) -> None:
    path = _write(tmp_path, "valves.inp", _valves_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    assert rep.surrogate_count_by_kind == diagnostics.surrogate_count_by_kind()


def test_report_surrogate_count_by_kind_is_fresh_dict() -> None:
    diagnostics = EpanetImportDiagnostics(
        edge_surrogates=(
            EpanetEdgeSurrogateDiagnostic(
                edge_index=0,
                link_id="V1",
                link_type="VALVE",
                surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
                severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
                message="msg",
                limitations=("only one",),
            ),
        )
    )
    rep_a = build_import_quality_report(diagnostics)
    rep_b = build_import_quality_report(diagnostics)
    # Two builder calls return equal-but-not-identical mappings.
    assert rep_a.surrogate_count_by_kind == rep_b.surrogate_count_by_kind
    assert rep_a.surrogate_count_by_kind is not rep_b.surrogate_count_by_kind


# ---------------------------------------------------------------------------
# (8) Network-supplied validation: out-of-range surrogate index warns
# ---------------------------------------------------------------------------


def _make_tiny_network() -> Network:
    """Build a 2-node, 1-pipe Network so edge_count == 1."""
    return Network(
        edge_index=torch.tensor([[0], [1]], dtype=torch.long),
        num_nodes=2,
        pipe_mask=torch.tensor([True], dtype=torch.bool),
        pump_mask=torch.tensor([False], dtype=torch.bool),
        lengths=torch.tensor([100.0]),
        diameters=torch.tensor([0.2]),
        c_factors=torch.tensor([130.0]),
        pump_coeffs=torch.tensor([[0.0, 0.0, 0.0]]),
        pump_speeds=torch.tensor([0.0]),
        demands=torch.tensor([0.0, 0.0]),
        fixed_head_mask=torch.tensor([False, True]),
        fixed_head_values=torch.tensor([0.0, 50.0]),
    )


def test_network_supplied_warns_on_out_of_range_surrogate_index() -> None:
    network = _make_tiny_network()
    diagnostics = EpanetImportDiagnostics(
        edge_surrogates=(
            EpanetEdgeSurrogateDiagnostic(
                edge_index=42,  # out of range
                link_id="V_PHANTOM",
                link_type="VALVE",
                surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
                severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
                message="msg",
                limitations=(),
            ),
        )
    )
    rep = build_import_quality_report(diagnostics, network)

    # Warning surfaced, no exception raised, surrogate record preserved.
    assert any("edge_index=42" in w for w in rep.warnings)
    assert any("edges 1" in w or "only 1 edges" in w for w in rep.warnings)
    assert len(rep.surrogates) == 1
    assert rep.surrogates[0].edge_index == 42


def test_network_supplied_does_not_warn_when_index_in_range() -> None:
    network = _make_tiny_network()
    diagnostics = EpanetImportDiagnostics(
        edge_surrogates=(
            EpanetEdgeSurrogateDiagnostic(
                edge_index=0,  # in range for a 1-edge network
                link_id="V_OK",
                link_type="VALVE",
                surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
                severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
                message="msg",
                limitations=(),
            ),
        )
    )
    rep = build_import_quality_report(diagnostics, network)
    assert rep.warnings == ()


def test_no_network_skips_edge_index_validation() -> None:
    diagnostics = EpanetImportDiagnostics(
        edge_surrogates=(
            EpanetEdgeSurrogateDiagnostic(
                edge_index=999,
                link_id="V1",
                link_type="VALVE",
                surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
                severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
                message="msg",
                limitations=(),
            ),
        )
    )
    rep = build_import_quality_report(diagnostics, network=None)
    # No warning emitted because we cannot validate without a network.
    assert rep.warnings == ()
    assert rep.surrogates[0].edge_index == 999


# ---------------------------------------------------------------------------
# (9) Read-only / deterministic — building twice yields equal reports
# ---------------------------------------------------------------------------


def test_builder_is_deterministic_across_calls(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")

    rep_a = build_import_quality_report(diagnostics)
    rep_b = build_import_quality_report(diagnostics)

    assert rep_a == rep_b
    assert rep_a.row_count_by_section == rep_b.row_count_by_section
    assert rep_a.warnings == rep_b.warnings
    assert rep_a.limitations == rep_b.limitations


def test_builder_does_not_mutate_diagnostics(tmp_path: Path) -> None:
    path = _write(tmp_path, "all_channels.inp", _all_channels_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")

    snapshot = (
        tuple(diagnostics.status_rows),
        tuple(diagnostics.ignored_sections),
        tuple(diagnostics.control_rule_rows),
        tuple(diagnostics.pattern_energy_rows),
        tuple(diagnostics.emitter_demand_rows),
        tuple(diagnostics.water_quality_rows),
        tuple(diagnostics.edge_surrogates),
    )
    _ = build_import_quality_report(diagnostics)
    after = (
        tuple(diagnostics.status_rows),
        tuple(diagnostics.ignored_sections),
        tuple(diagnostics.control_rule_rows),
        tuple(diagnostics.pattern_energy_rows),
        tuple(diagnostics.emitter_demand_rows),
        tuple(diagnostics.water_quality_rows),
        tuple(diagnostics.edge_surrogates),
    )
    assert snapshot == after


def test_builder_does_not_mutate_network(tmp_path: Path) -> None:
    path = _write(tmp_path, "valves.inp", _valves_inp())
    network, diagnostics = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )

    edge_index_before = network.edge_index.clone()
    diameters_before = network.diameters.clone()
    _ = build_import_quality_report(diagnostics, network)
    assert torch.equal(network.edge_index, edge_index_before)
    assert torch.equal(network.diameters, diameters_before)


# ---------------------------------------------------------------------------
# (10) Convenience loader agrees with explicit load + builder
# ---------------------------------------------------------------------------


def test_load_inp_import_quality_report_matches_explicit_path(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "valves.inp", _valves_inp())
    explicit_net, explicit_diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    explicit_rep = build_import_quality_report(
        explicit_diag, explicit_net, parser="fallback"
    )
    loader_rep = load_inp_import_quality_report(path, parser="fallback")
    assert loader_rep == explicit_rep


def test_load_inp_import_quality_report_rejects_auto_parser(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "valves.inp", _valves_inp())
    with pytest.raises(ValueError):
        load_inp_import_quality_report(path, parser="auto")


# ---------------------------------------------------------------------------
# (11) Default load_network_from_inp(path) still returns only the Network
# ---------------------------------------------------------------------------


def test_default_load_network_from_inp_unchanged(tmp_path: Path) -> None:
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    result = load_network_from_inp(path, parser="fallback")
    assert isinstance(result, Network)


# ---------------------------------------------------------------------------
# Misc: parser kwarg validation & propagation
# ---------------------------------------------------------------------------


def test_builder_rejects_unknown_parser() -> None:
    diagnostics = EpanetImportDiagnostics()
    with pytest.raises(ValueError):
        build_import_quality_report(diagnostics, parser="bogus")


def test_builder_records_parser_value() -> None:
    diagnostics = EpanetImportDiagnostics()
    rep = build_import_quality_report(diagnostics, parser="fallback")
    assert rep.parser == "fallback"


# ---------------------------------------------------------------------------
# Misc: surrogate limitations propagate (deduplicated) into report.limitations
# ---------------------------------------------------------------------------


def test_surrogate_limitations_flow_into_report_limitations(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "valves.inp", _valves_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")
    rep = build_import_quality_report(diagnostics)

    surrogate_lims: list[str] = []
    seen: set[str] = set()
    for rec in diagnostics.edge_surrogates:
        for lim in rec.limitations:
            if lim in seen:
                continue
            seen.add(lim)
            surrogate_lims.append(lim)
    for lim in surrogate_lims:
        assert lim in rep.limitations


def test_report_limitations_dedupe_across_surrogates() -> None:
    repeated = (
        EpanetEdgeSurrogateDiagnostic(
            edge_index=0,
            link_id="V1",
            link_type="VALVE",
            surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
            severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
            message="msg",
            limitations=("dup",),
        ),
        EpanetEdgeSurrogateDiagnostic(
            edge_index=1,
            link_id="V2",
            link_type="VALVE",
            surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
            severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
            message="msg",
            limitations=("dup",),
        ),
    )
    diagnostics = EpanetImportDiagnostics(edge_surrogates=repeated)
    rep = build_import_quality_report(diagnostics)
    assert rep.limitations.count("dup") == 1


# ---------------------------------------------------------------------------
# (12) WNTR optional test — empty / minimal report with documented asymmetry
# ---------------------------------------------------------------------------


def test_wntr_diagnostics_produce_empty_report_with_asymmetry_limitation(
    tmp_path: Path,
) -> None:
    pytest.importorskip("wntr")
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    network, diagnostics = load_network_from_inp(
        path, parser="wntr", return_diagnostics=True
    )
    rep = build_import_quality_report(diagnostics, network, parser="wntr")
    assert rep.parser == "wntr"
    assert rep.total_diagnostic_rows == 0
    assert rep.ignored_section_count == 0
    assert rep.sections == ()
    assert rep.surrogates == ()
    # The asymmetry warning fires only when every channel is empty (WNTR
    # contract). And the asymmetry limitation must be present in either
    # case.
    assert any("wntr" in w.lower() for w in rep.warnings)
    assert any("wntr" in lim.lower() for lim in rep.limitations)


def test_wntr_loader_matches_explicit_path(tmp_path: Path) -> None:
    pytest.importorskip("wntr")
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    explicit_net, explicit_diag = load_network_from_inp(
        path, parser="wntr", return_diagnostics=True
    )
    explicit_rep = build_import_quality_report(
        explicit_diag, explicit_net, parser="wntr"
    )
    loader_rep = load_inp_import_quality_report(path, parser="wntr")
    assert loader_rep == explicit_rep


# ---------------------------------------------------------------------------
# (13) Sprint 23-32 helpers still function alongside the new builder
# ---------------------------------------------------------------------------


def test_sprint_30_31_32_helpers_still_work_after_build(tmp_path: Path) -> None:
    path = _write(tmp_path, "valves.inp", _valves_inp())
    diagnostics = load_inp_diagnostics(path, parser="fallback")

    _ = build_import_quality_report(diagnostics)

    # Sprint 30: row_count_by_section / summary / ignored_section_names.
    counts = diagnostics.row_count_by_section()
    assert isinstance(counts, dict)
    summary = diagnostics.summary()
    assert summary.total_diagnostic_rows == sum(counts.values())
    assert diagnostics.ignored_section_names() == tuple(
        r.section for r in diagnostics.ignored_sections
    )
    # Sprint 31: rows_for_section.
    assert diagnostics.rows_for_section("STATUS") == diagnostics.status_rows
    # Sprint 32: surrogate accessors.
    assert diagnostics.surrogate_edges() == diagnostics.edge_surrogates
    assert isinstance(diagnostics.surrogate_count_by_kind(), dict)
