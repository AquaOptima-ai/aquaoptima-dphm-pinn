"""Unit normalization for canonical fields.

Sprint 4 only needs pass-through conversions for the units the replay
fixtures actually use (bar, m, m3h, Hz, kW, A, bool).  The table is
expressed as a small dispatch dict so future sprints can add real
conversions (e.g. PSI -> bar, GPM -> m3h) without changing call sites.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


_Converter = Callable[[float], float]


def _passthrough(value: float) -> float:
    return float(value)


_UNIT_TABLE: Dict[str, _Converter] = {
    "bar": _passthrough,
    "m": _passthrough,
    "m3h": _passthrough,
    "hz": _passthrough,
    "kw": _passthrough,
    "a": _passthrough,
    "bool": _passthrough,
    "": _passthrough,
}


def supported_units() -> tuple[str, ...]:
    """Return the unit tokens this module knows about."""

    return tuple(sorted(k for k in _UNIT_TABLE if k))


def _normalize_unit_key(unit: Optional[str]) -> str:
    if unit is None:
        return ""
    return str(unit).strip().lower()


def normalize_unit(value: Any, unit: Optional[str]) -> Optional[float]:
    """Return ``value`` converted to canonical units.

    Booleans collapse to ``0.0`` / ``1.0`` so downstream code can do
    arithmetic on running flags without branching.  ``None`` propagates
    unchanged.  Unknown unit tokens fall back to ``float(value)`` so a
    well-formed numeric value still survives -- the snapshot builder
    will record the quality penalty separately.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    converter = _UNIT_TABLE.get(_normalize_unit_key(unit), _passthrough)
    return converter(numeric)
