"""Sprint 32 — EPANET ``.inp`` per-edge surrogate diagnostics.

Sprint 15 introduced :func:`translate_valve_to_surrogate`, which
approximates EPANET ``[VALVES]`` PRV and TCV rows as pipe-like dPHM
edges (PRV pins the downstream node as a fixed-head boundary; TCV
becomes a Hazen-Williams pipe sized to match a minor-loss head loss
at one anchor flow). Sprint 32 surfaces those translations as
:class:`EpanetEdgeSurrogateDiagnostic` records on
:class:`EpanetImportDiagnostics`, so downstream UI / API / shadow-mode
import-quality reports can flag the approximated edges and surface
their limitations.

These tests cover:

* the frozen :class:`EpanetEdgeSurrogateDiagnostic` dataclass shape;
* the four read-only accessors:
  :meth:`surrogate_edges`, :meth:`surrogate_count_by_kind`,
  :meth:`surrogates_for_link`, and :meth:`surrogate_for_edge`;
* fallback-parser population on PRV / TCV fixtures, including edge-
  index alignment with the loaded :class:`Network`;
* link-id case sensitivity and unknown-link / unknown-edge return
  semantics;
* hydraulic inertness: the loaded :class:`Network` is identical with
  or without the new diagnostic field;
* ``load_inp_diagnostics`` / ``load_network_from_inp(...,
  return_diagnostics=True)`` agreement;
* default ``load_network_from_inp`` returns only the
  :class:`Network`;
* Sprint 23–31 helpers still work alongside the new field;
* WNTR asymmetry: ``edge_surrogates`` is empty under ``parser="wntr"``.
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
    EpanetEdgeSurrogateDiagnostic,
    EpanetImportDiagnostics,
    EpanetStatusDiagnostic,
    Network,
    load_inp_diagnostics,
    load_network_from_inp,
)


# ---------------------------------------------------------------------------
# Inline INP fixture helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def _tcv_only_inp() -> str:
    """One pipe + one TCV valve. Two edges, surrogate at index 1."""
    return (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0  15.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   R1   J1   200   150   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   J1   J2   150   TCV   2.5   0\n"
        "[OPTIONS]\n"
        " Units    LPS\n"
        " Headloss H-W\n"
        "[END]\n"
    )


def _no_valves_inp() -> str:
    """Mirror of ``_tcv_only_inp`` but without the [VALVES] block."""
    return (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0  15.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   R1   J1   200   150   130   0   OPEN\n"
        " V1   J1   J2   1.0e-6   150   130   0   OPEN\n"
        "[OPTIONS]\n"
        " Units    LPS\n"
        " Headloss H-W\n"
        "[END]\n"
    )


def _prv_inp() -> str:
    """Reservoir + PRV that pins J1 to elev + setting = 0 + 30 = 30 m."""
    return (
        "[JUNCTIONS]\n"
        " J1   0.0    0.0\n"
        " J2   0.0   10.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   J1   J2   200   150   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   R1   J1   150   PRV   30.0   0\n"
        "[OPTIONS]\n"
        " Units    LPS\n"
        " Headloss H-W\n"
        "[END]\n"
    )


def _multi_valve_inp() -> str:
    """Pipe + PRV + TCV in one fixture. Edge ordering: [P1, V1(PRV), V2(TCV)]."""
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
# Dataclass shape
# ---------------------------------------------------------------------------


def test_edge_surrogate_diagnostic_is_frozen() -> None:
    rec = EpanetEdgeSurrogateDiagnostic(
        edge_index=2,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_PRV_FIXED_HEAD,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
        limitations=("a", "b"),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.edge_index = 5  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.link_id = "X"  # type: ignore[misc]


def test_edge_surrogate_diagnostic_limitations_is_tuple() -> None:
    rec = EpanetEdgeSurrogateDiagnostic(
        edge_index=0,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
        limitations=("only one",),
    )
    assert isinstance(rec.limitations, tuple)
    assert rec.limitations == ("only one",)


def test_edge_surrogate_diagnostic_default_limitations_is_empty_tuple() -> None:
    rec = EpanetEdgeSurrogateDiagnostic(
        edge_index=0,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    assert rec.limitations == ()
    assert isinstance(rec.limitations, tuple)


# ---------------------------------------------------------------------------
# Container default + helpers on empty diagnostics
# ---------------------------------------------------------------------------


def test_empty_diagnostics_has_no_surrogates() -> None:
    diag = EpanetImportDiagnostics()
    assert diag.edge_surrogates == ()
    assert diag.surrogate_edges() == ()
    assert diag.surrogate_count_by_kind() == {}
    assert diag.surrogates_for_link("V1") == ()
    assert diag.surrogate_for_edge(0) == ()


def test_surrogate_edges_returns_fresh_tuple() -> None:
    rec = EpanetEdgeSurrogateDiagnostic(
        edge_index=1,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    diag = EpanetImportDiagnostics(edge_surrogates=(rec,))
    out = diag.surrogate_edges()
    assert isinstance(out, tuple)
    assert out == (rec,)
    # Mutating an external list view never affects the container.
    listed = list(out)
    listed.clear()
    assert diag.edge_surrogates == (rec,)
    assert diag.surrogate_edges() == (rec,)


def test_surrogate_count_by_kind_returns_fresh_dict() -> None:
    rec_a = EpanetEdgeSurrogateDiagnostic(
        edge_index=1,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_PRV_FIXED_HEAD,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    rec_b = EpanetEdgeSurrogateDiagnostic(
        edge_index=2,
        link_id="V2",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    rec_c = EpanetEdgeSurrogateDiagnostic(
        edge_index=3,
        link_id="V3",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    diag = EpanetImportDiagnostics(edge_surrogates=(rec_a, rec_b, rec_c))
    counts = diag.surrogate_count_by_kind()
    assert counts == {
        EDGE_SURROGATE_KIND_PRV_FIXED_HEAD: 1,
        EDGE_SURROGATE_KIND_TCV_MINOR_LOSS: 2,
    }
    # Mutating one returned dict cannot leak into another's snapshot.
    counts["something"] = 99
    counts2 = diag.surrogate_count_by_kind()
    assert "something" not in counts2


def test_surrogates_for_link_returns_matching_records() -> None:
    rec_a = EpanetEdgeSurrogateDiagnostic(
        edge_index=1,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_PRV_FIXED_HEAD,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    rec_b = EpanetEdgeSurrogateDiagnostic(
        edge_index=2,
        link_id="V2",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    diag = EpanetImportDiagnostics(edge_surrogates=(rec_a, rec_b))
    assert diag.surrogates_for_link("V1") == (rec_a,)
    assert diag.surrogates_for_link("V2") == (rec_b,)


def test_surrogates_for_link_case_sensitive_and_unknown_returns_empty() -> None:
    rec = EpanetEdgeSurrogateDiagnostic(
        edge_index=1,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_PRV_FIXED_HEAD,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    diag = EpanetImportDiagnostics(edge_surrogates=(rec,))
    # Wrong case (EPANET ids are case-sensitive in this parser).
    assert diag.surrogates_for_link("v1") == ()
    # Unknown id.
    assert diag.surrogates_for_link("X9") == ()
    # Non-string input.
    assert diag.surrogates_for_link(None) == ()  # type: ignore[arg-type]
    assert diag.surrogates_for_link(1) == ()  # type: ignore[arg-type]


def test_surrogate_for_edge_returns_matching_record() -> None:
    rec_a = EpanetEdgeSurrogateDiagnostic(
        edge_index=1,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_PRV_FIXED_HEAD,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    rec_b = EpanetEdgeSurrogateDiagnostic(
        edge_index=2,
        link_id="V2",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    diag = EpanetImportDiagnostics(edge_surrogates=(rec_a, rec_b))
    assert diag.surrogate_for_edge(1) == (rec_a,)
    assert diag.surrogate_for_edge(2) == (rec_b,)
    # Unknown index returns ().
    assert diag.surrogate_for_edge(0) == ()
    assert diag.surrogate_for_edge(99) == ()
    # Negative index returns ().
    assert diag.surrogate_for_edge(-1) == ()


def test_surrogate_for_edge_rejects_invalid_inputs() -> None:
    rec = EpanetEdgeSurrogateDiagnostic(
        edge_index=1,
        link_id="V1",
        link_type="VALVE",
        surrogate_kind=EDGE_SURROGATE_KIND_PRV_FIXED_HEAD,
        severity=EDGE_SURROGATE_SEVERITY_LIMITATION,
        message="msg",
    )
    diag = EpanetImportDiagnostics(edge_surrogates=(rec,))
    # Non-int-like input must return () rather than raising.
    assert diag.surrogate_for_edge("1") == ()  # type: ignore[arg-type]
    assert diag.surrogate_for_edge(None) == ()  # type: ignore[arg-type]
    assert diag.surrogate_for_edge(1.0) == ()  # type: ignore[arg-type]
    assert diag.surrogate_for_edge(float("nan")) == ()  # type: ignore[arg-type]
    # bool is an int subclass in Python; we explicitly reject it.
    assert diag.surrogate_for_edge(True) == ()  # type: ignore[arg-type]
    assert diag.surrogate_for_edge(False) == ()  # type: ignore[arg-type]


def test_container_frozen_after_surrogate_field_added() -> None:
    diag = EpanetImportDiagnostics()
    with pytest.raises(dataclasses.FrozenInstanceError):
        diag.edge_surrogates = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Fallback parser populates surrogate diagnostics
# ---------------------------------------------------------------------------


def test_fallback_parser_emits_one_record_per_valve(tmp_path: Path) -> None:
    path = _write(tmp_path, "tcv.inp", _tcv_only_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.edge_surrogates) == 1
    (rec,) = diag.edge_surrogates
    assert isinstance(rec, EpanetEdgeSurrogateDiagnostic)
    assert rec.link_id == "V1"
    assert rec.link_type == "VALVE"
    assert rec.surrogate_kind == EDGE_SURROGATE_KIND_TCV_MINOR_LOSS
    assert rec.severity == EDGE_SURROGATE_SEVERITY_LIMITATION
    assert isinstance(rec.limitations, tuple) and rec.limitations
    assert isinstance(rec.message, str) and rec.message


def test_fallback_parser_emits_prv_kind_for_prv(tmp_path: Path) -> None:
    path = _write(tmp_path, "prv.inp", _prv_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.edge_surrogates) == 1
    (rec,) = diag.edge_surrogates
    assert rec.link_id == "V1"
    assert rec.surrogate_kind == EDGE_SURROGATE_KIND_PRV_FIXED_HEAD
    assert rec.severity == EDGE_SURROGATE_SEVERITY_LIMITATION


def test_fallback_edge_index_matches_network_position(tmp_path: Path) -> None:
    """The diagnostic's ``edge_index`` must point at the actual valve edge."""
    path = _write(tmp_path, "tcv.inp", _tcv_only_inp())
    net, diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    # Edge ordering: P1 (pipe, idx 0), V1 (valve, idx 1).
    assert net.num_edges == 2
    (rec,) = diag.edge_surrogates
    assert rec.edge_index == 1
    # The edge at that index must be the one the valve translator
    # produced — pipe_mask=True (valves become pipe-like), pump_mask=False,
    # endpoints from V1's J1 -> J2 row.
    assert bool(net.pipe_mask[rec.edge_index].item()) is True
    assert bool(net.pump_mask[rec.edge_index].item()) is False
    # The TCV diameter is the file's 150 mm = 0.15 m.
    assert float(net.diameters[rec.edge_index].item()) == pytest.approx(0.15)


