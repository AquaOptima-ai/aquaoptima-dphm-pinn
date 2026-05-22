"""Sprint 4 training package: loop, metrics, ablations."""

from .ablations import ABLATION_MODES, run_ablation
from .metrics import TrainingMetrics
from .train import TrainConfig, train_loop, train_step

__all__ = [
    "ABLATION_MODES",
    "TrainConfig",
    "TrainingMetrics",
    "run_ablation",
    "train_loop",
    "train_step",
]
