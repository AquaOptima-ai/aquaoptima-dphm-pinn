"""Sprint 51 — AMAX pilot readiness review / hardware-in-the-loop plan SDK.

Sprint 51 is the final AMAX evidence-ladder sprint. It defines an
**AMAX pilot readiness review / hardware-in-the-loop (HIL) plan**
contract: a deterministic, audit-only structure that maps the
Sprint 46–50 evidence ladder onto a concrete HIL test matrix and the
go / no-go gate that must pass before any real lab or pilot is
considered. **Sprint 51 ships planning / HIL readiness contracts,
not a live write or control authorisation.** It is SDK / docs /
contracts / tests only. It does **not** implement live OT adapters,
Edge daemons, PLC/SCADA clients, network code, write paths, or any
proposal-to-PLC routing.

Every dataclass in this module is a frozen, stdlib-only audit value
record. Nothing here authorises a write, dispatch, actuation, or
control surface; every contract is planning-only / HIL-readiness-only
and falls through to site PLC authority at every gate.

The non-negotiable safety boundary stays explicit:

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- the site PLC retains direct VFD / pump / actuator authority.

Public surface:

* :class:`HILTestCase` — frozen dataclass for one HIL test case
  (id, category, objective, required evidence references, expected
  result, blocking flag, simulation_only flag, notes). Categories
  cover the Sprint 46–50 evidence chain: package install, CPU
  benchmark, read-only adapter, telemetry replay, stale-data failure,
  package rollback, operator disable, network loss, PLC gatekeeper
  dry-run, deployment readiness review.
* :class:`HILTestMatrix` — frozen dataclass bundling a tuple of
  :class:`HILTestCase` records with a matrix id, target hardware
  profile label, target OS / runtime label, bench (or simulated) PLC
  label, and references to Sprint 46–50 evidence.
* :class:`PilotReadinessEvidenceItem` — frozen dataclass capturing one
  evidence ledger entry (id, source sprint / doc, status, owner /
  reviewer label, blocking flag, notes).
* :class:`PilotReadinessReview` — frozen dataclass combining the HIL
  matrix, evidence items, open risks, verdict
  (``not_ready``, ``ready_for_lab_simulation``, ``blocked``),
  referenced Sprint 46–50 evidence, next gate, and the reaffirmed
  safety boundary. Carries explicit ``live_control_authorized=False``
  and refuses to record this flag as ``True``.
* :func:`default_amax_hil_test_matrix` — canonical Sprint 51 HIL
  matrix covering every required category.
* :func:`default_amax_pilot_readiness_review` — canonical Sprint 51
  default review. Audit-only; verdict starts at ``not_ready``.
* :func:`evaluate_amax_pilot_readiness_review` — pure helper that
  produces a deterministic readiness review from an HIL matrix plus
  a sequence of evidence items. The verdict is computed
  deterministically and is constrained to the lab / simulation
  vocabulary; no live control / write verdict can be produced.
* :class:`AMAXPilotReadinessDiagnostics` — deterministic warnings /
  errors record surfaced by
  :func:`diagnose_amax_pilot_readiness_review` when the review is
  missing required HIL categories, missing Sprint 46–50 evidence
  references, attempts to declare live-control authorisation, or
  carries unsafe vocabulary in identifier / label fields.

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


# Canonical HIL test categories. Adding a new token is an SDK MINOR
# bump; repurposing or removing is MAJOR.
HIL_CATEGORY_PACKAGE_INSTALL: str = "package_install"
HIL_CATEGORY_CPU_BENCHMARK: str = "cpu_benchmark"
HIL_CATEGORY_READ_ONLY_ADAPTER: str = "read_only_adapter"
HIL_CATEGORY_TELEMETRY_REPLAY: str = "telemetry_replay"
HIL_CATEGORY_STALE_DATA_FAILURE: str = "stale_data_failure"
HIL_CATEGORY_PACKAGE_ROLLBACK: str = "package_rollback"
HIL_CATEGORY_OPERATOR_DISABLE: str = "operator_disable"
HIL_CATEGORY_NETWORK_LOSS: str = "network_loss"
HIL_CATEGORY_PLC_GATEKEEPER_DRY_RUN: str = "plc_gatekeeper_dry_run"
HIL_CATEGORY_DEPLOYMENT_READINESS_REVIEW: str = (
    "deployment_readiness_review"
)


HIL_TEST_CATEGORIES: frozenset[str] = frozenset(
    {
        HIL_CATEGORY_PACKAGE_INSTALL,
        HIL_CATEGORY_CPU_BENCHMARK,
        HIL_CATEGORY_READ_ONLY_ADAPTER,
        HIL_CATEGORY_TELEMETRY_REPLAY,
        HIL_CATEGORY_STALE_DATA_FAILURE,
        HIL_CATEGORY_PACKAGE_ROLLBACK,
        HIL_CATEGORY_OPERATOR_DISABLE,
        HIL_CATEGORY_NETWORK_LOSS,
        HIL_CATEGORY_PLC_GATEKEEPER_DRY_RUN,
        HIL_CATEGORY_DEPLOYMENT_READINESS_REVIEW,
    }
)


# Canonical evidence-item status tokens for the Sprint 51 evidence
# ledger. ``pending`` is the conservative default; ``available``
# means the cited evidence is on file and current; ``blocked`` is
# reserved for evidence that has been actively flagged unsatisfied.
PILOT_EVIDENCE_STATUS_PENDING: str = "pending"
PILOT_EVIDENCE_STATUS_AVAILABLE: str = "available"
PILOT_EVIDENCE_STATUS_BLOCKED: str = "blocked"


PILOT_EVIDENCE_STATUS_TOKENS: frozenset[str] = frozenset(
    {
        PILOT_EVIDENCE_STATUS_PENDING,
        PILOT_EVIDENCE_STATUS_AVAILABLE,
        PILOT_EVIDENCE_STATUS_BLOCKED,
    }
)


# Canonical pilot readiness review verdict tokens. The vocabulary is
# intentionally restricted to lab / simulation states — no live
# write, dispatch, actuation, or control verdict can be produced by
# this module.
PILOT_VERDICT_NOT_READY: str = "not_ready"
PILOT_VERDICT_READY_FOR_LAB_SIMULATION: str = "ready_for_lab_simulation"
PILOT_VERDICT_BLOCKED: str = "blocked"


PILOT_READINESS_VERDICT_TOKENS: frozenset[str] = frozenset(
    {
        PILOT_VERDICT_NOT_READY,
        PILOT_VERDICT_READY_FOR_LAB_SIMULATION,
        PILOT_VERDICT_BLOCKED,
    }
)


# Canonical Sprint 51 review identifier. Adding additional canonical
# ids is an SDK MINOR bump; repurposing or removing is MAJOR.
AMAX_PILOT_READINESS_REVIEW_ID: str = (
    "amax_8580_pilot_readiness_review_v1"
)
AMAX_HIL_TEST_MATRIX_ID: str = (
    "amax_8580_hardware_in_the_loop_test_matrix_v1"
)


# Tokens that must never appear in an HIL identifier, label, or
# reference field because they describe an affirmative write /
# dispatch / actuator surface. Probe strings are assembled from
# fragments so this module does not embed the canonical forbidden-
# vocabulary literals; the forbidden-vocabulary scan remains the
# source of truth for those.
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
# HILTestCase
# ---------------------------------------------------------------------------


_TEST_CASE_FIELDS: tuple[str, ...] = (
    "test_id",
    "category",
    "objective",
    "required_evidence_references",
    "expected_result",
    "blocking",
    "simulation_only",
    "notes",
)


@dataclass(frozen=True)
class HILTestCase:
    """Frozen audit row for one HIL test case.

    Audit-only / planning-only. Captures the test id, canonical HIL
    category, plain-text objective, required evidence references
    (Sprint 46–50 evidence handles or document paths), the expected
    result text, a blocking flag, and audit notes. Always carries
    ``simulation_only=True``; the SDK refuses to record this flag as
    ``False``. Nothing in this record represents a write, dispatch,
    actuation, or control surface.

    The ``required_evidence_references`` field is a tuple of labels
    pointing to Sprint 46–50 evidence (e.g.
    ``sprint_46_amax_feasibility_decision``). The labels are
    references, not callable handles.
    """

    test_id: str
    category: str
    objective: str
    required_evidence_references: tuple[str, ...] = ()
    expected_result: str = ""
    blocking: bool = True
    simulation_only: bool = True
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(self.test_id, label="HILTestCase.test_id")
        _ensure_str(self.category, label="HILTestCase.category")
        if self.category not in HIL_TEST_CATEGORIES:
            raise ContractError(
                f"HILTestCase.category {self.category!r} is not in the "
                f"allowed list ({sorted(HIL_TEST_CATEGORIES)})"
            )
        _ensure_str(self.objective, label="HILTestCase.objective")
        refs = _ensure_str_tuple(
            self.required_evidence_references,
            label="HILTestCase.required_evidence_references",
        )
        _ensure_string(
            self.expected_result, label="HILTestCase.expected_result"
        )
        _ensure_bool(self.blocking, label="HILTestCase.blocking")
        _ensure_bool(
            self.simulation_only, label="HILTestCase.simulation_only"
        )
        if not self.simulation_only:
            raise ContractError(
                "HILTestCase.simulation_only must be True — Sprint 51 ships "
                "a HIL readiness contract, not a live write or control "
                "authorisation"
            )
        notes = _ensure_str_tuple(self.notes, label="HILTestCase.notes")
        object.__setattr__(self, "required_evidence_references", refs)
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "category": self.category,
            "objective": self.objective,
            "required_evidence_references": list(
                self.required_evidence_references
            ),
            "expected_result": self.expected_result,
            "blocking": self.blocking,
            "simulation_only": self.simulation_only,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HILTestCase":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"HILTestCase.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="HILTestCase")
        missing = {"test_id", "category", "objective"} - set(data.keys())
        if missing:
            raise ContractError(
                f"HILTestCase missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_TEST_CASE_FIELDS)
        if unknown:
            raise ContractError(
                f"HILTestCase received unknown fields: {sorted(unknown)}"
            )
        blocking_raw = data.get("blocking", True)
        if not isinstance(blocking_raw, bool):
            raise ContractError("HILTestCase.blocking must be a bool")
        simulation_only_raw = data.get("simulation_only", True)
        if not isinstance(simulation_only_raw, bool):
            raise ContractError(
                "HILTestCase.simulation_only must be a bool"
            )
        return cls(
            test_id=str(data["test_id"]),
            category=str(data["category"]),
            objective=str(data["objective"]),
            required_evidence_references=_coerce_str_sequence(
                data,
                "required_evidence_references",
                label="HILTestCase",
            ),
            expected_result=str(data.get("expected_result", "")),
            blocking=blocking_raw,
            simulation_only=simulation_only_raw,
            notes=_coerce_str_sequence(
                data, "notes", label="HILTestCase"
            ),
        )


# ---------------------------------------------------------------------------
# HILTestMatrix
# ---------------------------------------------------------------------------


_TEST_MATRIX_FIELDS: tuple[str, ...] = (
    "matrix_id",
    "test_cases",
    "target_hardware_profile_label",
    "target_os_runtime_label",
    "bench_plc_label",
    "referenced_evidence",
    "notes",
)


@dataclass(frozen=True)
class HILTestMatrix:
    """Frozen audit bundle of HIL test cases.

    Audit-only / planning-only. Bundles a tuple of
    :class:`HILTestCase` records under a matrix id with a target
    hardware profile label (e.g.
    ``amax_8580_core_i5_6300u_8gb``), a target OS / runtime label
    (e.g. ``ubuntu_18_codesys_linux_control_runtime``), a bench (or
    simulated) PLC label, references to Sprint 46–50 evidence, and
    audit notes. Nothing in this record represents a write, dispatch,
    actuation, or control surface.
    """

    matrix_id: str
    test_cases: tuple[HILTestCase, ...]
    target_hardware_profile_label: str = ""
    target_os_runtime_label: str = ""
    bench_plc_label: str = ""
    referenced_evidence: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.matrix_id, label="HILTestMatrix.matrix_id"
        )
        if not isinstance(self.test_cases, tuple):
            raise ContractError(
                "HILTestMatrix.test_cases must be a tuple"
            )
        for entry in self.test_cases:
            if not isinstance(entry, HILTestCase):
                raise ContractError(
                    "HILTestMatrix.test_cases must contain HILTestCase "
                    "instances"
                )
        seen: set[str] = set()
        for entry in self.test_cases:
            if entry.test_id in seen:
                raise ContractError(
                    f"HILTestMatrix has duplicate test id "
                    f"{entry.test_id!r}"
                )
            seen.add(entry.test_id)
        _ensure_string(
            self.target_hardware_profile_label,
            label="HILTestMatrix.target_hardware_profile_label",
        )
        _ensure_string(
            self.target_os_runtime_label,
            label="HILTestMatrix.target_os_runtime_label",
        )
        _ensure_string(
            self.bench_plc_label,
            label="HILTestMatrix.bench_plc_label",
        )
        referenced = _ensure_str_tuple(
            self.referenced_evidence,
            label="HILTestMatrix.referenced_evidence",
        )
        notes = _ensure_str_tuple(
            self.notes, label="HILTestMatrix.notes"
        )
        object.__setattr__(self, "referenced_evidence", referenced)
        object.__setattr__(self, "notes", notes)

    @property
    def categories(self) -> frozenset[str]:
        """Return the set of HIL categories present in this matrix."""

        return frozenset(case.category for case in self.test_cases)

    def cases_for_category(
        self, category: str
    ) -> tuple[HILTestCase, ...]:
        """Return the test cases whose ``category`` equals ``category``."""

        return tuple(c for c in self.test_cases if c.category == category)

    def to_dict(self) -> dict[str, Any]:
        return {
            "matrix_id": self.matrix_id,
            "test_cases": [case.to_dict() for case in self.test_cases],
            "target_hardware_profile_label": (
                self.target_hardware_profile_label
            ),
            "target_os_runtime_label": self.target_os_runtime_label,
            "bench_plc_label": self.bench_plc_label,
            "referenced_evidence": list(self.referenced_evidence),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HILTestMatrix":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"HILTestMatrix.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="HILTestMatrix")
        missing = {"matrix_id", "test_cases"} - set(data.keys())
        if missing:
            raise ContractError(
                f"HILTestMatrix missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_TEST_MATRIX_FIELDS)
        if unknown:
            raise ContractError(
                f"HILTestMatrix received unknown fields: {sorted(unknown)}"
            )
        raw_cases = data["test_cases"]
        if isinstance(raw_cases, (str, bytes)) or not isinstance(
            raw_cases, Sequence
        ):
            raise ContractError(
                "HILTestMatrix.test_cases must be a sequence"
            )
        return cls(
            matrix_id=str(data["matrix_id"]),
            test_cases=tuple(
                HILTestCase.from_dict(case) for case in raw_cases
            ),
            target_hardware_profile_label=str(
                data.get("target_hardware_profile_label", "")
            ),
            target_os_runtime_label=str(
                data.get("target_os_runtime_label", "")
            ),
            bench_plc_label=str(data.get("bench_plc_label", "")),
            referenced_evidence=_coerce_str_sequence(
                data, "referenced_evidence", label="HILTestMatrix"
            ),
            notes=_coerce_str_sequence(
                data, "notes", label="HILTestMatrix"
            ),
        )


# ---------------------------------------------------------------------------
# PilotReadinessEvidenceItem
# ---------------------------------------------------------------------------


_EVIDENCE_ITEM_FIELDS: tuple[str, ...] = (
    "evidence_id",
    "source_sprint_or_doc",
    "status",
    "owner_label",
    "blocking",
    "notes",
)


@dataclass(frozen=True)
class PilotReadinessEvidenceItem:
    """Frozen audit row for one Sprint 51 evidence-ledger entry.

    Audit-only / planning-only. Captures the evidence id, source
    sprint / doc reference (e.g.
    ``sprint_47_amax_benchmark_report`` or
    ``docs/hardware/amax-8580-cpu-benchmarking.md``), evidence status,
    owner / reviewer label, blocking flag, and audit notes. Nothing in
    this record represents a write, dispatch, actuation, or control
    surface.
    """

    evidence_id: str
    source_sprint_or_doc: str
    status: str = PILOT_EVIDENCE_STATUS_PENDING
    owner_label: str = ""
    blocking: bool = True
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.evidence_id,
            label="PilotReadinessEvidenceItem.evidence_id",
        )
        _ensure_str(
            self.source_sprint_or_doc,
            label="PilotReadinessEvidenceItem.source_sprint_or_doc",
        )
        _ensure_str(
            self.status, label="PilotReadinessEvidenceItem.status"
        )
        if self.status not in PILOT_EVIDENCE_STATUS_TOKENS:
            raise ContractError(
                f"PilotReadinessEvidenceItem.status {self.status!r} is "
                f"not in the allowed list "
                f"({sorted(PILOT_EVIDENCE_STATUS_TOKENS)})"
            )
        _ensure_string(
            self.owner_label,
            label="PilotReadinessEvidenceItem.owner_label",
        )
        _ensure_bool(
            self.blocking,
            label="PilotReadinessEvidenceItem.blocking",
        )
        notes = _ensure_str_tuple(
            self.notes, label="PilotReadinessEvidenceItem.notes"
        )
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_sprint_or_doc": self.source_sprint_or_doc,
            "status": self.status,
            "owner_label": self.owner_label,
            "blocking": self.blocking,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "PilotReadinessEvidenceItem":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"PilotReadinessEvidenceItem.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="PilotReadinessEvidenceItem")
        missing = {"evidence_id", "source_sprint_or_doc"} - set(
            data.keys()
        )
        if missing:
            raise ContractError(
                f"PilotReadinessEvidenceItem missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_EVIDENCE_ITEM_FIELDS)
        if unknown:
            raise ContractError(
                f"PilotReadinessEvidenceItem received unknown fields: "
                f"{sorted(unknown)}"
            )
        blocking_raw = data.get("blocking", True)
        if not isinstance(blocking_raw, bool):
            raise ContractError(
                "PilotReadinessEvidenceItem.blocking must be a bool"
            )
        return cls(
            evidence_id=str(data["evidence_id"]),
            source_sprint_or_doc=str(data["source_sprint_or_doc"]),
            status=str(
                data.get("status", PILOT_EVIDENCE_STATUS_PENDING)
            ),
            owner_label=str(data.get("owner_label", "")),
            blocking=blocking_raw,
            notes=_coerce_str_sequence(
                data, "notes", label="PilotReadinessEvidenceItem"
            ),
        )


# ---------------------------------------------------------------------------
# PilotReadinessReview
# ---------------------------------------------------------------------------


_REVIEW_FIELDS: tuple[str, ...] = (
    "review_id",
    "hil_matrix",
    "evidence_items",
    "open_risks",
    "verdict",
    "live_control_authorized",
    "referenced_evidence",
    "next_gate",
    "safety_notes",
)


@dataclass(frozen=True)
class PilotReadinessReview:
    """Frozen Sprint 51 pilot readiness review bundle.

    Audit-only / planning-only. Combines the HIL test matrix, the
    evidence ledger, open risks, a deterministic verdict, references
    to Sprint 46–50 evidence, the next gate, and the reaffirmed
    safety boundary. Carries explicit ``live_control_authorized=False``
    — the SDK refuses to record this flag as ``True``. Verdicts are
    constrained to ``not_ready``, ``ready_for_lab_simulation``, or
    ``blocked``; no live control / write verdict can be produced.
    Nothing in this record represents a write, dispatch, actuation,
    or control surface.
    """

    review_id: str
    hil_matrix: HILTestMatrix
    evidence_items: tuple[PilotReadinessEvidenceItem, ...]
    open_risks: tuple[str, ...] = ()
    verdict: str = PILOT_VERDICT_NOT_READY
    live_control_authorized: bool = False
    referenced_evidence: tuple[str, ...] = ()
    next_gate: str = ""
    safety_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.review_id, label="PilotReadinessReview.review_id"
        )
        if not isinstance(self.hil_matrix, HILTestMatrix):
            raise ContractError(
                "PilotReadinessReview.hil_matrix must be an HILTestMatrix"
            )
        if not isinstance(self.evidence_items, tuple):
            raise ContractError(
                "PilotReadinessReview.evidence_items must be a tuple"
            )
        for entry in self.evidence_items:
            if not isinstance(entry, PilotReadinessEvidenceItem):
                raise ContractError(
                    "PilotReadinessReview.evidence_items must contain "
                    "PilotReadinessEvidenceItem instances"
                )
        seen: set[str] = set()
        for entry in self.evidence_items:
            if entry.evidence_id in seen:
                raise ContractError(
                    f"PilotReadinessReview has duplicate evidence id "
                    f"{entry.evidence_id!r}"
                )
            seen.add(entry.evidence_id)
        open_risks = _ensure_str_tuple(
            self.open_risks,
            label="PilotReadinessReview.open_risks",
        )
        _ensure_str(self.verdict, label="PilotReadinessReview.verdict")
        if self.verdict not in PILOT_READINESS_VERDICT_TOKENS:
            raise ContractError(
                f"PilotReadinessReview.verdict {self.verdict!r} is not "
                f"in the allowed list "
                f"({sorted(PILOT_READINESS_VERDICT_TOKENS)})"
            )
        _ensure_bool(
            self.live_control_authorized,
            label="PilotReadinessReview.live_control_authorized",
        )
        if self.live_control_authorized:
            raise ContractError(
                "PilotReadinessReview.live_control_authorized must be "
                "False — Sprint 51 does not authorise any live write, "
                "dispatch, actuation, or control surface"
            )
        referenced = _ensure_str_tuple(
            self.referenced_evidence,
            label="PilotReadinessReview.referenced_evidence",
        )
        _ensure_string(
            self.next_gate, label="PilotReadinessReview.next_gate"
        )
        safety_notes = _ensure_str_tuple(
            self.safety_notes,
            label="PilotReadinessReview.safety_notes",
        )
        object.__setattr__(self, "open_risks", open_risks)
        object.__setattr__(self, "referenced_evidence", referenced)
        object.__setattr__(self, "safety_notes", safety_notes)

    @property
    def hil_categories(self) -> frozenset[str]:
        """Return the HIL categories present in the matrix."""

        return self.hil_matrix.categories

    def unresolved_blocking_evidence(
        self,
    ) -> tuple[PilotReadinessEvidenceItem, ...]:
        """Return blocking evidence whose status is not ``available``.

        Pure audit helper. Any blocking evidence whose status is
        anything other than ``available`` is considered unresolved.
        The verdict cannot be ``ready_for_lab_simulation`` while any
        unresolved blocking evidence remains.
        """

        return tuple(
            item
            for item in self.evidence_items
            if item.blocking
            and item.status != PILOT_EVIDENCE_STATUS_AVAILABLE
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "hil_matrix": self.hil_matrix.to_dict(),
            "evidence_items": [
                item.to_dict() for item in self.evidence_items
            ],
            "open_risks": list(self.open_risks),
            "verdict": self.verdict,
            "live_control_authorized": self.live_control_authorized,
            "referenced_evidence": list(self.referenced_evidence),
            "next_gate": self.next_gate,
            "safety_notes": list(self.safety_notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "PilotReadinessReview":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"PilotReadinessReview.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="PilotReadinessReview")
        missing = {
            "review_id",
            "hil_matrix",
            "evidence_items",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"PilotReadinessReview missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_REVIEW_FIELDS)
        if unknown:
            raise ContractError(
                f"PilotReadinessReview received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_items = data["evidence_items"]
        if isinstance(raw_items, (str, bytes)) or not isinstance(
            raw_items, Sequence
        ):
            raise ContractError(
                "PilotReadinessReview.evidence_items must be a sequence"
            )
        live_control = data.get("live_control_authorized", False)
        if not isinstance(live_control, bool):
            raise ContractError(
                "PilotReadinessReview.live_control_authorized must be "
                "a bool"
            )
        return cls(
            review_id=str(data["review_id"]),
            hil_matrix=HILTestMatrix.from_dict(data["hil_matrix"]),
            evidence_items=tuple(
                PilotReadinessEvidenceItem.from_dict(item)
                for item in raw_items
            ),
            open_risks=_coerce_str_sequence(
                data, "open_risks", label="PilotReadinessReview"
            ),
            verdict=str(
                data.get("verdict", PILOT_VERDICT_NOT_READY)
            ),
            live_control_authorized=live_control,
            referenced_evidence=_coerce_str_sequence(
                data,
                "referenced_evidence",
                label="PilotReadinessReview",
            ),
            next_gate=str(data.get("next_gate", "")),
            safety_notes=_coerce_str_sequence(
                data, "safety_notes", label="PilotReadinessReview"
            ),
        )


def evaluate_amax_pilot_readiness_review(
    hil_matrix: HILTestMatrix,
    evidence_items: Sequence[PilotReadinessEvidenceItem],
    *,
    review_id: str = AMAX_PILOT_READINESS_REVIEW_ID,
    open_risks: Sequence[str] = (),
    referenced_evidence: Sequence[str] = (),
    next_gate: str = "",
    safety_notes: Sequence[str] = (),
) -> PilotReadinessReview:
    """Return a deterministic, planning-only pilot readiness review.

    Pure helper. Builds a :class:`PilotReadinessReview` for
    ``hil_matrix`` against ``evidence_items``. The verdict is computed
    deterministically:

    * if any blocking evidence item has status ``blocked``, verdict
      is ``blocked``;
    * else if any blocking evidence item has status ``pending``,
      verdict is ``not_ready``;
    * else verdict is ``ready_for_lab_simulation``.

    The review is **always** ``live_control_authorized=False``; no
    live write, dispatch, actuation, or control verdict can be
    produced by this helper.
    """

    if not isinstance(hil_matrix, HILTestMatrix):
        raise ContractError(
            "evaluate_amax_pilot_readiness_review requires an "
            "HILTestMatrix"
        )
    if isinstance(evidence_items, (str, bytes)) or not isinstance(
        evidence_items, Sequence
    ):
        raise ContractError(
            "evaluate_amax_pilot_readiness_review requires a sequence "
            "of PilotReadinessEvidenceItem records"
        )
    items_tuple = tuple(evidence_items)
    for entry in items_tuple:
        if not isinstance(entry, PilotReadinessEvidenceItem):
            raise ContractError(
                "evaluate_amax_pilot_readiness_review requires "
                "PilotReadinessEvidenceItem records"
            )
    has_blocked = any(
        item.blocking
        and item.status == PILOT_EVIDENCE_STATUS_BLOCKED
        for item in items_tuple
    )
    has_pending = any(
        item.blocking
        and item.status == PILOT_EVIDENCE_STATUS_PENDING
        for item in items_tuple
    )
    if has_blocked:
        verdict = PILOT_VERDICT_BLOCKED
    elif has_pending:
        verdict = PILOT_VERDICT_NOT_READY
    else:
        verdict = PILOT_VERDICT_READY_FOR_LAB_SIMULATION
    return PilotReadinessReview(
        review_id=review_id,
        hil_matrix=hil_matrix,
        evidence_items=items_tuple,
        open_risks=tuple(open_risks),
        verdict=verdict,
        live_control_authorized=False,
        referenced_evidence=tuple(referenced_evidence),
        next_gate=next_gate,
        safety_notes=tuple(safety_notes),
    )


# ---------------------------------------------------------------------------
# AMAXPilotReadinessDiagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AMAXPilotReadinessDiagnostics:
    """Deterministic warnings / errors for a Sprint 51 readiness review.

    Audit-only / planning-only. Surfaces missing required HIL
    categories, missing Sprint 46–50 evidence references, missing
    next-gate language, attempts to declare live-control
    authorisation, verdicts outside the lab / simulation vocabulary,
    and unsafe vocabulary detected in identifier / label fields.
    Nothing in this record represents a write, dispatch, actuation,
    or control surface.
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
                    f"AMAXPilotReadinessDiagnostics.{name} must be a "
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
    ) -> "AMAXPilotReadinessDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXPilotReadinessDiagnostics.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        unknown = set(data.keys()) - {"warnings", "errors"}
        if unknown:
            raise ContractError(
                f"AMAXPilotReadinessDiagnostics received unknown "
                f"fields: {sorted(unknown)}"
            )
        warnings = tuple(str(w) for w in data.get("warnings", ()))
        errors = tuple(str(e) for e in data.get("errors", ()))
        return cls(warnings=warnings, errors=errors)