def test_fallback_multi_valve_edge_indices_are_correct(tmp_path: Path) -> None:
    path = _write(tmp_path, "multi.inp", _multi_valve_inp())
    net, diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    # Three edges: P1 (pipe, idx 0), V1 (PRV, idx 1), V2 (TCV, idx 2).
    assert net.num_edges == 3
    assert len(diag.edge_surrogates) == 2
    # File / parse order is preserved.
    rec_prv, rec_tcv = diag.edge_surrogates
    assert rec_prv.link_id == "V1"
    assert rec_prv.surrogate_kind == EDGE_SURROGATE_KIND_PRV_FIXED_HEAD
    assert rec_prv.edge_index == 1
    assert rec_tcv.link_id == "V2"
    assert rec_tcv.surrogate_kind == EDGE_SURROGATE_KIND_TCV_MINOR_LOSS
    assert rec_tcv.edge_index == 2
    # Helpers route on the same indices.
    assert diag.surrogate_for_edge(1) == (rec_prv,)
    assert diag.surrogate_for_edge(2) == (rec_tcv,)
    assert diag.surrogates_for_link("V1") == (rec_prv,)
    assert diag.surrogates_for_link("V2") == (rec_tcv,)
    # Pipe edge has no surrogate.
    assert diag.surrogate_for_edge(0) == ()


