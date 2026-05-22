"""Lightweight training-metrics container.

The training loop appends per-step dicts onto :class:`TrainingMetrics`.
The container exposes the raw history plus a small :meth:`summary`
helper so callers (and tests) can pull a stable shape without
recomputing aggregates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class TrainingMetrics:
    """Per-step training record store."""

    history: list[dict[str, float]] = field(default_factory=list)

    def record(self, record: dict[str, float]) -> None:
        self.history.append(dict(record))

    @property
    def num_iterations(self) -> int:
        return len(self.history)

    def summary(self) -> dict[str, float]:
        """Compact summary dict for logging / assertions."""
        if not self.history:
            return {"num_iterations": 0}
        last = self.history[-1]
        first = self.history[0]
        return {
            "num_iterations": float(len(self.history)),
            "final_total": float(last.get("loss_total", math.nan)),
            "final_data": float(last.get("loss_data", math.nan)),
            "final_physics": float(last.get("loss_physics", math.nan)),
            "final_lambda_physics": float(last.get("lambda_physics", math.nan)),
            "initial_lambda_physics": float(first.get("lambda_physics", math.nan)),
        }


__all__ = ["TrainingMetrics"]
