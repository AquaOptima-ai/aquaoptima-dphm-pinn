"""Authority gate: who is allowed to drive a setpoint, in what mode.

The gate is the single chokepoint that turns a :class:`ControlIntent`
into an :class:`AuthorityGateDecision`.  It enforces:

- runtime mode rules (e.g. learners are observe-only in
  ``baseline_plus_learning_shadow``);
- safety config flags (``baseline_control_enabled``,
  ``future_control_enabled``, frequency bounds);
- pump-state interlocks (manual mode, trips);
- quality-engine blocks (the gate refuses learner / console writes
  whenever the quality engine has blocked the advisory path).

No learner / console / future supervisory path may bypass this gate —
that is the central invariant of Optimizer Lite.
"""

from __future__ import annotations

from typing import List

from ..config.models import SiteConfig
from .models import AuthorityGateDecision, ControlIntent, QualityDecision, StationSnapshot
from .modes import RuntimeMode
from .reason_codes import ReasonCode


def _block(source: str, reasons: List[str]) -> AuthorityGateDecision:
    return AuthorityGateDecision(
        decision="block",
        reason_codes=tuple(reasons),
        source=source,
        write_allowed=False,
    )


def _observe(source: str, reasons: List[str]) -> AuthorityGateDecision:
    return AuthorityGateDecision(
        decision="observe_only",
        reason_codes=tuple(reasons),
        source=source,
        write_allowed=False,
    )


def _allow(source: str, reasons: List[str]) -> AuthorityGateDecision:
    return AuthorityGateDecision(
        decision="allow",
        reason_codes=tuple(reasons),
        source=source,
        write_allowed=True,
    )


def _frequency_out_of_bounds(intent: ControlIntent, config: SiteConfig) -> bool:
    if intent.target_frequency_hz is None:
        return False
    return (
        intent.target_frequency_hz < config.safety.min_frequency_hz
        or intent.target_frequency_hz > config.safety.max_frequency_hz
    )


def evaluate_authority(
    snapshot: StationSnapshot,
    quality: QualityDecision,
    proposal: ControlIntent,
    config: SiteConfig,
) -> AuthorityGateDecision:
    """Decide whether ``proposal`` may write a setpoint under ``snapshot``."""

    source = proposal.source
    reasons: List[str] = []
    mode = snapshot.mode

    # Frequency bounds apply to every source that proposes a setpoint.
    if proposal.write_requested and _frequency_out_of_bounds(proposal, config):
        reasons.append(ReasonCode.FREQUENCY_OUT_OF_BOUNDS.value)
        return _block(source, reasons)

    if source == "none":
        # No proposal — nothing to gate; everything observes.
        return _observe(source, reasons)

    if source == "baseline_mvp":
        if mode not in (
            RuntimeMode.BASELINE_CONTROL.value,
            RuntimeMode.BASELINE_PLUS_LEARNING_SHADOW.value,
        ):
            reasons.append(ReasonCode.SOURCE_NOT_ALLOWED_IN_MODE.value)
            return _block(source, reasons)
        if not config.safety.baseline_control_enabled:
            reasons.append(ReasonCode.BASELINE_CONTROL_DISABLED.value)
            return _block(source, reasons)
        if snapshot.manual_mode:
            reasons.append(ReasonCode.MANUAL_MODE_ACTIVE.value)
            return _block(source, reasons)
        if config.safety.block_on_any_trip and any(
            p.trip_active for p in snapshot.pumps
        ):
            reasons.append(ReasonCode.PUMP_TRIP_ACTIVE.value)
            return _block(source, reasons)
        return _allow(source, reasons)

    if source == "learner":
        if quality.blocked_for_advisory:
            reasons.extend(quality.reason_codes)
            return _block(source, reasons)

        if mode == RuntimeMode.MONITOR_ONLY.value:
            reasons.append(ReasonCode.SOURCE_NOT_ALLOWED_IN_MODE.value)
            return _block(source, reasons)

        if mode == RuntimeMode.BASELINE_CONTROL.value:
            # Pure baseline mode: learner is not active.
            reasons.append(ReasonCode.SOURCE_NOT_ALLOWED_IN_MODE.value)
            return _block(source, reasons)

        if mode == RuntimeMode.BASELINE_PLUS_LEARNING_SHADOW.value:
            # Shadow learner: never allowed to write, only to observe.
            if proposal.write_requested:
                reasons.append(ReasonCode.SOURCE_NOT_ALLOWED_IN_MODE.value)
                return _block(source, reasons)
            return _observe(source, reasons)

        if mode == RuntimeMode.LEARNED_ADVISORY.value:
            # Advisory mode: learner produces evidence, no setpoint writes.
            if proposal.write_requested:
                reasons.append(ReasonCode.SOURCE_NOT_ALLOWED_IN_MODE.value)
                return _block(source, reasons)
            return _observe(source, reasons)

        if mode == RuntimeMode.LEARNED_SUPERVISORY_CONTROL.value:
            if not config.safety.future_control_enabled:
                reasons.append(ReasonCode.FUTURE_CONTROL_DISABLED.value)
                return _block(source, reasons)
            if quality.blocked_for_future_control:
                reasons.extend(quality.reason_codes)
                return _block(source, reasons)
            if not proposal.write_requested:
                return _observe(source, reasons)
            return _allow(source, reasons)

        reasons.append(ReasonCode.SOURCE_NOT_ALLOWED_IN_MODE.value)
        return _block(source, reasons)

    if source == "console":
        # The Operations Console is always observe-only in this sprint.
        # It must never bypass quality blocks even for observation hints.
        if quality.blocked_for_advisory:
            reasons.extend(quality.reason_codes)
            return _block(source, reasons)
        if proposal.write_requested:
            reasons.append(ReasonCode.SOURCE_NOT_ALLOWED_IN_MODE.value)
            return _block(source, reasons)
        return _observe(source, reasons)

    reasons.append(ReasonCode.SOURCE_NOT_ALLOWED_IN_MODE.value)
    return _block(source, reasons)
