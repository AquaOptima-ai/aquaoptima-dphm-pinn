"""Advisory contract projections (Sprint 43) — audit-only.

The Sprint 43 SDK advisory module owns *shape* and deterministic JSON
for:

* :class:`AdvisoryRule` — single allow- or deny-list entry.
* :class:`AdvisoryContract` — frozen allow-list / deny-list bundle.
* :class:`AdvisoryProposal` — hypothetical proposal payload, **audit
  only** — never a write or actuation payload.
* :class:`AdvisoryDecision` — deterministic per-proposal verdict
  (accepted / rejected only).
* :class:`AdvisoryRejectionReason` — machine-readable rejection
  vocabulary.
* :class:`AdvisoryEvaluation` — bundle of decisions plus aggregate
  counts.

The Phase 1 evaluator ``aquaoptima.dphm.advisory_contract.evaluate_advisory_proposals``
remains the authority for evaluating a proposal against a contract.
The SDK projection here only models the read-only audit shape, and
the projection adapter ``project_phase1_advisory_decisions`` converts
a Phase 1 decision tuple into the SDK shape without importing
``aquaoptima.*`` from inside the SDK package code.

Boundary (audit only): the SDK advisory surface never represents a
write, actuation, dispatch, or control output. It cannot be turned
into one — every field is a frozen audit value.
"""

from .contract import (
    ADVISORY_DECISION_STATUSES,
    ADVISORY_REJECTION_REASONS,
    ADVISORY_RULE_MODES,
    ADVISORY_SDK_AXES,
    ADVISORY_STATUS_ACCEPTED,
    ADVISORY_STATUS_REJECTED,
    AdvisoryContract,
    AdvisoryDecision,
    AdvisoryEvaluation,
    AdvisoryProposal,
    AdvisoryRejectionReason,
    AdvisoryRule,
    project_phase1_advisory_decisions,
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
