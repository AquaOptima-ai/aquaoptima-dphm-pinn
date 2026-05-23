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
from .large_fixtures import make_grid_network
from .incidence import cached_incidence_matrix, incidence_matrix, node_flow_balance
from .inp_io import (
    EDGE_SURROGATE_KIND_PRV_FIXED_HEAD,
    EDGE_SURROGATE_KIND_TCV_MINOR_LOSS,
    EDGE_SURROGATE_SEVERITY_INFO,
    EDGE_SURROGATE_SEVERITY_LIMITATION,
    EDGE_SURROGATE_SEVERITY_WARNING,
    EpanetControlKind,
    EpanetControlRuleDiagnostic,
    EpanetEdgeSurrogateDiagnostic,
    EpanetEmitterDemandDiagnostic,
    EpanetIgnoredSectionDiagnostic,
    EpanetImportDiagnostics,
    EpanetImportDiagnosticsSummary,
    EpanetPatternEnergyDiagnostic,
    EpanetStatusDiagnostic,
    EpanetWaterQualityDiagnostic,
    fit_power_pump_surrogate,
    fit_pump_head_curve,
    fit_tcv_resistance_surrogate,
    load_inp_diagnostics,
    load_network_from_inp,
    translate_valve_to_surrogate,
)
from .network import Network
from .network_io import load_network_from_json
from .pump_affinity import pump_head_gain
from .residuals import mass_residual, pipe_energy_residual, pump_energy_residual
from .solver import (
    assemble_jacobian_analytic,
    assemble_residuals,
    assemble_residuals_batched,
    initial_guess,
    newton_solve,
    residual_norm,
)

__all__ = [
    "assemble_jacobian_analytic",
    "assemble_residuals",
    "assemble_residuals_batched",
    "assert_finite_gradients",
    "cached_incidence_matrix",
    "classify_failure",
    "EDGE_SURROGATE_KIND_PRV_FIXED_HEAD",
    "EDGE_SURROGATE_KIND_TCV_MINOR_LOSS",
    "EDGE_SURROGATE_SEVERITY_INFO",
    "EDGE_SURROGATE_SEVERITY_LIMITATION",
    "EDGE_SURROGATE_SEVERITY_WARNING",
    "EpanetControlKind",
    "EpanetControlRuleDiagnostic",
    "EpanetEdgeSurrogateDiagnostic",
    "EpanetEmitterDemandDiagnostic",
    "EpanetIgnoredSectionDiagnostic",
    "EpanetImportDiagnostics",
    "EpanetImportDiagnosticsSummary",
    "EpanetPatternEnergyDiagnostic",
    "EpanetStatusDiagnostic",
    "EpanetWaterQualityDiagnostic",
    "FeasibilityResult",
    "check_feasibility",
    "hazen_williams_head_loss",
    "fit_power_pump_surrogate",
    "fit_pump_head_curve",
    "fit_tcv_resistance_surrogate",
    "incidence_matrix",
    "initial_guess",
    "load_inp_diagnostics",
    "load_network_from_inp",
    "load_network_from_json",
    "make_branch_network",
    "make_grid_network",
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
    "translate_valve_to_surrogate",
]
