"""Sprint 28 — EPANET ``.inp`` ``[EMITTERS]`` / ``[DEMANDS]`` per-row diagnostics.

Sprint 24 surfaced *which* ignored sections were present in an imported
``.inp`` file via :class:`EpanetIgnoredSectionDiagnostic`. Sprint 25
narrowed that visibility for ``[CONTROLS]`` and ``[RULES]`` by emitting
one read-only :class:`EpanetControlRuleDiagnostic` per tokenised row.
Sprint 26 added the equivalent per-row surface for ``[PATTERNS]`` and
``[ENERGY]`` via :class:`EpanetPatternEnergyDiagnostic`. Sprint 27 then
classified the ``[CONTROLS]`` rows by link-type. Sprint 28 adds the
equivalent per-row surface for ``[EMITTERS]`` and ``[DEMANDS]`` via
:class:`EpanetEmitterDemandDiagnostic`. Analysts can inspect the exact
unsupported emitter / demand-category rows the parser dropped on the
floor without changing any hydraulic field on the loaded
:class:`Network`.

Contract:

* :class:`EpanetImportDiagnostics` gains an ``emitter_demand_rows`` field
  — a ``tuple[EpanetEmitterDemandDiagnostic, ...]`` defaulting to ``()``.
* The new dataclass is ``frozen=True`` and carries ``section``,
  ``row_index``, ``tokens`` (a tuple), ``text`` and ``message`` fields.
* Section names are normalised to upper-case ``EMITTERS`` / ``DEMANDS``.
* Only ``[EMITTERS]`` and ``[DEMANDS]`` rows surface here; other ignored
  sections (``[CONTROLS]``, ``[RULES]``, ``[PATTERNS]``, ``[ENERGY]``,
  ``[TIMES]``, …) remain visible through their existing channels.
* ``[STATUS]`` is excluded from this channel.
* Row order within each section matches the source-file row order; the
  ``row_index`` is 0-based within the section bucket
  :func:`_split_sections` produces. Section ordering follows the source
  file: whichever of ``[EMITTERS]`` / ``[DEMANDS]`` is declared first
  appears first in ``emitter_demand_rows``.
* Sprint 23 ``status_rows``, Sprint 24 ``ignored_sections``, Sprint 25
  ``control_rule_rows``, and Sprint 26 ``pattern_energy_rows``
  diagnostics are preserved unchanged.
* Diagnostics are hydraulically inert — the loaded :class:`Network`
  is byte-for-byte identical to one loaded from a fixture with no
  emitter or demand rows. Newton-solving the perturbed network
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
    EpanetEmitterDemandDiagnostic,
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
        "Sprint 28 emitters/demands diagnostics fixture\n"
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


def test_emitter_demand_diagnostic_is_dataclass() -> None:
    assert dataclasses.is_dataclass(EpanetEmitterDemandDiagnostic)


def test_emitter_demand_diagnostic_is_frozen() -> None:
    """Records must be immutable so callers cannot mutate read-only
    diagnostics.
    """
    rec = EpanetEmitterDemandDiagnostic(
        section="EMITTERS",
        row_index=0,
        tokens=("J1", "0.5"),
        text="J1 0.5",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.section = "DEMANDS"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.row_index = 1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.tokens = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.text = ""  # type: ignore[misc]


def test_emitter_demand_diagnostic_defaults() -> None:
    rec = EpanetEmitterDemandDiagnostic(
        section="EMITTERS",
        row_index=0,
        tokens=("J1", "0.5"),
        text="J1 0.5",
    )
    assert rec.section == "EMITTERS"
    assert rec.row_index == 0
    assert rec.tokens == ("J1", "0.5")
    assert rec.text == "J1 0.5"
    assert "ignored" in rec.message.lower()


def test_emitter_demand_diagnostic_tokens_is_tuple() -> None:
    """``tokens`` must be a tuple so the record stays structurally
    immutable even though :func:`_split_sections` produces lists.
    """
    rec = EpanetEmitterDemandDiagnostic(
        section="DEMANDS",
        row_index=2,
        tokens=("J1", "0.5", "PAT1"),
        text="J1 0.5 PAT1",
    )
    assert isinstance(rec.tokens, tuple)


def test_diagnostics_container_has_emitter_demand_rows_field() -> None:
    """``EpanetImportDiagnostics`` exposes ``status_rows``,
    ``ignored_sections``, ``control_rule_rows``, ``pattern_energy_rows``,
    and the new ``emitter_demand_rows`` field, each defaulting to an
    empty tuple so earlier-sprint callers stay backwards-compatible.
    """
    container = EpanetImportDiagnostics()
    assert container.status_rows == ()
    assert container.ignored_sections == ()
    assert container.control_rule_rows == ()
    assert container.pattern_energy_rows == ()
    assert container.emitter_demand_rows == ()


def test_diagnostics_container_is_frozen_for_emitter_demand_rows() -> None:
    rec = EpanetEmitterDemandDiagnostic(
        section="EMITTERS",
        row_index=0,
        tokens=("J1", "0.5"),
        text="J1 0.5",
    )
    container = EpanetImportDiagnostics(emitter_demand_rows=(rec,))
    assert isinstance(container.emitter_demand_rows, tuple)
    assert container.emitter_demand_rows == (rec,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.emitter_demand_rows = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Empty / absent cases
# ---------------------------------------------------------------------------


def test_diagnostics_empty_when_no_emitters_or_demands(tmp_path: Path) -> None:
    """A fixture with neither ``[EMITTERS]`` nor ``[DEMANDS]`` produces no
    emitter/demand row diagnostics.
    """
    path = _write(tmp_path, "no_emitters.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.emitter_demand_rows == ()


def test_diagnostics_empty_when_bare_emitters_header(tmp_path: Path) -> None:
    """A bare ``[EMITTERS]`` header (no body) produces no per-row
    diagnostics — the section is present (so ``ignored_sections`` carries
    it) but there are no rows to surface.
    """
    text = _baseline_inp("[EMITTERS]\n")
    path = _write(tmp_path, "bare_emitters.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.emitter_demand_rows == ()
    # The section header itself still shows up in ignored_sections (Sprint 24).
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "EMITTERS" in ignored_names


def test_diagnostics_empty_when_bare_demands_header(tmp_path: Path) -> None:
    text = _baseline_inp("[DEMANDS]\n")
    path = _write(tmp_path, "bare_demands.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.emitter_demand_rows == ()
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "DEMANDS" in ignored_names


# ---------------------------------------------------------------------------
# Single rows
# ---------------------------------------------------------------------------


def test_single_emitters_row_emits_one_diagnostic(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[EMITTERS]\n"
        " J1 0.5\n"
    )
    path = _write(tmp_path, "one_emitter.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.emitter_demand_rows) == 1
    rec = diag.emitter_demand_rows[0]
    assert isinstance(rec, EpanetEmitterDemandDiagnostic)
    assert rec.section == "EMITTERS"
    assert rec.row_index == 0
    assert rec.tokens == ("J1", "0.5")
    assert rec.text == "J1 0.5"


def test_single_demands_row_emits_one_diagnostic(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[DEMANDS]\n"
        " J1 0.5 PAT1\n"
    )
    path = _write(tmp_path, "one_demand.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.emitter_demand_rows) == 1
    rec = diag.emitter_demand_rows[0]
    assert rec.section == "DEMANDS"
    assert rec.row_index == 0
    assert rec.tokens == ("J1", "0.5", "PAT1")
    assert rec.text == "J1 0.5 PAT1"


# ---------------------------------------------------------------------------
# Multiple rows preserve order and row_index
# ---------------------------------------------------------------------------


def test_multiple_emitters_rows_preserve_order_and_row_index(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[EMITTERS]\n"
        " J1 0.5\n"
        " J2 0.7\n"
        " J3 0.9\n"
    )
    path = _write(tmp_path, "multi_emitters.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.emitter_demand_rows) == 3
    assert [r.section for r in diag.emitter_demand_rows] == [
        "EMITTERS",
        "EMITTERS",
        "EMITTERS",
    ]
    assert [r.row_index for r in diag.emitter_demand_rows] == [0, 1, 2]
    assert diag.emitter_demand_rows[0].tokens == ("J1", "0.5")
    assert diag.emitter_demand_rows[1].tokens == ("J2", "0.7")
    assert diag.emitter_demand_rows[2].tokens == ("J3", "0.9")
    # Text reconstructs from tokens with single-space joins.
    assert diag.emitter_demand_rows[0].text == "J1 0.5"


def test_multiple_demands_rows_preserve_order_and_row_index(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[DEMANDS]\n"
        " J1 0.5 PAT1\n"
        " J2 0.7 PAT2\n"
        " J3 0.9 PAT3\n"
    )
    path = _write(tmp_path, "multi_demands.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.emitter_demand_rows) == 3
    assert [r.section for r in diag.emitter_demand_rows] == [
        "DEMANDS",
        "DEMANDS",
        "DEMANDS",
    ]
    assert [r.row_index for r in diag.emitter_demand_rows] == [0, 1, 2]
    assert diag.emitter_demand_rows[0].tokens == ("J1", "0.5", "PAT1")
    assert diag.emitter_demand_rows[1].tokens == ("J2", "0.7", "PAT2")
    assert diag.emitter_demand_rows[2].tokens == ("J3", "0.9", "PAT3")


# ---------------------------------------------------------------------------
# Mixed EMITTERS + DEMANDS: deterministic source order
# ---------------------------------------------------------------------------


def test_mixed_emitters_and_demands_source_order_emitters_first(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[EMITTERS]\n"
        " J1 0.5\n"
        "[DEMANDS]\n"
        " J2 0.7 PAT1\n"
        " J3 0.9 PAT2\n"
    )
    path = _write(tmp_path, "emitters_then_demands.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.emitter_demand_rows]
    # EMITTERS rows come first because they appear first in the source file.
    assert sections == ["EMITTERS", "DEMANDS", "DEMANDS"]
    # row_index resets per section.
    assert [r.row_index for r in diag.emitter_demand_rows] == [0, 0, 1]


def test_mixed_emitters_and_demands_source_order_demands_first(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[DEMANDS]\n"
        " J1 0.5 PAT1\n"
        " J2 0.7 PAT2\n"
        "[EMITTERS]\n"
        " J3 0.9\n"
    )
    path = _write(tmp_path, "demands_then_emitters.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.emitter_demand_rows]
    # DEMANDS rows come first because they appear first in the source file.
    assert sections == ["DEMANDS", "DEMANDS", "EMITTERS"]
    assert [r.row_index for r in diag.emitter_demand_rows] == [0, 1, 0]


# ---------------------------------------------------------------------------
# Comments are stripped; blank lines dropped
# ---------------------------------------------------------------------------


def test_inline_comment_stripped_from_emitters_row(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[EMITTERS]\n"
        " J1 0.5 ; leakage coefficient\n"
    )
    path = _write(tmp_path, "emitter_with_comment.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.emitter_demand_rows) == 1
    rec = diag.emitter_demand_rows[0]
    # _strip_comment removes the ``; ...`` portion before tokenisation,
    # so the diagnostic carries only the pre-comment tokens.
    assert rec.tokens == ("J1", "0.5")


def test_blank_rows_inside_demands_are_dropped(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[DEMANDS]\n"
        " J1 0.5 PAT1\n"
        "\n"
        " J2 0.7 PAT2\n"
    )
    path = _write(tmp_path, "demands_with_blank.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.emitter_demand_rows) == 2
    assert [r.row_index for r in diag.emitter_demand_rows] == [0, 1]


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
        ("QUALITY", " J1 0.0\n"),
        ("SOURCES", " J1 CONCEN 1.0\n"),
        ("REACTIONS", " Order Bulk 1\n"),
        ("MIXING", " T1 MIXED\n"),
        ("TIMES", " Duration 24:00\n"),
        ("REPORT", " Status Yes\n"),
    ],
)
def test_other_ignored_sections_not_in_emitter_demand_rows(
    tmp_path: Path, section_name: str, body: str
) -> None:
    text = _baseline_inp(f"[{section_name}]\n{body}")
    path = _write(tmp_path, f"with_{section_name}.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.emitter_demand_rows}
    assert section_name not in sections
    # And the section is still surfaced via ignored_sections (Sprint 24).
    ignored_names = {r.section for r in diag.ignored_sections}
    assert section_name in ignored_names


def test_status_section_never_in_emitter_demand_rows(tmp_path: Path) -> None:
    """``[STATUS]`` is not in :data:`IGNORED_SECTIONS` and must never
    surface as an emitter/demand row diagnostic.
    """
    text = _baseline_inp("[STATUS]\n P1 OPEN\n")
    path = _write(tmp_path, "status_open.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.emitter_demand_rows}
    assert "STATUS" not in sections
    # And the OPEN row still surfaces via status_rows (Sprint 23).
    assert [r.link_id for r in diag.status_rows] == ["P1"]


def test_hydraulic_sections_never_in_emitter_demand_rows(tmp_path: Path) -> None:
    """``[JUNCTIONS]``, ``[PIPES]``, etc. must never surface here."""
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.emitter_demand_rows}
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


def test_emitted_records_only_carry_emitters_or_demands_section(
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
    )
    path = _write(tmp_path, "many.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    for rec in diag.emitter_demand_rows:
        assert rec.section in ("EMITTERS", "DEMANDS")
        # Both belong to the broader IGNORED_SECTIONS set.
        assert rec.section in IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Earlier per-row channels still exclude EMITTERS / DEMANDS
# ---------------------------------------------------------------------------


def test_control_rule_rows_exclude_emitters_and_demands(tmp_path: Path) -> None:
    """Sprint 25's per-row channel for ``[CONTROLS]`` / ``[RULES]`` must
    not pick up Sprint 28's ``[EMITTERS]`` / ``[DEMANDS]`` rows.
    """
    text = _baseline_inp(
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
        "[EMITTERS]\n J1 0.5\n"
        "[DEMANDS]\n J2 0.7 PAT1\n"
    )
    path = _write(tmp_path, "all_sections.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    cr_sections = {r.section for r in diag.control_rule_rows}
    assert "EMITTERS" not in cr_sections
    assert "DEMANDS" not in cr_sections
    # And the Sprint 25 channel still carries CONTROLS + RULES.
    assert "CONTROLS" in cr_sections
    assert "RULES" in cr_sections


def test_pattern_energy_rows_exclude_emitters_and_demands(tmp_path: Path) -> None:
    """Sprint 26's per-row channel for ``[PATTERNS]`` / ``[ENERGY]`` must
    not pick up Sprint 28's ``[EMITTERS]`` / ``[DEMANDS]`` rows.
    """
    text = _baseline_inp(
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
        "[EMITTERS]\n J1 0.5\n"
        "[DEMANDS]\n J2 0.7 PAT1\n"
    )
    path = _write(tmp_path, "all_sections_pe.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    pe_sections = {r.section for r in diag.pattern_energy_rows}
    assert "EMITTERS" not in pe_sections
    assert "DEMANDS" not in pe_sections
    # And the Sprint 26 channel still carries PATTERNS + ENERGY.
    assert "PATTERNS" in pe_sections
    assert "ENERGY" in pe_sections


# ---------------------------------------------------------------------------
# Sprint 24 ``ignored_sections`` still includes EMITTERS / DEMANDS
# ---------------------------------------------------------------------------


def test_ignored_sections_still_lists_emitters_and_demands(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[EMITTERS]\n J1 0.5\n"
        "[DEMANDS]\n J2 0.7 PAT1\n"
    )
    path = _write(tmp_path, "both.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "EMITTERS" in ignored_names
    assert "DEMANDS" in ignored_names


# ---------------------------------------------------------------------------
# Hydraulic-inertness proofs
# ---------------------------------------------------------------------------


def test_emitter_demand_diagnostics_do_not_change_network(tmp_path: Path) -> None:
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_emitters_demands.inp",
        _baseline_inp(
            "[EMITTERS]\n"
            " J1 0.5\n"
            " J2 0.7\n"
            "[DEMANDS]\n"
            " J3 0.9 PAT1\n"
            " J4 1.1 PAT2\n"
        ),
    )
    net_baseline = load_network_from_inp(baseline_path, parser="fallback")
    net_perturbed = load_network_from_inp(perturbed_path, parser="fallback")
    _assert_networks_identical(net_baseline, net_perturbed)


def test_emitter_demand_diagnostics_do_not_change_solve(tmp_path: Path) -> None:
    """Newton-solving the perturbed network reproduces the baseline heads
    and flows. Diagnostics are visibility only.
    """
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_emitters_demands.inp",
        _baseline_inp(
            "[EMITTERS]\n J1 0.5\n"
            "[DEMANDS]\n J2 0.7 PAT1\n"
        ),
    )
    net_base = load_network_from_inp(baseline_path, parser="fallback")
    net_ed = load_network_from_inp(perturbed_path, parser="fallback")
    r_base = newton_solve(
        net_base, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    r_ed = newton_solve(
        net_ed, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert r_base.converged and r_ed.converged
    assert torch.allclose(
        r_base.heads.double(), r_ed.heads.double(), atol=1e-9
    )
    assert torch.allclose(
        r_base.flows.double(), r_ed.flows.double(), atol=1e-12
    )


def test_return_diagnostics_network_matches_default_load(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "loop_ed.inp",
        _baseline_inp(
            "[EMITTERS]\n J1 0.5\n"
            "[DEMANDS]\n J2 0.7 PAT1\n"
        ),
    )
    default_net = load_network_from_inp(path, parser="fallback")
    net, diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert isinstance(net, Network)
    assert isinstance(diag, EpanetImportDiagnostics)
    _assert_networks_identical(default_net, net)
    sections = [r.section for r in diag.emitter_demand_rows]
    assert "EMITTERS" in sections
    assert "DEMANDS" in sections


def test_default_load_network_from_inp_still_returns_only_network(
    tmp_path: Path,
) -> None:
    """``load_network_from_inp(path)`` without ``return_diagnostics``
    must continue to return a bare :class:`Network` even when
    ``[EMITTERS]`` / ``[DEMANDS]`` rows are present.
    """
    path = _write(
        tmp_path,
        "loop_ed.inp",
        _baseline_inp(
            "[EMITTERS]\n J1 0.5\n"
            "[DEMANDS]\n J2 0.7 PAT1\n"
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
        "loop_ed.inp",
        _baseline_inp(
            "[EMITTERS]\n J1 0.5\n J2 0.7\n"
            "[DEMANDS]\n J3 0.9 PAT1\n J4 1.1 PAT2\n"
        ),
    )
    diag_only = load_inp_diagnostics(path, parser="fallback")
    _net, diag_tuple = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert diag_only.emitter_demand_rows == diag_tuple.emitter_demand_rows
    assert diag_only.pattern_energy_rows == diag_tuple.pattern_energy_rows
    assert diag_only.control_rule_rows == diag_tuple.control_rule_rows
    assert diag_only.status_rows == diag_tuple.status_rows
    assert diag_only.ignored_sections == diag_tuple.ignored_sections


# ---------------------------------------------------------------------------
# Combined Sprint 23 + 24 + 25 + 26 + 28 diagnostics coexist
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
    )
    path = _write(tmp_path, "all_five.inp", text)
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
    # Sprint 28 emitter/demand row diagnostics.
    ed_sections = [r.section for r in diag.emitter_demand_rows]
    assert ed_sections == ["EMITTERS", "EMITTERS", "DEMANDS", "DEMANDS"]
    # CONTROLS / RULES / PATTERNS / ENERGY / STATUS never show up in the
    # emitter/demand channel.
    ed_set = {r.section for r in diag.emitter_demand_rows}
    assert "CONTROLS" not in ed_set
    assert "RULES" not in ed_set
    assert "PATTERNS" not in ed_set
    assert "ENERGY" not in ed_set
    assert "STATUS" not in ed_set


def test_status_not_in_ignored_or_emitter_demand(tmp_path: Path) -> None:
    """``[STATUS]`` must not appear as ignored-section or emitter/demand
    diagnostic, ever.
    """
    text = _baseline_inp("[STATUS]\n P1 OPEN\n")
    path = _write(tmp_path, "status_only.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "STATUS" not in ignored_names
    ed_sections = {r.section for r in diag.emitter_demand_rows}
    assert "STATUS" not in ed_sections


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
def test_rejected_status_rows_still_raise_with_emitters_demands_present(
    tmp_path: Path, status_block: str
) -> None:
    """Sprint 28 does not soften Sprint 22 ``[STATUS]`` rejections — a
    file mixing a rejected status row with ``[EMITTERS]`` / ``[DEMANDS]``
    still raises, and no partial diagnostics leak out.
    """
    text = _baseline_inp(
        status_block
        + "[EMITTERS]\n J1 0.5\n"
        + "[DEMANDS]\n J2 0.7 PAT1\n"
    )
    path = _write(tmp_path, "rejected_with_ed.inp", text)
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
    Sprint 28 emitter/demand row diagnostics. The smoke check only
    confirms the API returns an :class:`EpanetImportDiagnostics`
    container without raising, and that the ``emitter_demand_rows``
    tuple is empty by design. When WNTR is not installed the test skips.
    """
    pytest.importorskip("wntr")
    text = _baseline_inp(
        "[EMITTERS]\n J1 0.5\n"
        "[DEMANDS]\n J2 0.7 PAT1\n"
    )
    path = _write(tmp_path, "wntr_ed.inp", text)
    diag = load_inp_diagnostics(path, parser="wntr")
    assert isinstance(diag, EpanetImportDiagnostics)
    # The WNTR back-end's per-row handling is documented as
    # fallback-authoritative; the adapter leaves emitter_demand_rows empty.
    assert diag.emitter_demand_rows == ()
    for rec in diag.emitter_demand_rows:
        assert isinstance(rec, EpanetEmitterDemandDiagnostic)
        assert rec.section in ("EMITTERS", "DEMANDS")
