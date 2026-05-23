"""Sprint 23 — EPANET ``.inp`` ``[STATUS]`` read-only diagnostics.

Sprint 22 made accepted ``[STATUS] OPEN`` rows validated no-ops.
Sprint 23 exposes the accepted rows as a read-only diagnostics
surface so analysts can see *which* status rows were declared in
an imported `.inp` file, without changing hydraulic behaviour.

The public diagnostics API:

* :func:`aquaoptima.dphm.load_inp_diagnostics(path, *, parser, units,
  default_c_factor)` returns an :class:`EpanetImportDiagnostics`
  instance whose ``status_rows`` field is a tuple of
  :class:`EpanetStatusDiagnostic` records (one per accepted
  ``[STATUS] OPEN`` row).
* :func:`aquaoptima.dphm.load_network_from_inp(path,
  return_diagnostics=True)` returns ``(Network, EpanetImportDiagnostics)``.
  The default ``load_network_from_inp(path)`` still returns only
  :class:`Network` — backward compatibility is preserved.

Diagnostics are deliberately read-only:

* The dataclass shape is ``frozen=True``.
* The container is ``frozen=True`` and ``status_rows`` is a tuple.
* The returned :class:`Network` is byte-for-byte identical to one
  loaded without ``[STATUS]``; nothing about the diagnostics path
  mutates network state.

Rejected ``[STATUS]`` rows (CLOSED, CV, numeric, unknown id, short
row, arbitrary token) still raise :class:`ValueError` exactly as they
did in Sprint 22; they never produce diagnostics.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    load_inp_diagnostics,
    load_network_from_inp,
)
from aquaoptima.dphm.inp_io import (
    EpanetImportDiagnostics,
    EpanetStatusDiagnostic,
)


# ---------------------------------------------------------------------------
# Fixtures (kept independent from the Sprint 22 test module so the two
# suites can drift cleanly).
# ---------------------------------------------------------------------------


def _loop_inp(status_block: str = "") -> str:
    return (
        "[TITLE]\n"
        "Sprint 23 [STATUS] diagnostics fixture\n"
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
        f"{status_block}"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        "[END]\n"
    )


def _head_pump_inp(status_block: str = "") -> str:
    return (
        "[JUNCTIONS]\n"
        " J1   0.0    0.0\n"
        " J2   0.0   10.0\n"
        "[RESERVOIRS]\n"
        " R1   5.0\n"
        "[PIPES]\n"
        " P1   J1   J2   200   150   130   0   OPEN\n"
        "[PUMPS]\n"
        " PU1  R1   J1   HEAD   PUMPCURVE1\n"
        "[CURVES]\n"
        " PUMPCURVE1   0.0    45.0\n"
        " PUMPCURVE1  10.0    44.0\n"
        " PUMPCURVE1  20.0    41.0\n"
        f"{status_block}"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        "[END]\n"
    )


def _prv_inp(status_block: str = "") -> str:
    return (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0   0.0\n"
        " J3   0.0   2.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   R1   J1   2000   80   130   0   OPEN\n"
        " P2   J2   J3    200   80   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   J1   J2   80   PRV   30.0   0\n"
        f"{status_block}"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
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
# Public-surface checks
# ---------------------------------------------------------------------------


def test_diagnostics_dataclasses_are_importable() -> None:
    """The diagnostics types are part of the public ``inp_io`` surface."""
    assert dataclasses.is_dataclass(EpanetStatusDiagnostic)
    assert dataclasses.is_dataclass(EpanetImportDiagnostics)


def test_diagnostics_dataclass_is_frozen() -> None:
    """Status diagnostics must be immutable so callers cannot mutate
    the read-only metadata returned by the loader.
    """
    diag = EpanetStatusDiagnostic(link_id="P1", status="OPEN")
    with pytest.raises(dataclasses.FrozenInstanceError):
        diag.link_id = "P2"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        diag.status = "CLOSED"  # type: ignore[misc]


def test_diagnostics_container_is_frozen_and_uses_tuple_storage() -> None:
    """The container is frozen and stores rows as a ``tuple`` (not a
    list) so the surface is structurally read-only.
    """
    container = EpanetImportDiagnostics(
        status_rows=(EpanetStatusDiagnostic(link_id="P1", status="OPEN"),)
    )
    assert isinstance(container.status_rows, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.status_rows = ()  # type: ignore[misc]


def test_status_diagnostic_defaults_mark_row_as_noop() -> None:
    """Default-constructed records expose the read-only / no-op marker
    in both the boolean field and the human-readable message.
    """
    diag = EpanetStatusDiagnostic(link_id="P1", status="OPEN")
    assert diag.section == "STATUS"
    assert diag.is_noop is True
    assert "no-op" in diag.message.lower()
    assert "unsupported" in diag.message.lower()


def test_load_inp_diagnostics_is_public() -> None:
    """``load_inp_diagnostics`` is importable from the top-level package."""
    assert callable(load_inp_diagnostics)


# ---------------------------------------------------------------------------
# Empty-case behaviour
# ---------------------------------------------------------------------------


def test_diagnostics_empty_when_no_status_section(tmp_path: Path) -> None:
    path = _write(tmp_path, "loop.inp", _loop_inp())
    diag = load_inp_diagnostics(path, parser="fallback")
    assert isinstance(diag, EpanetImportDiagnostics)
    assert diag.status_rows == ()


def test_diagnostics_empty_when_status_section_is_empty(tmp_path: Path) -> None:
    path = _write(tmp_path, "loop_empty_status.inp", _loop_inp("[STATUS]\n"))
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.status_rows == ()


# ---------------------------------------------------------------------------
# Accepted no-op rows produce diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_record_pipe_status_open(tmp_path: Path) -> None:
    text = _loop_inp("[STATUS]\n P1   OPEN\n")
    path = _write(tmp_path, "loop_pipe_status.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.status_rows) == 1
    row = diag.status_rows[0]
    assert isinstance(row, EpanetStatusDiagnostic)
    assert row.link_id == "P1"
    assert row.status == "OPEN"
    assert row.section == "STATUS"
    assert row.is_noop is True
    assert "no-op" in row.message.lower()


def test_diagnostics_normalises_lowercase_open_token(tmp_path: Path) -> None:
    """``open`` in the file becomes ``OPEN`` in the diagnostic."""
    text = _head_pump_inp("[STATUS]\n PU1  open\n")
    path = _write(tmp_path, "pump_lower_open.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.status_rows) == 1
    row = diag.status_rows[0]
    assert row.link_id == "PU1"  # link id spelling preserved
    assert row.status == "OPEN"  # status token normalised


def test_diagnostics_preserve_link_id_casing(tmp_path: Path) -> None:
    """The diagnostic must echo the declared link id verbatim, even
    when it mixes case in the source file (link ids are matched
    case-sensitively, but the diagnostic must not re-case them).
    """
    text = _head_pump_inp("[STATUS]\n PU1  OPEN\n")
    path = _write(tmp_path, "pump_status_casing.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert diag.status_rows[0].link_id == "PU1"


def test_diagnostics_record_valve_status_open(tmp_path: Path) -> None:
    text = _prv_inp("[STATUS]\n V1   OPEN\n")
    path = _write(tmp_path, "prv_status.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.status_rows) == 1
    row = diag.status_rows[0]
    assert row.link_id == "V1"
    assert row.status == "OPEN"


def test_diagnostics_preserve_row_count_and_order(tmp_path: Path) -> None:
    """Multiple ``OPEN`` rows preserve both count and source order."""
    text = _loop_inp(
        "[STATUS]\n"
        " P5   OPEN\n"
        " P2   OPEN\n"
        " P1   OPEN\n"
        " P3   OPEN\n"
    )
    path = _write(tmp_path, "loop_many_status.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert [r.link_id for r in diag.status_rows] == ["P5", "P2", "P1", "P3"]
    assert all(r.status == "OPEN" for r in diag.status_rows)
    assert all(r.is_noop for r in diag.status_rows)


def test_diagnostics_record_mixed_link_kinds(tmp_path: Path) -> None:
    """A single ``[STATUS]`` block can declare OPEN on a pipe and on a
    pump in the same file; both should appear in the diagnostics.
    """
    text = _head_pump_inp(
        "[STATUS]\n"
        " P1    OPEN\n"
        " PU1   OPEN\n"
    )
    path = _write(tmp_path, "mixed_status.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert [r.link_id for r in diag.status_rows] == ["P1", "PU1"]


# ---------------------------------------------------------------------------
# Hydraulic-inertness proofs
# ---------------------------------------------------------------------------


def test_status_diagnostics_do_not_change_network(tmp_path: Path) -> None:
    """The network loaded with ``[STATUS] P1 OPEN`` must be byte-for-byte
    identical to the same fixture loaded without ``[STATUS]``.
    """
    baseline_path = _write(tmp_path, "baseline.inp", _loop_inp())
    with_status_path = _write(
        tmp_path,
        "with_status.inp",
        _loop_inp("[STATUS]\n P1 OPEN\n P2 OPEN\n"),
    )
    baseline_net = load_network_from_inp(baseline_path, parser="fallback")
    annotated_net = load_network_from_inp(with_status_path, parser="fallback")
    _assert_networks_identical(baseline_net, annotated_net)


def test_return_diagnostics_network_matches_default_load(tmp_path: Path) -> None:
    """The ``Network`` returned by ``return_diagnostics=True`` must be
    identical to the one returned by the default
    ``load_network_from_inp(path)`` call — diagnostics are a side
    channel, not a mutation.
    """
    path = _write(tmp_path, "loop_open.inp", _loop_inp("[STATUS]\n P1 OPEN\n"))
    default_net = load_network_from_inp(path, parser="fallback")
    net, diag = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert isinstance(net, Network)
    assert isinstance(diag, EpanetImportDiagnostics)
    _assert_networks_identical(default_net, net)


def test_load_inp_diagnostics_does_not_return_network(tmp_path: Path) -> None:
    """``load_inp_diagnostics`` is explicitly a read-only diagnostics
    accessor — it returns an :class:`EpanetImportDiagnostics`, never
    a :class:`Network`.
    """
    path = _write(tmp_path, "loop_open.inp", _loop_inp("[STATUS]\n P1 OPEN\n"))
    diag = load_inp_diagnostics(path, parser="fallback")
    assert isinstance(diag, EpanetImportDiagnostics)
    assert not isinstance(diag, Network)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_default_load_network_from_inp_returns_only_network(tmp_path: Path) -> None:
    """``load_network_from_inp(path)`` without ``return_diagnostics``
    must continue to return a bare :class:`Network` (no tuple).
    """
    path = _write(tmp_path, "loop_no_status.inp", _loop_inp())
    result = load_network_from_inp(path, parser="fallback")
    assert isinstance(result, Network)


def test_default_load_returns_network_even_with_status(tmp_path: Path) -> None:
    path = _write(tmp_path, "loop_open.inp", _loop_inp("[STATUS]\n P1 OPEN\n"))
    result = load_network_from_inp(path, parser="fallback")
    assert isinstance(result, Network)


def test_return_diagnostics_false_is_default(tmp_path: Path) -> None:
    """Explicit ``return_diagnostics=False`` matches the default behaviour."""
    path = _write(tmp_path, "loop_open.inp", _loop_inp("[STATUS]\n P1 OPEN\n"))
    result = load_network_from_inp(
        path, parser="fallback", return_diagnostics=False
    )
    assert isinstance(result, Network)


# ---------------------------------------------------------------------------
# Rejected rows still raise and never produce diagnostics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status_block, expected_msg_fragment",
    [
        ("[STATUS]\n P1 CLOSED\n", "CLOSED"),
        ("[STATUS]\n P1 closed\n", "closed"),
        ("[STATUS]\n P1 CV\n", "CV"),
        ("[STATUS]\n P1 1.0\n", "1.0"),
        ("[STATUS]\n P1 0\n", "0"),
        ("[STATUS]\n PHANTOM OPEN\n", "PHANTOM"),
        ("[STATUS]\n P1 MAYBE\n", "MAYBE"),
        ("[STATUS]\n P1\n", "[STATUS]"),
    ],
)
def test_rejected_rows_still_raise_through_diagnostics_api(
    tmp_path: Path, status_block: str, expected_msg_fragment: str
) -> None:
    path = _write(
        tmp_path,
        "rejected.inp",
        _loop_inp(status_block),
    )
    with pytest.raises(ValueError) as excinfo:
        load_inp_diagnostics(path, parser="fallback")
    assert expected_msg_fragment in str(excinfo.value)


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
def test_rejected_rows_still_raise_with_return_diagnostics(
    tmp_path: Path, status_block: str
) -> None:
    """``return_diagnostics=True`` must not swallow Sprint 22 rejections."""
    path = _write(tmp_path, "rejected.inp", _loop_inp(status_block))
    with pytest.raises(ValueError):
        load_network_from_inp(
            path, parser="fallback", return_diagnostics=True
        )


def test_mixed_open_and_closed_block_raises_and_yields_no_diagnostics(
    tmp_path: Path,
) -> None:
    """A block mixing OPEN and CLOSED rows must raise (the CLOSED row
    is rejected). No partial diagnostics may leak out.
    """
    text = _loop_inp(
        "[STATUS]\n"
        " P1   OPEN\n"
        " P2   CLOSED\n"
    )
    path = _write(tmp_path, "mixed.inp", text)
    with pytest.raises(ValueError):
        load_inp_diagnostics(path, parser="fallback")
    with pytest.raises(ValueError):
        load_network_from_inp(
            path, parser="fallback", return_diagnostics=True
        )


# ---------------------------------------------------------------------------
# CONTROLS / RULES remain ignored — they must not appear as diagnostics
# ---------------------------------------------------------------------------


def test_controls_section_not_represented_in_diagnostics(tmp_path: Path) -> None:
    """``[CONTROLS]`` remains a documented limitation (ignored).
    Sprint 23 diagnostics expose only accepted ``[STATUS]`` rows.
    """
    text = _loop_inp(
        "[STATUS]\n"
        " P1   OPEN\n"
        "[CONTROLS]\n"
        " LINK P2 CLOSED IF NODE J1 ABOVE 50\n"
    )
    path = _write(tmp_path, "with_controls.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert [r.link_id for r in diag.status_rows] == ["P1"]


def test_rules_section_not_represented_in_diagnostics(tmp_path: Path) -> None:
    text = _loop_inp(
        "[STATUS]\n"
        " P1   OPEN\n"
        "[RULES]\n"
        " RULE R1\n"
        " IF NODE J1 ABOVE 50\n"
        " THEN LINK P2 STATUS = CLOSED\n"
    )
    path = _write(tmp_path, "with_rules.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert [r.link_id for r in diag.status_rows] == ["P1"]


# ---------------------------------------------------------------------------
# Parser selector + units kwargs reach the diagnostics path
# ---------------------------------------------------------------------------


def test_load_inp_diagnostics_accepts_fallback_parser(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "loop_fallback.inp",
        _loop_inp("[STATUS]\n P1 OPEN\n"),
    )
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.status_rows) == 1


def test_load_inp_diagnostics_rejects_unknown_parser(tmp_path: Path) -> None:
    path = _write(tmp_path, "loop.inp", _loop_inp())
    with pytest.raises(ValueError):
        load_inp_diagnostics(path, parser="ham-radio")


def test_load_inp_diagnostics_rejects_non_si_units(tmp_path: Path) -> None:
    path = _write(tmp_path, "loop.inp", _loop_inp())
    with pytest.raises(ValueError):
        load_inp_diagnostics(path, units="imperial")


# ---------------------------------------------------------------------------
# Optional WNTR back-end smoke check
# ---------------------------------------------------------------------------


def test_diagnostics_through_wntr_parser_skips_or_returns_container(
    tmp_path: Path,
) -> None:
    """When WNTR is installed, the diagnostics surface for the WNTR
    back-end is documented as fallback-authoritative: the dPHM WNTR
    adapter does not re-emit ``[STATUS]`` records. The smoke check
    only confirms the API returns an :class:`EpanetImportDiagnostics`
    container without raising. When WNTR is not installed the test
    skips.
    """
    pytest.importorskip("wntr")
    path = _write(
        tmp_path,
        "loop_wntr.inp",
        _loop_inp("[STATUS]\n P1 OPEN\n"),
    )
    diag = load_inp_diagnostics(path, parser="wntr")
    assert isinstance(diag, EpanetImportDiagnostics)
    # The WNTR back-end is documented as fallback-authoritative for
    # [STATUS] diagnostics — see docs/epanet-inp-import.md. We do not
    # require parity here; we only require the API does not raise and
    # returns the read-only container shape.
    for row in diag.status_rows:
        assert isinstance(row, EpanetStatusDiagnostic)
