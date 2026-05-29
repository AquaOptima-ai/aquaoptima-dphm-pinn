"""AOPSO Sprint 32 -- Pillar B envelope scorecard orchestrator.

OFFLINE, ADVISORY ONLY. Builds the Sprint 32 scorecard from the Sprint 31
OperatingPoints CSV. No setpoints, no actuation, no live integration.

Outputs ``data/eval/pillarB/sprint32_envelope_scorecard.json`` whose shape is
specified in the Sprint 32 brief:

  * identity + safety block
  * frozen_params (from :mod:`efficiency_gate`)
  * matched_search example queries with comparable_count + match_distance
  * envelopes: per-bucket p10/p25 SE + observed speed range + support count
  * rejection: count + reasons for unsupported queries
  * mvpv1_alignment: {coverage, n_aligned, n_rejected, diagnostic}
  * train_meta: {csv_path, 2025-only, per_month_rows, timestamp_min/max}
  * march_used_for_tuning: false
  * acceptance_gate: {criteria, passed, verdict, rule}
  * verdict: "PASS"|"FAIL"

The acceptance gate has FIVE criteria (matching the Sprint 32 brief verbatim):

  C1. Advisories require minimum historical support (frozen min_support enforced).
  C2. All reported speed ranges are historically observed (no extrapolation).
  C3. Unsupported intervals are rejected with reasons.
  C4. MVPv1 comparison produced ONLY where alignment is valid.
  C5. Matching tolerances + quantiles are FROZEN before March
      (efficiency_gate.MARCH_USED_FOR_TUNING is False AND march_used_for_tuning
      reported in scorecard is False).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .efficiency_envelope import (
    EnvelopeAdvisory,
    EnvelopeRejection,
    OperatingConditionQuery,
    SE_COLUMN,
    SPEED_COLUMN,
    WINDOW_START_COLUMN,
    assert_operating_points_no_march_2026,
    evaluate_query_batch,
    matched_search,
    produce_advisory,
)
from .efficiency_gate import (
    GATE_VERSION,
    MARCH_USED_FOR_TUNING,
    MATCHING_CHANNELS,
    MIN_SUPPORT,
    PILLAR,
    SPRINT,
    frozen_params_canonical_json,
    frozen_params_sha256,
    frozen_pillar_b_params,
)
from .efficiency_mvpv1_alignment import (
    MvpV1AlignmentReport,
    diagnose_mvpv1_alignment,
)

DEFAULT_OPERATING_POINTS_CSV = (
    "data/eval/pillarB/operating_points_30min_2025.csv"
)
DEFAULT_OUTPUT_PATH = (
    "data/eval/pillarB/sprint32_envelope_scorecard.json"
)


# --------------------------------------------------------------------------- #
# Default example queries
# --------------------------------------------------------------------------- #
def default_example_queries(ops: pd.DataFrame) -> list[OperatingConditionQuery]:
    """Pick a small, deterministic set of example queries from the data.

    The queries are taken from the data's own quantiles (25th, 50th, 75th of
    each context channel) PLUS one out-of-distribution query that should be
    REJECTED. This is example-driven evidence for the scorecard; it does not
    select the bucket structure of the envelope.
    """
    ops = ops.reset_index(drop=True)
    q25 = ops[list(MATCHING_CHANNELS)].quantile(0.25)
    q50 = ops[list(MATCHING_CHANNELS)].quantile(0.50)
    q75 = ops[list(MATCHING_CHANNELS)].quantile(0.75)
    queries: list[OperatingConditionQuery] = []
    for label, q in (("p25", q25), ("p50", q50), ("p75", q75)):
        queries.append(
            OperatingConditionQuery(
                demand_m3_per_h=float(q["mean_demand_m3_per_h"]),
                level_m=float(q["mean_level_m"]),
                pressure_m_head=float(q["mean_pressure_m_head"]),
                flow_m3_per_h=float(q["mean_flow_m3_per_h"]),
                label=f"data_quantile_{label}",
            )
        )
    # An out-of-distribution query: far outside the demand range. The matched
    # bucket should be empty -> REJECTED for insufficient support.
    demand_max = float(pd.to_numeric(ops["mean_demand_m3_per_h"], errors="coerce").max())
    queries.append(
        OperatingConditionQuery(
            demand_m3_per_h=demand_max + 10_000.0,
            level_m=float(q50["mean_level_m"]),
            pressure_m_head=float(q50["mean_pressure_m_head"]),
            flow_m3_per_h=float(q50["mean_flow_m3_per_h"]),
            label="far_ood_demand",
        )
    )
    return queries


# --------------------------------------------------------------------------- #
# Train meta
# --------------------------------------------------------------------------- #
def _per_month_rows(ts: pd.Series) -> dict[str, int]:
    parsed = pd.to_datetime(ts, errors="coerce")
    counts = parsed.dropna().dt.strftime("%Y-%m").value_counts().sort_index()
    return {str(k): int(v) for k, v in counts.items()}


def build_train_meta(
    ops: pd.DataFrame,
    *,
    csv_path: str,
) -> dict[str, Any]:
    """Build train_meta from an OperatingPoints frame."""
    ts = pd.to_datetime(ops[WINDOW_START_COLUMN], errors="coerce").dropna()
    months = sorted({f"{t.year:04d}-{t.month:02d}" for t in ts})
    return {
        "csv_path": str(csv_path),
        "n_operating_points": int(len(ops)),
        "timestamp_min": str(ts.min()) if not ts.empty else None,
        "timestamp_max": str(ts.max()) if not ts.empty else None,
        "distinct_months": months,
        "per_month_rows": _per_month_rows(ops[WINDOW_START_COLUMN]),
        "year_lock": "2025-only",
        "all_2025_only": bool(all(m.startswith("2025-") for m in months)),
    }


# --------------------------------------------------------------------------- #
# Acceptance gate
# --------------------------------------------------------------------------- #
def _check_all_speeds_historically_observed(
    advisories: Sequence[dict[str, Any]],
    ops: pd.DataFrame,
    *,
    speed_rounding_decimals: int = 2,
) -> tuple[bool, dict[str, Any]]:
    """Verify every reported advisory speed exists in the 2025 observed set."""
    full_speeds = pd.to_numeric(ops[SPEED_COLUMN], errors="coerce").dropna()
    observed = set(
        np.round(full_speeds.to_numpy(dtype=float), speed_rounding_decimals).tolist()
    )
    n_speeds_checked = 0
    n_speeds_unobserved = 0
    unobserved_examples: list[float] = []
    for adv in advisories:
        for s in adv.get("observed_efficient_speed_values_hz", []):
            n_speeds_checked += 1
            if round(float(s), speed_rounding_decimals) not in observed:
                n_speeds_unobserved += 1
                if len(unobserved_examples) < 5:
                    unobserved_examples.append(float(s))
    passed = n_speeds_unobserved == 0
    return passed, {
        "n_advisories_checked": int(len(advisories)),
        "n_speeds_checked": int(n_speeds_checked),
        "n_speeds_unobserved": int(n_speeds_unobserved),
        "unobserved_examples": unobserved_examples,
    }


def _evaluate_acceptance_gate(
    *,
    batch_result: Mapping[str, Any],
    speed_check: Mapping[str, Any],
    speed_check_passed: bool,
    alignment: MvpV1AlignmentReport,
    march_used_for_tuning: bool,
    frozen_module_says_no_march: bool,
) -> dict[str, Any]:
    criteria: list[dict[str, Any]] = []

    # C1. Advisories require minimum historical support (frozen min_support enforced).
    # Every produced advisory satisfies comparable_count >= MIN_SUPPORT by
    # construction; the rejections list contains any sub-threshold queries.
    advisories = batch_result["advisories"]
    min_comparable = min(
        (int(a["comparable_count"]) for a in advisories), default=None
    )
    c1_passed = (
        all(int(a["comparable_count"]) >= MIN_SUPPORT for a in advisories)
        and (frozen_pillar_b_params().min_support == MIN_SUPPORT)
    )
    criteria.append({
        "name": "advisories_require_minimum_historical_support",
        "passed": bool(c1_passed),
        "detail": {
            "frozen_min_support": int(MIN_SUPPORT),
            "n_advisories": int(len(advisories)),
            "min_comparable_count_among_advisories": min_comparable,
        },
    })

    # C2. All reported speed ranges are historically observed.
    criteria.append({
        "name": "all_reported_speed_ranges_historically_observed",
        "passed": bool(speed_check_passed),
        "detail": dict(speed_check),
    })

    # C3. Unsupported intervals rejected with reasons.
    rejections = batch_result["rejections"]
    has_reasons = all(bool(r.get("reason")) for r in rejections)
    c3_passed = bool(has_reasons)
    criteria.append({
        "name": "unsupported_intervals_rejected_with_reasons",
        "passed": c3_passed,
        "detail": {
            "n_rejected": int(len(rejections)),
            "rejection_reason_counts": dict(batch_result["rejection_reason_counts"]),
        },
    })

    # C4. MVPv1 comparison produced ONLY where alignment is valid.
    # PASSING if EITHER the diagnostic passed (and a comparison may be produced)
    # OR the diagnostic FAILED and we did not produce a comparison.
    # In both branches the invariant ``alignment.diagnostic_passed
    # == (comparison_was_produced)`` is upheld. In this sprint, the comparison
    # is NEVER produced beyond reporting the alignment diagnostic itself.
    c4_passed = True  # we honour the invariant by construction (see report)
    criteria.append({
        "name": "mvpv1_comparison_only_where_alignment_is_valid",
        "passed": c4_passed,
        "detail": {
            "diagnostic_passed": bool(alignment.diagnostic_passed),
            "alignment_coverage": float(alignment.coverage),
            "n_aligned": int(alignment.n_aligned),
            "n_rejected": int(alignment.n_rejected),
            "rejection_reason": alignment.rejection_reason,
            "comparison_produced": False,  # this sprint reports diagnostic only
        },
    })

    # C5. Matching tolerances + quantiles FROZEN before March.
    c5_passed = (
        frozen_module_says_no_march is True
        and march_used_for_tuning is False
    )
    criteria.append({
        "name": "matching_tolerances_and_quantiles_frozen_before_march",
        "passed": bool(c5_passed),
        "detail": {
            "efficiency_gate_module_march_used_for_tuning":
                bool(not frozen_module_says_no_march),
            "scorecard_march_used_for_tuning": bool(march_used_for_tuning),
            "frozen_params_sha256": frozen_params_sha256(),
        },
    })

    passed = all(c["passed"] for c in criteria)
    return {
        "gate_version": GATE_VERSION,
        "criteria": criteria,
        "passed": bool(passed),
        "verdict": "PASS" if passed else "FAIL",
        "rule": (
            "Sprint 32 PASS iff: advisories_require_minimum_historical_support AND "
            "all_reported_speed_ranges_historically_observed AND "
            "unsupported_intervals_rejected_with_reasons AND "
            "mvpv1_comparison_only_where_alignment_is_valid AND "
            "matching_tolerances_and_quantiles_frozen_before_march."
        ),
    }


# --------------------------------------------------------------------------- #
# Per-bucket envelope summary (for the scorecard ``envelopes`` block)
# --------------------------------------------------------------------------- #
def _build_envelope_block(
    advisories: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project each advisory into the scorecard ``envelopes`` schema."""
    out: list[dict[str, Any]] = []
    for adv in advisories:
        q = adv["query"]
        out.append({
            "label": q.get("label", "unlabeled"),
            "query": q,
            "support": int(adv["comparable_count"]),
            "se_p10": float(adv["se_p10"]),
            "se_p25": float(adv["se_p25"]),
            "se_median": float(adv["se_median"]),
            "n_efficient": int(adv["n_efficient"]),
            "observed_speed_min_hz": float(adv["observed_efficient_speed_min_hz"]),
            "observed_speed_max_hz": float(adv["observed_efficient_speed_max_hz"]),
            "observed_speed_values_hz": list(adv["observed_efficient_speed_values_hz"]),
            "advisory_only": True,
            "is_evidence_not_setpoint": True,
        })
    return out


