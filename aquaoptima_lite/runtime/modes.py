"""Runtime modes for Optimizer Lite.

The mode determines who is allowed to drive frequency setpoints at the
authority gate.  Baseline PLC/PAC control is preserved in
``baseline_control`` and ``baseline_plus_learning_shadow``; the learner
is observe-only until at least ``learned_advisory``; and the future
``learned_supervisory_control`` mode is gated off by
``SafetyConfig.future_control_enabled``.
"""

from __future__ import annotations

from enum import Enum


class RuntimeMode(str, Enum):
    #: No control writes from any source; only telemetry.
    MONITOR_ONLY = "monitor_only"

    #: Existing MVP-style PLC/PAC output remains allowed if commissioned.
    BASELINE_CONTROL = "baseline_control"

    #: Baseline PLC/PAC retains authority; learner runs observe-only.
    BASELINE_PLUS_LEARNING_SHADOW = "baseline_plus_learning_shadow"

    #: Learner emits advisory evidence to the console; no direct writes.
    LEARNED_ADVISORY = "learned_advisory"

    #: Future supervisory mode; blocked unless ``future_control_enabled``.
    LEARNED_SUPERVISORY_CONTROL = "learned_supervisory_control"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(m.value for m in cls)

    @classmethod
    def from_string(cls, value: str) -> "RuntimeMode":
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(
                f"unknown runtime mode {value!r}; expected one of {cls.values()!r}"
            ) from exc
