"""Sprint 30 — EPANET ``.inp`` diagnostics summary / row-count helpers.

Sprint 23–29 grew :class:`EpanetImportDiagnostics` into a multi-channel
container: ``status_rows``, ``ignored_sections``, ``control_rule_rows``,
``pattern_energy_rows``, ``emitter_demand_rows``, and
``water_quality_rows``. Sprint 30 adds a thin, read-only ergonomics
layer on top of that container: a deterministic per-section row-count
view, a typed summary dataclass, and an ignored-section presence
helper. The layer adds no new EPANET semantics, never mutates the
container, and is hydraulically inert.

Contract:

* ``EpanetImportDiagnostics.row_count_by_section()`` returns a fresh
  ``dict[str, int]`` mapping canonical EPANET section names to row
  counts derived from the *row* diagnostic channels only:
  ``status_rows`` → ``"STATUS"``, ``control_rule_rows`` →
  ``"CONTROLS"`` / ``"RULES"``, ``pattern_energy_rows`` →
  ``"PATTERNS"`` / ``"ENERGY"``, ``emitter_demand_rows`` →
  ``"EMITTERS"`` / ``"DEMANDS"``, and ``water_quality_rows`` →
  ``"QUALITY"`` / ``"SOURCES"`` / ``"REACTIONS"`` / ``"MIXING"``.
* ``ignored_sections`` is **not** folded into ``row_count_by_section``:
  ignored-section *presence* is exposed separately through
  ``ignored_section_names()``. This keeps row-counts unambiguous and
  prevents double-counting (a file with ``[CONTROLS]`` rows would
  otherwise be counted once in ``control_rule_rows`` and again in
  ``ignored_sections``).
* The dict preserves the canonical ordering
  ``STATUS, CONTROLS, RULES, PATTERNS, ENERGY, EMITTERS, DEMANDS,
  QUALITY, SOURCES, REACTIONS, MIXING`` with any unknown / future
  section appended in alphabetical order. Sections with zero rows are
  omitted from the dict.
* Each call returns a fresh ``dict``; mutating the returned dict has
  no effect on the diagnostics container or on subsequent calls.
* ``EpanetImportDiagnostics.ignored_section_names()`` returns a tuple
  of canonical section names from ``ignored_sections``, preserving
  source-file order, deterministically.
* ``EpanetImportDiagnostics.summary()`` returns a frozen
  :class:`EpanetImportDiagnosticsSummary` with per-channel counts,
  total row count, ignored-section count, and a fresh row-count dict.
* All helpers are read-only and never mutate the diagnostics object.
* WNTR-parsed diagnostics return empty / zero values from all helpers
  (the WNTR adapter does not emit diagnostics).
* ``load_inp_diagnostics(...)`` and
  ``load_network_from_inp(..., return_diagnostics=True)`` produce
  identical summary / count helpers.
* Default ``load_network_from_inp(path)`` continues to return only
  the :class:`Network`.
* The Sprint 22/23 ``[STATUS]`` rejection contract is preserved.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from aquaoptima.dphm import (
    EpanetControlRuleDiagnostic,
    EpanetEmitterDemandDiagnostic,
    EpanetIgnoredSectionDiagnostic,
    EpanetImportDiagnostics,
    EpanetPatternEnergyDiagnostic,
    EpanetStatusDiagnostic,
    EpanetWaterQualityDiagnostic,
    Network,
    load_inp_diagnostics,
    load_network_from_inp,
)
from aquaoptima.dphm.inp_io import (
    EpanetImportDiagnosticsSummary,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _baseline_inp(extra: str = "") -> str:
    """A small loop fixture; ``extra`` is injected just before ``[END]``."""
    return (
        "[TITLE]\n"
        "Sprint 30 diagnostics summary fixture\n"
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
    """Fixture exercising every Sprint 23–29 diagnostic channel."""
    extra = (
        "[STATUS]\n"
        " P1 OPEN\n"
        " P2 OPEN\n"
        "[CONTROLS]\n"
        " LINK P1 OPEN IF NODE J1 BELOW 5\n"
        " LINK P2 CLOSED IF NODE J1 ABOVE 30\n"
        " LINK P3 OPEN IF NODE J2 BELOW 5\n"
        "[RULES]\n"
        " RULE R1\n"
        " IF NODE J1 BELOW 5\n"
        " THEN LINK P1 OPEN\n"
        "[PATTERNS]\n"
        " PAT1 1.0 1.1 1.2 1.3\n"
        " PAT1 1.4 1.5 1.6 1.7\n"
        "[ENERGY]\n"
        " GLOBAL PRICE 0.10\n"
        "[EMITTERS]\n"
        " J1 0.5\n"
        " J2 0.75\n"
        "[DEMANDS]\n"
        " J1 1.0 PAT1 cat1\n"
        " J2 0.5 PAT1 cat1\n"
        " J3 0.25 PAT1 cat1\n"
        "[QUALITY]\n"
        " J1 0.5\n"
        "[SOURCES]\n"
        " J1 CONCEN 1.0 PAT1\n"
        " J2 MASS 0.5 PAT1\n"
        "[REACTIONS]\n"
        " ORDER BULK 1\n"
        " GLOBAL BULK -0.5\n"
        "[MIXING]\n"
        " T1 MIXED\n"
    )
    return _baseline_inp(extra)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_summary_dataclass_is_frozen_dataclass() -> None:
    assert dataclasses.is_dataclass(EpanetImportDiagnosticsSummary)
    # Frozen: assignment must raise.
    container = EpanetImportDiagnostics()
    summary = container.summary()
    with pytest.raises(dataclasses.FrozenInstanceError):
        summary.total_diagnostic_rows = 99  # type: ignore[misc]


def test_diagnostics_container_has_row_count_helper() -> None:
    container = EpanetImportDiagnostics()
    assert hasattr(container, "row_count_by_section")
    assert callable(container.row_count_by_section)


def test_diagnostics_container_has_ignored_section_names_helper() -> None:
    container = EpanetImportDiagnostics()
    assert hasattr(container, "ignored_section_names")
    assert callable(container.ignored_section_names)


def test_diagnostics_container_has_summary_helper() -> None:
    container = EpanetImportDiagnostics()
    assert hasattr(container, "summary")
    assert callable(container.summary)


# ---------------------------------------------------------------------------
# Empty container
# ---------------------------------------------------------------------------


def test_empty_row_count_by_section() -> None:
    container = EpanetImportDiagnostics()
    assert container.row_count_by_section() == {}


def test_empty_ignored_section_names() -> None:
    container = EpanetImportDiagnostics()
    assert container.ignored_section_names() == ()


def test_empty_summary_zero_counts() -> None:
    container = EpanetImportDiagnostics()
    summary = container.summary()
    assert summary.total_diagnostic_rows == 0
    assert summary.ignored_section_count == 0
    assert summary.status_row_count == 0
    assert summary.control_rule_row_count == 0
    assert summary.pattern_energy_row_count == 0
    assert summary.emitter_demand_row_count == 0
    assert summary.water_quality_row_count == 0
    assert dict(summary.row_count_by_section) == {}


# ---------------------------------------------------------------------------
# Single-channel counts (direct construction, no parser)
# ---------------------------------------------------------------------------


def test_row_count_status_only() -> None:
    rows = (
        EpanetStatusDiagnostic(link_id="P1", status="OPEN"),
        EpanetStatusDiagnostic(link_id="P2", status="OPEN"),
    )
    container = EpanetImportDiagnostics(status_rows=rows)
    assert container.row_count_by_section() == {"STATUS": 2}


def test_row_count_controls_and_rules() -> None:
    rows = (
        EpanetControlRuleDiagnostic(
            section="CONTROLS",
            row_index=0,
            tokens=("LINK", "P1", "OPEN"),
            text="LINK P1 OPEN",
        ),
        EpanetControlRuleDiagnostic(
            section="CONTROLS",
            row_index=1,
            tokens=("LINK", "P2", "CLOSED"),
            text="LINK P2 CLOSED",
        ),
        EpanetControlRuleDiagnostic(
            section="RULES",
            row_index=0,
            tokens=("RULE", "R1"),
            text="RULE R1",
        ),
    )
    container = EpanetImportDiagnostics(control_rule_rows=rows)
    assert container.row_count_by_section() == {"CONTROLS": 2, "RULES": 1}


def test_row_count_patterns_and_energy() -> None:
    rows = (
        EpanetPatternEnergyDiagnostic(
            section="PATTERNS",
            row_index=0,
            tokens=("PAT1", "1.0"),
            text="PAT1 1.0",
        ),
        EpanetPatternEnergyDiagnostic(
            section="ENERGY",
            row_index=0,
            tokens=("GLOBAL", "PRICE", "0.10"),
            text="GLOBAL PRICE 0.10",
        ),
        EpanetPatternEnergyDiagnostic(
            section="ENERGY",
            row_index=1,
            tokens=("PUMP", "PU1", "PRICE", "0.20"),
            text="PUMP PU1 PRICE 0.20",
        ),
    )
    container = EpanetImportDiagnostics(pattern_energy_rows=rows)
    assert container.row_count_by_section() == {"PATTERNS": 1, "ENERGY": 2}


def test_row_count_emitters_and_demands() -> None:
    rows = (
        EpanetEmitterDemandDiagnostic(
            section="EMITTERS",
            row_index=0,
            tokens=("J1", "0.5"),
            text="J1 0.5",
        ),
        EpanetEmitterDemandDiagnostic(
            section="DEMANDS",
            row_index=0,
            tokens=("J1", "1.0", "PAT1"),
            text="J1 1.0 PAT1",
        ),
        EpanetEmitterDemandDiagnostic(
            section="DEMANDS",
            row_index=1,
            tokens=("J2", "0.5", "PAT1"),
            text="J2 0.5 PAT1",
        ),
    )
    container = EpanetImportDiagnostics(emitter_demand_rows=rows)
    assert container.row_count_by_section() == {"EMITTERS": 1, "DEMANDS": 2}


def test_row_count_water_quality_family() -> None:
    rows = (
        EpanetWaterQualityDiagnostic(
            section="QUALITY",
            row_index=0,
            tokens=("J1", "0.5"),
            text="J1 0.5",
        ),
        EpanetWaterQualityDiagnostic(
            section="SOURCES",
            row_index=0,
            tokens=("J1", "CONCEN", "1.0"),
            text="J1 CONCEN 1.0",
        ),
        EpanetWaterQualityDiagnostic(
            section="REACTIONS",
            row_index=0,
            tokens=("ORDER", "BULK", "1"),
            text="ORDER BULK 1",
        ),
        EpanetWaterQualityDiagnostic(
            section="REACTIONS",
            row_index=1,
            tokens=("GLOBAL", "BULK", "-0.5"),
            text="GLOBAL BULK -0.5",
        ),
        EpanetWaterQualityDiagnostic(
            section="MIXING",
            row_index=0,
            tokens=("T1", "MIXED"),
            text="T1 MIXED",
        ),
    )
    container = EpanetImportDiagnostics(water_quality_rows=rows)
    assert container.row_count_by_section() == {
        "QUALITY": 1,
        "SOURCES": 1,
        "REACTIONS": 2,
        "MIXING": 1,
    }


# ---------------------------------------------------------------------------
# Canonical ordering
# ---------------------------------------------------------------------------


def test_canonical_ordering() -> None:
    """The dict preserves canonical EPANET section order even when channels
    are constructed in a non-canonical order.
    """
    container = EpanetImportDiagnostics(
        water_quality_rows=(
            EpanetWaterQualityDiagnostic(
                section="MIXING", row_index=0, tokens=("T1", "MIXED"), text="T1 MIXED"
            ),
            EpanetWaterQualityDiagnostic(
                section="QUALITY", row_index=0, tokens=("J1", "0.5"), text="J1 0.5"
            ),
            EpanetWaterQualityDiagnostic(
                section="REACTIONS",
                row_index=0,
                tokens=("ORDER", "BULK", "1"),
                text="ORDER BULK 1",
            ),
            EpanetWaterQualityDiagnostic(
                section="SOURCES",
                row_index=0,
                tokens=("J1", "CONCEN", "1.0"),
                text="J1 CONCEN 1.0",
            ),
        ),
        emitter_demand_rows=(
            EpanetEmitterDemandDiagnostic(
                section="DEMANDS", row_index=0, tokens=("J1", "1.0"), text="J1 1.0"
            ),
            EpanetEmitterDemandDiagnostic(
                section="EMITTERS", row_index=0, tokens=("J1", "0.5"), text="J1 0.5"
            ),
        ),
        pattern_energy_rows=(
            EpanetPatternEnergyDiagnostic(
                section="ENERGY",
                row_index=0,
                tokens=("GLOBAL", "PRICE", "0.10"),
                text="GLOBAL PRICE 0.10",
            ),
            EpanetPatternEnergyDiagnostic(
                section="PATTERNS",
                row_index=0,
                tokens=("PAT1", "1.0"),
                text="PAT1 1.0",
            ),
        ),
        control_rule_rows=(
            EpanetControlRuleDiagnostic(
                section="RULES", row_index=0, tokens=("RULE", "R1"), text="RULE R1"
            ),
            EpanetControlRuleDiagnostic(
                section="CONTROLS",
                row_index=0,
                tokens=("LINK", "P1", "OPEN"),
                text="LINK P1 OPEN",
            ),
        ),
        status_rows=(EpanetStatusDiagnostic(link_id="P1", status="OPEN"),),
    )
    keys = list(container.row_count_by_section().keys())
    assert keys == [
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
    ]


def test_unknown_sections_sorted_alphabetically_after_canonical() -> None:
    """Hypothetical future / unknown section names sort alphabetically
    after the canonical block. Constructed via direct dataclass to keep
    the test parser-agnostic.
    """
    rows = (
        EpanetWaterQualityDiagnostic(
            section="ZULU", row_index=0, tokens=("Z",), text="Z"
        ),
        EpanetWaterQualityDiagnostic(
            section="ALPHA", row_index=0, tokens=("A",), text="A"
        ),
        EpanetWaterQualityDiagnostic(
            section="QUALITY", row_index=0, tokens=("J1", "0.5"), text="J1 0.5"
        ),
    )
    container = EpanetImportDiagnostics(water_quality_rows=rows)
    keys = list(container.row_count_by_section().keys())
    # Canonical first, then unknowns alphabetically.
    assert keys == ["QUALITY", "ALPHA", "ZULU"]


# ---------------------------------------------------------------------------
# Freshness / immutability of returned dict
# ---------------------------------------------------------------------------


def test_returned_dict_is_fresh_each_call() -> None:
    container = EpanetImportDiagnostics(
        status_rows=(EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    )
    first = container.row_count_by_section()
    second = container.row_count_by_section()
    assert first is not second
    assert first == second


def test_mutating_returned_dict_does_not_affect_diagnostics() -> None:
    container = EpanetImportDiagnostics(
        status_rows=(EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    )
    counts = container.row_count_by_section()
    counts["STATUS"] = 999
    counts["FAKE"] = 1
    fresh = container.row_count_by_section()
    assert fresh == {"STATUS": 1}
    # And the underlying tuple was not mutated.
    assert len(container.status_rows) == 1


def test_summary_row_count_dict_is_fresh() -> None:
    container = EpanetImportDiagnostics(
        status_rows=(EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    )
    s1 = container.summary()
    s2 = container.summary()
    # Each call returns a fresh dict.
    assert s1.row_count_by_section is not s2.row_count_by_section
    assert dict(s1.row_count_by_section) == dict(s2.row_count_by_section)


# ---------------------------------------------------------------------------
# Ignored-section presence helper
# ---------------------------------------------------------------------------


def test_ignored_section_names_returns_tuple() -> None:
    container = EpanetImportDiagnostics(
        ignored_sections=(
            EpanetIgnoredSectionDiagnostic(section="TITLE", row_count=1),
            EpanetIgnoredSectionDiagnostic(section="REPORT", row_count=0),
        )
    )
    names = container.ignored_section_names()
    assert isinstance(names, tuple)
    assert names == ("TITLE", "REPORT")


def test_ignored_section_names_preserves_source_order() -> None:
    container = EpanetImportDiagnostics(
        ignored_sections=(
            EpanetIgnoredSectionDiagnostic(section="REPORT", row_count=0),
            EpanetIgnoredSectionDiagnostic(section="TITLE", row_count=1),
            EpanetIgnoredSectionDiagnostic(section="PATTERNS", row_count=2),
        )
    )
    assert container.ignored_section_names() == ("REPORT", "TITLE", "PATTERNS")


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------


def test_summary_field_counts_match_methods() -> None:
    container = EpanetImportDiagnostics(
        status_rows=(EpanetStatusDiagnostic(link_id="P1", status="OPEN"),),
        ignored_sections=(
            EpanetIgnoredSectionDiagnostic(section="TITLE", row_count=1),
            EpanetIgnoredSectionDiagnostic(section="REPORT", row_count=0),
        ),
        control_rule_rows=(
            EpanetControlRuleDiagnostic(
                section="CONTROLS",
                row_index=0,
                tokens=("LINK", "P1", "OPEN"),
                text="LINK P1 OPEN",
            ),
            EpanetControlRuleDiagnostic(
                section="RULES", row_index=0, tokens=("RULE", "R1"), text="RULE R1"
            ),
        ),
        pattern_energy_rows=(
            EpanetPatternEnergyDiagnostic(
                section="PATTERNS",
                row_index=0,
                tokens=("PAT1", "1.0"),
                text="PAT1 1.0",
            ),
        ),
        emitter_demand_rows=(
            EpanetEmitterDemandDiagnostic(
                section="EMITTERS", row_index=0, tokens=("J1", "0.5"), text="J1 0.5"
            ),
            EpanetEmitterDemandDiagnostic(
                section="DEMANDS", row_index=0, tokens=("J1", "1.0"), text="J1 1.0"
            ),
        ),
        water_quality_rows=(
            EpanetWaterQualityDiagnostic(
                section="QUALITY", row_index=0, tokens=("J1", "0.5"), text="J1 0.5"
            ),
            EpanetWaterQualityDiagnostic(
                section="MIXING", row_index=0, tokens=("T1", "MIXED"), text="T1 MIXED"
            ),
        ),
    )
    summary = container.summary()
    assert summary.status_row_count == 1
    assert summary.control_rule_row_count == 2
    assert summary.pattern_energy_row_count == 1
    assert summary.emitter_demand_row_count == 2
    assert summary.water_quality_row_count == 2
    assert summary.ignored_section_count == 2
    assert summary.total_diagnostic_rows == 1 + 2 + 1 + 2 + 2
    assert dict(summary.row_count_by_section) == container.row_count_by_section()


# ---------------------------------------------------------------------------
# No double-counting between row diagnostics and ignored-section presence
# ---------------------------------------------------------------------------


def test_no_double_counting_between_channels_and_ignored_sections() -> None:
    """A file with both ``ignored_sections=[CONTROLS]`` and
    ``control_rule_rows`` must not double-count: row counts come from row
    channels only; presence comes from ``ignored_section_names``.
    """
    container = EpanetImportDiagnostics(
        ignored_sections=(
            EpanetIgnoredSectionDiagnostic(section="CONTROLS", row_count=3),
            EpanetIgnoredSectionDiagnostic(section="PATTERNS", row_count=1),
        ),
        control_rule_rows=(
            EpanetControlRuleDiagnostic(
                section="CONTROLS",
                row_index=0,
                tokens=("LINK", "P1", "OPEN"),
                text="LINK P1 OPEN",
            ),
            EpanetControlRuleDiagnostic(
                section="CONTROLS",
                row_index=1,
                tokens=("LINK", "P2", "CLOSED"),
                text="LINK P2 CLOSED",
            ),
            EpanetControlRuleDiagnostic(
                section="CONTROLS",
                row_index=2,
                tokens=("LINK", "P3", "OPEN"),
                text="LINK P3 OPEN",
            ),
        ),
        pattern_energy_rows=(
            EpanetPatternEnergyDiagnostic(
                section="PATTERNS",
                row_index=0,
                tokens=("PAT1", "1.0"),
                text="PAT1 1.0",
            ),
        ),
    )
    counts = container.row_count_by_section()
    # Each section appears exactly once with the row-channel count.
    assert counts == {"CONTROLS": 3, "PATTERNS": 1}
    # And ignored-section presence is a separate surface.
    assert container.ignored_section_names() == ("CONTROLS", "PATTERNS")


# ---------------------------------------------------------------------------
# Read-only / no mutation
# ---------------------------------------------------------------------------


def test_helpers_do_not_mutate_container() -> None:
    rows = (
        EpanetStatusDiagnostic(link_id="P1", status="OPEN"),
        EpanetStatusDiagnostic(link_id="P2", status="OPEN"),
    )
    ignored = (
        EpanetIgnoredSectionDiagnostic(section="TITLE", row_count=1),
    )
    container = EpanetImportDiagnostics(
        status_rows=rows,
        ignored_sections=ignored,
    )
    # Invoke every helper.
    _ = container.row_count_by_section()
    _ = container.ignored_section_names()
    _ = container.summary()
    # Tuples are unchanged identities.
    assert container.status_rows is rows
    assert container.ignored_sections is ignored


# ---------------------------------------------------------------------------
# Parser integration (fallback parser is authoritative for diagnostics)
# ---------------------------------------------------------------------------


def test_parser_emits_expected_counts_for_all_channels(tmp_path: Path) -> None:
    path = _write(tmp_path, "all.inp", _all_channels_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    counts = diag.row_count_by_section()
    assert counts == {
        "STATUS": 2,
        "CONTROLS": 3,
        "RULES": 3,
        "PATTERNS": 2,
        "ENERGY": 1,
        "EMITTERS": 2,
        "DEMANDS": 3,
        "QUALITY": 1,
        "SOURCES": 2,
        "REACTIONS": 2,
        "MIXING": 1,
    }


def test_parser_summary_matches_row_count_by_section(tmp_path: Path) -> None:
    path = _write(tmp_path, "all.inp", _all_channels_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    summary = diag.summary()
    assert dict(summary.row_count_by_section) == diag.row_count_by_section()
    assert summary.status_row_count == len(diag.status_rows)
    assert summary.control_rule_row_count == len(diag.control_rule_rows)
    assert summary.pattern_energy_row_count == len(diag.pattern_energy_rows)
    assert summary.emitter_demand_row_count == len(diag.emitter_demand_rows)
    assert summary.water_quality_row_count == len(diag.water_quality_rows)
    assert summary.ignored_section_count == len(diag.ignored_sections)
    assert summary.total_diagnostic_rows == (
        summary.status_row_count
        + summary.control_rule_row_count
        + summary.pattern_energy_row_count
        + summary.emitter_demand_row_count
        + summary.water_quality_row_count
    )


def test_load_network_from_inp_with_return_diagnostics_matches_summary(
    tmp_path: Path,
) -> None:
    """The summary obtained via ``load_network_from_inp`` matches the
    summary obtained via ``load_inp_diagnostics`` on the same file.
    """
    path = _write(tmp_path, "all.inp", _all_channels_inp())
    _, diag_a = load_network_from_inp(path, parser="fallback", return_diagnostics=True)
    diag_b = load_inp_diagnostics(path, parser="fallback")
    assert diag_a.row_count_by_section() == diag_b.row_count_by_section()
    assert diag_a.ignored_section_names() == diag_b.ignored_section_names()
    summary_a = diag_a.summary()
    summary_b = diag_b.summary()
    assert summary_a == summary_b
    assert dataclasses.asdict(summary_a) == dataclasses.asdict(summary_b)


def test_load_network_from_inp_default_remains_network_only(tmp_path: Path) -> None:
    path = _write(tmp_path, "all.inp", _all_channels_inp())
    result = load_network_from_inp(path, parser="fallback")
    assert isinstance(result, Network)


def test_parser_empty_fixture_summary_is_zero(tmp_path: Path) -> None:
    """Baseline fixture (no diagnostic-row sections) produces empty row
    counts. ``[TITLE]`` / ``[END]`` are members of ``IGNORED_SECTIONS``
    and still surface through the ignored-section presence channel —
    Sprint 30 row counts and ignored-section names are deliberately
    independent surfaces, so the row-count dict stays empty while
    ignored-section names lists TITLE/END.
    """
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.row_count_by_section() == {}
    # Baseline declares [TITLE] and [END]; both are IGNORED_SECTIONS.
    ignored = diag.ignored_section_names()
    assert "TITLE" in ignored
    assert "END" in ignored
    summary = diag.summary()
    # No row channels populated.
    assert summary.total_diagnostic_rows == 0
    assert summary.status_row_count == 0
    assert summary.control_rule_row_count == 0
    assert summary.pattern_energy_row_count == 0
    assert summary.emitter_demand_row_count == 0
    assert summary.water_quality_row_count == 0
    # Ignored-section presence is the separate channel.
    assert summary.ignored_section_count == len(ignored)


# ---------------------------------------------------------------------------
# WNTR parser asymmetry
# ---------------------------------------------------------------------------


def test_wntr_diagnostics_summary_is_empty(tmp_path: Path) -> None:
    """The WNTR adapter does not emit diagnostics — every helper returns
    the empty / zero value, mirroring Sprints 23–29 asymmetry.

    Uses a WNTR-parseable fixture with a representative slice of
    diagnostic-bearing sections (``[STATUS]``, ``[PATTERNS]``,
    ``[QUALITY]``, ``[SOURCES]``). The bogus ``[RULES]`` /
    ``[CONTROLS]`` syntax in :func:`_all_channels_inp` is fallback-
    parser-friendly but not WNTR-friendly, so the WNTR asymmetry test
    deliberately exercises a narrower fixture WNTR can ingest.
    """
    pytest.importorskip("wntr")
    extra = (
        "[STATUS]\n"
        " P1 OPEN\n"
        "[PATTERNS]\n"
        " PAT1 1.0 1.1 1.2 1.3\n"
        "[QUALITY]\n"
        " J1 0.5\n"
        "[SOURCES]\n"
        " J1 CONCEN 1.0\n"
    )
    path = _write(tmp_path, "wntr_friendly.inp", _baseline_inp(extra))
    diag = load_inp_diagnostics(path, parser="wntr")
    assert diag.row_count_by_section() == {}
    assert diag.ignored_section_names() == ()
    summary = diag.summary()
    assert summary.total_diagnostic_rows == 0
    assert summary.ignored_section_count == 0
    assert summary.status_row_count == 0
    assert summary.control_rule_row_count == 0
    assert summary.pattern_energy_row_count == 0
    assert summary.emitter_demand_row_count == 0
    assert summary.water_quality_row_count == 0


# ---------------------------------------------------------------------------
# Backwards-compatible — Sprint 22/23 [STATUS] rejection still raises
# ---------------------------------------------------------------------------


def test_status_rejection_still_raises(tmp_path: Path) -> None:
    """Sprint 22 ``[STATUS] CLOSED`` rejection must still raise, and no
    partial diagnostics / summary may leak out of the error.
    """
    text = _baseline_inp("[STATUS]\n P1 CLOSED\n")
    path = _write(tmp_path, "bad_status.inp", text)
    with pytest.raises(ValueError):
        load_inp_diagnostics(path, parser="fallback")
