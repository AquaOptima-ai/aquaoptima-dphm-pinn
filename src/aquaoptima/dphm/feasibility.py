"""Feasibility checks for pressures, pump speeds, and flows.

No defaults are imposed on bounds: every constraint must be supplied
explicitly by the caller. A bound left as ``None`` simply skips that side of
the check (e.g. ``pressure_min=15.0, pressure_max=None`` only checks the
lower bound).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import torch


@dataclass
class FeasibilityResult:
    """Result of a :func:`check_feasibility` call.

    Attributes
    ----------
    ok
        ``True`` iff no requested bound was violated. With no checks
        requested, ``ok`` is ``True`` by definition.
    violations
        Human-readable strings describing each violation. Each entry
        identifies the channel, the offending bound, and the worst
        observed value so a single result can be logged or surfaced
        verbatim to an operator without further formatting.
    """

    ok: bool
    violations: list[str] = field(default_factory=list)


def _as_tensor(x) -> torch.Tensor:
    return x if isinstance(x, torch.Tensor) else torch.as_tensor(x)


def _check_lower(name: str, values: torch.Tensor, bound: float, violations: list[str]) -> None:
    mask = values < bound
    if torch.any(mask):
        bad = values[mask]
        violations.append(
            f"{name} below min: bound={bound}, min_seen={bad.min().item()}"
        )


def _check_upper(name: str, values: torch.Tensor, bound: float, violations: list[str]) -> None:
    mask = values > bound
    if torch.any(mask):
        bad = values[mask]
        violations.append(
            f"{name} above max: bound={bound}, max_seen={bad.max().item()}"
        )


def check_feasibility(
    pressures: Optional[torch.Tensor] = None,
    pump_speeds: Optional[torch.Tensor] = None,
    flows: Optional[torch.Tensor] = None,
    pressure_min: Optional[float] = None,
    pressure_max: Optional[float] = None,
    pump_speed_min: Optional[float] = None,
    pump_speed_max: Optional[float] = None,
    max_abs_flow: Optional[float] = None,
) -> FeasibilityResult:
    """Run requested feasibility checks and return a structured result."""
    violations: list[str] = []

    if pressures is not None:
        p = _as_tensor(pressures)
        if pressure_min is not None:
            _check_lower("pressure", p, pressure_min, violations)
        if pressure_max is not None:
            _check_upper("pressure", p, pressure_max, violations)

    if pump_speeds is not None:
        s = _as_tensor(pump_speeds)
        if pump_speed_min is not None:
            _check_lower("pump_speed", s, pump_speed_min, violations)
        if pump_speed_max is not None:
            _check_upper("pump_speed", s, pump_speed_max, violations)

    if flows is not None and max_abs_flow is not None:
        f = torch.abs(_as_tensor(flows))
        _check_upper("flow", f, max_abs_flow, violations)

    return FeasibilityResult(ok=not violations, violations=violations)
