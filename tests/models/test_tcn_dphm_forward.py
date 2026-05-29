"""Forward-pass tests for TCN_DPHM (AOPSO Sprint 24).

Dims are derived from the real Sprint 23 normalization-stats contract (8 active
axes), so the model is [B, window, 8] -> [B, 8]. We assert shape, positive
param count, and no-NaN on random input.
"""

from __future__ import annotations

import json
from pathlib import Path

import torch

from aquaoptima.models.tcn_dphm import TCN_DPHM

REPO = Path(__file__).resolve().parents[2]
NORM_STATS = REPO / "data" / "normalization" / "yilan_2025_train_stats.json"


def _load_stats() -> dict:
    return json.loads(NORM_STATS.read_text())


def test_forward_shape_b_window_nfeat_to_b8():
    stats = _load_stats()
    n = len(stats["active_axes"])
    assert n == 8, f"expected 8 active axes (reality), got {n}"

    model = TCN_DPHM.from_norm_stats(stats)
    assert model.n_features == 8
    assert model.n_axes == 8

    B, window = 16, 10
    x = torch.randn(B, window, model.n_features)
    out = model(x)
    assert tuple(out.shape) == (B, 8), f"output shape {tuple(out.shape)} != (16, 8)"


def test_param_count_positive():
    stats = _load_stats()
    model = TCN_DPHM.from_norm_stats(stats)
    assert model.param_count() > 0


def test_no_nan_on_random_input():
    stats = _load_stats()
    model = TCN_DPHM.from_norm_stats(stats)
    for _ in range(5):
        x = torch.randn(8, 10, model.n_features)
        out = model(x)
        assert not torch.isnan(out).any()
        assert torch.isfinite(out).all()


def test_three_tcn_blocks_and_linear_head():
    stats = _load_stats()
    model = TCN_DPHM.from_norm_stats(stats)
    assert len(model.tcn) == 3  # 3-layer dilated TCN encoder
    assert isinstance(model.head, torch.nn.Linear)


def test_batch_size_one():
    stats = _load_stats()
    model = TCN_DPHM.from_norm_stats(stats)
    out = model(torch.randn(1, 10, model.n_features))
    assert tuple(out.shape) == (1, 8)
