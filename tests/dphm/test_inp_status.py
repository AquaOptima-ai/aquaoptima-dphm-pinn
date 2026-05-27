"""Sprint 22 — EPANET ``.inp`` ``[STATUS]`` row handling.

Sprint 22 narrows the Sprint 21 ignored-section contract for
``[STATUS]``: the fallback parser now actively validates ``[STATUS]``
rows. Explicit ``<link_id> OPEN`` rows (case-insensitive, extra
whitespace tolerated) are accepted as redundant no-ops on top of the
parser's default "every link is open" assumption; ``CLOSED``, ``CV``,
numeric pump speed/status declarations, and any other unsupported
token raise :class:`ValueError`. Unknown link ids also raise.

This module pins the Sprint 22 contract:

* the public :data:`IGNORED_SECTIONS` no longer advertises ``STATUS``
  as a global no-op (covered by ``test_inp_ignored_sections.py`` too);
* ``<id> OPEN`` rows on pipes, pumps, and PRV/TCV valves load and
  produce a :class:`Network` identical to the same fixture with no
  ``[STATUS]`` section;
* status tokens are case-insensitive and extra whitespace is
  tolerated;
* multiple ``OPEN`` rows are accepted;
* the ``[STATUS]`` section may appear before or after the link
  sections — validation runs after every link is known;
* unknown link ids raise with the id in the message;
* short rows (< 2 tokens) raise;
* ``CLOSED``, ``CV``, numeric pump speed/status, and arbitrary tokens
  raise with the link id and offending token in the message;
* the existing per-row ``[PIPES] ... CLOSED`` / ``CV`` rejection in
  the pipe loop is unchanged;
* ``[CONTROLS]`` / ``[RULES]`` remain ignored (Sprint 21 documented
  limitation);
* ``[CURVES]`` HEAD-curve pump behaviour remains active.

The tests are dependency-free for the fallback path; the optional
WNTR-back-end behaviour around ``[STATUS]`` is documented in
``docs/epanet-inp-import.md`` and ``SPRINT22_REPORT.md`` rather than
asserted here (WNTR has its own [STATUS] parser).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import load_network_from_inp
from aquaoptima.dphm.inp_io import IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Baseline fixtures
# ---------------------------------------------------------------------------


def _loop_inp(status_block: str = "") -> str:
    """Five-node loop network identical to the Sprint 21 baseline."""
    return (
        "[TITLE]\n"
        "Sprint 22 [STATUS] baseline fixture\n"
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
    """Reservoir-pump-junction fixture with one HEAD curve and a pump id."""
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


def _tcv_inp(status_block: str = "") -> str:
    return (
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0  15.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   J1   J2   200   150   130   0   OPEN\n"
        "[VALVES]\n"
        " V1   R1   J1   150   TCV   2.5   0\n"
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


def _assert_networks_identical(a, b) -> None:
    """Same byte-for-byte equality check used by the Sprint 21 tests."""
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


def test_status_no_longer_in_ignored_sections() -> None:
    """Sprint 22: ``STATUS`` was removed from :data:`IGNORED_SECTIONS`
    because the section is now actively validated. A regression here
    would mean the validator silently never runs.
    """
    assert "STATUS" not in IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Accepted no-op behaviour
# ---------------------------------------------------------------------------


def test_status_open_on_pipe_is_no_op(tmp_path: Path) -> None:
    """``[STATUS] P1 OPEN`` on an existing pipe loads and produces a
    network byte-for-byte identical to the no-status baseline.
    """
    baseline = _loop_inp()
    with_status = _loop_inp(
        "[STATUS]\n"
        " P1 OPEN\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "pipe_baseline.inp", baseline), parser="fallback"
    )
    net_status = load_network_from_inp(
        _write(tmp_path, "pipe_with_status.inp", with_status),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_status)


def test_status_open_on_pump_is_no_op(tmp_path: Path) -> None:
    """``[STATUS] PU1 OPEN`` on a HEAD-curve pump loads identically to
    the no-status fixture.
    """
    baseline = _head_pump_inp()
    with_status = _head_pump_inp(
        "[STATUS]\n"
        " PU1 OPEN\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "pump_baseline.inp", baseline), parser="fallback"
    )
    net_status = load_network_from_inp(
        _write(tmp_path, "pump_with_status.inp", with_status),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_status)


def test_status_open_on_prv_valve_is_no_op(tmp_path: Path) -> None:
    """``[STATUS] V1 OPEN`` on a PRV valve loads identically (the PRV
    pressure-boundary surrogate is unchanged).
    """
    baseline = _prv_inp()
    with_status = _prv_inp(
        "[STATUS]\n"
        " V1 OPEN\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "prv_baseline.inp", baseline), parser="fallback"
    )
    net_status = load_network_from_inp(
        _write(tmp_path, "prv_with_status.inp", with_status),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_status)


def test_status_open_on_tcv_valve_is_no_op(tmp_path: Path) -> None:
    """``[STATUS] V1 OPEN`` on a TCV valve loads identically (the TCV
    resistance surrogate is unchanged).
    """
    baseline = _tcv_inp()
    with_status = _tcv_inp(
        "[STATUS]\n"
        " V1 OPEN\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "tcv_baseline.inp", baseline), parser="fallback"
    )
    net_status = load_network_from_inp(
        _write(tmp_path, "tcv_with_status.inp", with_status),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_status)


@pytest.mark.parametrize("status_word", ["OPEN", "open", "Open", "OpEn"])
def test_status_token_is_case_insensitive(
    tmp_path: Path, status_word: str
) -> None:
    """The status token is normalised to upper-case before comparison;
    every spelling of ``OPEN`` is accepted as a no-op.
    """
    baseline = _loop_inp()
    with_status = _loop_inp(
        "[STATUS]\n"
        f" P1 {status_word}\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, f"case_baseline_{status_word}.inp", baseline),
        parser="fallback",
    )
    net_status = load_network_from_inp(
        _write(tmp_path, f"case_with_status_{status_word}.inp", with_status),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_status)


def test_status_extra_whitespace_is_tolerated(tmp_path: Path) -> None:
    """Extra whitespace between tokens / inside the row is collapsed by
    :func:`_split_sections`; the validator must accept the same shape.
    """
    baseline = _loop_inp()
    with_status = _loop_inp(
        "[STATUS]\n"
        "    P1    OPEN   \n"
        "\t  P2  \tOPEN\t\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "ws_baseline.inp", baseline), parser="fallback"
    )
    net_status = load_network_from_inp(
        _write(tmp_path, "ws_with_status.inp", with_status),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_status)


def test_status_multiple_open_rows_accepted(tmp_path: Path) -> None:
    """All five pipes of the loop fixture declared ``OPEN`` in a single
    ``[STATUS]`` block must load identically.
    """
    baseline = _loop_inp()
    with_status = _loop_inp(
        "[STATUS]\n"
        " P1 OPEN\n"
        " P2 OPEN\n"
        " P3 OPEN\n"
        " P4 OPEN\n"
        " P5 OPEN\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "multi_baseline.inp", baseline), parser="fallback"
    )
    net_status = load_network_from_inp(
        _write(tmp_path, "multi_with_status.inp", with_status),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_status)


# ---------------------------------------------------------------------------
# Position invariance: [STATUS] before vs. after the link sections
# ---------------------------------------------------------------------------


def test_status_before_pipes_section_validates_against_known_links(
    tmp_path: Path,
) -> None:
    """The ``[STATUS]`` section can be placed before the link sections
    in the file; validation runs after every link is known, so the
    order does not matter.
    """
    text = (
        "[STATUS]\n"
        " P1 OPEN\n"
        " P2 OPEN\n"
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
        "[END]\n"
    )
    no_status = (
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
        "[END]\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "pre_baseline.inp", no_status), parser="fallback"
    )
    net_pre = load_network_from_inp(
        _write(tmp_path, "pre_with_status.inp", text), parser="fallback"
    )
    _assert_networks_identical(net_base, net_pre)


def test_status_after_link_sections_still_validates(tmp_path: Path) -> None:
    """``[STATUS]`` placed after every link section (the most common
    EPANET layout) loads identically to the no-status baseline.
    """
    baseline = _loop_inp()
    after = _loop_inp(
        "[STATUS]\n"
        " P5 OPEN\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "after_baseline.inp", baseline), parser="fallback"
    )
    net_after = load_network_from_inp(
        _write(tmp_path, "after_with_status.inp", after), parser="fallback"
    )
    _assert_networks_identical(net_base, net_after)


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------


def test_status_unknown_link_id_raises(tmp_path: Path) -> None:
    """A ``[STATUS]`` row that references a link id the fixture never
    declared raises with the id and ``[STATUS]`` in the message.
    """
    text = _loop_inp(
        "[STATUS]\n"
        " QQQ_unknown OPEN\n"
    )
    path = _write(tmp_path, "unknown_id.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "[STATUS]" in msg
    assert "QQQ_unknown" in msg


def test_status_short_row_raises(tmp_path: Path) -> None:
    """A ``[STATUS]`` row with only a link id (no status token) raises
    a clear shape error.
    """
    text = _loop_inp(
        "[STATUS]\n"
        " P1\n"
    )
    path = _write(tmp_path, "short_row.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "[STATUS]" in msg
    assert "at least 2 tokens" in msg


def test_status_closed_token_raises(tmp_path: Path) -> None:
    """``CLOSED`` is explicitly rejected — the steady-state core does
    not model closed links.
    """
    text = _loop_inp(
        "[STATUS]\n"
        " P1 CLOSED\n"
    )
    path = _write(tmp_path, "closed.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "[STATUS]" in msg
    assert "P1" in msg
    assert "CLOSED" in msg


def test_status_closed_token_is_case_insensitive_for_rejection(
    tmp_path: Path,
) -> None:
    """``closed`` (lower case) is rejected too — case-folding must not
    accidentally swallow a closed-link declaration.
    """
    text = _loop_inp(
        "[STATUS]\n"
        " P1 closed\n"
    )
    path = _write(tmp_path, "closed_lc.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "[STATUS]" in msg
    assert "P1" in msg
    # The original-case token is echoed in the message so the user can
    # find the row in their source file.
    assert "closed" in msg.lower()


def test_status_cv_token_raises(tmp_path: Path) -> None:
    """``CV`` (check valve) is rejected — the steady-state core does not
    model check valves as a unilateral-flow edge.
    """
    text = _loop_inp(
        "[STATUS]\n"
        " P1 CV\n"
    )
    path = _write(tmp_path, "cv.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "[STATUS]" in msg
    assert "P1" in msg
    assert "CV" in msg


def test_status_numeric_pump_speed_raises(tmp_path: Path) -> None:
    """A numeric pump speed/status (e.g. ``PU1 1.0``) is rejected with
    a message naming the pump id and the numeric value.
    """
    text = _head_pump_inp(
        "[STATUS]\n"
        " PU1 1.0\n"
    )
    path = _write(tmp_path, "numeric_speed.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "[STATUS]" in msg
    assert "PU1" in msg
    assert "1.0" in msg


def test_status_numeric_zero_speed_raises(tmp_path: Path) -> None:
    """``PU1 0`` (off pump status) is still numeric and still rejected;
    the steady-state core does not consume per-link speed multipliers.
    """
    text = _head_pump_inp(
        "[STATUS]\n"
        " PU1 0\n"
    )
    path = _write(tmp_path, "numeric_zero.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "[STATUS]" in msg
    assert "PU1" in msg


def test_status_arbitrary_token_raises(tmp_path: Path) -> None:
    """An unrecognised non-numeric token raises with link id and token
    in the message.
    """
    text = _loop_inp(
        "[STATUS]\n"
        " P1 MAYBE_LATER\n"
    )
    path = _write(tmp_path, "arbitrary.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "[STATUS]" in msg
    assert "P1" in msg
    assert "MAYBE_LATER" in msg


def test_status_open_then_closed_raises_on_the_closed_row(
    tmp_path: Path,
) -> None:
    """A ``[STATUS]`` block that mixes an accepted ``OPEN`` row with a
    rejected ``CLOSED`` row must fail loudly on the second row — the
    validator cannot silently swallow CLOSED when another row in the
    same block is OPEN.
    """
    text = _loop_inp(
        "[STATUS]\n"
        " P1 OPEN\n"
        " P2 CLOSED\n"
    )
    path = _write(tmp_path, "mixed.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "P2" in msg
    assert "CLOSED" in msg


# ---------------------------------------------------------------------------
# Sprint 11 contract preserved: [PIPES] ... CLOSED still raises in the
# pipe row loop. The Sprint 22 [STATUS] validator must not weaken that.
# ---------------------------------------------------------------------------


def test_pipes_row_closed_status_column_still_raises(tmp_path: Path) -> None:
    """A per-row ``CLOSED`` status on a ``[PIPES]`` row continues to
    raise as it did in earlier sprints, regardless of any ``[STATUS]``
    section.
    """
    text = (
        "[JUNCTIONS]\n"
        " J1   0.0   10.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   R1   J1   300.0   250.0   130.0   0.0   CLOSED\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        "[END]\n"
    )
    path = _write(tmp_path, "pipes_closed.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "CLOSED" in msg
    assert "P1" in msg


def test_pipes_row_cv_status_column_still_raises(tmp_path: Path) -> None:
    """``CV`` on a per-row ``[PIPES]`` status column continues to raise."""
    text = (
        "[JUNCTIONS]\n"
        " J1   0.0   10.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   R1   J1   300.0   250.0   130.0   0.0   CV\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        "[END]\n"
    )
    path = _write(tmp_path, "pipes_cv.inp", text)
    with pytest.raises(ValueError) as excinfo:
        load_network_from_inp(path, parser="fallback")
    msg = str(excinfo.value)
    assert "CV" in msg
    assert "P1" in msg


# ---------------------------------------------------------------------------
# [CONTROLS] / [RULES] limitation preserved (Sprint 21)
# ---------------------------------------------------------------------------


def test_controls_still_ignored_alongside_status(tmp_path: Path) -> None:
    """A ``[CONTROLS]`` block (deferred limitation) sitting next to a
    valid Sprint 22 ``[STATUS] OPEN`` block remains a silent no-op —
    Sprint 22 does not change ``[CONTROLS]`` semantics.
    """
    baseline = _loop_inp()
    perturbed = _loop_inp(
        "[STATUS]\n"
        " P1 OPEN\n"
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 99999\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "ctrl_baseline.inp", baseline), parser="fallback"
    )
    net_with = load_network_from_inp(
        _write(tmp_path, "ctrl_with_status.inp", perturbed),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_with)


def test_rules_still_ignored_alongside_status(tmp_path: Path) -> None:
    """``[RULES]`` (deferred limitation) is still dropped on the floor
    when ``[STATUS] OPEN`` is also present.
    """
    baseline = _loop_inp()
    perturbed = _loop_inp(
        "[STATUS]\n"
        " P2 OPEN\n"
        "[RULES]\n"
        " RULE 1\n"
        " IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P1 STATUS IS CLOSED\n"
        " PRIORITY 1\n"
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "rules_baseline.inp", baseline), parser="fallback"
    )
    net_with = load_network_from_inp(
        _write(tmp_path, "rules_with_status.inp", perturbed),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_with)


# ---------------------------------------------------------------------------
# CURVES pump path unaffected
# ---------------------------------------------------------------------------


def test_head_pump_coefficients_unaffected_by_status_open_on_pump(
    tmp_path: Path,
) -> None:
    """The pump quadratic coefficients (``[a0, a1, a2]``) derived from
    the ``[CURVES]`` section are unchanged when a Sprint 22 ``[STATUS]
    PU1 OPEN`` row is added — confirming that ``[STATUS]`` validation
    does not bleed into curve resolution.
    """
    net_clean = load_network_from_inp(
        _write(tmp_path, "pump_clean.inp", _head_pump_inp()),
        parser="fallback",
    )
    net_status = load_network_from_inp(
        _write(
            tmp_path,
            "pump_status.inp",
            _head_pump_inp("[STATUS]\n PU1 OPEN\n"),
        ),
        parser="fallback",
    )
    _assert_networks_identical(net_clean, net_status)
    assert any(net_clean.pump_mask.tolist())
    pump_idx = next(
        i for i, m in enumerate(net_clean.pump_mask.tolist()) if m
    )
    a0_clean = float(net_clean.pump_coeffs[pump_idx][0].item())
    a0_status = float(net_status.pump_coeffs[pump_idx][0].item())
    assert a0_clean == pytest.approx(a0_status, abs=1e-12)
    assert a0_clean > 0.0


# ---------------------------------------------------------------------------
# Empty [STATUS] section
# ---------------------------------------------------------------------------


def test_empty_status_section_is_accepted(tmp_path: Path) -> None:
    """A bare ``[STATUS]`` header with no rows must not raise — empty
    sections are legitimate in EPANET output and the validator has
    nothing to do.
    """
    baseline = _loop_inp()
    with_empty = _loop_inp("[STATUS]\n")
    net_base = load_network_from_inp(
        _write(tmp_path, "empty_baseline.inp", baseline), parser="fallback"
    )
    net_empty = load_network_from_inp(
        _write(tmp_path, "empty_status.inp", with_empty), parser="fallback"
    )
    _assert_networks_identical(net_base, net_empty)


# ---------------------------------------------------------------------------
# Optional WNTR back-end smoke check. Sprint 22 leaves the WNTR adapter
# structurally unchanged (WNTR has its own [STATUS] parser); we only
# confirm that a fixture with ``[STATUS] P1 OPEN`` still round-trips
# cleanly through both back-ends with matching demand sums.
# ---------------------------------------------------------------------------


def test_wntr_smoke_status_open_does_not_break_back_end(
    tmp_path: Path,
) -> None:
    """The WNTR back-end parses ``[STATUS]`` internally; this smoke test
    only confirms that adding an ``OPEN`` row to a fixture WNTR is happy
    to round-trip does not perturb the dPHM-side demand sum or node/edge
    counts. WNTR's own ``[STATUS]`` behaviour is documented in
    ``docs/epanet-inp-import.md`` rather than asserted here.
    """
    pytest.importorskip("wntr")
    text = _loop_inp("[STATUS]\n P1 OPEN\n")
    path = _write(tmp_path, "wntr_smoke.inp", text)

    net_fb = load_network_from_inp(path, parser="fallback")
    net_wn = load_network_from_inp(path, parser="wntr")

    assert net_fb.num_nodes == net_wn.num_nodes
    assert net_fb.num_edges == net_wn.num_edges
    fb_sorted = sorted(net_fb.demands.tolist())
    wn_sorted = sorted(net_wn.demands.tolist())
    assert fb_sorted == pytest.approx(wn_sorted, abs=1e-7)
