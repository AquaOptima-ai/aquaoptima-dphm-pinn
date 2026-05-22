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
    """Per-step training record store.

    Sprint 7 adds optional ``elapsed_seconds`` and ``batch_size`` fields
    that callers can stamp on the metrics container before serialising
    the :meth:`summary`. These travel through unchanged from
    :func:`aquaoptima.training.train.train_loop` /
    :func:`run_ablation` so downstream tooling can compare runs at
    different batch sizes without re-running training.
    """

    history: list[dict[str, float]] = field(default_factory=list)
    elapsed_seconds: float | None = None
    batch_size: int | None = None

    def record(self, record: dict[str, float]) -> None:
        self.history.append(dict(record))

    @property
    def num_iterations(self) -> int:
        return len(self.history)

    def summary(self) -> dict[str, float]:
        """Compact summary dict for logging / assertions."""
        if not self.history:
            base: dict[str, float] = {"num_iterations": 0}
            if self.elapsed_seconds is not None:
                base["elapsed_seconds"] = float(self.elapsed_seconds)
            if self.batch_size is not None:
                base["batch_size"] = float(self.batch_size)
            return base
        last = self.history[-1]
        first = self.history[0]
        out: dict[str, float] = {
            "num_iterations": float(len(self.history)),
            "final_total": float(last.get("loss_total", math.nan)),
            "final_data": float(last.get("loss_data", math.nan)),
            "final_physics": float(last.get("loss_physics", math.nan)),
            "final_lambda_physics": float(last.get("lambda_physics", math.nan)),
            "initial_lambda_physics": float(first.get("lambda_physics", math.nan)),
        }
        if self.elapsed_seconds is not None:
            out["elapsed_seconds"] = float(self.elapsed_seconds)
        if self.batch_size is not None:
            out["batch_size"] = float(self.batch_size)
        return out


__all__ = ["TrainingMetrics"]