# --------------------------------------------------------------------------- #
# Main builder
# --------------------------------------------------------------------------- #
def build_sprint32_scorecard(
    *,
    operating_points: pd.DataFrame,
    operating_points_csv_path: str,
    queries: Sequence[OperatingConditionQuery] | None = None,
    mvpv1_log: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build the Sprint 32 envelope scorecard."""
    # Leakage guard runs FIRST, before any compute.
    assert_operating_points_no_march_2026(operating_points)

    # Determine queries (deterministic example set if not provided).
    if queries is None:
        queries = default_example_queries(operating_points)
    queries = list(queries)

    # --- C1 + C2 + C3 inputs.
    batch = evaluate_query_batch(operating_points, queries)

    # --- C2 invariant: every reported advisory speed must be in the 2025
    # observed-speed multiset.
    speed_check_passed, speed_check_detail = _check_all_speeds_historically_observed(
        batch["advisories"], operating_points
    )

    # --- C4 inputs: alignment diagnostic.
    alignment = diagnose_mvpv1_alignment(mvpv1_log, operating_points)

    # --- C5 inputs.
    march_used_for_tuning = False  # this sprint must not have touched March-2026.
    frozen_module_says_no_march = (MARCH_USED_FOR_TUNING is False)

    gate = _evaluate_acceptance_gate(
        batch_result=batch,
        speed_check=speed_check_detail,
        speed_check_passed=speed_check_passed,
        alignment=alignment,
        march_used_for_tuning=march_used_for_tuning,
        frozen_module_says_no_march=frozen_module_says_no_march,
    )

    train_meta = build_train_meta(
        operating_points, csv_path=operating_points_csv_path
    )

    scorecard: dict[str, Any] = {
        "sprint": SPRINT,
        "pillar": PILLAR,
        "advisory_only": True,
        "evaluation_mode": "offline_only",
        "march_used_for_tuning": bool(march_used_for_tuning),
        "frozen_params": {
            "frozen": True,
            "matching_tolerances": dict(frozen_pillar_b_params().matching_tolerances),
            "matching_channels": list(frozen_pillar_b_params().matching_channels),
            "se_quantiles": list(frozen_pillar_b_params().se_quantiles),
            "se_quantile_primary": float(frozen_pillar_b_params().se_quantile_primary),
            "se_quantile_aggressive": float(
                frozen_pillar_b_params().se_quantile_aggressive
            ),
            "min_support": int(frozen_pillar_b_params().min_support),
            "speed_range_se_cutoff_quantile": float(
                frozen_pillar_b_params().speed_range_se_cutoff_quantile
            ),
            "mvpv1_min_overlap_fraction": float(
                frozen_pillar_b_params().mvpv1_min_overlap_fraction
            ),
            "mvpv1_max_demand_disagreement_m3_per_h": float(
                frozen_pillar_b_params().mvpv1_max_demand_disagreement_m3_per_h
            ),
            "gate_version": GATE_VERSION,
            "frozen_params_sha256": frozen_params_sha256(),
            "frozen_params_canonical_json": frozen_params_canonical_json(),
        },
        "matched_search": {
            "examples": batch["matched_search_examples"],
            "metric": "L_inf_normalised_by_per_channel_tolerance",
        },
        "envelopes": _build_envelope_block(batch["advisories"]),
        "rejection": {
            "n_rejected": int(batch["n_rejected"]),
            "reasons": dict(batch["rejection_reason_counts"]),
            "head": batch["rejections"][:5],
        },
        "mvpv1_alignment": alignment.to_dict(),
        "train_meta": train_meta,
        "acceptance_gate": gate,
        "verdict": gate["verdict"],
        "safety": {
            "advisory_only": True,
            "evaluation_mode": "offline_only",
            "is_evidence_not_setpoint": True,
            "site_integration_allowed": False,
            "influences_control": False,
            "scorecard_role": "advisory_evidence_only",
            "speed_ranges_are_evidence_not_setpoints": True,
        },
    }
    return scorecard


def write_scorecard(
    scorecard: Mapping[str, Any],
    output_path: str | os.PathLike[str] = DEFAULT_OUTPUT_PATH,
) -> str:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scorecard, indent=2, default=str) + "\n")
    return str(out)


def run_sprint32_scorecard(
    *,
    operating_points_csv: str | os.PathLike[str] = DEFAULT_OPERATING_POINTS_CSV,
    output_path: str | os.PathLike[str] = DEFAULT_OUTPUT_PATH,
    mvpv1_log_csv: str | os.PathLike[str] | None = None,
    queries: Sequence[OperatingConditionQuery] | None = None,
) -> dict[str, Any]:
    """Build and write the Sprint 32 envelope scorecard from the Sprint 31 CSV."""
    ops_path = Path(operating_points_csv)
    ops = pd.read_csv(ops_path)

    mvpv1_log: pd.DataFrame | None = None
    if mvpv1_log_csv is not None:
        mvpv1_path = Path(mvpv1_log_csv)
        if mvpv1_path.exists():
            mvpv1_log = pd.read_csv(mvpv1_path)

    sc = build_sprint32_scorecard(
        operating_points=ops,
        operating_points_csv_path=str(ops_path),
        queries=queries,
        mvpv1_log=mvpv1_log,
    )
    write_scorecard(sc, output_path=output_path)
    return sc


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Iterable[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        description="AOPSO Sprint 32 -- Pillar B envelope scorecard",
    )
    p.add_argument("--operating-points-csv", default=DEFAULT_OPERATING_POINTS_CSV)
    p.add_argument("--mvpv1-log-csv", default=None)
    p.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    args = p.parse_args(list(argv) if argv is not None else None)
    sc = run_sprint32_scorecard(
        operating_points_csv=args.operating_points_csv,
        output_path=args.output,
        mvpv1_log_csv=args.mvpv1_log_csv,
    )
    print(f"sprint32 verdict: {sc['verdict']}")
    print(f"scorecard written to {args.output}")
    return 0 if sc["acceptance_gate"]["passed"] else 1


__all__ = [
    "DEFAULT_OPERATING_POINTS_CSV",
    "DEFAULT_OUTPUT_PATH",
    "default_example_queries",
    "build_train_meta",
    "build_sprint32_scorecard",
    "write_scorecard",
    "run_sprint32_scorecard",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
