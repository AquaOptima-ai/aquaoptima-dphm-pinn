"""Canonical-telemetry-axis -> Yilan source CSV column mapping (Sprint 23).

The roadmap referenced abstract canonical axis tokens
(``aquaoptima_contracts.telemetry.axis.CANONICAL_TELEMETRY_AXES``) but the
real Yilan ``source1_2025.csv`` exposes site-specific column names. This
module is the single source of truth for that mapping, used by the profiler,
the split builder, the normalization stats computation, and the PyTorch
dataset so they all agree on which physical signal backs each canonical axis.

Safety / scope
--------------
* Read-only metadata. No I/O, no control influence.
* ``edge_valve_position`` has no backing column in the Yilan site data
  (the site has no telemetered valve position), so it is intentionally
  mapped to ``None`` and reports ~0% coverage. Downstream code treats
  zero-coverage axes as *inactive* and excludes them from normalization and
  from the model feature matrix.

DATA-REALITY CORRECTION
-----------------------
The roadmap guessed mode columns ``optimizer_enabled`` / ``auto_mode_active``;
the real columns are literally ``auto`` and ``manual``. See
``MODE_AUTO_COLUMN`` / ``MODE_MANUAL_COLUMN`` below and
``docs/planning/dataset_construction.md``.
"""

from __future__ import annotations

from aquaoptima_contracts.telemetry.axis import CANONICAL_TELEMETRY_AXES

# Timestamp column + format (YYYY-MM-DD_HH:MM:SS, 60s cadence).
TIMESTAMP_COLUMN = "timestamp"
TIMESTAMP_FORMAT = "%Y-%m-%d_%H:%M:%S"

# Real operating-mode columns (NOT the roadmap's guessed names).
MODE_AUTO_COLUMN = "auto"
MODE_MANUAL_COLUMN = "manual"

# Canonical axis -> backing Yilan CSV column. ``None`` => no backing column
# in this site's data (treated as zero coverage / inactive axis).
CANONICAL_AXIS_TO_COLUMN: dict[str, str | None] = {
    "node_pressure": "system_pressure",
    "node_level": "tank_level",
    "node_demand": "tb_system_predicted_flow_rate",
    "node_status": "tb_system_head",
    "edge_flow": "system_flow_rate",
    "edge_pump_speed": "P_1531A_frequency",
    "edge_status": "P_1531A_status",
    "edge_power": "tb_system_real_power",
    # No telemetered valve position at the Yilan site -> 0% coverage.
    "edge_valve_position": None,
}

# Deterministic canonical-axis ordering used for CSV/JSON output and for the
# dataset feature dimension order.
CANONICAL_AXES_ORDERED: list[str] = sorted(CANONICAL_TELEMETRY_AXES)


def _validate_mapping() -> None:
    mapped = set(CANONICAL_AXIS_TO_COLUMN)
    canonical = set(CANONICAL_TELEMETRY_AXES)
    if mapped != canonical:
        missing = canonical - mapped
        extra = mapped - canonical
        raise ValueError(
            "CANONICAL_AXIS_TO_COLUMN must cover exactly the canonical axes; "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )


_validate_mapping()


__all__ = [
    "TIMESTAMP_COLUMN",
    "TIMESTAMP_FORMAT",
    "MODE_AUTO_COLUMN",
    "MODE_MANUAL_COLUMN",
    "CANONICAL_AXIS_TO_COLUMN",
    "CANONICAL_AXES_ORDERED",
]
