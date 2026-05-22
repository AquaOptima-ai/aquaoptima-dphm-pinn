"""Differentiable Pressurised Hydraulic Model (dPHM) primitives."""

from .autograd_checks import assert_finite_gradients
from .diagnostics import SolveFailureReason, SolveResult, classify_failure
from .feasibility import FeasibilityResult, check_feasibility
from .fixtures import (
    make_branch_network,
    make_pump_network,
    make_single_loop_network,
)
from .hazen_williams import hazen_williams_head_loss
from .incidence import incidence_matrix, node_flow_balance
from .network import Network
from .pump_affinity import pump_head_gain
from .residuals import mass_residual, pipe_energy_residual, pump_energy_residual
from .solver import (
    assemble_residuals,
    initial_guess,
    newton_solve,
    residual_norm,
)

__all__ = [
    "assemble_residuals",
    "assert_finite_gradients",
    "classify_failure",
    "FeasibilityResult",
    "check_feasibility",
    "hazen_williams_head_loss",
    "incidence_matrix",
    "initial_guess",
    "make_branch_network",
    "make_pump_network",
    "make_single_loop_network",
    "mass_residual",
    "Network",
    "newton_solve",
    "node_flow_balance",
    "pipe_energy_residual",
    "pump_energy_residual",
    "pump_head_gain",
    "residual_norm",
    "SolveFailureReason",
    "SolveResult",
]
