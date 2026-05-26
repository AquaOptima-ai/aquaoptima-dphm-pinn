"""Optimizer Lite baseline interface and MVP PumpController integration.

This package wraps the existing MVP baseline PLC/PAC control logic behind
a canonical :class:`BaselineEngine` interface so the rest of Optimizer
Lite can treat it as one of several recommendation sources.  The wrapper
performs no live PLC writes and opens no network sockets; it only
translates between the canonical :class:`StationSnapshot` model and the
MVP-shaped input/output dictionaries that the legacy ``PumpController``
already understands.
"""

from .interface import (
    BaselineEngine,
    BaselineRecommendation,
    DemandTarget,
    PumpSetpoint,
    default_demand_target,
)
from .fallback import FallbackBaselineEngine
from .mvp_compat import (
    mvp_input_from_snapshot,
    recommendation_from_mvp_output,
)
from .mvp_wrapper import MvpBaselineWrapper, load_legacy_pump_controller

__all__ = [
    "BaselineEngine",
    "BaselineRecommendation",
    "DemandTarget",
    "FallbackBaselineEngine",
    "MvpBaselineWrapper",
    "PumpSetpoint",
    "default_demand_target",
    "load_legacy_pump_controller",
    "mvp_input_from_snapshot",
    "recommendation_from_mvp_output",
]