def test_fallback_surrogate_count_by_kind_on_multi_valve(tmp_path: Path) -> None:
    path = _write(tmp_path, "multi.inp", _multi_valve_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    counts = diag.surrogate_count_by_kind()
    assert counts == {
        EDGE_SURROGATE_KIND_PRV_FIXED_HEAD: 1,
        EDGE_SURROGATE_KIND_TCV_MINOR_LOSS: 1,
    }


def test_fallback_no_valves_has_no_surrogates(tmp_path: Path) -> None:
    """A fixture without [VALVES] must emit no surrogate diagnostics."""
    path = _write(tmp_path, "novalves.inp", _no_valves_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.edge_surrogates == ()
    assert diag.surrogate_edges() == ()
    assert diag.surrogate_count_by_kind() == {}


# ---------------------------------------------------------------------------
# Hydraulic inertness
# ---------------------------------------------------------------------------


def test_network_arrays_unchanged_by_diagnostics(tmp_path: Path) -> None:
    """The Sprint 15 valve fixtures already exercised the network arrays.
    Sprint 32 adds diagnostics only — the network loaded with
    ``return_diagnostics=True`` must equal the network loaded with the
    default flag exactly, on every field the dPHM core consumes.
    """
    path = _write(tmp_path, "tcv.inp", _tcv_only_inp())
    net_only = load_network_from_inp(path, parser="fallback")
    net_with, _diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert isinstance(net_only, Network)
    assert isinstance(net_with, Network)
    assert net_only.num_nodes == net_with.num_nodes
    assert net_only.num_edges == net_with.num_edges
    assert net_only.num_fixed_heads == net_with.num_fixed_heads
    assert torch.equal(net_only.edge_index, net_with.edge_index)
    assert net_only.pipe_mask.tolist() == net_with.pipe_mask.tolist()
    assert net_only.pump_mask.tolist() == net_with.pump_mask.tolist()
    assert net_only.fixed_head_mask.tolist() == net_with.fixed_head_mask.tolist()
    for attr in (
        "demands",
        "fixed_head_values",
        "lengths",
        "diameters",
        "c_factors",
        "pump_speeds",
    ):
        a = getattr(net_only, attr).double()
        b = getattr(net_with, attr).double()
        assert torch.allclose(a, b, atol=0.0), attr


# ---------------------------------------------------------------------------
# API parity & backwards compatibility
# ---------------------------------------------------------------------------


def test_load_inp_diagnostics_and_load_network_from_inp_agree(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "multi.inp", _multi_valve_inp())
    diag_a = load_inp_diagnostics(path, parser="fallback")
    _net, diag_b = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert diag_a.edge_surrogates == diag_b.edge_surrogates
    assert diag_a.surrogate_count_by_kind() == diag_b.surrogate_count_by_kind()
    for link_id in ("V1", "V2"):
        assert diag_a.surrogates_for_link(link_id) == diag_b.surrogates_for_link(
            link_id
        )
    for idx in range(5):
        assert diag_a.surrogate_for_edge(idx) == diag_b.surrogate_for_edge(idx)


def test_default_load_network_from_inp_returns_only_network(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "multi.inp", _multi_valve_inp())
    result = load_network_from_inp(path, parser="fallback")
    assert isinstance(result, Network)


def test_sprint_23_to_31_helpers_still_work_with_new_field(
    tmp_path: Path,
) -> None:
    text = (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0  15.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   R1   J1   200   150   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   J1   J2   150   TCV   2.5   0\n"
        "[STATUS]\n"
        " P1 OPEN\n"
        "[CONTROLS]\n"
        " LINK P1 OPEN IF NODE J1 BELOW 5\n"
        "[OPTIONS]\n"
        " Units    LPS\n"
        " Headloss H-W\n"
        "[END]\n"
    )
    path = _write(tmp_path, "mixed.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    # Sprint 23 status row diagnostics still populated.
    assert len(diag.status_rows) == 1
    # Sprint 25 control row diagnostics still populated.
    assert len(diag.control_rule_rows) == 1
    # Sprint 30 / 31 helpers still work.
    counts = diag.row_count_by_section()
    assert counts.get("STATUS") == 1
    assert counts.get("CONTROLS") == 1
    summary = diag.summary()
    assert summary.status_row_count == 1
    assert summary.control_rule_row_count == 1
    # Sprint 32 surrogate field is independent of row-channel surfaces.
    assert len(diag.edge_surrogates) == 1
    assert diag.edge_surrogates[0].surrogate_kind == EDGE_SURROGATE_KIND_TCV_MINOR_LOSS


def test_status_diagnostic_construction_unaffected() -> None:
    """Sprint 23 :class:`EpanetStatusDiagnostic` shape is untouched."""
    rec = EpanetStatusDiagnostic(link_id="P1", status="OPEN")
    assert rec.link_id == "P1"
    assert rec.status == "OPEN"


# ---------------------------------------------------------------------------
# Read-only contract
# ---------------------------------------------------------------------------


def test_helpers_do_not_mutate_container(tmp_path: Path) -> None:
    path = _write(tmp_path, "multi.inp", _multi_valve_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    original = diag.edge_surrogates
    # Exercise every helper with valid and invalid inputs.
    _ = diag.surrogate_edges()
    _ = diag.surrogate_count_by_kind()
    for link in ("V1", "V2", "ghost", "", "v1"):
        _ = diag.surrogates_for_link(link)
    for idx in (-1, 0, 1, 2, 99):
        _ = diag.surrogate_for_edge(idx)
    # Container is untouched: tuple identity preserved.
    assert diag.edge_surrogates is original


# ---------------------------------------------------------------------------
# WNTR back-end asymmetry
# ---------------------------------------------------------------------------


def test_wntr_edge_surrogates_is_empty(tmp_path: Path) -> None:
    pytest.importorskip("wntr")
    path = _write(tmp_path, "tcv.inp", _tcv_only_inp())
    diag = load_inp_diagnostics(path, parser="wntr")
    assert diag.edge_surrogates == ()
    assert diag.surrogate_edges() == ()
    assert diag.surrogate_count_by_kind() == {}
    assert diag.surrogates_for_link("V1") == ()
    assert diag.surrogate_for_edge(1) == ()
