"""Sprint 4 training package: loop, metrics, ablations."""

from .ablations import ABLATION_MODES, run_ablation
from .metrics import TrainingMetrics
from .train import (
    TrainConfig,
    make_window_dataloader,
    train_loop,
    train_loop_dataloader,
    train_step,
)

__all__ = [
    "ABLATION_MODES",
    "TrainConfig",
    "TrainingMetrics",
    "make_window_dataloader",
    "run_ablation",
    "train_loop",
    "train_loop_dataloader",
    "train_step",
]
