"""Lambda schedulers for composite loss weighting.

A scheduler maps integer training step → non-negative scalar weight.
Two shapes are supported in Sprint 4:

* :class:`FixedLambda` — constant value, regardless of step.
* :class:`LinearRampLambda` — linear interpolation from ``start`` to
  ``end`` across the first ``ramp_steps`` steps, then clamped at
  ``end`` forever after.

A small dict-driven factory :func:`make_scheduler` keeps configs out
of imports and lets the ablation harness select between the two
without if/else ladders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class LambdaScheduler:
    """Protocol-like base — exposes ``value(step) -> float``."""

    def value(self, step: int) -> float:  # pragma: no cover - interface only
        raise NotImplementedError


@dataclass
class FixedLambda(LambdaScheduler):
    """Constant lambda; ``value(step)`` is always the same."""

    constant: float

    def __post_init__(self) -> None:
        if self.constant < 0.0:
            raise ValueError(
                f"FixedLambda value must be non-negative, got {self.constant}"
            )

    def value(self, step: int) -> float:
        return float(self.constant)


@dataclass
class LinearRampLambda(LambdaScheduler):
    """Linear ramp from ``start`` to ``end`` across ``ramp_steps`` steps."""

    start: float
    end: float
    ramp_steps: int

    def __post_init__(self) -> None:
        if self.start < 0.0 or self.end < 0.0:
            raise ValueError(
                f"start and end must be non-negative, got start={self.start}, "
                f"end={self.end}"
            )
        if self.ramp_steps <= 0:
            raise ValueError(
                f"ramp_steps must be positive, got {self.ramp_steps}"
            )

    def value(self, step: int) -> float:
        if step <= 0:
            return float(self.start)
        if step >= self.ramp_steps:
            return float(self.end)
        frac = step / self.ramp_steps
        return float(self.start + frac * (self.end - self.start))


def make_scheduler(config: Mapping[str, Any]) -> LambdaScheduler:
    """Build a scheduler from a ``{"kind": ..., ...}`` config dict."""
    kind = config.get("kind")
    if kind == "fixed":
        return FixedLambda(constant=float(config["value"]))
    if kind == "linear":
        return LinearRampLambda(
            start=float(config["start"]),
            end=float(config["end"]),
            ramp_steps=int(config["ramp_steps"]),
        )
    raise ValueError(f"unknown lambda scheduler kind: {kind!r}")


__all__ = [
    "FixedLambda",
    "LambdaScheduler",
    "LinearRampLambda",
    "make_scheduler",
]
