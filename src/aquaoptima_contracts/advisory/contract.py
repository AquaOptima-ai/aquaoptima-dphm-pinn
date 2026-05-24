"""``AdvisoryContract`` SDK projections (Sprint 43) — audit-only.

These types capture the *audit-only* shape of the Phase 1 Sprint 37
advisory surface. The Phase 1 module
``aquaoptima.dphm.advisory_contract`` continues to own
``evaluate_advisory_proposals`` and the actual proposal evaluation
math.

The SDK projection here intentionally cannot represent a write or
actuation payload:

* :class:`AdvisoryProposal` carries a numeric ``proposed_value`` field
  and a free-form audit ``reason`` string — never a write or
  dispatch verb;
* :class:`AdvisoryDecision` carries one of two statuses
  (``accepted`` / ``rejected``) — no actuation status;
* the field names ``setpoint``, ``write``, ``control``, ``command``,
  ``actuate``, ``dispatch`` are deliberately absent from every
  dataclass.

The advisory axes here are intentionally a separate vocabulary from
the canonical telemetry axes. The Phase 1 module uses these as the
operator-side names of the targets a hypothetical proposal would
touch (``pump_speed``, ``valve_position``, ``tank_level``, …).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError


# ---------------------------------------------------------------------------
# Canonical vocabularies (audit-only — none of these can carry actuation)
# ---------------------------------------------------------------------------


ADVISORY_SDK_AXES: frozenset[str] = frozenset(
    {
        "pump_speed",
        "valve_position",
        "reservoir_head",
        "tank_level",
        "node_pressure",
        "edge_flow",
        "edge_velocity",
        "status",
    }
)


ADVISORY_RULE_MODES: frozenset[str] = frozenset({"allow", "deny"})


ADVISORY_STATUS_ACCEPTED: str = "accepted"
ADVISORY_STATUS_REJECTED: str = "rejected"
ADVISORY_DECISION_STATUSES: frozenset[str] = frozenset(
    {ADVISORY_STATUS_ACCEPTED, ADVISORY_STATUS_REJECTED}
)


# Machine-readable rejection vocabulary. Each entry maps a rejection
# cause that downstream audit consumers can switch on without parsing
# the free-text description.
ADVISORY_REJECTION_REASONS: frozenset[str] = frozenset(
    {
        "out_of_bounds",
        "delta_exceeded",
        "deny_rule_match",
        "no_allow_rule_match",
        "insufficient_evidence",
        "axis_loss_exceeded",
        "malformed_proposal",
    }
)


_RULE_FIELDS: tuple[str, ...] = (
    "rule_id",
    "axis",
    "target_id",
    "mode",
    "min_value",
    "max_value",
    "max_abs_delta",
    "min_evidence_count",
    "max_axis_loss",
    "note",
)


_CONTRACT_FIELDS: tuple[str, ...] = (
    "name",
    "allow_rules",
    "deny_rules",
)


_PROPOSAL_FIELDS: tuple[str, ...] = (
    "proposal_id",
    "axis",
    "target_id",
    "proposed_value",
    "current_value",
    "observed_value",
    "reason",
    "source",
)


_REJECTION_FIELDS: tuple[str, ...] = (
    "code",
    "rule_id",
    "description",
)


_DECISION_FIELDS: tuple[str, ...] = (
    "proposal",
    "status",
    "accepted",
    "rejection_reasons",
    "violated_rule_ids",
    "warnings",
)


_EVALUATION_FIELDS: tuple[str, ...] = (
    "contract_name",
    "decisions",
    "proposal_count",
    "accepted_count",
    "rejected_count",
    "warnings",
)


def _ensure_finite_optional(value: object, *, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(
            f"{label} must be a finite float or None, got {type(value).__name__}"
        )
    numeric = float(value)
    if math.isnan(numeric) or math.isinf(numeric):
        raise ContractError(f"{label} must be finite, got {value!r}")
    return numeric


def _ensure_finite(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(
            f"{label} must be a finite float, got {type(value).__name__}"
        )
    numeric = float(value)
    if math.isnan(numeric) or math.isinf(numeric):
        raise ContractError(f"{label} must be finite, got {value!r}")
    return numeric


def _ensure_str_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if isinstance(value, str) or isinstance(value, bytes):
        raise ContractError(f"{label} must be a tuple of strings")
    if not isinstance(value, tuple):
        raise ContractError(f"{label} must be a tuple of strings")
    for item in value:
        if not isinstance(item, str):
            raise ContractError(f"{label} entries must be strings")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class AdvisoryRule:
    """SDK allow / deny rule projection (audit only)."""

    rule_id: str
    axis: str
    target_id: int
    mode: str
    min_value: float | None = None
    max_value: float | None = None
    max_abs_delta: float | None = None
    min_evidence_count: int | None = None
    max_axis_loss: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise ContractError("AdvisoryRule.rule_id must be a non-empty string")
        if not isinstance(self.axis, str) or self.axis not in ADVISORY_SDK_AXES:
            raise ContractError(
                f"AdvisoryRule.axis {self.axis!r} is not a canonical SDK "
                f"advisory axis; allowed: {sorted(ADVISORY_SDK_AXES)}"
            )
        if isinstance(self.target_id, bool) or not isinstance(self.target_id, int):
            raise ContractError("AdvisoryRule.target_id must be int")
        if self.target_id < 0:
            raise ContractError(
                "AdvisoryRule.target_id must be non-negative"
            )
        if not isinstance(self.mode, str) or self.mode not in ADVISORY_RULE_MODES:
            raise ContractError(
                f"AdvisoryRule.mode {self.mode!r} must be one of "
                f"{sorted(ADVISORY_RULE_MODES)}"
            )
        min_value = _ensure_finite_optional(
            self.min_value, label="AdvisoryRule.min_value"
        )
        max_value = _ensure_finite_optional(
            self.max_value, label="AdvisoryRule.max_value"
        )
        max_abs_delta = _ensure_finite_optional(
            self.max_abs_delta, label="AdvisoryRule.max_abs_delta"
        )
        max_axis_loss = _ensure_finite_optional(
            self.max_axis_loss, label="AdvisoryRule.max_axis_loss"
        )
        if max_abs_delta is not None and max_abs_delta < 0.0:
            raise ContractError(
                "AdvisoryRule.max_abs_delta must be non-negative"
            )
        if max_axis_loss is not None and max_axis_loss < 0.0:
            raise ContractError(
                "AdvisoryRule.max_axis_loss must be non-negative"
            )
        if min_value is not None and max_value is not None and min_value > max_value:
            raise ContractError(
                f"AdvisoryRule: min_value {min_value} is greater than "
                f"max_value {max_value}"
            )
        if self.min_evidence_count is not None:
            if (
                isinstance(self.min_evidence_count, bool)
                or not isinstance(self.min_evidence_count, int)
            ):
                raise ContractError(
                    "AdvisoryRule.min_evidence_count must be int or None"
                )
            if self.min_evidence_count < 0:
                raise ContractError(
                    "AdvisoryRule.min_evidence_count must be non-negative"
                )
        if not isinstance(self.note, str):
            raise ContractError("AdvisoryRule.note must be a string")
        object.__setattr__(self, "min_value", min_value)
        object.__setattr__(self, "max_value", max_value)
        object.__setattr__(self, "max_abs_delta", max_abs_delta)
        object.__setattr__(self, "max_axis_loss", max_axis_loss)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "axis": self.axis,
            "target_id": self.target_id,
            "mode": self.mode,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "max_abs_delta": self.max_abs_delta,
            "min_evidence_count": self.min_evidence_count,
            "max_axis_loss": self.max_axis_loss,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdvisoryRule":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AdvisoryRule.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {"rule_id", "axis", "target_id", "mode"} - set(data.keys())
        if missing:
            raise ContractError(
                f"AdvisoryRule missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_RULE_FIELDS)
        if unknown:
            raise ContractError(
                f"AdvisoryRule received unknown fields: {sorted(unknown)}"
            )
        return cls(
            rule_id=str(data["rule_id"]),
            axis=str(data["axis"]),
            target_id=int(data["target_id"]),
            mode=str(data["mode"]),
            min_value=(
                float(data["min_value"])
                if data.get("min_value") is not None
                else None
            ),
            max_value=(
                float(data["max_value"])
                if data.get("max_value") is not None
                else None
            ),
            max_abs_delta=(
                float(data["max_abs_delta"])
                if data.get("max_abs_delta") is not None
                else None
            ),
            min_evidence_count=(
                int(data["min_evidence_count"])
                if data.get("min_evidence_count") is not None
                else None
            ),
            max_axis_loss=(
                float(data["max_axis_loss"])
                if data.get("max_axis_loss") is not None
                else None
            ),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True)
class AdvisoryContract:
    """SDK allow-list / deny-list bundle (audit only)."""

    name: str = ""
    allow_rules: tuple[AdvisoryRule, ...] = ()
    deny_rules: tuple[AdvisoryRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise ContractError("AdvisoryContract.name must be a string")
        for label, rules in (
            ("allow_rules", self.allow_rules),
            ("deny_rules", self.deny_rules),
        ):
            if not isinstance(rules, tuple):
                raise ContractError(
                    f"AdvisoryContract.{label} must be a tuple"
                )
            for rule in rules:
                if not isinstance(rule, AdvisoryRule):
                    raise ContractError(
                        f"AdvisoryContract.{label} entries must be "
                        f"AdvisoryRule instances"
                    )
        for rule in self.allow_rules:
            if rule.mode != "allow":
                raise ContractError(
                    f"AdvisoryContract.allow_rules entry {rule.rule_id!r} "
                    f"has mode {rule.mode!r}; expected 'allow'"
                )
        for rule in self.deny_rules:
            if rule.mode != "deny":
                raise ContractError(
                    f"AdvisoryContract.deny_rules entry {rule.rule_id!r} "
                    f"has mode {rule.mode!r}; expected 'deny'"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "allow_rules": [r.to_dict() for r in self.allow_rules],
            "deny_rules": [r.to_dict() for r in self.deny_rules],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdvisoryContract":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AdvisoryContract.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_CONTRACT_FIELDS)
        if unknown:
            raise ContractError(
                f"AdvisoryContract received unknown fields: {sorted(unknown)}"
            )
        raw_allow = data.get("allow_rules", ())
        raw_deny = data.get("deny_rules", ())
        for label, raw in (("allow_rules", raw_allow), ("deny_rules", raw_deny)):
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                raise ContractError(
                    f"AdvisoryContract.{label} must be a sequence"
                )
        return cls(
            name=str(data.get("name", "")),
            allow_rules=tuple(AdvisoryRule.from_dict(r) for r in raw_allow),
            deny_rules=tuple(AdvisoryRule.from_dict(r) for r in raw_deny),
        )


@dataclass(frozen=True)
class AdvisoryProposal:
    """Hypothetical advisory proposal — audit only, never an actuation."""

    proposal_id: str
    axis: str
    target_id: int
    proposed_value: float
    current_value: float | None = None
    observed_value: float | None = None
    reason: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise ContractError(
                "AdvisoryProposal.proposal_id must be a non-empty string"
            )
        if not isinstance(self.axis, str) or self.axis not in ADVISORY_SDK_AXES:
            raise ContractError(
                f"AdvisoryProposal.axis {self.axis!r} is not a canonical "
                f"SDK advisory axis; allowed: {sorted(ADVISORY_SDK_AXES)}"
            )
        if isinstance(self.target_id, bool) or not isinstance(self.target_id, int):
            raise ContractError("AdvisoryProposal.target_id must be int")
        if self.target_id < 0:
            raise ContractError(
                "AdvisoryProposal.target_id must be non-negative"
            )
        proposed = _ensure_finite(
            self.proposed_value, label="AdvisoryProposal.proposed_value"
        )
        object.__setattr__(self, "proposed_value", proposed)
        current = _ensure_finite_optional(
            self.current_value, label="AdvisoryProposal.current_value"
        )
        observed = _ensure_finite_optional(
            self.observed_value, label="AdvisoryProposal.observed_value"
        )
        object.__setattr__(self, "current_value", current)
        object.__setattr__(self, "observed_value", observed)
        for name in ("reason", "source"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ContractError(
                    f"AdvisoryProposal.{name} must be a string"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "axis": self.axis,
            "target_id": self.target_id,
            "proposed_value": self.proposed_value,
            "current_value": self.current_value,
            "observed_value": self.observed_value,
            "reason": self.reason,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdvisoryProposal":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AdvisoryProposal.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {
            "proposal_id",
            "axis",
            "target_id",
            "proposed_value",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AdvisoryProposal missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_PROPOSAL_FIELDS)
        if unknown:
            raise ContractError(
                f"AdvisoryProposal received unknown fields: {sorted(unknown)}"
            )
        return cls(
            proposal_id=str(data["proposal_id"]),
            axis=str(data["axis"]),
            target_id=int(data["target_id"]),
            proposed_value=float(data["proposed_value"]),
            current_value=(
                float(data["current_value"])
                if data.get("current_value") is not None
                else None
            ),
            observed_value=(
                float(data["observed_value"])
                if data.get("observed_value") is not None
                else None
            ),
            reason=str(data.get("reason", "")),
            source=str(data.get("source", "")),
        )


@dataclass(frozen=True)
class AdvisoryRejectionReason:
    """Machine-readable rejection cause attached to an
    :class:`AdvisoryDecision`."""

    code: str
    rule_id: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str)
            or self.code not in ADVISORY_REJECTION_REASONS
        ):
            raise ContractError(
                f"AdvisoryRejectionReason.code {self.code!r} is not in the "
                f"canonical rejection vocabulary; allowed: "
                f"{sorted(ADVISORY_REJECTION_REASONS)}"
            )
        for name in ("rule_id", "description"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ContractError(
                    f"AdvisoryRejectionReason.{name} must be a string"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "rule_id": self.rule_id,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdvisoryRejectionReason":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AdvisoryRejectionReason.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        if "code" not in data:
            raise ContractError(
                "AdvisoryRejectionReason missing required field 'code'"
            )
        unknown = set(data.keys()) - set(_REJECTION_FIELDS)
        if unknown:
            raise ContractError(
                f"AdvisoryRejectionReason received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            code=str(data["code"]),
            rule_id=str(data.get("rule_id", "")),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True)
class AdvisoryDecision:
    """Per-proposal audit verdict — accepted or rejected only."""

    proposal: AdvisoryProposal
    status: str
    accepted: bool
    rejection_reasons: tuple[AdvisoryRejectionReason, ...] = ()
    violated_rule_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, AdvisoryProposal):
            raise ContractError(
                "AdvisoryDecision.proposal must be an AdvisoryProposal"
            )
        if (
            not isinstance(self.status, str)
            or self.status not in ADVISORY_DECISION_STATUSES
        ):
            raise ContractError(
                f"AdvisoryDecision.status {self.status!r} must be one of "
                f"{sorted(ADVISORY_DECISION_STATUSES)}"
            )
        if not isinstance(self.accepted, bool):
            raise ContractError(
                "AdvisoryDecision.accepted must be a bool"
            )
        if self.accepted and self.status != ADVISORY_STATUS_ACCEPTED:
            raise ContractError(
                "AdvisoryDecision.accepted is True but status is not "
                f"{ADVISORY_STATUS_ACCEPTED!r}"
            )
        if not self.accepted and self.status != ADVISORY_STATUS_REJECTED:
            raise ContractError(
                "AdvisoryDecision.accepted is False but status is not "
                f"{ADVISORY_STATUS_REJECTED!r}"
            )
        if not isinstance(self.rejection_reasons, tuple):
            raise ContractError(
                "AdvisoryDecision.rejection_reasons must be a tuple"
            )
        for reason in self.rejection_reasons:
            if not isinstance(reason, AdvisoryRejectionReason):
                raise ContractError(
                    "AdvisoryDecision.rejection_reasons entries must be "
                    "AdvisoryRejectionReason instances"
                )
        _ensure_str_tuple(
            self.violated_rule_ids, label="AdvisoryDecision.violated_rule_ids"
        )
        _ensure_str_tuple(self.warnings, label="AdvisoryDecision.warnings")
        if self.accepted and self.rejection_reasons:
            raise ContractError(
                "AdvisoryDecision: accepted decision must not carry "
                "rejection_reasons"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.to_dict(),
            "status": self.status,
            "accepted": self.accepted,
            "rejection_reasons": [r.to_dict() for r in self.rejection_reasons],
            "violated_rule_ids": list(self.violated_rule_ids),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdvisoryDecision":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AdvisoryDecision.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {"proposal", "status", "accepted"} - set(data.keys())
        if missing:
            raise ContractError(
                f"AdvisoryDecision missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_DECISION_FIELDS)
        if unknown:
            raise ContractError(
                f"AdvisoryDecision received unknown fields: {sorted(unknown)}"
            )
        raw_reasons = data.get("rejection_reasons", ())
        if not isinstance(raw_reasons, Sequence) or isinstance(
            raw_reasons, (str, bytes)
        ):
            raise ContractError(
                "AdvisoryDecision.rejection_reasons must be a sequence"
            )
        return cls(
            proposal=AdvisoryProposal.from_dict(data["proposal"]),
            status=str(data["status"]),
            accepted=bool(data["accepted"]),
            rejection_reasons=tuple(
                AdvisoryRejectionReason.from_dict(r) for r in raw_reasons
            ),
            violated_rule_ids=tuple(
                str(s) for s in data.get("violated_rule_ids", ())
            ),
            warnings=tuple(str(w) for w in data.get("warnings", ())),
        )


@dataclass(frozen=True)
class AdvisoryEvaluation:
    """Bundle of advisory decisions plus aggregate audit counts."""

    contract_name: str = ""
    decisions: tuple[AdvisoryDecision, ...] = ()
    proposal_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.contract_name, str):
            raise ContractError(
                "AdvisoryEvaluation.contract_name must be a string"
            )
        if not isinstance(self.decisions, tuple):
            raise ContractError(
                "AdvisoryEvaluation.decisions must be a tuple"
            )
        for d in self.decisions:
            if not isinstance(d, AdvisoryDecision):
                raise ContractError(
                    "AdvisoryEvaluation.decisions entries must be "
                    "AdvisoryDecision instances"
                )
        for name in ("proposal_count", "accepted_count", "rejected_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ContractError(
                    f"AdvisoryEvaluation.{name} must be int"
                )
            if value < 0:
                raise ContractError(
                    f"AdvisoryEvaluation.{name} must be non-negative"
                )
        if self.proposal_count != len(self.decisions):
            raise ContractError(
                f"AdvisoryEvaluation.proposal_count {self.proposal_count} "
                f"does not match len(decisions)={len(self.decisions)}"
            )
        if self.accepted_count + self.rejected_count != self.proposal_count:
            raise ContractError(
                "AdvisoryEvaluation: accepted_count + rejected_count "
                f"({self.accepted_count} + {self.rejected_count}) does not "
                f"match proposal_count {self.proposal_count}"
            )
        actual_accepted = sum(1 for d in self.decisions if d.accepted)
        if actual_accepted != self.accepted_count:
            raise ContractError(
                f"AdvisoryEvaluation.accepted_count {self.accepted_count} "
                f"disagrees with decisions ({actual_accepted})"
            )
        _ensure_str_tuple(self.warnings, label="AdvisoryEvaluation.warnings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_name": self.contract_name,
            "decisions": [d.to_dict() for d in self.decisions],
            "proposal_count": self.proposal_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdvisoryEvaluation":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AdvisoryEvaluation.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_EVALUATION_FIELDS)
        if unknown:
            raise ContractError(
                f"AdvisoryEvaluation received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_decisions = data.get("decisions", ())
        if not isinstance(raw_decisions, Sequence) or isinstance(
            raw_decisions, (str, bytes)
        ):
            raise ContractError(
                "AdvisoryEvaluation.decisions must be a sequence"
            )
        decisions = tuple(
            AdvisoryDecision.from_dict(d) for d in raw_decisions
        )
        return cls(
            contract_name=str(data.get("contract_name", "")),
            decisions=decisions,
            proposal_count=int(data.get("proposal_count", len(decisions))),
            accepted_count=int(
                data.get(
                    "accepted_count",
                    sum(1 for d in decisions if d.accepted),
                )
            ),
            rejected_count=int(
                data.get(
                    "rejected_count",
                    sum(1 for d in decisions if not d.accepted),
                )
            ),
            warnings=tuple(str(w) for w in data.get("warnings", ())),
        )


# ---------------------------------------------------------------------------
# Phase 1 projection adapters
# ---------------------------------------------------------------------------


def _coerce_phase1_rejection_reason(
    raw_descriptor: str, raw_reason: str
) -> AdvisoryRejectionReason:
    """Coerce a Phase 1 ``violated_rules`` descriptor into a canonical SDK
    rejection reason. The Phase 1 strings are formatted as
    ``allow_rules[0]:max_value`` or ``deny_rules[1]`` (or the literal
    ``allow_rules:miss`` / ``malformed_proposal`` for the misses).
    """
    descriptor = raw_descriptor
    rule_id = ""
    if descriptor == "malformed_proposal":
        code = "malformed_proposal"
    elif descriptor == "allow_rules:miss":
        code = "no_allow_rule_match"
    elif descriptor.startswith("deny_rules["):
        code = "deny_rule_match"
        rule_id = descriptor
    elif ":min_value" in descriptor or ":max_value" in descriptor:
        code = "out_of_bounds"
        rule_id = descriptor.split(":", 1)[0]
    elif ":max_abs_delta" in descriptor:
        code = "delta_exceeded"
        rule_id = descriptor.split(":", 1)[0]
    elif ":min_residual_support" in descriptor:
        code = "insufficient_evidence"
        rule_id = descriptor.split(":", 1)[0]
    elif ":max_axis_loss" in descriptor:
        code = "axis_loss_exceeded"
        rule_id = descriptor.split(":", 1)[0]
    else:
        # Unknown descriptors fall back to no_allow_rule_match so the
        # SDK shape stays canonical even if the Phase 1 evaluator
        # grows new descriptor strings.
        code = "no_allow_rule_match"
        rule_id = descriptor
    return AdvisoryRejectionReason(
        code=code,
        rule_id=rule_id,
        description=raw_reason,
    )


def project_phase1_advisory_decisions(
    phase1_decisions: Any,
    *,
    contract_name: str = "",
) -> AdvisoryEvaluation:
    """Project a Phase 1 advisory decision tuple into the SDK shape.

    Duck-typed: the adapter only reads the documented attributes
    (``proposal``, ``status``, ``accepted``, ``reasons``,
    ``violated_rules``, ``diagnostics``) and does not import
    ``aquaoptima.*`` from inside the SDK package code, preserving the
    no-runtime-dependency boundary.

    The input is never mutated. The result is an audit-only
    :class:`AdvisoryEvaluation` whose decisions are accepted /
    rejected only.
    """
    sdk_decisions: list[AdvisoryDecision] = []
    warnings: list[str] = []
    accepted_count = 0
    rejected_count = 0
    for raw_decision in phase1_decisions:
        raw_proposal = getattr(raw_decision, "proposal")
        sdk_proposal = AdvisoryProposal(
            proposal_id=str(getattr(raw_proposal, "proposal_id")),
            axis=str(getattr(raw_proposal, "axis")),
            target_id=int(getattr(raw_proposal, "target_id")),
            proposed_value=float(getattr(raw_proposal, "proposed_value")),
            current_value=(
                float(getattr(raw_proposal, "current_value"))
                if getattr(raw_proposal, "current_value", None) is not None
                else None
            ),
            observed_value=(
                float(getattr(raw_proposal, "observed_value"))
                if getattr(raw_proposal, "observed_value", None) is not None
                else None
            ),
            reason=str(getattr(raw_proposal, "reason", "")),
            source=str(getattr(raw_proposal, "source", "")),
        )
        accepted = bool(getattr(raw_decision, "accepted"))
        status = (
            ADVISORY_STATUS_ACCEPTED if accepted else ADVISORY_STATUS_REJECTED
        )
        raw_reasons = tuple(getattr(raw_decision, "reasons", ()))
        raw_descriptors = tuple(getattr(raw_decision, "violated_rules", ()))
        # Pair reasons with descriptors positionally; Phase 1 emits one
        # of each per violation.
        rejection_reasons: list[AdvisoryRejectionReason] = []
        violated_rule_ids: list[str] = []
        for idx, descriptor in enumerate(raw_descriptors):
            reason_text = (
                raw_reasons[idx] if idx < len(raw_reasons) else ""
            )
            rr = _coerce_phase1_rejection_reason(
                str(descriptor), str(reason_text)
            )
            rejection_reasons.append(rr)
            if rr.rule_id:
                violated_rule_ids.append(rr.rule_id)
        diagnostics = getattr(raw_decision, "diagnostics", None)
        decision_warnings: tuple[str, ...] = ()
        if diagnostics is not None:
            decision_warnings = tuple(
                str(w) for w in getattr(diagnostics, "warnings", ())
            )
            for err in getattr(diagnostics, "errors", ()):
                warnings.append(str(err))
        sdk_decision = AdvisoryDecision(
            proposal=sdk_proposal,
            status=status,
            accepted=accepted,
            rejection_reasons=tuple(rejection_reasons) if not accepted else (),
            violated_rule_ids=tuple(violated_rule_ids) if not accepted else (),
            warnings=decision_warnings,
        )
        sdk_decisions.append(sdk_decision)
        if accepted:
            accepted_count += 1
        else:
            rejected_count += 1
    return AdvisoryEvaluation(
        contract_name=contract_name,
        decisions=tuple(sdk_decisions),
        proposal_count=len(sdk_decisions),
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        warnings=tuple(warnings),
    )


__all__ = [
    "ADVISORY_DECISION_STATUSES",
    "ADVISORY_REJECTION_REASONS",
    "ADVISORY_RULE_MODES",
    "ADVISORY_SDK_AXES",
    "ADVISORY_STATUS_ACCEPTED",
    "ADVISORY_STATUS_REJECTED",
    "AdvisoryContract",
    "AdvisoryDecision",
    "AdvisoryEvaluation",
    "AdvisoryProposal",
    "AdvisoryRejectionReason",
    "AdvisoryRule",
    "project_phase1_advisory_decisions",
]
