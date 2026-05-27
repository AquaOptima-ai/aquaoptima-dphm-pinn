"""YAML loader and deterministic hashing for :class:`SiteConfig`.

The hash is the SHA-256 of a canonical JSON encoding (sorted keys, tight
separators) so two configs that differ only in YAML formatting, key order,
or whitespace produce the same hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import (
    DataRequirements,
    PumpConfig,
    RuntimeConfig,
    SafetyConfig,
    SiteConfig,
    TagConfig,
)


_REQUIRED_TOP_LEVEL = ("site", "runtime", "safety", "data_requirements", "pumps", "tags")


def _require_keys(section: Mapping[str, Any], keys: tuple, section_name: str) -> None:
    missing = [k for k in keys if k not in section]
    if missing:
        raise ValueError(
            f"config section {section_name!r} missing keys: {sorted(missing)!r}"
        )


def _build_runtime(raw: Mapping[str, Any]) -> RuntimeConfig:
    _require_keys(raw, ("default_mode", "cycle_seconds", "stale_after_seconds"), "runtime")
    return RuntimeConfig(
        default_mode=str(raw["default_mode"]),
        cycle_seconds=float(raw["cycle_seconds"]),
        stale_after_seconds=float(raw["stale_after_seconds"]),
    )


def _build_safety(raw: Mapping[str, Any]) -> SafetyConfig:
    required_keys = (
        "require_auto_mode",
        "block_on_any_trip",
        "block_on_any_alarm",
        "baseline_control_enabled",
        "future_control_enabled",
        "min_frequency_hz",
        "max_frequency_hz",
        "max_step_hz",
        "min_pressure_bar",
        "max_pressure_bar",
        "min_flow_m3h",
        "max_flow_m3h",
        "min_model_confidence_for_advisory",
    )
    _require_keys(raw, required_keys, "safety")
    return SafetyConfig(
        require_auto_mode=bool(raw["require_auto_mode"]),
        block_on_any_trip=bool(raw["block_on_any_trip"]),
        block_on_any_alarm=bool(raw["block_on_any_alarm"]),
        baseline_control_enabled=bool(raw["baseline_control_enabled"]),
        future_control_enabled=bool(raw["future_control_enabled"]),
        min_frequency_hz=float(raw["min_frequency_hz"]),
        max_frequency_hz=float(raw["max_frequency_hz"]),
        max_step_hz=float(raw["max_step_hz"]),
        min_pressure_bar=float(raw["min_pressure_bar"]),
        max_pressure_bar=float(raw["max_pressure_bar"]),
        min_flow_m3h=float(raw["min_flow_m3h"]),
        max_flow_m3h=float(raw["max_flow_m3h"]),
        min_model_confidence_for_advisory=float(raw["min_model_confidence_for_advisory"]),
    )


def _build_data_requirements(raw: Mapping[str, Any]) -> DataRequirements:
    return DataRequirements(
        required=tuple(str(x) for x in raw.get("required", ()) or ()),
        strongly_preferred=tuple(str(x) for x in raw.get("strongly_preferred", ()) or ()),
        optional=tuple(str(x) for x in raw.get("optional", ()) or ()),
    )


def _build_pump(raw: Mapping[str, Any]) -> PumpConfig:
    _require_keys(
        raw,
        ("id", "display_name", "role", "min_frequency_hz", "max_frequency_hz"),
        "pumps[*]",
    )
    rated = raw.get("rated_power_kw")
    return PumpConfig(
        pump_id=str(raw["id"]),
        display_name=str(raw["display_name"]),
        role=str(raw["role"]),
        min_frequency_hz=float(raw["min_frequency_hz"]),
        max_frequency_hz=float(raw["max_frequency_hz"]),
        rated_power_kw=None if rated is None else float(rated),
    )


def _build_tag(raw: Mapping[str, Any]) -> TagConfig:
    _require_keys(raw, ("canonical", "source", "address", "unit"), "tags[*]")
    return TagConfig(
        canonical=str(raw["canonical"]),
        source=str(raw["source"]),
        address=str(raw["address"]),
        unit=str(raw["unit"]),
        scale=float(raw.get("scale", 1.0)),
        valid_min=None if raw.get("valid_min") is None else float(raw["valid_min"]),
        valid_max=None if raw.get("valid_max") is None else float(raw["valid_max"]),
        stale_after_seconds=(
            None
            if raw.get("stale_after_seconds") is None
            else float(raw["stale_after_seconds"])
        ),
        required=bool(raw.get("required", False)),
    )


def load_site_config(path: str | Path) -> SiteConfig:
    """Load a :class:`SiteConfig` from a YAML file."""

    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"config root must be a mapping, got {type(data).__name__}")

    missing = [k for k in _REQUIRED_TOP_LEVEL if k not in data]
    if missing:
        raise ValueError(f"config missing required top-level sections: {missing!r}")

    site = data["site"]
    _require_keys(site, ("id", "name", "timezone"), "site")

    pumps = tuple(_build_pump(p) for p in data["pumps"])
    if not pumps:
        raise ValueError("config must declare at least one pump")

    tags = tuple(_build_tag(t) for t in data["tags"])

    return SiteConfig(
        site_id=str(site["id"]),
        site_name=str(site["name"]),
        timezone=str(site["timezone"]),
        runtime=_build_runtime(data["runtime"]),
        safety=_build_safety(data["safety"]),
        data_requirements=_build_data_requirements(data["data_requirements"]),
        pumps=pumps,
        tags=tags,
    )


def _canonicalize(value: Any) -> Any:
    """Recursively convert dataclass output into JSON-friendly primitives.

    Tuples become lists, ``None`` is preserved, and floats / bools / strings
    pass through unchanged.  Keys are not sorted here — :func:`json.dumps`
    will do that with ``sort_keys=True``.
    """

    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    return value


def compute_config_hash(config: SiteConfig) -> str:
    """Return a deterministic SHA-256 hex digest of ``config``."""

    canonical = _canonicalize(asdict(config))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
