"""Deterministic seeding for dPHM training (AOPSO Sprint 24).

Seeds Python's ``random``, NumPy, and PyTorch, and forces cuDNN into a
deterministic, non-benchmarking mode so that two identical-seed CPU runs are
bitwise reproducible (a Sprint 24 acceptance criterion).

Safety: offline only, no I/O beyond reading the optional seed-config JSON, no
edge imports.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import numpy as np
import torch

__all__ = ["set_deterministic_seed", "load_seed_config", "DEFAULT_SEED"]

DEFAULT_SEED = 42


def set_deterministic_seed(
    torch_seed: int = DEFAULT_SEED,
    numpy_seed: int = DEFAULT_SEED,
    random_seed: int = DEFAULT_SEED,
) -> dict:
    """Seed all RNGs and force deterministic cuDNN. Returns the seeds used."""
    random.seed(random_seed)
    np.random.seed(numpy_seed)
    torch.manual_seed(torch_seed)
    if torch.cuda.is_available():  # pragma: no cover - CPU CI
        torch.cuda.manual_seed_all(torch_seed)

    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    # Make hashing deterministic for any dict-order-sensitive paths.
    os.environ.setdefault("PYTHONHASHSEED", str(random_seed))
    return {
        "torch_seed": torch_seed,
        "numpy_seed": numpy_seed,
        "random_seed": random_seed,
    }


def load_seed_config(path: str | os.PathLike[str]) -> dict:
    """Load a ``seed_config.json`` ({torch_seed, numpy_seed, random_seed})."""
    cfg = json.loads(Path(path).read_text())
    return {
        "torch_seed": int(cfg.get("torch_seed", DEFAULT_SEED)),
        "numpy_seed": int(cfg.get("numpy_seed", DEFAULT_SEED)),
        "random_seed": int(cfg.get("random_seed", DEFAULT_SEED)),
    }
