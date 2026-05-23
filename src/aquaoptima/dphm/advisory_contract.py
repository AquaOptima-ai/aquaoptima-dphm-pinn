"""Advisory safety contract (Sprint 37).

Sprint 37 introduces the first typed, frozen, read-only **advisory
safety contract** surface. It answers, given a contract plus a list of
hypothetical advisory proposals (and optionally a Sprint 36
:class:`DPLCalibrationLossReport`):

* would each proposal be *accepted* or *rejected* by the contract?
* exactly which contract rules did the proposal violate?
* deterministic, auditable reasons strings — never an actual setpoint
  write, never a live control output.

This module is **read-only / offline / no-write / no-control / no live
OT binding / no setpoint output / advisory proposal audit only**.
It contains:

* :class:`AdvisoryContractDiagnostics` — deterministic warnings /
  errors tuples.
* :class:`AdvisoryRule` — single allow / deny entry within a contract.
* :class:`AdvisoryContract` — frozen top-level allow-list / deny-list
  container.
* :class:`AdvisoryProposal` — proposed advisory value, never an
  actuator command.
* :class:`AdvisoryDecision` — deterministic per-proposal verdict.
* :func:`build_advisory_contract` — pure builder that canonicalises
  and validates contract rules.
* :func:`evaluate_advisory_proposals` — pure deterministic evaluator
  that returns ``tuple[AdvisoryDecision, ...]`` in input order.

Safety boundary (reaffirmed verbatim per Sprints 23-36):

* no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter is imported, registered, or polled;
* no write / control / setpoint path is exposed;
* no live OT binding is opened;
* no actuator / write surface is offered;
* no setpoint output is emitted;
* no automatic setpoint recommendation is produced — the Sprint 37
  surface only **audits hypothetical advisory proposals against a
  read-only contract**;
* no dPHM forward solve is invoked;
* no training loop / optimiser integration is performed;
* no ONNX / TensorRT / Jetson deployment is performed;
* no production savings / control claim is made.

A future advisory layer would need to (a) build a contract via this
sprint's :func:`build_advisory_contract`, (b) audit its candidate
proposals via :func:`evaluate_advisory_proposals`, and (c) drop any
proposal whose decision is rejected. Sprint 37 stops at step (b); it
never emits a setpoint and never opens a live binding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .dpl_calibration import DPLCalibrationLossReport
from .telemetry_tag_map import (
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_EDGE_VALVE_POSITION,
    TELEMETRY_AXIS_NODE_LEVEL,
    TELEMETRY_AXIS_NODE_PRESSURE,
)


# ---------------------------------------------------------------------------
# Canonical advisory axis tokens
# ---------------------------------------------------------------------------


ADVISORY_AXIS_PUMP_SPEED: str = "pump_speed"
ADVISORY_AXIS_VALVE_POSITION: str = "valve_position"
ADVISORY_AXIS_RESERVOIR_HEAD: str = "reservoir_head"
ADVISORY_AXIS_TANK_LEVEL: str = "tank_level"
ADVISORY_AXIS_NODE_PRESSURE: str = "node_pressure"
ADVISORY_AXIS_EDGE_FLOW: str = "edge_flow"
ADVISORY_AXIS_EDGE_VELOCITY: str = "edge_velocity"
ADVISORY_AXIS_STATUS: str = "status"

# Deterministic canonical order — used everywhere we iterate / sort axes.
ADVISORY_AXES: tuple[str, ...] = (
    ADVISORY_AXIS_PUMP_SPEED,
    ADVISORY_AXIS_VALVE_POSITION,
    ADVISORY_AXIS_RESERVOIR_HEAD,
    ADVISORY_AXIS_TANK_LEVEL,
    ADVISORY_AXIS_NODE_PRESSURE,
    ADVISORY_AXIS_EDGE_FLOW,
    ADVISORY_AXIS_EDGE_VELOCITY,
    ADVISORY_AXIS_STATUS,
)

# Status-style axes accept bool / 0|1 values; all others accept numeric.
_ADVISORY_STATUS_AXES: frozenset[str] = frozenset({ADVISORY_AXIS_STATUS})

# Advisory axis → Sprint 36 DPL axis token, for residual-support /
# axis-loss gating. Advisory axes that have no DPL counterpart cannot
# carry residual/loss guards — the contract builder rejects such rules.
_ADVISORY_TO_DPL_AXIS: Mapping[str, str] = {
    ADVISORY_AXIS_PUMP_SPEED: TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    ADVISORY_AXIS_VALVE_POSITION: TELEMETRY_AXIS_EDGE_VALVE_POSITION,
    ADVISORY_AXIS_RESERVOIR_HEAD: TELEMETRY_AXIS_NODE_PRESSURE,
    ADVISORY_AXIS_TANK_LEVEL: TELEMETRY_AXIS_NODE_LEVEL,
    ADVISORY_AXIS_NODE_PRESSURE: TELEMETRY_AXIS_NODE_PRESSURE,
    ADVISORY_AXIS_EDGE_FLOW: TELEMETRY_AXIS_EDGE_FLOW,
}


# ---------------------------------------------------------------------------
# Decision status tokens
# ---------------------------------------------------------------------------


ADVISORY_STATUS_ACCEPTED: str = "accepted"
ADVISORY_STATUS_REJECTED: str = "rejected"
ADVISORY_STATUSES: tuple[str, ...] = (
    ADVISORY_STATUS_ACCEPTED,
    ADVISORY_STATUS_REJECTED,
)


# ---------------------------------------------------------------------------
# Frozen dataclass surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdvisoryContractDiagnostics:
    """Deterministic warnings / errors tuples.

    Both tuples are empty for a fully-valid input. Warnings are
    non-fatal observations (duplicate allow rule on the same axis /
    target id, overlap between allow- and deny-lists). Errors are
    structural problems (malformed rule, unknown axis, negative
    target id, non-finite bound, residual/loss guard on an axis
    without a DPL counterpart).

    In ``strict=True`` mode the builder / evaluator raises
    :class:`ValueError` instead of returning a populated ``errors``
    tuple. Warnings are *always* returned through this surface.

    Attributes
    ----------
    warnings
        Deterministic tuple of human-readable warning strings, in
        encounter order.
    errors
        Deterministic tuple of human-readable error strings, in
        encounter order.
    """

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdvisoryRule:
    """Single allow- or deny-list entry within an :class:`AdvisoryContract`.

    A rule names an ``(axis, target_id)`` pair plus optional guard
    fields. Allow rules are conditional accepts — every guard that is
    set must pass before the rule accepts the proposal. Deny rules are
    unconditional rejects on their ``(axis, target_id)`` pair; their
    guard fields are advisory metadata only and are *not* evaluated.

    Attributes
    ----------
    axis
        One of :data:`ADVISORY_AXES`.
    target_id
        Zero-based dPHM node / edge id this rule applies to. Must be
        ``>= 0``.
    min_value
        Optional inclusive lower bound on the proposed value. ``None``
        means no lower bound. Must be a finite ``float`` / ``int``
        when set.
    max_value
        Optional inclusive upper bound on the proposed value. ``None``
        means no upper bound. Must be a finite ``float`` / ``int``
        when set.
    max_abs_delta
        Optional non-negative maximum absolute deviation between the
        proposed value and a supplied reference value
        (:attr:`AdvisoryProposal.current_value` if present, otherwise
        :attr:`AdvisoryProposal.observed_value`). When the proposal
        carries no reference value, this guard is skipped — the
        evaluator records a deterministic warning instead.
    min_residual_support
        Optional non-negative minimum number of residuals (from a
        Sprint 36 :class:`DPLCalibrationLossReport`) on the mapped
        DPL axis *and* the same ``target_id`` that the contract
        requires before accepting a proposal on this rule. ``None``
        means no residual-support gate. Requires the rule's axis to
        be mappable to a DPL axis token.
    max_axis_loss
        Optional non-negative MSE threshold against
        :attr:`DPLCalibrationLossReport.mse_by_axis` on the mapped
        DPL axis. A proposal is rejected if the report's axis MSE is
        strictly greater than ``max_axis_loss``. ``None`` means no
        axis-loss gate. Requires the rule's axis to be mappable to a
        DPL axis token.
    note
        Optional free-form human-readable note kept verbatim. The
        evaluator never parses this string.
    """

    axis: str
    target_id: int
    min_value: float | None = None
    max_value: float | None = None
    max_abs_delta: float | None = None
    min_residual_support: int | None = None
    max_axis_loss: float | None = None
    note: str = ""


@dataclass(frozen=True)
class AdvisoryContract:
    """Frozen, read-only advisory safety contract.

    Carries an allow-list of :class:`AdvisoryRule` entries and an
    optional deny-list. The contract is the **only** surface a future
    advisory layer would consult before proposing a setpoint change —
    it is intentionally narrow, deterministic, and contains no live
    binding.

    Attributes
    ----------
    name
        Optional human-readable contract name. Kept verbatim.
    allow_rules
        Deterministic tuple of allow-list :class:`AdvisoryRule`
        entries, in builder input order. Multiple rules on the same
        ``(axis, target_id)`` are allowed; the evaluator applies all
        of them and requires every matching rule to pass.
    deny_rules
        Deterministic tuple of deny-list :class:`AdvisoryRule`
        entries. A proposal whose ``(axis, target_id)`` matches *any*
        deny rule is rejected unconditionally.
    diagnostics
        Build-time :class:`AdvisoryContractDiagnostics`.
    """

    name: str = ""
    allow_rules: tuple[AdvisoryRule, ...] = ()
    deny_rules: tuple[AdvisoryRule, ...] = ()
    diagnostics: AdvisoryContractDiagnostics = field(
        default_factory=AdvisoryContractDiagnostics
    )


@dataclass(frozen=True)
class AdvisoryProposal:
    """Proposed advisory value — *never* an actuator command.

    Carries enough metadata for the evaluator to audit the proposal
    against an :class:`AdvisoryContract`. Sprint 37 deliberately does
    **not** define a write / actuate method on this class. A future
    advisory layer would build a list of proposals, audit them, and
    drop any rejected proposal before any control output is emitted —
    that downstream emission step is **out of scope** for Sprint 37.

    Attributes
    ----------
    proposal_id
        Non-empty, deterministic identifier for the proposal. Used by
        the decision audit trail.
    axis
        One of :data:`ADVISORY_AXES`.
    target_id
        Zero-based dPHM node / edge id the proposal targets. Must be
        ``>= 0``.
    proposed_value
        Proposed advisory value. Numeric for non-status axes; for
        ``status``, either ``bool`` or ``0 / 1``.
    current_value
        Optional reference value the advisory layer would compute
        the delta against (e.g. the current setpoint). Used by the
        ``max_abs_delta`` guard.
    observed_value
        Optional secondary reference value (e.g. the latest observed
        sample on the same axis / target). Used by the
        ``max_abs_delta`` guard when ``current_value`` is absent.
    reason
        Optional human-readable rationale string kept verbatim.
    source
        Optional source identifier (e.g. the model / version that
        produced the proposal).
    metadata
        Optional ``{key: value}`` mapping for additional audit
        metadata. Kept verbatim — never parsed by the evaluator.
    """

    proposal_id: str
    axis: str
    target_id: int
    proposed_value: float
    current_value: float | None = None
    observed_value: float | None = None
    reason: str = ""
    source: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AdvisoryDecision:
    """Deterministic per-proposal verdict from
    :func:`evaluate_advisory_proposals`.

    Each decision carries the proposal verbatim plus a deterministic
    explanation of why the contract accepted or rejected it.

    Attributes
    ----------
    proposal
        The proposal this decision corresponds to.
    accepted
        ``True`` iff the proposal passed every applicable allow rule
        and did not hit a deny rule. Equivalent to
        ``status == ADVISORY_STATUS_ACCEPTED``.
    status
        One of :data:`ADVISORY_STATUSES`.
    reasons
        Deterministic tuple of human-readable strings explaining
        every rejection cause encountered. Empty for accepted
        proposals.
    violated_rules
        Deterministic tuple of rule descriptors (e.g.
        ``"allow_rules[3]:max_value"``) naming each rule that
        contributed to a rejection. Empty for accepted proposals.
    diagnostics
        Per-decision :class:`AdvisoryContractDiagnostics`. Used for
        non-fatal observations such as a ``max_abs_delta`` guard that
        could not be evaluated because the proposal carried no
        reference value.
    """

    proposal: AdvisoryProposal
    accepted: bool
    status: str
    reasons: tuple[str, ...] = ()
    violated_rules: tuple[str, ...] = ()
    diagnostics: AdvisoryContractDiagnostics = field(
        default_factory=AdvisoryContractDiagnostics
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    numeric = float(value)
    return not (math.isnan(numeric) or math.isinf(numeric))


def _coerce_status_value(value: object) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isnan(numeric) or math.isinf(numeric):
            return None
        if numeric == 0.0:
            return 0.0
        if numeric == 1.0:
            return 1.0
    return None


def _coerce_numeric_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isnan(numeric) or math.isinf(numeric):
            return None
        return numeric
    return None


def _validate_rule(
    rule: object, kind: str, index: int
) -> str | None:
    """Return ``None`` if ``rule`` is structurally valid, else error string."""
    if not isinstance(rule, AdvisoryRule):
        return (
            f"{kind}_rules[{index}]: expected AdvisoryRule, got "
            f"{type(rule).__name__}"
        )
    if rule.axis not in ADVISORY_AXES:
        return (
            f"{kind}_rules[{index}]: axis {rule.axis!r} is not a recognised "
            f"advisory axis; expected one of {list(ADVISORY_AXES)!r}"
        )
    if isinstance(rule.target_id, bool) or not isinstance(rule.target_id, int):
        return (
            f"{kind}_rules[{index}]: target_id must be a non-negative int, "
            f"got {rule.target_id!r}"
        )
    if rule.target_id < 0:
        return (
            f"{kind}_rules[{index}]: target_id must be >= 0, got "
            f"{rule.target_id}"
        )
    for bound_name in ("min_value", "max_value", "max_abs_delta", "max_axis_loss"):
        bound = getattr(rule, bound_name)
        if bound is None:
            continue
        if not _is_finite_number(bound):
            return (
                f"{kind}_rules[{index}]: {bound_name} must be a finite "
                f"number, got {bound!r}"
            )
    if rule.max_abs_delta is not None and float(rule.max_abs_delta) < 0.0:
        return (
            f"{kind}_rules[{index}]: max_abs_delta must be >= 0, got "
            f"{rule.max_abs_delta}"
        )
    if rule.max_axis_loss is not None and float(rule.max_axis_loss) < 0.0:
        return (
            f"{kind}_rules[{index}]: max_axis_loss must be >= 0, got "
            f"{rule.max_axis_loss}"
        )
    if (
        rule.min_value is not None
        and rule.max_value is not None
        and float(rule.min_value) > float(rule.max_value)
    ):
        return (
            f"{kind}_rules[{index}]: min_value {rule.min_value} is greater "
            f"than max_value {rule.max_value}"
        )
    if rule.min_residual_support is not None:
        if (
            isinstance(rule.min_residual_support, bool)
            or not isinstance(rule.min_residual_support, int)
        ):
            return (
                f"{kind}_rules[{index}]: min_residual_support must be a "
                f"non-negative int, got {rule.min_residual_support!r}"
            )
        if rule.min_residual_support < 0:
            return (
                f"{kind}_rules[{index}]: min_residual_support must be >= 0, "
                f"got {rule.min_residual_support}"
            )
    needs_dpl_mapping = (
        rule.min_residual_support is not None or rule.max_axis_loss is not None
    )
    if needs_dpl_mapping and rule.axis not in _ADVISORY_TO_DPL_AXIS:
        return (
            f"{kind}_rules[{index}]: axis {rule.axis!r} has no DPL axis "
            f"mapping; a residual-support or axis-loss guard cannot be set "
            f"on this axis"
        )
    if not isinstance(rule.note, str):
        return (
            f"{kind}_rules[{index}]: note must be a string, got "
            f"{type(rule.note).__name__}"
        )
    return None


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_advisory_contract(
    *,
    name: str = "",
    allow_rules: Sequence[AdvisoryRule] = (),
    deny_rules: Sequence[AdvisoryRule] = (),
    strict: bool = True,
) -> AdvisoryContract:
    """Canonicalise / validate contract inputs into a frozen
    :class:`AdvisoryContract`.

    The builder is **pure** and **offline / read-only / no-write /
    no-control**:

    * never mutates the supplied rule sequences;
    * never opens a socket / process / live binding;
    * never returns a write or control surface;
    * never invokes the dPHM forward solver.

    Parameters
    ----------
    name
        Optional human-readable contract name.
    allow_rules
        Sequence of :class:`AdvisoryRule` entries describing what the
        contract allows.
    deny_rules
        Sequence of :class:`AdvisoryRule` entries describing
        unconditional rejections. Guard fields on deny rules are
        kept verbatim but are *not* evaluated.
    strict
        When ``True`` (default), malformed rules raise
        :class:`ValueError`. When ``False``, the offending rule is
        omitted and its error string is appended to
        :attr:`AdvisoryContractDiagnostics.errors`.

    Returns
    -------
    AdvisoryContract
        Frozen, immutable contract.

    Raises
    ------
    ValueError
        See ``strict``. The ``allow_rules`` / ``deny_rules`` arguments
        must be true :class:`Sequence`\\ s (lists, tuples) — strings
        are rejected, generators are rejected.
    """
    if not isinstance(name, str):
        raise ValueError(
            f"name must be a string, got {type(name).__name__}"
        )
    for label, rules in (("allow_rules", allow_rules), ("deny_rules", deny_rules)):
        if isinstance(rules, (str, bytes)):
            raise ValueError(
                f"{label} must be a sequence of AdvisoryRule, not a string"
            )
        if not isinstance(rules, Sequence):
            raise ValueError(
                f"{label} must be a Sequence (list, tuple); got "
                f"{type(rules).__name__}"
            )

    warnings: list[str] = []
    errors: list[str] = []
    cleaned_allow: list[AdvisoryRule] = []
    cleaned_deny: list[AdvisoryRule] = []

    for index, rule in enumerate(allow_rules):
        err = _validate_rule(rule, "allow", index)
        if err is not None:
            if strict:
                raise ValueError(err)
            errors.append(err)
            continue
        cleaned_allow.append(rule)

    for index, rule in enumerate(deny_rules):
        err = _validate_rule(rule, "deny", index)
        if err is not None:
            if strict:
                raise ValueError(err)
            errors.append(err)
            continue
        cleaned_deny.append(rule)

    # Duplicate-allow warning (deterministic ordering).
    seen_allow: dict[tuple[str, int], int] = {}
    for idx, rule in enumerate(cleaned_allow):
        key = (rule.axis, rule.target_id)
        if key in seen_allow:
            warnings.append(
                f"allow_rules[{idx}]: duplicate (axis={rule.axis!r}, "
                f"target_id={rule.target_id}) — every matching rule must "
                f"pass for the proposal to be accepted"
            )
        else:
            seen_allow[key] = idx

    # Allow / deny overlap warning. Deny wins at evaluation time.
    deny_keys: set[tuple[str, int]] = {
        (r.axis, r.target_id) for r in cleaned_deny
    }
    for idx, rule in enumerate(cleaned_allow):
        if (rule.axis, rule.target_id) in deny_keys:
            warnings.append(
                f"allow_rules[{idx}]: (axis={rule.axis!r}, "
                f"target_id={rule.target_id}) also appears in deny_rules; "
                f"the deny-list takes precedence"
            )

    diagnostics = AdvisoryContractDiagnostics(
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    return AdvisoryContract(
        name=name,
        allow_rules=tuple(cleaned_allow),
        deny_rules=tuple(cleaned_deny),
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# Proposal validation helpers
# ---------------------------------------------------------------------------


def _validate_proposal(prop: object, index: int) -> str | None:
    if not isinstance(prop, AdvisoryProposal):
        return (
            f"proposals[{index}]: expected AdvisoryProposal, got "
            f"{type(prop).__name__}"
        )
    if not isinstance(prop.proposal_id, str) or not prop.proposal_id:
        return (
            f"proposals[{index}]: proposal_id must be a non-empty string, "
            f"got {prop.proposal_id!r}"
        )
    if prop.axis not in ADVISORY_AXES:
        return (
            f"proposals[{index}] ({prop.proposal_id!r}): axis "
            f"{prop.axis!r} is not a recognised advisory axis; expected "
            f"one of {list(ADVISORY_AXES)!r}"
        )
    if isinstance(prop.target_id, bool) or not isinstance(prop.target_id, int):
        return (
            f"proposals[{index}] ({prop.proposal_id!r}): target_id must be "
            f"a non-negative int, got {prop.target_id!r}"
        )
    if prop.target_id < 0:
        return (
            f"proposals[{index}] ({prop.proposal_id!r}): target_id must be "
            f">= 0, got {prop.target_id}"
        )
    if prop.axis in _ADVISORY_STATUS_AXES:
        coerced = _coerce_status_value(prop.proposed_value)
    else:
        coerced = _coerce_numeric_value(prop.proposed_value)
    if coerced is None:
        return (
            f"proposals[{index}] ({prop.proposal_id!r}): proposed_value "
            f"{prop.proposed_value!r} is not coercible to a finite "
            f"{'status (0/1)' if prop.axis in _ADVISORY_STATUS_AXES else 'numeric'} "
            f"value"
        )
    for ref_name in ("current_value", "observed_value"):
        ref = getattr(prop, ref_name)
        if ref is None:
            continue
        if isinstance(ref, bool) or not isinstance(ref, (int, float)):
            return (
                f"proposals[{index}] ({prop.proposal_id!r}): {ref_name} "
                f"must be a finite number, got {ref!r}"
            )
        if math.isnan(float(ref)) or math.isinf(float(ref)):
            return (
                f"proposals[{index}] ({prop.proposal_id!r}): {ref_name} "
                f"must be finite, got {ref!r}"
            )
    if not isinstance(prop.metadata, Mapping):
        return (
            f"proposals[{index}] ({prop.proposal_id!r}): metadata must be "
            f"a Mapping, got {type(prop.metadata).__name__}"
        )
    return None


def _proposal_value_as_float(prop: AdvisoryProposal) -> float:
    """Return the proposed value coerced to a finite float.

    Caller must have already validated the proposal via
    :func:`_validate_proposal`.
    """
    if prop.axis in _ADVISORY_STATUS_AXES:
        coerced = _coerce_status_value(prop.proposed_value)
    else:
        coerced = _coerce_numeric_value(prop.proposed_value)
    # _validate_proposal guarantees this is not None.
    assert coerced is not None
    return coerced


def _reference_value(prop: AdvisoryProposal) -> float | None:
    """Return the reference value used by the ``max_abs_delta`` guard.

    Prefers ``current_value`` over ``observed_value``. Returns
    ``None`` when neither is supplied.
    """
    if prop.current_value is not None:
        return float(prop.current_value)
    if prop.observed_value is not None:
        return float(prop.observed_value)
    return None


# ---------------------------------------------------------------------------
# Rule-guard application
# ---------------------------------------------------------------------------


def _apply_rule_guards(
    rule: AdvisoryRule,
    rule_label: str,
    proposal: AdvisoryProposal,
    proposed_value: float,
    *,
    residual_counts: Mapping[tuple[str, int], int],
    loss_report: DPLCalibrationLossReport | None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Apply every guard on ``rule`` to ``proposal``.

    Returns ``(violations, warnings)``:

    * ``violations`` — list of ``(reason, rule_descriptor)`` tuples,
      one entry per failed guard.
    * ``warnings`` — list of human-readable warning strings (e.g.
      a ``max_abs_delta`` guard could not be evaluated because no
      reference value was supplied).
    """
    violations: list[tuple[str, str]] = []
    warnings: list[str] = []

    if rule.min_value is not None and proposed_value < float(rule.min_value):
        violations.append(
            (
                f"{proposal.proposal_id!r}: proposed value {proposed_value} "
                f"is below {rule_label} min_value {float(rule.min_value)}",
                f"{rule_label}:min_value",
            )
        )
    if rule.max_value is not None and proposed_value > float(rule.max_value):
        violations.append(
            (
                f"{proposal.proposal_id!r}: proposed value {proposed_value} "
                f"is above {rule_label} max_value {float(rule.max_value)}",
                f"{rule_label}:max_value",
            )
        )
    if rule.max_abs_delta is not None:
        reference = _reference_value(proposal)
        if reference is None:
            warnings.append(
                f"{proposal.proposal_id!r}: {rule_label} max_abs_delta "
                f"guard was skipped because the proposal carries neither "
                f"current_value nor observed_value"
            )
        else:
            delta = abs(proposed_value - reference)
            if delta > float(rule.max_abs_delta):
                violations.append(
                    (
                        f"{proposal.proposal_id!r}: |proposed - reference| "
                        f"= {delta} exceeds {rule_label} max_abs_delta "
                        f"{float(rule.max_abs_delta)} (reference={reference})",
                        f"{rule_label}:max_abs_delta",
                    )
                )

    if rule.min_residual_support is not None:
        dpl_axis = _ADVISORY_TO_DPL_AXIS.get(rule.axis)
        # Builder rejected rules whose axis cannot be mapped.
        assert dpl_axis is not None
        if loss_report is None:
            violations.append(
                (
                    f"{proposal.proposal_id!r}: {rule_label} "
                    f"min_residual_support={int(rule.min_residual_support)} "
                    f"requires a DPLCalibrationLossReport but none was "
                    f"supplied",
                    f"{rule_label}:min_residual_support",
                )
            )
        else:
            count = int(residual_counts.get((dpl_axis, proposal.target_id), 0))
            if count < int(rule.min_residual_support):
                violations.append(
                    (
                        f"{proposal.proposal_id!r}: residual support "
                        f"{count} on DPL axis {dpl_axis!r} target "
                        f"{proposal.target_id} is below {rule_label} "
                        f"min_residual_support "
                        f"{int(rule.min_residual_support)}",
                        f"{rule_label}:min_residual_support",
                    )
                )

    if rule.max_axis_loss is not None:
        dpl_axis = _ADVISORY_TO_DPL_AXIS.get(rule.axis)
        assert dpl_axis is not None
        if loss_report is None:
            violations.append(
                (
                    f"{proposal.proposal_id!r}: {rule_label} "
                    f"max_axis_loss={float(rule.max_axis_loss)} requires a "
                    f"DPLCalibrationLossReport but none was supplied",
                    f"{rule_label}:max_axis_loss",
                )
            )
        else:
            axis_mse = float(loss_report.mse_by_axis.get(dpl_axis, 0.0))
            if axis_mse > float(rule.max_axis_loss):
                violations.append(
                    (
                        f"{proposal.proposal_id!r}: DPL axis {dpl_axis!r} "
                        f"MSE {axis_mse} exceeds {rule_label} "
                        f"max_axis_loss {float(rule.max_axis_loss)}",
                        f"{rule_label}:max_axis_loss",
                    )
                )

    return violations, warnings


