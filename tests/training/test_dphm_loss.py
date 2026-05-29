"""MultiAxisLoss tests (AOPSO Sprint 24).

Active axes (Sprint 23 reality, ordered): edge_flow, edge_power,
edge_pump_speed, edge_status, node_demand, node_level, node_pressure,
node_status. Binary (BCE): edge_status, node_status. Continuous (MSE): rest.
"""

from __future__ import annotations

import torch

from aquaoptima.training.dphm_loss import (
    BINARY_AXES,
    CONTINUOUS_AXES,
    MultiAxisLoss,
)

ACTIVE_AXES = [
    "edge_flow",
    "edge_power",
    "edge_pump_speed",
    "edge_status",
    "node_demand",
    "node_level",
    "node_pressure",
    "node_status",
]


def test_returns_nonnegative_scalar():
    loss_fn = MultiAxisLoss(ACTIVE_AXES)
    pred = torch.randn(32, 8)
    target = torch.randn(32, 8)
    loss = loss_fn(pred, target)
    assert loss.ndim == 0  # scalar
    assert float(loss) >= 0.0


def test_zero_loss_when_continuous_matches_and_binary_certain():
    # Continuous axes: pred == target -> MSE 0.
    # Binary axes: target 0/1, logit pushed to +-inf-ish -> BCE ~ 0.
    # Sprint 26 emptied the DEFAULT binary set (node_status reclassified
    # continuous, edge_status dropped), so we exercise BCE routing by passing
    # binary_axes explicitly -- the routing machinery is still general.
    loss_fn = MultiAxisLoss(ACTIVE_AXES, binary_axes=["edge_status", "node_status"])
    target = torch.zeros(4, 8)
    # set binary axis targets to 1.0 to exercise both classes
    bin_idx = [ACTIVE_AXES.index(a) for a in ("edge_status", "node_status")]
    target[:, bin_idx[0]] = 1.0
    target[:, bin_idx[1]] = 0.0
    pred = target.clone()
    # large logits so BCE ~ 0 on the binary columns
    pred[:, bin_idx[0]] = 20.0   # sigmoid->~1 matches target 1
    pred[:, bin_idx[1]] = -20.0  # sigmoid->~0 matches target 0
    loss = loss_fn(pred, target)
    assert float(loss) < 1e-3


def test_binary_axes_routed_to_bce_continuous_to_mse():
    # Build two losses: one with only binary axes weighted, one with only
    # continuous, and confirm the binary one matches a hand BCE computation
    # and the continuous one matches a hand MSE computation.
    torch.manual_seed(0)
    pred = torch.randn(16, 8)
    target = torch.rand(16, 8)  # in [0,1] so BCE target is well defined

    # Only edge_status active (binary) -> equals BCEWithLogits on that column.
    # Sprint 26: pass binary_axes explicitly since the default set is now empty.
    w_bin = {a: 0.0 for a in ACTIVE_AXES}
    w_bin["edge_status"] = 1.0
    loss_bin = MultiAxisLoss(ACTIVE_AXES, weights=w_bin, binary_axes=["edge_status"])
    j = ACTIVE_AXES.index("edge_status")
    expected_bce = torch.nn.functional.binary_cross_entropy_with_logits(
        pred[:, j], target[:, j].clamp(0, 1)
    )
    assert torch.allclose(loss_bin(pred, target), expected_bce, atol=1e-6)

    # Only edge_flow active (continuous) -> equals MSE on that column.
    w_cont = {a: 0.0 for a in ACTIVE_AXES}
    w_cont["edge_flow"] = 1.0
    loss_cont = MultiAxisLoss(ACTIVE_AXES, weights=w_cont)
    k = ACTIVE_AXES.index("edge_flow")
    expected_mse = ((pred[:, k] - target[:, k]) ** 2).mean()
    assert torch.allclose(loss_cont(pred, target), expected_mse, atol=1e-6)


def test_masked_axis_contributes_zero():
    pred = torch.randn(8, 8)
    target = torch.randn(8, 8)

    full = MultiAxisLoss(ACTIVE_AXES)
    # Exclude one continuous axis; recompute as weighted mean excluding it.
    excluded = "node_level"
    masked = MultiAxisLoss(ACTIVE_AXES, excluded_axes=[excluded])

    # The masked loss must equal the mean over the remaining 7 axes only,
    # i.e. it must NOT include node_level's contribution.
    # Verify by comparing to an explicit weights dict that zeroes node_level.
    w = {a: (0.0 if a == excluded else 1.0) for a in ACTIVE_AXES}
    weighted = MultiAxisLoss(ACTIVE_AXES, weights=w)
    assert torch.allclose(masked(pred, target), weighted(pred, target), atol=1e-7)

    # And the excluded axis truly contributes 0: weight is 0.
    assert masked.weights[excluded] == 0.0
    # full loss differs from masked (node_level had nonzero contribution).
    assert not torch.allclose(full(pred, target), masked(pred, target))


def test_all_masked_is_exactly_zero():
    loss_fn = MultiAxisLoss(ACTIVE_AXES, weights={a: 0.0 for a in ACTIVE_AXES})
    loss = loss_fn(torch.randn(4, 8), torch.randn(4, 8))
    assert float(loss) == 0.0


def test_axis_routing_sets_are_disjoint_and_cover():
    # Sprint 26 routing contract: the DEFAULT binary set is now EMPTY
    # (node_status reclassified continuous; edge_status dropped as a binary
    # target). All 8 active axes default to continuous (MSE). BCE routing is
    # still available per-instance via the binary_axes override.
    assert BINARY_AXES == set()
    assert BINARY_AXES.isdisjoint(CONTINUOUS_AXES)
    assert len(CONTINUOUS_AXES) == 8
