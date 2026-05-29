"""Lightweight training-metrics container.

The training loop appends per-step dicts onto :class:`TrainingMetrics`.
The container exposes the raw history plus a small :meth:`summary`
helper so callers (and tests) can pull a stable shape without
recomputing aggregates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


def binary_classification_metrics(
    y_true: "np.ndarray", y_pred: "np.ndarray"
) -> dict[str, float]:
    """Imbalance-aware binary metrics (AOPSO Sprint 26, DEFECT 2 fix).

    Computes raw accuracy, **balanced accuracy**, **F1**, plus the confusion
    counts, from already-thresholded integer 0/1 class arrays. Raw accuracy is
    meaningless on the 99.85%-imbalanced pump status (always-on scores 0.9985),
    so the acceptance gate uses balanced accuracy / F1 from here.

    Balanced accuracy = mean(sensitivity, specificity); a do-nothing always-on
    (or always-off) predictor scores 0.5. F1 = harmonic mean of precision and
    recall. Degenerate cases (no positives or no negatives in ``y_true``) are
    handled so the metric stays finite.
    """
    yt = np.asarray(y_true).astype(int).ravel()
    yp = np.asarray(y_pred).astype(int).ravel()
    if yt.size == 0:
        return {
            "accuracy": float("nan"),
            "balanced_accuracy": float("nan"),
            "f1": float("nan"),
            "tp": 0,
            "tn": 0,
            "fp": 0,
            "fn": 0,
            "n": 0,
        }
    tp = int(np.sum((yt == 1) & (yp == 1)))
    tn = int(np.sum((yt == 0) & (yp == 0)))
    fp = int(np.sum((yt == 0) & (yp == 1)))
    fn = int(np.sum((yt == 1) & (yp == 0)))

    accuracy = (tp + tn) / yt.size

    # Sensitivity (recall on positives) and specificity (recall on negatives).
    pos = tp + fn
    neg = tn + fp
    # If a class is absent, its recall is undefined; balanced accuracy then
    # reduces to the recall of the present class (single-class fallback).
    recalls = []
    if pos > 0:
        recalls.append(tp / pos)
    if neg > 0:
        recalls.append(tn / neg)
    balanced_accuracy = float(np.mean(recalls)) if recalls else float("nan")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / pos if pos > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "accuracy": float(accuracy),
        "balanced_accuracy": float(balanced_accuracy),
        "f1": float(f1),
        "precision": float(precision),
        "recall": float(recall),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "n": int(yt.size),
    }


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


__all__ = ["TrainingMetrics", "binary_classification_metrics"]