_REQUIRED_SPRINT_EVIDENCE_TOKENS: tuple[str, ...] = (
    "sprint_46",
    "sprint_47",
    "sprint_48",
    "sprint_49",
    "sprint_50",
)


def diagnose_amax_pilot_readiness_review(
    review: PilotReadinessReview,
) -> AMAXPilotReadinessDiagnostics:
    """Return deterministic warnings / errors for ``review``.

    Pure audit helper. The checks cover:

    * missing required HIL categories from the canonical Sprint 51
      set (package install, CPU benchmark, read-only adapter,
      telemetry replay, stale-data failure, package rollback,
      operator disable, network loss, PLC gatekeeper dry-run,
      deployment readiness review);
    * missing Sprint 46 / 47 / 48 / 49 / 50 evidence references;
    * missing next-gate language;
    * any attempt to declare live-control authorisation;
    * verdicts outside the lab / simulation vocabulary; and
    * unsafe vocabulary in identifier / label / reference fields
      (substring scan).

    No live binding, no write, no setpoint, no command emission.
    """

    if not isinstance(review, PilotReadinessReview):
        raise ContractError(
            "diagnose_amax_pilot_readiness_review requires a "
            "PilotReadinessReview"
        )

    warnings: list[str] = []
    errors: list[str] = []

    present_categories = review.hil_categories
    missing_categories = HIL_TEST_CATEGORIES - present_categories
    if missing_categories:
        errors.append(
            f"HIL matrix missing required categories: "
            f"{sorted(missing_categories)}"
        )

    refs_joined = "\n".join(review.referenced_evidence).lower()
    if not review.referenced_evidence:
        errors.append(
            "review has no referenced_evidence — Sprint 51 reviews "
            "must cite Sprint 46–50 evidence handles"
        )
    else:
        missing_sprints: list[str] = []
        for token in _REQUIRED_SPRINT_EVIDENCE_TOKENS:
            if token not in refs_joined:
                missing_sprints.append(token)
        if missing_sprints:
            warnings.append(
                f"review referenced_evidence is missing references to "
                f"these sprints: {missing_sprints}"
            )

    if not review.next_gate:
        warnings.append(
            "review has no next_gate — Sprint 51 reviews should name "
            "the next gate (Sprint 52+ phase checkpoint / replanning "
            "gate, not automatic live-control implementation)"
        )

    if not review.safety_notes:
        warnings.append(
            "review has no safety_notes — Sprint 51 reviews should "
            "explicitly reaffirm the planning-only / HIL-readiness-only "
            "boundary"
        )

    if review.live_control_authorized:
        errors.append(
            "review.live_control_authorized must be False — Sprint 51 "
            "does not authorise any live write or control surface"
        )

    if review.verdict not in PILOT_READINESS_VERDICT_TOKENS:
        errors.append(
            f"review verdict {review.verdict!r} is not in the allowed "
            f"lab / simulation set "
            f"{sorted(PILOT_READINESS_VERDICT_TOKENS)}"
        )

    # Unsafe vocabulary scan over identifier / label fields only. The
    # narrative objective / expected_result / notes / open_risks /
    # safety_notes fields are intentionally allowed to discuss
    # boundary phrases in negative context (e.g. "no setpoint output",
    # "site PLC retains direct VFD / pump / actuator authority");
    # they are audit text and would lose their value if they could
    # not name what the system explicitly does not do. Labels and ids
    # must stay clear of those phrases — that is what callers grep
    # for.
    for case in review.hil_matrix.test_cases:
        unsafe = _scan_unsafe_phrases(case.test_id)
        if unsafe:
            errors.append(
                f"HIL test case {case.test_id!r} contains unsafe "
                f"vocabulary {list(unsafe)}"
            )

    matrix_label_haystack = "\n".join(
        (
            review.hil_matrix.matrix_id,
            review.hil_matrix.target_hardware_profile_label,
            review.hil_matrix.target_os_runtime_label,
            review.hil_matrix.bench_plc_label,
        )
    )
    matrix_unsafe = _scan_unsafe_phrases(matrix_label_haystack)
    if matrix_unsafe:
        errors.append(
            f"HIL matrix labels contain unsafe vocabulary "
            f"{list(matrix_unsafe)}"
        )

    for item in review.evidence_items:
        haystack = "\n".join(
            (
                item.evidence_id,
                item.source_sprint_or_doc,
                item.owner_label,
            )
        )
        unsafe = _scan_unsafe_phrases(haystack)
        if unsafe:
            errors.append(
                f"evidence item {item.evidence_id!r} contains unsafe "
                f"vocabulary {list(unsafe)}"
            )

    return AMAXPilotReadinessDiagnostics(
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# Canonical Sprint 51 default helpers
# ---------------------------------------------------------------------------


def _default_hil_test_cases() -> tuple[HILTestCase, ...]:
    return (
        HILTestCase(
            test_id="hil_package_install_signed",
            category=HIL_CATEGORY_PACKAGE_INSTALL,
            objective=(
                "install the signed Sprint 44 deployment package on the "
                "AMAX lab unit using the Sprint 45 capability declaration "
                "shape and verify the package validator accepts it"
            ),
            required_evidence_references=(
                "sprint_45_amax_edge_capability_declaration",
                "sprint_46_amax_feasibility_decision",
                "sprint_49_amax_site_deployment_evidence_package",
            ),
            expected_result=(
                "package validator returns accepted=True; install "
                "completes with provenance + hash recorded"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "real AMAX lab unit is required before this case can "
                "transition from planned to executed",
                "no live OT binding",
            ),
        ),
        HILTestCase(
            test_id="hil_cpu_benchmark_within_supervisory_envelope",
            category=HIL_CATEGORY_CPU_BENCHMARK,
            objective=(
                "run the Sprint 47 dPHM-PINN CPU benchmark on the AMAX "
                "lab unit and verify p95 latency stays within the "
                "supervisory cadence envelope"
            ),
            required_evidence_references=(
                "sprint_47_amax_benchmark_report",
                "sprint_46_amax_feasibility_decision",
            ),
            expected_result=(
                "p50/p95/p99 latency within the supervisory cadence "
                "envelope; classify_supervisory_cadence returns the "
                "expected bucket label"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "benchmark is offline / CPU-only; no live OT binding",
                "no PLC/PAC/SCADA write",
            ),
        ),
        HILTestCase(
            test_id="hil_read_only_adapter_audit_only",
            category=HIL_CATEGORY_READ_ONLY_ADAPTER,
            objective=(
                "wire the AMAX lab unit to a bench or simulated PLC "
                "using the Sprint 48 read-only integration contract "
                "and confirm no write path is exposed"
            ),
            required_evidence_references=(
                "sprint_48_amax_read_only_integration_contract",
                "sprint_49_amax_site_deployment_evidence_package",
            ),
            expected_result=(
                "telemetry frames arrive on the read-only adapter; "
                "no write surface is exposed; site PLC retains direct "
                "VFD / pump / actuator authority"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "audit-only adapter exercise",
                "no command emission",
                "no setpoint output",
            ),
        ),
        HILTestCase(
            test_id="hil_telemetry_replay_equivalence",
            category=HIL_CATEGORY_TELEMETRY_REPLAY,
            objective=(
                "replay the Sprint 48 frozen replay dataset against the "
                "AMAX lab unit and confirm replay-to-live equivalence "
                "evidence is captured"
            ),
            required_evidence_references=(
                "sprint_48_amax_replay_to_live_equivalence_evidence",
                "sprint_42_shadow_replay_dataset",
            ),
            expected_result=(
                "equivalence status records as compatible or "
                "not_evaluated under controlled inputs; no live writes "
                "are attempted"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "telemetry replay is read-only by construction",
            ),
        ),
        HILTestCase(
            test_id="hil_stale_data_failure_audit",
            category=HIL_CATEGORY_STALE_DATA_FAILURE,
            objective=(
                "inject stale telemetry and confirm the Sprint 48 "
                "freshness policy + Sprint 50 stale-data gate together "
                "block the dry-run from being marked simulation-accepted"
            ),
            required_evidence_references=(
                "sprint_48_amax_read_only_integration_contract",
                "sprint_50_amax_supervisory_dry_run_contract",
            ),
            expected_result=(
                "dry-run gatekeeper verdict transitions to blocked; "
                "site PLC retains authority for the duration of the "
                "stale window"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "audit-only failure injection",
            ),
        ),
        HILTestCase(
            test_id="hil_package_rollback_drill",
            category=HIL_CATEGORY_PACKAGE_ROLLBACK,
            objective=(
                "execute the Sprint 49 rollback runbook against a known-"
                "bad package and confirm the AMAX lab unit returns to "
                "pre-deployment PLC-only operation"
            ),
            required_evidence_references=(
                "sprint_49_amax_site_deployment_evidence_package",
                "sprint_49_rollback_runbook_label",
            ),
            expected_result=(
                "rollback completes within the documented window; "
                "site PLC retains direct VFD / pump / actuator authority "
                "throughout"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "rollback drill is mandatory before any pilot",
            ),
        ),
        HILTestCase(
            test_id="hil_operator_disable_priority",
            category=HIL_CATEGORY_OPERATOR_DISABLE,
            objective=(
                "exercise the operator console disable path and confirm "
                "the AquaOptima advisory channel is disabled within the "
                "documented window without affecting site PLC behaviour"
            ),
            required_evidence_references=(
                "sprint_49_amax_site_deployment_evidence_package",
                "sprint_50_amax_supervisory_dry_run_contract",
            ),
            expected_result=(
                "advisory channel disabled; site PLC continues normal "
                "operation; manual / e-stop paths remain authoritative"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "operator disable is non-negotiable",
            ),
        ),
        HILTestCase(
            test_id="hil_network_loss_audit",
            category=HIL_CATEGORY_NETWORK_LOSS,
            objective=(
                "sever the AMAX lab unit's network link and confirm "
                "behaviour matches the Sprint 49 network failure mode "
                "(advisory pauses; site PLC retains authority)"
            ),
            required_evidence_references=(
                "sprint_49_amax_site_deployment_evidence_package",
                "sprint_48_amax_read_only_integration_contract",
            ),
            expected_result=(
                "advisory output pauses; site PLC continues normal "
                "operation; reconnection restores read-only flow "
                "without manual intervention"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "network loss falls through to site PLC authority",
            ),
        ),
        HILTestCase(
            test_id="hil_plc_gatekeeper_dry_run",
            category=HIL_CATEGORY_PLC_GATEKEEPER_DRY_RUN,
            objective=(
                "run the Sprint 50 PLC gatekeeper dry-run against a "
                "bench or simulated PLC and confirm the verdict stays "
                "in the simulation-only vocabulary"
            ),
            required_evidence_references=(
                "sprint_50_amax_supervisory_dry_run_contract",
                "sprint_49_amax_site_deployment_evidence_package",
            ),
            expected_result=(
                "gatekeeper evaluation produces a verdict in "
                "{not_evaluated, blocked, simulation_accepted}; no live "
                "write is attempted at any point"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "dry-run only; site PLC retains direct VFD / pump / "
                "actuator authority",
                "no control-loop closure",
            ),
        ),
        HILTestCase(
            test_id="hil_deployment_readiness_review",
            category=HIL_CATEGORY_DEPLOYMENT_READINESS_REVIEW,
            objective=(
                "walk the Sprint 49 deployment readiness checklist "
                "against the AMAX lab unit and confirm every required "
                "category has captured evidence"
            ),
            required_evidence_references=(
                "sprint_49_amax_site_deployment_evidence_package",
                "sprint_49_rollback_runbook_label",
            ),
            expected_result=(
                "checklist diagnostics return is_clean=True under "
                "lab evidence; no site install is approved by Sprint 51 "
                "alone"
            ),
            blocking=True,
            simulation_only=True,
            notes=(
                "checklist walkthrough is audit-only",
                "no site install approval by default",
            ),
        ),
    )


def default_amax_hil_test_matrix() -> HILTestMatrix:
    """Return the canonical Sprint 51 AMAX HIL test matrix.

    Audit-only / planning-only. Enumerates a deterministic test case
    for every canonical HIL category. All cases default to
    ``simulation_only=True`` — Sprint 51 ships a HIL readiness plan,
    not a pilot sign-off; real lab evidence is still required.
    """

    return HILTestMatrix(
        matrix_id=AMAX_HIL_TEST_MATRIX_ID,
        test_cases=_default_hil_test_cases(),
        target_hardware_profile_label=(
            "amax_8580_core_i5_6300u_8gb_serious_candidate"
        ),
        target_os_runtime_label=(
            "ubuntu_18_codesys_linux_control_runtime_lab_profile"
        ),
        bench_plc_label=(
            "bench_or_simulated_plc_lab_profile"
        ),
        referenced_evidence=(
            "sprint_46_amax_feasibility_decision",
            "sprint_47_amax_benchmark_report",
            "sprint_48_amax_read_only_integration_contract",
            "sprint_49_amax_site_deployment_evidence_package",
            "sprint_50_amax_supervisory_dry_run_contract",
        ),
        notes=(
            "Sprint 51 ships an AMAX HIL plan, not a pilot sign-off",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "no control-loop closure",
            "site PLC retains direct VFD / pump / actuator authority",
        ),
    )


def _default_evidence_items() -> tuple[
    PilotReadinessEvidenceItem, ...
]:
    return (
        PilotReadinessEvidenceItem(
            evidence_id="evidence_sprint_46_feasibility_decision",
            source_sprint_or_doc=(
                "sprint_46_amax_feasibility_decision"
            ),
            status=PILOT_EVIDENCE_STATUS_PENDING,
            owner_label="aquaoptima_amax_feasibility_owner",
            blocking=True,
            notes=(
                "feasibility evidence remains surrogate until real "
                "AMAX hardware is procured and inventoried",
            ),
        ),
        PilotReadinessEvidenceItem(
            evidence_id="evidence_sprint_47_benchmark_report",
            source_sprint_or_doc=(
                "sprint_47_amax_benchmark_report"
            ),
            status=PILOT_EVIDENCE_STATUS_PENDING,
            owner_label="aquaoptima_amax_benchmark_owner",
            blocking=True,
            notes=(
                "real AMAX CPU benchmark numbers are required before "
                "the HIL p95 envelope can be marked available",
            ),
        ),
        PilotReadinessEvidenceItem(
            evidence_id=(
                "evidence_sprint_48_read_only_integration_contract"
            ),
            source_sprint_or_doc=(
                "sprint_48_amax_read_only_integration_contract"
            ),
            status=PILOT_EVIDENCE_STATUS_PENDING,
            owner_label="aquaoptima_amax_integration_owner",
            blocking=True,
            notes=(
                "read-only adapter wiring must be verified against a "
                "bench or simulated PLC before lab simulation",
                "no live OT binding",
            ),
        ),
        PilotReadinessEvidenceItem(
            evidence_id=(
                "evidence_sprint_49_site_deployment_evidence_package"
            ),
            source_sprint_or_doc=(
                "sprint_49_amax_site_deployment_evidence_package"
            ),
            status=PILOT_EVIDENCE_STATUS_PENDING,
            owner_label="aquaoptima_amax_deployment_owner",
            blocking=True,
            notes=(
                "FAT / SAT / rollback / cybersecurity / failure-mode "
                "evidence still required",
            ),
        ),
        PilotReadinessEvidenceItem(
            evidence_id=(
                "evidence_sprint_50_supervisory_dry_run_contract"
            ),
            source_sprint_or_doc=(
                "sprint_50_amax_supervisory_dry_run_contract"
            ),
            status=PILOT_EVIDENCE_STATUS_PENDING,
            owner_label="aquaoptima_amax_supervisory_owner",
            blocking=True,
            notes=(
                "PLC gatekeeper dry-run remains simulation-only",
                "no PLC/PAC/SCADA write",
            ),
        ),
        PilotReadinessEvidenceItem(
            evidence_id="evidence_hil_lab_unit_inventoried",
            source_sprint_or_doc=(
                "docs/hardware/amax-8580-pilot-readiness-hil-plan.md"
            ),
            status=PILOT_EVIDENCE_STATUS_PENDING,
            owner_label="aquaoptima_amax_hil_lab_owner",
            blocking=True,
            notes=(
                "real AMAX lab unit must be procured, inventoried, and "
                "panel-mounted before Sprint 51 verdict can transition "
                "to ready_for_lab_simulation",
            ),
        ),
    )


def default_amax_pilot_readiness_review() -> PilotReadinessReview:
    """Return the canonical Sprint 51 AMAX pilot readiness review.

    Audit-only / planning-only. Bundles the deterministic HIL test
    matrix with a deterministic evidence ledger covering Sprint 46 /
    47 / 48 / 49 / 50 and the lab-unit-inventoried gate. References
    Sprint 46–50 evidence, reaffirms the Sprint 51 boundary in
    ``safety_notes``, and carries explicit
    ``live_control_authorized=False``. The default verdict is
    ``not_ready`` — Sprint 51 ships a HIL plan and evidence ledger,
    not a pilot sign-off.
    """

    matrix = default_amax_hil_test_matrix()
    evidence = _default_evidence_items()
    return PilotReadinessReview(
        review_id=AMAX_PILOT_READINESS_REVIEW_ID,
        hil_matrix=matrix,
        evidence_items=evidence,
        open_risks=(
            "real AMAX hardware not yet procured; Sprint 46 evidence "
            "remains surrogate",
            "CODESYS co-tenancy on the AMAX lab unit is unverified "
            "until Sprint 47/48 lab exercises are run",
            "site-specific FAT / SAT plan must be authored and "
            "reviewed before any real pilot",
            "rollback runbook must be dry-run signed off",
        ),
        verdict=PILOT_VERDICT_NOT_READY,
        live_control_authorized=False,
        referenced_evidence=(
            "sprint_46_amax_feasibility_decision",
            "sprint_47_amax_benchmark_report",
            "sprint_48_amax_read_only_integration_contract",
            "sprint_49_amax_site_deployment_evidence_package",
            "sprint_50_amax_supervisory_dry_run_contract",
            "docs/hardware/amax-8580-feasibility.md",
            "docs/hardware/amax-8580-cpu-benchmarking.md",
            "docs/hardware/amax-8580-read-only-integration.md",
            "docs/hardware/amax-8580-site-deployment-readiness.md",
            "docs/hardware/amax-8580-supervisory-dry-run-gatekeeper.md",
            "docs/hardware/amax-8580-pilot-readiness-hil-plan.md",
        ),
        next_gate=(
            "Sprint 52+ — phase checkpoint / replanning gate, not "
            "automatic live-control implementation. Sprints 52–60 are "
            "not yet well-planned and must be replanned before any "
            "implementation work begins."
        ),
        safety_notes=(
            "Sprint 51 ships an AMAX pilot readiness review / HIL plan "
            "contract, not a live write or control authorisation",
            "Sprint 51 remains planning-only / HIL-readiness-only",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "no control-loop closure",
            "no direct VFD / pump / actuator control from AquaOptima Edge",
            "no bypass of site PLC interlocks, permissives, trips, "
            "manual mode, or emergency stop",
            "site PLC retains direct VFD / pump / actuator authority",
            "after Sprint 51, Sprint 52 and beyond are not yet well-"
            "planned and should be replanned before implementation; "
            "the recommended next step is a phase checkpoint, not "
            "automatic live-control implementation",
        ),
    )


__all__ = [
    "AMAX_HIL_TEST_MATRIX_ID",
    "AMAX_PILOT_READINESS_REVIEW_ID",
    "AMAXPilotReadinessDiagnostics",
    "HIL_CATEGORY_CPU_BENCHMARK",
    "HIL_CATEGORY_DEPLOYMENT_READINESS_REVIEW",
    "HIL_CATEGORY_NETWORK_LOSS",
    "HIL_CATEGORY_OPERATOR_DISABLE",
    "HIL_CATEGORY_PACKAGE_INSTALL",
    "HIL_CATEGORY_PACKAGE_ROLLBACK",
    "HIL_CATEGORY_PLC_GATEKEEPER_DRY_RUN",
    "HIL_CATEGORY_READ_ONLY_ADAPTER",
    "HIL_CATEGORY_STALE_DATA_FAILURE",
    "HIL_CATEGORY_TELEMETRY_REPLAY",
    "HIL_TEST_CATEGORIES",
    "HILTestCase",
    "HILTestMatrix",
    "PILOT_EVIDENCE_STATUS_AVAILABLE",
    "PILOT_EVIDENCE_STATUS_BLOCKED",
    "PILOT_EVIDENCE_STATUS_PENDING",
    "PILOT_EVIDENCE_STATUS_TOKENS",
    "PILOT_READINESS_VERDICT_TOKENS",
    "PILOT_VERDICT_BLOCKED",
    "PILOT_VERDICT_NOT_READY",
    "PILOT_VERDICT_READY_FOR_LAB_SIMULATION",
    "PilotReadinessEvidenceItem",
    "PilotReadinessReview",
    "default_amax_hil_test_matrix",
    "default_amax_pilot_readiness_review",
    "diagnose_amax_pilot_readiness_review",
    "evaluate_amax_pilot_readiness_review",
]
