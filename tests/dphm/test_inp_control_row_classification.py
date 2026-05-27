"""Sprint 27 — EPANET ``[CONTROLS]`` row classification diagnostics.

Sprint 25 surfaced one read-only :class:`EpanetControlRuleDiagnostic`
record per tokenised parser row inside ``[CONTROLS]`` / ``[RULES]``.
Sprint 27 adds a conservative, deterministic ``kind`` classification on
top of that record for ``[CONTROLS]`` rows only. The classification is
purely diagnostic — it does **not** activate any control semantics, it
does **not** evaluate conditions or settings, and it does **not** change
any hydraulic field on the loaded :class:`Network`. ``[RULES]`` rows
remain raw row diagnostics with the conservative ``UNKNOWN``
classification.

Contract:

* A new public string :class:`Enum` :class:`EpanetControlKind` enumerates
  the four conservative categories: ``LINK_SETTING``, ``PUMP_SETTING``,
  ``VALVE_SETTING``, ``UNKNOWN``.
* :class:`EpanetControlRuleDiagnostic` gains a ``kind: str`` field with a
  default of ``EpanetControlKind.UNKNOWN.value`` so every Sprint 25
  positional / keyword constructor call keeps working.
* The fallback parser classifies ``[CONTROLS]`` rows by their leading
  ``LINK <link_id>`` tokens **and** by the parsed network's link-type
  context — known pump ids classify as ``PUMP_SETTING``, known valve ids
  as ``VALVE_SETTING``, known pipe ids as ``LINK_SETTING``, and anything
  else as ``UNKNOWN``.
* ``[RULES]`` rows always classify as ``UNKNOWN`` — the dPHM importer
  does not interpret EPANET rule structure.
* Unknown ``[CONTROLS]`` rows are **not** rejected. They remain accepted
  as ignored diagnostics with ``kind = UNKNOWN``.
* Classification preserves the Sprint 25 ``section`` / ``row_index`` /
  ``tokens`` / ``text`` fields, the Sprint 23 ``status_rows`` channel,
  the Sprint 24 ``ignored_sections`` channel, and the Sprint 26
  ``pattern_energy_rows`` channel.
* Classification is hydraulically inert — the loaded :class:`Network`
  is byte-for-byte identical to one loaded from a fixture with no
  control rows. Newton-solving the perturbed network reproduces the
  baseline heads and flows.
* The Sprint 22 ``[STATUS]`` rejection behaviour is preserved.
* ``load_network_from_inp(path)`` without ``return_diagnostics`` still
  returns only a :class:`Network`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    EpanetControlKind,
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


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _baseline_inp(extra: str = "") -> str:
    """Pure-pipe loop fixture; ``extra`` is injected just before ``[END]``."""
    return (
        "[TITLE]\n"
        "Sprint 27 control-row classification fixture\n"
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


def _pump_inp(extra: str = "") -> str:
    """Fixture with one POWER pump named ``PU1``."""
    return (
        "[TITLE]\n"
        "Sprint 27 pump fixture\n"
        "[JUNCTIONS]\n"
        " J1   0.0   0.0\n"
        " J2   0.0   1.0\n"
        "[RESERVOIRS]\n"
        " R1   50.0\n"
        "[PIPES]\n"
        " P1   J1   J2   100.0   200.0   130.0\n"
        "[PUMPS]\n"
        " PU1   R1   J1   POWER   10.0\n"
        "[OPTIONS]\n"
        " Units      LPS\n"
        " Headloss   H-W\n"
        f"{extra}"
        "[END]\n"
    )


def _valve_inp(extra: str = "") -> str:
    """Fixture with one PRV valve named ``V1``."""
    return (
        "[TITLE]\n"
        "Sprint 27 valve fixture\n"
        "[JUNCTIONS]\n"
        " J1   0.0   1.0\n"
        " J2   0.0   1.0\n"
        " J3   0.0   1.0\n"
        "[RESERVOIRS]\n"
        " R1   100.0\n"
        "[PIPES]\n"
        " P1   R1   J1   100.0   250.0   130.0\n"
        " P2   J2   J3   100.0   250.0   130.0\n"
        "[VALVES]\n"
        " V1   J1   J2   250.0   PRV   30.0\n"
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
# Public surface — enum
# ---------------------------------------------------------------------------


def test_epanet_control_kind_enum_members_exist() -> None:
    """The enum exposes the four conservative categories."""
    assert EpanetControlKind.LINK_SETTING.value == "LINK_SETTING"
    assert EpanetControlKind.PUMP_SETTING.value == "PUMP_SETTING"
    assert EpanetControlKind.VALVE_SETTING.value == "VALVE_SETTING"
    assert EpanetControlKind.UNKNOWN.value == "UNKNOWN"


def test_epanet_control_kind_str_subclass() -> None:
    """``EpanetControlKind`` is a string enum so the ``kind`` field can be
    compared directly to plain strings or to enum members.
    """
    assert isinstance(EpanetControlKind.UNKNOWN, str)
    assert EpanetControlKind.LINK_SETTING == "LINK_SETTING"
    assert EpanetControlKind.PUMP_SETTING == "PUMP_SETTING"
    assert EpanetControlKind.VALVE_SETTING == "VALVE_SETTING"
    assert EpanetControlKind.UNKNOWN == "UNKNOWN"


def test_epanet_control_kind_has_exactly_four_members() -> None:
    members = {member.value for member in EpanetControlKind}
    assert members == {"LINK_SETTING", "PUMP_SETTING", "VALVE_SETTING", "UNKNOWN"}


# ---------------------------------------------------------------------------
# Public surface — diagnostic ``kind`` field
# ---------------------------------------------------------------------------


def test_diagnostic_has_kind_field_with_default_unknown() -> None:
    """``EpanetControlRuleDiagnostic`` now carries a ``kind`` field that
    defaults to ``UNKNOWN`` so every Sprint 25 positional / keyword
    constructor call continues to work.
    """
    rec = EpanetControlRuleDiagnostic(
        section="CONTROLS",
        row_index=0,
        tokens=("LINK", "P1", "CLOSED"),
        text="LINK P1 CLOSED",
    )
    assert rec.kind == EpanetControlKind.UNKNOWN
    assert rec.kind == "UNKNOWN"


def test_diagnostic_kind_field_is_frozen() -> None:
    rec = EpanetControlRuleDiagnostic(
        section="CONTROLS",
        row_index=0,
        tokens=("LINK", "P1", "CLOSED"),
        text="LINK P1 CLOSED",
        kind=EpanetControlKind.LINK_SETTING.value,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.kind = EpanetControlKind.UNKNOWN.value  # type: ignore[misc]


def test_diagnostic_accepts_each_kind() -> None:
    """A caller can construct a record with any of the four enum values
    — useful for callers consuming the surface directly.
    """
    for member in EpanetControlKind:
        rec = EpanetControlRuleDiagnostic(
            section="CONTROLS",
            row_index=0,
            tokens=("LINK", "P1", "CLOSED"),
            text="LINK P1 CLOSED",
            kind=member.value,
        )
        assert rec.kind == member


def test_sprint_25_default_constructor_still_works() -> None:
    """The Sprint 25 constructor call (no ``kind`` kwarg) must continue
    to succeed — that is the backwards-compatibility contract.
    """
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
    assert rec.kind == EpanetControlKind.UNKNOWN


# ---------------------------------------------------------------------------
# Classification: pipe-link control row -> LINK_SETTING
# ---------------------------------------------------------------------------


def test_pipe_link_control_row_classifies_as_link_setting(tmp_path: Path) -> None:
    """A ``[CONTROLS] LINK <pipe_id> ...`` row classifies as
    ``LINK_SETTING`` because the link id resolves to a known pipe.
    """
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 10\n"
    )
    path = _write(tmp_path, "pipe_link.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 1
    rec = diag.control_rule_rows[0]
    assert rec.kind == EpanetControlKind.LINK_SETTING
    # Sprint 25 fields untouched.
    assert rec.section == "CONTROLS"
    assert rec.row_index == 0
    assert rec.tokens == ("LINK", "P1", "CLOSED", "IF", "NODE", "J1", "BELOW", "10")
    assert rec.text == "LINK P1 CLOSED IF NODE J1 BELOW 10"


def test_pipe_link_control_row_lowercase_link_keyword(tmp_path: Path) -> None:
    """The leading ``LINK`` keyword is case-insensitive in EPANET; the
    classifier must accept any case.
    """
    text = _baseline_inp(
        "[CONTROLS]\n"
        " link P2 OPEN AT TIME 0\n"
    )
    path = _write(tmp_path, "lower_link.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 1
    assert diag.control_rule_rows[0].kind == EpanetControlKind.LINK_SETTING


# ---------------------------------------------------------------------------
# Classification: pump control row -> PUMP_SETTING
# ---------------------------------------------------------------------------


def test_pump_link_control_row_classifies_as_pump_setting(tmp_path: Path) -> None:
    """A ``[CONTROLS] LINK <pump_id> ...`` row classifies as
    ``PUMP_SETTING`` because the link id resolves to a known pump.
    """
    text = _pump_inp(
        "[CONTROLS]\n"
        " LINK PU1 1.2 IF NODE J2 BELOW 5\n"
    )
    path = _write(tmp_path, "pump_link.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    pump_records = [
        r for r in diag.control_rule_rows if r.tokens[:2] == ("LINK", "PU1")
    ]
    assert len(pump_records) == 1
    assert pump_records[0].kind == EpanetControlKind.PUMP_SETTING


def test_pump_link_open_control_row_classifies_as_pump_setting(
    tmp_path: Path,
) -> None:
    text = _pump_inp(
        "[CONTROLS]\n"
        " LINK PU1 OPEN AT TIME 6\n"
    )
    path = _write(tmp_path, "pump_open.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 1
    assert diag.control_rule_rows[0].kind == EpanetControlKind.PUMP_SETTING


# ---------------------------------------------------------------------------
# Classification: valve control row -> VALVE_SETTING
# ---------------------------------------------------------------------------


def test_valve_link_control_row_classifies_as_valve_setting(
    tmp_path: Path,
) -> None:
    """A ``[CONTROLS] LINK <valve_id> ...`` row classifies as
    ``VALVE_SETTING`` because the link id resolves to a known valve.
    """
    text = _valve_inp(
        "[CONTROLS]\n"
        " LINK V1 OPEN IF NODE J3 BELOW 4\n"
    )
    path = _write(tmp_path, "valve_link.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 1
    assert diag.control_rule_rows[0].kind == EpanetControlKind.VALVE_SETTING


# ---------------------------------------------------------------------------
# Classification: unknown link id -> UNKNOWN (not rejected)
# ---------------------------------------------------------------------------


def test_unknown_link_id_classifies_as_unknown(tmp_path: Path) -> None:
    """A ``[CONTROLS] LINK <unknown_id> ...`` row classifies as
    ``UNKNOWN``. Crucially, it is **not** rejected — the parser still
    surfaces the row as an ignored diagnostic.
    """
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK PHANTOM CLOSED IF NODE J1 BELOW 1\n"
    )
    path = _write(tmp_path, "phantom_link.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 1
    rec = diag.control_rule_rows[0]
    assert rec.kind == EpanetControlKind.UNKNOWN
    assert rec.tokens[1] == "PHANTOM"


def test_unknown_link_id_does_not_raise_on_network_load(tmp_path: Path) -> None:
    """The classifier is non-fatal — loading the Network succeeds even
    with an unknown link id in ``[CONTROLS]``.
    """
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK PHANTOM CLOSED IF NODE J1 BELOW 1\n"
    )
    path = _write(tmp_path, "phantom_link.inp", text)
    net = load_network_from_inp(path, parser="fallback")
    assert isinstance(net, Network)


# ---------------------------------------------------------------------------
# Classification: non-LINK-prefixed row -> UNKNOWN
# ---------------------------------------------------------------------------


def test_non_link_prefixed_control_row_classifies_as_unknown(
    tmp_path: Path,
) -> None:
    """A ``[CONTROLS]`` row whose leading token is not ``LINK`` (e.g.
    EPANET ``RULE`` keyword embedded in CONTROLS by mistake, or a stray
    token) classifies as ``UNKNOWN``.
    """
    text = _baseline_inp(
        "[CONTROLS]\n"
        " WEIRD TOKEN P1 OPEN\n"
    )
    path = _write(tmp_path, "non_link.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 1
    assert diag.control_rule_rows[0].kind == EpanetControlKind.UNKNOWN


def test_short_control_row_classifies_as_unknown(tmp_path: Path) -> None:
    """A single-token ``[CONTROLS]`` row (no link id) classifies as
    ``UNKNOWN`` instead of raising.
    """
    text = _baseline_inp(
        "[CONTROLS]\n"
        " LINK\n"
    )
    path = _write(tmp_path, "short_control.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 1
    assert diag.control_rule_rows[0].kind == EpanetControlKind.UNKNOWN


# ---------------------------------------------------------------------------
# Classification: RULES rows are not semantically classified — UNKNOWN
# ---------------------------------------------------------------------------


def test_rules_rows_classify_as_unknown(tmp_path: Path) -> None:
    """``[RULES]`` rows always classify as ``UNKNOWN`` — the dPHM
    importer does not interpret rule structure beyond per-row visibility.
    """
    text = _baseline_inp(
        "[RULES]\n"
        " RULE R1\n"
        " IF NODE J1 PRESSURE BELOW 20\n"
        " THEN LINK P2 STATUS IS CLOSED\n"
    )
    path = _write(tmp_path, "rules.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    rules_records = [r for r in diag.control_rule_rows if r.section == "RULES"]
    assert len(rules_records) == 3
    for rec in rules_records:
        assert rec.kind == EpanetControlKind.UNKNOWN


def test_rules_then_with_known_link_id_still_unknown(tmp_path: Path) -> None:
    """A ``[RULES]`` ``THEN LINK <pipe_id> ...`` line targets a known
    pipe, but ``[RULES]`` rows are never semantically classified — the
    record must remain ``UNKNOWN``.
    """
    text = _baseline_inp(
        "[RULES]\n"
        " THEN LINK P1 STATUS IS CLOSED\n"
    )
    path = _write(tmp_path, "then_known.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    rules_records = [r for r in diag.control_rule_rows if r.section == "RULES"]
    assert len(rules_records) == 1
    assert rules_records[0].kind == EpanetControlKind.UNKNOWN


# ---------------------------------------------------------------------------
# Classification preserves Sprint 25 fields & ordering
# ---------------------------------------------------------------------------


def test_classification_preserves_tokens_text_and_row_index(
    tmp_path: Path,
) -> None:
    text = _pump_inp(
        "[CONTROLS]\n"
        " LINK PU1 1.2 IF NODE J2 BELOW 5\n"
        " LINK P1 OPEN AT TIME 0\n"
        " LINK GHOST CLOSED IF NODE J9 BELOW 1\n"
    )
    path = _write(tmp_path, "three_kinds.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    assert len(diag.control_rule_rows) == 3
    # row_index is sequential and starts at 0.
    assert [r.row_index for r in diag.control_rule_rows] == [0, 1, 2]
    # tokens & text preserved from Sprint 25.
    assert diag.control_rule_rows[0].tokens == (
        "LINK", "PU1", "1.2", "IF", "NODE", "J2", "BELOW", "5",
    )
    assert diag.control_rule_rows[0].text == "LINK PU1 1.2 IF NODE J2 BELOW 5"
    # Per-row classification.
    assert diag.control_rule_rows[0].kind == EpanetControlKind.PUMP_SETTING
    assert diag.control_rule_rows[1].kind == EpanetControlKind.LINK_SETTING
    assert diag.control_rule_rows[2].kind == EpanetControlKind.UNKNOWN


def test_classification_preserves_section_ordering(tmp_path: Path) -> None:
    """``[RULES]`` declared before ``[CONTROLS]`` still surfaces first
    — Sprint 25's source-order contract is preserved.
    """
    text = _baseline_inp(
        "[RULES]\n"
        " RULE R1\n"
        "[CONTROLS]\n"
        " LINK P1 CLOSED IF NODE J1 BELOW 10\n"
    )
    path = _write(tmp_path, "rules_then_controls.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    sections = [r.section for r in diag.control_rule_rows]
    assert sections == ["RULES", "CONTROLS"]
    # Per-section classification.
    assert diag.control_rule_rows[0].kind == EpanetControlKind.UNKNOWN
    assert diag.control_rule_rows[1].kind == EpanetControlKind.LINK_SETTING


# ---------------------------------------------------------------------------
# Hydraulic inertness — diagnostics never mutate Network / solve
# ---------------------------------------------------------------------------


def test_classification_does_not_change_network(tmp_path: Path) -> None:
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_controls.inp",
        _baseline_inp(
            "[CONTROLS]\n"
            " LINK P1 CLOSED IF NODE J1 BELOW 99999\n"
            " LINK PHANTOM OPEN AT TIME 0\n"
            "[RULES]\n"
            " RULE R1\n"
            " THEN LINK P2 STATUS IS CLOSED\n"
        ),
    )
    net_baseline = load_network_from_inp(baseline_path, parser="fallback")
    net_perturbed = load_network_from_inp(perturbed_path, parser="fallback")
    _assert_networks_identical(net_baseline, net_perturbed)


def test_classification_does_not_change_solve(tmp_path: Path) -> None:
    baseline_path = _write(tmp_path, "baseline.inp", _baseline_inp())
    perturbed_path = _write(
        tmp_path,
        "with_controls_classified.inp",
        _baseline_inp(
            "[CONTROLS]\n"
            " LINK P1 CLOSED IF NODE J1 BELOW 99999\n"
            " LINK PHANTOM CLOSED IF NODE J9 BELOW 1\n"
            "[RULES]\n"
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


def test_classification_does_not_mutate_demands_on_pump_fixture(
    tmp_path: Path,
) -> None:
    """A pump fixture's demand / pump_coeffs vectors are unaffected by
    adding classified ``[CONTROLS]`` rows that target the pump.
    """
    baseline_path = _write(tmp_path, "pump_baseline.inp", _pump_inp())
    perturbed_path = _write(
        tmp_path,
        "pump_with_controls.inp",
        _pump_inp(
            "[CONTROLS]\n"
            " LINK PU1 1.5 IF NODE J2 BELOW 5\n"
            " LINK PU1 0.8 AT TIME 6\n"
        ),
    )
    net_base = load_network_from_inp(baseline_path, parser="fallback")
    net_ctrl = load_network_from_inp(perturbed_path, parser="fallback")
    _assert_networks_identical(net_base, net_ctrl)


# ---------------------------------------------------------------------------
# Public API parity: load_inp_diagnostics vs load_network_from_inp tuple
# ---------------------------------------------------------------------------


def test_load_inp_diagnostics_and_tuple_path_return_same_kinds(
    tmp_path: Path,
) -> None:
    text = _pump_inp(
        "[CONTROLS]\n"
        " LINK PU1 1.2 IF NODE J2 BELOW 5\n"
        " LINK P1 OPEN AT TIME 0\n"
        "[RULES]\n"
        " RULE R1\n"
    )
    path = _write(tmp_path, "parity.inp", text)
    diag_only = load_inp_diagnostics(path, parser="fallback")
    _net, diag_tuple = load_network_from_inp(
        path, parser="fallback", return_diagnostics=True
    )
    assert diag_only.control_rule_rows == diag_tuple.control_rule_rows
    # And the per-record kind is preserved across both API entry points.
    assert [r.kind for r in diag_only.control_rule_rows] == [
        EpanetControlKind.PUMP_SETTING,
        EpanetControlKind.LINK_SETTING,
        EpanetControlKind.UNKNOWN,
    ]


def test_default_load_network_from_inp_still_returns_only_network(
    tmp_path: Path,
) -> None:
    """``load_network_from_inp(path)`` without ``return_diagnostics``
    must continue to return a bare :class:`Network` even when classified
    ``[CONTROLS]`` rows are present.
    """
    path = _write(
        tmp_path,
        "default_load.inp",
        _pump_inp(
            "[CONTROLS]\n"
            " LINK PU1 1.2 IF NODE J2 BELOW 5\n"
        ),
    )
    result = load_network_from_inp(path, parser="fallback")
    assert isinstance(result, Network)


# ---------------------------------------------------------------------------
# Coexistence: status_rows + ignored_sections + pattern_energy_rows preserved
# ---------------------------------------------------------------------------


def test_classification_coexists_with_other_diagnostics(tmp_path: Path) -> None:
    """All four Sprint 23 / 24 / 25 / 26 channels remain populated when
    classification fires."""
    text = _pump_inp(
        "[STATUS]\n PU1 OPEN\n"
        "[CONTROLS]\n LINK PU1 1.5 IF NODE J2 BELOW 5\n"
        "[RULES]\n RULE R1\n IF NODE J1 PRESSURE BELOW 20\n"
        "[PATTERNS]\n PAT1 0.5 0.6\n"
        "[ENERGY]\n GLOBAL PRICE 0.10\n"
    )
    path = _write(tmp_path, "coexist.inp", text)
    diag = load_inp_diagnostics(path, parser="fallback")
    # Sprint 23 — status rows preserved.
    assert [r.link_id for r in diag.status_rows] == ["PU1"]
    for rec in diag.status_rows:
        assert isinstance(rec, EpanetStatusDiagnostic)
    # Sprint 24 — ignored sections preserved.
    ignored_names = {r.section for r in diag.ignored_sections}
    assert {"CONTROLS", "RULES", "PATTERNS", "ENERGY"} <= ignored_names
    for rec in diag.ignored_sections:
        assert isinstance(rec, EpanetIgnoredSectionDiagnostic)
    # Sprint 26 — pattern/energy rows preserved.
    for rec in diag.pattern_energy_rows:
        assert isinstance(rec, EpanetPatternEnergyDiagnostic)
    pe_sections = {r.section for r in diag.pattern_energy_rows}
    assert pe_sections == {"PATTERNS", "ENERGY"}
    # Sprint 27 — classification on controls/rules.
    controls = [r for r in diag.control_rule_rows if r.section == "CONTROLS"]
    rules = [r for r in diag.control_rule_rows if r.section == "RULES"]
    assert len(controls) == 1
    assert controls[0].kind == EpanetControlKind.PUMP_SETTING
    assert len(rules) >= 1
    for rec in rules:
        assert rec.kind == EpanetControlKind.UNKNOWN


# ---------------------------------------------------------------------------
# Sprint 22 ``[STATUS]`` rejection paths still raise
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
def test_status_rejection_preserved_with_classified_controls(
    tmp_path: Path, status_block: str
) -> None:
    text = _baseline_inp(
        status_block + "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
    )
    path = _write(tmp_path, "rejected_with_classified.inp", text)
    with pytest.raises(ValueError):
        load_inp_diagnostics(path, parser="fallback")
    with pytest.raises(ValueError):
        load_network_from_inp(
            path, parser="fallback", return_diagnostics=True
        )


# ---------------------------------------------------------------------------
# Optional WNTR back-end: documented asymmetry preserved
# ---------------------------------------------------------------------------


def test_wntr_back_end_classification_empty(tmp_path: Path) -> None:
    """The WNTR back-end remains fallback-authoritative for Sprint 25/27
    control-row diagnostics. Its ``control_rule_rows`` tuple is empty,
    so there is no kind to inspect. The smoke check only confirms the
    API surface is preserved.

    The fixture deliberately uses only ``[CONTROLS]`` — WNTR's strict
    rule parser rejects malformed multi-line ``[RULES]`` blocks (it
    cannot evaluate a bare ``RULE`` header without a body), and the
    fallback parser's intentionally lenient per-row visibility is
    documented as fallback-authoritative.
    """
    pytest.importorskip("wntr")
    text = _baseline_inp(
        "[CONTROLS]\n LINK P1 CLOSED IF NODE J1 BELOW 1\n"
    )
    path = _write(tmp_path, "wntr_classified.inp", text)
    diag = load_inp_diagnostics(path, parser="wntr")
    assert isinstance(diag, EpanetImportDiagnostics)
    assert diag.control_rule_rows == ()