# ---------------------------------------------------------------------------
# Public evaluator
# ---------------------------------------------------------------------------


def evaluate_advisory_proposals(
    contract: AdvisoryContract,
    proposals: Sequence[AdvisoryProposal],
    *,
    loss_report: DPLCalibrationLossReport | None = None,
    strict: bool = True,
) -> tuple[AdvisoryDecision, ...]:
    """Evaluate ``proposals`` against ``contract`` and return decisions.

    The evaluator is **pure** and **offline / read-only / no-write /
    no-control**:

    * never mutates ``contract``, ``proposals``, or ``loss_report``;
    * never opens a socket / process / live binding;
    * never returns a write or control surface;
    * never invokes the dPHM forward solver;
    * never emits a setpoint, never publishes, never contacts an
      external system.

    Parameters
    ----------
    contract
        The :class:`AdvisoryContract` to audit against.
    proposals
        Sequence of :class:`AdvisoryProposal` entries. The returned
        decisions are in the same order as the input.
    loss_report
        Optional Sprint 36 :class:`DPLCalibrationLossReport` used to
        evaluate ``min_residual_support`` and ``max_axis_loss``
        guards. When ``None``, rules that *require* a loss report
        produce a rejection.
    strict
        When ``True`` (default), malformed proposals raise
        :class:`ValueError`. When ``False``, the offending proposal
        produces a rejected decision whose ``diagnostics.errors``
        carries the explanation and the rest of the input is still
        processed deterministically.

    Returns
    -------
    tuple[AdvisoryDecision, ...]
        One :class:`AdvisoryDecision` per input proposal, in input
        order.

    Raises
    ------
    ValueError
        See ``strict``. ``contract`` must be an
        :class:`AdvisoryContract`, ``proposals`` must be a
        :class:`Sequence` (not a generator or string), and
        ``loss_report`` must be a
        :class:`DPLCalibrationLossReport` when supplied.
    """
    if not isinstance(contract, AdvisoryContract):
        raise ValueError(
            f"contract must be an AdvisoryContract, got "
            f"{type(contract).__name__}"
        )
    if isinstance(proposals, (str, bytes)):
        raise ValueError("proposals must be a sequence, not a string")
    if not isinstance(proposals, Sequence):
        raise ValueError(
            f"proposals must be a Sequence (list, tuple); got "
            f"{type(proposals).__name__}"
        )
    if loss_report is not None and not isinstance(
        loss_report, DPLCalibrationLossReport
    ):
        raise ValueError(
            f"loss_report must be a DPLCalibrationLossReport or None, got "
            f"{type(loss_report).__name__}"
        )

    # Precompute residual counts keyed by (dpl_axis, target_id).
    residual_counts: dict[tuple[str, int], int] = {}
    if loss_report is not None:
        for r in loss_report.residuals:
            key = (r.axis, int(r.target_id))
            residual_counts[key] = residual_counts.get(key, 0) + 1

    # Index allow rules by (axis, target_id) preserving insertion order.
    allow_index: dict[tuple[str, int], list[tuple[int, AdvisoryRule]]] = {}
    for idx, rule in enumerate(contract.allow_rules):
        allow_index.setdefault((rule.axis, rule.target_id), []).append(
            (idx, rule)
        )
    deny_index: dict[tuple[str, int], list[int]] = {}
    for idx, rule in enumerate(contract.deny_rules):
        deny_index.setdefault((rule.axis, rule.target_id), []).append(idx)

    decisions: list[AdvisoryDecision] = []
    for index, prop in enumerate(proposals):
        err = _validate_proposal(prop, index)
        if err is not None:
            if strict:
                raise ValueError(err)
            placeholder = (
                prop
                if isinstance(prop, AdvisoryProposal)
                else AdvisoryProposal(
                    proposal_id=f"<malformed[{index}]>",
                    axis=ADVISORY_AXIS_PUMP_SPEED,
                    target_id=0,
                    proposed_value=0.0,
                )
            )
            decisions.append(
                AdvisoryDecision(
                    proposal=placeholder,
                    accepted=False,
                    status=ADVISORY_STATUS_REJECTED,
                    reasons=(err,),
                    violated_rules=("malformed_proposal",),
                    diagnostics=AdvisoryContractDiagnostics(
                        errors=(err,),
                    ),
                )
            )
            continue

        reasons: list[str] = []
        violated_rules: list[str] = []
        warnings: list[str] = []

        proposed_value = _proposal_value_as_float(prop)
        key = (prop.axis, prop.target_id)

        # Deny rules — first match wins; emit one violation per
        # matching deny rule for full auditability.
        for deny_idx in deny_index.get(key, ()):
            reasons.append(
                f"{prop.proposal_id!r}: (axis={prop.axis!r}, "
                f"target_id={prop.target_id}) matches deny_rules[{deny_idx}]"
            )
            violated_rules.append(f"deny_rules[{deny_idx}]")

        # Allow rules — every matching allow rule must pass.
        matching_allow = allow_index.get(key, [])
        if not matching_allow:
            reasons.append(
                f"{prop.proposal_id!r}: no allow_rules entry matches "
                f"(axis={prop.axis!r}, target_id={prop.target_id})"
            )
            violated_rules.append("allow_rules:miss")
        else:
            for rule_idx, rule in matching_allow:
                rule_label = f"allow_rules[{rule_idx}]"
                viols, warns = _apply_rule_guards(
                    rule,
                    rule_label,
                    prop,
                    proposed_value,
                    residual_counts=residual_counts,
                    loss_report=loss_report,
                )
                for reason, descriptor in viols:
                    reasons.append(reason)
                    violated_rules.append(descriptor)
                warnings.extend(warns)

        accepted = not reasons
        status = (
            ADVISORY_STATUS_ACCEPTED if accepted else ADVISORY_STATUS_REJECTED
        )
        decisions.append(
            AdvisoryDecision(
                proposal=prop,
                accepted=accepted,
                status=status,
                reasons=tuple(reasons),
                violated_rules=tuple(violated_rules),
                diagnostics=AdvisoryContractDiagnostics(
                    warnings=tuple(warnings),
                ),
            )
        )

    return tuple(decisions)


__all__ = [
    "ADVISORY_AXES",
    "ADVISORY_AXIS_EDGE_FLOW",
    "ADVISORY_AXIS_EDGE_VELOCITY",
    "ADVISORY_AXIS_NODE_PRESSURE",
    "ADVISORY_AXIS_PUMP_SPEED",
    "ADVISORY_AXIS_RESERVOIR_HEAD",
    "ADVISORY_AXIS_STATUS",
    "ADVISORY_AXIS_TANK_LEVEL",
    "ADVISORY_AXIS_VALVE_POSITION",
    "ADVISORY_STATUSES",
    "ADVISORY_STATUS_ACCEPTED",
    "ADVISORY_STATUS_REJECTED",
    "AdvisoryContract",
    "AdvisoryContractDiagnostics",
    "AdvisoryDecision",
    "AdvisoryProposal",
    "AdvisoryRule",
    "build_advisory_contract",
    "evaluate_advisory_proposals",
]
