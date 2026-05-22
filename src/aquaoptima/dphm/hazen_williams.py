"""Hazen-Williams head loss for pressurised pipe flow.

The signed form used here is:

    h_f = 10.67 * L * sign(Q) * (|Q| + eps) ** 1.852 / (C ** 1.852 * D ** 4.87)

with internal units of m^3/s for Q and metres for L, D, and head loss.

Reverse flow (negative Q) produces a negative head loss, which makes the
expression compatible with the directed-edge energy residual convention
``head_upstream - head_downstream - head_loss = 0``.
"""

from __future__ import annotations

import torch


def _as_tensor(x, ref):
    if isinstance(x, torch.Tensor):
        return x
    return torch.as_tensor(x, dtype=ref.dtype, device=ref.device)


def _validate_positive(name, value):
    """Raise ValueError if any element of value is non-positive."""
    t = value if isinstance(value, torch.Tensor) else torch.as_tensor(value)
    if torch.any(t <= 0):
        raise ValueError(f"{name} must be strictly positive, got {value!r}")


def hazen_williams_head_loss(Q, L, D, C, eps: float = 1e-6):
    """Signed Hazen-Williams head loss in metres.

    Parameters
    ----------
    Q : tensor-like
        Volumetric flow rate in m^3/s. Sign convention follows the directed edge.
    L : tensor-like
        Pipe length in metres. Must be strictly positive.
    D : tensor-like
        Internal diameter in metres. Must be strictly positive.
    C : tensor-like
        Hazen-Williams roughness coefficient. Must be strictly positive.
    eps : float
        Small regulariser added to |Q| so the gradient stays finite at Q=0.
    """
    _validate_positive("L", L)
    _validate_positive("D", D)
    _validate_positive("C", C)

    Q_t = Q if isinstance(Q, torch.Tensor) else torch.as_tensor(Q, dtype=torch.get_default_dtype())
    L_t = _as_tensor(L, Q_t)
    D_t = _as_tensor(D, Q_t)
    C_t = _as_tensor(C, Q_t)

    abs_Q = torch.abs(Q_t)
    magnitude = 10.67 * L_t * (abs_Q + eps) ** 1.852 / (C_t ** 1.852 * D_t ** 4.87)
    return torch.sign(Q_t) * magnitude
