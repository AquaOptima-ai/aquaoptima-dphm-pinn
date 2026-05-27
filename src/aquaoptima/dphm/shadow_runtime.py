"""Shadow-mode runtime harness (Sprint 38).

Sprint 38 closes the read-only / offline shadow-mode loop opened by
Sprints 34-37. It is a *runtime harness* in the audit/reporting sense:
it consumes a Sprint 35 :class:`ShadowReplayDataset`, a caller-supplied
per-frame predictions sequence, an optional Sprint 37
:class:`AdvisoryContract` plus per-frame hypothetical proposals, and
emits a single typed :class:`ShadowRuntimeReport` recording, for every
replay frame in deterministic input order:

* the frame timestamp,
* per-axis observation and prediction counts,
* the Sprint 36 residuals attributable to that frame (no residual math
  is re-implemented — :func:`build_dpl_calibration_loss_report` is
  called exactly once over the whole replay),
* the Sprint 37 advisory decisions for that frame's hypothetical
  proposals (no setpoint emission — :func:`evaluate_advisory_proposals`
  is the only contract-side surface invoked).

Sprint 38 is **offline / read-only / no-write / no-control / no live
OT binding / no setpoint output / replay/audit only**. It contains:

* :class:`ShadowRuntimeDiagnostics` — deterministic warnings / errors
  tuples.
* :class:`ShadowRuntimeStepReport` — frozen per-frame report.
* :class:`ShadowRuntimeReport` — frozen top-level container.
* :func:`run_shadow_runtime` — pure deterministic harness driver.

Safety boundary (reaffirmed verbatim per Sprints 23-37):

* no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter is imported, registered, or polled;
* no write / control / setpoint path is exposed;
* no live OT binding is opened;
* no actuator / write surface is offered;
* no setpoint output is emitted;
* no automatic setpoint recommendation is produced — the Sprint 38
  harness only **audits hypothetical advisory proposals against a
  read-only contract** and **reports** dPL calibration loss against
  offline observations;
* no dPHM forward solve is invoked;
* no training loop / optimiser integration is performed;
* no ONNX / TensorRT / Jetson deployment is performed;
* no production savings / control claim is made.

Sprint 38 is **not** a live runtime, **not** a controller, and
**not** an advisory emission layer. A future live deployment would
need to add (out-of-scope) trust-boundary plumbing, a real adapter,
write authorisation, and operator-in-the-loop sign-off — none of
that lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from .advisory_contract import (
    ADVISORY_STATUS_ACCEPTED,
    AdvisoryContract,
    AdvisoryDecision,
    AdvisoryProposal,
    evaluate_advisory_proposals,
)
from .dpl_calibration import (
    DPL_AXES,
    DPLCalibrationLossReport,
    DPLResidual,
    build_dpl_calibration_loss_report,
)
from .shadow_replay import ShadowReplayDataset, ShadowReplayFrame


# Per-frame field names on :class:`ShadowReplayFrame` keyed by the
# canonical DPL axis token. Order matches :data:`DPL_AXES`.
_FRAME_FIELD_BY_AXIS: Mapping[str, str] = {
    "node_pressure": "node_pressure",
    "node_demand": "node_demand",
    "node_level": "node_level",
    "edge_flow": "edge_flow",
    "edge_pump_speed": "edge_pump_speed",
    "edge_power": "edge_power",
    "edge_valve_position": "edge_valve_position",
    "node_status": "node_status",
    "edge_status": "edge_status",
}


# ---------------------------------------------------------------------------
# Frozen dataclass surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShadowRuntimeDiagnostics:
    """Deterministic warnings / errors tuples for a shadow-runtime run.

    Both tuples are empty for a fully-valid input. Warnings are
    non-fatal observations (a proposal builder produced an empty list
    for a frame, an unused prediction axis); errors are structural
    problems (a proposal builder returned a non-sequence in
    non-strict mode, a per-frame proposal sequence had the wrong
    type).

    In ``strict=True`` mode the harness raises :class:`ValueError`
    instead of returning a populated ``errors`` tuple. Warnings are
    *always* returned through this surface.

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
class ShadowRuntimeStepReport:
    """Single-frame shadow-runtime step report.

    Carries the per-frame projection of the run's overall report:
    timestamp, observation / prediction axis counts, the residuals
    bound to this frame, the per-frame MSE / MAE summary restricted
    to axes that actually produced a residual, and the advisory
    decisions for any hypothetical proposals scoped to this frame.

    All collection fields are freshly allocated tuples / dicts on
    construction; the dataclass is frozen so the *binding* cannot be
    rewritten.

    Attributes
    ----------
    frame_index
        Zero-based index into ``replay.frames``.
    timestamp
        Whatever timestamp object the originating
        :class:`ShadowReplayFrame` carried — forwarded verbatim.
    observation_counts
        ``{axis_name -> number_of_observed_targets}`` restricted to
        axes that carry at least one observed target in this frame.
        Axis order follows :data:`DPL_AXES`.
    prediction_axes
        Deterministic tuple of axis tokens supplied in the prediction
        mapping for this frame. Sorted by :data:`DPL_AXES` order with
        any unsupported axes appended in ``sorted`` order.
    prediction_counts
        ``{axis_name -> number_of_predicted_targets}`` restricted to
        axes that the caller supplied. Axis order follows
        :data:`DPL_AXES` then alphabetical for unsupported axes.
    residuals
        Tuple of :class:`DPLResidual` records produced by Sprint 36
        whose ``frame_index`` equals this frame's index. Order is the
        Sprint 36 deterministic order (axis order from
        :data:`DPL_AXES`, then ascending ``target_id``).
    observation_count
        Number of residuals attributable to this frame. Equal to
        ``len(residuals)``.
    mse_by_axis
        Per-frame mean squared error per axis, restricted to axes
        that actually produced at least one residual in this frame.
    mae_by_axis
        Per-frame mean absolute error per axis, restricted to axes
        that actually produced at least one residual in this frame.
    advisory_decisions
        Deterministic tuple of :class:`AdvisoryDecision` records for
        the hypothetical proposals scoped to this frame. Empty when
        no contract / proposals are supplied or when no proposals
        target this frame.
    diagnostics
        Per-step :class:`ShadowRuntimeDiagnostics`. Step-local
        diagnostics are recorded here; run-level diagnostics are
        recorded on the :class:`ShadowRuntimeReport` instead.
    """

    frame_index: int
    timestamp: object
    observation_counts: Mapping[str, int] = field(default_factory=dict)
    prediction_axes: tuple[str, ...] = ()
    prediction_counts: Mapping[str, int] = field(default_factory=dict)
    residuals: tuple[DPLResidual, ...] = ()
    observation_count: int = 0
    mse_by_axis: Mapping[str, float] = field(default_factory=dict)
    mae_by_axis: Mapping[str, float] = field(default_factory=dict)
    advisory_decisions: tuple[AdvisoryDecision, ...] = ()
    diagnostics: ShadowRuntimeDiagnostics = field(
        default_factory=ShadowRuntimeDiagnostics
    )


