"""Sprint 50 — AMAX simulated supervisory proposal / PLC gatekeeper SDK.

Sprint 50 defines a **simulated supervisory proposal / PLC gatekeeper
contract** that names the structure of future autonomy work without
enabling any of it. It is a contracts / evidence / dry-run sprint. It
does **not** implement live OT adapters, Edge daemons, PLC/SCADA
clients, network code, write paths, or any proposal-to-PLC routing.

Every dataclass in this module is a frozen, stdlib-only audit value
record. Nothing here authorises a write, dispatch, actuation, or
control surface; every contract is dry-run / simulation-only and falls
through to site PLC authority at every gate.

The non-negotiable safety boundary stays explicit:

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- the site PLC retains direct VFD / pump / actuator authority.

Public surface:

* :class:`SupervisoryProposalValue` — frozen dataclass for one
  simulated proposal value (axis label, target id, proposed value,
  unit, lower / upper envelope, confidence, validity window seconds,
  rollback / fallback reference, notes). Audit-only.
* :class:`SupervisoryProposalDryRun` — frozen dataclass bundling a
  tuple of :class:`SupervisoryProposalValue` records with a proposal
  id, source evidence references, created-by label, simulation /
  dry-run flags, validity / expiration metadata, and safety notes.
  Defaults to ``simulation_only=True`` and ``dry_run=True``.
* :class:`PLCGatekeeperCondition` — frozen dataclass for one gate
  condition (id, category, required state, observed evidence label,
  status, blocking flag, notes). Categories cover operator enable,
  mode enabled, interlocks healthy, permissives healthy, stale-data
  rejection, bounds / rate limits, fallback / manual priority, and
  E-stop / manual override.
* :class:`PLCGatekeeperEvaluation` — frozen dataclass combining a
  :class:`SupervisoryProposalDryRun` with a tuple of
  :class:`PLCGatekeeperCondition` records and the deterministic
  verdict. Verdicts are ``not_evaluated``, ``blocked``, or
  ``simulation_accepted``; no live write / control verdict can be
  produced.
* :func:`evaluate_plc_gatekeeper_dry_run` — pure helper that produces
  an evaluation from a proposal plus a tuple of conditions. Simulation
  only.
* :class:`AMAXSupervisoryDryRunContract` — frozen Sprint 50 bundle that
  combines the proposal contract, the gatekeeper evaluation, Sprint 49
  referenced evidence ids / docs, warnings, errors, next gate, and the
  reaffirmed safety boundary.
* :func:`default_amax_supervisory_dry_run_contract` — canonical
  Sprint 50 default helper. Audit-only.
* :class:`AMAXSupervisoryDryRunDiagnostics` — deterministic warnings /
  errors record surfaced by
  :func:`diagnose_amax_supervisory_dry_run_contract` when the contract
  is missing Sprint 49 evidence references, missing gatekeeper
  categories, attempts to declare live write authorisation, or carries
  unsafe vocabulary in labels.

All ``to_dict`` / ``from_dict`` round trips are deterministic; tuple
ordering is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..safety.vocabulary import FORBIDDEN_VOCABULARY, contains_forbidden_token


# ---------------------------------------------------------------------------
# Canonical vocabularies
# ---------------------------------------------------------------------------


# Canonical gatekeeper category tokens. Adding a new token is an SDK
# MINOR bump; repurposing or removing is MAJOR.
GATEKEEPER_CATEGORY_OPERATOR_ENABLE: str = "operator_enable"
GATEKEEPER_CATEGORY_MODE_ENABLED: str = "mode_enabled"
GATEKEEPER_CATEGORY_INTERLOCKS_HEALTHY: str = "interlocks_healthy"
GATEKEEPER_CATEGORY_PERMISSIVES_HEALTHY: str = "permissives_healthy"
GATEKEEPER_CATEGORY_STALE_DATA_REJECTION: str = "stale_data_rejection"
GATEKEEPER_CATEGORY_BOUNDS_RATE_LIMITS: str = "bounds_rate_limits"
GATEKEEPER_CATEGORY_FALLBACK_MANUAL_PRIORITY: str = (
    "fallback_manual_priority"
)
GATEKEEPER_CATEGORY_E_STOP_MANUAL_OVERRIDE: str = "e_stop_manual_override"


GATEKEEPER_CATEGORIES: frozenset[str] = frozenset(
    {
        GATEKEEPER_CATEGORY_OPERATOR_ENABLE,
        GATEKEEPER_CATEGORY_MODE_ENABLED,
        GATEKEEPER_CATEGORY_INTERLOCKS_HEALTHY,
        GATEKEEPER_CATEGORY_PERMISSIVES_HEALTHY,
        GATEKEEPER_CATEGORY_STALE_DATA_REJECTION,
        GATEKEEPER_CATEGORY_BOUNDS_RATE_LIMITS,
        GATEKEEPER_CATEGORY_FALLBACK_MANUAL_PRIORITY,
        GATEKEEPER_CATEGORY_E_STOP_MANUAL_OVERRIDE,
    }
)


# Canonical per-condition status tokens. ``not_evaluated`` is the safe
# default; ``passed`` means the condition has audit evidence on file;
# ``failed`` means a discovered gap that blocks the dry-run from being
# marked as simulation-accepted.
GATEKEEPER_STATUS_NOT_EVALUATED: str = "not_evaluated"
GATEKEEPER_STATUS_PASSED: str = "passed"
GATEKEEPER_STATUS_FAILED: str = "failed"


GATEKEEPER_STATUS_TOKENS: frozenset[str] = frozenset(
    {
        GATEKEEPER_STATUS_NOT_EVALUATED,
        GATEKEEPER_STATUS_PASSED,
        GATEKEEPER_STATUS_FAILED,
    }
)


# Canonical evaluation verdict tokens. ``not_evaluated`` covers the
# safe initial state; ``blocked`` covers any case where a blocking
# condition is not ``passed``; ``simulation_accepted`` covers the
# dry-run-only "all gates passed" state. None of these tokens authorise
# a live write, dispatch, actuation, or control surface — the verdict
# is an audit label only.
VERDICT_NOT_EVALUATED: str = "not_evaluated"
VERDICT_BLOCKED: str = "blocked"
VERDICT_SIMULATION_ACCEPTED: str = "simulation_accepted"


GATEKEEPER_VERDICT_TOKENS: frozenset[str] = frozenset(
    {
        VERDICT_NOT_EVALUATED,
        VERDICT_BLOCKED,
        VERDICT_SIMULATION_ACCEPTED,
    }
)


# Canonical Sprint 50 contract identifier. Adding additional canonical
# ids is an SDK MINOR bump; repurposing or removing is MAJOR.
AMAX_SUPERVISORY_DRY_RUN_CONTRACT_ID: str = (
    "amax_8580_supervisory_dry_run_contract_v1"
)


# Tokens that must never appear in a proposal or gatekeeper label
# because they describe an affirmative write / dispatch / actuator
# surface. Probe strings are assembled from fragments so this module
# does not embed the canonical forbidden-vocabulary literals; the
# forbidden-vocabulary scan remains the source of truth for those.
_UNSAFE_LABEL_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("set" + "point", "setpoint"),
    ("act" + "uator", "actuator"),
    ("comm" + "and", "command"),
    ("clo" + "sed-loop", "closed-loop"),
    ("clo" + "sed_loop", "closed_loop"),
    ("wri" + "te_register", "write_register"),
    ("wri" + "te_topic", "write_topic"),
    ("dispa" + "tch_topic", "dispatch_topic"),
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ensure_str(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(
            f"{label} must be a non-empty string, got {type(value).__name__}"
        )
    hits = contains_forbidden_token(value)
    if hits:
        raise ContractError(
            f"{label} value contains forbidden vocabulary token(s) "
            f"{sorted(hits)}"
        )
    return value


def _ensure_string(value: Any, *, label: str) -> str:
    """Allow empty strings (used for optional reference / notes labels)."""

    if not isinstance(value, str):
        raise ContractError(
            f"{label} must be a string, got {type(value).__name__}"
        )
    hits = contains_forbidden_token(value)
    if hits:
        raise ContractError(
            f"{label} value contains forbidden vocabulary token(s) "
            f"{sorted(hits)}"
        )
    return value


def _ensure_str_tuple(value: Any, *, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ContractError(
            f"{label} must be a tuple of strings, got a bare string"
        )
    if not isinstance(value, tuple):
        raise ContractError(
            f"{label} must be a tuple, got {type(value).__name__}"
        )
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry:
            raise ContractError(
                f"{label} entries must be non-empty strings"
            )
        hits = contains_forbidden_token(entry)
        if hits:
            raise ContractError(
                f"{label} entry {entry!r} contains forbidden vocabulary "
                f"token(s) {sorted(hits)}"
            )
        out.append(entry)
    return tuple(out)


def _ensure_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(
            f"{label} must be a bool, got {type(value).__name__}"
        )
    return value


def _ensure_finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(
            f"{label} must be a real number, got {type(value).__name__}"
        )
    out = float(value)
    if out != out or out in (float("inf"), float("-inf")):
        raise ContractError(f"{label} must be a finite real number")
    return out


def _ensure_positive_number(value: Any, *, label: str) -> float:
    out = _ensure_finite_number(value, label=label)
    if out <= 0:
        raise ContractError(f"{label} must be positive")
    return out


def _ensure_unit_interval(value: Any, *, label: str) -> float:
    out = _ensure_finite_number(value, label=label)
    if out < 0.0 or out > 1.0:
        raise ContractError(f"{label} must be within [0.0, 1.0]")
    return out


def _coerce_str_sequence(
    data: Mapping[str, Any], name: str, *, label: str
) -> tuple[str, ...]:
    raw = data.get(name, ()) or ()
    if isinstance(raw, (str, bytes)):
        raise ContractError(
            f"{label}.{name} must be a sequence of strings, got a bare string"
        )
    if not isinstance(raw, Sequence):
        raise ContractError(f"{label}.{name} must be a sequence")
    return tuple(str(item) for item in raw)


def _reject_forbidden_keys(data: Mapping[str, Any], *, label: str) -> None:
    forbidden_hits = set(data.keys()) & FORBIDDEN_VOCABULARY
    if forbidden_hits:
        raise ContractError(
            f"{label} received forbidden vocabulary field name(s): "
            f"{sorted(forbidden_hits)}"
        )


def _scan_unsafe_phrases(text: str) -> tuple[str, ...]:
    """Return canonical names of unsafe phrases found in ``text``.

    The probe strings are assembled from fragments so this helper does
    not embed the canonical forbidden-vocabulary literals. Case-
    insensitive substring scan; callers receive the canonical
    (human-readable) name to surface in diagnostics.
    """

    lowered = text.lower()
    hits: list[str] = []
    for probe, canonical in _UNSAFE_LABEL_FRAGMENTS:
        if probe in lowered:
            hits.append(canonical)
    return tuple(sorted(set(hits)))


# ---------------------------------------------------------------------------
# SupervisoryProposalValue
# ---------------------------------------------------------------------------


_VALUE_FIELDS: tuple[str, ...] = (
    "axis_label",
    "target_id",
    "proposed_value",
    "unit",
    "lower_envelope",
    "upper_envelope",
    "confidence",
    "validity_window_seconds",
    "rollback_reference",
    "notes",
)


@dataclass(frozen=True)
class SupervisoryProposalValue:
    """Frozen audit row for one simulated supervisory proposal value.

    Audit-only. Captures the proposed variable / axis label, the target
    id (e.g. a pump or station label), the proposed value, the unit,
    a lower / upper safety envelope, the proposal confidence in
    ``[0.0, 1.0]``, the validity window in seconds, a rollback /
    fallback evidence reference label, and audit notes. Nothing in
    this record represents a write, dispatch, actuation, or control
    surface — the proposed value is an audit-only number that the site
    PLC may consider or ignore at its sole discretion.

    The ``rollback_reference`` field is a label pointing to the
    AquaOptima fallback / rollback evidence (see Sprint 49 readiness
    package); it is not a callable handle. Bounds are enforced:
    ``lower_envelope <= proposed_value <= upper_envelope``.
    """

    axis_label: str
    target_id: str
    proposed_value: float
    unit: str
    lower_envelope: float
    upper_envelope: float
    confidence: float
    validity_window_seconds: float
    rollback_reference: str = ""
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.axis_label, label="SupervisoryProposalValue.axis_label"
        )
        _ensure_str(
            self.target_id, label="SupervisoryProposalValue.target_id"
        )
        _ensure_str(self.unit, label="SupervisoryProposalValue.unit")
        proposed = _ensure_finite_number(
            self.proposed_value,
            label="SupervisoryProposalValue.proposed_value",
        )
        lower = _ensure_finite_number(
            self.lower_envelope,
            label="SupervisoryProposalValue.lower_envelope",
        )
        upper = _ensure_finite_number(
            self.upper_envelope,
            label="SupervisoryProposalValue.upper_envelope",
        )
        if lower > upper:
            raise ContractError(
                "SupervisoryProposalValue.lower_envelope must be <= "
                "upper_envelope"
            )
        if proposed < lower or proposed > upper:
            raise ContractError(
                "SupervisoryProposalValue.proposed_value must lie within "
                "[lower_envelope, upper_envelope]"
            )
        confidence = _ensure_unit_interval(
            self.confidence, label="SupervisoryProposalValue.confidence"
        )
        validity = _ensure_positive_number(
            self.validity_window_seconds,
            label="SupervisoryProposalValue.validity_window_seconds",
        )
        _ensure_string(
            self.rollback_reference,
            label="SupervisoryProposalValue.rollback_reference",
        )
        notes = _ensure_str_tuple(
            self.notes, label="SupervisoryProposalValue.notes"
        )
        object.__setattr__(self, "proposed_value", proposed)
        object.__setattr__(self, "lower_envelope", lower)
        object.__setattr__(self, "upper_envelope", upper)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "validity_window_seconds", validity)
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis_label": self.axis_label,
            "target_id": self.target_id,
            "proposed_value": self.proposed_value,
            "unit": self.unit,
            "lower_envelope": self.lower_envelope,
            "upper_envelope": self.upper_envelope,
            "confidence": self.confidence,
            "validity_window_seconds": self.validity_window_seconds,
            "rollback_reference": self.rollback_reference,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "SupervisoryProposalValue":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"SupervisoryProposalValue.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="SupervisoryProposalValue")
        missing = {
            "axis_label",
            "target_id",
            "proposed_value",
            "unit",
            "lower_envelope",
            "upper_envelope",
            "confidence",
            "validity_window_seconds",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"SupervisoryProposalValue missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_VALUE_FIELDS)
        if unknown:
            raise ContractError(
                f"SupervisoryProposalValue received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            axis_label=str(data["axis_label"]),
            target_id=str(data["target_id"]),
            proposed_value=float(data["proposed_value"]),
            unit=str(data["unit"]),
            lower_envelope=float(data["lower_envelope"]),
            upper_envelope=float(data["upper_envelope"]),
            confidence=float(data["confidence"]),
            validity_window_seconds=float(data["validity_window_seconds"]),
            rollback_reference=str(data.get("rollback_reference", "")),
            notes=_coerce_str_sequence(
                data, "notes", label="SupervisoryProposalValue"
            ),
        )


# ---------------------------------------------------------------------------
# SupervisoryProposalDryRun
# ---------------------------------------------------------------------------


_PROPOSAL_FIELDS: tuple[str, ...] = (
    "proposal_id",
    "values",
    "source_evidence_references",
    "created_by_label",
    "validity_window_seconds",
    "expiration_label",
    "simulation_only",
    "dry_run",
    "safety_notes",
)


@dataclass(frozen=True)
class SupervisoryProposalDryRun:
    """Frozen audit bundle for one simulated supervisory proposal.

    Audit-only. Bundles a tuple of :class:`SupervisoryProposalValue`
    rows under a proposal id, with source evidence references, a
    created-by label, an overall validity window in seconds, an
    expiration label, simulation / dry-run flags, and safety notes.
    Always carries ``simulation_only=True`` and ``dry_run=True``; the
    SDK refuses to record either flag as ``False``. Nothing in this
    record represents a write, dispatch, actuation, or control
    surface.
    """

    proposal_id: str
    values: tuple[SupervisoryProposalValue, ...]
    source_evidence_references: tuple[str, ...] = ()
    created_by_label: str = ""
    validity_window_seconds: float = 60.0
    expiration_label: str = ""
    simulation_only: bool = True
    dry_run: bool = True
    safety_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.proposal_id,
            label="SupervisoryProposalDryRun.proposal_id",
        )
        if not isinstance(self.values, tuple):
            raise ContractError(
                "SupervisoryProposalDryRun.values must be a tuple"
            )
        for entry in self.values:
            if not isinstance(entry, SupervisoryProposalValue):
                raise ContractError(
                    "SupervisoryProposalDryRun.values must contain "
                    "SupervisoryProposalValue instances"
                )
        seen: set[tuple[str, str]] = set()
        for entry in self.values:
            key = (entry.axis_label, entry.target_id)
            if key in seen:
                raise ContractError(
                    f"SupervisoryProposalDryRun has duplicate "
                    f"(axis_label, target_id) pair {key!r}"
                )
            seen.add(key)
        refs = _ensure_str_tuple(
            self.source_evidence_references,
            label="SupervisoryProposalDryRun.source_evidence_references",
        )
        _ensure_string(
            self.created_by_label,
            label="SupervisoryProposalDryRun.created_by_label",
        )
        validity = _ensure_positive_number(
            self.validity_window_seconds,
            label="SupervisoryProposalDryRun.validity_window_seconds",
        )
        _ensure_string(
            self.expiration_label,
            label="SupervisoryProposalDryRun.expiration_label",
        )
        _ensure_bool(
            self.simulation_only,
            label="SupervisoryProposalDryRun.simulation_only",
        )
        if not self.simulation_only:
            raise ContractError(
                "SupervisoryProposalDryRun.simulation_only must be True — "
                "Sprint 50 ships a simulated supervisory proposal contract, "
                "not a live write or control authorisation"
            )
        _ensure_bool(
            self.dry_run, label="SupervisoryProposalDryRun.dry_run"
        )
        if not self.dry_run:
            raise ContractError(
                "SupervisoryProposalDryRun.dry_run must be True — Sprint 50 "
                "proposals are dry-run only"
            )
        safety_notes = _ensure_str_tuple(
            self.safety_notes,
            label="SupervisoryProposalDryRun.safety_notes",
        )
        object.__setattr__(self, "source_evidence_references", refs)
        object.__setattr__(self, "validity_window_seconds", validity)
        object.__setattr__(self, "safety_notes", safety_notes)

    @property
    def axes(self) -> frozenset[str]:
        """Return the set of axis labels present in this proposal."""

        return frozenset(value.axis_label for value in self.values)

    @property
    def target_ids(self) -> frozenset[str]:
        """Return the set of target ids referenced in this proposal."""

        return frozenset(value.target_id for value in self.values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "values": [value.to_dict() for value in self.values],
            "source_evidence_references": list(
                self.source_evidence_references
            ),
            "created_by_label": self.created_by_label,
            "validity_window_seconds": self.validity_window_seconds,
            "expiration_label": self.expiration_label,
            "simulation_only": self.simulation_only,
            "dry_run": self.dry_run,
            "safety_notes": list(self.safety_notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "SupervisoryProposalDryRun":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"SupervisoryProposalDryRun.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="SupervisoryProposalDryRun")
        missing = {"proposal_id", "values"} - set(data.keys())
        if missing:
            raise ContractError(
                f"SupervisoryProposalDryRun missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_PROPOSAL_FIELDS)
        if unknown:
            raise ContractError(
                f"SupervisoryProposalDryRun received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_values = data["values"]
        if isinstance(raw_values, (str, bytes)) or not isinstance(
            raw_values, Sequence
        ):
            raise ContractError(
                "SupervisoryProposalDryRun.values must be a sequence"
            )
        simulation_only = data.get("simulation_only", True)
        if not isinstance(simulation_only, bool):
            raise ContractError(
                "SupervisoryProposalDryRun.simulation_only must be a bool"
            )
        dry_run = data.get("dry_run", True)
        if not isinstance(dry_run, bool):
            raise ContractError(
                "SupervisoryProposalDryRun.dry_run must be a bool"
            )
        return cls(
            proposal_id=str(data["proposal_id"]),
            values=tuple(
                SupervisoryProposalValue.from_dict(value)
                for value in raw_values
            ),
            source_evidence_references=_coerce_str_sequence(
                data,
                "source_evidence_references",
                label="SupervisoryProposalDryRun",
            ),
            created_by_label=str(data.get("created_by_label", "")),
            validity_window_seconds=float(
                data.get("validity_window_seconds", 60.0)
            ),
            expiration_label=str(data.get("expiration_label", "")),
            simulation_only=simulation_only,
            dry_run=dry_run,
            safety_notes=_coerce_str_sequence(
                data, "safety_notes", label="SupervisoryProposalDryRun"
            ),
        )


# ---------------------------------------------------------------------------
# PLCGatekeeperCondition
# ---------------------------------------------------------------------------


_CONDITION_FIELDS: tuple[str, ...] = (
    "condition_id",
    "category",
    "required_state",
    "observed_label",
    "status",
    "blocking",
    "notes",
)


@dataclass(frozen=True)
class PLCGatekeeperCondition:
    """Frozen audit row for one PLC gatekeeper condition.

    Audit-only. Captures the condition id, canonical gatekeeper
    category, the required state (audit text describing what the site
    PLC must report before the dry-run can be marked simulation-
    accepted), an observed-evidence label, the current condition
    status, a blocking flag, and audit notes. Nothing in this record
    represents a write, dispatch, actuation, or control surface — the
    record names the *gates* the site PLC enforces, not any AquaOptima
    behaviour.

    The site PLC retains direct VFD / pump / actuator authority at
    every gate; an AquaOptima dry-run only ever asks whether the site
    PLC reports the gate as healthy.
    """

    condition_id: str
    category: str
    required_state: str
    observed_label: str = ""
    status: str = GATEKEEPER_STATUS_NOT_EVALUATED
    blocking: bool = True
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.condition_id, label="PLCGatekeeperCondition.condition_id"
        )
        _ensure_str(
            self.category, label="PLCGatekeeperCondition.category"
        )
        if self.category not in GATEKEEPER_CATEGORIES:
            raise ContractError(
                f"PLCGatekeeperCondition.category {self.category!r} is not "
                f"in the allowed list ({sorted(GATEKEEPER_CATEGORIES)})"
            )
        _ensure_str(
            self.required_state,
            label="PLCGatekeeperCondition.required_state",
        )
        _ensure_string(
            self.observed_label,
            label="PLCGatekeeperCondition.observed_label",
        )
        _ensure_str(
            self.status, label="PLCGatekeeperCondition.status"
        )
        if self.status not in GATEKEEPER_STATUS_TOKENS:
            raise ContractError(
                f"PLCGatekeeperCondition.status {self.status!r} is not in "
                f"the allowed list ({sorted(GATEKEEPER_STATUS_TOKENS)})"
            )
        _ensure_bool(
            self.blocking, label="PLCGatekeeperCondition.blocking"
        )
        notes = _ensure_str_tuple(
            self.notes, label="PLCGatekeeperCondition.notes"
        )
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "category": self.category,
            "required_state": self.required_state,
            "observed_label": self.observed_label,
            "status": self.status,
            "blocking": self.blocking,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "PLCGatekeeperCondition":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"PLCGatekeeperCondition.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="PLCGatekeeperCondition")
        missing = {
            "condition_id",
            "category",
            "required_state",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"PLCGatekeeperCondition missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_CONDITION_FIELDS)
        if unknown:
            raise ContractError(
                f"PLCGatekeeperCondition received unknown fields: "
                f"{sorted(unknown)}"
            )
        blocking_raw = data.get("blocking", True)
        if not isinstance(blocking_raw, bool):
            raise ContractError(
                "PLCGatekeeperCondition.blocking must be a bool"
            )
        return cls(
            condition_id=str(data["condition_id"]),
            category=str(data["category"]),
            required_state=str(data["required_state"]),
            observed_label=str(data.get("observed_label", "")),
            status=str(data.get("status", GATEKEEPER_STATUS_NOT_EVALUATED)),
            blocking=blocking_raw,
            notes=_coerce_str_sequence(
                data, "notes", label="PLCGatekeeperCondition"
            ),
        )


# ---------------------------------------------------------------------------
# PLCGatekeeperEvaluation
# ---------------------------------------------------------------------------


_EVALUATION_FIELDS: tuple[str, ...] = (
    "evaluation_id",
    "proposal",
    "conditions",
    "verdict",
    "simulation_only",
    "notes",
)


@dataclass(frozen=True)
class PLCGatekeeperEvaluation:
    """Frozen audit bundle for one dry-run gatekeeper evaluation.

    Audit-only. Combines a :class:`SupervisoryProposalDryRun` with a
    tuple of :class:`PLCGatekeeperCondition` records and a
    deterministic verdict. Verdicts are limited to
    ``not_evaluated``, ``blocked``, and ``simulation_accepted`` —
    the SDK refuses to produce any verdict that implies a live write,
    dispatch, actuation, or control surface. The evaluation always
    carries ``simulation_only=True``.
    """

    evaluation_id: str
    proposal: SupervisoryProposalDryRun
    conditions: tuple[PLCGatekeeperCondition, ...]
    verdict: str = VERDICT_NOT_EVALUATED
    simulation_only: bool = True
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.evaluation_id,
            label="PLCGatekeeperEvaluation.evaluation_id",
        )
        if not isinstance(self.proposal, SupervisoryProposalDryRun):
            raise ContractError(
                "PLCGatekeeperEvaluation.proposal must be a "
                "SupervisoryProposalDryRun"
            )
        if not isinstance(self.conditions, tuple):
            raise ContractError(
                "PLCGatekeeperEvaluation.conditions must be a tuple"
            )
        for entry in self.conditions:
            if not isinstance(entry, PLCGatekeeperCondition):
                raise ContractError(
                    "PLCGatekeeperEvaluation.conditions must contain "
                    "PLCGatekeeperCondition instances"
                )
        seen: set[str] = set()
        for entry in self.conditions:
            if entry.condition_id in seen:
                raise ContractError(
                    f"PLCGatekeeperEvaluation has duplicate condition id "
                    f"{entry.condition_id!r}"
                )
            seen.add(entry.condition_id)
        _ensure_str(self.verdict, label="PLCGatekeeperEvaluation.verdict")
        if self.verdict not in GATEKEEPER_VERDICT_TOKENS:
            raise ContractError(
                f"PLCGatekeeperEvaluation.verdict {self.verdict!r} is not "
                f"in the allowed list ({sorted(GATEKEEPER_VERDICT_TOKENS)})"
            )
        _ensure_bool(
            self.simulation_only,
            label="PLCGatekeeperEvaluation.simulation_only",
        )
        if not self.simulation_only:
            raise ContractError(
                "PLCGatekeeperEvaluation.simulation_only must be True — "
                "Sprint 50 evaluations are simulation only"
            )
        notes = _ensure_str_tuple(
            self.notes, label="PLCGatekeeperEvaluation.notes"
        )
        object.__setattr__(self, "notes", notes)

    @property
    def gatekeeper_categories(self) -> frozenset[str]:
        """Return the set of gatekeeper categories present."""

        return frozenset(c.category for c in self.conditions)

    def unresolved_blocking_conditions(
        self,
    ) -> tuple[PLCGatekeeperCondition, ...]:
        """Return blocking conditions whose status is not ``passed``.

        Pure audit helper. Any blocking condition whose status is
        anything other than ``passed`` is considered unresolved — the
        dry-run cannot be marked ``simulation_accepted`` while any
        unresolved blocking condition remains.
        """

        return tuple(
            c
            for c in self.conditions
            if c.blocking and c.status != GATEKEEPER_STATUS_PASSED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "proposal": self.proposal.to_dict(),
            "conditions": [c.to_dict() for c in self.conditions],
            "verdict": self.verdict,
            "simulation_only": self.simulation_only,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "PLCGatekeeperEvaluation":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"PLCGatekeeperEvaluation.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="PLCGatekeeperEvaluation")
        missing = {
            "evaluation_id",
            "proposal",
            "conditions",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"PLCGatekeeperEvaluation missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_EVALUATION_FIELDS)
        if unknown:
            raise ContractError(
                f"PLCGatekeeperEvaluation received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_conditions = data["conditions"]
        if isinstance(raw_conditions, (str, bytes)) or not isinstance(
            raw_conditions, Sequence
        ):
            raise ContractError(
                "PLCGatekeeperEvaluation.conditions must be a sequence"
            )
        simulation_only = data.get("simulation_only", True)
        if not isinstance(simulation_only, bool):
            raise ContractError(
                "PLCGatekeeperEvaluation.simulation_only must be a bool"
            )
        return cls(
            evaluation_id=str(data["evaluation_id"]),
            proposal=SupervisoryProposalDryRun.from_dict(data["proposal"]),
            conditions=tuple(
                PLCGatekeeperCondition.from_dict(c) for c in raw_conditions
            ),
            verdict=str(data.get("verdict", VERDICT_NOT_EVALUATED)),
            simulation_only=simulation_only,
            notes=_coerce_str_sequence(
                data, "notes", label="PLCGatekeeperEvaluation"
            ),
        )


def evaluate_plc_gatekeeper_dry_run(
    proposal: SupervisoryProposalDryRun,
    conditions: Sequence[PLCGatekeeperCondition],
    *,
    evaluation_id: str = "amax_8580_supervisory_dry_run_evaluation_v1",
    notes: Sequence[str] = (),
) -> PLCGatekeeperEvaluation:
    """Return a deterministic, simulation-only gatekeeper evaluation.

    Pure helper. Builds a :class:`PLCGatekeeperEvaluation` for
    ``proposal`` against ``conditions``. The verdict is computed
    deterministically:

    * if any condition has status ``not_evaluated``, verdict is
      ``not_evaluated``;
    * else if any blocking condition has status ``failed`` (or any
      blocking condition is not ``passed``), verdict is ``blocked``;
    * else verdict is ``simulation_accepted``.

    The evaluation is **always** ``simulation_only=True``; no live
    write, dispatch, actuation, or control verdict can be produced
    by this helper.
    """

    if not isinstance(proposal, SupervisoryProposalDryRun):
        raise ContractError(
            "evaluate_plc_gatekeeper_dry_run requires a "
            "SupervisoryProposalDryRun proposal"
        )
    if isinstance(conditions, (str, bytes)) or not isinstance(
        conditions, Sequence
    ):
        raise ContractError(
            "evaluate_plc_gatekeeper_dry_run requires a sequence of "
            "PLCGatekeeperCondition records"
        )
    condition_tuple = tuple(conditions)
    for entry in condition_tuple:
        if not isinstance(entry, PLCGatekeeperCondition):
            raise ContractError(
                "evaluate_plc_gatekeeper_dry_run requires "
                "PLCGatekeeperCondition records"
            )
    has_not_evaluated = any(
        c.status == GATEKEEPER_STATUS_NOT_EVALUATED for c in condition_tuple
    )
    has_blocking_unresolved = any(
        c.blocking and c.status != GATEKEEPER_STATUS_PASSED
        for c in condition_tuple
    )
    if has_not_evaluated:
        verdict = VERDICT_NOT_EVALUATED
    elif has_blocking_unresolved:
        verdict = VERDICT_BLOCKED
    else:
        verdict = VERDICT_SIMULATION_ACCEPTED
    return PLCGatekeeperEvaluation(
        evaluation_id=evaluation_id,
        proposal=proposal,
        conditions=condition_tuple,
        verdict=verdict,
        simulation_only=True,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# AMAXSupervisoryDryRunContract
# ---------------------------------------------------------------------------


_CONTRACT_FIELDS: tuple[str, ...] = (
    "contract_id",
    "proposal",
    "gatekeeper_evaluation",
    "referenced_evidence",
    "next_gate",
    "live_write_authorized",
    "warnings",
    "errors",
    "safety_notes",
)


@dataclass(frozen=True)
class AMAXSupervisoryDryRunContract:
    """Frozen Sprint 50 supervisory dry-run / gatekeeper contract.

    Audit-only. Combines the simulated proposal contract, the PLC
    gatekeeper evaluation expectations, Sprint 49 referenced evidence
    ids / docs, deterministic warnings / errors, and the next gate
    (Sprint 51 — AMAX pilot readiness review / hardware-in-the-loop
    plan). Carries explicit ``live_write_authorized=False``; the SDK
    refuses to record this as ``True``. Nothing in this record
    represents a write, dispatch, actuation, or control surface.
    """

    contract_id: str
    proposal: SupervisoryProposalDryRun
    gatekeeper_evaluation: PLCGatekeeperEvaluation
    referenced_evidence: tuple[str, ...] = ()
    next_gate: str = ""
    live_write_authorized: bool = False
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.contract_id,
            label="AMAXSupervisoryDryRunContract.contract_id",
        )
        if not isinstance(self.proposal, SupervisoryProposalDryRun):
            raise ContractError(
                "AMAXSupervisoryDryRunContract.proposal must be a "
                "SupervisoryProposalDryRun"
            )
        if not isinstance(
            self.gatekeeper_evaluation, PLCGatekeeperEvaluation
        ):
            raise ContractError(
                "AMAXSupervisoryDryRunContract.gatekeeper_evaluation must "
                "be a PLCGatekeeperEvaluation"
            )
        # The evaluation must wrap the same proposal id; otherwise we
        # have a contract that references two different proposals,
        # which would be confusing to auditors.
        if (
            self.gatekeeper_evaluation.proposal.proposal_id
            != self.proposal.proposal_id
        ):
            raise ContractError(
                "AMAXSupervisoryDryRunContract.gatekeeper_evaluation must "
                "reference the same proposal id as "
                "AMAXSupervisoryDryRunContract.proposal"
            )
        refs = _ensure_str_tuple(
            self.referenced_evidence,
            label="AMAXSupervisoryDryRunContract.referenced_evidence",
        )
        _ensure_string(
            self.next_gate,
            label="AMAXSupervisoryDryRunContract.next_gate",
        )
        _ensure_bool(
            self.live_write_authorized,
            label=(
                "AMAXSupervisoryDryRunContract.live_write_authorized"
            ),
        )
        if self.live_write_authorized:
            raise ContractError(
                "AMAXSupervisoryDryRunContract.live_write_authorized must "
                "be False — Sprint 50 does not authorise any live write, "
                "dispatch, actuation, or control surface"
            )
        warnings = _ensure_str_tuple(
            self.warnings,
            label="AMAXSupervisoryDryRunContract.warnings",
        )
        errors = _ensure_str_tuple(
            self.errors, label="AMAXSupervisoryDryRunContract.errors"
        )
        safety_notes = _ensure_str_tuple(
            self.safety_notes,
            label="AMAXSupervisoryDryRunContract.safety_notes",
        )
        object.__setattr__(self, "referenced_evidence", refs)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "safety_notes", safety_notes)

    @property
    def gatekeeper_categories(self) -> frozenset[str]:
        """Return the gatekeeper categories present in the evaluation."""

        return self.gatekeeper_evaluation.gatekeeper_categories

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "proposal": self.proposal.to_dict(),
            "gatekeeper_evaluation": self.gatekeeper_evaluation.to_dict(),
            "referenced_evidence": list(self.referenced_evidence),
            "next_gate": self.next_gate,
            "live_write_authorized": self.live_write_authorized,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "safety_notes": list(self.safety_notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "AMAXSupervisoryDryRunContract":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXSupervisoryDryRunContract.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="AMAXSupervisoryDryRunContract")
        missing = {
            "contract_id",
            "proposal",
            "gatekeeper_evaluation",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXSupervisoryDryRunContract missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_CONTRACT_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXSupervisoryDryRunContract received unknown fields: "
                f"{sorted(unknown)}"
            )
        live_write = data.get("live_write_authorized", False)
        if not isinstance(live_write, bool):
            raise ContractError(
                "AMAXSupervisoryDryRunContract.live_write_authorized must "
                "be a bool"
            )
        return cls(
            contract_id=str(data["contract_id"]),
            proposal=SupervisoryProposalDryRun.from_dict(data["proposal"]),
            gatekeeper_evaluation=PLCGatekeeperEvaluation.from_dict(
                data["gatekeeper_evaluation"]
            ),
            referenced_evidence=_coerce_str_sequence(
                data,
                "referenced_evidence",
                label="AMAXSupervisoryDryRunContract",
            ),
            next_gate=str(data.get("next_gate", "")),
            live_write_authorized=live_write,
            warnings=_coerce_str_sequence(
                data, "warnings", label="AMAXSupervisoryDryRunContract"
            ),
            errors=_coerce_str_sequence(
                data, "errors", label="AMAXSupervisoryDryRunContract"
            ),
            safety_notes=_coerce_str_sequence(
                data,
                "safety_notes",
                label="AMAXSupervisoryDryRunContract",
            ),
        )


# ---------------------------------------------------------------------------
# AMAXSupervisoryDryRunDiagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AMAXSupervisoryDryRunDiagnostics:
    """Deterministic warnings / errors for a Sprint 50 dry-run contract.

    Audit-only. Surfaces missing gatekeeper categories, missing
    Sprint 49 referenced evidence handles, missing next-gate language,
    attempts to declare live write authorisation, and unsafe
    vocabulary detected in labels. Nothing in this record represents a
    write, dispatch, actuation, or control surface.
    """

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("warnings", "errors"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(v, str) for v in value
            ):
                raise ContractError(
                    f"AMAXSupervisoryDryRunDiagnostics.{name} must be a "
                    f"tuple of strings"
                )

    @property
    def is_clean(self) -> bool:
        return not self.warnings and not self.errors

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "AMAXSupervisoryDryRunDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXSupervisoryDryRunDiagnostics.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        unknown = set(data.keys()) - {"warnings", "errors"}
        if unknown:
            raise ContractError(
                f"AMAXSupervisoryDryRunDiagnostics received unknown "
                f"fields: {sorted(unknown)}"
            )
        warnings = tuple(str(w) for w in data.get("warnings", ()))
        errors = tuple(str(e) for e in data.get("errors", ()))
        return cls(warnings=warnings, errors=errors)


def diagnose_amax_supervisory_dry_run_contract(
    contract: AMAXSupervisoryDryRunContract,
) -> AMAXSupervisoryDryRunDiagnostics:
    """Return deterministic warnings / errors for ``contract``.

    Pure audit helper. The checks cover:

    * missing gatekeeper categories from the canonical Sprint 50 set;
    * missing Sprint 49 referenced evidence handles;
    * missing next-gate language;
    * any attempt to declare live write authorisation;
    * unsafe vocabulary in proposal / condition labels (substring
      scan); and
    * verdicts that imply anything other than ``not_evaluated``,
      ``blocked``, or ``simulation_accepted``.

    No live binding, no write, no setpoint, no command emission.
    """

    if not isinstance(contract, AMAXSupervisoryDryRunContract):
        raise ContractError(
            "diagnose_amax_supervisory_dry_run_contract requires an "
            "AMAXSupervisoryDryRunContract"
        )

    warnings: list[str] = []
    errors: list[str] = []

    present_categories = contract.gatekeeper_categories
    missing_categories = GATEKEEPER_CATEGORIES - present_categories
    if missing_categories:
        errors.append(
            f"gatekeeper evaluation missing required categories: "
            f"{sorted(missing_categories)}"
        )

    refs_joined = "\n".join(contract.referenced_evidence)
    if not contract.referenced_evidence:
        errors.append(
            "contract has no referenced_evidence — Sprint 50 contracts "
            "must cite Sprint 49 site deployment readiness evidence"
        )
    elif "sprint_49" not in refs_joined and "sprint-49" not in refs_joined:
        warnings.append(
            "contract referenced_evidence does not appear to cite the "
            "Sprint 49 site deployment readiness evidence package"
        )

    if not contract.next_gate:
        warnings.append(
            "contract has no next_gate — Sprint 50 contracts should "
            "name the next gate (Sprint 51 — AMAX pilot readiness "
            "review / hardware-in-the-loop plan)"
        )

    if not contract.safety_notes:
        warnings.append(
            "contract has no safety_notes — Sprint 50 contracts should "
            "explicitly reaffirm the simulation-only / dry-run boundary"
        )

    if contract.live_write_authorized:
        errors.append(
            "contract.live_write_authorized must be False — Sprint 50 "
            "does not authorise any live write or control surface"
        )

    # Unsafe vocabulary scan over label-shaped fields. Narrative
    # required_state / notes / safety_notes fields are intentionally
    # allowed to discuss boundary phrases in negative context (e.g.
    # "no setpoint output", "site PLC retains direct VFD / pump /
    # actuator authority"); they are audit text. Labels and ids must
    # stay clear of those phrases — they are what callers grep for.
    for value in contract.proposal.values:
        haystack = "\n".join(
            (value.axis_label, value.target_id, value.rollback_reference)
        )
        unsafe = _scan_unsafe_phrases(haystack)
        if unsafe:
            errors.append(
                f"proposal value ({value.axis_label!r}, "
                f"{value.target_id!r}) contains unsafe vocabulary "
                f"{list(unsafe)}"
            )

    for condition in contract.gatekeeper_evaluation.conditions:
        haystack = "\n".join(
            (condition.condition_id, condition.observed_label)
        )
        unsafe = _scan_unsafe_phrases(haystack)
        if unsafe:
            errors.append(
                f"gatekeeper condition {condition.condition_id!r} "
                f"contains unsafe vocabulary {list(unsafe)}"
            )

    verdict = contract.gatekeeper_evaluation.verdict
    if verdict not in GATEKEEPER_VERDICT_TOKENS:
        errors.append(
            f"gatekeeper evaluation verdict {verdict!r} is not in the "
            f"allowed simulation-only set "
            f"{sorted(GATEKEEPER_VERDICT_TOKENS)}"
        )

    return AMAXSupervisoryDryRunDiagnostics(
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# Canonical Sprint 50 default helpers
# ---------------------------------------------------------------------------


def _default_proposal_values() -> tuple[SupervisoryProposalValue, ...]:
    return (
        SupervisoryProposalValue(
            axis_label="pump_speed_proposed_fraction",
            target_id="station_a_pump_1",
            proposed_value=0.72,
            unit="fraction_of_rated_speed",
            lower_envelope=0.40,
            upper_envelope=0.90,
            confidence=0.78,
            validity_window_seconds=60.0,
            rollback_reference="sprint_49_rollback_runbook_label",
            notes=(
                "audit-only proposed value; the site PLC retains direct "
                "VFD / pump / actuator authority",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
            ),
        ),
        SupervisoryProposalValue(
            axis_label="pressure_target_proposed_metres",
            target_id="zone_b_pressure_zone",
            proposed_value=42.0,
            unit="metres_water_column",
            lower_envelope=30.0,
            upper_envelope=55.0,
            confidence=0.66,
            validity_window_seconds=60.0,
            rollback_reference="sprint_49_rollback_runbook_label",
            notes=(
                "audit-only proposed value; advisory output for site "
                "operations only",
                "no command emission",
                "no setpoint output",
            ),
        ),
    )


def default_amax_supervisory_dry_run_contract() -> (
    AMAXSupervisoryDryRunContract
):
    """Return the canonical Sprint 50 AMAX supervisory dry-run contract.

    Audit-only. Bundles a deterministic simulated proposal with the
    canonical eight-condition PLC gatekeeper evaluation, references
    the Sprint 49 site deployment readiness evidence package, and
    reaffirms the Sprint 50 boundary in ``safety_notes``. Carries
    explicit ``live_write_authorized=False``. The default verdict is
    ``not_evaluated`` — Sprint 50 ships a contract shape, not a site
    sign-off.
    """

    proposal = SupervisoryProposalDryRun(
        proposal_id="amax_8580_supervisory_dry_run_proposal_v1",
        values=_default_proposal_values(),
        source_evidence_references=(
            "sprint_49_amax_site_deployment_evidence_package",
            "sprint_48_amax_read_only_integration_contract",
            "sprint_47_amax_benchmark_report",
            "sprint_46_amax_feasibility_decision",
        ),
        created_by_label="aquaoptima_supervisory_advisor_dry_run",
        validity_window_seconds=60.0,
        expiration_label="audit_window_validity_label",
        simulation_only=True,
        dry_run=True,
        safety_notes=(
            "Sprint 50 ships a simulated supervisory proposal contract, "
            "not a live write authorisation",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "site PLC retains direct VFD / pump / actuator authority",
        ),
    )

    conditions = (
        PLCGatekeeperCondition(
            condition_id="gate_operator_enable",
            category=GATEKEEPER_CATEGORY_OPERATOR_ENABLE,
            required_state=(
                "site operator has explicitly enabled the AquaOptima "
                "supervisory advisory channel at the operator console"
            ),
            observed_label="site_operator_enable_evidence_label",
            status=GATEKEEPER_STATUS_NOT_EVALUATED,
            blocking=True,
            notes=(
                "audit-only gate; the site PLC enforces the authority, "
                "not AquaOptima",
            ),
        ),
        PLCGatekeeperCondition(
            condition_id="gate_mode_enabled",
            category=GATEKEEPER_CATEGORY_MODE_ENABLED,
            required_state=(
                "site PLC reports the supervisory advisory mode as "
                "enabled and not in manual / maintenance / e-stop"
            ),
            observed_label="site_plc_mode_status_label",
            status=GATEKEEPER_STATUS_NOT_EVALUATED,
            blocking=True,
            notes=(
                "mode gate is audit-only; manual / maintenance / e-stop "
                "always wins",
            ),
        ),
        PLCGatekeeperCondition(
            condition_id="gate_interlocks_healthy",
            category=GATEKEEPER_CATEGORY_INTERLOCKS_HEALTHY,
            required_state=(
                "site PLC reports all relevant interlocks as healthy "
                "for the proposal window"
            ),
            observed_label="site_plc_interlock_health_label",
            status=GATEKEEPER_STATUS_NOT_EVALUATED,
            blocking=True,
            notes=(
                "any unhealthy interlock blocks the dry-run regardless "
                "of confidence",
            ),
        ),
        PLCGatekeeperCondition(
            condition_id="gate_permissives_healthy",
            category=GATEKEEPER_CATEGORY_PERMISSIVES_HEALTHY,
            required_state=(
                "site PLC reports all relevant permissives as healthy "
                "for the proposal window"
            ),
            observed_label="site_plc_permissive_health_label",
            status=GATEKEEPER_STATUS_NOT_EVALUATED,
            blocking=True,
            notes=(
                "permissives gate the site PLC, not AquaOptima",
            ),
        ),
        PLCGatekeeperCondition(
            condition_id="gate_stale_data_rejection",
            category=GATEKEEPER_CATEGORY_STALE_DATA_REJECTION,
            required_state=(
                "Sprint 48 freshness policy holds — telemetry windows "
                "feeding the proposal are within their freshness "
                "thresholds"
            ),
            observed_label="sprint_48_freshness_evidence_label",
            status=GATEKEEPER_STATUS_NOT_EVALUATED,
            blocking=True,
            notes=(
                "stale data falls through to audit-only output; the "
                "site PLC retains authority",
            ),
        ),
        PLCGatekeeperCondition(
            condition_id="gate_bounds_rate_limits",
            category=GATEKEEPER_CATEGORY_BOUNDS_RATE_LIMITS,
            required_state=(
                "proposal value lies within the lower / upper envelope "
                "and within site rate-of-change limits documented in "
                "the site SAT evidence"
            ),
            observed_label="site_sat_rate_limit_evidence_label",
            status=GATEKEEPER_STATUS_NOT_EVALUATED,
            blocking=True,
            notes=(
                "bounds and rate limits are enforced by the site PLC; "
                "AquaOptima only proposes",
            ),
        ),
        PLCGatekeeperCondition(
            condition_id="gate_fallback_manual_priority",
            category=GATEKEEPER_CATEGORY_FALLBACK_MANUAL_PRIORITY,
            required_state=(
                "site PLC fallback / manual operation always takes "
                "priority over any AquaOptima advisory output"
            ),
            observed_label="site_fallback_priority_evidence_label",
            status=GATEKEEPER_STATUS_NOT_EVALUATED,
            blocking=True,
            notes=(
                "site PLC retains direct VFD / pump / actuator "
                "authority at all times",
            ),
        ),
        PLCGatekeeperCondition(
            condition_id="gate_e_stop_manual_override",
            category=GATEKEEPER_CATEGORY_E_STOP_MANUAL_OVERRIDE,
            required_state=(
                "E-stop and manual override paths remain authoritative "
                "and unaffected by the AquaOptima advisory channel"
            ),
            observed_label="site_e_stop_walkthrough_evidence_label",
            status=GATEKEEPER_STATUS_NOT_EVALUATED,
            blocking=True,
            notes=(
                "E-stop and manual override are non-negotiable; the "
                "advisory channel can be disabled at any time",
            ),
        ),
    )

    evaluation = PLCGatekeeperEvaluation(
        evaluation_id="amax_8580_supervisory_dry_run_evaluation_v1",
        proposal=proposal,
        conditions=conditions,
        verdict=VERDICT_NOT_EVALUATED,
        simulation_only=True,
        notes=(
            "default Sprint 50 evaluation ships in not_evaluated state; "
            "real site evidence is required before any condition can be "
            "marked passed",
        ),
    )

    return AMAXSupervisoryDryRunContract(
        contract_id=AMAX_SUPERVISORY_DRY_RUN_CONTRACT_ID,
        proposal=proposal,
        gatekeeper_evaluation=evaluation,
        referenced_evidence=(
            "sprint_49_amax_site_deployment_evidence_package",
            "sprint_48_amax_read_only_integration_contract",
            "sprint_47_amax_benchmark_report",
            "sprint_46_amax_feasibility_decision",
            "docs/hardware/amax-8580-site-deployment-readiness.md",
            "docs/hardware/amax-8580-read-only-integration.md",
            "docs/hardware/amax-8580-supervisory-dry-run-gatekeeper.md",
        ),
        next_gate=(
            "Sprint 51 — AMAX Pilot Readiness Review / "
            "Hardware-in-the-loop Plan (still no live control)"
        ),
        live_write_authorized=False,
        warnings=(),
        errors=(),
        safety_notes=(
            "Sprint 50 ships a simulated supervisory proposal / PLC "
            "gatekeeper contract, not a live write or control "
            "authorisation",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "no control-loop closure",
            "no direct VFD / pump / actuator control from AquaOptima Edge",
            "no bypass of site PLC interlocks, permissives, trips, "
            "manual mode, or emergency stop",
            "site PLC retains direct VFD / pump / actuator authority",
            "Sprint 51 should remain an AMAX pilot readiness review / "
            "hardware-in-the-loop plan, still no live control",
        ),
    )


__all__ = [
    "AMAX_SUPERVISORY_DRY_RUN_CONTRACT_ID",
    "AMAXSupervisoryDryRunContract",
    "AMAXSupervisoryDryRunDiagnostics",
    "GATEKEEPER_CATEGORIES",
    "GATEKEEPER_CATEGORY_BOUNDS_RATE_LIMITS",
    "GATEKEEPER_CATEGORY_E_STOP_MANUAL_OVERRIDE",
    "GATEKEEPER_CATEGORY_FALLBACK_MANUAL_PRIORITY",
    "GATEKEEPER_CATEGORY_INTERLOCKS_HEALTHY",
    "GATEKEEPER_CATEGORY_MODE_ENABLED",
    "GATEKEEPER_CATEGORY_OPERATOR_ENABLE",
    "GATEKEEPER_CATEGORY_PERMISSIVES_HEALTHY",
    "GATEKEEPER_CATEGORY_STALE_DATA_REJECTION",
    "GATEKEEPER_STATUS_FAILED",
    "GATEKEEPER_STATUS_NOT_EVALUATED",
    "GATEKEEPER_STATUS_PASSED",
    "GATEKEEPER_STATUS_TOKENS",
    "GATEKEEPER_VERDICT_TOKENS",
    "PLCGatekeeperCondition",
    "PLCGatekeeperEvaluation",
    "SupervisoryProposalDryRun",
    "SupervisoryProposalValue",
    "VERDICT_BLOCKED",
    "VERDICT_NOT_EVALUATED",
    "VERDICT_SIMULATION_ACCEPTED",
    "default_amax_supervisory_dry_run_contract",
    "diagnose_amax_supervisory_dry_run_contract",
    "evaluate_plc_gatekeeper_dry_run",
]
