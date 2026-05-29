"""Sprint 27 schema / unit validators + governance-aware scorecard helpers.

Pure, dependency-light validators for the offline advisory product:

* :func:`validate_axis_taxonomy` -- proves the active axis set is exactly the eight
  expected axes (the masked ``edge_valve_position`` is excluded), every axis has a unit
  string in ``AXIS_UNITS``, and every axis maps to a real backing column in
  ``CANONICAL_AXIS_TO_COLUMN`` (the masked axis maps to ``None``).
* :func:`validate_normalization_coverage` -- reads the cached normalization stats JSON
  and asserts coverage matches the active axes exactly (no missing, no extra), each with
  finite ``mu`` / ``sigma`` and ``sigma > 0``.

Plus two scorecard-wiring helpers:

* :func:`build_governance_block` -- composes a single ``safety.governance`` block from
  (1) the March-2026 leakage guard over the split manifest's train/val keys, (2) the
  modeling-source import / connector scan, (3) the axis taxonomy validator, and (4) the
  normalization coverage validator. ``governance_status`` is ``"PASS"`` iff every guard
  is ok.
* :func:`apply_governance_to_verdict` -- on a governance FAIL, forces an acceptance gate
  to FAIL and appends a ``governance_guardrails`` criterion. On governance PASS the gate
  is returned unchanged.

Safety: no IO unless a path is passed; never imports ``aquaoptima.edge`` or any
write-capable connector; ``aquaoptima_contracts`` is read-only.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..dataio.yilan_axis_map import CANONICAL_AXIS_TO_COLUMN
from .governance import (
    GovernanceScanResult,
    HoldoutIsolationResult,
    assert_holdout_isolated,
    scan_modeling_source_for_governance_violations,
)
from .label_schema import (
    AXIS_UNITS,
    MASKED_AXIS,
    active_axes_ordered,
    axis_kind,
)

# The eight axes that MUST be active at the Yilan site (masked axis excluded).
EXPECTED_ACTIVE_AXES: tuple[str, ...] = (
    "edge_flow",
    "edge_power",
    "edge_pump_speed",
    "edge_status",
    "node_demand",
    "node_level",
    "node_pressure",
    "node_status",
)


# --------------------------------------------------------------------------- #
# Axis taxonomy validator
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AxisTaxonomyResult:
    ok: bool
    errors: tuple[str, ...] = ()
    expected_axes: tuple[str, ...] = ()
    active_axes: tuple[str, ...] = ()
    units: Mapping[str, str] = field(default_factory=dict)
    masked_axis: str = MASKED_AXIS

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "expected_axes": list(self.expected_axes),
            "active_axes": list(self.active_axes),
            "units": dict(self.units),
            "masked_axis": self.masked_axis,
        }


def validate_axis_taxonomy(
    *,
    expected_axes: Sequence[str] = EXPECTED_ACTIVE_AXES,
    units: Mapping[str, str] | None = None,
    axis_to_column: Mapping[str, str | None] | None = None,
    masked_axis: str = MASKED_AXIS,
) -> AxisTaxonomyResult:
    """Validate the active-axis set, per-axis unit, and column backing.

    All inputs default to the real label-schema / yilan-axis-map taxonomy; tests
    monkey-patch ``units`` / ``axis_to_column`` to exercise failure paths without
    mutating the real modules.
    """
    units_map = AXIS_UNITS if units is None else units
    column_map = CANONICAL_AXIS_TO_COLUMN if axis_to_column is None else axis_to_column

    errors: list[str] = []
    active = tuple(active_axes_ordered())
    expected = tuple(expected_axes)

    if set(active) != set(expected):
        missing = sorted(set(expected) - set(active))
        extra = sorted(set(active) - set(expected))
        if missing:
            errors.append(f"active axes missing expected: {missing}")
        if extra:
            errors.append(f"active axes contains unexpected: {extra}")

    if masked_axis in active:
        errors.append(f"masked axis {masked_axis!r} must not appear in active set")

    for axis in active:
        unit = units_map.get(axis)
        if not isinstance(unit, str) or not unit:
            errors.append(f"axis {axis!r} has no unit in AXIS_UNITS")
        try:
            kind = axis_kind(axis)
        except KeyError:
            errors.append(f"axis {axis!r} has no taxonomy kind (continuous/binary)")
            kind = None
        if kind == "masked":
            errors.append(f"axis {axis!r} taxonomy reports 'masked' but is active")
        if axis not in column_map:
            errors.append(f"axis {axis!r} missing from CANONICAL_AXIS_TO_COLUMN")
        else:
            col = column_map[axis]
            if col is None or not isinstance(col, str) or not col:
                errors.append(
                    f"active axis {axis!r} maps to no backing column ({col!r})"
                )

    if masked_axis in column_map and column_map[masked_axis] is not None:
        errors.append(
            f"masked axis {masked_axis!r} must map to None, got {column_map[masked_axis]!r}"
        )

    return AxisTaxonomyResult(
        ok=not errors,
        errors=tuple(errors),
        expected_axes=expected,
        active_axes=active,
        units={a: units_map.get(a, "") for a in active},
        masked_axis=masked_axis,
    )


# --------------------------------------------------------------------------- #
# Normalization-coverage validator
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NormalizationCoverageResult:
    ok: bool
    errors: tuple[str, ...] = ()
    expected_axes: tuple[str, ...] = ()
    covered_axes: tuple[str, ...] = ()
    missing_axes: tuple[str, ...] = ()
    extra_axes: tuple[str, ...] = ()
    stats_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "expected_axes": list(self.expected_axes),
            "covered_axes": list(self.covered_axes),
            "missing_axes": list(self.missing_axes),
            "extra_axes": list(self.extra_axes),
            "stats_path": self.stats_path,
        }


def _coerce_stats_payload(
    stats: Mapping[str, Any] | str | Path,
) -> tuple[Mapping[str, Any], str | None]:
    if isinstance(stats, (str, Path)):
        path = Path(stats)
        return json.loads(path.read_text()), str(path)
    return stats, None


def validate_normalization_coverage(
    stats: Mapping[str, Any] | str | Path,
    *,
    expected_axes: Sequence[str] = EXPECTED_ACTIVE_AXES,
) -> NormalizationCoverageResult:
    """Validate that a normalization stats payload covers exactly the expected axes.

    Accepts either an in-memory mapping or a path to the JSON file. Each axis must have
    finite ``mu`` and ``sigma``, with ``sigma > 0``. The payload's own ``active_axes``
    list (if present) must also match the stats keys -- a mismatch is itself a bug.
    """
    payload, stats_path = _coerce_stats_payload(stats)
    errors: list[str] = []

    stats_block = payload.get("stats")
    if not isinstance(stats_block, Mapping):
        return NormalizationCoverageResult(
            ok=False,
            errors=("normalization payload missing 'stats' mapping",),
            expected_axes=tuple(expected_axes),
            stats_path=stats_path,
        )

    covered = tuple(sorted(stats_block.keys()))
    expected = tuple(expected_axes)
    missing = tuple(sorted(set(expected) - set(covered)))
    extra = tuple(sorted(set(covered) - set(expected)))
    if missing:
        errors.append(f"normalization missing axes: {list(missing)}")
    if extra:
        errors.append(f"normalization has unexpected axes: {list(extra)}")

    declared = payload.get("active_axes")
    if isinstance(declared, list) and set(declared) != set(covered):
        errors.append(
            f"payload 'active_axes' {sorted(declared)} disagrees with stats keys {list(covered)}"
        )

    for axis in covered:
        entry = stats_block.get(axis)
        if not isinstance(entry, Mapping):
            errors.append(f"axis {axis!r} normalization entry is not a mapping")
            continue
        mu = entry.get("mu")
        sigma = entry.get("sigma")
        if not isinstance(mu, (int, float)) or not math.isfinite(float(mu)):
            errors.append(f"axis {axis!r} mu is not finite: {mu!r}")
        if not isinstance(sigma, (int, float)) or not math.isfinite(float(sigma)):
            errors.append(f"axis {axis!r} sigma is not finite: {sigma!r}")
        elif float(sigma) <= 0.0:
            errors.append(f"axis {axis!r} sigma must be > 0, got {sigma!r}")

    return NormalizationCoverageResult(
        ok=not errors,
        errors=tuple(errors),
        expected_axes=expected,
        covered_axes=covered,
        missing_axes=missing,
        extra_axes=extra,
        stats_path=stats_path,
    )


# --------------------------------------------------------------------------- #
# Scorecard wiring helpers
# --------------------------------------------------------------------------- #
def _collect_train_val_keys(split_manifest: Mapping[str, Any]) -> list[str]:
    """Collect every train/val timestamp/date string we can use as a leakage key."""
    keys: list[str] = []
    splits = split_manifest.get("splits", {}) if isinstance(split_manifest, Mapping) else {}
    for split_name in ("train", "val"):
        split = splits.get(split_name, {})
        if not isinstance(split, Mapping):
            continue
        days = split.get("days")
        if isinstance(days, list):
            keys.extend(str(d) for d in days)
        date_range = split.get("date_range", {})
        if isinstance(date_range, Mapping):
            for bound in (date_range.get("start"), date_range.get("end")):
                if bound:
                    keys.append(str(bound))
    return keys


def _load_split_manifest(
    split_manifest: Mapping[str, Any] | str | Path,
) -> Mapping[str, Any]:
    if isinstance(split_manifest, (str, Path)):
        return json.loads(Path(split_manifest).read_text())
    return split_manifest


def build_governance_block(
    *,
    split_manifest: Mapping[str, Any] | str | Path,
    modeling_roots: Sequence[Path | str],
    normalization_stats: Mapping[str, Any] | str | Path,
    expected_axes: Sequence[str] = EXPECTED_ACTIVE_AXES,
) -> dict[str, Any]:
    """Compose the ``safety.governance`` block for the scorecard.

    Combines the four guards into a single audit dict and computes
    ``governance_status``: ``"PASS"`` iff every guard is ok, else ``"FAIL"``.
    """
    manifest = _load_split_manifest(split_manifest)
    train_val_keys = _collect_train_val_keys(manifest)

    holdout: HoldoutIsolationResult = assert_holdout_isolated(train_val_keys)
    scan: GovernanceScanResult = scan_modeling_source_for_governance_violations(
        modeling_roots
    )
    taxonomy = validate_axis_taxonomy(expected_axes=expected_axes)
    coverage = validate_normalization_coverage(
        normalization_stats, expected_axes=expected_axes
    )

    governance_ok = (
        holdout.isolated and scan.clean and taxonomy.ok and coverage.ok
    )

    return {
        "governance_status": "PASS" if governance_ok else "FAIL",
        "holdout_isolation": {
            "isolated": holdout.isolated,
            "leaked_keys": list(holdout.leaked_keys),
            "holdout_prefix": holdout.holdout_prefix,
            "n_train_val_checked": holdout.n_train_val_checked,
        },
        "import_connector_scan": {
            "clean": scan.clean,
            "safety_status": scan.safety_status,
            "files_scanned": scan.files_scanned,
            "violations": list(scan.violations),
            "roots": [str(r) for r in modeling_roots],
        },
        "axis_taxonomy": taxonomy.to_dict(),
        "normalization_coverage": coverage.to_dict(),
    }


def apply_governance_to_verdict(
    acceptance_gate: Mapping[str, Any],
    governance_block: Mapping[str, Any],
) -> dict[str, Any]:
    """Force the acceptance verdict to FAIL when ``governance_status == 'FAIL'``.

    Returns a SHALLOW copy of the gate so the caller can drop it back into the
    scorecard. On governance PASS the gate is returned unchanged (deep-equal). On
    governance FAIL the verdict is forced to ``"FAIL"``, ``passed`` to ``False``,
    and a ``governance_guardrails`` criterion is appended to ``criteria`` with the
    failing-guard details so the reason is explicit in the artifact.
    """
    gate = dict(acceptance_gate)
    status = governance_block.get("governance_status", "PASS")
    if status == "PASS":
        return gate

    failing = _summarize_failing_guards(governance_block)
    criterion = {
        "name": "governance_guardrails",
        "passed": False,
        "detail": {
            "governance_status": status,
            "failing_guards": failing,
        },
    }
    criteria = list(gate.get("criteria", []))
    criteria.append(criterion)
    gate["criteria"] = criteria
    gate["verdict"] = "FAIL"
    gate["passed"] = False
    gate["governance_override"] = True
    return gate


def _summarize_failing_guards(governance_block: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a compact list of which sub-guards failed (for the criterion detail)."""
    failing: list[dict[str, Any]] = []
    holdout = governance_block.get("holdout_isolation", {})
    if not holdout.get("isolated", True):
        failing.append(
            {
                "guard": "holdout_isolation",
                "leaked_keys": list(holdout.get("leaked_keys", [])),
            }
        )
    scan = governance_block.get("import_connector_scan", {})
    if not scan.get("clean", True):
        failing.append(
            {
                "guard": "import_connector_scan",
                "violations": list(scan.get("violations", [])),
            }
        )
    taxonomy = governance_block.get("axis_taxonomy", {})
    if not taxonomy.get("ok", True):
        failing.append(
            {"guard": "axis_taxonomy", "errors": list(taxonomy.get("errors", []))}
        )
    coverage = governance_block.get("normalization_coverage", {})
    if not coverage.get("ok", True):
        failing.append(
            {
                "guard": "normalization_coverage",
                "errors": list(coverage.get("errors", [])),
            }
        )
    return failing


# Default modeling roots scanned by the Sprint 27 governance block. Kept here as the
# single source of truth so the scorecard and the CLI agree.
DEFAULT_MODELING_ROOTS: tuple[Path, ...] = (
    Path("src/aquaoptima/advisory"),
    Path("src/aquaoptima/training"),
    Path("src/aquaoptima/models"),
    Path("src/aquaoptima/dataio"),
)


__all__ = [
    "EXPECTED_ACTIVE_AXES",
    "AxisTaxonomyResult",
    "NormalizationCoverageResult",
    "validate_axis_taxonomy",
    "validate_normalization_coverage",
    "build_governance_block",
    "apply_governance_to_verdict",
    "DEFAULT_MODELING_ROOTS",
]