@dataclass(frozen=True)
class ShadowRuntimeReport:
    """Frozen, read-only top-level shadow-runtime report.

    Returned by :func:`run_shadow_runtime`. Carries the per-frame
    step reports in replay order, the Sprint 36
    :class:`DPLCalibrationLossReport` for the whole run, the full
    flat advisory decisions tuple in deterministic order (frame
    order, then per-frame input order), and a few aggregate counts.

    Attributes
    ----------
    steps
        Tuple of :class:`ShadowRuntimeStepReport` records, one per
        replay frame, in replay order.
    loss_report
        Sprint 36 :class:`DPLCalibrationLossReport` produced for the
        whole replay. Carries the full residual tuple, per-axis MSE
        / MAE, and the weighted MSE.
    advisory_decisions
        Flat deterministic tuple of every
        :class:`AdvisoryDecision` produced across all frames.
        Ordering: outer key is the replay frame index, inner key is
        the per-frame proposal input order.
    frame_count
        ``len(steps)``. Equal to ``len(replay.frames)``.
    observation_count
        Total number of residuals across the run. Equal to
        ``loss_report.observation_count``.
    proposal_count
        Total number of advisory decisions across the run. Equal to
        ``len(advisory_decisions)``.
    accepted_count
        Number of advisory decisions whose ``status`` is
        ``ADVISORY_STATUS_ACCEPTED``.
    rejected_count
        Number of advisory decisions whose ``status`` is
        ``ADVISORY_STATUS_REJECTED``.
    diagnostics
        Run-level :class:`ShadowRuntimeDiagnostics`.
    """

    steps: tuple[ShadowRuntimeStepReport, ...] = ()
    loss_report: DPLCalibrationLossReport = field(
        default_factory=DPLCalibrationLossReport
    )
    advisory_decisions: tuple[AdvisoryDecision, ...] = ()
    frame_count: int = 0
    observation_count: int = 0
    proposal_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    diagnostics: ShadowRuntimeDiagnostics = field(
        default_factory=ShadowRuntimeDiagnostics
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Caller-facing proposal-source callback type.
ProposalBuilder = Callable[
    [int, ShadowReplayFrame], Sequence[AdvisoryProposal]
]


def _observation_counts(frame: ShadowReplayFrame) -> dict[str, int]:
    """Return ``{axis_name -> count}`` restricted to non-empty axes.

    Axis order follows :data:`DPL_AXES`.
    """
    counts: dict[str, int] = {}
    for axis in DPL_AXES:
        field_name = _FRAME_FIELD_BY_AXIS[axis]
        mapping = getattr(frame, field_name)
        if mapping:
            counts[axis] = len(mapping)
    return counts


def _prediction_axis_summary(
    prediction: Mapping[str, Mapping[int, float]],
) -> tuple[tuple[str, ...], dict[str, int]]:
    """Return ``(prediction_axes, prediction_counts)`` for a frame.

    Deterministic order: :data:`DPL_AXES` first, then unsupported
    axes in ``sorted`` order. Unsupported axes are still surfaced
    (Sprint 38 reports the shape of the caller's prediction surface
    — it does not silently drop unknown axes here, the Sprint 36
    builder is the one that classifies them as warnings).
    """
    axes: list[str] = []
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for axis in DPL_AXES:
        if axis in prediction:
            axis_map = prediction.get(axis, {})
            if isinstance(axis_map, Mapping):
                axes.append(axis)
                counts[axis] = len(axis_map)
                seen.add(axis)
    extras = sorted(k for k in prediction.keys() if k not in seen)
    for axis in extras:
        axis_map = prediction.get(axis, {})
        if isinstance(axis_map, Mapping):
            axes.append(axis)
            counts[axis] = len(axis_map)
    return tuple(axes), counts


def _validate_proposal_builder_result(
    result: object, frame_index: int
) -> tuple[list[AdvisoryProposal], str | None]:
    """Validate the return value of a proposal builder callback.

    Returns ``(proposals, error)``. Strings / bytes are rejected;
    non-sequence objects are rejected; ``None`` is treated as an
    empty list.
    """
    if result is None:
        return [], None
    if isinstance(result, (str, bytes)):
        return (
            [],
            f"proposal_builder for frame[{frame_index}] returned a string; "
            f"expected a Sequence[AdvisoryProposal]",
        )
    if not isinstance(result, Sequence):
        return (
            [],
            f"proposal_builder for frame[{frame_index}] returned "
            f"{type(result).__name__}; expected a Sequence[AdvisoryProposal]",
        )
    return list(result), None


def _proposals_by_frame_for(
    proposals_by_frame: Sequence[Sequence[AdvisoryProposal]] | None,
    frame_index: int,
    frame_count: int,
) -> tuple[list[AdvisoryProposal], str | None]:
    """Resolve the per-frame proposals from a ``proposals_by_frame``."""
    if proposals_by_frame is None:
        return [], None
    if frame_index >= len(proposals_by_frame):
        return (
            [],
            f"proposals_by_frame has length {len(proposals_by_frame)} but "
            f"replay carries {frame_count} frames; frame[{frame_index}] "
            f"has no proposal entry",
        )
    entry = proposals_by_frame[frame_index]
    if entry is None:
        return [], None
    if isinstance(entry, (str, bytes)):
        return (
            [],
            f"proposals_by_frame[{frame_index}] is a string; expected a "
            f"Sequence[AdvisoryProposal]",
        )
    if not isinstance(entry, Sequence):
        return (
            [],
            f"proposals_by_frame[{frame_index}] is "
            f"{type(entry).__name__}; expected a Sequence[AdvisoryProposal]",
        )
    return list(entry), None


# ---------------------------------------------------------------------------
# Public harness driver
# ---------------------------------------------------------------------------


def run_shadow_runtime(
    replay: ShadowReplayDataset,
    predictions: Sequence[Mapping[str, Mapping[int, float]]],
    *,
    advisory_contract: AdvisoryContract | None = None,
    proposal_builder: ProposalBuilder | None = None,
    proposals_by_frame: Sequence[Sequence[AdvisoryProposal]] | None = None,
    axis_weights: Mapping[str, float] | None = None,
    strict: bool = True,
) -> ShadowRuntimeReport:
    """Run the shadow-mode runtime harness over a replay dataset.

    The harness is **pure**, **offline**, **read-only**, **no-write**,
    **no-control**:

    * never mutates ``replay``, ``predictions``, ``advisory_contract``,
      or any caller-supplied proposal sequence;
    * never opens a socket / process / live OT binding;
    * never returns a write or control surface;
    * never invokes the dPHM forward solver;
    * never emits a setpoint, never publishes, never contacts an
      external system;
    * never writes to the filesystem.

    Sprint 38 is **not** a live runtime, **not** a controller, and
    **not** an advisory emission layer. The decisions returned in
    :attr:`ShadowRuntimeReport.advisory_decisions` are *advisory
    proposal audit only* — even an accepted decision is *never*
    transformed into a setpoint write here.

    Parameters
    ----------
    replay
        Sprint 35 :class:`ShadowReplayDataset` whose frames carry the
        canonicalised observation maps.
    predictions
        Sequence of mappings — one per replay frame, in the same
        order. Each entry maps an axis token (e.g.
        ``"node_pressure"``) to a ``{target_id: value}`` sub-mapping
        carrying the supplied predicted values in the *same canonical
        units* as the observations. Forwarded verbatim to
        :func:`build_dpl_calibration_loss_report`.
    advisory_contract
        Optional Sprint 37 :class:`AdvisoryContract`. When supplied
        alongside a ``proposal_builder`` or ``proposals_by_frame``,
        per-frame proposals are audited against the contract via
        :func:`evaluate_advisory_proposals`. When omitted, all
        :attr:`ShadowRuntimeStepReport.advisory_decisions` tuples are
        empty.
    proposal_builder
        Optional callback ``(frame_index, frame) -> Sequence[
        AdvisoryProposal]`` that yields the hypothetical proposals to
        audit for each frame. Returning ``None`` or an empty sequence
        means "no proposals this frame".
    proposals_by_frame
        Optional alternative to ``proposal_builder``: a sequence of
        per-frame proposal sequences, indexed by frame number. Mutually
        exclusive with ``proposal_builder`` — supplying both raises
        :class:`ValueError`. Shorter sequences (fewer entries than
        replay frames) raise in strict mode; in non-strict mode the
        missing trailing frames record a deterministic error string
        and produce no advisory decisions.
    axis_weights
        Optional ``{axis: weight}`` mapping forwarded verbatim to
        :func:`build_dpl_calibration_loss_report`. Sprint 36 validates
        the mapping; invalid weights always raise (this is a
        programmer error and is not gated by ``strict``).
    strict
        When ``True`` (default), structural input errors raise
        :class:`ValueError` (length mismatches, malformed proposal
        builder return, malformed proposals_by_frame entry, both
        proposal sources supplied). When ``False``, the offending
        proposal source is treated as empty for the affected frame
        and an error string is appended to
        :attr:`ShadowRuntimeDiagnostics.errors`. Sprint 36 / 37
        ``strict`` semantics are forwarded as-is for the downstream
        loss report / proposal evaluator.

    Returns
    -------
    ShadowRuntimeReport
        Frozen, immutable report. Frames in :attr:`steps` are in
        replay order; advisory decisions in
        :attr:`advisory_decisions` are deterministically ordered
        (frame order, then per-frame input order).

    Raises
    ------
    ValueError
        See ``strict``. Type-check raises also fire (``replay`` must
        be a :class:`ShadowReplayDataset`; ``advisory_contract`` must
        be an :class:`AdvisoryContract` when supplied;
        ``proposal_builder`` must be callable; ``proposals_by_frame``
        must be a :class:`Sequence`).
    """
    if not isinstance(replay, ShadowReplayDataset):
        raise ValueError(
            f"replay must be a ShadowReplayDataset, got "
            f"{type(replay).__name__}"
        )
    if advisory_contract is not None and not isinstance(
        advisory_contract, AdvisoryContract
    ):
        raise ValueError(
            f"advisory_contract must be an AdvisoryContract or None, got "
            f"{type(advisory_contract).__name__}"
        )
    if proposal_builder is not None and proposals_by_frame is not None:
        raise ValueError(
            "supply at most one of proposal_builder / proposals_by_frame; "
            "both were provided"
        )
    if proposal_builder is not None and not callable(proposal_builder):
        raise ValueError(
            f"proposal_builder must be callable, got "
            f"{type(proposal_builder).__name__}"
        )
    if proposals_by_frame is not None:
        if isinstance(proposals_by_frame, (str, bytes)):
            raise ValueError(
                "proposals_by_frame must be a Sequence, not a string"
            )
        if not isinstance(proposals_by_frame, Sequence):
            raise ValueError(
                f"proposals_by_frame must be a Sequence, got "
                f"{type(proposals_by_frame).__name__}"
            )

    warnings: list[str] = []
    errors: list[str] = []

    # ---- Sprint 36 calibration loss report ------------------------------
    # This call is the *only* residual math invoked by Sprint 38.
    loss_report = build_dpl_calibration_loss_report(
        replay,
        predictions,
        axis_weights=axis_weights,
        strict=strict,
    )

    # Index residuals by frame for fast per-step lookup. Sprint 36
    # already emits residuals in deterministic order; we preserve it.
    residuals_by_frame: dict[int, list[DPLResidual]] = {}
    for residual in loss_report.residuals:
        residuals_by_frame.setdefault(residual.frame_index, []).append(residual)

    # Length-check predictions for the prediction-axes column. In
    # non-strict mode Sprint 36 may have absorbed a length mismatch
    # into its diagnostics; for the step-report shape we treat a
    # missing prediction as an empty mapping for that frame.
    predictions_list: list[Mapping[str, Mapping[int, float]]] = list(predictions)

    # ---- Proposal source resolution ------------------------------------
    frame_count = len(replay.frames)
    if (
        proposals_by_frame is not None
        and len(proposals_by_frame) != frame_count
    ):
        msg = (
            f"proposals_by_frame length {len(proposals_by_frame)} does not "
            f"match replay frame count {frame_count}"
        )
        if strict:
            raise ValueError(msg)
        warnings.append(msg)

    # Eagerly resolve per-frame proposal lists so we can run a single
    # batched advisory evaluation per frame and capture the decisions
    # both per-step and in the flat run-level tuple.
    per_frame_proposals: list[list[AdvisoryProposal]] = []
    for frame_index, frame in enumerate(replay.frames):
        proposals: list[AdvisoryProposal] = []
        builder_err: str | None = None

        if proposal_builder is not None:
            try:
                raw_result = proposal_builder(frame_index, frame)
            except Exception as exc:  # noqa: BLE001 — surface as deterministic error
                builder_err = (
                    f"proposal_builder raised "
                    f"{type(exc).__name__} for frame[{frame_index}]: {exc}"
                )
                raw_result = None
            if builder_err is None:
                proposals, builder_err = _validate_proposal_builder_result(
                    raw_result, frame_index
                )
        elif proposals_by_frame is not None:
            proposals, builder_err = _proposals_by_frame_for(
                proposals_by_frame, frame_index, frame_count
            )

        if builder_err is not None:
            if strict:
                raise ValueError(builder_err)
            errors.append(builder_err)
            proposals = []

        per_frame_proposals.append(proposals)

    # ---- Per-frame advisory evaluation ---------------------------------
    flat_decisions: list[AdvisoryDecision] = []
    per_frame_decisions: list[tuple[AdvisoryDecision, ...]] = []

    if advisory_contract is not None:
        for frame_index, proposals in enumerate(per_frame_proposals):
            if not proposals:
                per_frame_decisions.append(())
                continue
            decisions = evaluate_advisory_proposals(
                advisory_contract,
                proposals,
                loss_report=loss_report,
                strict=strict,
            )
            per_frame_decisions.append(decisions)
            flat_decisions.extend(decisions)
    else:
        # No contract → no decisions, but record a warning if the
        # caller supplied proposals without a contract.
        any_proposals = any(p for p in per_frame_proposals)
        if any_proposals:
            warnings.append(
                "advisory proposals were supplied but no advisory_contract "
                "was provided; proposals were ignored (advisory proposal "
                "audit only — no setpoint output)"
            )
        per_frame_decisions = [() for _ in per_frame_proposals]

    # ---- Per-frame step reports ----------------------------------------
    steps: list[ShadowRuntimeStepReport] = []
    for frame_index, frame in enumerate(replay.frames):
        observation_counts = _observation_counts(frame)
        if frame_index < len(predictions_list):
            prediction = predictions_list[frame_index]
            if isinstance(prediction, Mapping):
                prediction_axes, prediction_counts = _prediction_axis_summary(
                    prediction
                )
            else:
                prediction_axes = ()
                prediction_counts = {}
        else:
            prediction_axes = ()
            prediction_counts = {}

        frame_residuals = tuple(residuals_by_frame.get(frame_index, ()))
        sum_sq: dict[str, float] = {}
        sum_abs: dict[str, float] = {}
        count_by_axis: dict[str, int] = {}
        for r in frame_residuals:
            sum_sq[r.axis] = sum_sq.get(r.axis, 0.0) + r.residual ** 2
            sum_abs[r.axis] = sum_abs.get(r.axis, 0.0) + abs(r.residual)
            count_by_axis[r.axis] = count_by_axis.get(r.axis, 0) + 1
        mse_by_axis: dict[str, float] = {}
        mae_by_axis: dict[str, float] = {}
        for axis in DPL_AXES:
            n = count_by_axis.get(axis, 0)
            if n == 0:
                continue
            mse_by_axis[axis] = sum_sq[axis] / n
            mae_by_axis[axis] = sum_abs[axis] / n

        decisions = per_frame_decisions[frame_index]

        step = ShadowRuntimeStepReport(
            frame_index=frame_index,
            timestamp=frame.timestamp,
            observation_counts=dict(observation_counts),
            prediction_axes=tuple(prediction_axes),
            prediction_counts=dict(prediction_counts),
            residuals=frame_residuals,
            observation_count=len(frame_residuals),
            mse_by_axis=mse_by_axis,
            mae_by_axis=mae_by_axis,
            advisory_decisions=tuple(decisions),
            diagnostics=ShadowRuntimeDiagnostics(),
        )
        steps.append(step)

    accepted = sum(
        1 for d in flat_decisions if d.status == ADVISORY_STATUS_ACCEPTED
    )
    rejected = len(flat_decisions) - accepted

    diagnostics = ShadowRuntimeDiagnostics(
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    return ShadowRuntimeReport(
        steps=tuple(steps),
        loss_report=loss_report,
        advisory_decisions=tuple(flat_decisions),
        frame_count=len(steps),
        observation_count=loss_report.observation_count,
        proposal_count=len(flat_decisions),
        accepted_count=accepted,
        rejected_count=rejected,
        diagnostics=diagnostics,
    )


__all__ = [
    "ShadowRuntimeDiagnostics",
    "ShadowRuntimeReport",
    "ShadowRuntimeStepReport",
    "run_shadow_runtime",
]
