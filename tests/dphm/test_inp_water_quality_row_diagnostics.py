"""Sprint 29 — EPANET ``.inp`` water-quality per-row diagnostics.

Sprint 24 surfaced *which* ignored sections were present in an imported
``.inp`` file via :class:`EpanetIgnoredSectionDiagnostic`. Sprint 25
narrowed that visibility for ``[CONTROLS]`` and ``[RULES]`` by emitting
one read-only :class:`EpanetControlRuleDiagnostic` per tokenised row.
Sprint 26 added the equivalent per-row surface for ``[PATTERNS]`` and
``[ENERGY]`` via :class:`EpanetPatternEnergyDiagnostic`. Sprint 27 then
classified the ``[CONTROLS]`` rows by link-type. Sprint 28 added the
equivalent per-row surface for ``[EMITTERS]`` and ``[DEMANDS]`` via
:class:`EpanetEmitterDemandDiagnostic`. Sprint 29 adds the equivalent
per-row surface for the four remaining water-quality-family ignored
sections — ``[QUALITY]``, ``[SOURCES]``, ``[REACTIONS]``, and
``[MIXING]`` — via :class:`EpanetWaterQualityDiagnostic`. Analysts
can inspect the exact unsupported initial-quality, source, reaction,
and tank-mixing rows the parser dropped on the floor without changing
any hydraulic field on the loaded :class:`Network`.

Contract:

* :class:`EpanetImportDiagnostics` gains a ``water_quality_rows`` field
  — a ``tuple[EpanetWaterQualityDiagnostic, ...]`` defaulting to ``()``.
* The new dataclass is ``frozen=True`` and carries ``section``,
  ``row_index``, ``tokens`` (a tuple), ``text`` and ``message`` fields.
* Section names are normalised to upper-case ``QUALITY`` / ``SOURCES``
  / ``REACTIONS`` / ``MIXING``.
* Only ``[QUALITY]`` / ``[SOURCES]`` / ``[REACTIONS]`` / ``[MIXING]``
  rows surface here; other ignored sections (``[CONTROLS]``,
  ``[RULES]``, ``[PATTERNS]``, ``[ENERGY]``, ``[EMITTERS]``,
  ``[DEMANDS]``, ``[TIMES]``, …) remain visible through their existing
  channels.
* ``[STATUS]`` is excluded from this channel.
* Row order within each section matches the source-file row order; the
  ``row_index`` is 0-based within the section bucket
  :func:`_split_sections` produces. Section ordering follows the source
  file: whichever of the four water-quality sections is declared first
  appears first in ``water_quality_rows``.
* Sprint 23 ``status_rows``, Sprint 24 ``ignored_sections``, Sprint 25
  ``control_rule_rows``, Sprint 26 ``pattern_energy_rows``, and
  Sprint 28 ``emitter_demand_rows`` diagnostics are preserved unchanged.
* Diagnostics are hydraulically inert — the loaded :class:`Network`
  is byte-for-byte identical to one loaded from a fixture with no
  water-quality rows. Newton-solving the perturbed network reproduces
  the baseline heads and flows.
* The Sprint 22 rejection behaviour for ``[STATUS]`` rows is preserved.
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
    newton_solve,
)
from aquaoptima.dphm.inp_io import IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _baseline_inp(extra: str = "") -> str:
    """A small loop fixture; ``extra`` is injected just before ``[END]``."""
    return (
        "[TITLE]\n"
        "Sprint 29 water-quality diagnostics fixture\n"
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


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def _assert_networks_identical(a: Network, b: Network) -> None:
    assert a.num_nodes == b.num_nodes
    assert a.num_edges == b.num_edges
    assert a.num_fixed_heads == b.num_fixed_heads
    assert torch.equal(a.edge_index, b.edge_index)
    assert a.pipe_mask.tolist() == b.pipe_mask.tolist()
    assert a.pump_mask.tolist() == b.pump_mask.tolist()
    assert a.fixed_head_mask.tolist() == b.fixed_head_mask.tolist()
    for attr in (
        "demands",
        "fixed_head_values",
        "lengths",
        "diameters",
        "c_factors",
        "pump_speeds",
    ):
        a_t = getattr(a, attr).double()
        b_t = getattr(b, attr).double()
        assert torch.allclose(a_t, b_t, atol=0.0), f"{attr} drifted"
    a_pc = a.pump_coeffs.double()
    b_pc = b.pump_coeffs.double()
    assert torch.allclose(a_pc, b_pc, atol=1e-9, rtol=1e-9)


_WQ_SECTIONS = ("QUALITY", "SOURCES", "REACTIONS", "MIXING")


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_water_quality_diagnostic_is_dataclass() -> None:
    assert dataclasses.is_dataclass(EpanetWaterQualityDiagnostic)


def test_water_quality_diagnostic_is_frozen() -> None:
    """Records must be immutable so callers cannot mutate read-only
    diagnostics.
    """
    rec = EpanetWaterQualityDiagnostic(
        section="QUALITY",
        row_index=0,
        tokens=("J1", "0.5"),
        text="J1 0.5",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.section = "SOURCES"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.row_index = 1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.tokens = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.text = ""  # type: ignore[misc]


def test_water_quality_diagnostic_defaults() -> None:
    rec = EpanetWaterQualityDiagnostic(
        section="QUALITY",
        row_index=0,
        tokens=("J1", "0.5"),
        text="J1 0.5",
    )
    assert rec.section == "QUALITY"
    assert rec.row_index == 0
    assert rec.tokens == ("J1", "0.5")
    assert rec.text == "J1 0.5"
    assert "ignored" in rec.message.lower()


def test_water_quality_diagnostic_tokens_is_tuple() -> None:
    """``tokens`` must be a tuple so the record stays structurally
    immutable even though :func:`_split_sections` produces lists.
    """
    rec = EpanetWaterQualityDiagnostic(
        section="SOURCES",
        row_index=2,
        tokens=("J1", "CONCEN", "1.0", "PAT1"),
        text="J1 CONCEN 1.0 PAT1",
    )
    assert isinstance(rec.tokens, tuple)


def test_diagnostics_container_has_water_quality_rows_field() -> None:
    """``EpanetImportDiagnostics`` exposes ``status_rows``,
    ``ignored_sections``, ``control_rule_rows``, ``pattern_energy_rows``,
    ``emitter_demand_rows``, and the new ``water_quality_rows`` field,
    each defaulting to an empty tuple so earlier-sprint callers stay
    backwards-compatible.
    """
    container = EpanetImportDiagnostics()
    assert container.status_rows == ()
    assert container.ignored_sections == ()
    assert container.control_rule_rows == ()
    assert container.pattern_energy_rows == ()
    assert container.emitter_demand_rows == ()
    assert container.water_quality_rows == ()


def test_diagnostics_container_is_frozen_for_water_quality_rows() -> None:
    rec = EpanetWaterQualityDiagnostic(
        section="QUALITY",
        row_index=0,
        tokens=("J1", "0.5"),
        text="J1 0.5",
    )
    container = EpanetImportDiagnostics(water_quality_rows=(rec,))
    assert isinstance(container.water_quality_rows, tuple)
    assert container.water_quality_rows == (rec,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.water_quality_rows = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Empty / absent cases
# ---------------------------------------------------------------------------


def test_diagnostics_empty_when_no_water_quality_sections(tmp_path: Path) -> None:
    """A fixture with none of the four water-quality sections produces no
    water-quality row diagnostics.
    """
    path = _write(tmp_path, "no_wq.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.water_quality_rows == ()


@pytest.mark.parametrize("section_name", _WQ_SECTIONS)
def test_diagnostics_empty_when_bare_header(
    tmp_path: Path, section_name: str
) -> None:
    """A bare ``[<water-quality>]`` header (no body) produces no per-row
    diagnostics — the section is present (so ``ignored_sections`` carries
    it) but there are no rows to surface.
    """
    text = _baseline_inp(f"[{section_name}]\n")
    path = _write(tmp_path, f"bare_{section_name}.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.water_quality_rows == ()
    ignored_names = {r.section for r in diag.ignored_sections}
    assert section_name in ignored_names


# ---------------------------------------------------------------------------
# Single rows per water-quality section
# ---------------------------------------------------------------------------


def test_single_quality_row_emits_one_diagnostic(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[QUALITY]\n"
        " J1 0.5\n"
    )
    path = _write(tmp_path, "one_quality.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.water_quality_rows) == 1
    rec = diag.water_quality_rows[0]
    assert isinstance(rec, EpanetWaterQualityDiagnostic)
    assert rec.section == "QUALITY"
    assert rec.row_index == 0
    assert rec.tokens == ("J1", "0.5")
    assert rec.text == "J1 0.5"


def test_single_sources_row_emits_one_diagnostic(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[SOURCES]\n"
        " J1 CONCEN 1.0 PAT1\n"
    )
    path = _write(tmp_path, "one_source.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.water_quality_rows) == 1
    rec = diag.water_quality_rows[0]
    assert rec.section == "SOURCES"
    assert rec.row_index == 0
    assert rec.tokens == ("J1", "CONCEN", "1.0", "PAT1")
    assert rec.text == "J1 CONCEN 1.0 PAT1"


def test_single_reactions_row_emits_one_diagnostic(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[REACTIONS]\n"
        " Order Bulk 1\n"
    )
    path = _write(tmp_path, "one_reaction.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.water_quality_rows) == 1
    rec = diag.water_quality_rows[0]
    assert rec.section == "REACTIONS"
    assert rec.row_index == 0
    assert rec.tokens == ("Order", "Bulk", "1")
    assert rec.text == "Order Bulk 1"


def test_single_mixing_row_emits_one_diagnostic(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[MIXING]\n"
        " T1 MIXED\n"
    )
    path = _write(tmp_path, "one_mixing.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.water_quality_rows) == 1
    rec = diag.water_quality_rows[0]
    assert rec.section == "MIXING"
    assert rec.row_index == 0
    assert rec.tokens == ("T1", "MIXED")
    assert rec.text == "T1 MIXED"


# ---------------------------------------------------------------------------
# Multiple rows preserve order and row_index
# ---------------------------------------------------------------------------


def test_multiple_quality_rows_preserve_order_and_row_index(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[QUALITY]\n"
        " J1 0.5\n"
        " J2 0.7\n"
        " J3 0.9\n"
    )
    path = _write(tmp_path, "multi_quality.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.water_quality_rows) == 3
    assert [r.section for r in diag.water_quality_rows] == [
        "QUALITY",
        "QUALITY",
        "QUALITY",
    ]
    assert [r.row_index for r in diag.water_quality_rows] == [0, 1, 2]
    assert diag.water_quality_rows[0].tokens == ("J1", "0.5")
    assert diag.water_quality_rows[1].tokens == ("J2", "0.7")
    assert diag.water_quality_rows[2].tokens == ("J3", "0.9")
    assert diag.water_quality_rows[0].text == "J1 0.5"


def test_multiple_reactions_rows_preserve_order_and_row_index(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[REACTIONS]\n"
        " Order Bulk 1\n"
        " Order Wall 1\n"
        " Global Bulk -0.5\n"
    )
    path = _write(tmp_path, "multi_reactions.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.water_quality_rows) == 3
    assert [r.section for r in diag.water_quality_rows] == [
        "REACTIONS",
        "REACTIONS",
        "REACTIONS",
    ]
    assert [r.row_index for r in diag.water_quality_rows] == [0, 1, 2]
    assert diag.water_quality_rows[0].tokens == ("Order", "Bulk", "1")
    assert diag.water_quality_rows[1].tokens == ("Order", "Wall", "1")
    assert diag.water_quality_rows[2].tokens == ("Global", "Bulk", "-0.5")


# ---------------------------------------------------------------------------
# Mixed water-quality sections: deterministic source order
# ---------------------------------------------------------------------------


def test_mixed_water_quality_sections_source_order(tmp_path: Path) -> None:
    """All four sections present in canonical order:
    ``[QUALITY]`` then ``[SOURCES]`` then ``[REACTIONS]`` then ``[MIXING]``.
    """
    text = _baseline_inp(
        "[QUALITY]\n J1 0.5\n"
        "[SOURCES]\n J2 CONCEN 1.0\n"
        "[REACTIONS]\n Order Bulk 1\n"
        "[MIXING]\n T1 MIXED\n"
    )
    path = _write(tmp_path, "all_wq.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert [r.section for r in diag.water_quality_rows] == [
        "QUALITY",
        "SOURCES",
        "REACTIONS",
        "MIXING",
    ]
    assert [r.row_index for r in diag.water_quality_rows] == [0, 0, 0, 0]


def test_mixed_water_quality_sections_reverse_order(tmp_path: Path) -> None:
    """All four sections present in the reverse of their canonical
    ordering — surface order should follow the source file, not a
    hard-coded enumeration.
    """
    text = _baseline_inp(
        "[MIXING]\n T1 MIXED\n"
        "[REACTIONS]\n Order Bulk 1\n"
        "[SOURCES]\n J2 CONCEN 1.0\n"
        "[QUALITY]\n J1 0.5\n"
    )
    path = _write(tmp_path, "all_wq_rev.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert [r.section for r in diag.water_quality_rows] == [
        "MIXING",
        "REACTIONS",
        "SOURCES",
        "QUALITY",
    ]


def test_mixed_water_quality_sections_row_index_resets_per_section(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[QUALITY]\n J1 0.5\n J2 0.7\n"
        "[SOURCES]\n J3 CONCEN 1.0\n J4 MASS 2.0\n"
        "[REACTIONS]\n Order Bulk 1\n Global Bulk -0.5\n"
        "[MIXING]\n T1 MIXED\n T2 2COMP 0.6\n"
    )
    path = _write(tmp_path, "multi_each.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert [(r.section, r.row_index) for r in diag.water_quality_rows] == [
        ("QUALITY", 0),
        ("QUALITY", 1),
        ("SOURCES", 0),
        ("SOURCES", 1),
        ("REACTIONS", 0),
        ("REACTIONS", 1),
        ("MIXING", 0),
        ("MIXING", 1),
    ]


# ---------------------------------------------------------------------------
# Comments are stripped; blank lines dropped
# ---------------------------------------------------------------------------


def test_inline_comment_stripped_from_quality_row(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[QUALITY]\n"
        " J1 0.5 ; initial chlorine residual mg/L\n"
    )
    path = _write(tmp_path, "quality_with_comment.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.water_quality_rows) == 1
    rec = diag.water_quality_rows[0]
    # _strip_comment removes the ``; ...`` portion before tokenisation,
    # so the diagnostic carries only the pre-comment tokens.
    assert rec.tokens == ("J1", "0.5")


def test_blank_rows_inside_sources_are_dropped(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[SOURCES]\n"
        " J1 CONCEN 1.0\n"
        "\n"
        " J2 MASS 2.0\n"
    )
    path = _write(tmp_path, "sources_with_blank.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.water_quality_rows) == 2
    assert [r.row_index for r in diag.water_quality_rows] == [0, 1]


# ---------------------------------------------------------------------------
# Exclusion of other sections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "section_name, body",
    [
        ("CONTROLS", " LINK P1 CLOSED IF NODE J1 BELOW 10\n"),
        ("RULES", " RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"),
        ("PATTERNS", " PAT1 0.5 0.6\n"),
        ("ENERGY", " GLOBAL PRICE 0.10\n"),
        ("EMITTERS", " J1 0.5\n"),
        ("DEMANDS", " J1 0.5 PAT1\n"),
        ("TIMES", " Duration 24:00\n"),
        ("REPORT", " Status Yes\n"),
    ],
)
def test_other_ignored_sections_not_in_water_quality_rows(
    tmp_path: Path, section_name: str, body: str
) -> None:
    text = _baseline_inp(f"[{section_name}]\n{body}")
    path = _write(tmp_path, f"with_{section_name}.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.water_quality_rows}
    assert section_name not in sections
    # And the section is still surfaced via ignored_sections (Sprint 24).
    ignored_names = {r.section for r in diag.ignored_sections}
    assert section_name in ignored_names


def test_status_section_never_in_water_quality_rows(tmp_path: Path) -> None:
    """``[STATUS]`` is not in :data:`IGNORED_SECTIONS` and must never
    surface as a water-quality row diagnostic.
    """
    text = _baseline_inp("[STATUS]\n P1 OPEN\n")
    path = _write(tmp_path, "status_open.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.water_quality_rows}
    assert "STATUS" not in sections
    # And the OPEN row still surfaces via status_rows (Sprint 23).
    assert [r.link_id for r in diag.status_rows] == ["P1"]


def test_hydraulic_sections_never_in_water_quality_rows(tmp_path: Path) -> None:
    """``[JUNCTIONS]``, ``[PIPES]``, etc. must never surface here."""
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.water_quality_rows}
    for active in (
        "JUNCTIONS",
        "RESERVOIRS",
        "TANKS",
        "PIPES",
        "PUMPS",
        "VALVES",
        "OPTIONS",
        "CURVES",
    ):
        assert active not in sections


def test_emitted_records_only_carry_water_quality_section(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
        "[EMITTERS]\n J1 0.5\n"
        "[DEMANDS]\n J2 0.7 PAT1\n"
        "[QUALITY]\n J1 0.5\n"
        "[SOURCES]\n J2 CONCEN 1.0\n"
        "[REACTIONS]\n Order Bulk 1\n"
        "[MIXING]\n T1 MIXED\n"
    )
    path = _write(tmp_path, "many.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    for rec in diag.water_quality_rows:
        assert rec.section in _WQ_SECTIONS
        # Each surfaced section is in the broader IGNORED_SECTIONS set.
        assert rec.section in IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Earlier per-row channels still exclude QUALITY / SOURCES / REACTIONS / MIXING
# ---------------------------------------------------------------------------


def test_control_rule_rows_exclude_water_quality_sections(
    tmp_path: Path,
) -> None:
    """Sprint 25's per-row channel for ``[CONTROLS]`` / ``[RULES]`` must
    not pick up Sprint 29's water-quality rows.
    """
    text = _baseline_inp(
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
        "[QUALITY]\n J1 0.5\n"
        "[SOURCES]\n J2 CONCEN 1.0\n"
        "[REACTIONS]\n Order Bulk 1\n"
        "[MIXING]\n T1 MIXED\n"
    )
    path = _write(tmp_path, "all_cr_wq.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    cr_sections = {r.section for r in diag.control_rule_rows}
    for wq in _WQ_SECTIONS:
        assert wq not in cr_sections
    # And the Sprint 25 channel still carries CONTROLS + RULES.
    assert "CONTROLS" in cr_sections
    assert "RULES" in cr_sections


def test_pattern_energy_rows_exclude_water_quality_sections(
    tmp_path: Path,
) -> None:
    """Sprint 26's per-row channel for ``[PATTERNS]`` / ``[ENERGY]`` must
    not pick up Sprint 29's water-quality rows.
    """
    text = _baseline_inp(
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
        "[QUALITY]\n J1 0.5\n"
        "[SOURCES]\n J2 CONCEN 1.0\n"
        "[REACTIONS]\n Order Bulk 1\n"
        "[MIXING]\n T1 MIXED\n"
    )
    path = _write(tmp_path, "all_pe_wq.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    pe_sections = {r.section for r in diag.pattern_energy_rows}
    for wq in _WQ_SECTIONS:
        assert wq not in pe_sections
    assert "PATTERNS" in pe_sections
    assert "ENERGY" in pe_sections


def test_emitter_demand_rows_exclude_water_quality_sections(
    tmp_path: Path,
) -> None:
    """Sprint 28's per-row channel for ``[EMITTERS]`` / ``[DEMANDS]`` must
    not pick up Sprint 29's water-quality rows.
    """
    text = _baseline_inp(
        "[EMITTERS]\n J1 0.5\n"
        "[DEMANDS]\n J2 0.7 PAT1\n"
        "[QUALITY]\n J1 0.5\n"
        "[SOURCES]\n J2 CONCEN 1.0\n"
        "[REACTIONS]\n Order Bulk 1\n"
        "[MIXING]\n T1 MIXED\n"
    )
    path = _write(tmp_path, "all_ed_wq.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    ed_sections = {r.section for r in diag.emitter_demand_rows}
    for wq in _WQ_SECTIONS:
        assert wq not in ed_sections
    assert "EMITTERS" in ed_sections
    assert "DEMANDS" in ed_sections


# ---------------------------------------------------------------------------
# Sprint 24 ``ignored_sections`` still includes all four water-quality sections
# ---------------------------------------------------------------------------


def test_ignored_sections_still_lists_water_quality_sections(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[QUALITY]\n J1 0.5\n"
        "[SOURCES]\n J2 CONCEN 1.0\n"
        "[REACTIONS]\n Order Bulk 1\n"
        "[MIXING]\n T1 MIXED\n"
    )
    path = _write(tmp_path, "all_four.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    ignored_names = {r.section for r in diag.ignored_sections}
    for wq in _WQ_SECTIONS:
        assert wq in ignored_names


# ---------------------------------------------------------------------------
# Hydraulic-inertness proofs
# ---------------------------------------------------------------------------


def test_water_quality_diagnostics_do_not_change_network(tmp_path: Path) -> None:
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_water_quality.inp",
        _baseline_inp(
            "[QUALITY]\n"
            " J1 0.5\n"
            " J2 0.7\n"
            "[SOURCES]\n"
            " J3 CONCEN 1.0\n"
            " J4 MASS 2.0\n"
            "[REACTIONS]\n"
            " Order Bulk 1\n"
            " Global Bulk -0.5\n"
            "[MIXING]\n"
            " T1 MIXED\n"
            " T2 2COMP 0.6\n"
        ),
    )
    net_baseline = load_network_from_inp(baseline_path, parser="fallback")
    net_perturbed = load_network_from_inp(perturbed_path, parser="fallback")
    _assert_networks_identical(net_baseline, net_perturbed)


def test_water_quality_diagnostics_do_not_change_solve(tmp_path: Path) -> None:
    """Newton-solving the perturbed network reproduces the baseline heads
    and flows. Diagnostics are visibility only.
    """
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_water_quality.inp",
        _baseline_inp(
            "[QUALITY]\n J1 0.5\n"
            "[SOURCES]\n J2 CONCEN 1.0\n"
            "[REACTIONS]\n Order Bulk 1\n"
            "[MIXING]\n T1 MIXED\n"
        ),
    )
    net_base = load_network_from_inp(baseline_path, parser="fallback")
    net_wq = load_network_from_inp(perturbed_path, parser="fallback")
    r_base = newton_solve(
        net_base, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    r_wq = newton_solve(
        net_wq, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert r_base.converged and r_wq.converged
    assert torch.allclose(
        r_base.heads.double(), r_wq.heads.double(), atol=1e-9
    )
    assert torch.allclose(
        r_base.flows.double(), r_wq.flows.double(), atol=1e-12
    )


def test_return_diagnostics_network_matches_default_load(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "loop_wq.inp",
        _baseline_inp(
            "[QUALITY]\n J1 0.5\n"
            "[SOURCES]\n J2 CONCEN 1.0\n"
            "[REACTIONS]\n Order Bulk 1\n"
            "[MIXING]\n T1 MIXED\n"
        ),
    )
    default_net = load_network_from_inp(path, parser="fallback")
    net, diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert isinstance(net, Network)
    assert isinstance(diag, EpanetImportDiagnostics)
    _assert_networks_identical(default_net, net)
    sections = [r.section for r in diag.water_quality_rows]
    for wq in _WQ_SECTIONS:
        assert wq in sections


def test_default_load_network_from_inp_still_returns_only_network(
    tmp_path: Path,
) -> None:
    """``load_network_from_inp(path)`` without ``return_diagnostics``
    must continue to return a bare :class:`Network` even when
    water-quality rows are present.
    """
    path = _write(
        tmp_path,
        "loop_wq.inp",
        _baseline_inp(
            "[QUALITY]\n J1 0.5\n"
            "[SOURCES]\n J2 CONCEN 1.0\n"
            "[REACTIONS]\n Order Bulk 1\n"
            "[MIXING]\n T1 MIXED\n"
        ),
    )
    result = load_network_from_inp(path, parser="fallback")
    assert isinstance(result, Network)


# ---------------------------------------------------------------------------
# load_inp_diagnostics returns the same diagnostics as the tuple path
# ---------------------------------------------------------------------------


def test_load_inp_diagnostics_matches_load_network_from_inp_tuple(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        "loop_wq.inp",
        _baseline_inp(
            "[QUALITY]\n J1 0.5\n J2 0.7\n"
            "[SOURCES]\n J3 CONCEN 1.0\n J4 MASS 2.0\n"
            "[REACTIONS]\n Order Bulk 1\n Global Bulk -0.5\n"
            "[MIXING]\n T1 MIXED\n T2 2COMP 0.6\n"
        ),
    )
    diag_only = load_inp_diagnostics(path, parser="fallback")
    _net, diag_tuple = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert diag_only.water_quality_rows == diag_tuple.water_quality_rows
    assert diag_only.emitter_demand_rows == diag_tuple.emitter_demand_rows
    assert diag_only.pattern_energy_rows == diag_tuple.pattern_energy_rows
    assert diag_only.control_rule_rows == diag_tuple.control_rule_rows
    assert diag_only.status_rows == diag_tuple.status_rows
    assert diag_only.ignored_sections == diag_tuple.ignored_sections


# ---------------------------------------------------------------------------
# Combined Sprint 23 + 24 + 25 + 26 + 28 + 29 diagnostics coexist
# ---------------------------------------------------------------------------


def test_all_diagnostics_coexist(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[STATUS]\n P1 OPEN\n P2 OPEN\n"
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P3 STATUS IS CLOSED\n"
        "[PATTERNS]\n PAT1 0.5 0.6\n PAT1 0.7 0.8\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n PUMP PU1 PRICE 0.12\n"
        "[EMITTERS]\n J1 0.5\n J2 0.7\n"
        "[DEMANDS]\n J3 0.9 PAT1\n J4 1.1 PAT2\n"
        "[QUALITY]\n J1 0.5\n J2 0.7\n"
        "[SOURCES]\n J3 CONCEN 1.0\n J4 MASS 2.0\n"
        "[REACTIONS]\n Order Bulk 1\n Global Bulk -0.5\n"
        "[MIXING]\n T1 MIXED\n T2 2COMP 0.6\n"
    )
    path = _write(tmp_path, "all_six.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    # Sprint 23 status diagnostics preserved.
    assert [r.link_id for r in diag.status_rows] == ["P1", "P2"]
    for rec in diag.status_rows:
        assert isinstance(rec, EpanetStatusDiagnostic)
    # Sprint 24 ignored-section diagnostics preserved.
    ignored_names = {r.section for r in diag.ignored_sections}
    assert {
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
    }.issubset(ignored_names)
    for rec in diag.ignored_sections:
        assert isinstance(rec, EpanetIgnoredSectionDiagnostic)
    # Sprint 25 control/rule row diagnostics preserved.
    cr_sections = [r.section for r in diag.control_rule_rows]
    assert cr_sections == ["CONTROLS", "RULES", "RULES", "RULES"]
    for rec in diag.control_rule_rows:
        assert isinstance(rec, EpanetControlRuleDiagnostic)
    # Sprint 26 pattern/energy row diagnostics preserved.
    pe_sections = [r.section for r in diag.pattern_energy_rows]
    assert pe_sections == ["PATTERNS", "PATTERNS", "ENERGY", "ENERGY"]
    for rec in diag.pattern_energy_rows:
        assert isinstance(rec, EpanetPatternEnergyDiagnostic)
    # Sprint 28 emitter/demand row diagnostics preserved.
    ed_sections = [r.section for r in diag.emitter_demand_rows]
    assert ed_sections == ["EMITTERS", "EMITTERS", "DEMANDS", "DEMANDS"]
    for rec in diag.emitter_demand_rows:
        assert isinstance(rec, EpanetEmitterDemandDiagnostic)
    # Sprint 29 water-quality row diagnostics.
    wq_sections = [r.section for r in diag.water_quality_rows]
    assert wq_sections == [
        "QUALITY",
        "QUALITY",
        "SOURCES",
        "SOURCES",
        "REACTIONS",
        "REACTIONS",
        "MIXING",
        "MIXING",
    ]
    for rec in diag.water_quality_rows:
        assert isinstance(rec, EpanetWaterQualityDiagnostic)
    # CONTROLS / RULES / PATTERNS / ENERGY / EMITTERS / DEMANDS / STATUS
    # never show up in the water-quality channel.
    wq_set = {r.section for r in diag.water_quality_rows}
    for excluded in (
        "CONTROLS",
        "RULES",
        "PATTERNS",
        "ENERGY",
        "EMITTERS",
        "DEMANDS",
        "STATUS",
    ):
        assert excluded not in wq_set


def test_status_not_in_ignored_or_water_quality(tmp_path: Path) -> None:
    """``[STATUS]`` must not appear as ignored-section or water-quality
    diagnostic, ever.
    """
    text = _baseline_inp("[STATUS]\n P1 OPEN\n")
    path = _write(tmp_path, "status_only.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "STATUS" not in ignored_names
    wq_sections = {r.section for r in diag.water_quality_rows}
    assert "STATUS" not in wq_sections


# ---------------------------------------------------------------------------
# Sprint 22/23 rejection behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status_block",
    [
        "[STATUS]\n P1 CLOSED\n",
        "[STATUS]\n P1 CV\n",
        "[STATUS]\n P1 1.0\n",
        "[STATUS]\n PHANTOM OPEN\n",
        "[STATUS]\n P1 MAYBE\n",
    ],
)
def test_rejected_status_rows_still_raise_with_water_quality_present(
    tmp_path: Path, status_block: str
) -> None:
    """Sprint 29 does not soften Sprint 22 ``[STATUS]`` rejections — a
    file mixing a rejected status row with any water-quality section
    still raises, and no partial diagnostics leak out.
    """
    text = _baseline_inp(
        status_block
        + "[QUALITY]\n J1 0.5\n"
        + "[SOURCES]\n J2 CONCEN 1.0\n"
        + "[REACTIONS]\n Order Bulk 1\n"
        + "[MIXING]\n T1 MIXED\n"
    )
    path = _write(tmp_path, "rejected_with_wq.inp", text)
    with pytest.raises(ValueError):
        load_inp_diagnostics(path, parser="fallback")
    with pytest.raises(ValueError):
        load_network_from_inp(
            path, parser="fallback", return_diagnostics=True
        )


# ---------------------------------------------------------------------------
# Optional WNTR back-end: documented asymmetry
# ---------------------------------------------------------------------------


def test_wntr_back_end_returns_container_without_raising(tmp_path: Path) -> None:
    """The WNTR back-end is documented as fallback-authoritative for
    Sprint 29 water-quality row diagnostics. The smoke check only
    confirms the API returns an :class:`EpanetImportDiagnostics`
    container without raising, and that the ``water_quality_rows``
    tuple is empty by design. When WNTR is not installed the test skips.

    The fixture here uses only those water-quality sections that WNTR
    semantically accepts on a tank-less loop fixture: ``[QUALITY]`` and
    ``[REACTIONS]``. ``[SOURCES]`` and ``[MIXING]`` are exercised against
    the fallback parser elsewhere in this file; their per-row dPHM
    diagnostics are documented as fallback-authoritative anyway, so
    excluding them from the WNTR smoke check changes neither the
    documented WNTR asymmetry nor the Sprint 29 contract.
    """
    pytest.importorskip("wntr")
    text = _baseline_inp(
        "[QUALITY]\n J1 0.5\n"
        "[REACTIONS]\n Order Bulk 1\n"
    )
    path = _write(tmp_path, "wntr_wq.inp", text)
    diag = load_inp_diagnostics(path, parser="wntr")
    assert isinstance(diag, EpanetImportDiagnostics)
    # The WNTR back-end's per-row handling is documented as
    # fallback-authoritative; the adapter leaves water_quality_rows empty.
    assert diag.water_quality_rows == ()
    for rec in diag.water_quality_rows:
        assert isinstance(rec, EpanetWaterQualityDiagnostic)
