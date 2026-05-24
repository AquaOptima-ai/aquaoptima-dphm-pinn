"""Sprint 31 — EPANET ``.inp`` diagnostics ``rows_for_section`` accessor.

Sprint 23–30 grew :class:`EpanetImportDiagnostics` into a multi-channel
container plus a thin read-only summary/count ergonomics layer. Sprint 31
adds a section-keyed retrieval accessor on top of that container:

* ``EpanetImportDiagnostics.rows_for_section(name)`` returns a tuple of
  diagnostic records emitted from the requested EPANET section, looked
  up case-insensitively after trimming whitespace and EPANET bracket
  notation (``"[STATUS]"`` works identically to ``"status"``).
* The accessor reads only the row diagnostic channels — ``status_rows``,
  ``control_rule_rows``, ``pattern_energy_rows``, ``emitter_demand_rows``,
  and ``water_quality_rows``. ``ignored_sections`` is **not** folded in:
  it is a presence channel, surfaced separately through
  :meth:`ignored_section_names`.
* Unknown section names, empty strings, and whitespace-only strings
  return ``()`` for UI-lookup ergonomics (no exception).
* Row order is preserved from the underlying channel (which itself
  preserves source-file order).
* The return value is a :class:`tuple`; mutating it externally is
  impossible and does not affect the diagnostics container.
* The accessor never mutates the container, never activates EPANET
  semantics, and is hydraulically inert.
* WNTR-parsed diagnostics return ``()`` for every section (the WNTR
  adapter does not emit row diagnostics).
* ``load_inp_diagnostics(...)`` and
  ``load_network_from_inp(..., return_diagnostics=True)`` agree
  exactly on ``rows_for_section`` results.
* Default ``load_network_from_inp(path)`` keeps returning only the
  :class:`Network` (Sprint 11 contract is preserved).
* The Sprint 22/23 ``[STATUS]`` rejection contract is preserved.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import torch

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


# ---------------------------------------------------------------------------
# Fixture helpers (shared shape with test_inp_diagnostics_summary)
# ---------------------------------------------------------------------------


def _baseline_inp(extra: str = "") -> str:
    return (
        "[TITLE]\n"
        "Sprint 31 rows_for_section fixture\n"
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
# API existence
# ---------------------------------------------------------------------------


def test_rows_for_section_exists_and_is_callable() -> None:
    container = EpanetImportDiagnostics()
    assert hasattr(container, "rows_for_section")
    assert callable(container.rows_for_section)


def test_rows_for_section_empty_container_returns_empty_tuple() -> None:
    container = EpanetImportDiagnostics()
    assert container.rows_for_section("STATUS") == ()
    assert container.rows_for_section("CONTROLS") == ()
    assert container.rows_for_section("QUALITY") == ()


# ---------------------------------------------------------------------------
# Each row channel resolves to its records (direct construction)
# ---------------------------------------------------------------------------


def test_status_rows_for_section() -> None:
    rows = (
        EpanetStatusDiagnostic(link_id="P1", status="OPEN"),
        EpanetStatusDiagnostic(link_id="P2", status="OPEN"),
    )
    container = EpanetImportDiagnostics(status_rows=rows)
    assert container.rows_for_section("STATUS") == rows


def test_controls_rows_filtered_from_control_rule_channel() -> None:
    c1 = EpanetControlRuleDiagnostic(
        section="CONTROLS",
        row_index=0,
        tokens=("LINK", "P1", "OPEN"),
        text="LINK P1 OPEN",
    )
    c2 = EpanetControlRuleDiagnostic(
        section="CONTROLS",
        row_index=1,
        tokens=("LINK", "P2", "CLOSED"),
        text="LINK P2 CLOSED",
    )
    r1 = EpanetControlRuleDiagnostic(
        section="RULES",
        row_index=0,
        tokens=("RULE", "R1"),
        text="RULE R1",
    )
    container = EpanetImportDiagnostics(control_rule_rows=(c1, c2, r1))
    assert container.rows_for_section("CONTROLS") == (c1, c2)
    assert container.rows_for_section("RULES") == (r1,)


def test_patterns_rows_filtered_from_pattern_energy_channel() -> None:
    p1 = EpanetPatternEnergyDiagnostic(
        section="PATTERNS", row_index=0, tokens=("PAT1", "1.0"), text="PAT1 1.0"
    )
    e1 = EpanetPatternEnergyDiagnostic(
        section="ENERGY",
        row_index=0,
        tokens=("GLOBAL", "PRICE", "0.10"),
        text="GLOBAL PRICE 0.10",
    )
    e2 = EpanetPatternEnergyDiagnostic(
        section="ENERGY",
        row_index=1,
        tokens=("PUMP", "PU1", "PRICE", "0.20"),
        text="PUMP PU1 PRICE 0.20",
    )
    container = EpanetImportDiagnostics(pattern_energy_rows=(p1, e1, e2))
    assert container.rows_for_section("PATTERNS") == (p1,)
    assert container.rows_for_section("ENERGY") == (e1, e2)


def test_emitters_and_demands_filtered_from_emitter_demand_channel() -> None:
    em1 = EpanetEmitterDemandDiagnostic(
        section="EMITTERS", row_index=0, tokens=("J1", "0.5"), text="J1 0.5"
    )
    d1 = EpanetEmitterDemandDiagnostic(
        section="DEMANDS", row_index=0, tokens=("J1", "1.0"), text="J1 1.0"
    )
    d2 = EpanetEmitterDemandDiagnostic(
        section="DEMANDS", row_index=1, tokens=("J2", "0.5"), text="J2 0.5"
    )
    container = EpanetImportDiagnostics(emitter_demand_rows=(em1, d1, d2))
    assert container.rows_for_section("EMITTERS") == (em1,)
    assert container.rows_for_section("DEMANDS") == (d1, d2)


def test_water_quality_family_filtered_from_water_quality_channel() -> None:
    q1 = EpanetWaterQualityDiagnostic(
        section="QUALITY", row_index=0, tokens=("J1", "0.5"), text="J1 0.5"
    )
    s1 = EpanetWaterQualityDiagnostic(
        section="SOURCES",
        row_index=0,
        tokens=("J1", "CONCEN", "1.0"),
        text="J1 CONCEN 1.0",
    )
    r1 = EpanetWaterQualityDiagnostic(
        section="REACTIONS",
        row_index=0,
        tokens=("ORDER", "BULK", "1"),
        text="ORDER BULK 1",
    )
    r2 = EpanetWaterQualityDiagnostic(
        section="REACTIONS",
        row_index=1,
        tokens=("GLOBAL", "BULK", "-0.5"),
        text="GLOBAL BULK -0.5",
    )
    m1 = EpanetWaterQualityDiagnostic(
        section="MIXING", row_index=0, tokens=("T1", "MIXED"), text="T1 MIXED"
    )
    container = EpanetImportDiagnostics(water_quality_rows=(q1, s1, r1, r2, m1))
    assert container.rows_for_section("QUALITY") == (q1,)
    assert container.rows_for_section("SOURCES") == (s1,)
    assert container.rows_for_section("REACTIONS") == (r1, r2)
    assert container.rows_for_section("MIXING") == (m1,)


# ---------------------------------------------------------------------------
# Section name normalisation
# ---------------------------------------------------------------------------


def test_case_insensitive_lookup() -> None:
    rows = (EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    container = EpanetImportDiagnostics(status_rows=rows)
    assert container.rows_for_section("status") == rows
    assert container.rows_for_section("Status") == rows
    assert container.rows_for_section("StAtUs") == rows
    assert container.rows_for_section("STATUS") == rows


def test_whitespace_is_stripped_from_section_name() -> None:
    rows = (EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    container = EpanetImportDiagnostics(status_rows=rows)
    assert container.rows_for_section(" STATUS") == rows
    assert container.rows_for_section("STATUS ") == rows
    assert container.rows_for_section("  status  ") == rows
    assert container.rows_for_section("\tSTATUS\n") == rows


def test_bracket_notation_is_accepted() -> None:
    rows = (EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    container = EpanetImportDiagnostics(status_rows=rows)
    assert container.rows_for_section("[STATUS]") == rows
    assert container.rows_for_section(" [ status ] ") == rows
    assert container.rows_for_section("[Status]") == rows


def test_unknown_section_returns_empty_tuple() -> None:
    container = EpanetImportDiagnostics(
        status_rows=(EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    )
    assert container.rows_for_section("NOPE") == ()
    assert container.rows_for_section("OPTIONS") == ()
    assert container.rows_for_section("PIPES") == ()


def test_empty_or_whitespace_section_name_returns_empty_tuple() -> None:
    container = EpanetImportDiagnostics(
        status_rows=(EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    )
    assert container.rows_for_section("") == ()
    assert container.rows_for_section("   ") == ()
    assert container.rows_for_section("\t\n") == ()
    assert container.rows_for_section("[]") == ()
    assert container.rows_for_section("[ ]") == ()


# ---------------------------------------------------------------------------
# Ignored-section presence is not surfaced by rows_for_section
# ---------------------------------------------------------------------------


def test_does_not_return_ignored_section_presence_records() -> None:
    """Sections that emit only an ``EpanetIgnoredSectionDiagnostic``
    presence record (e.g. ``[TITLE]``, ``[REPORT]``) must not appear in
    ``rows_for_section``: the accessor reads row channels only.
    """
    container = EpanetImportDiagnostics(
        ignored_sections=(
            EpanetIgnoredSectionDiagnostic(section="TITLE", row_count=1),
            EpanetIgnoredSectionDiagnostic(section="REPORT", row_count=0),
            EpanetIgnoredSectionDiagnostic(section="CONTROLS", row_count=3),
        ),
        control_rule_rows=(
            EpanetControlRuleDiagnostic(
                section="CONTROLS",
                row_index=0,
                tokens=("LINK", "P1", "OPEN"),
                text="LINK P1 OPEN",
            ),
        ),
    )
    # Presence-only sections return empty even when ignored_sections has them.
    assert container.rows_for_section("TITLE") == ()
    assert container.rows_for_section("REPORT") == ()
    # CONTROLS comes back from the row channel only — one row, not three.
    rows = container.rows_for_section("CONTROLS")
    assert len(rows) == 1
    assert all(isinstance(r, EpanetControlRuleDiagnostic) for r in rows)


def test_no_double_count_with_row_count_by_section() -> None:
    """For every section the row channels can populate,
    ``len(rows_for_section(name)) == row_count_by_section()[name]``.
    """
    container = EpanetImportDiagnostics(
        status_rows=(
            EpanetStatusDiagnostic(link_id="P1", status="OPEN"),
            EpanetStatusDiagnostic(link_id="P2", status="OPEN"),
        ),
        control_rule_rows=(
            EpanetControlRuleDiagnostic(
                section="CONTROLS",
                row_index=0,
                tokens=("LINK", "P1", "OPEN"),
                text="LINK P1 OPEN",
            ),
            EpanetControlRuleDiagnostic(
                section="RULES",
                row_index=0,
                tokens=("RULE", "R1"),
                text="RULE R1",
            ),
        ),
        pattern_energy_rows=(
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
        ),
        emitter_demand_rows=(
            EpanetEmitterDemandDiagnostic(
                section="EMITTERS", row_index=0, tokens=("J1", "0.5"), text="J1 0.5"
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
        ignored_sections=(
            EpanetIgnoredSectionDiagnostic(section="CONTROLS", row_count=1),
        ),
    )
    counts = container.row_count_by_section()
    for section, count in counts.items():
        assert len(container.rows_for_section(section)) == count, section


# ---------------------------------------------------------------------------
# Source-order preservation
# ---------------------------------------------------------------------------


def test_source_order_preserved() -> None:
    r0 = EpanetControlRuleDiagnostic(
        section="CONTROLS", row_index=0, tokens=("LINK", "P1", "OPEN"), text="LINK P1 OPEN"
    )
    r1 = EpanetControlRuleDiagnostic(
        section="CONTROLS",
        row_index=1,
        tokens=("LINK", "P2", "CLOSED"),
        text="LINK P2 CLOSED",
    )
    r2 = EpanetControlRuleDiagnostic(
        section="CONTROLS", row_index=2, tokens=("LINK", "P3", "OPEN"), text="LINK P3 OPEN"
    )
    container = EpanetImportDiagnostics(control_rule_rows=(r0, r1, r2))
    assert container.rows_for_section("CONTROLS") == (r0, r1, r2)


# ---------------------------------------------------------------------------
# Return value is a tuple and the container is not mutable through it
# ---------------------------------------------------------------------------


def test_return_value_is_tuple_backed() -> None:
    rows = (EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    container = EpanetImportDiagnostics(status_rows=rows)
    result = container.rows_for_section("STATUS")
    assert isinstance(result, tuple)


def test_returned_tuple_cannot_mutate_diagnostics() -> None:
    """Tuples are immutable, but callers may convert to a list. Either way,
    diagnostics must remain unchanged.
    """
    rows = (
        EpanetStatusDiagnostic(link_id="P1", status="OPEN"),
        EpanetStatusDiagnostic(link_id="P2", status="OPEN"),
    )
    container = EpanetImportDiagnostics(status_rows=rows)
    result = container.rows_for_section("STATUS")
    # tuples are immutable
    with pytest.raises((TypeError, AttributeError)):
        result[0] = "tampered"  # type: ignore[index]
    # Even an external list copy that gets cleared leaves diagnostics intact.
    external = list(result)
    external.clear()
    assert container.status_rows == rows
    assert container.rows_for_section("STATUS") == rows


def test_helpers_do_not_mutate_container() -> None:
    rows = (
        EpanetStatusDiagnostic(link_id="P1", status="OPEN"),
        EpanetStatusDiagnostic(link_id="P2", status="OPEN"),
    )
    cr_rows = (
        EpanetControlRuleDiagnostic(
            section="CONTROLS",
            row_index=0,
            tokens=("LINK", "P1", "OPEN"),
            text="LINK P1 OPEN",
        ),
    )
    container = EpanetImportDiagnostics(status_rows=rows, control_rule_rows=cr_rows)
    # Invoke the accessor with many section names.
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
        "NOPE",
        "",
    ):
        _ = container.rows_for_section(name)
    # Tuple identities are unchanged.
    assert container.status_rows is rows
    assert container.control_rule_rows is cr_rows


def test_container_remains_frozen_dataclass() -> None:
    container = EpanetImportDiagnostics()
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.status_rows = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Parser integration — fallback parser is the authoritative diagnostics path.
# ---------------------------------------------------------------------------


def test_fallback_parser_rows_for_section_matches_channels(tmp_path: Path) -> None:
    path = _write(tmp_path, "all.inp", _all_channels_inp())
    diag = load_inp_diagnostics(path, parser="fallback")

    assert diag.rows_for_section("STATUS") == diag.status_rows
    assert diag.rows_for_section("CONTROLS") == tuple(
        r for r in diag.control_rule_rows if r.section == "CONTROLS"
    )
    assert diag.rows_for_section("RULES") == tuple(
        r for r in diag.control_rule_rows if r.section == "RULES"
    )
    assert diag.rows_for_section("PATTERNS") == tuple(
        r for r in diag.pattern_energy_rows if r.section == "PATTERNS"
    )
    assert diag.rows_for_section("ENERGY") == tuple(
        r for r in diag.pattern_energy_rows if r.section == "ENERGY"
    )
    assert diag.rows_for_section("EMITTERS") == tuple(
        r for r in diag.emitter_demand_rows if r.section == "EMITTERS"
    )
    assert diag.rows_for_section("DEMANDS") == tuple(
        r for r in diag.emitter_demand_rows if r.section == "DEMANDS"
    )
    assert diag.rows_for_section("QUALITY") == tuple(
        r for r in diag.water_quality_rows if r.section == "QUALITY"
    )
    assert diag.rows_for_section("SOURCES") == tuple(
        r for r in diag.water_quality_rows if r.section == "SOURCES"
    )
    assert diag.rows_for_section("REACTIONS") == tuple(
        r for r in diag.water_quality_rows if r.section == "REACTIONS"
    )
    assert diag.rows_for_section("MIXING") == tuple(
        r for r in diag.water_quality_rows if r.section == "MIXING"
    )


def test_fallback_parser_rows_for_section_matches_counts(tmp_path: Path) -> None:
    path = _write(tmp_path, "all.inp", _all_channels_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    counts = diag.row_count_by_section()
    for section, count in counts.items():
        assert len(diag.rows_for_section(section)) == count


def test_load_inp_and_load_network_agree_on_rows_for_section(tmp_path: Path) -> None:
    path = _write(tmp_path, "all.inp", _all_channels_inp())
    diag_a = load_inp_diagnostics(path, parser="fallback")
    _, diag_b = load_network_from_inp(path, parser="fallback", return_diagnostics=True)
    for section in (
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
        "NOPE",
    ):
        assert diag_a.rows_for_section(section) == diag_b.rows_for_section(section)


def test_load_network_from_inp_default_remains_network_only(tmp_path: Path) -> None:
    path = _write(tmp_path, "all.inp", _all_channels_inp())
    result = load_network_from_inp(path, parser="fallback")
    assert isinstance(result, Network)


def test_network_identical_with_and_without_diagnostic_sections(tmp_path: Path) -> None:
    """Diagnostic sections are hydraulically inert. The :class:`Network`
    loaded from the all-channels fixture must be identical to the
    network loaded from the baseline fixture (which carries no
    diagnostic-row sections) on every field the dPHM core consumes.
    """
    bare = _write(tmp_path, "bare.inp", _baseline_inp())
    full = _write(tmp_path, "full.inp", _all_channels_inp())
    net_bare = load_network_from_inp(bare, parser="fallback")
    net_full = load_network_from_inp(full, parser="fallback")
    assert net_bare.num_nodes == net_full.num_nodes
    assert net_bare.num_edges == net_full.num_edges
    assert net_bare.num_fixed_heads == net_full.num_fixed_heads
    assert torch.equal(net_bare.edge_index, net_full.edge_index)
    assert net_bare.pipe_mask.tolist() == net_full.pipe_mask.tolist()
    assert net_bare.pump_mask.tolist() == net_full.pump_mask.tolist()
    assert net_bare.fixed_head_mask.tolist() == net_full.fixed_head_mask.tolist()
    for attr in (
        "demands",
        "fixed_head_values",
        "lengths",
        "diameters",
        "c_factors",
        "pump_speeds",
    ):
        a_t = getattr(net_bare, attr).double()
        b_t = getattr(net_full, attr).double()
        assert torch.allclose(a_t, b_t, atol=0.0), attr


def test_status_rejection_still_raises(tmp_path: Path) -> None:
    """Sprint 22 ``[STATUS] CLOSED`` rejection must still raise."""
    text = _baseline_inp("[STATUS]\n P1 CLOSED\n")
    path = _write(tmp_path, "bad.inp", text)
    with pytest.raises(ValueError):
        load_inp_diagnostics(path, parser="fallback")


# ---------------------------------------------------------------------------
# WNTR adapter asymmetry: rows_for_section returns () for every section.
# ---------------------------------------------------------------------------


def test_wntr_rows_for_section_is_empty(tmp_path: Path) -> None:
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
    for section in (
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
        assert diag.rows_for_section(section) == ()
