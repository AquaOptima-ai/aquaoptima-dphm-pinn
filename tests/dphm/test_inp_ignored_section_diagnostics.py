"""Sprint 24 — EPANET ``.inp`` ignored-section read-only diagnostics.

Sprint 21 documented the parser's ignored-section contract via the
public :data:`IGNORED_SECTIONS` frozenset. Sprint 23 surfaced accepted
``[STATUS] OPEN`` rows as read-only diagnostics. Sprint 24 closes the
last visibility gap on the diagnostics surface: which ``IGNORED_SECTIONS``
were actually present in the imported ``.inp`` file.

The contract:

* :class:`EpanetImportDiagnostics` gains an ``ignored_sections`` field
  carrying a ``tuple[EpanetIgnoredSectionDiagnostic, ...]``.
* Records appear in *source order* — i.e. the order each ignored
  section is first declared in the ``.inp`` file.
* Section names are normalised to upper-case (the parser already
  upper-cases section headers).
* Only sections that are both in :data:`IGNORED_SECTIONS` and present
  in the file are emitted.
* ``[STATUS]`` is never emitted as an ignored-section diagnostic —
  Sprint 22 removed it from :data:`IGNORED_SECTIONS` and accepted
  ``OPEN`` rows surface through ``status_rows`` instead.
* A section header with an empty body still counts as present.
* Records are frozen / read-only.
* Diagnostics are hydraulically inert: the loaded :class:`Network`
  is byte-for-byte identical to one loaded from a fixture with no
  ignored sections.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    EpanetImportDiagnostics,
    EpanetIgnoredSectionDiagnostic,
    Network,
    load_inp_diagnostics,
    load_network_from_inp,
)
from aquaoptima.dphm.inp_io import IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _baseline_inp(extra: str = "") -> str:
    """A small loop fixture; ``extra`` is injected just before ``[END]``."""
    return (
        "[TITLE]\n"
        "Sprint 24 ignored-section diagnostics fixture\n"
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


def _no_title_inp(extra: str = "") -> str:
    """A baseline fixture with NO ``[TITLE]`` so the only ignored section
    naturally present is ``[END]``. Useful for the "no ignored sections
    declared" path.
    """
    return (
        "[JUNCTIONS]\n"
        " J1   0.0   10.0\n"
        " J2   0.0   15.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   R1   J1   300.0   250.0   130.0   0.0   OPEN\n"
        " P2   J1   J2   250.0   200.0   130.0   0.0   OPEN\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{extra}"
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


def test_ignored_section_diagnostic_is_dataclass() -> None:
    assert dataclasses.is_dataclass(EpanetIgnoredSectionDiagnostic)


def test_ignored_section_diagnostic_is_frozen() -> None:
    """Records must be immutable so callers cannot mutate read-only
    diagnostics.
    """
    rec = EpanetIgnoredSectionDiagnostic(section="CONTROLS", row_count=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.section = "RULES"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.row_count = 0  # type: ignore[misc]


def test_ignored_section_diagnostic_defaults() -> None:
    rec = EpanetIgnoredSectionDiagnostic(section="CONTROLS", row_count=2)
    assert rec.section == "CONTROLS"
    assert rec.row_count == 2
    assert "ignored" in rec.message.lower()


def test_diagnostics_container_has_ignored_sections_field() -> None:
    """``EpanetImportDiagnostics`` exposes both ``status_rows`` and
    ``ignored_sections`` and defaults the new field to an empty tuple
    so Sprint 23 callers stay backwards-compatible.
    """
    container = EpanetImportDiagnostics()
    assert container.status_rows == ()
    assert container.ignored_sections == ()


def test_diagnostics_container_is_frozen_for_ignored_sections() -> None:
    container = EpanetImportDiagnostics(
        ignored_sections=(
            EpanetIgnoredSectionDiagnostic(section="CONTROLS", row_count=1),
        )
    )
    assert isinstance(container.ignored_sections, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.ignored_sections = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Empty / absent cases
# ---------------------------------------------------------------------------


def test_diagnostics_empty_when_no_ignored_sections(tmp_path: Path) -> None:
    """A fixture with no ignored-section headers anywhere produces no
    ignored-section diagnostics.
    """
    path = _write(tmp_path, "loop_no_ignored.inp", _no_title_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.ignored_sections == ()


def test_baseline_emits_title_and_end_diagnostics(tmp_path: Path) -> None:
    """The baseline fixture declares ``[TITLE]`` and ``[END]`` — both are
    ignored sections, so both should appear in the diagnostics tuple.
    """
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.ignored_sections]
    assert "TITLE" in sections
    assert "END" in sections


# ---------------------------------------------------------------------------
# Single ignored-section presence
# ---------------------------------------------------------------------------


def test_diagnostics_record_controls_section(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        " LINK P2 OPEN AT TIME 0\n"
    )
    path = _write(tmp_path, "with_controls.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    by_section = {r.section: r for r in diag.ignored_sections}
    assert "CONTROLS" in by_section
    assert by_section["CONTROLS"].row_count == 2


def test_diagnostics_record_empty_controls_section(tmp_path: Path) -> None:
    """A bare ``[CONTROLS]`` header (no body) still surfaces as present
    because the file declared the section.
    """
    text = _baseline_inp("[CONTROLS]\n")
    path = _write(tmp_path, "empty_controls.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    by_section = {r.section: r for r in diag.ignored_sections}
    assert "CONTROLS" in by_section
    assert by_section["CONTROLS"].row_count == 0


@pytest.mark.parametrize(
    "section_name, body",
    [
        ("CONTROLS", " LINK P1 CLOSED IF NODE J1 BELOW 10\n"),
        ("RULES", " RULE 1\n IF NODE J1 PRESSURE BELOW 20\n THEN LINK P1 STATUS IS CLOSED\n"),
        ("PATTERNS", " PAT1 0.7 0.8 0.9 1.0\n"),
        ("ENERGY", " GLOBAL PRICE 0.10\n"),
        ("EMITTERS", " J1 0.5\n"),
        ("QUALITY", " J1 0.0\n"),
        ("SOURCES", " J1 CONCEN 1.0\n"),
        ("REACTIONS", " Order Bulk 1\n"),
        ("MIXING", " T1 MIXED\n"),
        ("TIMES", " Duration 24:00\n"),
        ("REPORT", " Status Yes\n"),
    ],
)
def test_diagnostics_record_individual_ignored_sections(
    tmp_path: Path, section_name: str, body: str
) -> None:
    text = _baseline_inp(f"[{section_name}]\n{body}")
    path = _write(tmp_path, f"with_{section_name}.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    by_section = {r.section: r for r in diag.ignored_sections}
    assert section_name in by_section
    assert by_section[section_name].row_count >= 1


# ---------------------------------------------------------------------------
# Multiple ignored sections, deterministic ordering
# ---------------------------------------------------------------------------


def test_diagnostics_record_multiple_ignored_sections(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n"
        " RULE R1\n"
        " IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
        "[PATTERNS]\n"
        " PAT1 0.7 0.8 0.9 1.0\n"
        "[ENERGY]\n"
        " GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "multi_ignored.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.ignored_sections]
    # All four explicitly-added ignored sections must be present.
    for expected in ("CONTROLS", "RULES", "PATTERNS", "ENERGY"):
        assert expected in sections


def test_diagnostics_preserve_source_order(tmp_path: Path) -> None:
    """Records appear in the order each ignored section is first
    declared in the source file.
    """
    text = _baseline_inp(
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n THEN LINK P2 STATUS IS CLOSED\n"
    )
    path = _write(tmp_path, "ordered_ignored.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.ignored_sections]
    # Filter to just the four ignored sections we appended (the baseline
    # also declares [TITLE] and [END] which appear at the file edges).
    explicit = [s for s in sections if s in {"ENERGY", "CONTROLS", "PATTERNS", "RULES"}]
    assert explicit == ["ENERGY", "CONTROLS", "PATTERNS", "RULES"]


def test_diagnostics_repeated_section_collapsed_to_single_record(
    tmp_path: Path,
) -> None:
    """``_split_sections`` already deduplicates repeated headers into one
    section bucket, so repeated ``[CONTROLS]`` blocks must collapse to a
    single diagnostic record whose ``row_count`` reflects the total.
    """
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[CONTROLS]\n"
        " LINK P2 OPEN AT TIME 0\n"
    )
    path = _write(tmp_path, "repeated_controls.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    controls = [r for r in diag.ignored_sections if r.section == "CONTROLS"]
    assert len(controls) == 1
    assert controls[0].row_count == 2


# ---------------------------------------------------------------------------
# STATUS is NOT an ignored section (Sprint 22) — must never appear here
# ---------------------------------------------------------------------------


def test_status_section_never_in_ignored_diagnostics(tmp_path: Path) -> None:
    """``[STATUS]`` is not in :data:`IGNORED_SECTIONS` from Sprint 22
    onwards. A file that declares ``[STATUS] OPEN`` should surface the
    accepted row through ``status_rows`` — never through
    ``ignored_sections``.
    """
    text = _baseline_inp("[STATUS]\n P1 OPEN\n")
    path = _write(tmp_path, "status_open.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    ignored_names = {r.section for r in diag.ignored_sections}
    assert "STATUS" not in ignored_names
    # And the OPEN row surfaces through status_rows as Sprint 23 contract.
    assert [r.link_id for r in diag.status_rows] == ["P1"]


def test_status_section_excluded_even_when_other_ignored_sections_present(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[STATUS]\n P1 OPEN\n"
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE 1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
    )
    path = _write(tmp_path, "status_with_others.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.ignored_sections}
    assert "STATUS" not in sections
    assert "CONTROLS" in sections
    assert "RULES" in sections


# ---------------------------------------------------------------------------
# Active hydraulic sections never appear as ignored
# ---------------------------------------------------------------------------


def test_hydraulically_active_sections_not_in_ignored_diagnostics(
    tmp_path: Path,
) -> None:
    """``[JUNCTIONS]``, ``[PIPES]``, ``[OPTIONS]``, ``[CURVES]``, etc.
    must never appear as ignored-section diagnostics — they are
    consumed by the parser, not dropped.
    """
    path = _write(tmp_path, "baseline.inp", _baseline_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.ignored_sections}
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


# ---------------------------------------------------------------------------
# Sections surfaced are exactly the IGNORED_SECTIONS that are present
# ---------------------------------------------------------------------------


def test_emitted_diagnostics_are_subset_of_ignored_sections(
    tmp_path: Path,
) -> None:
    text = _baseline_inp(
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE 1\n IF NODE J1 PRESSURE BELOW 20\n THEN LINK P2 STATUS IS CLOSED\n"
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "many.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    for rec in diag.ignored_sections:
        assert rec.section in IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Hydraulic-inertness proofs
# ---------------------------------------------------------------------------


def test_ignored_section_diagnostics_do_not_change_network(tmp_path: Path) -> None:
    """Adding ``[CONTROLS]`` / ``[RULES]`` / ``[PATTERNS]`` / ``[ENERGY]``
    must leave the loaded :class:`Network` byte-for-byte identical to
    the baseline. The diagnostics are a side channel; the Sprint 21
    invariance contract still holds.
    """
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_ignored.inp",
        _baseline_inp(
            "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
            "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
            " THEN LINK P2 STATUS IS CLOSED\n"
            "[PATTERNS]\n PAT1 0.5 0.6\n"
            "[ENERGY]\n GLOBAL PRICE 0.10\n"
        ),
    )
    net_baseline = load_network_from_inp(baseline_path, parser="fallback")
    net_perturbed = load_network_from_inp(perturbed_path, parser="fallback")
    _assert_networks_identical(net_baseline, net_perturbed)


def test_return_diagnostics_network_matches_default_load(tmp_path: Path) -> None:
    """The ``Network`` returned by ``return_diagnostics=True`` is the
    same one returned by the default ``load_network_from_inp(path)``.
    """
    path = _write(
        tmp_path,
        "loop_controls.inp",
        _baseline_inp("[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"),
    )
    default_net = load_network_from_inp(path, parser="fallback")
    net, diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert isinstance(net, Network)
    assert isinstance(diag, EpanetImportDiagnostics)
    _assert_networks_identical(default_net, net)
    sections = {r.section for r in diag.ignored_sections}
    assert "CONTROLS" in sections


def test_default_load_network_from_inp_still_returns_only_network(
    tmp_path: Path,
) -> None:
    """``load_network_from_inp(path)`` without ``return_diagnostics``
    must continue to return a bare :class:`Network` even when ignored
    sections are present.
    """
    path = _write(
        tmp_path,
        "loop_controls.inp",
        _baseline_inp("[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"),
    )
    result = load_network_from_inp(path, parser="fallback")
    assert isinstance(result, Network)


# ---------------------------------------------------------------------------
# Combined status + ignored-section diagnostics
# ---------------------------------------------------------------------------


def test_status_and_ignored_section_diagnostics_coexist(tmp_path: Path) -> None:
    text = _baseline_inp(
        "[STATUS]\n P1 OPEN\n P2 OPEN\n"
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P3 STATUS IS CLOSED\n"
    )
    path = _write(tmp_path, "both.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    # Sprint 23 status diagnostics unchanged.
    assert [r.link_id for r in diag.status_rows] == ["P1", "P2"]
    # Sprint 24 ignored-section diagnostics include CONTROLS and RULES.
    sections = {r.section for r in diag.ignored_sections}
    assert "CONTROLS" in sections
    assert "RULES" in sections


# ---------------------------------------------------------------------------
# CONTROLS / RULES remain ignored (not implemented)
# ---------------------------------------------------------------------------


def test_controls_remain_ignored_not_enforced(tmp_path: Path) -> None:
    """Sprint 24 only surfaces visibility — ``[CONTROLS]`` rules that
    would close a link are still dropped on the floor at parse time.
    """
    from aquaoptima.dphm import newton_solve

    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    controls_path = _write(
        tmp_path,
        "with_controls.inp",
        _baseline_inp("[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 99999\n"),
    )
    net_base = load_network_from_inp(baseline_path, parser="fallback")
    net_ctrl = load_network_from_inp(controls_path, parser="fallback")
    _assert_networks_identical(net_base, net_ctrl)
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


# ---------------------------------------------------------------------------
# Sprint 22 / 23 rejection behaviour still raises
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
def test_rejected_status_rows_still_raise(
    tmp_path: Path, status_block: str
) -> None:
    """Adding ``[CONTROLS]`` (Sprint 24) does not soften Sprint 22's
    rejection of status-changing or invalid ``[STATUS]`` rows.
    """
    text = _baseline_inp(
        status_block + "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
    )
    path = _write(tmp_path, "rejected.inp", text)
    with pytest.raises(ValueError):
        load_inp_diagnostics(path, parser="fallback")
    with pytest.raises(ValueError):
        load_network_from_inp(
            path, parser="fallback", return_diagnostics=True
        )


# ---------------------------------------------------------------------------
# Parser selector
# ---------------------------------------------------------------------------


def test_load_inp_diagnostics_accepts_fallback_parser_for_ignored(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        "fb.inp",
        _baseline_inp("[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"),
    )
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = {r.section for r in diag.ignored_sections}
    assert "CONTROLS" in sections


# ---------------------------------------------------------------------------
# Optional WNTR back-end smoke check
# ---------------------------------------------------------------------------


def test_wntr_back_end_returns_container_without_raising(
    tmp_path: Path,
) -> None:
    """The WNTR back-end is documented as fallback-authoritative for
    Sprint 24 ignored-section diagnostics. The smoke check only
    confirms the API returns an :class:`EpanetImportDiagnostics`
    container without raising. When WNTR is not installed the test
    skips.
    """
    pytest.importorskip("wntr")
    text = _baseline_inp(
        "[TIMES]\n Duration 24:00\n"
        "[REPORT]\n Status Yes\n"
    )
    path = _write(tmp_path, "wntr_ignored.inp", text)
    diag = load_inp_diagnostics(path, parser="wntr")
    assert isinstance(diag, EpanetImportDiagnostics)
    # The WNTR back-end's ignored-section handling is documented as
    # fallback-authoritative. We do not require parity; only that the
    # records returned (if any) have the right shape.
    for rec in diag.ignored_sections:
        assert isinstance(rec, EpanetIgnoredSectionDiagnostic)
        assert rec.section in IGNORED_SECTIONS
