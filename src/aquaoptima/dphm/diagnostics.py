"""Structured diagnostics for the dPHM steady-state solver.

The solver never returns "best-effort" heads as if they were a converged
solution. Failure modes are classified explicitly so downstream consumers
(training loops, PLC bridges, dashboards) can react without re-parsing
human-readable strings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import torch


class SolveFailureReason(str, Enum):
    """Why a :func:`newton_solve` call did not converge.

    Members are deterministic, machine-checkable strings so downstream
    code (training loop, PLC bridge, dashboards) can branch on the
    failure mode without parsing free-form text.
    """

    MAX_ITERATIONS = "max_iterations"
    DIVERGED = "diverged"
    NAN_RESIDUAL = "nan_residual"
    SINGULAR_JACOBIAN = "singular_jacobian"


@dataclass
class SolveResult:
    """Outcome of a dPHM steady-state Newton solve.

    Attributes
    ----------
    converged
        ``True`` iff the residual norm dropped at or below ``tol``
        without hitting any failure mode. Never set to ``True`` on a
        non-finite residual.
    heads
        Final per-node head vector, shape ``[num_nodes]``.
    flows
        Final per-edge flow vector, shape ``[num_edges]``.
    residual_norm
        L2 norm of the final residual vector. ``NaN`` /``Inf`` indicate
        catastrophic numerical state and force ``converged=False``.
    iterations
        Number of Newton iterations actually executed.
    reason
        ``None`` on a clean convergence; otherwise the string value of
        the corresponding :class:`SolveFailureReason` member.
    """

    converged: bool
    heads: torch.Tensor
    flows: torch.Tensor
    residual_norm: float
    iterations: int
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.converged:
            if not math.isfinite(self.residual_norm):
                raise ValueError(
                    "converged=True is inconsistent with non-finite residual_norm "
                    f"{self.residual_norm!r}"
                )
            if self.reason is not None:
                raise ValueError(
                    f"converged=True must not carry a failure reason, got {self.reason!r}"
                )


def classify_failure(
    *,
    residual_norm: float,
    iterations: int,
    max_iterations: int,
    tol: float,
    diverged: bool,
    singular: bool = False,
) -> Optional[SolveFailureReason]:
    """Return the failure reason matching the solver's terminal state, or ``None``
    if the iteration actually converged.

    The classifier is deterministic and order-sensitive: NaN beats divergence
    beats singularity beats iteration-budget. Convergence is decided last so
    that any pathological numeric state always reports as a failure.
    """
    if math.isnan(residual_norm):
        return SolveFailureReason.NAN_RESIDUAL
    if diverged or math.isinf(residual_norm):
        return SolveFailureReason.DIVERGED
    if singular:
        return SolveFailureReason.SINGULAR_JACOBIAN
    if residual_norm <= tol:
        return None
    if iterations >= max_iterations:
        return SolveFailureReason.MAX_ITERATIONS
    return SolveFailureReason.MAX_ITERATIONS
