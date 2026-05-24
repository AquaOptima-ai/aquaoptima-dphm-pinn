"""Sprint 25 — EPANET ``.inp`` ``[CONTROLS]`` / ``[RULES]`` per-row diagnostics.

Sprint 24 surfaced *which* ignored sections were present in an imported
``.inp`` file via :class:`EpanetIgnoredSectionDiagnostic`. Sprint 25 narrows
that visibility for two ignored sections only — ``[CONTROLS]`` and
``[RULES]`` — by emitting one read-only :class:`EpanetControlRuleDiagnostic`
per tokenised row inside those sections. Analysts can see exactly which
unsupported control / rule rows were dropped on the floor at parse time
without changing any hydraulic field on the loaded :class:`Network`.

Contract:

* :class:`EpanetImportDiagnostics` gains a ``control_rule_rows`` field —
  a ``tuple[EpanetControlRuleDiagnostic, ...]`` defaulting to ``()``.
* The new dataclass is ``frozen=True`` and carries ``section``,
  ``row_index``, ``tokens`` (a tuple), ``text`` and ``message`` fields.
* Section names are normalised to upper-case ``CONTROLS`` / ``RULES``.
* Only ``[CONTROLS]`` and ``[RULES]`` rows surface here; other ignored
  sections (``[PATTERNS]``, ``[ENERGY]``, ``[TIMES]``, …) remain visible
  only through ``ignored_sections``.
* ``[STATUS]`` is excluded from both ``ignored_sections`` and
  ``control_rule_rows`` (its accepted rows go through ``status_rows``).
* Row order within each section matches the source-file row order; the
  ``row_index`` is 0-based within the section bucket
  :func:`_split_sections` produces. Section ordering follows the source
  file: whichever of ``[CONTROLS]`` / ``[RULES]`` is declared first
  appears first in ``control_rule_rows``.
* Sprint 23 ``status_rows`` and Sprint 24 ``ignored_sections``
  diagnostics are preserved unchanged.
* Diagnostics are hydraulically inert — the loaded :class:`Network`
  is byte-for-byte identical to one loaded from a fixture with no
  control or rule rows. Newton-solving the perturbed network
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
        "Sprint 25 controls/rules diagnostics fixture\n"
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


def test_control_rule_diagnostic_is_dataclass() -> None:
    assert dataclasses.is_dataclass(EpanetControlRuleDiagnostic)


def test_control_rule_diagnostic_is_frozen() -> None:
    """Records must be immutable so callers cannot mutate read-only
    diagnostics.
    """
    rec = EpanetControlRuleDiagnostic(
        section="CONTROLS",
        row_index=0,
        tokens=("LINK", "P1", "CLOSED"),
        text="LINK P1 CLOSED",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.section = "RULES"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.row_index = 1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.tokens = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.text = ""  # type: ignore[misc]


def test_control_rule_diagnostic_defaults() -> None:
    rec = EpanetControlRuleDiagnostic(
        section="CONTROLS",
        row_index=0,
        tokens=("LINK", "P1", "CLOSED"),
        text="LINK P1 CLOSED",
    )
    assert rec.section == "CONTROLS"
    assert rec.row_index == 0
    assert rec.tokens == ("LINK", "P1", "CLOSED")
    assert rec.text == "LINK P1 CLOSED"
    assert "ignored" in rec.message.lower()


def test_control_rule_diagnostic_tokens_is_tuple() -> None:
    """``tokens`` must be a tuple so the record stays structurally
    immutable even though :func:`_split_sections` produces lists.
    """
    rec = EpanetControlRuleDiagnostic(
        section="RULES",
        row_index=2,
        tokens=("IF", "NODE", "J1", "PRESSURE", "BELOW", "20"),
        text="IF NODE J1 PRESSURE BELOW 20",
    )
    assert isinstance(rec.tokens, tuple)


def test_diagnostics_container_has_control_rule_rows_field() -> None:
    """``EpanetImportDiagnostics`` exposes ``status_rows``,
    ``ignored_sections``, and the new ``control_rule_rows`` field, each
    defaulting to an empty tuple so Sprint 23 / 24 callers stay
    backwards-compatible.
    """
    container = EpanetImportDiagnostics()
    assert container.status_rows == ()
    assert container.ignored_sections == ()
    assert container.control_rule_rows == ()


def test_diagnostics_container_is_frozen_for_control_rule_rows() -> None:
    rec = EpanetControlRuleDiagnostic(
        section="CONTROLS",
        row_index=0,
        tokens=("LINK", "P1", "OPEN"),
        text="LINK P1 OPEN",
    )
    container = EpanetImportDiagnostics(control_rule_rows=(rec,))
    assert isinstance(container.control_rule_rows, tuple)
    assert container.control_rule_rows == (rec,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.control_rule_rows = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Empty / absent cases
# ---------------------------------------------------------------------------


def test_diagnostics_empty_when_no_controls_or_rules(tmp_path: Path) -> None:
    """A fixture with neither ``[CONTROLS]`` nor ``[RULES]`` produces no
    control/rule row diagnostics.
    """
    path = _write(tmp_path, "no_controls.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.control_rule_rows == ()


def test_diagnostics_empty_when_bare_controls_header(tmp_path: Path) -> None:
    """A bare ``[CONTROLS]`` header (no body) produces no per-row
    diagnostics — the section is present (so ``ignored_sections`` carries
    it) but there are no rows to surface.
    """
    text = _baseline_inp("[CONTROLS]\n")
    path = _write(tmp_path, "bare_controls.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.control_rule_rows == ()
    # The section header itself still shows up in ignored_sections (Sprint 24).
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "CONTROLS" in ignored_names


def test_diagnostics_empty_when_bare_rules_header(tmp_path: Path) -> None:
    text = _baseline_inp("[RULES]\n")
    path = _write(tmp_path, "bare_rules.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.control_rule_rows == ()
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "RULES" in ignored_names


# ---------------------------------------------------------------------------
# Single CONTROLS row
# ---------------------------------------------------------------------------


def test_single_controls_row_emits_one_diagnostic(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 10\n"
    )
    path = _write(tmp_path, "one_control.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 1
    rec = diag.control_rule_rows[0]
    assert rec.section == "CONTROLS"
    assert rec.row_index == 0
    assert rec.tokens == ("LINK", "P1", "CLOSED", "IF", "NODE", "J1", "BELOW", "10")
    assert rec.text == "LINK P1 CLOSED IF NODE J1 BELOW 10"


# ---------------------------------------------------------------------------
# Multiple CONTROLS rows preserve order and row_index
# ---------------------------------------------------------------------------


def test_multiple_controls_rows_preserve_order_and_row_index(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 10\n"
        " LINK P2 OPEN AT TIME 0\n"
        " LINK P3 OPEN IF NODE J2 ABOVE 30\n"
    )
    path = _write(tmp_path, "multi_controls.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 3
    assert [r.section for r in diag.control_rule_rows] == [
        "CONTROLS",
        "CONTROLS",
        "CONTROLS",
    ]
    assert [r.row_index for r in diag.control_rule_rows] == [0, 1, 2]
    assert diag.control_rule_rows[0].tokens == (
        "LINK", "P1", "CLOSED", "IF", "NODE", "J1", "BELOW", "10",
    )
    assert diag.control_rule_rows[1].tokens == ("LINK", "P2", "OPEN", "AT", "TIME", "0")
    assert diag.control_rule_rows[2].tokens == (
        "LINK", "P3", "OPEN", "IF", "NODE", "J2", "ABOVE", "30",
    )
    # Text reconstructs from tokens with single-space joins.
    assert diag.control_rule_rows[0].text == "LINK P1 CLOSED IF NODE J1 BELOW 10"
    assert diag.control_rule_rows[1].text == "LINK P2 OPEN AT TIME 0"


# ---------------------------------------------------------------------------
# RULES rows surface per-line (EPANET rules span multiple lines, but the
# diagnostics emit one record per tokenised parser row).
# ---------------------------------------------------------------------------


def test_rules_rows_emit_one_record_per_parser_line(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[RULES]\n"
        " RULE R1\n"
        " IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P1 STATUS IS CLOSED\n"
    )
    path = _write(tmp_path, "rules_three_lines.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    rules_records = [r for r in diag.control_rule_rows if r.section == "RULES"]
    assert len(rules_records) == 3
    assert [r.row_index for r in rules_records] == [0, 1, 2]
    assert rules_records[0].tokens == ("RULE", "R1")
    assert rules_records[1].tokens == ("IF", "NODE", "J1", "PRESSURE", "BELOW", "20")
    assert rules_records[2].tokens == (
        "THEN", "LINK", "P1", "STATUS", "IS", "CLOSED",
    )


# ---------------------------------------------------------------------------
# Mixed CONTROLS + RULES: deterministic source order
# ---------------------------------------------------------------------------


def test_mixed_controls_and_rules_source_order_controls_first(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 10\n"
        "[RULES]\n"
        " RULE R1\n"
        " IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
    )
    path = _write(tmp_path, "controls_then_rules.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.control_rule_rows]
    # CONTROLS rows come first, then RULES rows.
    assert sections == ["CONTROLS", "RULES", "RULES", "RULES"]
    # row_index resets per section.
    assert [r.row_index for r in diag.control_rule_rows] == [0, 0, 1, 2]


def test_mixed_controls_and_rules_source_order_rules_first(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[RULES]\n"
        " RULE R1\n"
        " IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 10\n"
    )
    path = _write(tmp_path, "rules_then_controls.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.control_rule_rows]
    # RULES rows come first because they appear first in the source file.
    assert sections == ["RULES", "RULES", "RULES", "CONTROLS"]
    assert [r.row_index for r in diag.control_rule_rows] == [0, 1, 2, 0]


# ---------------------------------------------------------------------------
# Comments are stripped (matching _split_sections behaviour); blank lines
# are dropped.
# ---------------------------------------------------------------------------


def test_inline_comment_stripped_from_control_row(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 10 ; closed when J1 drops\n"
    )
    path = _write(tmp_path, "control_with_comment.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 1
    rec = diag.control_rule_rows[0]
    # _strip_comment removes the ``; ...`` portion before tokenisation,
    # so the diagnostic carries only the pre-comment tokens.
    assert rec.tokens == ("LINK", "P1", "CLOSED", "IF", "NODE", "J1", "BELOW", "10")


def test_blank_rows_inside_controls_are_dropped(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 10\n"
        "\n"
        " LINK P2 OPEN AT TIME 0\n"
    )
    path = _write(tmp_path, "controls_with_blank.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 2
    assert [r.row_index for r in diag.control_rule_rows] == [0, 1]


# ---------------------------------------------------------------------------
# Other ignored sections are excluded from control_rule_rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "section_name, body",
    [
        ("PATTERNS", " PAT1 0.7 0.8 0.9 1.0\n"),
        ("ENERGY", " GLOBAL PRICE 0.10\n"),
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
def test_other_ignored_sections_not_in_control_rule_rows(
    tmp_path: Path, section_name: str, body: str
) -> None:
    text = _baseline_inp(f"[{section_name}]\n{body}")
    path = _write(tmp_path, f"with_{section_name}.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.control_rule_rows}
    assert section_name not in sections
    # And the section is still surfaced via ignored_sections (Sprint 24).
    ignored_names = {r.section for r in diag.ignored_sections}
    assert section_name in ignored_names


def test_status_section_never_in_control_rule_rows(tmp_path: Path) -> None:
    """``[STATUS]`` is not in :data:`IGNORED_SECTIONS` and must never
    surface as a control/rule row diagnostic.
    """
    text = _baseline_inp("[STATUS]\n P1 OPEN\n")
    path = _write(tmp_path, "status_open.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.control_rule_rows}
    assert "STATUS" not in sections
    # And the OPEN row still surfaces via status_rows (Sprint 23).
    assert [r.link_id for r in diag.status_rows] == ["P1"]


def test_hydraulic_sections_never_in_control_rule_rows(tmp_path: Path) -> None:
    """``[JUNCTIONS]``, ``[PIPES]``, etc. must never surface here."""
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.control_rule_rows}
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


def test_emitted_records_only_carry_controls_or_rules_section(
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
    for rec in diag.control_rule_rows:
        assert rec.section in ("CONTROLS", "RULES")
        # Both belong to the broader IGNORED_SECTIONS set.
        assert rec.section in IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Sprint 24 ``ignored_sections`` still includes CONTROLS / RULES
# ---------------------------------------------------------------------------


def test_ignored_sections_still_lists_controls_and_rules(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
    )
    path = _write(tmp_path, "both.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "CONTROLS" in ignored_names
    assert "RULES" in ignored_names


# ---------------------------------------------------------------------------
# Hydraulic-inertness proofs
# ---------------------------------------------------------------------------


def test_control_rule_diagnostics_do_not_change_network(tmp_path: Path) -> None:
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_controls_rules.inp",
        _baseline_inp(
            "[CONTROLS]\n"
            " LINK P1 CLOSED IF NODE J1 BELOW 99999\n"
            " LINK P2 OPEN AT TIME 0\n"
            "[RULES]\n"
            " RULE R1\n"
            " IF NODE J1 PRESSURE BELOW 20\n"
            " THEN LINK P3 STATUS IS CLOSED\n"
        ),
    )
    net_baseline = load_network_from_inp(baseline_path, parser="fallback")
    net_perturbed = load_network_from_inp(perturbed_path, parser="fallback")
    _assert_networks_identical(net_baseline, net_perturbed)


def test_control_rule_diagnostics_do_not_change_solve(tmp_path: Path) -> None:
    """Newton-solving the perturbed network reproduces the baseline heads
    and flows. Diagnostics are visibility only.
    """
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_controls_rules.inp",
        _baseline_inp(
            "[CONTROLS]\n"
            " LINK P1 CLOSED IF NODE J1 BELOW 99999\n"
            "[RULES]\n"
            " RULE R1\n"
            " IF NODE J1 PRESSURE BELOW 20\n"
            " THEN LINK P2 STATUS IS CLOSED\n"
        ),
    )
    net_base = load_network_from_inp(baseline_path, parser="fallback")
    net_ctrl = load_network_from_inp(perturbed_path, parser="fallback")
    r_base = newton_solve(
        net_base, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    r_ctrl = newton_solve(
        net_ctrl, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert r_base.converged and r_ctrl.converged
    assert torch.allclose(
        r_base.heads.double(), r_ctrl.heads.double(), atol=1e-9
    )
    assert torch.allclose(
        r_base.flows.double(), r_ctrl.flows.double(), atol=1e-12
    )


def test_return_diagnostics_network_matches_default_load(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "loop_ctrls.inp",
        _baseline_inp(
            "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
            "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
            " THEN LINK P2 STATUS IS CLOSED\n"
        ),
    )
    default_net = load_network_from_inp(path, parser="fallback")
    net, diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert isinstance(net, Network)
    assert isinstance(diag, EpanetImportDiagnostics)
    _assert_networks_identical(default_net, net)
    sections = [r.section for r in diag.control_rule_rows]
    assert "CONTROLS" in sections
    assert "RULES" in sections


def test_default_load_network_from_inp_still_returns_only_network(
    tmp_path: Path,
) -> None:
    """``load_network_from_inp(path)`` without ``return_diagnostics``
    must continue to return a bare :class:`Network` even when CONTROLS /
    RULES rows are present.
    """
    path = _write(
        tmp_path,
        "loop_ctrls.inp",
        _baseline_inp(
            "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
            "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
            " THEN LINK P2 STATUS IS CLOSED\n"
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
        "loop_ctrls.inp",
        _baseline_inp(
            "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
            " LINK P2 OPEN AT TIME 0\n"
            "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
            " THEN LINK P3 STATUS IS CLOSED\n"
        ),
    )
    diag_only = load_inp_diagnostics(path, parser="fallback")
    _net, diag_tuple = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert diag_only.control_rule_rows == diag_tuple.control_rule_rows
    assert diag_only.status_rows == diag_tuple.status_rows
    assert diag_only.ignored_sections == diag_tuple.ignored_sections


# ---------------------------------------------------------------------------
# Combined Sprint 23 + 24 + 25 diagnostics coexist
# ---------------------------------------------------------------------------


def test_status_ignored_and_control_rule_diagnostics_coexist(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[STATUS]\n P1 OPEN\n P2 OPEN\n"
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P3 STATUS IS CLOSED\n"
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "all_three.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    # Sprint 23 status diagnostics preserved.
    assert [r.link_id for r in diag.status_rows] == ["P1", "P2"]
    for rec in diag.status_rows:
        assert isinstance(rec, EpanetStatusDiagnostic)
    # Sprint 24 ignored-section diagnostics preserved.
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "CONTROLS" in ignored_names
    assert "RULES" in ignored_names
    assert "PATTERNS" in ignored_names
    assert "ENERGY" in ignored_names
    for rec in diag.ignored_sections:
        assert isinstance(rec, EpanetIgnoredSectionDiagnostic)
    # Sprint 25 control/rule row diagnostics.
    sections = [r.section for r in diag.control_rule_rows]
    assert sections == ["CONTROLS", "RULES", "RULES", "RULES"]
    # PATTERNS / ENERGY never show up here.
    crs = {r.section for r in diag.control_rule_rows}
    assert "PATTERNS" not in crs
    assert "ENERGY" not in crs


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
def test_rejected_status_rows_still_raise_with_controls_present(
    tmp_path: Path, status_block: str
) -> None:
    """Sprint 25 does not soften Sprint 22 ``[STATUS]`` rejections — a
    file mixing a rejected status row with ``[CONTROLS]`` still raises,
    and no partial diagnostics leak out.
    """
    text = _baseline_inp(
        status_block + "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
    )
    path = _write(tmp_path, "rejected_with_controls.inp", text)
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
    Sprint 25 control/rule row diagnostics. The smoke check only
    confirms the API returns an :class:`EpanetImportDiagnostics`
    container without raising, and that any records (typically none)
    carry the right shape. When WNTR is not installed the test skips.
    """
    pytest.importorskip("wntr")
    text = _baseline_inp(
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
    )
    path = _write(tmp_path, "wntr_ctrls.inp", text)
    diag = load_inp_diagnostics(path, parser="wntr")
    assert isinstance(diag, EpanetImportDiagnostics)
    # The WNTR back-end's per-row handling is documented as
    # fallback-authoritative; the adapter leaves control_rule_rows empty.
    # We only enforce shape — any records returned must be valid records.
    assert diag.control_rule_rows == ()
    for rec in diag.control_rule_rows:
        assert isinstance(rec, EpanetControlRuleDiagnostic)
        assert rec.section in ("CONTROLS", "RULES")
