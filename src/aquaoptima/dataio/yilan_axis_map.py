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


# --------------------------------------------------------------------------- #
# Axis TAXONOMY (Sprint 26 correction) -- single source of truth.
# --------------------------------------------------------------------------- #
# Sprint 25 diagnostic dig found two labeling defects in the original
# ``BINARY_AXES = {node_status, edge_status}`` assumption:
#
#   DEFECT 1 -- ``node_status`` is mapped to ``tb_system_head``, a CONTINUOUS
#   hydraulic head (~7.2-24.0 m, 10,102 unique values), NOT a binary status.
#   It was wrongly thresholded at 0.5 against a ~18 m de-normalized value, so
#   the "true class" was always 1 and accuracy was meaningless. FIX: reclassify
#   ``node_status`` as CONTINUOUS (treated like pressure / level).
#
#   DEFECT 2 -- ``edge_status`` (``P_1531A_status``) is the only GENUINE binary
#   signal, but the pump is on 99.85% of the time (sigma ~ 0.011). Raw accuracy
#   is the wrong metric (always-on scores 0.9985). DECISION: DROP ``edge_status``
#   as a *binary* target for this sprint. It is hollow (no learnable on/off
#   signal in this site's data) and was masking the real modeling problem. It
#   stays an ACTIVE axis (it is in the normalization stats and the model still
#   emits a column for it), but it is handled as a CONTINUOUS axis (residual of
#   its near-constant value) rather than a BCE classification target. With
#   ``node_status`` reclassified and ``edge_status`` dropped, ``BINARY_AXES`` is
#   EMPTY by default this sprint.
#
# The binary INFRASTRUCTURE (BCEWithLogits routing, sigmoid decode, and
# balanced-accuracy / F1 gating) is preserved and fully tested so that a future
# genuine binary axis can be re-enabled by listing it in ``BINARY_AXES`` (loss /
# eval read this set), WITHOUT reintroducing the raw-accuracy or
# missing-sigmoid bugs.
#
# Continuous axes = every active axis NOT in ``BINARY_AXES``. The
# active-axis set is unchanged from Sprint 23 (8 axes); only the *taxonomy*
# (which axis is binary vs continuous) changed, so the cached normalization
# stats (``data/normalization/yilan_2025_train_stats.json``) remain VALID and
# do NOT need regeneration -- node_status / edge_status already carry continuous
# mu/sigma there.

# The full set of canonical axes that are continuous-valued in this site's data
# (everything except a genuine binary status). node_status -> tb_system_head is
# continuous; edge_status -> P_1531A_status is near-constant but handled as
# continuous this sprint (dropped as a binary target).
CONTINUOUS_AXES: frozenset[str] = frozenset(
    {
        "edge_flow",
        "edge_power",
        "edge_pump_speed",
        "edge_status",
        "node_demand",
        "node_level",
        "node_pressure",
        "node_status",
    }
)

# Genuine binary (BCE-classification) axes. EMPTY this sprint (see DEFECT notes
# above). Loss, trainer and evaluation all read this set as the single source
# of truth for binary-vs-continuous routing.
BINARY_AXES: frozenset[str] = frozenset()


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
    "CONTINUOUS_AXES",
    "BINARY_AXES",
]
