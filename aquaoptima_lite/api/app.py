"""Minimal status/evidence API for Optimizer Lite.

The API is intentionally tiny in Sprint 3. It exposes the latest in-memory
runtime state for Operations Console prototypes and contract tests. The app
can be backed by any object exposing ``latest_state()``; if no provider is
passed it returns a safe empty status.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Optional, Protocol

try:  # FastAPI is preferred when available in the active environment.
    from fastapi import FastAPI
except Exception:  # pragma: no cover - fallback exercised only without FastAPI
    FastAPI = None  # type: ignore[assignment]


class RuntimeStateProvider(Protocol):
    def latest_state(self) -> Mapping[str, Any]: ...


class EmptyRuntimeStateProvider:
    def latest_state(self) -> Mapping[str, Any]:
        return {
            "status": {"service": "optimizer_lite", "healthy": True, "has_cycle": False},
            "snapshot": None,
            "quality": None,
            "recommendation": None,
        }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return str(value)


def _empty_console_evidence() -> dict[str, Any]:
    return {
        "service": "optimizer_lite",
        "has_cycle": False,
        "site_id": None,
        "runtime_mode": None,
        "config_hash": None,
        "read_only": True,
        "influences_control": False,
        "safety": {
            "no_console_direct_write_path": True,
            "no_new_field_write_path": True,
            "baseline_remains_authority": True,
        },
        "quality": None,
        "baseline": None,
        "learner_shadow": {},
        "performance_model": {},
        "advisory_ranking": {},
    }


def _console_evidence_payload(provider: RuntimeStateProvider) -> dict[str, Any]:
    state = provider.latest_state()
    status = _jsonable(state.get("status")) or {}
    evidence = _empty_console_evidence()
    evidence.update(
        {
            "has_cycle": bool(status.get("has_cycle")),
            "site_id": status.get("site_id"),
            "runtime_mode": status.get("runtime_mode"),
            "config_hash": status.get("config_hash"),
            "quality": _jsonable(state.get("quality")),
            "baseline": _jsonable(state.get("recommendation")),
        }
    )
    store = getattr(provider, "audit_store", None)
    latest = store.latest() if store is not None else None
    learner_shadow = _jsonable(getattr(latest, "learner_shadow", {})) if latest is not None else {}
    evidence["learner_shadow"] = learner_shadow or {}
    evidence["performance_model"] = evidence["learner_shadow"].get("performance_model", {})
    evidence["advisory_ranking"] = evidence["learner_shadow"].get("advisory_ranking", {})
    return evidence


def create_app(provider: Optional[RuntimeStateProvider] = None):
    """Create the Optimizer Lite API app.

    Returns a FastAPI app when FastAPI is installed. The repository's test
    environment has FastAPI available through the existing dPHM stack; if a
    future PAC image omits FastAPI, this function raises a clear error rather
    than silently inventing a different server framework.
    """

    if FastAPI is None:  # pragma: no cover
        raise RuntimeError("FastAPI is required for aquaoptima_lite.api in Sprint 3")

    state_provider = provider or EmptyRuntimeStateProvider()
    app = FastAPI(title="AquaOptima Pump Station Optimizer Lite", version="0.1.0")

    def state() -> Mapping[str, Any]:
        return state_provider.latest_state()

    @app.get("/status")
    def status() -> Any:
        return _jsonable(state().get("status"))

    @app.get("/snapshot/current")
    def snapshot_current() -> Any:
        return _jsonable(state().get("snapshot"))

    @app.get("/quality/current")
    def quality_current() -> Any:
        return _jsonable(state().get("quality"))

    @app.get("/recommendation/current")
    def recommendation_current() -> Any:
        return _jsonable(state().get("recommendation"))

    @app.get("/console/evidence/current")
    def console_evidence_current() -> Any:
        return _jsonable(_console_evidence_payload(state_provider))

    return app
