"""Sprint 26 — EPANET ``.inp`` ``[PATTERNS]`` / ``[ENERGY]`` per-row diagnostics.

Sprint 24 surfaced *which* ignored sections were present in an imported
``.inp`` file via :class:`EpanetIgnoredSectionDiagnostic`. Sprint 25
narrowed that visibility for ``[CONTROLS]`` and ``[RULES]`` by emitting
one read-only :class:`EpanetControlRuleDiagnostic` per tokenised row.
Sprint 26 adds the equivalent per-row surface for ``[PATTERNS]`` and
``[ENERGY]`` via :class:`EpanetPatternEnergyDiagnostic`. Analysts can
inspect the exact unsupported pattern / energy rows the parser dropped
on the floor without changing any hydraulic field on the loaded
:class:`Network`.

Contract:

* :class:`EpanetImportDiagnostics` gains a ``pattern_energy_rows`` field
  — a ``tuple[EpanetPatternEnergyDiagnostic, ...]`` defaulting to ``()``.
* The new dataclass is ``frozen=True`` and carries ``section``,
  ``row_index``, ``tokens`` (a tuple), ``text`` and ``message`` fields.
* Section names are normalised to upper-case ``PATTERNS`` / ``ENERGY``.
* Only ``[PATTERNS]`` and ``[ENERGY]`` rows surface here; other ignored
  sections (``[CONTROLS]``, ``[RULES]``, ``[TIMES]``, …) remain visible
  through their existing channels.
* ``[STATUS]`` is excluded from this channel.
* Row order within each section matches the source-file row order; the
  ``row_index`` is 0-based within the section bucket
  :func:`_split_sections` produces. Section ordering follows the source
  file: whichever of ``[PATTERNS]`` / ``[ENERGY]`` is declared first
  appears first in ``pattern_energy_rows``.
* Sprint 23 ``status_rows``, Sprint 24 ``ignored_sections``, and Sprint
  25 ``control_rule_rows`` diagnostics are preserved unchanged.
* Diagnostics are hydraulically inert — the loaded :class:`Network`
  is byte-for-byte identical to one loaded from a fixture with no
  pattern or energy rows. Newton-solving the perturbed network
  reproduces the baseline heads and flows.
* The Sprint 22 rejection behaviour for ``[STATUS]`` rows is preserved.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    EpanetControlRuleDiagnostic,
    EpanetIgnoredSectionDiagnostic,
    EpanetImportDiagnostics,
    EpanetPatternEnergyDiagnostic,
    EpanetStatusDiagnostic,
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
        "Sprint 26 patterns/energy diagnostics fixture\n"
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


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_pattern_energy_diagnostic_is_dataclass() -> None:
    assert dataclasses.is_dataclass(EpanetPatternEnergyDiagnostic)


def test_pattern_energy_diagnostic_is_frozen() -> None:
    """Records must be immutable so callers cannot mutate read-only
    diagnostics.
    """
    rec = EpanetPatternEnergyDiagnostic(
        section="PATTERNS",
        row_index=0,
        tokens=("PAT1", "0.5", "0.6"),
        text="PAT1 0.5 0.6",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.section = "ENERGY"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.row_index = 1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.tokens = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.text = ""  # type: ignore[misc]


def test_pattern_energy_diagnostic_defaults() -> None:
    rec = EpanetPatternEnergyDiagnostic(
        section="PATTERNS",
        row_index=0,
        tokens=("PAT1", "0.5", "0.6"),
        text="PAT1 0.5 0.6",
    )
    assert rec.section == "PATTERNS"
    assert rec.row_index == 0
    assert rec.tokens == ("PAT1", "0.5", "0.6")
    assert rec.text == "PAT1 0.5 0.6"
    assert "ignored" in rec.message.lower()


def test_pattern_energy_diagnostic_tokens_is_tuple() -> None:
    """``tokens`` must be a tuple so the record stays structurally
    immutable even though :func:`_split_sections` produces lists.
    """
    rec = EpanetPatternEnergyDiagnostic(
        section="ENERGY",
        row_index=2,
        tokens=("GLOBAL", "PRICE", "0.10"),
        text="GLOBAL PRICE 0.10",
    )
    assert isinstance(rec.tokens, tuple)


def test_diagnostics_container_has_pattern_energy_rows_field() -> None:
    """``EpanetImportDiagnostics`` exposes ``status_rows``,
    ``ignored_sections``, ``control_rule_rows``, and the new
    ``pattern_energy_rows`` field, each defaulting to an empty tuple so
    earlier-sprint callers stay backwards-compatible.
    """
    container = EpanetImportDiagnostics()
    assert container.status_rows == ()
    assert container.ignored_sections == ()
    assert container.control_rule_rows == ()
    assert container.pattern_energy_rows == ()


def test_diagnostics_container_is_frozen_for_pattern_energy_rows() -> None:
    rec = EpanetPatternEnergyDiagnostic(
        section="PATTERNS",
        row_index=0,
        tokens=("PAT1", "0.5"),
        text="PAT1 0.5",
    )
    container = EpanetImportDiagnostics(pattern_energy_rows=(rec,))
    assert isinstance(container.pattern_energy_rows, tuple)
    assert container.pattern_energy_rows == (rec,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.pattern_energy_rows = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Empty / absent cases
# ---------------------------------------------------------------------------


def test_diagnostics_empty_when_no_patterns_or_energy(tmp_path: Path) -> None:
    """A fixture with neither ``[PATTERNS]`` nor ``[ENERGY]`` produces no
    pattern/energy row diagnostics.
    """
    path = _write(tmp_path, "no_patterns.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.pattern_energy_rows == ()


def test_diagnostics_empty_when_bare_patterns_header(tmp_path: Path) -> None:
    """A bare ``[PATTERNS]`` header (no body) produces no per-row
    diagnostics — the section is present (so ``ignored_sections`` carries
    it) but there are no rows to surface.
    """
    text = _baseline_inp("[PATTERNS]\n")
    path = _write(tmp_path, "bare_patterns.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.pattern_energy_rows == ()
    # The section header itself still shows up in ignored_sections (Sprint 24).
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "PATTERNS" in ignored_names


def test_diagnostics_empty_when_bare_energy_header(tmp_path: Path) -> None:
    text = _baseline_inp("[ENERGY]\n")
    path = _write(tmp_path, "bare_energy.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.pattern_energy_rows == ()
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "ENERGY" in ignored_names


# ---------------------------------------------------------------------------
# Single rows
# ---------------------------------------------------------------------------


def test_single_patterns_row_emits_one_diagnostic(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[PATTERNS]\n"
        " PAT1 0.5 0.6 0.7 0.8\n"
    )
    path = _write(tmp_path, "one_pattern.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.pattern_energy_rows) == 1
    rec = diag.pattern_energy_rows[0]
    assert rec.section == "PATTERNS"
    assert rec.row_index == 0
    assert rec.tokens == ("PAT1", "0.5", "0.6", "0.7", "0.8")
    assert rec.text == "PAT1 0.5 0.6 0.7 0.8"


def test_single_energy_row_emits_one_diagnostic(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[ENERGY]\n"
        " GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "one_energy.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.pattern_energy_rows) == 1
    rec = diag.pattern_energy_rows[0]
    assert rec.section == "ENERGY"
    assert rec.row_index == 0
    assert rec.tokens == ("GLOBAL", "PRICE", "0.10")
    assert rec.text == "GLOBAL PRICE 0.10"


# ---------------------------------------------------------------------------
# Multiple rows preserve order and row_index
# ---------------------------------------------------------------------------


def test_multiple_patterns_rows_preserve_order_and_row_index(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[PATTERNS]\n"
        " PAT1 0.5 0.6 0.7\n"
        " PAT1 0.8 0.9 1.0\n"
        " PAT2 1.1 1.2 1.3\n"
    )
    path = _write(tmp_path, "multi_patterns.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.pattern_energy_rows) == 3
    assert [r.section for r in diag.pattern_energy_rows] == [
        "PATTERNS",
        "PATTERNS",
        "PATTERNS",
    ]
    assert [r.row_index for r in diag.pattern_energy_rows] == [0, 1, 2]
    assert diag.pattern_energy_rows[0].tokens == ("PAT1", "0.5", "0.6", "0.7")
    assert diag.pattern_energy_rows[1].tokens == ("PAT1", "0.8", "0.9", "1.0")
    assert diag.pattern_energy_rows[2].tokens == ("PAT2", "1.1", "1.2", "1.3")
    # Text reconstructs from tokens with single-space joins.
    assert diag.pattern_energy_rows[0].text == "PAT1 0.5 0.6 0.7"


def test_multiple_energy_rows_preserve_order_and_row_index(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[ENERGY]\n"
        " GLOBAL PRICE 0.10\n"
        " GLOBAL EFFIC 75\n"
        " PUMP PU1 PRICE 0.12\n"
    )
    path = _write(tmp_path, "multi_energy.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.pattern_energy_rows) == 3
    assert [r.section for r in diag.pattern_energy_rows] == [
        "ENERGY",
        "ENERGY",
        "ENERGY",
    ]
    assert [r.row_index for r in diag.pattern_energy_rows] == [0, 1, 2]
    assert diag.pattern_energy_rows[0].tokens == ("GLOBAL", "PRICE", "0.10")
    assert diag.pattern_energy_rows[1].tokens == ("GLOBAL", "EFFIC", "75")
    assert diag.pattern_energy_rows[2].tokens == ("PUMP", "PU1", "PRICE", "0.12")


# ---------------------------------------------------------------------------
# Mixed PATTERNS + ENERGY: deterministic source order
# ---------------------------------------------------------------------------


def test_mixed_patterns_and_energy_source_order_patterns_first(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[PATTERNS]\n"
        " PAT1 0.5 0.6\n"
        "[ENERGY]\n"
        " GLOBAL PRICE 0.10\n"
        " GLOBAL EFFIC 75\n"
    )
    path = _write(tmp_path, "patterns_then_energy.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.pattern_energy_rows]
    # PATTERNS rows come first because they appear first in the source file.
    assert sections == ["PATTERNS", "ENERGY", "ENERGY"]
    # row_index resets per section.
    assert [r.row_index for r in diag.pattern_energy_rows] == [0, 0, 1]


def test_mixed_patterns_and_energy_source_order_energy_first(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[ENERGY]\n"
        " GLOBAL PRICE 0.10\n"
        " GLOBAL EFFIC 75\n"
        "[PATTERNS]\n"
        " PAT1 0.5 0.6\n"
    )
    path = _write(tmp_path, "energy_then_patterns.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.pattern_energy_rows]
    # ENERGY rows come first because they appear first in the source file.
    assert sections == ["ENERGY", "ENERGY", "PATTERNS"]
    assert [r.row_index for r in diag.pattern_energy_rows] == [0, 1, 0]


# ---------------------------------------------------------------------------
# Comments are stripped; blank lines dropped
# ---------------------------------------------------------------------------


def test_inline_comment_stripped_from_patterns_row(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[PATTERNS]\n"
        " PAT1 0.5 0.6 ; afternoon profile\n"
    )
    path = _write(tmp_path, "pattern_with_comment.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.pattern_energy_rows) == 1
    rec = diag.pattern_energy_rows[0]
    # _strip_comment removes the ``; ...`` portion before tokenisation,
    # so the diagnostic carries only the pre-comment tokens.
    assert rec.tokens == ("PAT1", "0.5", "0.6")


def test_blank_rows_inside_energy_are_dropped(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[ENERGY]\n"
        " GLOBAL PRICE 0.10\n"
        "\n"
        " GLOBAL EFFIC 75\n"
    )
    path = _write(tmp_path, "energy_with_blank.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.pattern_energy_rows) == 2
    assert [r.row_index for r in diag.pattern_energy_rows] == [0, 1]


# ---------------------------------------------------------------------------
# Exclusion of other sections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "section_name, body",
    [
        ("CONTROLS", " LINK P1 CLOSED IF NODE J1 BELOW 10\n"),
        ("RULES", " RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"),
        ("EMITTERS", " J1 0.5\n"),
        ("QUALITY", " J1 0.0\n"),
        ("SOURCES", " J1 CONCEN 1.0\n"),
        ("REACTIONS", " Order Bulk 1\n"),
        ("MIXING", " T1 MIXED\n"),
        ("TIMES", " Duration 24:00\n"),
        ("REPORT", " Status Yes\n"),
        ("DEMANDS", " J1 0.5\n"),
    ],
)
def test_other_ignored_sections_not_in_pattern_energy_rows(
    tmp_path: Path, section_name: str, body: str
) -> None:
    text = _baseline_inp(f"[{section_name}]\n{body}")
    path = _write(tmp_path, f"with_{section_name}.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.pattern_energy_rows}
    assert section_name not in sections
    # And the section is still surfaced via ignored_sections (Sprint 24).
    ignored_names = {r.section for r in diag.ignored_sections}
    assert section_name in ignored_names


def test_status_section_never_in_pattern_energy_rows(tmp_path: Path) -> None:
    """``[STATUS]`` is not in :data:`IGNORED_SECTIONS` and must never
    surface as a pattern/energy row diagnostic.
    """
    text = _baseline_inp("[STATUS]\n P1 OPEN\n")
    path = _write(tmp_path, "status_open.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.pattern_energy_rows}
    assert "STATUS" not in sections
    # And the OPEN row still surfaces via status_rows (Sprint 23).
    assert [r.link_id for r in diag.status_rows] == ["P1"]


def test_hydraulic_sections_never_in_pattern_energy_rows(tmp_path: Path) -> None:
    """``[JUNCTIONS]``, ``[PIPES]``, etc. must never surface here."""
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.pattern_energy_rows}
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


def test_emitted_records_only_carry_patterns_or_energy_section(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "many.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    for rec in diag.pattern_energy_rows:
        assert rec.section in ("PATTERNS", "ENERGY")
        # Both belong to the broader IGNORED_SECTIONS set.
        assert rec.section in IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Control/rule diagnostics still exclude patterns/energy
# ---------------------------------------------------------------------------


def test_control_rule_rows_exclude_patterns_and_energy(tmp_path: Path) -> None:
    """Sprint 25's per-row channel for ``[CONTROLS]`` / ``[RULES]`` must
    not pick up Sprint 26's ``[PATTERNS]`` / ``[ENERGY]`` rows.
    """
    text = _baseline_inp(
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "all_sections.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    cr_sections = {r.section for r in diag.control_rule_rows}
    assert "PATTERNS" not in cr_sections
    assert "ENERGY" not in cr_sections
    # And the Sprint 25 channel still carries CONTROLS + RULES.
    assert "CONTROLS" in cr_sections
    assert "RULES" in cr_sections


# ---------------------------------------------------------------------------
# Sprint 24 ``ignored_sections`` still includes PATTERNS / ENERGY
# ---------------------------------------------------------------------------


def test_ignored_sections_still_lists_patterns_and_energy(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "both.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "PATTERNS" in ignored_names
    assert "ENERGY" in ignored_names


# ---------------------------------------------------------------------------
# Hydraulic-inertness proofs
# ---------------------------------------------------------------------------


def test_pattern_energy_diagnostics_do_not_change_network(tmp_path: Path) -> None:
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_patterns_energy.inp",
        _baseline_inp(
            "[PATTERNS]\n"
            " PAT1 0.5 0.6 0.7 0.8\n"
            " PAT1 0.9 1.0 1.1 1.2\n"
            "[ENERGY]\n"
            " GLOBAL PRICE 0.10\n"
            " GLOBAL EFFIC 75\n"
            " PUMP PU1 PRICE 0.12\n"
        ),
    )
    net_baseline = load_network_from_inp(baseline_path, parser="fallback")
    net_perturbed = load_network_from_inp(perturbed_path, parser="fallback")
    _assert_networks_identical(net_baseline, net_perturbed)


def test_pattern_energy_diagnostics_do_not_change_solve(tmp_path: Path) -> None:
    """Newton-solving the perturbed network reproduces the baseline heads
    and flows. Diagnostics are visibility only.
    """
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_patterns_energy.inp",
        _baseline_inp(
            "[PATTERNS]\n PAT1 0.5 0.6 0.7\n"
            "[ENERGY]\n GLOBAL PRICE 0.10\n"
        ),
    )
    net_base = load_network_from_inp(baseline_path, parser="fallback")
    net_pe = load_network_from_inp(perturbed_path, parser="fallback")
    r_base = newton_solve(
        net_base, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    r_pe = newton_solve(
        net_pe, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert r_base.converged and r_pe.converged
    assert torch.allclose(
        r_base.heads.double(), r_pe.heads.double(), atol=1e-9
    )
    assert torch.allclose(
        r_base.flows.double(), r_pe.flows.double(), atol=1e-12
    )


def test_return_diagnostics_network_matches_default_load(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "loop_pe.inp",
        _baseline_inp(
            "[PATTERNS]\n PAT1 0.5 0.6\n"
            "[ENERGY]\n GLOBAL PRICE 0.10\n"
        ),
    )
    default_net = load_network_from_inp(path, parser="fallback")
    net, diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert isinstance(net, Network)
    assert isinstance(diag, EpanetImportDiagnostics)
    _assert_networks_identical(default_net, net)
    sections = [r.section for r in diag.pattern_energy_rows]
    assert "PATTERNS" in sections
    assert "ENERGY" in sections


def test_default_load_network_from_inp_still_returns_only_network(
    tmp_path: Path,
) -> None:
    """``load_network_from_inp(path)`` without ``return_diagnostics``
    must continue to return a bare :class:`Network` even when
    ``[PATTERNS]`` / ``[ENERGY]`` rows are present.
    """
    path = _write(
        tmp_path,
        "loop_pe.inp",
        _baseline_inp(
            "[PATTERNS]\n PAT1 0.5 0.6\n"
            "[ENERGY]\n GLOBAL PRICE 0.10\n"
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
        "loop_pe.inp",
        _baseline_inp(
            "[PATTERNS]\n PAT1 0.5 0.6\n PAT2 0.7 0.8\n"
            "[ENERGY]\n GLOBAL PRICE 0.10\n PUMP PU1 PRICE 0.12\n"
        ),
    )
    diag_only = load_inp_diagnostics(path, parser="fallback")
    _net, diag_tuple = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert diag_only.pattern_energy_rows == diag_tuple.pattern_energy_rows
    assert diag_only.control_rule_rows == diag_tuple.control_rule_rows
    assert diag_only.status_rows == diag_tuple.status_rows
    assert diag_only.ignored_sections == diag_tuple.ignored_sections


# ---------------------------------------------------------------------------
# Combined Sprint 23 + 24 + 25 + 26 diagnostics coexist
# ---------------------------------------------------------------------------


def test_all_diagnostics_coexist(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[STATUS]\n P1 OPEN\n P2 OPEN\n"
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P3 STATUS IS CLOSED\n"
        "[PATTERNS]\n PAT1 0.5 0.6\n PAT1 0.7 0.8\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n PUMP PU1 PRICE 0.12\n"
    )
    path = _write(tmp_path, "all_four.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    # Sprint 23 status diagnostics preserved.
    assert [r.link_id for r in diag.status_rows] == ["P1", "P2"]
    for rec in diag.status_rows:
        assert isinstance(rec, EpanetStatusDiagnostic)
    # Sprint 24 ignored-section diagnostics preserved.
    ignored_names = {r.section for r in diag.ignored_sections}
    assert {"CONTROLS", "RULES", "PATTERNS", "ENERGY"}.issubset(ignored_names)
    for rec in diag.ignored_sections:
        assert isinstance(rec, EpanetIgnoredSectionDiagnostic)
    # Sprint 25 control/rule row diagnostics preserved.
    cr_sections = [r.section for r in diag.control_rule_rows]
    assert cr_sections == ["CONTROLS", "RULES", "RULES", "RULES"]
    for rec in diag.control_rule_rows:
        assert isinstance(rec, EpanetControlRuleDiagnostic)
    # Sprint 26 pattern/energy row diagnostics.
    pe_sections = [r.section for r in diag.pattern_energy_rows]
    assert pe_sections == ["PATTERNS", "PATTERNS", "ENERGY", "ENERGY"]
    # CONTROLS / RULES / STATUS never show up in the pattern/energy channel.
    pe_set = {r.section for r in diag.pattern_energy_rows}
    assert "CONTROLS" not in pe_set
    assert "RULES" not in pe_set
    assert "STATUS" not in pe_set


def test_status_not_in_ignored_or_pattern_energy(tmp_path: Path) -> None:
    """``[STATUS]`` must not appear as ignored-section or pattern/energy
    diagnostic, ever.
    """
    text = _baseline_inp("[STATUS]\n P1 OPEN\n")
    path = _write(tmp_path, "status_only.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "STATUS" not in ignored_names
    pe_sections = {r.section for r in diag.pattern_energy_rows}
    assert "STATUS" not in pe_sections


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
def test_rejected_status_rows_still_raise_with_patterns_present(
    tmp_path: Path, status_block: str
) -> None:
    """Sprint 26 does not soften Sprint 22 ``[STATUS]`` rejections — a
    file mixing a rejected status row with ``[PATTERNS]`` / ``[ENERGY]``
    still raises, and no partial diagnostics leak out.
    """
    text = _baseline_inp(
        status_block
        + "[PATTERNS]\n PAT1 0.5 0.6\n"
        + "[ENERGY]\n GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "rejected_with_pe.inp", text)
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
    Sprint 26 pattern/energy row diagnostics. The smoke check only
    confirms the API returns an :class:`EpanetImportDiagnostics`
    container without raising, and that the ``pattern_energy_rows``
    tuple is empty by design. When WNTR is not installed the test skips.
    """
    pytest.importorskip("wntr")
    text = _baseline_inp(
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "wntr_pe.inp", text)
    diag = load_inp_diagnostics(path, parser="wntr")
    assert isinstance(diag, EpanetImportDiagnostics)
    # The WNTR back-end's per-row handling is documented as
    # fallback-authoritative; the adapter leaves pattern_energy_rows empty.
    assert diag.pattern_energy_rows == ()
    for rec in diag.pattern_energy_rows:
        assert isinstance(rec, EpanetPatternEnergyDiagnostic)
        assert rec.section in ("PATTERNS", "ENERGY")
