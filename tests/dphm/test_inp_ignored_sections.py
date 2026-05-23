"""Sprint 21 — EPANET ``.inp`` ignored-section no-op behaviour.

Sprint 21 makes the fallback parser's ignored-section contract
*explicit* and *tested*. The fallback parser deliberately drops every
section that is outside the current steady-state Hazen-Williams scope
— ``[TIMES]``, ``[REPORT]``, ``[CONTROLS]``, ``[RULES]``,
``[EMITTERS]``, ``[QUALITY]``, ``[SOURCES]``, ``[REACTIONS]``,
``[MIXING]``, and the inert layout sections (``[TITLE]``, ``[END]``,
``[PATTERNS]``, ``[COORDINATES]``, ``[VERTICES]``, ``[LABELS]``,
``[BACKDROP]``, ``[TAGS]``, ``[ENERGY]``, ``[DEMANDS]``).

Sprint 22 narrows the contract for ``[STATUS]``: the fallback parser
now actively validates ``[STATUS]`` rows (accepting ``<link_id> OPEN``
as a no-op, rejecting ``CLOSED`` / ``CV`` / numeric / unknown tokens),
so ``STATUS`` is **not** in :data:`IGNORED_SECTIONS` anymore. The
Sprint 22 surface is covered by ``test_inp_status.py``; this module
continues to pin the no-op contract for the remaining ignored sections.

This module pins the no-op contract:

* the public :data:`IGNORED_SECTIONS` frozenset advertises every
  target section;
* adding any ignored section (representative body, malformed body,
  or multiple bodies) to a baseline fixture leaves the loaded
  :class:`Network` byte-for-byte unchanged;
* ignored sections **before** the hydraulic sections do not block
  subsequent parsing;
* ignored sections **after** the hydraulic sections do not mutate
  the already-parsed data;
* malformed-looking rows inside ignored sections do not raise;
* ``[CURVES]`` is **not** treated as a global no-op — pump HEAD-curve
  consumption still works;
* ``[CONTROLS]`` / ``[RULES]`` rows that would close a link or flip
  a status are dropped, *not* enforced — this is the documented
  Sprint 21 limitation.

The tests are dependency-free for the fallback path; the optional
WNTR-back-end smoke test guards with :func:`pytest.importorskip`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    load_network_from_inp,
    newton_solve,
)
from aquaoptima.dphm.inp_io import IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# The nine Sprint 21 target ignored sections + a representative body
# ---------------------------------------------------------------------------

# Bodies chosen to mirror real EPANET output. The rows are NOT
# physically supported by the dPHM steady-state importer — the point
# is to confirm they are dropped on the floor.
_TARGET_SECTION_BODIES: dict[str, str] = {
    "TIMES": (
        " Duration            24:00\n"
        " Hydraulic Timestep  1:00\n"
        " Pattern Timestep    1:00\n"
    ),
    "REPORT": (
        " Status   Yes\n"
        " Summary  No\n"
        " Nodes    All\n"
        " Links    All\n"
    ),
    "CONTROLS": (
        " LINK P1 CLOSED IF NODE J1 BELOW 10\n"
    ),
    "RULES": (
        " RULE 1\n"
        " IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P1 STATUS IS CLOSED\n"
        " PRIORITY 1\n"
    ),
    "EMITTERS": (
        " J1 0.5\n"
    ),
    "QUALITY": (
        " J1 0.0\n"
        " J2 0.0\n"
    ),
    "SOURCES": (
        " J1 CONCEN 1.0\n"
    ),
    "REACTIONS": (
        " Order Bulk 1\n"
        " Global Bulk -1.0\n"
    ),
    "MIXING": (
        " T1 MIXED\n"
    ),
}


_TARGET_SECTION_NAMES: tuple[str, ...] = tuple(_TARGET_SECTION_BODIES.keys())


# ---------------------------------------------------------------------------
# Baseline fixture — a small loop network with a single fixed head
# ---------------------------------------------------------------------------


def _baseline_inp() -> str:
    """Return the canonical Sprint 11 loop INP, sans any ignored section.

    This is the invariance reference. Every Sprint 21 test loads a
    perturbed version (with one or more ignored sections injected at
    various positions) and asserts the loaded :class:`Network` is
    identical.
    """
    return (
        "[TITLE]\n"
        "Sprint 21 ignored-section baseline fixture\n"
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
        "[END]\n"
    )


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def _assert_networks_identical(a, b) -> None:
    """Network-output equality within a tight floating-point tolerance.

    The check covers everything the dPHM core actually consumes:
    node count, edge count, demands, fixed-head mask & values,
    pipe / pump masks, geometry, pump coefficients and speeds, and
    the edge index itself.

    Most fields are compared bit-exactly (``atol = 0``) because the
    parser does a single conversion per file column; the same row
    must give the same bytes. ``pump_coeffs`` is exempted with a
    tight tolerance because the underlying ``torch.linalg.lstsq``
    solve can vary at the last few ULPs across runs depending on
    multi-threaded BLAS scheduling. The tolerance ``1e-9`` is well
    below any physically meaningful coefficient drift while
    absorbing BLAS noise (observed drift on the shipped HEAD-pump
    fixture: ~1e-14 in ``a1``).
    """
    assert a.num_nodes == b.num_nodes, "node count drifted"
    assert a.num_edges == b.num_edges, "edge count drifted"
    assert a.num_fixed_heads == b.num_fixed_heads, (
        "fixed-head count drifted"
    )

    assert torch.equal(a.edge_index, b.edge_index), "edge_index drifted"
    assert a.pipe_mask.tolist() == b.pipe_mask.tolist(), "pipe_mask drifted"
    assert a.pump_mask.tolist() == b.pump_mask.tolist(), "pump_mask drifted"
    assert (
        a.fixed_head_mask.tolist() == b.fixed_head_mask.tolist()
    ), "fixed_head_mask drifted"

    # File-derived numerics — single conversion path, must agree bit-
    # for-bit.
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
        assert torch.allclose(a_t, b_t, atol=0.0), (
            f"{attr} drifted: {a_t.tolist()} != {b_t.tolist()}"
        )

    # Pump coefficients come from ``torch.linalg.lstsq`` and can vary
    # by a few ULPs across runs on multi-threaded BLAS. Use a tight
    # tolerance instead of bit-equality.
    a_pc = a.pump_coeffs.double()
    b_pc = b.pump_coeffs.double()
    assert torch.allclose(a_pc, b_pc, atol=1e-9, rtol=1e-9), (
        f"pump_coeffs drifted beyond BLAS noise: "
        f"{a_pc.tolist()} != {b_pc.tolist()}"
    )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section_name", _TARGET_SECTION_NAMES)
def test_ignored_sections_surface_includes_target(section_name: str) -> None:
    """Every Sprint 21 target section is advertised on the public
    :data:`IGNORED_SECTIONS` surface so external code can introspect
    the explicit no-op contract.
    """
    assert section_name in IGNORED_SECTIONS, (
        f"{section_name!r} missing from IGNORED_SECTIONS; the Sprint 21 "
        f"target list is {_TARGET_SECTION_NAMES}"
    )


def test_ignored_sections_is_frozenset() -> None:
    """The contract is *documentation as code*; the constant must be
    immutable so downstream code cannot accidentally mutate it.
    """
    assert isinstance(IGNORED_SECTIONS, frozenset)


def test_curves_is_not_globally_ignored() -> None:
    """``[CURVES]`` is active: Sprint 12 consumes HEAD-type curves when
    a ``[PUMPS]`` row references one. The constant must NOT advertise
    it as a no-op.
    """
    assert "CURVES" not in IGNORED_SECTIONS


def test_status_is_not_globally_ignored_after_sprint_22() -> None:
    """Sprint 22 actively validates ``[STATUS]`` rows (accepting
    ``<link_id> OPEN`` as a no-op, rejecting closed/CV/numeric/unknown
    tokens). The constant must NOT advertise it as a global no-op
    anymore — that would silently swallow ``[STATUS]`` rows the Sprint
    22 validator is supposed to fail loudly on.
    """
    assert "STATUS" not in IGNORED_SECTIONS


@pytest.mark.parametrize(
    "active_section",
    ["JUNCTIONS", "RESERVOIRS", "TANKS", "PIPES", "PUMPS", "VALVES",
     "OPTIONS", "CURVES"],
)
def test_hydraulically_active_sections_are_not_ignored(
    active_section: str,
) -> None:
    """No hydraulically-active section should be silently dropped: a
    regression here would mean the parser stops consuming, e.g.,
    junction demands.
    """
    assert active_section not in IGNORED_SECTIONS


# ---------------------------------------------------------------------------
# Per-section invariance: adding the section preserves the network
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section_name", _TARGET_SECTION_NAMES)
def test_each_ignored_section_leaves_network_unchanged(
    tmp_path: Path, section_name: str
) -> None:
    """Adding any one of the nine target ignored sections to the
    baseline fixture must leave the loaded :class:`Network`
    byte-for-byte unchanged.
    """
    body = _TARGET_SECTION_BODIES[section_name]
    baseline = _baseline_inp()
    # Insert the ignored section just before [END]. This places it
    # *after* every hydraulic section, the most common position EPANET
    # emits ignored sections in.
    perturbed = baseline.replace(
        "[END]\n",
        f"[{section_name}]\n{body}[END]\n",
    )

    net_baseline = load_network_from_inp(
        _write(tmp_path, f"baseline_for_{section_name}.inp", baseline),
        parser="fallback",
    )
    net_perturbed = load_network_from_inp(
        _write(tmp_path, f"perturbed_{section_name}.inp", perturbed),
        parser="fallback",
    )

    _assert_networks_identical(net_baseline, net_perturbed)


def test_all_target_sections_at_once_leave_network_unchanged(
    tmp_path: Path,
) -> None:
    """Stacking every target ignored section into one file must STILL
    leave the network identical to the baseline. Catches accidental
    cross-section state leakage in the parser.
    """
    baseline = _baseline_inp()
    blob = ""
    for name, body in _TARGET_SECTION_BODIES.items():
        blob += f"[{name}]\n{body}"
    perturbed = baseline.replace("[END]\n", f"{blob}[END]\n")

    net_baseline = load_network_from_inp(
        _write(tmp_path, "baseline_all.inp", baseline), parser="fallback"
    )
    net_perturbed = load_network_from_inp(
        _write(tmp_path, "perturbed_all.inp", perturbed), parser="fallback"
    )
    _assert_networks_identical(net_baseline, net_perturbed)


# ---------------------------------------------------------------------------
# Position invariance: ignored sections before / after hydraulic ones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section_name", _TARGET_SECTION_NAMES)
def test_ignored_section_before_hydraulic_sections(
    tmp_path: Path, section_name: str
) -> None:
    """An ignored section placed BEFORE ``[JUNCTIONS]`` must not block
    the parser from consuming the subsequent hydraulic sections.
    """
    body = _TARGET_SECTION_BODIES[section_name]
    baseline = _baseline_inp()
    # Strip the [TITLE]/baseline title (which is its own ignored
    # section) and prepend the target section in its place so the
    # ignored section is the very first content the parser sees.
    no_title = baseline.replace(
        "[TITLE]\nSprint 21 ignored-section baseline fixture\n",
        "",
    )
    perturbed = f"[{section_name}]\n{body}{no_title}"

    net_baseline = load_network_from_inp(
        _write(tmp_path, f"baseline_pre_{section_name}.inp", baseline),
        parser="fallback",
    )
    net_perturbed = load_network_from_inp(
        _write(tmp_path, f"perturbed_pre_{section_name}.inp", perturbed),
        parser="fallback",
    )

    _assert_networks_identical(net_baseline, net_perturbed)


@pytest.mark.parametrize("section_name", _TARGET_SECTION_NAMES)
def test_ignored_section_after_hydraulic_sections(
    tmp_path: Path, section_name: str
) -> None:
    """An ignored section placed AFTER ``[OPTIONS]`` (the last
    hydraulic section in the baseline) must not mutate any
    already-parsed value.
    """
    body = _TARGET_SECTION_BODIES[section_name]
    baseline = _baseline_inp()
    # Place the ignored section just after [OPTIONS], before [END].
    perturbed = baseline.replace(
        "[END]\n", f"[{section_name}]\n{body}[END]\n"
    )

    net_baseline = load_network_from_inp(
        _write(tmp_path, f"baseline_post_{section_name}.inp", baseline),
        parser="fallback",
    )
    net_perturbed = load_network_from_inp(
        _write(tmp_path, f"perturbed_post_{section_name}.inp", perturbed),
        parser="fallback",
    )

    _assert_networks_identical(net_baseline, net_perturbed)


# ---------------------------------------------------------------------------
# Malformed-row tolerance inside ignored sections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "section_name, malformed_row",
    [
        ("TIMES", " Duration NOT_A_TIME"),
        ("REPORT", " Status MAYBE_LATER 12 34"),
        ("CONTROLS", " LINK QQQ_unknown_link OPEN IF NODE ZZZ ABOVE -1.0"),
        ("RULES", " IF NODE NONEXISTENT_NODE BELOW QQQ"),
        ("EMITTERS", " UNKNOWN_NODE_99 not_a_number"),
        ("QUALITY", " UNKNOWN_NODE_99 N/A"),
        ("SOURCES", " UNKNOWN_NODE_99 UNKNOWN_TYPE not_a_number trailing tokens"),
        ("REACTIONS", " Order Wall WHO_KNOWS"),
        ("MIXING", " UNKNOWN_TANK MIXED maybe extra columns"),
    ],
)
def test_malformed_rows_in_ignored_sections_do_not_raise(
    tmp_path: Path, section_name: str, malformed_row: str
) -> None:
    """The parser must not validate row shapes inside ignored sections.
    A row whose tokens reference unknown nodes, contain non-numeric
    fields, or carry extra columns must be tolerated silently.
    """
    baseline = _baseline_inp()
    perturbed = baseline.replace(
        "[END]\n",
        f"[{section_name}]\n{malformed_row}\n[END]\n",
    )
    net_baseline = load_network_from_inp(
        _write(tmp_path, f"baseline_malf_{section_name}.inp", baseline),
        parser="fallback",
    )
    # Must not raise.
    net_perturbed = load_network_from_inp(
        _write(tmp_path, f"perturbed_malf_{section_name}.inp", perturbed),
        parser="fallback",
    )
    _assert_networks_identical(net_baseline, net_perturbed)


# ---------------------------------------------------------------------------
# Documented limitation: CONTROLS / RULES are dropped, not enforced
# ---------------------------------------------------------------------------


def test_controls_close_link_is_dropped_not_enforced(tmp_path: Path) -> None:
    """A ``[CONTROLS]`` rule that would close pipe ``P1`` is *ignored*,
    not enforced. The Sprint 21 contract is that active controls are
    deferred — the loaded network exposes the same pipe geometry,
    mass balance and Newton-solve heads / flows as the baseline.

    Pinning this behaviour as a test makes the limitation explicit so
    a future sprint that adds control logic cannot do so silently.
    """
    baseline_text = _baseline_inp()
    closed_text = baseline_text.replace(
        "[END]\n",
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 99999\n"
        " LINK P2 OPEN AT TIME 0\n"
        " LINK P5 CLOSED AT CLOCKTIME 6:00 AM\n"
        "[END]\n",
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "controls_baseline.inp", baseline_text),
        parser="fallback",
    )
    net_with_controls = load_network_from_inp(
        _write(tmp_path, "controls_closed.inp", closed_text),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_with_controls)

    # And the solver must still reach the same operating point.
    r_base = newton_solve(
        net_base, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    r_ctrl = newton_solve(
        net_with_controls,
        max_iterations=200,
        tol=1e-9,
        jacobian_mode="analytic",
    )
    assert r_base.converged and r_ctrl.converged
    assert torch.allclose(
        r_base.heads.double(), r_ctrl.heads.double(), atol=1e-9
    )
    assert torch.allclose(
        r_base.flows.double(), r_ctrl.flows.double(), atol=1e-12
    )


def test_rules_block_is_dropped_not_enforced(tmp_path: Path) -> None:
    """An EPANET ``[RULES]`` block that would close a link is dropped.
    Same contract as ``[CONTROLS]`` — Sprint 21 documents rule-based
    logic as deferred.
    """
    baseline_text = _baseline_inp()
    rules_text = baseline_text.replace(
        "[END]\n",
        "[RULES]\n"
        " RULE 1\n"
        " IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P1 STATUS IS CLOSED\n"
        " PRIORITY 1\n"
        " RULE 2\n"
        " IF SYSTEM CLOCKTIME >= 0:00 AM\n"
        " AND SYSTEM CLOCKTIME <= 6:00 AM\n"
        " THEN LINK P5 STATUS IS CLOSED\n"
        " PRIORITY 2\n"
        "[END]\n",
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "rules_baseline.inp", baseline_text),
        parser="fallback",
    )
    net_with_rules = load_network_from_inp(
        _write(tmp_path, "rules_block.inp", rules_text),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_with_rules)


# ---------------------------------------------------------------------------
# [CURVES] remains active for pump HEAD curves (NOT a global no-op)
# ---------------------------------------------------------------------------


def _head_pump_inp(extra_ignored: str = "") -> str:
    """A small reservoir-pump-junction fixture with one HEAD curve."""
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
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{extra_ignored}"
        "[END]\n"
    )


def test_curves_still_consumed_by_head_pumps(tmp_path: Path) -> None:
    """Sanity check that ``[CURVES]`` is not silently dropped. A pump
    HEAD curve resolved through the active ``[CURVES]`` section must
    produce a non-trivial pump quadratic ``[a0, a1, a2]`` with
    ``a0 > 0``.
    """
    net = load_network_from_inp(
        _write(tmp_path, "head_pump.inp", _head_pump_inp()),
        parser="fallback",
    )
    assert any(net.pump_mask.tolist())
    pump_idx = next(i for i, m in enumerate(net.pump_mask.tolist()) if m)
    a0 = float(net.pump_coeffs[pump_idx][0].item())
    a2 = float(net.pump_coeffs[pump_idx][2].item())
    assert a0 == pytest.approx(45.0, abs=1e-5)
    assert a2 < 0.0  # drooping curve


def test_head_pump_unaffected_by_simultaneous_ignored_sections(
    tmp_path: Path,
) -> None:
    """A HEAD-curve pump fixture with EVERY target ignored section
    appended must produce identical pump coefficients. Confirms that
    ``[CURVES]`` resolution is robust against ignored-section noise.
    """
    extra = ""
    for name, body in _TARGET_SECTION_BODIES.items():
        extra += f"[{name}]\n{body}"

    net_clean = load_network_from_inp(
        _write(tmp_path, "head_pump_clean.inp", _head_pump_inp()),
        parser="fallback",
    )
    net_noisy = load_network_from_inp(
        _write(tmp_path, "head_pump_noisy.inp", _head_pump_inp(extra)),
        parser="fallback",
    )
    _assert_networks_identical(net_clean, net_noisy)


# ---------------------------------------------------------------------------
# Valve invariance under ignored sections (PRV + TCV)
# ---------------------------------------------------------------------------


def _prv_inp(extra_ignored: str = "") -> str:
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
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{extra_ignored}"
        "[END]\n"
    )


def test_prv_fixture_invariant_under_all_ignored_sections(
    tmp_path: Path,
) -> None:
    """The PRV pressure-boundary surrogate must produce identical
    ``fixed_head_values`` whether or not every target ignored section
    is also present in the file.
    """
    extra = ""
    for name, body in _TARGET_SECTION_BODIES.items():
        extra += f"[{name}]\n{body}"
    net_clean = load_network_from_inp(
        _write(tmp_path, "prv_clean.inp", _prv_inp()), parser="fallback"
    )
    net_noisy = load_network_from_inp(
        _write(tmp_path, "prv_noisy.inp", _prv_inp(extra)),
        parser="fallback",
    )
    _assert_networks_identical(net_clean, net_noisy)


def _tcv_inp(extra_ignored: str = "") -> str:
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
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{extra_ignored}"
        "[END]\n"
    )


def test_tcv_fixture_invariant_under_all_ignored_sections(
    tmp_path: Path,
) -> None:
    """The TCV resistance surrogate must produce identical edge
    geometry (length, diameter, c_factor) whether or not every target
    ignored section is also present.
    """
    extra = ""
    for name, body in _TARGET_SECTION_BODIES.items():
        extra += f"[{name}]\n{body}"
    net_clean = load_network_from_inp(
        _write(tmp_path, "tcv_clean.inp", _tcv_inp()), parser="fallback"
    )
    net_noisy = load_network_from_inp(
        _write(tmp_path, "tcv_noisy.inp", _tcv_inp(extra)),
        parser="fallback",
    )
    _assert_networks_identical(net_clean, net_noisy)


# ---------------------------------------------------------------------------
# Multi-position robustness
# ---------------------------------------------------------------------------


def test_ignored_sections_interleaved_throughout_file(tmp_path: Path) -> None:
    """Ignored sections may appear interleaved between every hydraulic
    section in real EPANET output. The parser must tolerate that
    layout and produce the same network.
    """
    baseline = _baseline_inp()
    interleaved = (
        "[TITLE]\n"
        "Sprint 21 ignored-section baseline fixture\n"
        f"[TIMES]\n{_TARGET_SECTION_BODIES['TIMES']}"
        "[JUNCTIONS]\n"
        " J1   0.0   10.0\n"
        " J2   0.0   15.0\n"
        " J3   0.0   12.0\n"
        " J4   0.0    8.0\n"
        f"[REPORT]\n{_TARGET_SECTION_BODIES['REPORT']}"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        f"[CONTROLS]\n{_TARGET_SECTION_BODIES['CONTROLS']}"
        "[PIPES]\n"
        " P1   R1   J1   300.0   250.0   130.0   0.0   OPEN\n"
        " P2   J1   J2   250.0   200.0   130.0   0.0   OPEN\n"
        " P3   J2   J3   220.0   150.0   130.0   0.0   OPEN\n"
        " P4   J3   J4   200.0   150.0   130.0   0.0   OPEN\n"
        " P5   J1   J4   280.0   150.0   130.0   0.0   OPEN\n"
        f"[RULES]\n{_TARGET_SECTION_BODIES['RULES']}"
        f"[EMITTERS]\n{_TARGET_SECTION_BODIES['EMITTERS']}"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"[QUALITY]\n{_TARGET_SECTION_BODIES['QUALITY']}"
        f"[SOURCES]\n{_TARGET_SECTION_BODIES['SOURCES']}"
        f"[REACTIONS]\n{_TARGET_SECTION_BODIES['REACTIONS']}"
        f"[MIXING]\n{_TARGET_SECTION_BODIES['MIXING']}"
        "[END]\n"
    )
    net_baseline = load_network_from_inp(
        _write(tmp_path, "interleave_baseline.inp", baseline),
        parser="fallback",
    )
    net_interleaved = load_network_from_inp(
        _write(tmp_path, "interleave_perturbed.inp", interleaved),
        parser="fallback",
    )
    _assert_networks_identical(net_baseline, net_interleaved)


# ---------------------------------------------------------------------------
# Repeated headers
# ---------------------------------------------------------------------------


def test_repeated_ignored_section_headers(tmp_path: Path) -> None:
    """Some EPANET-flavoured exporters emit the same ignored section
    twice (e.g. two ``[CONTROLS]`` blocks). The parser must accept
    that — :func:`_split_sections` already appends rows to whichever
    section is currently open — and the loaded network must still
    match the baseline.
    """
    baseline = _baseline_inp()
    repeated = baseline.replace(
        "[END]\n",
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 1\n"
        "[CONTROLS]\n"
        " LINK P2 OPEN AT TIME 0\n"
        "[END]\n",
    )
    net_base = load_network_from_inp(
        _write(tmp_path, "repeat_base.inp", baseline), parser="fallback"
    )
    net_rep = load_network_from_inp(
        _write(tmp_path, "repeat_perturbed.inp", repeated),
        parser="fallback",
    )
    _assert_networks_identical(net_base, net_rep)


# ---------------------------------------------------------------------------
# Optional WNTR smoke check — the same baseline + ignored sections
# must still produce a network whose demand sum matches between the
# fallback and WNTR back-ends. WNTR may parse some of these sections
# internally; the contract for the dPHM importer is only that the
# returned Network values agree.
# ---------------------------------------------------------------------------


def test_wntr_smoke_ignored_sections_do_not_break_back_end(
    tmp_path: Path,
) -> None:
    """The WNTR back-end has its own (strict) parser for several of
    the Sprint 21 target sections — e.g. ``[MIXING]`` validates that
    every named tank exists, ``[CONTROLS]`` validates link / node
    references. WNTR's parsing behaviour is *not* what Sprint 21 is
    documenting: this smoke test only confirms that adding the
    sections WNTR is happy to round-trip (``[TIMES]``, ``[REPORT]``,
    ``[QUALITY]`` against an existing node) does not perturb the
    dPHM-side demand sum produced through the WNTR back-end. The
    WNTR-ambiguous sections are documented in
    ``docs/epanet-inp-import.md`` and ``SPRINT21_REPORT.md`` rather
    than asserted on here.
    """
    pytest.importorskip("wntr")
    baseline = _baseline_inp()
    blob = (
        "[TIMES]\n"
        f"{_TARGET_SECTION_BODIES['TIMES']}"
        "[REPORT]\n"
        f"{_TARGET_SECTION_BODIES['REPORT']}"
        "[QUALITY]\n"
        " J1 0.0\n"
    )
    perturbed = baseline.replace("[END]\n", f"{blob}[END]\n")

    perturbed_path = _write(tmp_path, "wntr_smoke.inp", perturbed)

    net_fb = load_network_from_inp(perturbed_path, parser="fallback")
    net_wn = load_network_from_inp(perturbed_path, parser="wntr")

    fb_sorted = sorted(net_fb.demands.tolist())
    wn_sorted = sorted(net_wn.demands.tolist())
    assert fb_sorted == pytest.approx(wn_sorted, abs=1e-7)
    assert net_fb.num_nodes == net_wn.num_nodes
    assert net_fb.num_edges == net_wn.num_edges
