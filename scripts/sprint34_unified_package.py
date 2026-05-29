#!/usr/bin/env python3
"""AOPSO Sprint 34 -- Unified A+B offline evidence package runner.

This script writes the entire Sprint 34 unified evidence bundle to
``data/eval/unified/``:

  * sprint34_unified_scorecard.json  -- both pillars' verdicts + packaging gate
  * sprint34_dashboard.html          -- static read-only summary (no controls)
  * sprint34_executive_report.md     -- plant-manager executive report
  * sprint34_ml_audit_appendix.md    -- full methodology / verdicts / cannot-claim
  * sprint34_plant_manager_summary.md -- one-page summary
  * health_event_export.{csv,json}   -- Pillar A injected-fault evidence
  * efficiency_advisory_export.{csv,json} -- Pillar B counterfactual evidence
  * sprint34_artifact_manifest.json  -- ModelArtifactRecord-shaped manifest

OFFLINE ONLY. This script never opens a network socket, never trains, never
exports an ONNX model, and never integrates with any site. It reads two
pre-existing locked-March-2026 holdout scorecards (Sprint 30b for Pillar A,
Sprint 33 for Pillar B) and assembles a unified, honest package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aquaoptima.advisory.sprint34_unified_package import (  # noqa: E402
    DEFAULT_PILLAR_A_SCORECARD,
    DEFAULT_PILLAR_B_SCORECARD,
    DEFAULT_UNIFIED_DIR,
    build_unified_package,
    write_unified_package,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=_REPO_ROOT,
        help="Repo root (defaults to this script's parent).",
    )
    parser.add_argument(
        "--pillar-a-scorecard", type=Path, default=_REPO_ROOT / DEFAULT_PILLAR_A_SCORECARD,
        help="Path to the Pillar A locked-March holdout scorecard JSON.",
    )
    parser.add_argument(
        "--pillar-b-scorecard", type=Path, default=_REPO_ROOT / DEFAULT_PILLAR_B_SCORECARD,
        help="Path to the Pillar B locked-March holdout scorecard JSON.",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=_REPO_ROOT / DEFAULT_UNIFIED_DIR,
        help="Output directory for the unified package.",
    )
    parser.add_argument(
        "--generated-at", type=str, default=None,
        help="Override the generated_at_utc timestamp (default: now UTC). "
             "Useful for deterministic test runs.",
    )
    args = parser.parse_args(argv)

    pkg = build_unified_package(
        repo_root=args.repo_root,
        pillar_a_scorecard_path=args.pillar_a_scorecard,
        pillar_b_scorecard_path=args.pillar_b_scorecard,
        generated_at_utc=args.generated_at,
    )
    paths = write_unified_package(pkg, out_dir=args.out_dir)

    summary = {
        "pillar_a_verdict": pkg.scorecard["pillar_a_verdict"],
        "pillar_b_verdict": pkg.scorecard["pillar_b_verdict"],
        "product_status": pkg.scorecard["product_status"],
        "packaging_gate_verdict": pkg.packaging_gate["verdict"],
        "packaging_gate_passed": pkg.packaging_gate["passed"],
        "criteria": [
            {"name": c["name"], "passed": c["passed"]} for c in pkg.packaging_gate["criteria"]
        ],
        "governance_clean": bool(pkg.governance.clean),
        "n_files_written": len(paths),
        "out_dir": str(args.out_dir),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
