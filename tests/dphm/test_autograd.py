"""Tests for the autograd finite-gradient helper."""

import math

import pytest
import torch

from aquaoptima.dphm.autograd_checks import assert_finite_gradients
from aquaoptima.dphm.hazen_williams import hazen_williams_head_loss


def test_passes_for_well_behaved_loss():
    Q = torch.tensor(0.05, requires_grad=True)
    hf = hazen_williams_head_loss(Q, 100.0, 0.3, 130.0)
    loss = hf.pow(2)
    assert_finite_gradients(loss, [Q])
    assert Q.grad is not None and torch.isfinite(Q.grad).item()


def test_raises_when_gradient_is_nan():
    x = torch.tensor(0.0, requires_grad=True)
    # sqrt(x) at zero is fine forward but produces inf grad — wrap to force NaN.
    loss = torch.sqrt(x) * 0.0 + torch.log(x)  # log(0) -> -inf, grad -> -inf
    with pytest.raises(AssertionError):
        assert_finite_gradients(loss, [x])


def test_raises_when_tensor_did_not_participate():
    a = torch.tensor(1.0, requires_grad=True)
    unused = torch.tensor(2.0, requires_grad=True)
    loss = a * a
    with pytest.raises(AssertionError):
        assert_finite_gradients(loss, [a, unused])


def test_raises_when_tensor_has_no_grad_required():
    a = torch.tensor(1.0, requires_grad=True)
    constant = torch.tensor(3.0)  # requires_grad=False
    loss = a * a
    with pytest.raises(AssertionError):
        assert_finite_gradients(loss, [a, constant])


def test_clears_existing_grad_before_check():
    x = torch.tensor(2.0, requires_grad=True)
    # Pollute .grad with a NaN to make sure the helper does not reuse stale grads.
    x.grad = torch.tensor(float("nan"))
    loss = x * x
    assert_finite_gradients(loss, [x])
    assert math.isfinite(x.grad.item())
    assert math.isclose(x.grad.item(), 4.0, rel_tol=1e-6)
