"""Tests for the pump head-gain affinity model."""

import math

import pytest
import torch

from aquaoptima.dphm.pump_affinity import pump_head_gain


# Representative quadratic curve: H(Q) = 40 - 600 * Q^2 at full speed.
# a0 contributes head_static; a2 negative -> head drops as Q rises.
COEFFS = torch.tensor([40.0, 0.0, -600.0])


def test_matches_closed_form_at_full_speed():
    Q = torch.tensor(0.05)
    speed = torch.tensor(1.0)
    got = pump_head_gain(Q, speed, COEFFS).item()
    expected = 40.0 * 1.0 ** 2 + 0.0 * 1.0 * 0.05 + (-600.0) * 0.05 ** 2
    assert math.isclose(got, expected, rel_tol=1e-6)


def test_head_scales_quadratically_with_speed_at_zero_flow():
    Q = torch.tensor(0.0)
    full = pump_head_gain(Q, torch.tensor(1.0), COEFFS).item()
    half = pump_head_gain(Q, torch.tensor(0.5), COEFFS).item()
    assert math.isclose(half, 0.25 * full, rel_tol=1e-6)


def test_head_decreases_with_flow():
    speed = torch.tensor(1.0)
    low = pump_head_gain(torch.tensor(0.01), speed, COEFFS).item()
    high = pump_head_gain(torch.tensor(0.1), speed, COEFFS).item()
    assert high < low


def test_supports_batch_coefficients():
    Q = torch.tensor([0.05, 0.02])
    speed = torch.tensor([1.0, 0.8])
    coeffs = torch.tensor(
        [
            [40.0, 0.0, -600.0],
            [30.0, 0.0, -400.0],
        ]
    )
    got = pump_head_gain(Q, speed, coeffs)
    assert got.shape == (2,)
    for i in range(2):
        c = coeffs[i]
        s = speed[i].item()
        q = Q[i].item()
        expected = c[0].item() * s * s + c[1].item() * s * q + c[2].item() * q * q
        assert math.isclose(got[i].item(), expected, rel_tol=1e-6)


def test_finite_gradients_w_r_t_Q_and_speed():
    Q = torch.tensor(0.05, requires_grad=True)
    speed = torch.tensor(0.9, requires_grad=True)
    H = pump_head_gain(Q, speed, COEFFS)
    H.backward()
    assert torch.isfinite(Q.grad).item()
    assert torch.isfinite(speed.grad).item()


@pytest.mark.parametrize("bad_speed", [-0.1, -1.0, 1.51, 2.0])
def test_invalid_speed_raises(bad_speed):
    Q = torch.tensor(0.05)
    with pytest.raises(ValueError):
        pump_head_gain(Q, torch.tensor(bad_speed), COEFFS)


@pytest.mark.parametrize("good_speed", [0.0, 0.5, 1.0, 1.5])
def test_boundary_speeds_accepted(good_speed):
    Q = torch.tensor(0.05)
    out = pump_head_gain(Q, torch.tensor(good_speed), COEFFS)
    assert torch.isfinite(out).item()
