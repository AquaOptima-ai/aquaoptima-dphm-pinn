"""Tests for Hazen-Williams head loss."""

import math

import pytest
import torch

from aquaoptima.dphm.hazen_williams import hazen_williams_head_loss


# Reference reservoir pipe values used across tests.
L_REF = 100.0  # m
D_REF = 0.3    # m
C_REF = 130.0  # dimensionless


def _hf_reference(Q, L=L_REF, D=D_REF, C=C_REF, eps=1e-6):
    """Plain-Python reference implementation of the documented formula."""
    return 10.67 * L * math.copysign(1.0, Q) * (abs(Q) + eps) ** 1.852 / (
        C ** 1.852 * D ** 4.87
    )


def test_matches_reference_formula_for_typical_flow():
    Q = torch.tensor(0.05)  # ~50 L/s
    got = hazen_williams_head_loss(Q, L_REF, D_REF, C_REF).item()
    expected = _hf_reference(0.05)
    assert math.isclose(got, expected, rel_tol=1e-5)


def test_monotonic_increasing_with_abs_Q():
    Qs = torch.tensor([0.01, 0.05, 0.1, 0.2])
    hf = hazen_williams_head_loss(Qs, L_REF, D_REF, C_REF)
    assert torch.all(hf[1:] > hf[:-1]), "head loss must increase with |Q|"


def test_increases_with_length():
    Q = torch.tensor(0.05)
    short = hazen_williams_head_loss(Q, 10.0, D_REF, C_REF)
    long = hazen_williams_head_loss(Q, 1000.0, D_REF, C_REF)
    assert long.item() > short.item()


def test_decreases_with_diameter():
    Q = torch.tensor(0.05)
    small = hazen_williams_head_loss(Q, L_REF, 0.1, C_REF)
    big = hazen_williams_head_loss(Q, L_REF, 0.5, C_REF)
    assert big.item() < small.item()


def test_decreases_with_C():
    Q = torch.tensor(0.05)
    rough = hazen_williams_head_loss(Q, L_REF, D_REF, 80.0)
    smooth = hazen_williams_head_loss(Q, L_REF, D_REF, 150.0)
    assert smooth.item() < rough.item()


def test_reverse_flow_negative():
    Qp = torch.tensor(0.05)
    Qn = torch.tensor(-0.05)
    hf_p = hazen_williams_head_loss(Qp, L_REF, D_REF, C_REF).item()
    hf_n = hazen_williams_head_loss(Qn, L_REF, D_REF, C_REF).item()
    assert hf_p > 0
    assert hf_n < 0
    assert math.isclose(hf_p, -hf_n, rel_tol=1e-6)


def test_finite_at_zero_flow_and_finite_gradient():
    Q = torch.tensor(0.0, requires_grad=True)
    hf = hazen_williams_head_loss(Q, L_REF, D_REF, C_REF)
    assert torch.isfinite(hf).item()
    hf.backward()
    assert Q.grad is not None
    assert torch.isfinite(Q.grad).item()


def test_broadcasts_over_batched_pipes():
    Q = torch.tensor([0.01, 0.05, 0.1])
    L = torch.tensor([100.0, 200.0, 50.0])
    D = torch.tensor([0.2, 0.3, 0.15])
    C = torch.tensor([120.0, 130.0, 140.0])
    out = hazen_williams_head_loss(Q, L, D, C)
    assert out.shape == (3,)
    for i in range(3):
        ref = _hf_reference(Q[i].item(), L[i].item(), D[i].item(), C[i].item())
        assert math.isclose(out[i].item(), ref, rel_tol=1e-5)


@pytest.mark.parametrize(
    "L,D,C",
    [
        (0.0, 0.3, 130.0),
        (-1.0, 0.3, 130.0),
        (100.0, 0.0, 130.0),
        (100.0, -0.1, 130.0),
        (100.0, 0.3, 0.0),
        (100.0, 0.3, -10.0),
    ],
)
def test_invalid_geometry_raises(L, D, C):
    Q = torch.tensor(0.05)
    with pytest.raises(ValueError):
        hazen_williams_head_loss(Q, L, D, C)
