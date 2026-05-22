"""Autograd sanity helpers for dPHM physics losses.

These checks are intended to catch physics-bug failure modes (NaN gradients
from divide-by-zero, dangling tensors disconnected from the graph, frozen
parameters that should not be) before they corrupt a training run.
"""

from __future__ import annotations

from typing import Iterable

import torch


def assert_finite_gradients(loss: torch.Tensor, tensors: Iterable[torch.Tensor]) -> None:
    """Backprop ``loss`` and assert every tensor in ``tensors`` has a finite gradient.

    Raises
    ------
    AssertionError
        If any tensor does not require grad, did not participate in the
        graph (``grad is None`` after backward), or has non-finite gradient
        entries.
    """
    tensor_list = list(tensors)

    for i, t in enumerate(tensor_list):
        if not isinstance(t, torch.Tensor):
            raise AssertionError(f"entry {i} is not a torch.Tensor")
        if not t.requires_grad:
            raise AssertionError(f"tensor at index {i} does not require grad")
        # Wipe stale grads so we test only this backward pass.
        t.grad = None

    loss.backward()

    for i, t in enumerate(tensor_list):
        if t.grad is None:
            raise AssertionError(
                f"tensor at index {i} has no gradient after backward — "
                "it did not participate in the loss"
            )
        if not torch.isfinite(t.grad).all():
            raise AssertionError(
                f"tensor at index {i} has non-finite gradient entries"
            )
