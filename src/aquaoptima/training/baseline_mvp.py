"""MVP v1 persistence baseline predictor (AOPSO Sprint 25).

The incumbent "MVP v1" behaviour is modelled as a **persistence / last-observed
-value** predictor: the prediction for the next step is simply the last value of
the input window. This is the honest naive baseline the trained dPHM model must
beat to justify packaging.

It is scored on the *identical* holdout windows as the dPHM model (same gap-aware
windowing, same normalization stats, same canonical axis map), so the per-axis
MSE/MAE/accuracy comparison is apples-to-apples.

Mechanics
---------
``YilanTimeSeriesDataset`` yields ``(x, y)`` where ``x`` is a normalized
``[window, n_axes]`` window and ``y`` is the normalized next-step target. The
persistence prediction for axis ``j`` is ``x[-1, j]`` (last observed normalized
value). No parameters, no training, deterministic.

Safety: offline only; pure numpy over already-normalized windows. No edge
imports, no ONNX, no control influence.
"""

from __future__ import annotations

import numpy as np

__all__ = ["persistence_predict", "PERSISTENCE_NAME"]

PERSISTENCE_NAME = "mvp_persistence"


def persistence_predict(x_window: np.ndarray) -> np.ndarray:
    """Predict the next step as the last observed step of the window.

    Parameters
    ----------
    x_window
        Normalized input window, shape ``[..., window, n_axes]``. Accepts a
        single window ``[window, n_axes]`` or a batch ``[B, window, n_axes]``.

    Returns
    -------
    np.ndarray
        The last timestep along the window axis: ``[..., n_axes]``.
    """
    arr = np.asarray(x_window, dtype=float)
    if arr.ndim < 2:
        raise ValueError(
            f"expected at least [window, n_axes], got shape {arr.shape}"
        )
    # Window axis is the second-to-last dimension.
    return arr[..., -1, :]
