"""Pump head-gain model based on affinity-style quadratic curves.

For a pump operating at relative speed ``s`` (1.0 = nominal) with quadratic
characteristic coefficients ``coeffs = [a0, a1, a2]``:

    H(Q, s) = a0 * s^2 + a1 * s * Q + a2 * Q^2

This generalises the standard parabolic shut-off curve while preserving the
affinity-law structure: at Q=0 the head scales with s^2.
"""

from __future__ import annotations

import torch


SPEED_MIN = 0.0
SPEED_MAX = 1.5


def _validate_speed(speed):
    t = speed if isinstance(speed, torch.Tensor) else torch.as_tensor(speed)
    if torch.any(t < SPEED_MIN) or torch.any(t > SPEED_MAX):
        raise ValueError(
            f"speed_ratio must lie in [{SPEED_MIN}, {SPEED_MAX}], got {speed!r}"
        )


def pump_head_gain(Q, speed_ratio, coeffs):
    """Pump head gain in metres for the given operating point.

    Parameters
    ----------
    Q : tensor-like
        Volumetric flow rate in m^3/s.
    speed_ratio : tensor-like
        Relative shaft speed; 1.0 corresponds to nominal speed.
    coeffs : tensor-like
        Either a 1-D ``[a0, a1, a2]`` curve or a 2-D batch ``[..., 3]``.
    """
    _validate_speed(speed_ratio)

    Q_t = Q if isinstance(Q, torch.Tensor) else torch.as_tensor(Q, dtype=torch.get_default_dtype())
    s_t = speed_ratio if isinstance(speed_ratio, torch.Tensor) else torch.as_tensor(
        speed_ratio, dtype=Q_t.dtype
    )
    c_t = coeffs if isinstance(coeffs, torch.Tensor) else torch.as_tensor(
        coeffs, dtype=Q_t.dtype
    )

    if c_t.shape[-1] != 3:
        raise ValueError(f"coeffs last dim must be 3, got shape {tuple(c_t.shape)}")

    a0 = c_t[..., 0]
    a1 = c_t[..., 1]
    a2 = c_t[..., 2]

    return a0 * s_t ** 2 + a1 * s_t * Q_t + a2 * Q_t ** 2
