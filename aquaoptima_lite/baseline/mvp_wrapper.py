"""Wrap the legacy MVP ``PumpController`` behind the canonical interface.

The wrapper is dependency-injectable so unit tests can swap the legacy
engine for a fake.  When no engine is supplied the wrapper attempts to
import the real MVP ``PumpController`` from common vendor paths; if the
import fails the caller can either pass in :class:`FallbackBaselineEngine`
or use :func:`load_legacy_pump_controller` directly and handle
``ImportError``.

No PLC writes happen here — the wrapper only translates between
:class:`StationSnapshot` and the MVP dict shape and forwards the call
through to whatever callable was injected.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Mapping, Optional

from ..runtime.models import StationSnapshot
from .interface import BaselineRecommendation, DemandTarget
from .mvp_compat import mvp_input_from_snapshot, recommendation_from_mvp_output


# A callable that takes the MVP dict and returns the MVP dict.
MvpCallable = Callable[[Mapping[str, Any]], Mapping[str, Any]]


_LEGACY_IMPORT_CANDIDATES = (
    ("aquaoptima_mvp.controller", "PumpController"),
    ("aquaoptima.legacy.controller", "PumpController"),
    ("mvp_v1.controller", "PumpController"),
)


def load_legacy_pump_controller() -> MvpCallable:
    """Import the real MVP ``PumpController`` from a known vendor path.

    Returns a callable matching :data:`MvpCallable`.  Raises
    :class:`ImportError` with a clear summary if no candidate path
    resolves.
    """

    tried = []
    last_error: Optional[BaseException] = None
    for module_name, attr in _LEGACY_IMPORT_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            tried.append(f"{module_name} ({exc})")
            last_error = exc
            continue
        controller_cls = getattr(module, attr, None)
        if controller_cls is None:
            tried.append(f"{module_name}.{attr} (attribute missing)")
            continue
        controller = controller_cls()
        compute = getattr(controller, "compute", None) or getattr(controller, "step", None)
        if compute is None:
            tried.append(
                f"{module_name}.{attr} (no compute()/step() callable)"
            )
            continue
        return compute  # type: ignore[return-value]
    summary = "; ".join(tried) if tried else "no candidate paths configured"
    raise ImportError(
        f"legacy MVP PumpController not importable: {summary}"
    ) from last_error


class MvpBaselineWrapper:
    """A :class:`BaselineEngine` backed by the MVP v1 PumpController.

    The wrapper accepts an injected ``mvp_engine`` callable, which is
    very useful in tests (you can pass a lambda that returns canned MVP
    output).  When the caller passes ``mvp_engine=None`` the wrapper
    eagerly attempts to import the legacy ``PumpController`` so import
    failure surfaces at construction time, not in the middle of a
    cycle.
    """

    def __init__(self, mvp_engine: Optional[MvpCallable] = None) -> None:
        if mvp_engine is None:
            mvp_engine = load_legacy_pump_controller()
        if not callable(mvp_engine):
            raise TypeError(
                "MvpBaselineWrapper(mvp_engine=...) must be callable, got "
                f"{type(mvp_engine).__name__}"
            )
        self._mvp_engine = mvp_engine

    def recommend(
        self,
        snapshot: StationSnapshot,
        demand: DemandTarget,
    ) -> BaselineRecommendation:
        mvp_input = mvp_input_from_snapshot(snapshot, demand)
        # The pump-suffix map is for debugging only; the legacy engine
        # would choke on the unknown key.
        legacy_input = {k: v for k, v in mvp_input.items() if not k.startswith("_")}
        raw_output = self._mvp_engine(legacy_input)
        if not isinstance(raw_output, Mapping):
            raise TypeError(
                "MVP engine must return a Mapping, got "
                f"{type(raw_output).__name__}"
            )
        return recommendation_from_mvp_output(
            snapshot,
            raw_output,
            source="baseline_mvp",
        )
